"""Explicitly synthetic, shuffled H.2-G data; never adds data to sample tests."""

import json
from pathlib import Path

import pymupdf

from scoring.domain import DomainService
from scoring.pdf_native import sha256_file


def create_mapping_fixture(session, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    d = DomainService(session)
    user = d.user(display_name="H.2-G validation")
    course = d.course(user.id, name="H.2-G mapping validation")
    offering = d.offering(course.id, academic_year=2026, term="fall")
    test = d.test(offering.id, name="H.2-G mapping validation", total_points=30)
    parents = {
        key: d.question(
            test.id,
            question_number=key,
            stable_question_key=key,
            display_label=f"Parent {key}",
            question_text=f"PARENT_TOKEN_{key}",
            is_gradable=False,
            node_type="structural",
            max_points=None,
            sort_order=index * 3,
        )
        for index, key in enumerate(("A", "B"))
    }
    qs = {
        key: d.question(
            test.id,
            question_number=key,
            stable_question_key=f"stable-{key}",
            display_label="(2)" if key == "A2" else "(1)",
            title=f"QUESTION_TOKEN_{key}",
            question_text=f"QUESTION_TOKEN_{key}",
            max_points=10,
            parent_id=parents[key[0]].id,
            sort_order=index + 1,
        )
        for index, key in enumerate(("A1", "A2", "B1"))
    }
    models = {
        key: d.model_answer(test.id, question_id=qs[key].id, answer_text=f"MODEL_TOKEN_{key}")
        for key in ("A1", "B1", "A2")
    }
    rubric = d.rubric(
        test.id,
        {
            "questions": [
                {
                    "question_id": qs[key].id,
                    "max_points": 10,
                    "criteria": [
                        {
                            "id": f"criterion-{key}",
                            "points": 10,
                            "description": f"RUBRIC_TOKEN_{key}",
                        }
                    ],
                }
                for key in ("A2", "B1", "A1")
            ]
        },
    )
    d.approve_rubric(rubric.id, user.id)
    student = d.student(offering.id, student_identifier="H2G-SYNTHETIC")
    document = {
        "submission_id": "h2g-submission",
        "test_id": test.id,
        "student_id": student.id,
        "pages": [],
        "answers": [],
    }
    for key in ("B1", "A2", "A1"):
        with pymupdf.open() as image:
            page = image.new_page(width=500, height=80)
            page.insert_text((10, 30), f"STUDENT_TOKEN_{key}")
            page.get_pixmap().save(root / f"{key}.png")
        document["pages"].append({"page_id": f"STUDENT_TOKEN_{key}", "image": f"{key}.png"})
        document["answers"].append(
            {"question_id": qs[key].id, "page_ids": [f"STUDENT_TOKEN_{key}"]}
        )
    path = root / "submission.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    material = d.material(
        test.id,
        material_type="student_submission_source",
        storage_ref=str(path),
        mime_type="application/json",
        sha256=sha256_file(path),
    )
    sub = d.submission(
        test.id, student.id, submission_key=document["submission_id"], material_id=material.id
    )
    assignment = {
        "assignment_id": "h2g-validation",
        "questions": [],
        "submissions": ["submission.json"],
    }
    for key, q in qs.items():
        (root / f"{key}.txt").write_text(q.question_text)
        (root / f"{key}.rubric.json").write_text(
            json.dumps(
                {
                    "question_id": q.id,
                    "max_score": 10,
                    "criteria": [
                        {
                            "criterion_id": f"criterion-{key}",
                            "max_score": 10,
                            "description": f"RUBRIC_TOKEN_{key}",
                            "levels": [
                                {"score": 0, "condition": "SYNTHETIC_ZERO"},
                                {"score": 10, "condition": "SYNTHETIC_FULL"},
                            ],
                        }
                    ],
                }
            )
        )
        assignment["questions"].append(
            {"question_id": q.id, "question": f"{key}.txt", "rubric": f"{key}.rubric.json"}
        )
    (root / "assignment.json").write_text(json.dumps(assignment))
    session.flush()
    return dict(
        user=user,
        test=test,
        questions=qs,
        parents=parents,
        models=models,
        rubric=rubric,
        student=student,
        submission=sub,
        material=material,
        document=document,
        root=root,
    )


def create_missing_attempt(session, original, root):
    """A separate synthetic attempt; does not edit the complete attempt."""
    from scoring.db.models import Test
    assert session.get(Test, original.test_id).name == "H.2-G mapping validation"
    root = Path(root)
    document = json.loads((root / "submission.json").read_text())
    document["submission_id"] = "h2g-missing-answer"
    document["answers"].pop()
    path = root / "missing-submission.json"
    path.write_text(json.dumps(document))
    d = DomainService(session)
    mat = d.material(original.test_id, material_type="student_submission_source", storage_ref=str(path.resolve()),
                     mime_type="application/json", sha256=sha256_file(path))
    return d.submission(original.test_id, original.student_id, submission_key=document["submission_id"],
                        material_id=mat.id, attempt_number=2)
