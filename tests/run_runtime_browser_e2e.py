"""Run isolated production-frontend E2E through real API/Manager/managed stub.

Usage: python -m tests.run_runtime_browser_e2e
Requires npm dependencies and installed Playwright Chromium. No real model call.
"""

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import pymupdf
from sqlalchemy import func, select

from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import GradingJob, ModelAnswerImportDraft
from scoring.domain import DomainService
from tests.runtime_fixture import REPO, runtime_service, stop_process, unused_port, wait_http


def seed(root):
    db_url = f"sqlite:///{root / 'isolated.sqlite'}"
    engine, factory = create_session_factory(db_url)
    init_database(engine)
    password = secrets.token_urlsafe(24)
    email = "runtime-fixture@example.invalid"
    with factory() as session:
        domain = DomainService(session)
        admin = domain.user(display_name="Isolated runtime teacher", email=email, role="admin",
                            password_hash=hash_password(password), is_active=True)
        course = domain.course(admin.id, name="Isolated runtime course")
        offering = domain.offering(course.id, academic_year=2026, term="fall")
        test = domain.test(offering.id, name="Runtime classification fixture", total_points=10)
        domain.question(test.id, question_number="1", display_label="問題1", sort_order=1,
                        max_points=10, is_gradable=True, question_text="Describe the idea of overfitting.")
        pdf = pymupdf.open()
        page = pdf.new_page(width=600, height=800)
        text = ("Question 1\nExplain overfitting and state its effect.\n"
                "The model memorizes the training examples and generalizes poorly.\n"
                "5 points: identify overfitting.\nAlternative: describe high variance.")
        page.insert_textbox(pymupdf.Rect(30, 30, 570, 750), text, fontsize=12, lineheight=1.5)
        content = pdf.tobytes()
        pdf.close()
        digest = hashlib.sha256(content).hexdigest()
        source = root / "sources" / test.id / f"{digest}.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(content)
        material = domain.material(test.id, material_type="model_answer_source", storage_ref=str(source),
                                   original_filename="semantic-model-answer.pdf", mime_type="application/pdf",
                                   sha256=digest)
        geometry_test = domain.test(offering.id, name="Geometry Q1 Q2 Q3 fixture", total_points=30)
        question_ids = []
        for number in range(1, 4):
            q = domain.question(geometry_test.id, question_number=str(number), display_label=f"問題{number}",
                                sort_order=number, max_points=10, is_gradable=True,
                                question_text=f"Explain concept {number}.")
            question_ids.append(q.id)
        for kind in ("question_sheet", "model_answer_source"):
            pdf = pymupdf.open()
            page = pdf.new_page(width=600, height=800)
            for number, y in enumerate((100, 350, 600), 1):
                page.insert_text((30, y), f"Question {number}", fontsize=12)
                page.insert_text((30, y + 25), f"Explain concept {number}.", fontsize=12)
                if kind == "model_answer_source":
                    page.insert_text((30, y + 60), f"Source answer {number}.", fontsize=12)
            content = pdf.tobytes()
            pdf.close()
            digest = hashlib.sha256(content).hexdigest()
            source = root / "sources" / geometry_test.id / f"{digest}.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(content)
            geometric_material = domain.material(geometry_test.id, material_type=kind, storage_ref=str(source),
                                                original_filename=f"geometry-{kind}.pdf", mime_type="application/pdf",
                                                sha256=digest)
            if kind == "model_answer_source":
                geometry_material_id = geometric_material.id
        session.commit()
        geometry_env = {"GEOMETRY_TEST_ID": geometry_test.id, "GEOMETRY_MATERIAL_ID": geometry_material_id,
                        "GEOMETRY_QUESTION_IDS": json.dumps(question_ids)}
        review_ux_test = domain.test(offering.id, name="Review UX isolated fixture", total_points=30)
        review_ux_question_ids = []
        for number in range(1, 4):
            question = domain.question(review_ux_test.id, question_number=str(number),
                                       display_label=f"問題{number}", sort_order=number, max_points=10,
                                       is_gradable=True, question_text=f"Explain concept {number}.")
            review_ux_question_ids.append(question.id)
        domain.rubric(review_ux_test.id, {"questions": [
            {"question_id": question_id, "max_points": 10,
             "criteria": [{"id": f"existing-{index}", "description": "既存の採点基準", "points": 10}]}
            for index, question_id in enumerate(review_ux_question_ids, 1)
        ]}, source_type="manual")
        review_pdf = pymupdf.open(stream=source.read_bytes(), filetype="pdf")
        review_pdf.new_page(width=600, height=800)
        review_content = review_pdf.tobytes()
        review_pdf.close()
        review_digest = hashlib.sha256(review_content).hexdigest()
        review_source = root / "sources" / review_ux_test.id / f"{review_digest}.pdf"
        review_source.parent.mkdir(parents=True, exist_ok=True)
        review_source.write_bytes(review_content)
        review_ux_material = domain.material(
            review_ux_test.id, material_type="model_answer_source",
            storage_ref=str(review_source), original_filename="review-ux-model-answer.pdf",
            mime_type="application/pdf", sha256=review_digest)
        rubric_pdf = pymupdf.open()
        rubric_page = rubric_pdf.new_page(width=600, height=800)
        rubric_page.insert_textbox(
            pymupdf.Rect(30, 30, 570, 750),
            "Question 1\nExplain concept 1.\nA source answer.\n"
            "5 points: identify overfitting.\n2 points: cite evidence.\n3 points: mention generalization.",
            fontsize=12, lineheight=1.5,
        )
        rubric_content = rubric_pdf.tobytes()
        rubric_pdf.close()
        rubric_digest = hashlib.sha256(rubric_content).hexdigest()
        rubric_source = root / "sources" / review_ux_test.id / f"{rubric_digest}.pdf"
        rubric_source.write_bytes(rubric_content)
        rubric_material = domain.material(
            review_ux_test.id, material_type="model_answer_source",
            storage_ref=str(rubric_source), original_filename="unified-rubric-model-answer.pdf",
            mime_type="application/pdf", sha256=rubric_digest)
        geometry_env.update({"REVIEW_UX_TEST_ID": review_ux_test.id,
                             "REVIEW_UX_QUESTION_IDS": json.dumps(review_ux_question_ids),
                             "REVIEW_UX_MATERIAL_ID": review_ux_material.id,
                             "REVIEW_RUBRIC_MATERIAL_ID": rubric_material.id})
        split_test = domain.test(offering.id, name="Rubric split fixture", total_points=10)
        split_question = domain.question(split_test.id, question_number="1", display_label="問題1", sort_order=1,
                                          max_points=10, is_gradable=True, question_text="Explain overfitting.")
        split_pdf = pymupdf.open()
        split_page = split_pdf.new_page(width=600, height=800)
        split_page.insert_textbox(pymupdf.Rect(30, 30, 570, 750),
            "Question 1\nA source answer.\n5 points: explain overfitting. 5 points: cite evidence.", fontsize=10, lineheight=1.5)
        split_content = split_pdf.tobytes()
        split_pdf.close()
        split_digest = hashlib.sha256(split_content).hexdigest()
        split_source = root / "sources" / split_test.id / f"{split_digest}.pdf"
        split_source.parent.mkdir(parents=True, exist_ok=True)
        split_source.write_bytes(split_content)
        domain.material(split_test.id, material_type="model_answer_source", storage_ref=str(split_source),
                        original_filename="split-rubric-model-answer.pdf", mime_type="application/pdf", sha256=split_digest)
        geometry_env.update({"RUBRIC_SPLIT_TEST_ID": split_test.id, "RUBRIC_SPLIT_QUESTION_ID": split_question.id})
        teacher_email, student_email = "text-teacher@example.invalid", "text-student@example.invalid"
        teacher = domain.user(display_name="Text tool teacher", email=teacher_email, role="teacher",
                              password_hash=hash_password(password), is_active=True)
        domain.user(display_name="Text tool non-staff", email=student_email, role="student",
                    password_hash=hash_password(password), is_active=True)
        teacher_course = domain.course(teacher.id, name="Teacher-owned text tool fixture")
        teacher_offering = domain.offering(teacher_course.id, academic_year=2026, term="fall")
        geometry_env.update({"TEXT_TOOL_TEACHER_EMAIL": teacher_email, "TEXT_TOOL_STUDENT_EMAIL": student_email})
        state_test = domain.test(teacher_offering.id, name="LaTeX state semantics fixture", total_points=10)
        state_question = domain.question(state_test.id, question_number="1", display_label="問題1", sort_order=1,
                                         max_points=10, is_gradable=True, question_text="Explain precision.")
        state_material = domain.material(state_test.id, material_type="model_answer_source", storage_ref=str(split_source),
                                         original_filename="state-model-answer.pdf", mime_type="application/pdf", sha256=split_digest)
        domain.model_answer(state_test.id, question_id=state_question.id, answer_text="Formal answer A.")
        geometry_env.update({"LATEX_STATE_TEST_ID": state_test.id, "LATEX_STATE_QUESTION_ID": state_question.id,
                             "LATEX_STATE_MATERIAL_ID": state_material.id})
        from uuid import uuid4
        math_pdf = pymupdf.open()
        math_page = math_pdf.new_page()
        math_page.insert_text((30, 53), "Precision=")
        for x, numerator, denominator in [(114, "TP", "TP+FP"), (191, "24", "24+6"), (250, "24", "30")]:
            math_page.insert_text((x, 45), numerator)
            math_page.draw_line((x-2, 50), (x+35, 50))
            math_page.insert_text((x, 65), denominator)
        math_page.insert_text((165, 53), "=")
        math_page.insert_text((224, 53), "=")
        math_page.insert_text((294, 53), "=0.800")
        math_page.insert_text((50, 165), "Answer: 0.800 (80%)")
        math_source = root / "sources" / "math.pdf"
        math_source.write_bytes(math_pdf.tobytes())
        math_pdf.close()
        math_digest = hashlib.sha256(math_source.read_bytes()).hexdigest()
        math_test = domain.test(teacher_offering.id, name="Source math fixture", total_points=10)
        math_question = domain.question(math_test.id, question_number="1", display_label="問題1", sort_order=1,
                                        max_points=10, is_gradable=True, question_text="Explain precision.")
        domain.model_answer(math_test.id, question_id=math_question.id, answer_text="Formal answer A.")
        math_material = domain.material(math_test.id, material_type="model_answer_source", storage_ref=str(math_source),
                                       original_filename="fractions.pdf", mime_type="application/pdf", sha256=math_digest)
        source_lines = ["Precision=", "TP", "TP+FP=", "24", "24+6 =", "24", "30 = 0.800"]
        source_boxes = [[30,45,100,58], [114,37,135,49], [110,56,175,68], [191,37,205,49], [180,56,230,68], [250,37,264,49], [240,56,330,68]]
        math_text = "\n".join(source_lines) + "\nAnswer: 0.800 (80%)"
        math_segments = [{"id": f"math-{i}", "original_text": t, "text": t, "page_index": 0,
                          "bbox": source_boxes[i], "reading_order": i}
                         for i, t in enumerate(source_lines)]
        math_draft = ModelAnswerImportDraft(id=str(uuid4()), test_id=math_test.id, material_id=math_material.id,
            source_sha256=math_digest, artifact_ref="math-ir.json", state="editing", revision=1,
            snapshot={"schema": "model-answer-review.v1", "page_count": 1, "entries": [{"id": str(uuid4()),
                "question_id": math_question.id, "answer_text": math_text, "disposition": "include",
                "answer_kind": "primary", "classification_reviewed": True,
                "source": {"kind": "native_pdf", "material_id": math_material.id, "segments": math_segments}}]})
        session.add(math_draft)
        geometry_env["SOURCE_MATH_DRAFT_ID"] = math_draft.id
        question_math_test = domain.test(teacher_offering.id, name="Question source math fixture", total_points=10)
        question_split_math_test = domain.test(teacher_offering.id, name="Split Question source fixture", total_points=10)
        question_pdf = pymupdf.open()
        question_page = question_pdf.new_page()
        question_page.insert_text((30, 35), "問題1 (10点)", fontname="japan", fontsize=12)
        question_page.insert_text((30, 65), "次の式の意味を説明せよ。", fontname="japan", fontsize=10)
        question_page.insert_text((30, 95), "Precision=TP/(TP+FP)=24/(24+6)=24/30=0.800", fontsize=10)
        question_page.insert_text((30, 130), "途中の数値を変更しないこと。", fontname="japan", fontsize=10)
        question_page.insert_text((30, 220), "問題2 (0点)", fontname="japan", fontsize=12)
        question_page.insert_text((30, 250), "隣の設問の文章。", fontname="japan", fontsize=10)
        question_pdf_path = root / "sources" / "question-math.pdf"
        question_pdf_path.write_bytes(question_pdf.tobytes())
        question_pdf.close()
        geometry_env.update(QUESTION_MATH_TEST_ID=question_math_test.id, QUESTION_MATH_PDF_PATH=str(question_pdf_path), QUESTION_SPLIT_MATH_TEST_ID=question_split_math_test.id)
        from tests.test_diagram_review_api import diagram_pdf
        diagram_test = domain.test(teacher_offering.id, name="Diagram review fixture", total_points=20)
        diagram_split_test = domain.test(teacher_offering.id, name="Diagram split fixture", total_points=20)
        diagram_answer_test = domain.test(teacher_offering.id, name="Diagram answer fixture", total_points=20)
        for n in (3, 4):
            domain.question(diagram_answer_test.id, question_number=str(n), display_label=f"問題{n}",
                sort_order=n, max_points=10, is_gradable=True, question_text="図の範囲を確認してください。")
        diagram_path = root / "sources" / "diagram.pdf"
        diagram_path.write_bytes(diagram_pdf())
        diagram_answer_path = root / "sources" / "diagram-answer.pdf"
        diagram_answer_path.write_bytes(diagram_pdf(True))
        diagram_material = domain.material(diagram_answer_test.id, material_type="model_answer_source",
            storage_ref=str(diagram_answer_path), original_filename="diagram-answer.pdf", mime_type="application/pdf",
            sha256=hashlib.sha256(diagram_answer_path.read_bytes()).hexdigest())
        geometry_env.update(DIAGRAM_TEST_ID=diagram_test.id, DIAGRAM_SPLIT_TEST_ID=diagram_split_test.id, DIAGRAM_PDF_PATH=str(diagram_path),
            DIAGRAM_ANSWER_TEST_ID=diagram_answer_test.id, DIAGRAM_ANSWER_MATERIAL_ID=diagram_material.id)
        manual_diagram_test = domain.test(teacher_offering.id, name="Manual diagram-only answers", total_points=30)
        major = domain.question(manual_diagram_test.id, question_number="3", display_label="問題3",
            sort_order=3, max_points=None, is_gradable=False)
        for n in (1, 2, 3):
            domain.question(manual_diagram_test.id, question_number=f"3.{n}", display_label=f"({n})",
                sort_order=n, parent_id=major.id, max_points=10, is_gradable=True)
        with pymupdf.open() as manual_pdf:
            p = manual_pdf.new_page(width=400, height=800)
            p.insert_text((25, 30), "問題3", fontname="japan", fontsize=12)
            for n, y in ((1, 60), (2, 300), (3, 540)):
                p.insert_text((25, y), f"({n}) (10点)", fontname="japan", fontsize=12)
                p.draw_line((70, y+100), (230, y+100))
                p.draw_line((150, y+30), (150, y+170))
                p.draw_line((80, y+150), (215, y+45), color=(0, 0, 1))
                p.draw_rect((160, y+110, 205, y+150), fill=(.6, .8, 1))
                p.insert_text((153, y+97), "O", fontsize=8)
            manual_source = root / "sources" / "manual-diagram-answer.pdf"
            manual_source.write_bytes(manual_pdf.tobytes())
        manual_material = domain.material(manual_diagram_test.id, material_type="model_answer_source",
            storage_ref=str(manual_source), original_filename="manual-diagram-answer.pdf", mime_type="application/pdf",
            sha256=hashlib.sha256(manual_source.read_bytes()).hexdigest())
        geometry_env.update(MANUAL_DIAGRAM_TEST_ID=manual_diagram_test.id, MANUAL_DIAGRAM_MATERIAL_ID=manual_material.id)
        # Review state after splitting an originally parent-owned diagram.
        # There is ONE completed diagram, not one fabricated per child.
        from scoring.pdf_native import PyMuPdfNativeExtractor
        for scope_name in ("parent", "pdf"):
            scope_test = domain.test(teacher_offering.id, name=f"Diagram {scope_name} fallback", total_points=30)
            owner = domain.question(scope_test.id, question_number="3", display_label="問題3",
                sort_order=3, max_points=None, is_gradable=False)
            children = [domain.question(scope_test.id, question_number=f"3.{n}", display_label=f"({n})",
                sort_order=n, parent_id=owner.id, max_points=10, is_gradable=True) for n in (1, 2, 3)]
            with pymupdf.open() as shared_pdf:
                p = shared_pdf.new_page(width=400, height=500)
                p.insert_text((25, 30), "問題3 決定境界", fontname="japan", fontsize=12)
                p.insert_text((25, 55), "(1) 境界 (2) 領域 (3) 点", fontname="japan", fontsize=10)
                p.draw_line((70, 220), (230, 220))
                p.draw_line((150, 140), (150, 300))
                p.draw_line((80, 285), (215, 150), color=(0, 0, 1))
                p.draw_rect((160, 230, 205, 280), fill=(.6, .8, 1))
                p.insert_text((153, 217), "O", fontsize=8)
                scope_source = root / "sources" / f"shared-{scope_name}.pdf"
                scope_source.write_bytes(shared_pdf.tobytes())
            digest = hashlib.sha256(scope_source.read_bytes()).hexdigest()
            scope_material = domain.material(scope_test.id, material_type="model_answer_source",
                storage_ref=str(scope_source), original_filename=f"shared-{scope_name}.pdf", mime_type="application/pdf", sha256=digest)
            native_dir = root / f"diagram-{scope_name}-native"
            PyMuPdfNativeExtractor().extract(scope_source, source_sha256=digest,
                material_id=scope_material.id, output_dir=native_dir)
            scope_draft = ModelAnswerImportDraft(id=str(uuid4()), test_id=scope_test.id, material_id=scope_material.id,
                source_sha256=digest, artifact_ref=f"diagram-{scope_name}-native/document-ir.json", state="editing", revision=1,
                snapshot={"schema": "model-answer-review.v1", "page_count": 1, "entries": [],
                    "question_regions": [{"question_id": owner.id, "page_index": 0, "left": 20,
                        "top": 80, "right": 250, "bottom": 330, "depth": 1}] if scope_name == "parent" else []})
            session.add(scope_draft)
            geometry_env.update({f"DIAGRAM_{scope_name.upper()}_DRAFT_ID": scope_draft.id,
                                 f"DIAGRAM_{scope_name.upper()}_CHILD_IDS": json.dumps([q.id for q in children]),
                                 f"DIAGRAM_{scope_name.upper()}_OWNER_ID": owner.id})
        caret_test = domain.test(teacher_offering.id, name="Question caret fixture", total_points=10)
        caret_pdf = pymupdf.open()
        caret_page = caret_pdf.new_page()
        for y, text in [(35, "問題1 (10点)"), (65, "2変数 x1, x2 に対して、"),
                        (95, "x1 + x2 - 3 の値が"), (125, "0以上ならクラス1"),
                        (220, "問題2 (0点)"), (250, "隣の設問の文章。")]:
            caret_page.insert_text((30, y), text, fontname="japan", fontsize=10)
        caret_path = root / "sources" / "question-caret.pdf"
        caret_path.write_bytes(caret_pdf.tobytes())
        caret_pdf.close()
        geometry_env.update(QUESTION_CARET_TEST_ID=caret_test.id, QUESTION_CARET_PDF_PATH=str(caret_path))
        continuation_test = domain.test(teacher_offering.id, name="Question continuation fixture", total_points=20)
        continuation_pdf = pymupdf.open()
        continuation_page = continuation_pdf.new_page()
        for y, text, japanese in [(35, "問題1 (10点)", True), (65, "式を確認してください。", True),
                                  (95, "Precision=TP/(TP+FP)=24/(24+6)=24/30=0.800", False), (125, "説明文を残してください。", True),
                                  (220, "問題2 (10点)", True), (250, "Recall=TP/(TP+FN)=24/(24+6)=24/30=0.800", False)]:
            continuation_page.insert_text((30, y), text, fontname="japan" if japanese else "helv", fontsize=10)
        continuation_path = root / "sources" / "question-continuation.pdf"
        continuation_path.write_bytes(continuation_pdf.tobytes())
        continuation_pdf.close()
        geometry_env.update(QUESTION_CONTINUATION_TEST_ID=continuation_test.id,
                            QUESTION_CONTINUATION_PDF_PATH=str(continuation_path))
        from scoring.model_answer_classification import fallback_classification, apply_teacher_segment_edits
        issue_test = domain.test(teacher_offering.id, name="Answer issue continuation fixture", total_points=20)
        issue_major = domain.question(issue_test.id, question_number="2", display_label="問題2", sort_order=1,
                                      max_points=None, is_gradable=False)
        issue_sub = domain.question(issue_test.id, question_number="2.2", display_label="(2)", sort_order=1,
                                    parent_id=issue_major.id, max_points=None, is_gradable=False)
        issue_questions = [domain.question(issue_test.id, question_number=f"2.2.{n}", display_label=f"{n}.",
                           sort_order=n, parent_id=issue_sub.id, max_points=10, is_gradable=True) for n in (1, 2)]
        issue_material = domain.material(issue_test.id, material_type="model_answer_source", storage_ref=str(split_source),
            original_filename="answer-continuation.pdf", mime_type="application/pdf", sha256=split_digest)
        candidate = "Saved answer.\n5 points: explain the source."
        classification = fallback_classification(candidate)
        classification = apply_teacher_segment_edits(classification, [
            {**segment, "category": "rubric" if "5 points" in segment["text"] else "model_answer"}
            for segment in classification["segments"]])
        classification["status"] = "needs_teacher_review"
        rubric_segment = next(segment for segment in classification["segments"] if segment["category"] == "rubric")
        issue_entries = [{"id": str(uuid4()), "question_id": issue_questions[0].id,
            "answer_text": "Saved alternative.", "answer_kind": "alternative", "disposition": "include",
            "source": {"kind": "teacher_manual", "material_id": issue_material.id, "segments": []}},
            {"id": str(uuid4()), "question_id": issue_questions[1].id, "answer_text": "Saved answer.",
             "candidate_text": candidate, "answer_kind": "primary", "disposition": "include",
             "semantic_classification": classification,
             "rubric_edits": [{"id": "issue-criterion", "description": rubric_segment["text"], "points": 5,
                 "segment_ids": [rubric_segment["id"]], "source_text": rubric_segment["source_text"],
                 "points_conflict": True, "points_confirmed": False, "grouping_confirmed": True}],
             "source": {"kind": "native_pdf", "material_id": issue_material.id, "source_sha256": split_digest,
                        "segments": []}},
            {"id": str(uuid4()), "question_id": None, "answer_text": "Unassigned candidate.",
             "answer_kind": "primary", "disposition": "unassigned",
             "source": {"kind": "teacher_manual", "material_id": issue_material.id, "segments": []}}]
        issue_draft = ModelAnswerImportDraft(id=str(uuid4()), test_id=issue_test.id, material_id=issue_material.id,
            source_sha256=split_digest, artifact_ref="issue-fixture.json", state="editing", revision=1,
            snapshot={"schema": "model-answer-review.v1", "page_count": 1, "entries": issue_entries})
        session.add(issue_draft)
        geometry_env.update(ANSWER_CONTINUATION_TEST_ID=issue_test.id, ANSWER_CONTINUATION_DRAFT_ID=issue_draft.id,
                            ANSWER_CONTINUATION_QUESTION_IDS=json.dumps([q.id for q in issue_questions]))
        completion_tests = [domain.test(teacher_offering.id, name=f"Question completion fixture {n}",
                                        total_points=20) for n in range(2)]
        completion_material = domain.material(completion_tests[1].id, material_type="model_answer_source",
            storage_ref=str(split_source), original_filename="saved-completion-answer.pdf",
            mime_type="application/pdf", sha256=split_digest)
        completion_draft = ModelAnswerImportDraft(id=str(uuid4()), test_id=completion_tests[1].id,
            material_id=completion_material.id, source_sha256=split_digest, artifact_ref="completion-fixture.json",
            state="editing", revision=1, snapshot={"schema": "model-answer-review.v1", "page_count": 1,
                "entries": [{"id": str(uuid4()), "question_id": None, "answer_text": "Saved teacher answer.",
                    "answer_kind": "primary", "disposition": "unassigned",
                    "source": {"kind": "teacher_manual", "material_id": completion_material.id, "segments": []}}]})
        session.add(completion_draft)
        geometry_env.update(QUESTION_COMPLETION_TEST_IDS=json.dumps([t.id for t in completion_tests]),
                            QUESTION_COMPLETION_DRAFT_ID=completion_draft.id)
        nested_test = domain.test(offering.id, name="Nested review navigation fixture", total_points=20)
        domain.question(nested_test.id, question_number="1", display_label="問題1", sort_order=1,
                        max_points=10, is_gradable=True)
        major = domain.question(nested_test.id, question_number="2", display_label="問題2", sort_order=2,
                                max_points=None, is_gradable=False)
        sub = domain.question(nested_test.id, question_number="2.2", display_label="(2)", sort_order=2,
                              parent_id=major.id, max_points=None, is_gradable=False)
        domain.question(nested_test.id, question_number="2.2.1", display_label="1.", sort_order=1,
                        parent_id=sub.id, max_points=0, is_gradable=True)
        nested = domain.question(nested_test.id, question_number="2.2.2", display_label="2.", sort_order=2,
                                 parent_id=sub.id, max_points=10, is_gradable=True,
                                 question_text="**Recall（再現率）**を $\\frac{TP}{TP+FN}$ で示しなさい。")
        domain.question(nested_test.id, question_number="2.2.3", display_label="3.", sort_order=3,
                        parent_id=sub.id, max_points=0, is_gradable=True)
        third = domain.question(nested_test.id, question_number="3", display_label="問題3", sort_order=3,
                                max_points=None, is_gradable=False)
        third_child = domain.question(nested_test.id, question_number="3.1", display_label="(1)", sort_order=1,
                                      parent_id=third.id, max_points=0, is_gradable=True)
        domain.material(nested_test.id, material_type="model_answer_source", storage_ref=str(review_source),
                        original_filename="review-ux-nested.pdf", mime_type="application/pdf",
                        sha256=review_digest)
        domain.model_answer(nested_test.id, question_id=third_child.id, answer_text="Second-page answer.",
                            provenance_json={"segments": [{"page_index": 1, "bbox": [20, 40, 120, 55]}]})
        geometry_env.update({"NESTED_REVIEW_TEST_ID": nested_test.id,
                             "NESTED_REVIEW_QUESTION_ID": nested.id,
                             "NESTED_REVIEW_PAGE_TWO_QUESTION_ID": third_child.id})
        session.commit()
        ids = test.id, material.id
    return engine, factory, db_url, email, password, ids, geometry_env


def json_request(opener, url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--insecure-origin", action="store_true", help="exercise non-loopback HTTP without secure-context Web Crypto")
    parser.add_argument("--spec", action="append", help="run selected browser specifications")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="llm-grader-runtime-e2e-") as temporary:
        root = Path(temporary)
        engine, factory, db_url, email, password, (test_id, material_id), geometry_env = seed(root)
        with runtime_service(root, hardware_backend="cuda") as (manager, manager_url, _):
            api_port, frontend_port = unused_port(), unused_port()
            api_url = f"http://127.0.0.1:{api_port}"
            frontend_host = socket.gethostbyname(socket.gethostname()) if args.insecure_origin else "127.0.0.1"
            env = {**os.environ, **geometry_env, "PYTHONPATH": str(REPO / "src"),
                   "LLM_GRADER_DATABASE_URL": db_url,
                   "LLM_GRADER_ARTIFACT_ROOT": str(root),
                   "LLM_GRADER_QUESTION_IMPORT_ROOT": str(root / "question-imports"),
                   "LLM_GRADER_ALLOWED_ROOTS": str(root),
                   "LLM_GRADER_ALLOW_HEADER_AUTH": "false", "LLM_GRADER_COOKIE_SECURE": "false",
                   "LLM_GRADER_RUNTIME_MANAGER_URL": manager_url,
                   "LLM_GRADER_MODEL_ANSWER_CLASSIFIER_PROFILE": "ornith_rubric_draft",
                   "LLM_GRADER_TRUSTED_RUNTIME_HOSTS": "127.0.0.2",
                   "API_PROXY_TARGET": api_url,
                   "E2E_FRONTEND_URL": f"http://{frontend_host}:{frontend_port}",
                   "RUBRIC_INSECURE_ORIGIN": "1" if args.insecure_origin else "0",
                   "MODEL_ANSWER_CLASSIFICATION_TEST_ID": test_id,
                   "MODEL_ANSWER_CLASSIFICATION_MATERIAL_ID": material_id,
                   "MODEL_ANSWER_CLASSIFICATION_EMAIL": email,
                   "MODEL_ANSWER_CLASSIFICATION_PASSWORD": password, "RUNTIME_MANAGER_E2E": "1"}
            api = frontend = None
            try:
                with (root / "api.log").open("w") as api_log, (root / "frontend.log").open("w") as frontend_log:
                    import sys
                    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "scoring.api.server:app",
                                            "--host", "127.0.0.1", "--port", str(api_port)],
                                           cwd=REPO, env=env, stdout=api_log, stderr=subprocess.STDOUT)
                    wait_http(api_url + "/api/v1/health", api)
                    # Persist a pre-9b draft whose edit omits newly introduced optional fields.
                    fixture_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                    json_request(fixture_opener, api_url + "/api/v1/auth/login", {"email": email, "password": password})
                    split_test_id = geometry_env["RUBRIC_SPLIT_TEST_ID"]
                    split_materials = json_request(fixture_opener, api_url + f"/api/v1/tests/{split_test_id}/materials")
                    legacy = json_request(fixture_opener, api_url + f"/api/v1/tests/{split_test_id}/model-answer-imports",
                                          {"material_id": split_materials[0]["id"]})
                    with factory() as session:
                        legacy_row = session.get(ModelAnswerImportDraft, legacy["id"])
                        legacy_entries = json.loads(json.dumps(legacy_row.snapshot["entries"]))
                        for entry in legacy_entries:
                            rubric_segments = [item for item in entry.get("semantic_classification", {}).get("segments", [])
                                               if item.get("category") == "rubric"]
                            if rubric_segments:
                                text = "".join(item.get("source_text", item["text"]) for item in rubric_segments)
                                entry["rubric_edits"] = [{"id": "legacy-rubric-item", "description": text, "points": 10,
                                    "segment_ids": [item["id"] for item in rubric_segments], "grouping_confirmed": True}]
                        legacy_row.snapshot = {**legacy_row.snapshot, "entries": legacy_entries}
                        session.commit()
                    env["RUBRIC_LEGACY_DRAFT_ID"] = legacy["id"]
                    if not args.skip_build:
                        subprocess.run(["npm", "run", "build"], cwd=REPO / "frontend", env=env, check=True)
                    frontend = subprocess.Popen(["npm", "run", "start", "--", "--hostname", frontend_host,
                                                 "--port", str(frontend_port)], cwd=REPO / "frontend",
                                                env=env, stdout=frontend_log, stderr=subprocess.STDOUT,
                                                start_new_session=True)
                    wait_http(env["E2E_FRONTEND_URL"] + "/login", frontend, timeout=60)
                    specs = args.spec or [
                        "e2e/runtime-classification-real-isolated.spec.ts",
                        "e2e/model-answer-classification-real-isolated.spec.ts",
                        "e2e/model-answer-geometry-real-isolated.spec.ts",
                        "e2e/model-answer-review-ux-real-isolated.spec.ts",
                        "e2e/unified-answer-rubric-review-real.spec.ts",
                        "e2e/rubric-split-real-isolated.spec.ts",
                        "e2e/rubric-edit-reliability-real.spec.ts",
                        "e2e/latex-normalization-real.spec.ts",
                        "e2e/latex-runtime-state-real.spec.ts",
                        "e2e/latex-error-mapping.spec.ts",
                        "e2e/source-math-ocr-real.spec.ts",
                        "e2e/question-math-ocr-real.spec.ts",
                        "e2e/question-editor-caret-real.spec.ts",
                        "e2e/review-continuation-real.spec.ts",
                        "e2e/question-completion-real.spec.ts",
                        "e2e/diagram-review-real.spec.ts",
                        "e2e/model-answer-nested-navigation-real-isolated.spec.ts",
                    ]
                    subprocess.run(["npm", "run", "e2e", "--", *specs, "--workers=1"],
                                   cwd=REPO / "frontend", env=env, check=True)
                    if any("diagram-review" not in spec for spec in specs):
                        assert any("POST /v1/chat/completions" in line
                                   for line in manager.logs("ornith_rubric_draft")["lines"])
                    assert manager.status("ornith_rubric_draft")["state"] in {"ready", "stopped"}
                    manager.stop("ornith_rubric_draft")
                    assert manager.status("ornith_rubric_draft")["pid"] is None
                    # Keep API/Frontend alive with no model, and check graceful fallback via real API.
                    (root / "synthetic.gguf").unlink()
                    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                    json_request(opener, api_url + "/api/v1/auth/login", {"email": email, "password": password})
                    if any("latex-" in spec and "error-mapping" not in spec for spec in specs):
                        api_log = (root / "api.log").read_text()
                        for stage in ("latex API request", "latex runtime ensure start", "latex runtime ready", "latex inference start", "latex inference success"):
                            assert stage in api_log, f"missing normalization stage log: {stage}"
                        assert "Formal answer A." not in api_log
                        assert "Draft answer B." not in api_log
                    statuses = json_request(opener, api_url + "/api/v1/system/runtimes")
                    assert all(row["availability"] == "model_missing" for row in statuses)
                    draft = json_request(opener, f"{api_url}/api/v1/tests/{test_id}/model-answer-imports", {"material_id": material_id})
                    classified = json_request(opener, f"{api_url}/api/v1/model-answer-import-drafts/{draft['id']}/classify",
                                              {"expected_revision": draft["revision"]})
                    assert classified["entries"][0]["answer_text"] == draft["entries"][0]["answer_text"]
                    assert classified["entries"][0]["semantic_classification"]["reason"] == "classification_failed"
                    json_request(opener, api_url + "/api/v1/health")
                    with factory() as session:
                        assert session.scalar(select(func.count()).select_from(GradingJob)) == 0
                    print("PASS: normal API bootstrap / real Manager / managed stub / browser / model-missing fallback; grading jobs 0")
            except Exception:
                for name in ["api.log", "frontend.log", "runtime-manager.log", "ornith_rubric_draft.log"]:
                    path = root / name
                    if path.exists():
                        print(f"{name}:\n{path.read_text()[-5000:]}")
                raise
            finally:
                if frontend:
                    # npm starts Next as a child: terminate only this isolated process group.
                    import signal
                    if frontend.poll() is None:
                        os.killpg(frontend.pid, signal.SIGTERM)
                    stop_process(frontend)
                if api:
                    stop_process(api)
                engine.dispose()


if __name__ == "__main__":
    main()
