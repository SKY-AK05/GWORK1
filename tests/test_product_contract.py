import json
from pathlib import Path

from app.__main__ import _build_task, _parser, _slug
from src.graph.nodes import _save_product_manifests
from src.schemas.research import ResearchMemo, ResearchSource, WriterReport


def test_cli_requires_company_and_country_and_builds_scoped_task():
    args = _parser().parse_args(["research", "--company", "ORCHVATE", "--country", "India", "--depth", "quick"])
    task = _build_task(args)
    assert args.depth == "quick"
    assert "ORCHVATE" in task and "India" in task
    assert _slug("A/B Company") == "a-b-company"


def test_manifest_exports_are_schema_versioned(tmp_path: Path):
    source = ResearchSource(title="Site", url="https://example.com", evidence=["fact"])
    memo = ResearchMemo(question="Research ACME in India", search_plan=["ACME India"], summary="summary", sources=[source], open_questions=[])
    report = WriterReport(
        question=memo.question,
        executive_summary="summary",
        sections=[],
        recommendations=[],
        methodology_notes="test",
        confidence_summary="medium",
        open_questions=[],
        sources=["[1] Site — https://example.com"],
    )
    paths = _save_product_manifests(
        {"task": memo.question, "depth": "brief", "model_name": "test", "writer_model_name": None, "session_id": "run-1", "search_plan": ["ACME India"], "coverage_summary": {}, "search_failures": [], "fetch_failures": [], "registry_verification": {}},
        report,
        memo,
        str(tmp_path),
    )
    assert set(paths) == {
        "company_report_path", "company_json_path", "sources_json_path", "run_metadata_path",
        "snapshot_path", "changes_path",
    }
    assert json.loads(Path(paths["company_json_path"]).read_text())["schema_version"] == "1.0"
    assert json.loads(Path(paths["sources_json_path"]).read_text())["sources"][0]["url"] == "https://example.com"
    assert json.loads(Path(paths["run_metadata_path"]).read_text())["run_id"] == "run-1"
