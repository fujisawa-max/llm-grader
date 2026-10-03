import json
from unittest.mock import patch

import pytest

from scoring.rubric_split import reconstruct_split, validate_split
from scoring.api.model_answer_imports import validate_rubric_edits
from scoring.model_answer_classification import ModelAnswerSemanticClassifier


def proposal(text, cuts, **patches):
    offsets = [0, *cuts, len(text)]
    return {"candidate_id": "c", "split": bool(cuts), "confidence": .95, "reason": "independent_criteria",
            "parts": [{"start": a, "end": b} for a, b in zip(offsets, offsets[1:])] if cuts else [], **patches}


@pytest.mark.parametrize("text,cut,points", [
    ("Aが説明されている（10点）。Bを示している（10点）。", 16, [10, 10]),
    ("A (5点).B 【5点】.", 7, [5, 5]),
    ("AとB（20点）", 2, [0, 0]),
    ("A。B。", 2, [0, 0]),
    ("A（5点）（10点）。B（5点）", 11, [0, 5]),
    ("5 points: A. 5 points: B.", 13, [5, 5]),
])
def test_exact_reconstruction_and_point_safety(text, cut, points):
    result = reconstruct_split(proposal(text, [cut]), "c", text)
    assert "".join(part["source_text"] for part in result["parts"]) == text
    assert [part["points"] for part in result["parts"]] == points


def test_unicode_latex_three_parts_preserved():
    text = "α😀。$\\frac{TP}{FN}$。未知データ。"
    raw = proposal(text, [3, text.index("未知")])
    result = reconstruct_split(raw, "c", text)
    assert "".join(part["source_text"] for part in result["parts"]) == text


@pytest.mark.parametrize("raw", [None, {}, {"candidate_id": "other"}, {"confidence": float("nan")},
    {"parts": [{"start": 0, "end": 3}, {"start": 2, "end": 4}]},
    {"parts": [{"start": 0, "end": 2}, {"start": 3, "end": 4}]},
    {"parts": [{"start": 0, "end": 2}, {"start": 2, "end": 8}]},
    {"parts": [{"start": 0, "end": 0}, {"start": 0, "end": 4}]},
    {"parts": [{"start": 0, "end": 2}]}, {"text": "invented"}])
def test_invalid_model_ranges_rejected(raw):
    payload = proposal("abcd", [2])
    if isinstance(raw, dict) and raw:
        payload.update(raw)
    else:
        payload = raw
    with pytest.raises(ValueError):
        validate_split(payload, "c", "abcd")


def test_whitespace_part_rejected():
    with pytest.raises(ValueError):
        validate_split(proposal("  ab", [2]), "c", "  ab")


@pytest.mark.parametrize("text", ["A and B jointly (10点)", "A wrapped\nover two lines (10点)"])
def test_no_split_preserves_single_semantic_criterion(text):
    assert reconstruct_split(proposal(text, []), "c", text)["parts"] == []


def test_disjoint_split_sources_and_duplicate_and_manual_allowed_overlap_rejected():
    classification = {"segments": [{"id": "s", "category": "rubric"}]}
    items = [{"id": str(i), "segment_ids": ["s"], "provenance": {
        "split_from_candidate_id": "c", "original_text": "abcd", "start": i * 2, "end": i * 2 + 2}}
        for i in range(2)]
    validate_rubric_edits(items, classification)
    with pytest.raises(ValueError):
        validate_rubric_edits([items[0], {**items[0], "id": "overlap"}], classification)
    validate_rubric_edits([items[0], {**items[0], "id": "copy", "provenance": {"manual_duplicate_from": "0"}}], classification)
    validate_rubric_edits([{"id": "manual", "segment_ids": [], "grouping_method": "teacher_manual"}], classification)
    with pytest.raises(ValueError):
        validate_rubric_edits([{"id": "fake", "segment_ids": ["foreign"]}], classification)


def test_runtime_split_returns_only_ranges_reuses_profile_and_never_stops():
    class Manager:
        def ensure_running(self, profile):
            assert profile == "ornith_rubric_draft"
            return {"endpoint": "http://runtime/v1", "profile": {"model_id": "model", "generation": {}}}

    class Client:
        generation = {"temperature": 0, "seed": 1, "top_k": 1, "top_p": 1, "min_p": 0,
                      "repeat_penalty": 1, "max_output_tokens": 512}
        def __init__(self, *_):
            pass
        def request(self, url, request):
            data = json.loads(request["messages"][1]["content"])
            assert data["explicit_point_spans"]
            assert request["response_format"]["json_schema"]["name"] == "rubric_semantic_split"
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal(data["text"], [7]))}}]}

    with patch("scoring.model_answer_classification.LocalClient", Client):
        result = ModelAnswerSemanticClassifier(Manager()).suggest_rubric_split(
            candidate_id="c", text="A（5点）。B（5点）。", question_label="問題1", segment_ids=["s"])
    assert result["split"]


def test_split_api_is_proposal_only_checks_revision_and_keeps_failed_draft(tmp_path):
    from fastapi import HTTPException
    from scoring.api import create_app
    from scoring.api.model_answer_imports import ClassificationRequest, ImportCreate
    from scoring.db.models import ModelAnswerImportDraft
    from tests.test_model_answer_import_api import ModelAnswerImportApiTests, _endpoint

    calls = []
    class Classifier:
        def suggest_rubric_split(self, **kwargs):
            calls.append(kwargs)
            return reconstruct_split(proposal(kwargs["text"], [2]), kwargs["candidate_id"], kwargs["text"])

    root = tmp_path.resolve()
    factory, test_id, material_id, *_ = ModelAnswerImportApiTests().make_fixture(root, "Question 1\nAnswer one")
    with patch.dict("os.environ", {"LLM_GRADER_ARTIFACT_ROOT": str(root)}):
        app = create_app(factory, question_import_root=root / "question-imports", allowed_roots=[root],
                         model_answer_classifier=Classifier())
    create = _endpoint(app, "/api/v1/tests/{test_id}/model-answer-imports")
    suggest = _endpoint(app, "/api/v1/model-answer-import-drafts/{draft_id}/rubric-candidates/{candidate_id}/split-suggest")
    with factory() as session:
        draft = create(test_id, ImportCreate(material_id=material_id), session)
        row = session.get(ModelAnswerImportDraft, draft["id"])
        entry = row.snapshot["entries"][0]
        entry = {**entry, "rubric_edits": [{"id": "c", "description": "abcd", "points": 10,
                                            "source_text": "abcd", "segment_ids": []}]}
        row.snapshot = {**row.snapshot, "entries": [entry]}
        session.commit()
        result = suggest(draft["id"], "c", ClassificationRequest(expected_revision=1), session)
        assert [part["source_text"] for part in result["parts"]] == ["ab", "cd"]
        assert row.revision == 1 and row.snapshot["entries"][0]["rubric_edits"][0]["description"] == "abcd"
        assert len(calls) == 1
        with pytest.raises(HTTPException) as stale:
            suggest(draft["id"], "c", ClassificationRequest(expected_revision=2), session)
        assert stale.value.status_code == 409 and len(calls) == 1
        with pytest.raises(HTTPException) as missing:
            suggest(draft["id"], "unknown", ClassificationRequest(expected_revision=1), session)
        assert missing.value.status_code == 404 and len(calls) == 1
        with patch.object(Classifier, "suggest_rubric_split", side_effect=TimeoutError()):
            with pytest.raises(HTTPException) as unavailable:
                suggest(draft["id"], "c", ClassificationRequest(expected_revision=1), session)
            assert unavailable.value.status_code == 503
        assert row.revision == 1


def test_nested_split_overlap_claims_and_manual_lineage():
    classification = {"segments": [{"id": "s", "category": "rubric"}]}
    parent = {"split_from_candidate_id": "root", "original_text": "abcdef", "start": 0, "end": 4}
    first = {"id": "a", "segment_ids": ["s"], "provenance": {
        "split_from_candidate_id": "parent", "original_text": "abcd", "start": 0, "end": 2,
        "previous_operation": parent}}
    second = {"id": "b", "segment_ids": ["s"], "provenance": {
        "split_from_candidate_id": "parent", "original_text": "abcd", "start": 2, "end": 4,
        "previous_operation": parent}}
    tail = {"id": "tail", "segment_ids": ["s"], "provenance": {
        "split_from_candidate_id": "root", "original_text": "abcdef", "start": 4, "end": 6}}
    validate_rubric_edits([first, second, tail], classification)
    validate_rubric_edits([{**first, "segment_ids": [], "provenance": {**first["provenance"], "source": "teacher_manual"}}], classification)
    with pytest.raises(ValueError):
        validate_rubric_edits([first, {**second, "provenance": {**second["provenance"], "previous_operation": "invalid"}}], classification)
