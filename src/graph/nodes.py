"""LangGraph node implementations for the deep-research pipeline.

Each node is an async function that receives the full ResearchState and
returns a dict of partial state updates.  LangGraph merges the updates
before calling the next node.

Single-researcher pipeline:
  detect_mode → plan_search → execute_searches → fetch_pages
              → follow_up_searches → build_memo
              → build_report → critique → [build_report] → save_artifacts

Multi-researcher pipeline (num_researchers > 1):
  detect_mode → plan_researchers → execute_parallel_research
              → build_report → critique → [build_report] → save_artifacts

Depth modes control query count, pages fetched, and follow-up searches:
  brief        — 2 queries, 3 pages, no follow-up
  standard     — 3 queries, 4 pages, 2 follow-up queries
  comprehensive — 5 queries, 6 pages, 3 follow-up queries
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.graph.state import ResearchState
from src.llm.factory import get_llm
from src.memory import DataType, MemoryManager, get_manager
from src.memory.manager import search_cache_key
from src.schemas.research import (
    ClaimRecord,
    ClaimVerificationResult,
    CritiqueResult,
    ReportSection,
    ProspectRecord,
    ResearchMemo,
    SourceVerdict,
    TaskAnalysis,
    WriterReport,
)
from src.tools.web_fetch import WebFetchTool
from src.tools.web_search import WebSearchTool
from src.verification.company_intelligence import (
    detect_contradictions,
    extract_business_contacts,
    extract_dated_events,
    extract_identity_candidates,
    extract_roles,
    search_companies_house,
)
from src.verification.india import build_india_verification

# Module-level singletons — shared across all graph invocations
_web_search = WebSearchTool()
_web_fetch = WebFetchTool()

SchemaT = TypeVar("SchemaT", bound=BaseModel)


def _get_memory(state: ResearchState) -> Optional[MemoryManager]:
    """Return the MemoryManager for this session, or None if no session_id."""
    session_id = state.get("session_id")
    if not session_id:
        return None
    return get_manager(session_id, state.get("workdir", ""))


async def _fetch_page(url: str) -> Optional[dict]:
    """Fetch one URL and return {url, title, content}, or None on failure.

    Single shared implementation used by all fetch sites so the cache
    integration and timeout are consistent everywhere.
    """
    try:
        result = await asyncio.wait_for(_web_fetch.ainvoke({"url": url}), timeout=20.0)
        if isinstance(result, dict) and result.get("success") and result.get("content"):
            return {
                "url": result.get("url", url),
                "title": result.get("title", "Untitled Source"),
                "content": result.get("content", ""),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        if isinstance(result, dict):
            return {
                "_fetch_failure": True,
                "url": url,
                "failure_type": result.get("error_type", "backend_or_blocked"),
                "reason": str(result.get("error", "no content returned"))[:300],
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
    except asyncio.TimeoutError:
        return {"_fetch_failure": True, "url": url, "failure_type": "timeout", "reason": "fetch timed out"}
    except Exception as exc:
        return {"_fetch_failure": True, "url": url, "failure_type": "exception", "reason": str(exc)[:300]}
    return {"_fetch_failure": True, "url": url, "failure_type": "empty", "reason": "no fetch result"}


def _split_fetch_results(items: List[Optional[dict]]) -> Tuple[List[dict], List[dict]]:
    pages = [item for item in items if item and not item.get("_fetch_failure")]
    failures = [
        {k: v for k, v in item.items() if k != "_fetch_failure"}
        for item in items if item and item.get("_fetch_failure")
    ]
    return pages, failures

def _source_platform(url: str) -> str:
    """Classify a URL without making ownership or identity claims."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0].removeprefix("www.")
    path = parsed.path.lower()
    if host.endswith("linkedin.com"):
        return "linkedin"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("facebook.com"):
        return "facebook"
    if host in {"x.com", "twitter.com", "t.co"} or host.endswith("twitter.com"):
        return "x"
    if host.endswith("youtube.com") or host == "youtu.be":
        return "youtube"
    if host.endswith("tiktok.com"):
        return "tiktok"
    if "companieshouse.gov.uk" in host or ("gov.uk" in host and "company" in path):
        return "registry"
    if "blog" in path or "blog" in host:
        return "blog"
    return "website"


def _source_category(platform: str) -> str:
    if platform in {"linkedin", "instagram", "facebook", "x", "youtube", "tiktok"}:
        return "social"
    if platform == "registry":
        return "registry"
    if platform == "blog":
        return "blog"
    return "official" if platform == "website" else "web"


def _access_status(content: str) -> str:
    """Describe observed public access without attempting authentication."""
    text = (content or "").lower()
    auth_markers = ("agree & join", "sign in", "log in", "login", "create an account")
    if any(marker in text for marker in auth_markers):
        return "partial_public"
    return "fetched"


def _coverage_records(
    search_results: List[dict],
    fetched_pages: List[dict],
    official_link_urls: Optional[set[str]] = None,
) -> List[dict]:
    """Create auditable candidate-URL coverage records from observed pipeline data."""
    official_link_urls = official_link_urls or set()
    fetched_by_url = {p.get("url"): p for p in fetched_pages if p.get("url")}
    candidates: List[dict] = []
    seen: set[str] = set()
    for item in search_results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        page = fetched_by_url.get(url)
        platform = _source_platform(url)
        candidates.append(
            {
                "url": url,
                "platform": platform,
                "source_category": _source_category(platform),
                "discovery_method": "search_result",
                "access_status": _access_status(page.get("content", "")) if page else "not_attempted",
                "retrieved_at": page.get("retrieved_at") if page else None,
            }
        )
    for page in fetched_pages:
        url = page.get("url", "")
        if not url or url in seen:
            continue
        platform = _source_platform(url)
        candidates.append(
            {
                "url": url,
                "platform": platform,
                "source_category": _source_category(platform),
                "discovery_method": "official_site_link" if url in official_link_urls else "follow_up_search",
                "access_status": _access_status(page.get("content", "")),
                "retrieved_at": page.get("retrieved_at"),
            }
        )
    return candidates


def _enrich_memo_sources(memo_dict: dict, state: ResearchState) -> dict:
    """Attach pipeline-observed provenance to LLM-selected sources; never infer ownership."""
    coverage = {item["url"]: item for item in state.get("source_coverage", []) if item.get("url")}
    fetched = {item.get("url"): item for item in state.get("fetched_pages", []) if item.get("url")}
    for source in memo_dict.get("sources", []):
        url = source.get("url", "")
        observed = coverage.get(url)
        if observed:
            source.update({k: v for k, v in observed.items() if v is not None})
        else:
            platform = _source_platform(url)
            source.update(
                {
                    "platform": platform,
                    "source_category": _source_category(platform),
                    "access_status": _access_status(fetched[url].get("content", "")) if url in fetched else "not_attempted",
                    "discovery_method": "unknown",
                }
            )
        source.setdefault("identity_status", "unverified")
        if url in fetched and fetched[url].get("retrieved_at"):
            source["retrieved_at"] = fetched[url]["retrieved_at"]
    return memo_dict


def _company_search_term(task: str) -> str:
    """Extract a compact company token for deterministic discovery queries."""
    uppercase = re.findall(r"\b[A-Z][A-Z0-9&.-]{2,}\b", task)
    if uppercase:
        return uppercase[0]
    quoted = re.findall(r"[\"']([^\"']{2,80})[\"']", task)
    if quoted:
        return quoted[0].strip()
    return task.strip()[:80]


def _is_company_task(task: str) -> bool:
    text = task.lower()
    markers = (
        "company", "legal entity", "corporate", "business", "organization",
        "official website", "social profile", "registry", "company intelligence",
    )
    return any(marker in text for marker in markers)


def _deterministic_social_queries(task: str, depth: str) -> List[str]:
    """Return bounded, provider-neutral public discovery queries for company tasks."""
    if not _is_company_task(task):
        return []
    term = _company_search_term(task)
    queries = [
        f"site:linkedin.com/company {term}",
        f"site:instagram.com {term}",
        f"site:facebook.com {term}",
        f"site:x.com {term} OR site:twitter.com {term}",
        f"site:youtube.com {term}",
        f"site:tiktok.com {term}",
        f"site:find-and-update.company-information.service.gov.uk/company {term} Companies House",
    ]
    budget = {"brief": 4, "standard": 6, "comprehensive": len(queries)}.get(depth, 6)
    return queries[:budget]


def _extract_followable_links(pages: List[dict], max_links: int = 8) -> List[str]:
    """Extract only same-site or explicitly allowlisted public links from official pages."""
    priority_links: List[str] = []
    same_site_links: List[str] = []
    seen: set[str] = set()
    for page in pages:
        page_url = page.get("url", "")
        page_host = urlparse(page_url).netloc.lower().split(":", 1)[0].removeprefix("www.")
        if not page_host or _source_platform(page_url) in {"linkedin", "instagram", "facebook", "x", "youtube", "tiktok", "registry"}:
            continue
        for raw in re.findall(r"https?://[^\s<>\]\)\"']+", page.get("content", "")):
            candidate = raw.rstrip(".,;:!?")
            parsed = urlparse(candidate)
            host = parsed.netloc.lower().split(":", 1)[0].removeprefix("www.")
            allowed_external = _source_platform(candidate) in {
                "linkedin", "instagram", "facebook", "x", "youtube", "tiktok", "registry"
            }
            if not parsed.scheme or not host or (host != page_host and not allowed_external):
                continue
            if candidate not in seen:
                seen.add(candidate)
                (priority_links if allowed_external else same_site_links).append(candidate)
    return (priority_links + same_site_links)[:max_links]


def _extract_social_terms(pages: List[dict], max_terms: int = 8) -> List[str]:
    """Extract public hashtag/mention tokens; matching is not treated as ownership proof."""
    terms: List[str] = []
    seen: set[str] = set()
    for page in pages:
        for token in re.findall(r"(?<!\w)[#@][A-Za-z0-9_]{2,50}", page.get("content", "")):
            normalized = token.lower()
            if normalized not in seen:
                seen.add(normalized)
                terms.append(token)
                if len(terms) >= max_terms:
                    return terms
    return terms


def _research_llm(state: ResearchState):
    """LLM for lightweight tasks: query planning, gap analysis, task detection."""
    return get_llm(state["model_name"])


def _writer_llm(state: ResearchState):
    """LLM for synthesis tasks: memo building, report writing, critique, verification."""
    return get_llm(state.get("writer_model_name") or state["model_name"])


# ─────────────────────────────────────────────────────────────────────────── #
#  Depth configuration                                                         #
# ─────────────────────────────────────────────────────────────────────────── #

_DEPTH_CONFIGS: Dict[str, Dict[str, int]] = {
    "brief": {
        "queries": 2,
        "pages": 3,
        "follow_up": 0,
        "url_cap": 6,
        "comparison_url_multiplier": 2,
        "page_chars": 6_000,   # ~1.5 k tokens per page → ~18 k total input
    },
    "standard": {
        "queries": 3,
        "pages": 4,
        "follow_up": 2,
        "url_cap": 8,
        "comparison_url_multiplier": 2,
        "page_chars": 10_000,  # ~2.5 k tokens per page → ~40 k total input
    },
    "comprehensive": {
        "queries": 5,
        "pages": 6,
        "follow_up": 3,
        "url_cap": 14,
        "comparison_url_multiplier": 3,
        "page_chars": 18_000,  # ~4.5 k tokens per page → ~108 k total input
    },
}


def _depth_config(depth: str) -> Dict[str, int]:
    return _DEPTH_CONFIGS.get(depth, _DEPTH_CONFIGS["standard"])


# ─────────────────────────────────────────────────────────────────────────── #
#  Shared helpers                                                               #
# ─────────────────────────────────────────────────────────────────────────── #

def _extract_json_object(text: str) -> dict:
    """Parse a JSON object, accepting common fenced-code LLM responses."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object from structured-output fallback.")
    return parsed


async def _invoke_structured(
    llm: Any,
    schema: Type[SchemaT],
    messages: List[Any],
) -> SchemaT:
    """Invoke a model with structured output, with JSON fallback.

    Some OpenRouter preview models do not reliably support LangChain tool-based
    structured output. The fallback keeps those models usable by asking for raw
    JSON and validating it locally with Pydantic.
    """
    try:
        result = await llm.with_structured_output(schema).ainvoke(messages)
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)
    except Exception as structured_exc:
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        response = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Return only a valid JSON object. Do not wrap it in markdown. "
                        "The object must satisfy this JSON Schema:\n"
                        f"{schema_json}"
                    )
                ),
                *messages,
            ]
        )
        try:
            return schema.model_validate(_extract_json_object(str(response.content)))
        except Exception as fallback_exc:
            raise RuntimeError(
                "Structured output failed and JSON fallback could not be validated. "
                f"structured_error={structured_exc!r}; fallback_error={fallback_exc!r}"
            ) from fallback_exc


def _deduplicate_memos(
    researcher_memos: List[dict],
) -> Tuple[List[dict], str]:
    """Deduplicate evidence bullets across parallel memos.

    Returns the cleaned memos and a confirmation note listing any URLs cited
    independently by more than one researcher (genuine multi-source support).
    """
    url_counts: Dict[str, int] = {}
    for memo in researcher_memos:
        for src in memo.get("sources", []):
            url = src.get("url", "")
            if url:
                url_counts[url] = url_counts.get(url, 0) + 1

    multi_source_urls = [url for url, cnt in url_counts.items() if cnt > 1]
    confirmation_note = ""
    if multi_source_urls:
        confirmation_note = (
            f"{len(multi_source_urls)} URL(s) independently cited by multiple researchers "
            f"(strong corroboration): {', '.join(multi_source_urls[:3])}"
            + (" …" if len(multi_source_urls) > 3 else "")
        )

    seen_bullets: set = set()
    deduped: List[dict] = []
    for memo in researcher_memos:
        dm = dict(memo)
        deduped_sources = []
        for src in memo.get("sources", []):
            ds = dict(src)
            unique_evidence = []
            for bullet in src.get("evidence", []):
                key = " ".join(bullet.lower().split())[:120]
                if key not in seen_bullets:
                    seen_bullets.add(key)
                    unique_evidence.append(bullet)
            ds["evidence"] = unique_evidence
            if unique_evidence:
                deduped_sources.append(ds)
        dm["sources"] = deduped_sources
        deduped.append(dm)

    return deduped, confirmation_note


def _build_source_index(memos: List[dict]) -> List[Dict[str, str]]:
    """Return a deduplicated, numbered list of sources across all memos.

    Each entry: {"index": "1", "title": "...", "url": "..."}
    Order: first-seen wins for deduplication; index is 1-based.
    """
    seen_urls: set = set()
    index: List[Dict[str, str]] = []
    for memo in memos:
        for src in memo.get("sources", []):
            url = src.get("url", "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                index.append({
                    "index": str(len(index) + 1),
                    "title": src.get("title", "Untitled").strip(),
                    "url": url,
                })
    return index


def _format_source_index_block(index: List[Dict[str, str]]) -> str:
    """Format the numbered source index as a prompt block."""
    if not index:
        return ""
    lines = ["Source index (use [N] in narrative to cite):"]
    for src in index:
        lines.append(f"  [{src['index']}] {src['title']} — {src['url']}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════ #
#  detect_mode_node                                                            #
# ═══════════════════════════════════════════════════════════════════════════ #

async def detect_mode_node(state: ResearchState) -> dict:
    """Use an LLM to determine task mode, comparison targets, and useful output formats."""
    task = state["task"]
    llm = _research_llm(state)

    analysis: TaskAnalysis = await _invoke_structured(
        llm,
        TaskAnalysis,
        [
            SystemMessage(
                content=(
                    "You are a research task analyzer. Given the user's research question, determine:\n\n"
                    "1. task_mode: 'comparison' if the question asks to compare, contrast, or evaluate "
                    "multiple named entities against each other; 'standard' for all other research.\n\n"
                    "2. comparison_targets: for comparison tasks, the named products, frameworks, "
                    "systems, or concepts being compared (2–6 items). Empty list for standard tasks.\n\n"
                    "3. requested_outputs: output formats that would genuinely improve this report "
                    "(omit any that would not add value):\n"
                    "   - 'comparison_table': include when comparing ≥2 items across multiple "
                    "     dimensions where a side-by-side matrix aids understanding\n"
                    "   - 'architecture_diagram': include when the topic involves system architecture, "
                    "     agent orchestration, data flows, or multi-step processes where a Mermaid "
                    "     flowchart would clarify relationships\n\n"
                    "Be proactive: if a comparison task would clearly benefit from a table even if the "
                    "user did not explicitly ask for one, include it. Similarly for diagrams on "
                    "architecture/workflow topics. Return structured JSON."
                )
            ),
            HumanMessage(content=task),
        ],
    )

    # Enforce: comparison mode requires at least 2 identified targets
    if analysis.task_mode == "comparison" and len(analysis.comparison_targets) < 2:
        analysis = TaskAnalysis(
            task_mode="standard",
            comparison_targets=[],
            requested_outputs=analysis.requested_outputs,
        )

    update = {
        "task_mode": analysis.task_mode,
        "comparison_targets": analysis.comparison_targets[:6],
        "requested_outputs": analysis.requested_outputs,
    }

    # Auto-assign one researcher per comparison target when the user has not
    # explicitly requested a multi-researcher run. This ensures each target gets
    # dedicated queries, fetches, and a focused memo rather than sharing a single
    # research pass that can be biased toward whichever target appears first.
    if analysis.task_mode == "comparison" and state.get("num_researchers", 1) == 1:
        update["num_researchers"] = len(analysis.comparison_targets)

    memory = _get_memory(state)
    if memory:
        await memory.put(DataType.EPHEMERAL, "task_analysis", update)

    return update


# ═══════════════════════════════════════════════════════════════════════════ #
#  plan_search_node  (single-researcher path)                                  #
# ═══════════════════════════════════════════════════════════════════════════ #

async def plan_search_node(state: ResearchState) -> dict:
    """Generate a list of web search queries for the task."""
    task = state["task"]
    task_mode = state["task_mode"]
    comparison_targets = state.get("comparison_targets", [])
    depth = state.get("depth", "standard")
    cfg = _depth_config(depth)
    n_queries = cfg["queries"]

    llm = _research_llm(state)

    response = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    f"You are a research planning assistant. "
                    f"Return a JSON array with exactly {n_queries} short web search queries "
                    f"that together would help answer the user's question. "
                    f"Vary the angle: include a general overview query, a technical-depth query, "
                    f"and (if appropriate) a recent-news or data-focused query."
                )
            ),
            HumanMessage(content=task),
        ]
    )
    try:
        queries = [str(q).strip() for q in json.loads(response.content) if str(q).strip()][:n_queries]
    except Exception:
        queries = [task]

    deterministic = _deterministic_social_queries(task, depth)
    combined: List[str] = []
    for query in (queries or [task]) + deterministic:
        if query and query not in combined:
            combined.append(query)
    return {"search_plan": combined}


# ═══════════════════════════════════════════════════════════════════════════ #
#  execute_searches_node  (single-researcher path)                             #
# ═══════════════════════════════════════════════════════════════════════════ #

async def execute_searches_node(state: ResearchState) -> dict:
    """Run all search queries and collect unique results."""
    search_plan = state.get("search_plan", [])
    task_mode = state.get("task_mode", "standard")
    comparison_targets = state.get("comparison_targets", [])
    depth = state.get("depth", "standard")
    cfg = _depth_config(depth)

    url_cap = (
        max(cfg["url_cap"] * cfg["comparison_url_multiplier"], len(comparison_targets) * 3)
        if task_mode == "comparison"
        else cfg["url_cap"]
    )

    memory = _get_memory(state)

    async def search_one(query: str) -> Tuple[List[dict], List[dict]]:
        try:
            items = await _web_search.ainvoke({"query": query, "num_results": 5})
            return items, _web_search.last_attempts
        except Exception as exc:
            return [], [{"provider": "web_search", "attempt": 1, "status": "failed", "reason": str(exc)[:300], "retryable": False}]

    all_results: List[dict] = []
    seen_urls: set = set()
    search_failures: List[dict] = list(state.get("search_failures", []))

    for query in search_plan:
        cache_key = search_cache_key(query)
        if memory:
            cached = await memory.get(DataType.SEARCH_RESULT, cache_key)
        else:
            cached = None

        if cached is not None:
            items = cached
        else:
            items, attempts = await search_one(query)
            for attempt in attempts:
                search_failures.append({"query": query, **attempt})
            if memory and items:
                await memory.put(DataType.SEARCH_RESULT, cache_key, items)

        for item in items:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(item)
        if len(all_results) >= url_cap:
            break

    if all_results:
        run_status = "partial" if any(item.get("status") == "failed" for item in search_failures) else "completed"
    else:
        run_status = "blocked" if search_failures else "completed"
    return {
        "search_results": all_results,
        "search_failures": search_failures,
        "run_status": run_status,
        "coverage_summary": {"search_queries": len(search_plan), "search_results": len(all_results), "search_failures": len(search_failures)},
    }


# ═══════════════════════════════════════════════════════════════════════════ #
#  fetch_pages_node  (single-researcher path)                                  #
# ═══════════════════════════════════════════════════════════════════════════ #

async def fetch_pages_node(state: ResearchState) -> dict:
    """Fetch markdown content for each search result URL."""
    search_results = state.get("search_results", [])
    task_mode = state.get("task_mode", "standard")
    comparison_targets = state.get("comparison_targets", [])
    depth = state.get("depth", "standard")
    cfg = _depth_config(depth)

    source_cap = (
        max(cfg["pages"] * 2, len(comparison_targets) * 3)
        if task_mode == "comparison"
        else cfg["pages"]
    )
    urls = [r["url"] for r in search_results[:source_cap] if r.get("url")]
    memory = _get_memory(state)

    if memory:
        fetched_raw = await asyncio.gather(
            *[memory.get_or_fetch_page(u, _fetch_page) for u in urls]
        )
    else:
        fetched_raw = await asyncio.gather(*[_fetch_page(u) for u in urls])

    pages, fetch_failures = _split_fetch_results(fetched_raw)
    link_cap = max(2, min(8, cfg["pages"] // 2))
    linked_urls = _extract_followable_links(pages, max_links=link_cap)
    existing_urls = {p.get("url") for p in pages}
    linked_urls = [url for url in linked_urls if url not in existing_urls]
    if linked_urls:
        if memory:
            linked_raw = await asyncio.gather(
                *[memory.get_or_fetch_page(u, _fetch_page) for u in linked_urls]
            )
        else:
            linked_raw = await asyncio.gather(*[_fetch_page(u) for u in linked_urls])
        linked_pages, linked_failures = _split_fetch_results(linked_raw)
        pages.extend(linked_pages)
        fetch_failures.extend(linked_failures)
    status = "completed" if pages and not fetch_failures else ("partial" if pages else "blocked")
    return {
        "fetched_pages": pages,
        "source_coverage": _coverage_records(search_results, pages, set(linked_urls)),
        "fetch_failures": list(state.get("fetch_failures", [])) + fetch_failures,
        "run_status": status,
        "coverage_summary": {
            **state.get("coverage_summary", {}), "fetched_pages": len(pages), "fetch_failures": len(fetch_failures)
        },
    }


# ═══════════════════════════════════════════════════════════════════════════ #
#  follow_up_searches_node  (single-researcher path)                           #
# ═══════════════════════════════════════════════════════════════════════════ #

async def follow_up_searches_node(state: ResearchState) -> dict:
    """Generate targeted follow-up queries based on initial fetch gaps, then fetch new pages.

    Skipped when depth='brief' or when initial fetch returned no pages.
    """
    depth = state.get("depth", "standard")
    cfg = _depth_config(depth)
    n_follow_up = cfg["follow_up"]

    if n_follow_up == 0:
        return {}

    fetched_pages = state.get("fetched_pages", [])
    if not fetched_pages:
        return {}

    task = state["task"]
    search_plan = state.get("search_plan", [])
    llm = _research_llm(state)

    pages_summary = "\n".join(
        f"- {p['title']}: {p['content'][:300]}"
        for p in fetched_pages[:5]
    )

    response = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    f"You are a research assistant. Based on initial research results, "
                    f"generate exactly {n_follow_up} targeted follow-up web search queries "
                    f"to fill the most important remaining gaps. "
                    f"Focus on specifics not yet covered: concrete data, counterarguments, "
                    f"recent developments, or under-represented perspectives. "
                    f"Return a JSON array of query strings only."
                )
            ),
            HumanMessage(
                content=(
                    f"Research question: {task}\n\n"
                    f"Queries already run: {json.dumps(search_plan)}\n\n"
                    f"Sources found so far:\n{pages_summary}\n\n"
                    f"What {n_follow_up} follow-up queries would fill the most important gaps?"
                )
            ),
        ]
    )

    try:
        follow_up_queries = [
            str(q).strip() for q in json.loads(response.content) if str(q).strip()
        ][:n_follow_up]
    except Exception:
        return {}

    social_terms = _extract_social_terms(fetched_pages, max_terms=8)
    term_queries = [
        f"{term} {_company_search_term(task)}" for term in social_terms
    ]
    merged_queries: List[str] = []
    for query in term_queries + follow_up_queries:
        if query and query not in merged_queries:
            merged_queries.append(query)
    follow_up_queries = merged_queries[:n_follow_up]

    if not follow_up_queries:
        return {}

    memory = _get_memory(state)

    # Search — SEARCH_RESULT cache with normalized key per follow-up query
    seen_urls = {p["url"] for p in fetched_pages}
    new_results: List[dict] = []
    for query in follow_up_queries:
        cache_key = search_cache_key(query)
        if memory:
            cached = await memory.get(DataType.SEARCH_RESULT, cache_key)
        else:
            cached = None

        if cached is not None:
            items = cached
        else:
            try:
                items = await _web_search.ainvoke({"query": query, "num_results": 3})
            except Exception:
                items = []
            if memory and items:
                await memory.put(DataType.SEARCH_RESULT, cache_key, items)

        for item in items:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                new_results.append(item)

    if not new_results:
        return {"search_plan": search_plan + follow_up_queries}

    # Fetch new pages — PAGE_CACHE via get_or_fetch_page (coalesces concurrent calls)
    new_urls = [r["url"] for r in new_results[: n_follow_up + 1] if r.get("url")]

    if memory:
        fetched_raw = await asyncio.gather(
            *[memory.get_or_fetch_page(u, _fetch_page) for u in new_urls]
        )
    else:
        fetched_raw = await asyncio.gather(*[_fetch_page(u) for u in new_urls])

    new_pages, new_failures = _split_fetch_results(fetched_raw)

    if new_pages:
        combined_pages = fetched_pages + new_pages
        prior_official_links = {
            row.get("url")
            for row in state.get("source_coverage", [])
            if row.get("discovery_method") == "official_site_link"
        }
        return {
            "fetched_pages": combined_pages,
            "source_coverage": _coverage_records(
                state.get("search_results", []), combined_pages, prior_official_links
            ),
            "search_plan": search_plan + follow_up_queries,
            "fetch_failures": list(state.get("fetch_failures", [])) + new_failures,
            "run_status": "partial" if new_failures else state.get("run_status", "completed"),
        }
    return {
        "search_plan": search_plan + follow_up_queries,
        "fetch_failures": list(state.get("fetch_failures", [])) + new_failures,
        "run_status": "partial" if new_failures and fetched_pages else "blocked" if new_failures else state.get("run_status", "completed"),
    }


# ═══════════════════════════════════════════════════════════════════════════ #
#  verify_company_intelligence_node  (P3 verification path)                    #
# ═══════════════════════════════════════════════════════════════════════════ #

async def verify_company_intelligence_node(state: ResearchState) -> dict:
    """Build P3 verification records without treating weak signals as proof."""
    task_text = state["task"]
    is_india = bool(re.search(r"(?i)\b(india|indian|mca|cin|llpin|gstin|udyam|msme)\b", task_text))
    target_for_registry = _company_search_term(task_text)
    identifiers = re.findall(r"(?i)\b(?:[ULFOTCGP][0-9]{5}[A-Z]{2}[0-9]{4}PLC[0-9]{6}|[A-Z]{3}[0-9]{4}|[0-9]{2}[A-Z0-9]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]|UDYAM[A-Z]{2}[0-9]{2}[0-9]{7})\b", task_text)
    india = build_india_verification(target_for_registry, identifiers=identifiers) if is_india else {}
    pages = state.get("fetched_pages", [])
    if not pages:
        return {
            "registry_verification": await search_companies_house(target_for_registry),
            "india_verification": india,
            "identity_candidates": [],
            "role_records": [],
            "dated_events": [],
            "contradictions": [],
            "business_contacts": [],
        }

    target = target_for_registry
    registry = await search_companies_house(target)
    identities = extract_identity_candidates(target, pages)
    identities.extend(registry.get("records", []))
    roles = extract_roles(pages, target)
    events = extract_dated_events(pages, target)
    contacts = extract_business_contacts(pages, target)

    claims: List[dict] = []
    for page in pages:
        for line in page.get("content", "").splitlines():
            lowered = line.lower()
            for field, marker in (("headquarters", "headquarters"), ("founded", "founded"), ("location", "based in")):
                if marker in lowered and ":" in line:
                    claims.append({
                        "field": field,
                        "value": line.split(":", 1)[1].strip(),
                        "source_url": page.get("url", ""),
                        "evidence": line.strip(),
                        "retrieved_at": page.get("retrieved_at"),
                    })
    contradictions = detect_contradictions(claims)
    return {
        "registry_verification": registry,
        "india_verification": india,
        "identity_candidates": identities,
        "role_records": roles,
        "dated_events": events,
        "contradictions": contradictions,
        "business_contacts": contacts,
    }


# ═══════════════════════════════════════════════════════════════════════════ #
#  build_memo_node  (single-researcher path)                                   #
# ═══════════════════════════════════════════════════════════════════════════ #

async def build_memo_node(state: ResearchState) -> dict:
    """Synthesize a structured ResearchMemo from fetched pages via LLM."""
    fetched_pages = state.get("fetched_pages", [])
    if not fetched_pages:
        failure_count = len(state.get("search_failures", [])) + len(state.get("fetch_failures", []))
        memo_dict = {
            "question": state["task"],
            "task_mode": state.get("task_mode", "standard"),
            "requested_outputs": state.get("requested_outputs", []),
            "search_plan": state.get("search_plan", []),
            "comparison_targets": state.get("comparison_targets", []),
            "summary": "No source pages were successfully fetched. This is an incomplete research run, not evidence that the target claim is false.",
            "sources": [],
            "open_questions": [
                f"Research was incomplete: {failure_count} search/fetch failures were recorded.",
                "Which sources can be retried successfully with a functioning provider or accessible URL?",
            ],
            "key_statistics": [],
            "key_quotes": [],
            "source_quality_notes": "No source could be evaluated because the run was blocked or all fetches failed.",
            "registry_verification": state.get("registry_verification", {}),
            "india_verification": state.get("india_verification", {}),
            "identity_candidates": [], "role_records": [], "dated_events": [],
            "contradictions": [], "business_contacts": [],
            "search_failures": state.get("search_failures", []),
            "fetch_failures": state.get("fetch_failures", []),
            "run_status": state.get("run_status", "blocked"),
        }
        memory = _get_memory(state)
        if memory:
            await memory.put(DataType.INTERMEDIATE, "memo", memo_dict)
        return {"memo": memo_dict, "run_status": "blocked", "error": None}

    task = state["task"]
    search_plan = state.get("search_plan", [])
    task_mode = state.get("task_mode", "standard")
    requested_outputs = state.get("requested_outputs", [])
    comparison_targets = state.get("comparison_targets", [])
    use_rag = state.get("use_rag", False)

    source_pages = fetched_pages
    if use_rag:
        from src.rag.retriever import retrieve_relevant_chunks
        source_pages = await retrieve_relevant_chunks(fetched_pages, task, k=10)

    depth = state.get("depth", "standard")
    max_chars = _depth_config(depth).get("page_chars", 8_000)
    pages_text = []
    for i, page in enumerate(source_pages, 1):
        content = page["content"][:max_chars]
        pages_text.append(
            f"Source {i}\nURL: {page['url']}\nTitle: {page['title']}\n{content}"
        )

    llm = _writer_llm(state)
    memo: ResearchMemo = await _invoke_structured(
        llm,
        ResearchMemo,
        [
            SystemMessage(
                content=(
                    "You are the Researcher agent in a two-agent research system.\n"
                    "Use the supplied webpage material to produce a detailed evidence memo "
                    "for a downstream Writer.\n\n"
                    "Requirements:\n"
                    "- Only include sources that provide concrete evidence\n"
                    "- For key_statistics: extract every quantitative fact verbatim "
                    "  (percentages, benchmark numbers, dates, counts) with its source title\n"
                    "- For key_quotes: extract 2-4 verbatim short quotes that best capture "
                    "  expert opinion or key findings, with attribution\n"
                    "- For source_quality_notes: briefly assess whether sources are peer-reviewed, "
                    "  vendor-produced, journalism, or blog posts; note any recency gaps\n"
                    "- If this is a comparison task, fairly cover each target and capture tradeoffs\n"
                    "- Only request output structures the user explicitly asked for\n"
                    "Return structured JSON matching the requested schema."
                )
            ),
            HumanMessage(
                content=(
                    f"Question:\n{task}\n\n"
                    f"Task mode:\n{task_mode}\n\n"
                    f"Requested outputs:\n{json.dumps(requested_outputs)}\n\n"
                    f"Comparison targets:\n{json.dumps(comparison_targets)}\n\n"
                    f"Search plan:\n{json.dumps(search_plan)}\n\n"
                    "Fetched source material:\n" + "\n\n".join(pages_text)
                )
            ),
        ],
    )

    memo_dict = _enrich_memo_sources(memo.model_dump(), state)
    memo_dict.update(
        {
            "registry_verification": state.get("registry_verification", {}),
            "india_verification": state.get("india_verification", {}),
            "identity_candidates": state.get("identity_candidates", []),
            "role_records": state.get("role_records", []),
            "dated_events": state.get("dated_events", []),
            "contradictions": state.get("contradictions", []),
            "business_contacts": state.get("business_contacts", []),
            "search_failures": state.get("search_failures", []),
            "fetch_failures": state.get("fetch_failures", []),
            "run_status": state.get("run_status", "completed"),
        }
    )
    memory = _get_memory(state)
    if memory:
        await memory.put(DataType.INTERMEDIATE, "memo", memo_dict)

    return {"memo": memo_dict}


# ═══════════════════════════════════════════════════════════════════════════ #
#  plan_researchers_node  (multi-researcher path)                              #
# ═══════════════════════════════════════════════════════════════════════════ #

async def plan_researchers_node(state: ResearchState) -> dict:
    """Decompose the task into N focused sub-topics for parallel researchers.

    For comparison tasks, each sub-topic is pinned to one comparison target so
    every target gets a dedicated researcher with its own queries and sources.
    For standard tasks, sub-topics are generated by the LLM.
    """
    task = state["task"]
    num_researchers = state.get("num_researchers", 3)
    task_mode = state.get("task_mode", "standard")
    comparison_targets = state.get("comparison_targets", [])

    # Comparison: one researcher per target — no LLM decomposition needed.
    if task_mode == "comparison" and comparison_targets:
        sub_topics = [
            f"Research exclusively on '{t}': its strengths, limitations, use cases, "
            f"and concrete examples. Context for comparison: {task}"
            for t in comparison_targets[:num_researchers]
        ]
        # Pad if num_researchers > number of targets (shouldn't happen after auto-set)
        while len(sub_topics) < num_researchers:
            sub_topics.append(f"{task} — additional evidence angle {len(sub_topics) + 1}")
        return {"sub_topics": sub_topics[:num_researchers]}

    # Standard task: LLM decomposes into N distinct sub-topics.
    llm = _research_llm(state)
    response = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    f"You are a research planning assistant. "
                    f"Break the following research task into exactly {num_researchers} "
                    f"focused sub-topics that together provide comprehensive coverage. "
                    f"Each sub-topic should be distinct and independently researchable. "
                    f"Include at least one sub-topic that specifically seeks counter-evidence "
                    f"or alternative perspectives. "
                    f"Return a JSON array of exactly {num_researchers} short descriptive strings."
                )
            ),
            HumanMessage(content=task),
        ]
    )

    try:
        sub_topics = [
            str(t).strip()
            for t in json.loads(response.content)
            if str(t).strip()
        ][:num_researchers]
    except Exception:
        sub_topics = []

    while len(sub_topics) < num_researchers:
        sub_topics.append(f"{task} — supplementary angle {len(sub_topics) + 1}")

    return {"sub_topics": sub_topics[:num_researchers]}


# ═══════════════════════════════════════════════════════════════════════════ #
#  execute_parallel_research_node  (multi-researcher path)                     #
# ═══════════════════════════════════════════════════════════════════════════ #

async def _run_single_researcher(
    task: str,
    sub_topic: str,
    model_name: str,
    writer_model_name: Optional[str] = None,
    use_rag: bool = False,
    depth: str = "standard",
    memory: Optional[MemoryManager] = None,
) -> Optional[dict]:
    """Full mini research pipeline for one sub-topic: search → fetch → follow-up → memo."""
    cfg = _depth_config(depth)
    research_llm = get_llm(model_name)
    writer_llm = get_llm(writer_model_name or model_name)

    # 1. Generate queries for this sub-topic
    response = await research_llm.ainvoke(
        [
            SystemMessage(
                content=(
                    f"You are a research planning assistant. "
                    f"Return a JSON array with exactly {cfg['queries']} short web search queries "
                    f"that best cover the given sub-topic. "
                    f"Vary angle: include overview, technical depth, and a data/statistics query."
                )
            ),
            HumanMessage(
                content=f"Main task: {task}\n\nFocused sub-topic: {sub_topic}"
            ),
        ]
    )
    try:
        queries = [
            str(q).strip() for q in json.loads(response.content) if str(q).strip()
        ][: cfg["queries"]]
    except Exception:
        queries = [sub_topic]

    # 2. Execute searches — SEARCH_RESULT cache with normalized keys
    async def _search(query: str) -> List[dict]:
        try:
            return await _web_search.ainvoke({"query": query, "num_results": 4})
        except Exception:
            return []

    async def search_cached(query: str) -> List[dict]:
        key = search_cache_key(query)
        if memory:
            cached = await memory.get(DataType.SEARCH_RESULT, key)
            if cached is not None:
                return cached
        items = await _search(query)
        if memory and items:
            await memory.put(DataType.SEARCH_RESULT, key, items)
        return items

    all_results: List[dict] = []
    seen_urls: set = set()

    for query in queries:
        for item in await search_cached(query):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(item)

    if not all_results:
        for item in await search_cached(f"{task} {sub_topic}"):
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_results.append(item)

    # 3. Fetch top pages — PAGE_CACHE via get_or_fetch_page (coalesces concurrent calls)
    urls = [r["url"] for r in all_results[: cfg["pages"]] if r.get("url")]

    if memory:
        fetched_raw = await asyncio.gather(
            *[memory.get_or_fetch_page(u, _fetch_page) for u in urls]
        )
    else:
        fetched_raw = await asyncio.gather(*[_fetch_page(u) for u in urls])

    pages: List[dict] = [p for p in fetched_raw if p]

    if not pages and all_results:
        pages = [
            {
                "url": r.get("url", ""),
                "title": r.get("title", "Search result"),
                "content": r.get("snippet", ""),
            }
            for r in all_results[:6]
            if r.get("snippet")
        ]

    # 4. Follow-up searches — SEARCH_RESULT + PAGE_CACHE
    if pages and cfg["follow_up"] > 0:
        pages_summary = "\n".join(
            f"- {p['title']}: {p['content'][:200]}" for p in pages[:4]
        )
        fu_response = await research_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        f"Generate exactly {cfg['follow_up']} targeted follow-up web search queries "
                        f"to fill the most important gaps not covered by the initial sources. "
                        f"Focus on: specific data points, counterarguments, or recent developments. "
                        f"Return a JSON array of query strings only."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Sub-topic: {sub_topic}\n\n"
                        f"Initial queries: {json.dumps(queries)}\n\n"
                        f"Sources found:\n{pages_summary}"
                    )
                ),
            ]
        )
        try:
            follow_up_queries = [
                str(q).strip() for q in json.loads(fu_response.content) if str(q).strip()
            ][: cfg["follow_up"]]
        except Exception:
            follow_up_queries = []

        for fq in follow_up_queries:
            for item in await search_cached(fq):
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    new_page = (
                        await memory.get_or_fetch_page(url, _fetch_page)
                        if memory
                        else await _fetch_page(url)
                    )
                    if new_page:
                        pages.append(new_page)
                    break  # one new page per follow-up query is enough

    if not pages:
        return None

    # 5. Optional RAG: trim context to most relevant chunks
    source_pages = pages
    if use_rag:
        from src.rag.retriever import retrieve_relevant_chunks
        source_pages = await retrieve_relevant_chunks(pages, sub_topic, k=10)

    # 6. Build focused memo with enriched fields
    max_chars = cfg.get("page_chars", 8_000)
    pages_text = [
        f"Source {i}\nURL: {p['url']}\nTitle: {p['title']}\n{p['content'][:max_chars]}"
        for i, p in enumerate(source_pages, 1)
    ]

    memo: ResearchMemo = await _invoke_structured(
        writer_llm,
        ResearchMemo,
        [
            SystemMessage(
                content=(
                    "You are a Researcher agent focused on a specific research sub-topic.\n"
                    "Use the supplied webpage material to produce a detailed evidence memo.\n\n"
                    "Requirements:\n"
                    "- Only include sources that provide concrete evidence\n"
                    "- For key_statistics: extract every quantitative fact verbatim "
                    "  (percentages, benchmark numbers, dates, counts) with its source title\n"
                    "- For key_quotes: extract 2-3 verbatim short quotes with attribution\n"
                    "- For source_quality_notes: briefly assess source types and quality\n"
                    "Return structured JSON matching the requested schema."
                )
            ),
            HumanMessage(
                content=(
                    f"Main research question:\n{task}\n\n"
                    f"Your focused sub-topic:\n{sub_topic}\n\n"
                    "Fetched source material:\n" + "\n\n".join(pages_text)
                )
            ),
        ],
    )
    return memo.model_dump()


async def execute_parallel_research_node(state: ResearchState) -> dict:
    """Run N researcher agents in parallel, one per sub-topic."""
    sub_topics = state.get("sub_topics", [])
    if not sub_topics:
        return {"error": "No sub-topics found for parallel research."}

    task = state["task"]
    model_name = state["model_name"]
    writer_model_name = state.get("writer_model_name")
    use_rag = state.get("use_rag", False)
    depth = state.get("depth", "standard")
    memory = _get_memory(state)

    results = await asyncio.gather(
        *[
            _run_single_researcher(task, sub_topic, model_name, writer_model_name, use_rag, depth, memory)
            for sub_topic in sub_topics
        ],
        return_exceptions=True,
    )

    researcher_memos = [r for r in results if isinstance(r, dict)]
    researcher_errors = [
        f"Researcher {i}: {r!r}"
        for i, r in enumerate(results, 1)
        if not isinstance(r, dict)
    ]

    if not researcher_memos:
        detail = "; ".join(researcher_errors[:3]) or "no pages were fetched"
        return {"error": f"All parallel researchers failed to produce memos: {detail}"}

    if memory:
        for i, memo_dict in enumerate(researcher_memos):
            await memory.put(DataType.INTERMEDIATE, f"memo_{i}", memo_dict)

    return {"researcher_memos": researcher_memos, "researcher_errors": researcher_errors}


# ═══════════════════════════════════════════════════════════════════════════ #
#  build_report_node                                                           #
# ═══════════════════════════════════════════════════════════════════════════ #

def _build_writer_system_prompt(is_multi: bool, depth: str) -> str:
    depth_instructions = {
        "brief": (
            "Produce a concise report with 2-3 thematic sections. "
            "Each section narrative should be 1-2 paragraphs."
        ),
        "standard": (
            "Produce a thorough report with 3-5 thematic sections. "
            "Each section narrative should be 2-3 paragraphs with specific evidence."
        ),
        "comprehensive": (
            "Produce a comprehensive, deeply analytical report with 5-7 thematic sections. "
            "Each section narrative should be 3-4 paragraphs. "
            "Include specific statistics, named sources, and nuanced analysis of contradictions. "
            "The report should stand alone as a rigorous reference document."
        ),
    }
    depth_note = depth_instructions.get(depth, depth_instructions["standard"])

    source_context = (
        "multiple parallel researchers, each covering a different sub-topic"
        if is_multi
        else "a single researcher"
    )

    return (
        f"You are the Writer agent in a research system with {source_context}.\n"
        f"Transform the research memo(s) into a final structured report.\n\n"
        f"Depth requirement: {depth_note}\n\n"
        "Structural requirements:\n"
        "- sections: group related claims into thematic sections, each with a title, "
        "  narrative prose, and structured claims. The narrative must integrate evidence, "
        "  cite specific sources by name, and include key statistics inline.\n"
        "- recommendations: provide concrete, actionable items — name who should act, "
        "  what they should do, and why the evidence supports it.\n"
        "- methodology_notes: describe how many sources were used, their types, date range, "
        "  and any notable gaps in the evidence base.\n"
        "- confidence_summary: honestly assess which conclusions are well-supported vs. "
        "  tentative, and what would change the assessment.\n"
        "- executive_summary: 3-5 sentences naming the single most important finding, "
        "  overall confidence, and key open uncertainty.\n\n"
        "Quality constraints:\n"
        "- Separate each claim from its supporting evidence\n"
        "- Assign confidence: High, Medium, or Low\n"
        "- Assign source agreement: Strong agreement, Mixed, Conflicting, or Insufficient evidence\n"
        "- Do not invent evidence outside the memos\n"
        "- Only include a comparison table if requested_outputs contains comparison_table\n"
        "- Only include a Mermaid diagram if requested_outputs contains architecture_diagram\n\n"
        "Citation requirements:\n"
        "- A numbered source index will be provided in the user message.\n"
        "- Embed inline citations in narrative prose using [N] (e.g. 'models trained with LoRA [3] show...').\n"
        "- Cite at least one source per paragraph of narrative.\n"
        "- In the `sources` field of your JSON, list only sources you actually cited, "
        "  formatted as '[N] Title — url', using the same numbers from the index.\n"
        "Return structured JSON matching the requested schema."
    )


async def build_report_node(state: ResearchState) -> dict:
    """Transform memo(s) into a final WriterReport via LLM."""
    if state.get("error"):
        return {}

    researcher_memos = state.get("researcher_memos", [])
    memo_data = state.get("memo")

    if not researcher_memos and not memo_data:
        return {"error": "No research memo available for the writer."}

    if not state.get("fetched_pages") and not researcher_memos:
        report_dict = {
            "question": state["task"],
            "task_mode": state.get("task_mode", "standard"),
            "requested_outputs": state.get("requested_outputs", []),
            "comparison_targets": state.get("comparison_targets", []),
            "executive_summary": "Research was incomplete because no source pages were successfully fetched. No negative company or identity conclusion should be inferred from this run.",
            "sections": [{
                "title": "Research Coverage and Failure Status",
                "narrative": "The run did not obtain fetchable source pages. Search-provider and fetch failure records are preserved for retry and audit. The evidence is insufficient to verify or reject the requested company claims.",
                "claims": [{
                    "claim": "The requested research could not be completed from successfully fetched sources.",
                    "confidence": "High",
                    "source_agreement": "Insufficient evidence",
                    "evidence": ["No source pages were successfully fetched; see recorded search and fetch failures."],
                }],
                "key_statistics": [],
            }],
            "recommendations": ["Retry failed providers and inaccessible URLs within the bounded retry budget before drawing substantive conclusions."],
            "methodology_notes": f"Run status: {state.get('run_status', 'blocked')}. Search failures: {len(state.get('search_failures', []))}; fetch failures: {len(state.get('fetch_failures', []))}.",
            "confidence_summary": "High confidence that this run is incomplete; no confidence should be assigned to unverified company facts.",
            "comparison_table_markdown": None,
            "architecture_diagram_mermaid": None,
            "open_questions": state.get("memo", {}).get("open_questions", []),
            "sources": [],
            "registry_verification": state.get("registry_verification", {}),
            "india_verification": state.get("india_verification", {}),
            "identity_candidates": [], "role_records": [], "dated_events": [],
            "contradictions": [], "business_contacts": [],
            "search_failures": state.get("search_failures", []),
            "fetch_failures": state.get("fetch_failures", []),
            "run_status": state.get("run_status", "blocked"),
        }
        return {"report": report_dict}

    depth = state.get("depth", "standard")
    critique_result = state.get("critique_result")
    llm = _writer_llm(state)

    # Build critique feedback block if this is a revision pass
    critique_block = ""
    if critique_result and critique_result.get("has_issues"):
        issues = []
        if critique_result.get("unsupported_claims"):
            issues.append(
                "Unsupported claims to fix:\n"
                + "\n".join(f"  - {c}" for c in critique_result["unsupported_claims"])
            )
        if critique_result.get("missing_topics"):
            issues.append(
                "Missing topics to add:\n"
                + "\n".join(f"  - {t}" for t in critique_result["missing_topics"])
            )
        if critique_result.get("contradictions"):
            issues.append(
                "Contradictions to resolve:\n"
                + "\n".join(f"  - {c}" for c in critique_result["contradictions"])
            )
        if critique_result.get("improvement_notes"):
            issues.append(f"Editor notes: {critique_result['improvement_notes']}")
        if issues:
            critique_block = (
                "\n\n--- REVISION FEEDBACK (address all points below) ---\n"
                + "\n\n".join(issues)
            )

    system_prompt = _build_writer_system_prompt(bool(researcher_memos), depth)

    if researcher_memos:
        deduped_memos, confirmation_note = _deduplicate_memos(researcher_memos)
        source_index = _build_source_index(deduped_memos)
        source_index_block = _format_source_index_block(source_index)
        corroboration_note = (
            f"\n\nEvidence corroboration note: {confirmation_note}" if confirmation_note else ""
        )
        report: WriterReport = await _invoke_structured(
            llm,
            WriterReport,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=(
                        f"Original question:\n{state['task']}\n\n"
                        f"Task mode:\n{state.get('task_mode', 'standard')}\n\n"
                        f"Requested outputs:\n{json.dumps(state.get('requested_outputs', []))}\n\n"
                        f"Comparison targets:\n{json.dumps(state.get('comparison_targets', []))}\n\n"
                        f"{source_index_block}\n\n"
                        f"Researcher memos ({len(deduped_memos)} parallel researchers, "
                        f"evidence deduplicated):{corroboration_note}\n"
                        + json.dumps(deduped_memos, indent=2)
                        + critique_block
                    )
                ),
            ],
        )
    else:
        memo = ResearchMemo.model_validate(memo_data)
        source_index = _build_source_index([memo_data])
        source_index_block = _format_source_index_block(source_index)
        report = await _invoke_structured(
            llm,
            WriterReport,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=(
                        f"{source_index_block}\n\n"
                        + memo.model_dump_json(indent=2)
                        + critique_block
                    )
                ),
            ],
        )

    report_dict = report.model_dump()
    report_dict.update(
        {
            "registry_verification": state.get("registry_verification", {}),
            "india_verification": state.get("india_verification", {}),
            "identity_candidates": state.get("identity_candidates", []),
            "role_records": state.get("role_records", []),
            "dated_events": state.get("dated_events", []),
            "contradictions": state.get("contradictions", []),
            "business_contacts": state.get("business_contacts", []),
            "search_failures": state.get("search_failures", []),
            "fetch_failures": state.get("fetch_failures", []),
            "run_status": state.get("run_status", "completed"),
        }
    )
    memory = _get_memory(state)
    if memory:
        version = f"report_v{state.get('revision_count', 0) + 1}"
        await memory.put(DataType.REPORT, version, report_dict)

    return {"report": report_dict}


# ═══════════════════════════════════════════════════════════════════════════ #
#  critique_node                                                               #
# ═══════════════════════════════════════════════════════════════════════════ #

async def critique_node(state: ResearchState) -> dict:
    """Review the draft report against source memos and flag significant gaps."""
    if state.get("error"):
        return {}

    report_data = state.get("report")
    if not report_data:
        return {}

    researcher_memos = state.get("researcher_memos", [])
    memo_data = state.get("memo")
    memos_for_critique = researcher_memos if researcher_memos else ([memo_data] if memo_data else [])

    if not memos_for_critique:
        return {}

    llm = _writer_llm(state)
    revision_count = state.get("revision_count", 0)

    # Include any failed source verifications as hard evidence for the critique
    verification_results = state.get("verification_results") or []
    failed_verifications = [v for v in verification_results if not v.get("passed")]
    verification_block = ""
    if failed_verifications:
        verification_block = (
            "\n\nSource verification results — claims that were re-checked against their cited "
            "URLs and FAILED (source did not support the claim):\n"
            + "\n".join(
                f"  - [{v['section_title']}] \"{v['claim'][:120]}\" "
                f"— checked {v['url_checked']}: {v['note']}"
                for v in failed_verifications
            )
            + "\nThese failed verifications must be listed in unsupported_claims and "
            "has_issues must be True."
        )

    critique: CritiqueResult = await _invoke_structured(
        llm,
        CritiqueResult,
        [
            SystemMessage(
                content=(
                    "You are a rigorous research editor reviewing a draft report.\n\n"
                    "Your job: compare the draft report against the source memos it was built from.\n\n"
                    "Flag has_issues=True ONLY for significant problems:\n"
                    "  1. Claims in the report with no supporting evidence in the memos\n"
                    "  2. Important topics well-covered in the memos but entirely absent from the report\n"
                    "  3. Factual contradictions between different researchers' memos that the "
                    "     report did not acknowledge\n"
                    "  4. Any claims listed in the source verification failures block (if present) — "
                    "     these were checked against live source pages and found unsupported\n\n"
                    "Do NOT flag minor omissions, stylistic issues, or topics the memos themselves "
                    "lacked evidence for. If the report is reasonably comprehensive and well-supported, "
                    "set has_issues=False.\n\n"
                    "Be specific in improvement_notes: name the sections and claims to fix.\n"
                    "Return structured JSON."
                )
            ),
            HumanMessage(
                content=(
                    f"Original question: {state['task']}\n\n"
                    f"Source memos:\n{json.dumps(memos_for_critique, indent=2)}\n\n"
                    f"Draft report:\n{json.dumps(report_data, indent=2)}"
                    + verification_block
                )
            ),
        ],
    )

    critique_dict = critique.model_dump()
    memory = _get_memory(state)
    if memory:
        await memory.put(DataType.INTERMEDIATE, "critique", critique_dict)

    return {
        "critique_result": critique_dict,
        "revision_count": revision_count + 1,
    }


# ═══════════════════════════════════════════════════════════════════════════ #
#  verify_claims_node                                                          #
# ═══════════════════════════════════════════════════════════════════════════ #

def _url_for_citation(cite_num: str, sources: List[str]) -> Optional[str]:
    """Extract URL from a '[N] Title — url' sources entry."""
    for src in sources:
        m = re.match(r'\[(\d+)\].*?(?:\s+[—\-]+\s+)(https?://[^\s,.)]+)', src)
        if m and m.group(1) == cite_num:
            return m.group(2)
    return None


async def verify_claims_node(state: ResearchState) -> dict:
    """Re-fetch cited sources for low-confidence claims and verify grounding.

    Targets claims with confidence=Low or source_agreement in
    (Insufficient evidence, Conflicting). Capped at 5 verifications so the
    page cache is almost always warm from earlier fetch steps.
    Results are stored in verification_results and consumed by critique_node.
    """
    if state.get("error"):
        return {"verification_results": []}

    # Only verify on the first report pass — the revision is expected to fix the
    # failures we already flagged; re-running doubles cost with no new signal.
    if state.get("revision_count", 0) > 0:
        return {"verification_results": state.get("verification_results") or []}

    # Brief depth produces short, low-stakes reports — verification overhead
    # isn't worth it there.
    if state.get("depth", "standard") == "brief":
        return {"verification_results": []}

    report_data = state.get("report")
    if not report_data:
        return {"verification_results": []}

    # Collect claims that need verification
    to_verify: List[Dict[str, Any]] = []
    for section in report_data.get("sections", []):
        section_title = section.get("title", "")
        for claim in section.get("claims", []):
            confidence = claim.get("confidence", "")
            agreement = claim.get("source_agreement", "")
            if confidence == "Low" or agreement in ("Insufficient evidence", "Conflicting"):
                to_verify.append({
                    "section_title": section_title,
                    "claim": claim.get("claim", ""),
                    "evidence": claim.get("evidence", []),
                })

    if not to_verify:
        return {"verification_results": []}

    to_verify = to_verify[:5]  # cap to avoid excessive re-fetching

    # Build citation-index → URL map from report sources list
    sources_list: List[str] = report_data.get("sources", [])
    url_by_index: Dict[str, str] = {}
    for src_str in sources_list:
        m = re.match(r'\[(\d+)\].*?(?:\s+[—\-]+\s+)(https?://[^\s,.)]+)', src_str)
        if m:
            url_by_index[m.group(1)] = m.group(2)

    llm = _writer_llm(state)
    memory = _get_memory(state)
    results: List[dict] = []

    for item in to_verify:
        # Resolve a source URL: prefer the first [N] citation in evidence bullets
        url: Optional[str] = None
        for bullet in item["evidence"]:
            m = re.search(r'\[(\d+)\]', bullet)
            if m and m.group(1) in url_by_index:
                url = url_by_index[m.group(1)]
                break
        # Fall back to the first source URL in the report
        if not url and url_by_index:
            url = next(iter(url_by_index.values()))
        if not url:
            continue

        # Fetch page — almost always a PAGE_CACHE hit from earlier in the pipeline
        if memory:
            page = await memory.get_or_fetch_page(url, _fetch_page)
        else:
            page = await _fetch_page(url)

        if not page or not page.get("content"):
            results.append(ClaimVerificationResult(
                claim=item["claim"],
                section_title=item["section_title"],
                url_checked=url,
                passed=False,
                note="Source page could not be fetched for verification.",
            ).model_dump())
            continue

        content_excerpt = page["content"][:3000]
        try:
            verdict: SourceVerdict = await _invoke_structured(
                llm,
                SourceVerdict,
                [
                    SystemMessage(content=(
                        "You are a fact-checker. Determine whether the provided source page content "
                        "supports the given claim. Set passed=True if the source contains information "
                        "consistent with or supporting the claim, even partially. Set passed=False "
                        "only if the source actively contradicts the claim or contains no relevant "
                        "information whatsoever. Be lenient: indirect or partial support is passed=True."
                    )),
                    HumanMessage(content=(
                        f"Claim to verify:\n{item['claim']}\n\n"
                        f"Source URL: {url}\n"
                        f"Source content (excerpt):\n{content_excerpt}"
                    )),
                ],
            )
            results.append(ClaimVerificationResult(
                claim=item["claim"],
                section_title=item["section_title"],
                url_checked=url,
                passed=verdict.passed,
                note=verdict.note,
            ).model_dump())
        except Exception as exc:
            results.append(ClaimVerificationResult(
                claim=item["claim"],
                section_title=item["section_title"],
                url_checked=url,
                passed=False,
                note=f"Verification call failed: {exc!r}",
            ).model_dump())

    if memory and results:
        await memory.put(DataType.INTERMEDIATE, "verification_results", results)

    return {"verification_results": results}


# ═══════════════════════════════════════════════════════════════════════════ #
#  save_artifacts_node                                                         #
# ═══════════════════════════════════════════════════════════════════════════ #

def _build_prospect_record(
    state: ResearchState, report: WriterReport, memo: Optional[ResearchMemo] = None
) -> ProspectRecord:
    """Project the evidence-bearing run into the stable prospect-database contract."""
    candidates = state.get("identity_candidates", [])
    target = next(
        (item.get("target_name") or item.get("candidate_name") for item in candidates if item),
        None,
    )
    if not target:
        match = re.search(r"\b[A-Z][A-Z0-9.&-]{2,}\b", state.get("task", ""))
        target = match.group(0) if match else "Unknown"

    social_hosts = {"linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com"}
    registry_hosts = {"companieshouse.gov.uk", "company-information.service.gov.uk"}
    source_models = memo.sources if memo else []
    sources = [item.model_dump() for item in source_models]
    official_domain = None
    for source in sources:
        host = urlparse(source["url"]).netloc.lower().split(":", 1)[0].removeprefix("www.")
        if host and not any(host == h or host.endswith("." + h) for h in social_hosts | registry_hosts):
            official_domain = host
            break

    evidence = []
    for source in sources:
        for excerpt in source.get("evidence", []):
            evidence.append({"claim": None, "source_url": source["url"], "excerpt": excerpt})
    registry = state.get("registry_verification", {})
    records = registry.get("records", []) or []
    matched = next((item for item in records if item.get("match_status") in {"confirmed_match", "possible_match"}), {})
    identity_status = "confirmed_match" if any(item.get("match_status") == "confirmed_match" for item in candidates) else (
        "possible_match" if candidates else "inconclusive_verification"
    )
    return ProspectRecord(
        brand_name=str(target),
        official_domain=official_domain,
        legal_entity_name=matched.get("candidate_name"),
        jurisdiction=("United Kingdom" if "united kingdom" in state.get("task", "").lower() else None),
        registration_number=matched.get("candidate_id") or matched.get("company_number"),
        company_description=report.executive_summary,
        sources=sources,
        evidence=evidence,
        identity_match_status=identity_status,
        registration_verification_status=registry.get("outcome", "inconclusive_verification"),
        confidence="high" if identity_status == "confirmed_match" else ("medium" if sources else "low"),
        unresolved_questions=report.open_questions,
    )


async def save_artifacts_node(state: ResearchState) -> dict:
    """Write Markdown, JSON, PDF, and machine-readable run manifest artifacts."""
    from src.exporters import mermaid_to_png, report_to_pdf

    workdir = state["workdir"]
    os.makedirs(workdir, exist_ok=True)

    result: dict = {}

    # Single-researcher mode
    memo_data = state.get("memo")
    if memo_data:
        memo = ResearchMemo.model_validate(memo_data)
        result["memo_path"] = _save_memo(memo, workdir)

    # Multi-researcher mode: save one file per researcher
    researcher_memos = state.get("researcher_memos", [])
    if researcher_memos:
        memo_paths = []
        for i, md in enumerate(researcher_memos, 1):
            memo = ResearchMemo.model_validate(md)
            path = _save_memo(memo, workdir, filename=f"researcher_memo_{i}.md")
            memo_paths.append(path)
        result["memo_path"] = memo_paths[0] if memo_paths else None
        result["memo_paths"] = memo_paths

    report_data = state.get("report")
    if report_data:
        report = WriterReport.model_validate(report_data)
        report_md_path = _save_report(report, workdir)
        result["report_path"] = report_md_path
        memo_for_record = ResearchMemo.model_validate(memo_data) if memo_data else None
        prospect = _build_prospect_record(state, report, memo_for_record)
        prospect_path = os.path.join(workdir, "prospect.json")
        with open(prospect_path, "w", encoding="utf-8") as handle:
            handle.write(prospect.model_dump_json(indent=2))
        result["prospect_json_path"] = prospect_path
        result.update(_save_product_manifests(state, report, memo_for_record, workdir))

        # Diagram PNG export first (PDF may embed it)
        diagram_path: Optional[str] = None
        mermaid_code = report_data.get("architecture_diagram_mermaid")
        if mermaid_code and mermaid_code.strip():
            png_path = os.path.join(workdir, "architecture_diagram.png")
            success = await mermaid_to_png(mermaid_code.strip(), png_path)
            if success:
                diagram_path = png_path
                result["diagram_path"] = png_path
            else:
                print("[exporters] Mermaid PNG fetch failed (non-fatal).", flush=True)

        # PDF export from structured report data via xelatex
        try:
            pdf_path = os.path.join(workdir, "final_report.pdf")
            report_to_pdf(
                report_data,
                pdf_path,
                diagram_path=diagram_path,
                depth=state.get("depth", "standard"),
            )
            result["report_pdf_path"] = pdf_path
        except Exception as exc:
            print(f"[exporters] PDF generation failed (non-fatal): {exc}", flush=True)

    return result


def _save_product_manifests(
    state: ResearchState,
    report: WriterReport,
    memo: Optional[ResearchMemo],
    workdir: str,
) -> dict:
    """Save stable product-facing names without changing the legacy artifacts."""
    report_payload = report.model_dump()
    report_payload["schema_version"] = "1.0"
    report_payload["run_id"] = state.get("session_id")
    report_payload["input"] = {"task": state.get("task"), "depth": state.get("depth")}
    report_json = os.path.join(workdir, "company_research.json")
    with open(report_json, "w", encoding="utf-8") as handle:
        json.dump(report_payload, handle, ensure_ascii=False, indent=2)
    snapshot_paths = _save_snapshot(report_payload, workdir)

    sources = [source.model_dump() for source in (memo.sources if memo else [])]
    sources_json = os.path.join(workdir, "sources.json")
    with open(sources_json, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": "1.0", "sources": sources}, handle, ensure_ascii=False, indent=2)

    metadata = {
        "schema_version": "1.0",
        "run_id": state.get("session_id"),
        "status": report.run_status,
        "task": state.get("task"),
        "depth": state.get("depth"),
        "model": state.get("model_name"),
        "writer_model": state.get("writer_model_name") or state.get("model_name"),
        "search_plan": state.get("search_plan", []),
        "source_count": len(sources),
        "coverage_summary": state.get("coverage_summary", {}),
        "tool_errors": state.get("search_failures", []) + state.get("fetch_failures", []),
        "registry_verification": state.get("registry_verification", {}),
        "report_paths": {
            "markdown": os.path.join(workdir, "company_research_report.md"),
            "json": report_json,
            "sources": sources_json,
        },
    }
    metadata_json = os.path.join(workdir, "run_metadata.json")
    with open(metadata_json, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    report_md_path = os.path.join(workdir, "final_report.md")
    if not os.path.exists(report_md_path):
        _save_report(report, workdir)
    report_markdown = os.path.join(workdir, "company_research_report.md")
    with open(report_md_path, "r", encoding="utf-8") as source:
        markdown = source.read()
    with open(report_markdown, "w", encoding="utf-8") as target:
        target.write(markdown)
    return {
        "company_report_path": report_markdown,
        "company_json_path": report_json,
        "sources_json_path": sources_json,
        "run_metadata_path": metadata_json,
        **snapshot_paths,
    }


def _save_snapshot(prospect: dict, workdir: str) -> dict:
    """Store the latest report payload and a bounded JSON change summary."""
    from src.validation import compare_snapshot

    snapshot_dir = os.path.join(os.path.dirname(workdir), "snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    latest_path = os.path.join(snapshot_dir, "latest.json")
    previous = None
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as handle:
                previous = json.load(handle)
        except (OSError, json.JSONDecodeError):
            previous = None
    changes = compare_snapshot(previous, prospect)
    with open(latest_path, "w", encoding="utf-8") as handle:
        json.dump(prospect, handle, ensure_ascii=False, indent=2)
    changes_path = os.path.join(workdir, "changes.json")
    with open(changes_path, "w", encoding="utf-8") as handle:
        json.dump(changes, handle, ensure_ascii=False, indent=2)
    return {"snapshot_path": latest_path, "changes_path": changes_path}


# ═══════════════════════════════════════════════════════════════════════════ #
#  File serialisers                                                            #
# ═══════════════════════════════════════════════════════════════════════════ #

def _save_memo(
    memo: ResearchMemo, workdir: str, filename: str = "researcher_memo.md"
) -> str:
    lines = [
        "# Researcher Memo", "",
        "## Question", "", memo.question, "",
        "## Task Mode", "", memo.task_mode, "",
    ]

    if memo.requested_outputs:
        lines += ["## Requested Outputs", ""]
        lines += [f"- {item}" for item in memo.requested_outputs]
        lines.append("")

    if memo.comparison_targets:
        lines += ["## Comparison Targets", ""]
        lines += [f"- {t}" for t in memo.comparison_targets]
        lines.append("")

    lines += ["## Search Plan", ""]
    lines += [f"- {q}" for q in memo.search_plan] or ["- No search plan recorded"]
    lines.append("")

    lines += ["## Summary", "", memo.summary, ""]

    if memo.key_statistics:
        lines += ["## Key Statistics", ""]
        lines += [f"- {s}" for s in memo.key_statistics]
        lines.append("")

    if memo.key_quotes:
        lines += ["## Key Quotes", ""]
        lines += [f"- {q}" for q in memo.key_quotes]
        lines.append("")

    if memo.source_quality_notes:
        lines += ["## Source Quality Notes", "", memo.source_quality_notes, ""]

    registry_outcome = memo.registry_verification.get("outcome", "inconclusive_verification")
    lines += ["## Verification and Company Intelligence", "", f"- Registry outcome: {registry_outcome}"]
    if memo.registry_verification.get("error"):
        lines.append(f"- Registry note: {memo.registry_verification['error']}")
    if memo.india_verification:
        lines.append("- India registry outcomes:")
        for name, outcome in memo.india_verification.get("registries", {}).items():
            lines.append(f"  - {name}: {outcome.get('outcome', 'inconclusive_verification')}")
    for label, records in (
        ("Identity Candidates", memo.identity_candidates),
        ("Roles", memo.role_records),
        ("Dated Events", memo.dated_events),
        ("Contradictions", memo.contradictions),
        ("Public Business Contacts", memo.business_contacts),
    ):
        if records:
            lines += [f"### {label}", ""]
            for record in records:
                lines.append(f"- {json.dumps(record, ensure_ascii=False, sort_keys=True)}")
    lines.append("")

    lines += ["## Run Status and Failure Records", "", f"- Run status: {memo.run_status}"]
    for label, records in (("Search failures", memo.search_failures), ("Fetch failures", memo.fetch_failures)):
        if records:
            lines += [f"### {label}", ""]
            lines.extend(f"- {json.dumps(record, ensure_ascii=False, sort_keys=True)}" for record in records)
    lines.append("")

    lines += ["## Sources", ""]
    for src in memo.sources:
        lines.append(f"### {src.title}")
        lines.append(f"- URL: {src.url}")
        lines.append(
            f"- Provenance: platform={src.platform}; category={src.source_category}; "
            f"discovery={src.discovery_method}; access={src.access_status}; "
            f"identity={src.identity_status}"
        )
        if src.publication_date:
            lines.append(f"- Publication date: {src.publication_date}")
        if src.retrieved_at:
            lines.append(f"- Retrieved at: {src.retrieved_at}")
        lines.append("- Evidence:")
        for bullet in src.evidence:
            lines.append(f"  - {bullet}")
        lines.append("")

    lines += ["## Open Questions", ""]
    lines += [f"- {item}" for item in memo.open_questions] or ["- None"]

    path = os.path.join(workdir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def _save_report(report: WriterReport, workdir: str) -> str:
    lines = [
        "# Final Report", "",
        "## Question", "", report.question, "",
        "## Executive Summary", "", report.executive_summary, "",
    ]

    if report.task_mode == "comparison" and report.comparison_targets:
        lines += ["## Compared Targets", ""]
        lines += [f"- {t}" for t in report.comparison_targets]
        lines.append("")

    if "comparison_table" in report.requested_outputs and report.comparison_table_markdown:
        lines += ["## Comparison Table", "", report.comparison_table_markdown, ""]

    if "architecture_diagram" in report.requested_outputs and report.architecture_diagram_mermaid:
        lines += [
            "## Architecture Diagram", "",
            "```mermaid", report.architecture_diagram_mermaid.strip(), "```", "",
        ]

    # Thematic sections — the main body
    for section in report.sections:
        lines += [f"## {section.title}", "", section.narrative, ""]

        if section.key_statistics:
            lines += ["**Key Statistics**", ""]
            lines += [f"- {s}" for s in section.key_statistics]
            lines.append("")

        if section.claims:
            lines += [
                "**Claims**", "",
                "| # | Confidence | Source Agreement | Claim |",
                "|---|---|---|---|",
            ]
            for i, claim in enumerate(section.claims, 1):
                lines.append(
                    f"| {i} | {claim.confidence} | {claim.source_agreement} | {claim.claim} |"
                )
            lines.append("")

            for i, claim in enumerate(section.claims, 1):
                lines += [
                    f"### Claim {i}: {claim.claim[:80]}{'…' if len(claim.claim) > 80 else ''}",
                    "",
                    f"- **Confidence**: {claim.confidence}",
                    f"- **Source Agreement**: {claim.source_agreement}",
                    "",
                    "**Supporting Evidence**", "",
                ]
                for bullet in claim.evidence:
                    lines.append(f"- {bullet}")
                lines.append("")

    lines += ["## Verification and Company Intelligence", ""]
    lines.append(f"- Registry outcome: {report.registry_verification.get('outcome', 'inconclusive_verification')}")
    if report.registry_verification.get("error"):
        lines.append(f"- Registry note: {report.registry_verification['error']}")
    if report.india_verification:
        lines.append("- India registry outcomes:")
        for name, outcome in report.india_verification.get("registries", {}).items():
            lines.append(f"  - {name}: {outcome.get('outcome', 'inconclusive_verification')}")
    for label, records in (
        ("Identity Candidates", report.identity_candidates),
        ("Roles", report.role_records),
        ("Dated Events", report.dated_events),
        ("Contradictions", report.contradictions),
        ("Public Business Contacts", report.business_contacts),
    ):
        if records:
            lines += [f"### {label}", ""]
            for record in records:
                lines.append(f"- {json.dumps(record, ensure_ascii=False, sort_keys=True)}")
    lines.append("")

    lines += ["## Run Status and Failure Records", "", f"- Run status: {report.run_status}"]
    for label, records in (("Search failures", report.search_failures), ("Fetch failures", report.fetch_failures)):
        if records:
            lines += [f"### {label}", ""]
            lines.extend(f"- {json.dumps(record, ensure_ascii=False, sort_keys=True)}" for record in records)
    lines.append("")

    # Recommendations
    lines += ["## Recommendations", ""]
    if report.recommendations:
        lines += [f"- {r}" for r in report.recommendations]
    else:
        lines.append("- No specific recommendations recorded.")
    lines.append("")

    # Methodology & confidence
    lines += [
        "## Methodology & Confidence", "",
        "### Methodology", "", report.methodology_notes, "",
        "### Overall Confidence", "", report.confidence_summary, "",
    ]

    # Open questions
    lines += ["## Open Questions", ""]
    lines += [f"- {item}" for item in report.open_questions] or ["- None identified."]
    lines.append("")

    # Sources — numbered list so [N] inline citations resolve visually
    lines += ["## Sources", ""]
    if report.sources:
        for src in report.sources:
            # Entries may already start with "[N]" (writer-produced) or be plain strings
            lines.append(src if src.startswith("[") else f"- {src}")
    else:
        lines.append("- No sources recorded.")
    lines += [
        "",
        "## Report Notes",
        "",
        "- Claims are separated from evidence so reviewers can inspect support independently.",
        "- Confidence reflects strength and completeness of available evidence.",
        "- Source Agreement reflects whether cited sources align, conflict, or remain too sparse.",
    ]

    path = os.path.join(workdir, "final_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
