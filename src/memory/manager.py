"""MemoryManager — typed, async-safe memory for one research session.

Routing
───────
  EPHEMERAL     → InMemoryBackend (no disk I/O, cleared on process exit)
  SEARCH_RESULT │
  PAGE_CACHE    → shared DiskBackend (~/.cache/deepresearch/)
  INTERMEDIATE  │
  REPORT        → session DiskBackend (~/.cache/deepresearch/sessions/{id}/)
  SESSION       ╯

All DiskBackend calls are offloaded to a thread pool via asyncio.to_thread()
so that JSON file I/O never blocks the event loop.

Concurrent URL fetches
──────────────────────
get_or_fetch_page(url, fetch_fn) uses a per-URL asyncio.Lock (double-checked
locking) to prevent multiple researchers from fetching the same URL
simultaneously.  The first coroutine fetches and caches; later arrivals block
on the lock, then find the cache populated and return immediately.

Session directory
─────────────────
Session-scoped data (INTERMEDIATE, REPORT, SESSION) lands in
  ~/.cache/deepresearch/sessions/{session_id}/
This keeps the user-facing workdir/ clean (only final artifacts live there).

Query normalization
───────────────────
search_cache_key(query) lowercases and collapses whitespace so that minor
surface variations of the same query share a single cache entry.

Module-level registry
─────────────────────
get_manager(session_id, workdir) returns the same MemoryManager instance
throughout a run without needing to pass it through LangGraph state.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, Optional

from src.memory.backends.disk import DiskBackend
from src.memory.backends.in_memory import InMemoryBackend
from src.memory.types import DEFAULT_TTL, DataType, MemoryRecord

_SHARED_TYPES = {DataType.SEARCH_RESULT, DataType.PAGE_CACHE}
_SESSION_TYPES = {DataType.INTERMEDIATE, DataType.REPORT, DataType.SESSION}


def search_cache_key(query: str) -> str:
    """Normalize a search query to improve cache hit rate.

    Lowercases and collapses whitespace so that minor surface variations
    ("LangGraph agents" vs "langgraph  agents") share one cache entry.
    """
    return " ".join(query.lower().split())


class MemoryManager:
    """Typed, async-safe memory manager for a single research session."""

    def __init__(self, session_id: str, workdir: str = "") -> None:
        self.session_id = session_id

        shared_root = os.environ.get("DEEPRESEARCH_CACHE_DIR") or os.path.join(
            os.path.expanduser("~"), ".cache", "deepresearch"
        )
        # Session data always goes under the shared cache root, never in workdir,
        # so the user-facing output directory stays clean.
        session_dir = os.path.join(shared_root, "sessions", session_id)

        self._ephemeral = InMemoryBackend()
        self._shared = DiskBackend(shared_root)
        self._session = DiskBackend(session_dir)

        # Per-URL asyncio.Lock for concurrent fetch coalescing
        self._url_locks: Dict[str, asyncio.Lock] = {}

        # Write session provenance synchronously in __init__ (one small file, acceptable)
        self._session.put(
            MemoryRecord(
                data_type=DataType.SESSION,
                key="metadata",
                value={
                    "session_id": session_id,
                    "workdir": workdir,
                    "started_at": time.time(),
                },
            )
        )

    # ── Core async API ────────────────────────────────────────────────────────

    async def get(self, data_type: DataType, key: str) -> Optional[Any]:
        """Return the cached value, or None on miss or expiry."""
        if data_type == DataType.EPHEMERAL:
            return self._ephemeral.get(self._scoped(key))
        backend = self._shared if data_type in _SHARED_TYPES else self._session
        return await asyncio.to_thread(backend.get, data_type, key)

    async def put(self, data_type: DataType, key: str, value: Any) -> None:
        """Persist a value. Write errors are silently ignored."""
        record = MemoryRecord(
            data_type=data_type,
            key=key,
            value=value,
            ttl=DEFAULT_TTL.get(data_type),
        )
        if data_type == DataType.EPHEMERAL:
            record.key = self._scoped(key)
            self._ephemeral.put(record)
            return
        backend = self._shared if data_type in _SHARED_TYPES else self._session
        await asyncio.to_thread(backend.put, record)

    # ── High-level helper ─────────────────────────────────────────────────────

    async def get_or_fetch_page(
        self,
        url: str,
        fetch_fn: Callable[[str], Awaitable[Optional[dict]]],
    ) -> Optional[dict]:
        """Return a cached page dict or call fetch_fn, coalescing concurrent requests.

        Uses double-checked locking: if two coroutines arrive with a cache miss
        for the same URL, the second waits while the first fetches, then reads
        the result from cache instead of issuing a duplicate network request.

        fetch_fn must return a dict with keys {url, title, content} or None.
        """
        cached = await self.get(DataType.PAGE_CACHE, url)
        if cached is not None:
            return cached

        lock = self._url_locks.setdefault(url, asyncio.Lock())
        async with lock:
            # Re-check: another coroutine may have populated the cache while we waited
            cached = await self.get(DataType.PAGE_CACHE, url)
            if cached is not None:
                return cached
            page = await fetch_fn(url)
            if page is not None:
                await self.put(DataType.PAGE_CACHE, url, page)
            return page

    # ── Provenance ────────────────────────────────────────────────────────────

    def update_metadata(self, **kwargs: Any) -> None:
        existing = self._session.get(DataType.SESSION, "metadata") or {}
        self._session.put(
            MemoryRecord(
                data_type=DataType.SESSION,
                key="metadata",
                value={**existing, **kwargs},
            )
        )

    def summary(self) -> Dict[str, Any]:
        return self._session.get(DataType.SESSION, "metadata") or {}

    def _scoped(self, key: str) -> str:
        return f"{self.session_id}:{key}"


# ── Module-level registry ─────────────────────────────────────────────────────

_registry: Dict[str, MemoryManager] = {}


def get_manager(session_id: str, workdir: str = "") -> MemoryManager:
    """Return the MemoryManager for this session, creating it on first call."""
    if session_id not in _registry:
        _registry[session_id] = MemoryManager(session_id, workdir)
    return _registry[session_id]
