"""Memory management for the DeepResearch agentic pipeline.

Six data types, two backends:

  DataType.EPHEMERAL     — in-process dict (task analysis, routing metadata)
  DataType.SEARCH_RESULT — shared disk cache, TTL 12 h (search API results)
  DataType.PAGE_CACHE    — shared disk cache, TTL 24 h (fetched page content)
  DataType.INTERMEDIATE  — session disk (researcher memos, critique results)
  DataType.REPORT        — session disk, versioned (writer report drafts)
  DataType.SESSION       — session disk (run provenance, timestamps)

Usage
-----
  from src.memory import DataType, get_manager

  memory = get_manager(session_id, workdir)
  cached = await memory.get(DataType.PAGE_CACHE, url)
  await memory.put(DataType.PAGE_CACHE, url, page_dict)
"""

from src.memory.company_store import CompanyMemoryStore
from src.memory.manager import MemoryManager, get_manager
from src.memory.types import DataType, MemoryRecord

__all__ = ["CompanyMemoryStore", "DataType", "MemoryManager", "MemoryRecord", "get_manager"]
