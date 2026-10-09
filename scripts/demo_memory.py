#!/usr/bin/env python3
"""Demo: memory layer behaviour without needing any API keys.

Shows all six DataTypes, cache hits, query normalisation, concurrent
fetch coalescing, FIFO eviction, and the on-disk layout.

Run from the project root:
    python scripts/demo_memory.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.memory import DataType, get_manager
from src.memory.manager import search_cache_key
from src.memory.backends.disk import MAX_ENTRIES as _MAX_ENTRIES

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def hdr(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")

def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")

def info(msg: str) -> None:
    print(f"  {YELLOW}→{RESET}  {msg}")

def dim(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


async def main() -> None:
    session_id = "demo-session-abc123"
    workdir    = "/tmp/deepresearch_demo"
    mem        = get_manager(session_id, workdir)

    # ── 1. SESSION provenance ─────────────────────────────────────────────────
    hdr("1 · SESSION — run provenance")
    summary = mem.summary()
    ok(f"session_id : {summary['session_id']}")
    ok(f"workdir    : {summary['workdir']}")
    ok(f"started_at : {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(summary['started_at']))}")
    cache_root = os.environ.get("DEEPRESEARCH_CACHE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "deepresearch"
    )
    session_dir = os.path.join(cache_root, "sessions", session_id, "session")
    dim(f"stored at  : {session_dir}/")

    # ── 2. EPHEMERAL — task analysis ──────────────────────────────────────────
    hdr("2 · EPHEMERAL — task analysis (in-process only)")
    task_analysis = {
        "task_mode": "comparison",
        "comparison_targets": ["LangGraph", "AutoGen"],
        "requested_outputs": ["comparison_table", "architecture_diagram"],
    }
    await mem.put(DataType.EPHEMERAL, "task_analysis", task_analysis)
    got = await mem.get(DataType.EPHEMERAL, "task_analysis")
    ok(f"stored + retrieved task_mode='{got['task_mode']}', targets={got['comparison_targets']}")
    dim("lives in-process only — not persisted to disk")

    # ── 3. SEARCH_RESULT — query normalisation ────────────────────────────────
    hdr("3 · SEARCH_RESULT — query normalisation + cache")
    query_a = "LangGraph multi-agent  orchestration"
    query_b = "langgraph multi-agent orchestration"   # different casing/spacing
    key_a   = search_cache_key(query_a)
    key_b   = search_cache_key(query_b)
    info(f"query A : '{query_a}'  →  key='{key_a}'")
    info(f"query B : '{query_b}'  →  key='{key_b}'")
    assert key_a == key_b
    ok("both normalise to the same cache key — one API call shared")

    fake_results = [
        {"url": "https://docs.langgraph.dev/concepts", "title": "LangGraph Concepts", "snippet": "Stateful multi-actor apps..."},
        {"url": "https://blog.langchain.dev/langgraph", "title": "LangGraph Blog",     "snippet": "Graph-based orchestration..."},
    ]
    await mem.put(DataType.SEARCH_RESULT, key_a, fake_results)

    t0 = time.perf_counter()
    hit = await mem.get(DataType.SEARCH_RESULT, key_b)   # uses normalised key
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert hit == fake_results
    ok(f"cache hit in {elapsed_ms:.1f} ms — {len(hit)} results retrieved")
    dim(f"TTL: 12 h  |  cap: {_MAX_ENTRIES[DataType.SEARCH_RESULT]} entries")

    # ── 4. PAGE_CACHE — concurrent fetch coalescing ───────────────────────────
    hdr("4 · PAGE_CACHE — concurrent fetch coalescing (per-URL lock)")
    fetch_count = 0

    async def mock_fetch(url: str) -> dict:
        nonlocal fetch_count
        fetch_count += 1
        await asyncio.sleep(0.05)          # simulate 50 ms network call
        return {"url": url, "title": "LangGraph Docs", "content": "Stateful graph-based orchestration..."}

    # Use a unique URL so we never get a stale cache hit from a prior demo run
    unique_url = f"https://docs.langgraph.dev/concepts?demo={int(time.time())}"
    t0 = time.perf_counter()
    results = await asyncio.gather(
        mem.get_or_fetch_page(unique_url, mock_fetch),
        mem.get_or_fetch_page(unique_url, mock_fetch),
        mem.get_or_fetch_page(unique_url, mock_fetch),
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert all(r["title"] == "LangGraph Docs" for r in results)
    assert fetch_count == 1
    ok(f"3 concurrent requests → {fetch_count} actual fetch ({elapsed_ms:.0f} ms total)")
    ok("2nd and 3rd callers waited on the lock and read from cache")

    t0  = time.perf_counter()
    cached_page = await mem.get(DataType.PAGE_CACHE, unique_url)
    elapsed_ms  = (time.perf_counter() - t0) * 1000
    ok(f"subsequent get() from disk cache: {elapsed_ms:.1f} ms")
    dim(f"TTL: 24 h  |  cap: {_MAX_ENTRIES[DataType.PAGE_CACHE]} entries")

    # ── 5. INTERMEDIATE — researcher memo ─────────────────────────────────────
    hdr("5 · INTERMEDIATE — researcher memo")
    memo = {
        "question": "Compare LangGraph vs AutoGen",
        "task_mode": "comparison",
        "summary": "LangGraph uses directed graphs for stateful workflows; AutoGen uses chat-based multi-agent loops.",
        "key_statistics": ["LangGraph integrates with LangSmith for tracing", "AutoGen supports human-in-the-loop"],
        "sources": [{"title": "LangGraph Docs", "url": unique_url, "evidence": ["Graph-based orchestration"]}],
    }
    await mem.put(DataType.INTERMEDIATE, "memo_0", memo)
    got = await mem.get(DataType.INTERMEDIATE, "memo_0")
    ok(f"memo stored — summary: '{got['summary'][:60]}…'")
    dim(f"stored at: ~/.cache/deepresearch/sessions/{session_id}/intermediate/")

    # ── 6. REPORT — versioned drafts ─────────────────────────────────────────
    hdr("6 · REPORT — versioned writer drafts")
    for version, summary_text in [
        ("report_v1", "AutoGen and LangGraph serve different orchestration needs. [draft]"),
        ("report_v2", "AutoGen and LangGraph serve complementary orchestration needs. [revised]"),
    ]:
        await mem.put(DataType.REPORT, version, {"executive_summary": summary_text, "sections": []})
        got = await mem.get(DataType.REPORT, version)
        ok(f"{version}: '{got['executive_summary']}'")
    dim(f"stored at: ~/.cache/deepresearch/sessions/{session_id}/report/")

    # ── 7. On-disk layout ─────────────────────────────────────────────────────
    hdr("7 · On-disk layout")
    cache_base = Path(cache_root)
    for p in sorted(cache_base.rglob("*.json")):
        rel = p.relative_to(cache_base)
        size = p.stat().st_size
        print(f"  {DIM}{cache_root}/{RESET}{str(rel):<65}{DIM}{size:>6} B{RESET}")

    # ── 8. FIFO eviction (stress test) ────────────────────────────────────────
    hdr("8 · FIFO eviction (write 6 entries with cap=3)")
    import shutil
    from src.memory.backends.disk import DiskBackend
    from src.memory.backends import disk as _disk_mod
    from src.memory.types import MemoryRecord

    test_dir = "/tmp/dr_eviction_test"
    shutil.rmtree(test_dir, ignore_errors=True)   # start clean
    db = DiskBackend(test_dir)
    cap_override = 3
    _disk_mod.MAX_ENTRIES[DataType.SEARCH_RESULT] = cap_override

    for i in range(6):
        db.put(MemoryRecord(
            data_type=DataType.SEARCH_RESULT,
            key=f"unique-query-{i:04d}",
            value=[f"result_{i}"],
        ))
        search_dir = Path(test_dir) / "search"
        remaining = len(list(search_dir.glob("*.json"))) if search_dir.exists() else 0
        evicted = "← evicted oldest" if i >= cap_override else ""
        info(f"  write {i+1}: {remaining} file(s) on disk (cap={cap_override}) {evicted}")

    _disk_mod.MAX_ENTRIES[DataType.SEARCH_RESULT] = 500   # restore

    # ── Summary ───────────────────────────────────────────────────────────────
    hdr("Summary")
    print(f"""
  {BOLD}6 data types, 2 backends:{RESET}

  EPHEMERAL     in-process dict    task analysis (this run only)
  SEARCH_RESULT shared disk 12h   {len(fake_results)} results cached for '{key_a}'
  PAGE_CACHE    shared disk 24h   '{unique_url[:50]}…'
  INTERMEDIATE  session disk       researcher memo
  REPORT        session disk       report_v1, report_v2
  SESSION       session disk       provenance metadata

  {BOLD}Cache location:{RESET}  {cache_root}/
  {BOLD}Workdir stays clean:{RESET}  {workdir}/  (no .memory/ subfolder)
""")


if __name__ == "__main__":
    asyncio.run(main())
