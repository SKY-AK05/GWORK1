"""LangSmith-based evaluation for the deep-research pipeline.

Provides a `run_langsmith_evaluation` helper that:
1. Creates (or reuses) a LangSmith dataset from local report/memo files
2. Runs the full research graph against each example
3. Scores each run with the rubric-based `OfflineReportEvaluator`
4. Surfaces aggregate scores via the LangSmith UI

Usage:
    from src.evaluation.langsmith_eval import run_langsmith_evaluation
    results = await run_langsmith_evaluation(
        dataset_name="deep-research-eval",
        examples=[{"task": "What is RAG?"}],
        model_name="openai/gpt-4o",
    )

Set LANGCHAIN_API_KEY and LANGCHAIN_TRACING_V2=true in your environment
before calling this function.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from langsmith import Client
from langsmith.evaluation import evaluate
from langsmith.schemas import Example, Run

from src.evaluation.report_quality import OfflineReportEvaluator, ReportQualityEvaluation
from src.graph.graph import build_research_graph


# ─── Target function ───────────────────────────────────────────────────── #

def _run_research_pipeline(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous wrapper used by LangSmith's evaluate() helper."""
    task = inputs["task"]
    model_name = inputs.get("model_name", "openrouter/gemini-3-flash-preview")
    workdir = inputs.get("workdir", "workdir/langsmith_eval")

    graph = build_research_graph()
    initial_state = {
        "task": task,
        "workdir": workdir,
        "model_name": model_name,
        "task_mode": "standard",
        "comparison_targets": [],
        "requested_outputs": [],
        "search_plan": [],
        "search_results": [],
        "fetched_pages": [],
        "memo": None,
        "report": None,
        "memo_path": None,
        "memo_paths": None,
        "report_path": None,
        "report_pdf_path": None,
        "diagram_path": None,
        "error": None,
    }

    result = asyncio.run(graph.ainvoke(initial_state))
    report_md = ""
    if result.get("report_path"):
        try:
            with open(result["report_path"], "r", encoding="utf-8") as f:
                report_md = f.read()
        except OSError:
            pass

    return {
        "report_text": report_md,
        "memo_path": result.get("memo_path"),
        "report_path": result.get("report_path"),
        "error": result.get("error"),
    }


# ─── Evaluator ─────────────────────────────────────────────────────────── #

def _make_quality_evaluator(model_name: str):
    """Return a LangSmith-compatible evaluator closure."""

    def quality_evaluator(run: Run, example: Example) -> Dict[str, Any]:
        report_text = (run.outputs or {}).get("report_text", "")
        task_query = (example.inputs or {}).get("task", "")

        if not report_text:
            return {"key": "overall_score", "score": 0.0, "comment": "No report generated."}

        evaluator = OfflineReportEvaluator(model_name=model_name)
        result: ReportQualityEvaluation = asyncio.run(
            evaluator.evaluate(task_query=task_query, report_text=report_text)
        )

        return {
            "key": "overall_score",
            "score": result.overall_score / 5.0,
            "comment": result.verdict,
        }

    return quality_evaluator


# ─── Public API ────────────────────────────────────────────────────────── #

def run_langsmith_evaluation(
    *,
    dataset_name: str,
    examples: List[Dict[str, Any]],
    model_name: str = "openrouter/gemini-3-flash-preview",
    judge_model: str = "openai/gpt-4o",
    experiment_prefix: str = "deep-research",
) -> Any:
    """Create a LangSmith dataset and run a rubric evaluation experiment.

    Args:
        dataset_name:      Name of the LangSmith dataset to create or reuse.
        examples:          List of input dicts, each with at least {"task": "..."}.
        model_name:        Model used to run the research pipeline.
        judge_model:       Model used to judge report quality.
        experiment_prefix: Prefix for the LangSmith experiment run name.

    Returns:
        LangSmith evaluation results object.
    """
    client = Client()

    # Create or update dataset
    if not client.has_dataset(dataset_name=dataset_name):
        dataset = client.create_dataset(dataset_name=dataset_name)
    else:
        dataset = client.read_dataset(dataset_name=dataset_name)

    # Upsert examples
    client.create_examples(
        inputs=[{"task": ex["task"], "model_name": model_name, **ex} for ex in examples],
        dataset_id=dataset.id,
    )

    results = evaluate(
        _run_research_pipeline,
        data=dataset_name,
        evaluators=[_make_quality_evaluator(judge_model)],
        experiment_prefix=experiment_prefix,
        metadata={"model_name": model_name, "judge_model": judge_model},
    )

    return results
