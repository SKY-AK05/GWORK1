"""Data type taxonomy and record structure for the memory layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DataType(str, Enum):
    """Categories of data generated during agentic communication.

    Each type maps to a specific storage backend and retention policy.
    """

    # In-memory only — task analysis, routing decisions (cheap to regenerate)
    EPHEMERAL = "ephemeral"

    # Shared disk cache — web search results keyed by query (TTL 12 h)
    SEARCH_RESULT = "search"

    # Shared disk cache — fetched page content keyed by URL (TTL 24 h)
    PAGE_CACHE = "page"

    # Session disk — researcher memos and critique results (run lifetime)
    INTERMEDIATE = "intermediate"

    # Session disk — writer report drafts, versioned (persistent)
    REPORT = "report"

    # Session disk — run-level provenance metadata (persistent)
    SESSION = "session"


# Default time-to-live per type (seconds; None = no expiry)
DEFAULT_TTL: dict[DataType, Optional[float]] = {
    DataType.EPHEMERAL: None,
    DataType.SEARCH_RESULT: 12 * 3600,
    DataType.PAGE_CACHE: 24 * 3600,
    DataType.INTERMEDIATE: None,
    DataType.REPORT: None,
    DataType.SESSION: None,
}


@dataclass
class MemoryRecord:
    data_type: DataType
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl: Optional[float] = None

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl
