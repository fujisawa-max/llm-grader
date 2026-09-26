from pathlib import Path

from scoring.model_answer_import import (
    SOURCES, _source_rubric_draft, validate_source,
)


def test_all_model_answer_sources_are_exact_files_and_pdf():
    rows = [validate_source(spec) for spec in SOURCES]
    assert [row["sample"] for row in rows] == ["sampleQ1", "sampleQ2", "sampleQ3", "sampleQ4"]
    assert all(row["page_count"] == 1 for row in rows)
    assert all(len(row["sha256"]) == 64 for row in rows)
    assert all("modelAnswer" in row["filename"] for row in rows)


def test_q1_explicit_points_are_preserved():
    draft = _source_rubric_draft("sampleQ1", "3.1", 10, "5点、5点")
    assert [c["points"] for c in draft["criteria"]] == [5, 5]
    assert all(c["source_kind"] == "EXPLICIT_SOURCE" for c in draft["criteria"])
    assert draft["review_required"] is False


def test_q2_ambiguous_points_remain_unresolved():
    draft = _source_rubric_draft("sampleQ2", "1.1", None, "5点ないし10点")
    assert any(c["points"] is None for c in draft["criteria"])
    assert draft["review_required"] is True


def test_q4_does_not_normalize_total_to_100():
    values = [_source_rubric_draft("sampleQ4", key, points, "source")
              for key, points in (("1", 30), ("2.1", 20), ("2.2", 20), ("3", 40))]
    assert sum(x["authoritative_max_points"] for x in values) == 110


def test_source_module_has_no_student_input_contract():
    source = Path("src/scoring/model_answer_import.py").read_text(encoding="utf-8")
    assert "StudentSubmission" not in source
    assert "GradingJob" not in source
