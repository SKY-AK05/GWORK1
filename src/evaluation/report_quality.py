"""Offline final-report quality evaluation using LangChain LLMs."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.llm.factory import get_llm


class ReportDimensionScore(BaseModel):
    score: int = Field(description="Integer score from 1 to 5")
    rationale: str = Field(description="Short explanation for the score")


class ReportQualityEvaluation(BaseModel):
    """Structured offline evaluation of a final report."""

    task_alignment: ReportDimensionScore = Field(
        description="How well the report answers the original task"
    )
    coverage: ReportDimensionScore = Field(
        description="How completely the report covers important subquestions"
    )
    evidence_grounding: ReportDimensionScore = Field(
        description="How well claims are supported by cited evidence"
    )
    factual_consistency: ReportDimensionScore = Field(
        description="Whether the report avoids unsupported leaps and contradictions"
    )
    clarity_structure: ReportDimensionScore = Field(
        description="How clear, organised, and easy to use the report is"
    )
    actionability: ReportDimensionScore = Field(
        description="How decision-useful or actionable the report is"
    )
    overall_score: float = Field(description="Overall score from 1.0 to 5.0")
    strengths: List[str] = Field(description="Top strengths of the report")
    weaknesses: List[str] = Field(description="Top weaknesses or risks")
    missing_items: List[str] = Field(
        description="Important missing pieces relative to the task"
    )
    verdict: str = Field(
        description="One-paragraph verdict on whether the report is good enough for use"
    )


class OfflineReportEvaluator:
    """Evaluate a generated final report after the main run completes."""

    def __init__(self, model_name: str):
        self.model_name = model_name

    @staticmethod
    def _extract_sources(report_text: str) -> List[str]:
        lines = report_text.splitlines()
        sources: List[str] = []
        in_sources = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## "):
                in_sources = stripped.lower() == "## sources"
                continue
            if in_sources and stripped.startswith("- "):
                sources.append(stripped[2:].strip())
        return sources

    @staticmethod
    def _extract_basic_metrics(task_query: str, report_text: str) -> Dict[str, Any]:
        task_terms = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", task_query)
        }
        report_terms = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", report_text)
        }
        overlapping = sorted(task_terms & report_terms)
        sources = OfflineReportEvaluator._extract_sources(report_text)
        headers = [
            line.strip()
            for line in report_text.splitlines()
            if line.strip().startswith("## ")
        ]
        return {
            "task_term_count": len(task_terms),
            "report_word_count": len(report_text.split()),
            "task_term_overlap_count": len(overlapping),
            "task_term_overlap_sample": overlapping[:20],
            "source_count": len(sources),
            "section_headers": headers,
            "has_executive_summary": "## Executive Summary" in headers,
            "has_sources_section": "## Sources" in headers,
            "has_open_questions": "## Open Questions" in headers,
        }

    async def evaluate(
        self,
        *,
        task_query: str,
        report_text: str,
        research_memo_text: Optional[str] = None,
    ) -> ReportQualityEvaluation:
        """Run an offline LLM judge pass over the final report."""
        metrics = self._extract_basic_metrics(task_query=task_query, report_text=report_text)

        prompt_parts = [
            "Evaluate the final report against the original task.",
            "Score each dimension from 1 to 5.",
            "Be strict — missing evidence, vague recommendations, and unsupported claims are real weaknesses.",
            "Use heuristic metrics only as supplemental context, not as ground truth.",
            "",
            "Original task:",
            task_query,
            "",
            "Heuristic metrics:",
            str(metrics),
            "",
        ]
        if research_memo_text:
            prompt_parts += ["Optional research memo context:", research_memo_text, ""]
        prompt_parts += ["Final report:", report_text]

        llm = get_llm(self.model_name)
        structured_llm = llm.with_structured_output(ReportQualityEvaluation)

        result: ReportQualityEvaluation = await structured_llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are an offline evaluation judge for research reports.\n"
                        "Judge report quality relative to the original task.\n"
                        "Do not reward style when alignment or evidence is weak.\n"
                        "Return structured JSON only."
                    )
                ),
                HumanMessage(content="\n".join(prompt_parts)),
            ]
        )
        return result

    async def evaluate_from_files(
        self,
        *,
        task_query: str,
        report_path: str,
        research_memo_path: Optional[str] = None,
    ) -> ReportQualityEvaluation:
        with open(report_path, "r", encoding="utf-8") as f:
            report_text = f.read()

        memo_text: Optional[str] = None
        if research_memo_path and os.path.exists(research_memo_path):
            with open(research_memo_path, "r", encoding="utf-8") as f:
                memo_text = f.read()

        return await self.evaluate(
            task_query=task_query,
            report_text=report_text,
            research_memo_text=memo_text,
        )


ReportQualityEvaluation.model_rebuild()
