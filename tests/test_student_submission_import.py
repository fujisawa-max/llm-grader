import base64
from pathlib import Path

from scoring.db.database import create_session_factory, init_database
from scoring.domain import DomainService
from scoring.student_submission_import import AnswerSheetSpec, StudentSubmissionImportService


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _setup(tmp_path):
    engine, factory = create_session_factory(f"sqlite:///{tmp_path / 'db.sqlite'}")
    init_database(engine)
    session = factory()
    domain = DomainService(session)
    teacher = domain.user(display_name="Teacher")
    course = domain.course(teacher.id, name="Sample")
    offering = domain.offering(course.id, academic_year=2026, term="fall")
    return session, domain, offering


def test_source_registration_is_idempotent_and_preserves_bytes(tmp_path):
    session, domain, offering = _setup(tmp_path)
    test = domain.test(offering.id, name="sampleQ1", total_points=10)
    source = tmp_path / "sampleQ1_answerSheet_s1.png"
    source.write_bytes(PNG_1X1)
    service = StudentSubmissionImportService(session, artifact_root=tmp_path / "artifacts")
    spec = AnswerSheetSpec("s1", test.id, source)

    first = service.import_one(spec)
    session.commit()
    second = service.import_one(spec)
    session.commit()

    assert first.student_created and first.material_created and first.submission_created
    assert not second.student_created and not second.material_created and not second.submission_created
    assert first.student_id == second.student_id
    assert first.material_id == second.material_id
    assert first.submission_id == second.submission_id
    assert first.source.sha256 == second.source.sha256
    stored = Path(first.storage_ref)
    if not stored.is_absolute():
        stored = Path.cwd() / stored
    assert stored.read_bytes() == PNG_1X1


def test_same_sample_identity_reused_across_tests(tmp_path):
    session, domain, offering = _setup(tmp_path)
    test1 = domain.test(offering.id, name="sampleQ1", total_points=10)
    test2 = domain.test(offering.id, name="sampleQ2", total_points=10)
    source1 = tmp_path / "q1.png"
    source2 = tmp_path / "q2.png"
    source1.write_bytes(PNG_1X1)
    source2.write_bytes(PNG_1X1)
    service = StudentSubmissionImportService(session, artifact_root=tmp_path / "artifacts")

    first = service.import_one(AnswerSheetSpec("s1", test1.id, source1))
    second = service.import_one(AnswerSheetSpec("s1", test2.id, source2))
    session.commit()

    assert first.student_id == second.student_id
