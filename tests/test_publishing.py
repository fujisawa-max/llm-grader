import json
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scoring.db.database import Base
from scoring.db.models import (
    DomainEvent,
    GradingJob,
    GradingJobItem,
    ModelAnswer,
    Student,
    StudentAnswerExtractionResult,
    StudentAnswerExtractionRun,
    StudentAnswerReconstruction,
    StudentSubmission,
    Test,
    TestQuestion,
    TestMaterial,
    RubricVersion,
)
from scoring.publishing import PublicationError, ResultPublicationService
from scoring.pdf_native import canonical_hash
from scoring.student_visual import StudentVisualAssetService


def fixture(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    offering = str(uuid4())
    test = Test(id=str(uuid4()), course_offering_id=offering, name="Published test", total_points=10)
    question = TestQuestion(id=str(uuid4()), test_id=test.id, question_number="1",
                            display_label="問題1", question_text="説明", max_points=10)
    student = Student(id=str(uuid4()), course_offering_id=offering, student_identifier="s1",
                      display_name="Private Name")
    import pymupdf
    source = tmp_path / "source.png"
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 10, 10), False)
    pixmap.save(str(source))
    pixmap = None
    source_bytes = source.read_bytes()
    material = TestMaterial(id=str(uuid4()), test_id=test.id, material_type="image",
                            storage_ref=str(source), sha256=__import__("hashlib").sha256(source_bytes).hexdigest())
    submission = StudentSubmission(id=str(uuid4()), test_id=test.id, student_id=student.id,
                                   submission_key="s1", material_id=material.id)
    model_answer = ModelAnswer(id=str(uuid4()), test_id=test.id, question_id=question.id,
                               answer_text="reference", version=1, is_current=True)
    entry = {"question_id": question.id, "max_points": 10, "criteria": [
        {"id": "criterion_1", "description": "quality", "points": 10,
         "levels": [{"score": 10, "description": "full"}, {"score": 0, "description": "none"}]},
    ]}
    rubric = RubricVersion(id=str(uuid4()), test_id=test.id, version=1, status="approved",
                           rubric_json={"questions": [entry]})
    run = StudentAnswerExtractionRun(id=str(uuid4()), submission_id=submission.id, test_id=test.id,
                                     source_sha256=material.sha256, pipeline_version="test",
                                     config_sha256="c" * 64, status="completed", artifact_ref="run.json", selected=True)
    result = StudentAnswerExtractionResult(id=str(uuid4()), run_id=run.id, submission_id=submission.id,
                                           question_id=question.id, source_sha256=material.sha256,
                                           status="completed", artifact_ref="result.json")
    reconstruction = StudentAnswerReconstruction(
        id=str(uuid4()), extraction_result_id=result.id, submission_id=submission.id,
        question_id=question.id, version=1, source_sha256=material.sha256,
        context_sha256="d" * 64, status="COMPLETE", answer_text="student answer",
        output_sha256="e" * 64, artifact_ref="reconstruction.json", model_identity={"origin": "TEACHER_TRANSCRIPTION"})
    bundle = {
        "identity": {"test_id": test.id, "question_id": question.id},
        "question": {"max_points": 10, "context": {"test_id": test.id, "question_id": question.id,
                                                       "is_gradable": True, "max_points": 10,
                                                       "context_sha256": "f" * 64}},
        "student_answer": {"submission_id": submission.id, "student_id": student.id,
                            "answer_text": "student answer", "source": "RECONSTRUCTED_FROM_DOCUMENT",
                            "reconstruction_status": "COMPLETE", "reconstruction": {"answer_text": "student answer"}},
        "model_answer": {"question_id": question.id, "content": "reference", "sha256": canonical_hash("reference")},
        "rubric": {"id": rubric.id, "question_id": question.id, "entry": entry,
                    "entry_sha256": canonical_hash(entry)},
    }
    bundle["bundle_sha256"] = canonical_hash({**bundle})
    snapshot = {"bundle": bundle, "snapshot_sha256": "snapshot", "model_settings": {"model_id": "grader"}}
    job = GradingJob(id=str(uuid4()), external_id=str(uuid4()), execution_mode="test", state="completed",
                     assignment_path="a", run_path="r", config_path="c", test_id=test.id,
                     rubric_version_id=rubric.id, metadata_json={"grading_execution": snapshot})
    item = GradingJobItem(id=str(uuid4()), job_id=job.id, item_key="s1", state="completed",
                          score=8, max_score=10, metadata_json={"submission_id": submission.id,
                          "question_id": question.id, "result": {"criteria": [{"criterion_id": "criterion_1", "score": 8, "max_score": 10, "reason": "Good work."}], "feedback": "Good work."}})
    session.add_all([test, question, student, material, submission, model_answer, rubric, run,
                     result, reconstruction, job, item])
    session.flush()
    session.add(DomainEvent(entity_type="grading_finalization", entity_id=str(uuid4()),
                            event_type="grading_finalized", payload={"test_id": test.id, "submission_id": submission.id,
                                                                      "status": "FINALIZED"}))
    session.commit()
    return session, test, question, student, submission


def test_publish_requires_finalized_and_student_dto_isolated(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    payload, created = service.publish_submission(test.id, submission.id)
    assert created and payload["status"] == "PUBLISHED"
    result = service.student_result(submission.id, requester_student_id=student.student_identifier)
    assert result["score"] == 8 and result["max_score"] == 10
    encoded = json.dumps(result, ensure_ascii=False)
    assert "ModelAnswer" not in encoded and "Rubric" not in encoded
    assert question.id not in encoded and student.id not in encoded
    assert "criterion_1" not in encoded and "artifact" not in encoded
    with __import__("pytest").raises(PublicationError, match="STUDENT_ACCESS_DENIED"):
        service.student_result(submission.id, requester_student_id="other")


def test_unfinalized_submission_cannot_publish(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    session.query(DomainEvent).filter(DomainEvent.event_type == "grading_finalized").delete()
    session.commit()
    with __import__("pytest").raises(PublicationError, match="PUBLISH_REQUIRES_FINALIZED"):
        ResultPublicationService(session, root=tmp_path).publish_submission(test.id, submission.id)


def test_feedback_override_and_changed_publication_state(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    service.publish_submission(test.id, submission.id)
    original = service.student_result(submission.id, requester_student_id=student.id)
    override = service.feedback_override(test.id, submission.id, question.id,
                                         "Revise the final step.", teacher_note="internal note")
    assert override["status"] == "COMPLETE"
    changed = service.student_result(submission.id, requester_student_id=student.id)
    assert changed["status"] == "RESULT_CHANGED_AFTER_PUBLICATION"
    assert changed["republish_required"] is True
    assert changed["questions"][0]["feedback"] == original["questions"][0]["feedback"]


def test_republish_appends_new_snapshot_after_feedback_change(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    first, _ = service.publish_submission(test.id, submission.id)
    service.feedback_override(test.id, submission.id, question.id, "Teacher feedback")
    current = service.student_result(submission.id, requester_student_id=student.id)
    assert current["status"] == "RESULT_CHANGED_AFTER_PUBLICATION"
    second, created = service.publish_submission(test.id, submission.id)
    assert created and second["snapshot_sha256"] != first["snapshot_sha256"]
    republished = service.student_result(submission.id, requester_student_id=student.id)
    assert republished["status"] == "PUBLISHED"
    assert republished["questions"][0]["feedback"] == "Teacher feedback"


def test_unpublish_hides_result_and_pdf_contains_no_internal_fields(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    service.publish_submission(test.id, submission.id)
    pdf = service.result_pdf_bytes("", submission.id, requester_student_id=student.id, student=True)
    assert pdf.startswith(b"%PDF")
    assert question.id.encode() not in pdf and b"criterion_1" not in pdf
    service.unpublish_submission(test.id, submission.id)
    with __import__("pytest").raises(PublicationError, match="RESULT_NOT_PUBLISHED"):
        service.student_result(submission.id, requester_student_id=student.id)


def test_published_visual_result_exposes_student_asset_only(tmp_path):
    session, test, question, student, submission = fixture(tmp_path)
    source = session.get(TestMaterial, submission.material_id)
    asset = StudentVisualAssetService(session, tmp_path).register(
        submission.id, question.id, [0, 0, 1, 1], source_sha=source.sha256,
        provenance={"source": "test"}, verified=True)
    job = session.query(GradingJob).first()
    snapshot = job.metadata_json["grading_execution"]
    bundle = {**snapshot["bundle"], "visual_assets": [asset]}
    job.metadata_json = {"grading_execution": {**snapshot, "bundle": bundle}}
    session.commit()
    service = ResultPublicationService(session, root=tmp_path, answer_root=tmp_path)
    service.publish_submission(test.id, submission.id)
    result = service.student_result(submission.id, requester_student_id=student.id)
    visual = result["questions"][0]["student_answer"]["visual_assets"]
    assert len(visual) == 1 and "asset_id" not in visual[0] and "sha256" not in visual[0]
    assert submission.id not in visual[0]["url"] and question.id not in visual[0]["url"]
    assert visual[0]["url"].split("/")[-1] != asset["asset_id"]
    path, mime = service.visual_path_by_token(
        submission.id, question.id, visual[0]["url"].rsplit("/", 1)[-1], requester_student_id=student.id)
    assert path.is_file() and mime == "image/png"
