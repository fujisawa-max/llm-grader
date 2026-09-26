"""H.3-G.0e smoke: use native Question anchors to detect handwritten answers."""
import json
import re
import sys
import time
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).parent))
from run_h3g_batch import MANIFEST, manager_setup

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.region_ownership import classify_regions
from scoring.student_answer_runtime import RuntimeStudentAnswerStages


def _compact(value):
    return re.sub(r"[\s\W_]+", "", value or "", flags=re.UNICODE)


def _question_ref(question_number):
    bits = str(question_number).split(".")
    return f"問題{bits[0]}" if len(bits) == 1 else f"問題{bits[0]} ({bits[1]})"


def _native_question_anchors(session, test_id):
    """Build anchors from the corrected Question PDF's native text layer.

    The previous Ricoh page artifact is deliberately not used as an anchor:
    it is model evidence and may contain printed text or a bad region.
    """
    extraction = session.scalar(select(m.QuestionImportExtraction).join(
        m.TestMaterial, m.TestMaterial.id == m.QuestionImportExtraction.material_id
    ).where(m.QuestionImportExtraction.test_id == test_id,
            m.TestMaterial.material_type == "corrected_question_sheet")
        .order_by(m.QuestionImportExtraction.created_at.desc()))
    if extraction is None:
        raise RuntimeError("CORRECTED_QUESTION_NATIVE_EXTRACTION_MISSING")
    candidates = [
        Path("artifacts/h2b-verification") / extraction.id / "native/pages/page-0001.json",
        Path("artifacts/question-imports") / extraction.id / "native/pages/page-0001.json",
    ]
    native_path = next((path for path in candidates if path.is_file()), None)
    if native_path is None:
        raise RuntimeError("CORRECTED_QUESTION_NATIVE_PAGE_MISSING")
    native = json.loads(native_path.read_text(encoding="utf-8"))
    width, height = float(native["width"]), float(native["height"])
    elements = [e for e in native.get("elements", []) if e.get("bbox") and str(e.get("native_text") or "").strip()]
    questions = list(session.scalars(select(m.TestQuestion).where(
        m.TestQuestion.test_id == test_id, m.TestQuestion.is_gradable.is_(True))))
    anchors = []
    for question in sorted(questions, key=lambda item: item.sort_order):
        text = question.question_text or ""
        needle = _compact(text)
        candidates_for_question = []
        for element in elements:
            candidate = _compact(element.get("native_text", ""))
            if not candidate:
                continue
            # Native line wrapping is common, so accept either side when the
            # shared text is substantial. Never use the Ricoh page result.
            # Keep only native spans that are actually part of this
            # authoritative Question text. A short shared prefix is not
            # sufficient: Japanese prompts share many characters.
            if needle and (needle in candidate or (candidate in needle and len(candidate) >= 4)):
                candidates_for_question.append(element)
        if not candidates_for_question:
            raise RuntimeError(f"QUESTION_NATIVE_ANCHOR_NOT_FOUND:{question.id}")
        # Pick the longest contiguous native span as the anchor's primary
        # line. Include wrapped continuation lines and same-baseline labels,
        # but exclude unrelated header text that merely shares a phrase.
        longest = max(candidates_for_question,
                      key=lambda element: len(_compact(element.get("native_text", ""))))
        core = longest["bbox"]
        matches = []
        for element in elements:
            eb = element["bbox"]
            vertical_gap = max(0.0, eb[1] - core[3], core[1] - eb[3])
            same_line = vertical_gap <= 3.0
            candidate = _compact(element.get("native_text", ""))
            in_question = element in candidates_for_question
            wrapped = in_question and vertical_gap <= 28.0
            if same_line or wrapped:
                matches.append(element)
        if not matches:
            raise RuntimeError(f"QUESTION_NATIVE_ANCHOR_NOT_FOUND:{question.id}")
        box = [min(float(e["bbox"][0]) for e in matches) / width,
               min(float(e["bbox"][1]) for e in matches) / height,
               max(float(e["bbox"][2]) for e in matches) / width,
               max(float(e["bbox"][3]) for e in matches) / height]
        anchors.append({"question_ref": _question_ref(question.question_number),
                        "question_id": question.id, "printed_text": text,
                        "bbox": box})
    anchors.sort(key=lambda item: item["bbox"][1])
    for index, anchor in enumerate(anchors):
        next_top = anchors[index + 1]["bbox"][1] if index + 1 < len(anchors) else 0.99
        anchor["search_bbox"] = [0.0, min(1.0, anchor["bbox"][3] + 0.003),
                                  1.0, max(0.0, next_top - 0.003)]
    return anchors, str(native_path)


def main():
    _, factory = create_session_factory("postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader")
    row = next(x for x in MANIFEST if x["sample_identity"] == "s1" and x["test_id"] == "70a63c23-f1b1-46b7-852c-046148b6f451")
    with factory() as session:
        submission = session.get(m.StudentSubmission, row["submission_id"])
        source = Path(session.get(m.TestMaterial, submission.material_id).storage_ref)
        qs = list(session.scalars(select(m.TestQuestion).where(
            m.TestQuestion.test_id == row["test_id"], m.TestQuestion.is_gradable.is_(True))))
        anchors, native_path = _native_question_anchors(session, row["test_id"])
    manager, config = manager_setup()
    stages = RuntimeStudentAnswerStages(manager, config, runtime_ids={"ricoh": "ocr"})
    started = time.monotonic()
    _, detected = stages.ricoh_page_answers(source, anchors)
    elapsed = time.monotonic() - started
    question_texts = {_question_ref(q.question_number): q.question_text or "" for q in qs}
    rows = []
    native_regions = {a["question_ref"]: a["bbox"] for a in anchors}
    answer_search_regions = {a["question_ref"]: a["search_bbox"] for a in anchors}
    for item in detected["questions"]:
        answer_regions = [dict(region, question_ref=item["question_ref"])
                          for region in item["answer_regions"]]
        regions = classify_regions(
            answer_regions,
            {item["question_ref"]: question_texts.get(item["question_ref"], "")},
            native_regions=native_regions,
            answer_search_regions=answer_search_regions,
        )
        rows.append({"question_ref": item["question_ref"], "anchor_bbox": next(a["bbox"] for a in anchors if a["question_ref"] == item["question_ref"]),
                     "answer_regions": regions, "no_answer_detected": item["no_answer_detected"]})
    manager.stop("ocr")
    out = Path("artifacts/h3g0e")
    out.mkdir(parents=True, exist_ok=True)
    result = {"submission_id": row["submission_id"], "source_sha256": row["source"]["sha256"],
              "native_anchor_path": native_path, "anchors": anchors,
              "elapsed_seconds": elapsed, "questions": rows, "ricoh_calls": 1,
              "unimumer_calls": 0, "reconstruction_created": 0, "grading_jobs": 0,
              "ornith_grading": 0}
    (out / "smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
