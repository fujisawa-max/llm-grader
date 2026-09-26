"""Register original student answer-sheet images without extracting answers.

This module is deliberately limited to source registration.  It does not
create question-level answers, run OCR/reconstruction, or touch grading
inputs.  Source metadata that is not represented by ``TestMaterial`` is kept
in an append-only ``DomainEvent`` so the existing schema can be reused without
adding a migration.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from sqlalchemy import select

from .db.models import (
    DomainEvent,
    Student,
    StudentSubmission,
    Test,
    TestMaterial,
)
from .domain import DomainService


SOURCE_MATERIAL_TYPE = "student_answer_source_image"
SOURCE_STATUS = "REGISTERED_SOURCE"
SOURCE_CLASSIFICATION = "REAL"
SOURCE_SCHEMA_VERSION = "student-answer-source-registration.v1"


class StudentSubmissionImportError(ValueError):
    """A safe, actionable source-registration failure."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class AnswerSheetSpec:
    """One source image and its already-resolved authoritative Test."""

    sample_identity: str
    test_id: str
    source_path: Path


@dataclass(frozen=True)
class SourceMetadata:
    original_filename: str
    sha256: str
    mime_type: str
    width: int
    height: int
    file_size: int
    page_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "original_filename": self.original_filename,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
            "page_count": self.page_count,
        }


@dataclass(frozen=True)
class ImportResult:
    sample_identity: str
    test_id: str
    student_id: str
    material_id: str
    submission_id: str
    submission_key: str
    source: SourceMetadata
    student_created: bool
    material_created: bool
    submission_created: bool
    storage_ref: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_identity": self.sample_identity,
            "test_id": self.test_id,
            "student_id": self.student_id,
            "material_id": self.material_id,
            "submission_id": self.submission_id,
            "submission_key": self.submission_key,
            "source": self.source.as_dict(),
            "student_created": self.student_created,
            "material_created": self.material_created,
            "submission_created": self.submission_created,
            "storage_ref": self.storage_ref,
            "classification": SOURCE_CLASSIFICATION,
            "status": SOURCE_STATUS,
            "question_level_extraction": "NOT_STARTED",
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _png_metadata(path: Path) -> SourceMetadata:
    if not path.exists():
        raise StudentSubmissionImportError("SOURCE_FILE_NOT_FOUND")
    if not path.is_file():
        raise StudentSubmissionImportError("SOURCE_FILE_NOT_REGULAR")
    if path.suffix.lower() != ".png":
        raise StudentSubmissionImportError("SOURCE_NOT_PNG")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StudentSubmissionImportError("SOURCE_FILE_UNREADABLE") from exc
    if not raw or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise StudentSubmissionImportError("SOURCE_NOT_PNG")
    try:
        # PNG IHDR is the first chunk after the signature.  This validates the
        # dimensions without rewriting or resampling the original bytes.
        if raw[12:16] != b"IHDR" or len(raw) < 24:
            raise ValueError
        width = int.from_bytes(raw[16:20], "big")
        height = int.from_bytes(raw[20:24], "big")
        if width <= 0 or height <= 0:
            raise ValueError
        import pymupdf

        pixmap = pymupdf.Pixmap(str(path))
        if pixmap.width != width or pixmap.height != height:
            raise ValueError
    except Exception as exc:  # pragma: no cover - backend-specific decode errors
        raise StudentSubmissionImportError("SOURCE_IMAGE_DECODE_FAILED") from exc
    return SourceMetadata(
        original_filename=path.name,
        sha256=hashlib.sha256(raw).hexdigest(),
        mime_type="image/png",
        width=width,
        height=height,
        file_size=len(raw),
    )


class StudentSubmissionImportService:
    """Idempotently register immutable source images for an authoritative Test."""

    def __init__(self, session, *, artifact_root: str | Path = "artifacts"):
        self.session = session
        self.artifact_root = Path(artifact_root).resolve()
        self.domain = DomainService(session, artifact_root=self.artifact_root)

    def _student(self, test: Test, sample_identity: str) -> tuple[Student, bool]:
        values = list(
            self.session.scalars(
                select(Student).where(
                    Student.course_offering_id == test.course_offering_id,
                    Student.student_identifier == sample_identity,
                )
            )
        )
        if len(values) > 1:
            raise StudentSubmissionImportError("STUDENT_IDENTITY_CONFLICT")
        if values:
            return values[0], False
        return (
            self.domain.student(
                test.course_offering_id,
                student_identifier=sample_identity,
                display_name=None,
            ),
            True,
        )

    def _copy_source(self, test_id: str, source: Path, metadata: SourceMetadata) -> str:
        relative = Path("student-submissions") / test_id / f"{metadata.sha256}.png"
        destination = self.artifact_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if _sha256(destination) != metadata.sha256:
                raise StudentSubmissionImportError("SOURCE_ARTIFACT_HASH_MISMATCH")
        else:
            shutil.copyfile(source, destination)
            if _sha256(destination) != metadata.sha256:
                raise StudentSubmissionImportError("SOURCE_ARTIFACT_HASH_MISMATCH")
        # Material references are resolved from the repository root by the
        # existing answer/reconstruction readers.  Keep the API value relative
        # where possible, without exposing an absolute filesystem path.
        try:
            return str(destination.relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(destination)

    def _material(
        self, test: Test, source: Path, metadata: SourceMetadata, sample_identity: str
    ) -> tuple[TestMaterial, bool, str]:
        existing = list(
            self.session.scalars(
                select(TestMaterial).where(
                    TestMaterial.test_id == test.id,
                    TestMaterial.material_type == SOURCE_MATERIAL_TYPE,
                    TestMaterial.sha256 == metadata.sha256,
                )
            )
        )
        if len(existing) > 1:
            raise StudentSubmissionImportError("DUPLICATE_SOURCE_MATERIAL")
        storage_ref = self._copy_source(test.id, source, metadata)
        if existing:
            material = existing[0]
            if material.mime_type != metadata.mime_type:
                raise StudentSubmissionImportError("SOURCE_MATERIAL_METADATA_MISMATCH")
            if material.storage_ref != storage_ref:
                old_path = Path(material.storage_ref)
                old_candidates = [old_path]
                if not old_path.is_absolute():
                    old_candidates.extend((Path.cwd() / old_path, self.artifact_root / old_path))
                if not any(path.is_file() and _sha256(path) == metadata.sha256 for path in old_candidates):
                    raise StudentSubmissionImportError("SOURCE_MATERIAL_METADATA_MISMATCH")
                old_ref = material.storage_ref
                material.storage_ref = storage_ref
                self.session.add(
                    DomainEvent(
                        entity_type="student_answer_source",
                        entity_id=material.id,
                        event_type="source_reference_repaired",
                        payload={
                            "schema_version": SOURCE_SCHEMA_VERSION,
                            "material_id": material.id,
                            "old_storage_ref": old_ref,
                            "new_storage_ref": storage_ref,
                            "source_sha256": metadata.sha256,
                            "reason": "storage_reference_root_normalization",
                        },
                    )
                )
            return material, False, storage_ref
        material = self.domain.material(
            test.id,
            material_type=SOURCE_MATERIAL_TYPE,
            storage_ref=storage_ref,
            original_filename=metadata.original_filename,
            mime_type=metadata.mime_type,
            sha256=metadata.sha256,
        )
        self.session.add(
            DomainEvent(
                entity_type="student_answer_source",
                entity_id=material.id,
                event_type="source_image_registered",
                payload={
                    "schema_version": SOURCE_SCHEMA_VERSION,
                    "test_id": test.id,
                    "material_id": material.id,
                    "sample_identity": sample_identity,
                    "source_type": SOURCE_MATERIAL_TYPE,
                    "classification": SOURCE_CLASSIFICATION,
                    "storage_ref": storage_ref,
                    **metadata.as_dict(),
                    "provenance": "teacher_provided_real_student_answer_image",
                },
            )
        )
        return material, True, storage_ref

    def _submission(
        self, test: Test, student: Student, material: TestMaterial, sample_identity: str
    ) -> tuple[StudentSubmission, bool]:
        existing = list(
            self.session.scalars(
                select(StudentSubmission).join(TestMaterial).where(
                    StudentSubmission.test_id == test.id,
                    StudentSubmission.student_id == student.id,
                    TestMaterial.id == material.id,
                )
            )
        )
        if len(existing) > 1:
            raise StudentSubmissionImportError("DUPLICATE_STUDENT_SUBMISSION")
        if existing:
            submission = existing[0]
            if submission.status != SOURCE_STATUS:
                raise StudentSubmissionImportError("SUBMISSION_STATUS_CONFLICT")
            return submission, False
        # The key is stable across retries while remaining scoped to this Test
        # and source.  No question-level answer JSON is created here.
        submission_key = f"{sample_identity}-{test.id[:8]}-{material.sha256[:16]}"
        submission = self.domain.submission(
            test.id,
            student.id,
            submission_key=submission_key,
            material_id=material.id,
            attempt_number=1,
            status=SOURCE_STATUS,
        )
        return submission, True

    def import_one(self, spec: AnswerSheetSpec) -> ImportResult:
        test = self.session.get(Test, spec.test_id)
        if test is None:
            raise StudentSubmissionImportError("TEST_NOT_FOUND")
        metadata = _png_metadata(spec.source_path)
        student, student_created = self._student(test, spec.sample_identity)
        material, material_created, storage_ref = self._material(
            test, spec.source_path, metadata, spec.sample_identity
        )
        submission, submission_created = self._submission(
            test, student, material, spec.sample_identity
        )
        self.session.flush()
        return ImportResult(
            sample_identity=spec.sample_identity,
            test_id=test.id,
            student_id=student.id,
            material_id=material.id,
            submission_id=submission.id,
            submission_key=submission.submission_key,
            source=metadata,
            student_created=student_created,
            material_created=material_created,
            submission_created=submission_created,
            storage_ref=storage_ref,
        )


def write_manifest(path: str | Path, results: list[ImportResult], *, phase: str) -> None:
    """Write a privacy-minimal deterministic import audit artifact."""
    payload = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "phase": phase,
        "classification": SOURCE_CLASSIFICATION,
        "results": [r.as_dict() for r in sorted(results, key=lambda x: (x.test_id, x.sample_identity))],
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
