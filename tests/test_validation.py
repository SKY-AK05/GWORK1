import json
from pathlib import Path

from src.validation import compare_snapshot, validate_product_artifacts


def test_snapshot_diff_distinguishes_first_and_changed_fields():
    first = compare_snapshot(None, {"brand_name": "ACME", "confidence": "low"})
    assert first["is_first_snapshot"] is True
    second = compare_snapshot({"brand_name": "ACME", "confidence": "low"}, {"brand_name": "ACME", "confidence": "medium"})
    assert second["changed_fields"] == ["confidence"]


def test_product_artifact_validation_accepts_schema_and_sources(tmp_path: Path):
    (tmp_path / "company_research_report.md").write_text("# Report\n\n## Sources\n", encoding="utf-8")
    (tmp_path / "company_research.json").write_text(json.dumps({
        "schema_version": "1.0", "run_id": "r1", "question": "q", "executive_summary": "s",
        "sections": [], "sources": [], "run_status": "completed",
    }), encoding="utf-8")
    (tmp_path / "sources.json").write_text(json.dumps({"schema_version": "1.0", "sources": [{"url": "https://example.com"}]}), encoding="utf-8")
    (tmp_path / "run_metadata.json").write_text("{}", encoding="utf-8")
    result = validate_product_artifacts(tmp_path)
    assert result["valid"] is True
    assert result["source_count"] == 1
