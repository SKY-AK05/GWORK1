"""LangGraph state definition for the deep-research pipeline."""

from __future__ import annotations

from typing import List, Optional

from typing_extensions import TypedDict


class ResearchState(TypedDict):
    """Shared state passed between all LangGraph nodes.

    Nodes read from this dict and return partial updates which LangGraph
    merges back before invoking the next node.
    """

    # ── Input ──────────────────────────────────────────────────────────
    task: str
    workdir: str
    model_name: str                      # Research model (query planning, gap analysis)
    writer_model_name: Optional[str]     # Synthesis model (memo, report, critique); None = use model_name
    session_id: Optional[str]           # Unique run ID for memory management

    # ── Depth control ─────────────────────────────────────────────────
    depth: str                         # "brief" | "standard" | "comprehensive"

    # ── Task analysis (set by detect_mode_node) ────────────────────────
    task_mode: str                     # "standard" | "comparison"
    comparison_targets: List[str]
    requested_outputs: List[str]       # "comparison_table" | "architecture_diagram"

    # ── Research pipeline (set by execute_searches / fetch_pages) ──────
    search_plan: List[str]
    research_plan: dict
    decision_trace: List[dict]
    model_usage: List[dict]
    search_results: List[dict]         # [{url, title, snippet}, ...]
    fetched_pages: List[dict]          # [{url, title, content}, ...]
    source_coverage: List[dict]        # typed retrieval/discovery status per candidate URL
    search_failures: List[dict]        # provider/query failures and retry outcomes
    fetch_failures: List[dict]         # URL fetch failures with access/timeout classification
    run_status: str                    # completed | partial | blocked | failed
    coverage_summary: dict             # completed, failed, and not-attempted counts
    india_verification: dict           # India-specific registry inventory and outcomes
    registry_verification: dict         # explicit Companies House outcome, including inconclusive
    identity_candidates: List[dict]    # possible/confirmed/rejected identity candidates
    role_records: List[dict]           # current claims versus historical roles
    dated_events: List[dict]           # dated company/person events
    contradictions: List[dict]        # conflicting claims kept unresolved
    business_contacts: List[dict]      # published but not assumed deliverable contacts
    entity_relationships: List[dict]   # links among legal entities, brands, subsidiaries, branches, aliases
    business_analysis: dict             # structured business-purpose and market evidence
    workforce_signals: List[dict]       # leadership, employees, joiners, departures, position changes
    hiring_signals: List[dict]          # public job-posting requirements and work arrangements
    claim_ledger: List[dict]            # verified/secondary/inference/unknown claim labels

    # ── Multi-researcher (set by plan_researchers / execute_parallel_research) ──
    num_researchers: int               # >1 enables parallel researchers; default 1
    sub_topics: List[str]              # N focused sub-topics, one per researcher
    researcher_memos: List[dict]       # one ResearchMemo per researcher
    researcher_errors: List[str]       # non-fatal per-researcher failures

    # ── RAG ─────────────────────────────────────────────────────────────
    use_rag: bool                      # trim context via retrieval before LLM calls

    # ── LLM outputs (set by build_memo / build_report) ──────────────────
    memo: Optional[dict]               # ResearchMemo.model_dump()
    report: Optional[dict]             # WriterReport.model_dump()

    # ── Critic loop ──────────────────────────────────────────────────────
    critique_result: Optional[dict]    # CritiqueResult.model_dump()
    revision_count: int                # incremented each time critique runs

    # ── Claim verification (set by verify_claims_node) ─────────────────
    verification_results: Optional[List[dict]]  # List[ClaimVerificationResult.model_dump()]

    # ── Persisted artifacts ────────────────────────────────────────────
    memo_path: Optional[str]
    memo_paths: Optional[List[str]]
    report_path: Optional[str]
    report_pdf_path: Optional[str]      # PDF export of final_report.md
    diagram_path: Optional[str]         # PNG export of architecture_diagram (if present)

    # ── Error propagation ──────────────────────────────────────────────
    error: Optional[str]
