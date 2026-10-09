"""In-process dict-based cache with TTL support.

Used for EPHEMERAL data that does not survive process restarts and is cheap
enough to recompute in any new run.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.memory.types import MemoryRecord


class InMemoryBackend:
    def __init__(self) -> None:
        self._store: Dict[str, MemoryRecord] = {}

    def get(self, key: str) -> Optional[Any]:
        record = self._store.get(key)
        if record is None:
            return None
        if record.is_expired():
            del self._store[key]
            return None
        return record.value

    def put(self, record: MemoryRecord) -> None:
        self._store[record.key] = record

    def clear(self) -> None:
        self._store.clear()
