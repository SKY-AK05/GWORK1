"""Disk-based cache using JSON files.

Files live at  base_dir/{data_type}/{sha256(key)[:24]}.json
and contain the record metadata alongside the serialized value.
Write failures are silently swallowed — the cache is best-effort.

Size management
───────────────
Each DataType directory has a configurable cap (MAX_ENTRIES).  When a put()
would exceed the cap, the oldest files (by mtime) are deleted first.  Eviction
happens synchronously inside put() because this module is called from a thread
pool (via asyncio.to_thread in MemoryManager), so it is safe to block.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from src.memory.types import DataType, MemoryRecord

# Maximum number of cache files kept per DataType directory.
# Oldest by mtime are evicted when the limit is reached.
MAX_ENTRIES: dict[DataType, int] = {
    DataType.EPHEMERAL: 0,          # never hits disk
    DataType.SEARCH_RESULT: 500,
    DataType.PAGE_CACHE: 200,
    DataType.INTERMEDIATE: 2000,
    DataType.REPORT: 2000,
    DataType.SESSION: 2000,
}


class DiskBackend:
    def __init__(self, base_dir: str) -> None:
        self._base = Path(base_dir)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _path(self, data_type: DataType, key: str) -> Path:
        hashed = hashlib.sha256(key.encode()).hexdigest()[:24]
        dir_path = self._base / data_type.value
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{hashed}.json"

    def _evict_oldest(self, data_type: DataType) -> None:
        """Delete oldest files (by mtime) if the directory is over its cap."""
        cap = MAX_ENTRIES.get(data_type, 0)
        if cap <= 0:
            return
        dir_path = self._base / data_type.value
        if not dir_path.exists():
            return
        files = sorted(dir_path.glob("*.json"), key=lambda p: p.stat().st_mtime)
        excess = len(files) - cap
        if excess <= 0:
            return
        for f in files[:excess]:
            f.unlink(missing_ok=True)

    # ── Public API (sync — called via asyncio.to_thread in MemoryManager) ────

    def get(self, data_type: DataType, key: str) -> Optional[Any]:
        path = self._path(data_type, key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            record = MemoryRecord(
                data_type=data_type,
                key=key,
                value=raw["value"],
                created_at=raw["created_at"],
                ttl=raw.get("ttl"),
            )
            if record.is_expired():
                path.unlink(missing_ok=True)
                return None
            return record.value
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def put(self, record: MemoryRecord) -> None:
        path = self._path(record.data_type, record.key)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(
                    {
                        "key": record.key,
                        "data_type": record.data_type.value,
                        "value": record.value,
                        "created_at": record.created_at,
                        "ttl": record.ttl,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            self._evict_oldest(record.data_type)
        except OSError:
            pass

    def delete(self, data_type: DataType, key: str) -> None:
        self._path(data_type, key).unlink(missing_ok=True)

    def list_keys(self, data_type: DataType) -> list[str]:
        """Return file stems (hashed keys) for a given data type."""
        dir_path = self._base / data_type.value
        if not dir_path.exists():
            return []
        return [p.stem for p in dir_path.glob("*.json")]
