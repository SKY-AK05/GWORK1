"""Tests for the offline report evaluator."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.evaluation.report_quality import (
    OfflineReportEvaluator,
    ReportDimensionScore,
    ReportQualityEvaluation,
)


def _fake_evaluation() -> ReportQualityEvaluation:
    dim = lambda score, rationale: ReportDimensionScore(score=score, rationale=rationale)
    return ReportQualityEvaluation(
        task_alignment=dim(5, "Directly answers the task."),
        coverage=dim(4, "Covers the major points."),
        evidence_grounding=dim(4, "Claims are supported by cited evidence."),
        factual_consistency=dim(4, "No major contradictions are visible."),
        clarity_structure=dim(5, "The report is clearly organized."),
        actionability=dim(4, "The report is usable for follow-up decisions."),
        overall_score=4.3,
        strengths=["Strong claim-evidence separation."],
        weaknesses=["Some residual uncertainty remains."],
        missing_items=["Could include a clearer limitations note."],
        verdict="The report is useful and aligned with the task.",
    )


def test_offline_report_evaluator_reads_task_and_report():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "final_report.md"
            report_path.write_text(
                "# Final Report\n\n## Executive Summary\n\n"
                "Chain-of-thought helps on multi-step tasks.\n\n"
                "## Sources\n\n- Source One - https://example.com\n",
                encoding="utf-8",
            )

            fake_structured = MagicMock()
            fake_structured.ainvoke = AsyncMock(return_value=_fake_evaluation())
            fake_llm = MagicMock()
            fake_llm.with_structured_output.return_value = fake_structured

            with patch("src.evaluation.report_quality.get_llm", return_value=fake_llm):
                evaluator = OfflineReportEvaluator(model_name="stub-model")
                evaluation = await evaluator.evaluate_from_files(
                    task_query="Is chain-of-thought prompting effective?",
                    report_path=str(report_path),
                )

            assert evaluation.overall_score == 4.3
            assert evaluation.task_alignment.score == 5
            assert "aligned with the task" in evaluation.verdict

    asyncio.run(_run())
