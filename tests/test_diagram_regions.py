from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pymupdf
import pytest

from scoring.adapters.artifacts import RunArtifactAdapter
from scoring.diagram_regions import DiagramRegionExtractor, diagram_groups, validate_grouping
from scoring.diagram_sources import question_diagram_candidates, model_answer_diagram_candidates
from scoring.pdf_native import PyMuPdfNativeExtractor, sha256_file


@pytest.fixture
def source():
    with TemporaryDirectory() as folder:
        root = Path(folder)
        pdf = root / "source.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page(width=400, height=500)
            page.insert_text((30, 35), "Question 3. Draw the boundary.")
            page.draw_line((70, 160), (230, 160))
            page.draw_line((150, 80), (150, 240))
            for x in (110, 130, 170, 190):
                page.draw_line((x, 157), (x, 163))
            page.insert_text((153, 157), "O", fontsize=8)
            page.insert_text((30, 270), "Unrelated explanatory prose stays outside.")
            page.draw_rect((290, 330, 350, 390))
            doc.save(pdf)
        ir = PyMuPdfNativeExtractor().extract(pdf, source_sha256=sha256_file(pdf),
            material_id="material-diagram", output_dir=root / "native").as_dict()
        yield pdf, ir, RunArtifactAdapter(root)


def ownership(ir):
    return {0: [e["element_id"] for e in ir["pages"][0]["vector_elements"]
                + ir["pages"][0]["elements"]]}


def extractor(source):
    return DiagramRegionExtractor(*source)


def candidates(source, domain="question"):
    return extractor(source).candidates(domain=domain, target_key="q3", ownership=ownership(source[1]))


def test_native_zero_area_axes_and_tick_marks_retained(source):
    vectors = source[1]["pages"][0]["vector_elements"]
    assert len(vectors) == 7
    assert vectors[0]["bbox"][1] == vectors[0]["bbox"][3]
    assert vectors[0]["native"]["horizontal_lines"] == 1
    assert vectors[1]["native"]["vertical_lines"] == 1


def test_axes_are_one_region_and_second_diagram_remains_separate(source):
    result = candidates(source)
    assert len(result) == 2
    assert result[0]["bbox"] == [70, 80, 230, 240]
    assert len(result[0]["source_element_ids"]) == 7  # axes, four ticks, O
    assert result[1]["bbox"] == [290, 330, 350, 390]
    assert not result[0]["ricoh_used"]


def test_nearby_prose_is_not_included(source):
    result = candidates(source)[0]
    text = [e for e in source[1]["pages"][0]["elements"] if e["type"] == "text"]
    assert all(e["element_id"] not in result["source_element_ids"] for e in text
               if len(e["native_text"]) > 12)


def test_question_and_model_answer_have_distinct_identity(source):
    question, answer = candidates(source)[0], candidates(source, "model_answer")[0]
    assert question["id"] != answer["id"]
    assert question["source_element_ids"] == answer["source_element_ids"]
    assert question["domain"] == "question"
    assert answer["domain"] == "model_answer"


def test_source_order_does_not_change_identity(source):
    result = candidates(source)
    ir = deepcopy(source[1])
    ir["pages"][0]["vector_elements"].reverse()
    other = (source[0], ir, source[2])
    reordered = candidates(other)
    # The raw IR hash records its ordering, but diagram identity and evidence
    # projection must remain stable under nonsemantic source array order.
    assert [{k: v for k, v in r.items() if k != "source_ir_sha256"} for r in reordered] == [
        {k: v for k, v in r.items() if k != "source_ir_sha256"} for r in result]


def test_unowned_sibling_diagram_not_available(source):
    ir = source[1]
    allowed = ownership(ir)
    allowed[0] = [e["element_id"] for e in ir["pages"][0]["vector_elements"]
                  if e["bbox"][1] < 300]
    result = extractor(source).candidates(domain="question", target_key="child", ownership=allowed)
    assert len(result) == 1
    assert result[0]["bbox"][3] < 300


def test_shared_exclusive_source_fails_closed(source):
    allowed = ownership(source[1])
    with pytest.raises(ValueError, match="diagram_shared_source_unresolved"):
        extractor(source).candidates(domain="question", target_key="child", ownership=allowed,
                                     exclusions={0: allowed[0][:1]})


def test_sibling_primitive_touching_region_fails_closed(source):
    page = source[1]["pages"][0]
    vectors = page["vector_elements"]
    allowed = [e["element_id"] for e in vectors if e != vectors[2]]
    with pytest.raises(ValueError, match="diagram_source_boundary"):
        diagram_groups(page, allowed_ids=allowed, excluded_ids=[vectors[2]["element_id"]])


def test_clean_geometry_does_not_call_grouping(source):
    def forbidden(_):
        pytest.fail("clean geometry must not call a model")
    result = extractor(source).candidates(domain="question", target_key="q3",
                                          ownership=ownership(source[1]), grouping=forbidden)
    assert len(result) == 2


def test_grid_is_unresolved_without_assistance(source):
    page = deepcopy(source[1]["pages"][0])
    page["vector_elements"][0]["native"].update(horizontal_lines=3, vertical_lines=3)
    result = diagram_groups(page, allowed_ids=ownership(source[1])[0])
    assert result[0]["status"] == "unresolved"
    assert result[0]["reason_code"] == "diagram_geometry_ambiguous"


def test_ambiguous_grouping_uses_only_known_ids(source):
    page = deepcopy(source[1]["pages"][0])
    page["vector_elements"][0]["native"].update(horizontal_lines=3, vertical_lines=3)
    calls = []
    def group(elements):
        calls.append(elements)
        return {"groups": [{"element_ids": [e["element_id"] for e in elements], "confidence": .95}]}
    result = diagram_groups(page, allowed_ids=ownership(source[1])[0], grouping=group)
    assert len(calls) == 1
    assert result[0]["grouping_method"] == "geometry_assisted"
    assert result[0]["bbox"] == [70, 80, 230, 240]


@pytest.mark.parametrize("value", [
    '{"groups":[',
    {"groups": [{"element_ids": ["invented"], "confidence": .99}]},
    {"groups": [{"element_ids": ["a", "a"], "confidence": .99}]},
    {"groups": [{"element_ids": ["a"], "confidence": .5}]},
    {"groups": [{"element_ids": ["a"], "confidence": .99, "bbox": [0, 0, 10, 10]}]},
    {"groups": [{"element_ids": ["a"], "confidence": float("nan")}]},
])
def test_invalid_grouping_not_trusted(value):
    with pytest.raises(ValueError, match="diagram_ricoh_low_confidence" if isinstance(value, dict) and value.get("groups", [{}])[0].get("confidence") == .5 else "diagram_grouping_invalid"):
        validate_grouping(value, {"a"})


def test_crop_padding_sha_cached_artifact_and_manual_provenance(source):
    engine = extractor(source)
    candidate = candidates(source)[0]
    crop = engine.crop(candidate)
    assert crop["crop_bbox"] == [64, 74, 236, 246]
    assert crop["crop_width"] == crop["crop_height"] == 344
    assert source[2].checksum(crop["artifact_ref"]) == crop["crop_sha256"]
    assert engine.crop(candidate) == crop
    adjusted = engine.crop(candidate, final_bbox=[65, 75, 240, 245])
    assert adjusted["teacher_adjusted"]
    assert adjusted["automatic_bbox"] == candidate["bbox"]
    assert adjusted["final_bbox"] == [65, 75, 240, 245]
    assert adjusted["source_element_ids"] == candidate["source_element_ids"]


def test_padding_clamps_to_page(source):
    candidate = candidates(source)[0]
    result = extractor(source).crop(candidate, final_bbox=[0, 0, 100, 100])
    assert result["crop_bbox"][:2] == [0, 0]


@pytest.mark.parametrize("box", [[-1, 0, 100, 100], [0, 0, 401, 100],
                                 [0, 0, 100, 501], [20, 20, 10, 10], [0, 0, float("nan"), 10]])
def test_manual_invalid_bounds_rejected(source, box):
    with pytest.raises(ValueError):
        extractor(source).crop(candidates(source)[0], final_bbox=box)


def test_whole_page_crop_rejected(source):
    with pytest.raises(ValueError, match="crop_limits_exceeded"):
        extractor(source).crop(candidates(source)[0], final_bbox=[0, 0, 400, 500])


def test_pdf_hash_mismatch_rejected(source):
    ir = deepcopy(source[1])
    ir["source"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="diagram_source_integrity_error"):
        DiagramRegionExtractor(source[0], ir, source[2])


def test_pdf_changed_after_engine_created_rejected(source):
    engine = extractor(source)
    candidate = candidates(source)[0]
    source[0].write_bytes(b"changed source")
    with pytest.raises(ValueError, match="diagram_source_integrity_error"):
        engine.crop(candidate)


def test_artifact_corruption_rejected(source):
    engine = extractor(source)
    candidate = candidates(source)[0]
    crop = engine.crop(candidate)
    source[2].path(crop["artifact_ref"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="diagram_artifact_integrity_error"):
        engine.crop(candidate)


def test_artifact_path_traversal_rejected(source):
    with pytest.raises(ValueError):
        source[2].path("../../outside.png")


def question_service(source, *, shared=False):
    figure = {"type": "figure_region", "region_id": "figure-1"}
    child = {"stable_key": "child", "included": True, "source_review_owner": "automatic",
             "ordered_content": [figure]}
    sibling = {"stable_key": "sibling", "included": True, "source_review_owner": "automatic",
               "ordered_content": [figure] if shared else []}
    automatic = {"nodes": [{"stable_key": "automatic", "ordered_content": [figure]}],
                 "figure_regions": [{"region_id": "figure-1", "page_index": 0,
                     "assigned_question_key": "automatic", "bbox": [70, 80, 230, 240]}]}
    return SimpleNamespace(
        _review=lambda _: SimpleNamespace(current_revision=2, draft_id="draft"),
        _draft=lambda _: (None, source[2], automatic, source[1]),
        _revision=lambda *_: SimpleNamespace(snapshot={"nodes": [child, sibling]}))


def test_question_adapter_uses_transformed_owner_and_does_not_borrow_sibling(source):
    engine, result = question_diagram_candidates(question_service(source), "review", "child", 2)
    assert len(result) == 1
    assert result[0]["domain"] == "question"
    assert result[0]["target_key"] == "child"
    assert result[0]["bbox"] == [70, 80, 230, 240]
    assert engine.crop(result[0])["crop_sha256"]
    _, sibling = question_diagram_candidates(question_service(source), "review", "sibling", 2)
    assert sibling == []


def test_question_adapter_shared_atomic_figure_is_unresolved(source):
    with pytest.raises(ValueError, match="diagram_shared_source_unresolved"):
        question_diagram_candidates(question_service(source, shared=True), "review", "child", 2)


def test_question_adapter_stale_revision_rejected(source):
    with pytest.raises(ValueError, match="diagram_revision_conflict"):
        question_diagram_candidates(question_service(source), "review", "child", 1)


def test_model_answer_adapter_uses_exact_persisted_question_boundary(source):
    region = {"question_id": "q3", "page_index": 0, "left": 20, "right": 250,
              "top": 50, "bottom": 280, "depth": 1}
    sibling = {"question_id": "q4", "page_index": 0, "left": 20, "right": 400,
               "top": 300, "bottom": 450, "depth": 1}
    _, result = model_answer_diagram_candidates(*source,
        entry={"question_id": "q3", "source": {}}, question_regions=[region, sibling])
    assert len(result) == 1
    assert result[0]["domain"] == "model_answer"
    assert result[0]["bbox"] == [70, 80, 230, 240]


def test_model_answer_adapter_missing_mapping_not_guessed(source):
    with pytest.raises(ValueError, match="diagram_source_mapping_missing"):
        model_answer_diagram_candidates(*source, entry={"question_id": None}, question_regions=[])


def test_embedded_native_image_is_candidate(source):
    page = deepcopy(source[1]["pages"][0])
    page["elements"].append({"element_id": "embedded", "type": "image", "bbox": [10, 330, 100, 400]})
    result = diagram_groups(page, allowed_ids=["embedded"])
    assert len(result) == 1
    assert result[0]["source_element_ids"] == ["embedded"]


def test_candidate_count_limit(source):
    page = deepcopy(source[1]["pages"][0])
    page["elements"] = [{"element_id": f"img-{n}", "type": "image", "bbox": [n*60, 0, n*60+30, 30]}
                        for n in range(17)]
    page["vector_elements"] = []
    with pytest.raises(ValueError, match="diagram_region_limit"):
        diagram_groups(page, allowed_ids=[e["element_id"] for e in page["elements"]])
