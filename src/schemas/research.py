"""Pydantic schemas for the researcher → writer pipeline.

These are the structured data contracts passed between LangGraph nodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskAnalysis(BaseModel):
    """Structured analysis of the user's research task produced by detect_mode_node."""

    task_mode: str = Field(
        description="'comparison' if the task asks to compare or contrast multiple named entities; 'standard' otherwise"
    )
    comparison_targets: List[str] = Field(
        default_factory=list,
        description="Named products, frameworks, or systems being compared. Empty for standard tasks.",
    )
    requested_outputs: List[str] = Field(
        default_factory=list,
        description=(
            "Output formats that would meaningfully enhance this report. "
            "Choose from: 'comparison_table' (side-by-side matrix of ≥2 items across key dimensions), "
            "'architecture_diagram' (Mermaid flowchart for system/workflow/process topics). "
            "Include only formats that add genuine value — not every comparison needs a table, "
            "and not every technical topic needs a diagram."
        ),
    )


class ResearchPlanItem(BaseModel):
    """One bounded, evidence-oriented research question selected by the model."""

    question: str
    required_fields: List[str] = Field(default_factory=list)
    queries: List[str] = Field(default_factory=list)
    tool_category: str
    preferred_source_types: List[str] = Field(default_factory=list)
    identity_signals: List[str] = Field(default_factory=list)
    evidence_required: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    priority: str = "medium"
    budget: int = 1


class ResearchPlan(BaseModel):
    """Model proposal validated against the application's permitted tool registry."""

    items: List[ResearchPlanItem] = Field(default_factory=list)
    stopping_conditions: List[str] = Field(default_factory=list)
    rationale: str = ""


class ResearchSource(BaseModel):
    """A single evidence-bearing source gathered by the researcher node."""

    title: str = Field(description="Human-readable source title")
    url: str = Field(description="Source URL")
    evidence: List[str] = Field(description="Concrete evidence bullets from the source")
    platform: str = Field(
        default="other",
        description=(
            "Normalized source platform/category, e.g. website, blog, linkedin, "
            "instagram, facebook, x, youtube, tiktok, registry, or other"
        ),
    )
    source_category: str = Field(
        default="web",
        description="Broad source category such as official, social, registry, news, blog, or web",
    )
    discovery_method: str = Field(
        default="unknown",
        description=(
            "How this URL was discovered: search_result, follow_up_search, "
            "official_site_link, direct_registry_query, or unknown"
        ),
    )
    access_status: str = Field(
        default="unknown",
        description=(
            "Retrieval outcome: fetched, partial_public, login_required, blocked, "
            "timeout, not_attempted, or unknown"
        ),
    )
    identity_status: str = Field(
        default="unverified",
        description="Evidence linkage status: unverified, candidate, corroborated, conflicting, or rejected",
    )
    publication_date: Optional[str] = Field(
        default=None, description="Publication date when explicitly available; never inferred"
    )
    retrieved_at: Optional[str] = Field(
        default=None, description="UTC retrieval timestamp recorded by the pipeline when available"
    )


class ProspectRecord(BaseModel):
    """Validated company-intelligence record suitable for prospect storage."""

    brand_name: str
    official_domain: Optional[str] = None
    legal_entity_name: Optional[str] = None
    jurisdiction: Optional[str] = None
    registration_number: Optional[str] = None
    company_description: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    identity_match_status: str = "inconclusive_verification"
    registration_verification_status: str = "inconclusive_verification"
    confidence: str = "low"
    unresolved_questions: List[str] = Field(default_factory=list)


class ResearchMemo(BaseModel):
    """Structured handoff produced by the researcher node for the writer node."""

    question: str = Field(description="Original research question")
    task_mode: str = Field(default="standard", description="standard or comparison")
    requested_outputs: List[str] = Field(
        default_factory=list,
        description="Requested output formats such as comparison_table or architecture_diagram",
    )
    search_plan: List[str] = Field(description="Queries executed during research")
    comparison_targets: List[str] = Field(
        default_factory=list, description="Named entities being compared"
    )
    summary: str = Field(description="High-level synthesis of findings")
    sources: List[ResearchSource] = Field(description="Evidence-bearing sources")
    open_questions: List[str] = Field(description="Unresolved issues or gaps")
    key_statistics: List[str] = Field(
        default_factory=list,
        description="Quantitative facts extracted verbatim: 'X% of Y, per [Source Title]'",
    )
    key_quotes: List[str] = Field(
        default_factory=list,
        description="Verbatim short quotes with attribution: '\"quote\" — Author/Source'",
    )
    source_quality_notes: str = Field(
        default="",
        description=(
            "Brief quality assessment: how many sources are peer-reviewed, vendor, news, blog, etc.; "
            "any notable recency gaps or bias concerns."
        ),
    )
    registry_verification: Dict[str, Any] = Field(default_factory=dict)
    identity_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    role_records: List[Dict[str, Any]] = Field(default_factory=list)
    dated_events: List[Dict[str, Any]] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    business_contacts: List[Dict[str, Any]] = Field(default_factory=list)
    search_failures: List[Dict[str, Any]] = Field(default_factory=list)
    fetch_failures: List[Dict[str, Any]] = Field(default_factory=list)
    run_status: str = Field(default="completed")
    india_verification: Dict[str, Any] = Field(default_factory=dict)


class ClaimRecord(BaseModel):
    """One report claim with evidence and quality labels."""

    claim: str = Field(description="A concise, specific claim answering part of the user's question")
    confidence: str = Field(description="High, Medium, or Low")
    source_agreement: str = Field(
        description="Strong agreement, Mixed, Conflicting, or Insufficient evidence"
    )
    evidence: List[str] = Field(description="Evidence bullets tied to this claim, with source attribution")


class ReportSection(BaseModel):
    """A thematic section of the final report with narrative prose and supporting claims."""

    title: str = Field(description="Section heading (e.g., 'Training Efficiency', 'Key Findings')")
    narrative: str = Field(
        description=(
            "2-3 paragraph synthesis prose for this theme. "
            "Must integrate evidence, name specific sources, and include inline statistics where available. "
            "Written for a technically literate reader."
        )
    )
    claims: List[ClaimRecord] = Field(
        description="Structured claims that anchor the narrative to evidence"
    )
    key_statistics: List[str] = Field(
        default_factory=list,
        description="Prominent numbers/percentages relevant to this section",
    )


class WriterReport(BaseModel):
    """Final structured report produced by the writer node."""

    question: str = Field(description="Original question")
    task_mode: str = Field(default="standard", description="standard or comparison")
    requested_outputs: List[str] = Field(default_factory=list)
    comparison_targets: List[str] = Field(default_factory=list)
    executive_summary: str = Field(
        description=(
            "3-5 sentence summary naming the single most important finding, "
            "the overall confidence level, and the key open uncertainty."
        )
    )
    sections: List[ReportSection] = Field(
        description=(
            "Thematic sections covering the full scope of the question. "
            "Each section has narrative prose plus structured claims. "
            "Use 3-6 sections for standard tasks; more for comprehensive research."
        )
    )
    recommendations: List[str] = Field(
        description=(
            "Concrete, actionable recommendations derived from the evidence. "
            "Each item should name who should act, what they should do, and why."
        )
    )
    methodology_notes: str = Field(
        description=(
            "How research was conducted: search backends used, number of sources, "
            "date range of sources, known gaps or limitations in the evidence base."
        )
    )
    confidence_summary: str = Field(
        description=(
            "Overall epistemic status: which conclusions are well-supported vs. tentative, "
            "what would change the assessment, and any important caveats."
        )
    )
    comparison_table_markdown: Optional[str] = Field(
        default=None, description="Markdown comparison table (only when requested)"
    )
    architecture_diagram_mermaid: Optional[str] = Field(
        default=None, description="Mermaid diagram (only when requested)"
    )
    open_questions: List[str] = Field(description="Remaining uncertainties worth further investigation")
    sources: List[str] = Field(description="Source citations as 'title — url' strings")
    registry_verification: Dict[str, Any] = Field(default_factory=dict)
    identity_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    role_records: List[Dict[str, Any]] = Field(default_factory=list)
    dated_events: List[Dict[str, Any]] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    business_contacts: List[Dict[str, Any]] = Field(default_factory=list)
    search_failures: List[Dict[str, Any]] = Field(default_factory=list)
    fetch_failures: List[Dict[str, Any]] = Field(default_factory=list)
    run_status: str = Field(default="completed")
    india_verification: Dict[str, Any] = Field(default_factory=dict)


class CritiqueResult(BaseModel):
    """Output of the critic node reviewing a draft report against source memos."""

    has_issues: bool = Field(
        description=(
            "True only if there are significant gaps, unsupported claims, or missed topics "
            "that meaningfully reduce report quality. Minor omissions should be False."
        )
    )
    unsupported_claims: List[str] = Field(
        default_factory=list,
        description="Claims in the report that are not backed by the provided memo evidence",
    )
    missing_topics: List[str] = Field(
        default_factory=list,
        description="Important topics well-covered in the memos but absent from the report",
    )
    contradictions: List[str] = Field(
        default_factory=list,
        description="Factual contradictions between different researchers' memos",
    )
    improvement_notes: str = Field(
        default="",
        description="Specific, actionable guidance for the revision pass",
    )


class SourceVerdict(BaseModel):
    """LLM output for one claim-vs-source check in verify_claims_node."""

    passed: bool = Field(
        description="True if source content supports or is consistent with the claim, even partially"
    )
    note: str = Field(description="One sentence: what was found or what is missing in the source")


class ClaimVerificationResult(BaseModel):
    """Outcome of verifying one low-confidence claim against its cited source URL."""

    claim: str = Field(description="The claim that was verified")
    section_title: str = Field(description="Report section the claim appears in")
    url_checked: str = Field(description="Source URL that was fetched for verification")
    passed: bool = Field(description="True if the source content supports the claim")
    note: str = Field(default="", description="What was found or missing in the source")
