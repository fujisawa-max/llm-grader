import base64

from scoring.db.database import create_session_factory, init_database
from scoring.domain import DomainService
from scoring.student_identity import StudentIdentityService, normalize_student_number
from scoring.student_submission_import import AnswerSheetSpec, StudentSubmissionImportService


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _submission(tmp_path):
    engine, factory = create_session_factory(f"sqlite:///{tmp_path / 'db.sqlite'}")
    init_database(engine)
    session = factory()
    domain = DomainService(session)
    teacher = domain.user(display_name="Teacher")
    course = domain.course(teacher.id, name="Sample")
    offering = domain.offering(course.id, academic_year=2026, term="fall")
    test = domain.test(offering.id, name="sampleQ5", total_points=100)
    source = tmp_path / "answer.png"
    source.write_bytes(PNG_1X1)
    imported = StudentSubmissionImportService(
        session, artifact_root=tmp_path / "artifacts"
    ).import_one(AnswerSheetSpec("fixture", test.id, source))
    session.commit()
    return session, imported.submission_id, tmp_path / "artifacts"


def test_identity_normalization_preserves_leading_zero_and_case():
    assert normalize_student_number(" M0A 0012　") == "M0A0012"


def test_identity_artifact_is_source_bound_and_idempotent(tmp_path):
    session, submission_id, root = _submission(tmp_path)
    service = StudentIdentityService(session, root=root)
    first = service.extract(
        submission_id,
        student_number="M0A0012",
        student_name="山田 太郎",
        confidence=0.95,
        raw_text="学籍番号 M0A0012 名前 山田 太郎 座席番号 4",
    )
    session.commit()
    second = service.extract(submission_id, student_number="different", student_name="別名")
    assert first["student_number"] == "M0A0012"
    assert first["student_name"] == "山田 太郎"
    assert first["seat_number"] is None
    assert first["source_bbox"]["header_bbox"]
    assert second["artifact_sha256"] == first["artifact_sha256"]
    assert service.load(submission_id)["student_number"] == "M0A0012"
    corrected = service.correct(
        submission_id, student_number="M0A0099", student_name="山田 次郎", reason="header verified"
    )
    session.commit()
    assert corrected["origin"] == "TEACHER_CORRECTION"
    assert corrected["revision"] == 2
    assert service.load(submission_id)["student_number"] == "M0A0099"
