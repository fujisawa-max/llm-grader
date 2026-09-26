"""Source-backed student identity extraction for teacher-facing workflows.

Identity is deliberately separate from answer reconstruction.  The source
image and the extracted fields are kept in an immutable artifact; the legacy
``s1``/``s2`` submission key is never used to fill an identity value.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select

from .db.models import DomainEvent, Student, StudentSubmission, Test, TestMaterial
from .pdf_native import sha256_file

IDENTITY_VERSION = "student-identity-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalize_student_number(value: str | None) -> str:
    """Only remove layout whitespace; preserve leading zeroes and case."""
    return re.sub(r"[\s\u3000]+", "", str(value or ""))


def normalize_student_name(value: str | None) -> str:
    return re.sub(r"[\s\u3000]+", " ", str(value or "")).strip()


def header_geometry() -> dict[str, list[float]]:
    # The template header is expressed as normalized page geometry and is
    # intentionally independent of the uploaded filename or fixture name.
    return {
        "header_bbox": [0.56, 0.02, 0.92, 0.17],
        "student_number_bbox": [0.68, 0.075, 0.92, 0.12],
        "student_name_bbox": [0.68, 0.115, 0.92, 0.17],
    }


def _source_for(session, submission_id: str, root: Path):
    submission = session.get(StudentSubmission, submission_id)
    if submission is None:
        raise ValueError("SUBMISSION_NOT_FOUND")
    material = session.get(TestMaterial, submission.material_id)
    if material is None or not material.sha256:
        raise ValueError("STUDENT_SOURCE_MISSING")
    path = Path(material.storage_ref)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file() or not path.is_relative_to(root) or sha256_file(path) != material.sha256:
        raise ValueError("SOURCE_ANSWER_HASH_MISMATCH")
    return submission, material, path


class StudentIdentityService:
    """Create and read idempotent identity artifacts without altering Student rows."""

    def __init__(self, session, *, root: str | Path):
        self.session = session
        self.root = Path(root).resolve()

    def artifact_path(self, submission_id: str, source_sha256: str, revision: int = 1) -> Path:
        suffix = IDENTITY_VERSION if revision == 1 else f"{IDENTITY_VERSION}-v{revision}"
        return self.root / "student-identity" / submission_id / f"{source_sha256}-{suffix}.json"

    def _artifact_candidates(self, submission_id: str, source_sha256: str) -> list[Path]:
        root = self.root / "student-identity" / submission_id
        def revision(value: Path) -> int:
            match = re.search(r"-v(\d+)\.json$", value.name)
            return int(match.group(1)) if match else 1
        return sorted(root.glob(f"{source_sha256}-{IDENTITY_VERSION}*.json"), key=revision)

    def load(self, submission_id: str):
        submission, material, _ = _source_for(self.session, submission_id, self.root)
        candidates = self._artifact_candidates(submission_id, material.sha256)
        if not candidates:
            return None
        path = candidates[-1]
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("source_sha256") != material.sha256 or value.get("submission_id") != submission.id:
            raise ValueError("STUDENT_IDENTITY_ARTIFACT_INVALID")
        return value

    def extract(self, submission_id: str, *, raw: dict[str, Any] | None = None,
                student_number: str | None = None, student_name: str | None = None,
                confidence: float | None = None, review_required: bool | None = None,
                raw_text: str | None = None, evidence: dict[str, Any] | None = None):
        submission, material, source = _source_for(self.session, submission_id, self.root)
        path = self.artifact_path(submission_id, material.sha256)
        if path.is_file():
            return self.load(submission_id)
        raw = raw or {}
        number = normalize_student_number(student_number if student_number is not None else raw.get("student_number", raw.get("student_id")))
        name = normalize_student_name(student_name if student_name is not None else raw.get("student_name", raw.get("name")))
        score = float(confidence if confidence is not None else raw.get("confidence", 0.0) or 0.0)
        warnings = list(raw.get("warnings", [])) if isinstance(raw.get("warnings", []), list) else []
        if not number:
            warnings.append("student_number_unreadable")
        if not name:
            warnings.append("student_name_unreadable")
        duplicate = list(self.session.scalars(select(Student).join(Test, Student.course_offering_id == Test.course_offering_id).where(Test.id == submission.test_id, Student.student_identifier == number))) if number else []
        artifact_duplicates = 0
        if number:
            for candidate in (self.root / "student-identity").glob("*/" + f"*-{IDENTITY_VERSION}*.json"):
                if candidate == path:
                    continue
                try:
                    value = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if value.get("test_id") == submission.test_id and value.get("student_number") == number:
                    artifact_duplicates += 1
        if len(duplicate) > 1 or artifact_duplicates:
            warnings.append("duplicate_student_number")
        needs_review = bool(review_required) if review_required is not None else bool(warnings or score < 0.8)
        payload = {
            "schema_version": IDENTITY_VERSION, "submission_id": submission.id,
            "test_id": submission.test_id, "source_sha256": material.sha256,
            "source_ref": material.storage_ref, "source_bbox": evidence or header_geometry(),
            "raw_text": raw_text if raw_text is not None else raw.get("raw_text", ""),
            "student_number_raw": student_number if student_number is not None else raw.get("student_number", raw.get("student_id", "")),
            "student_name_raw": student_name if student_name is not None else raw.get("student_name", raw.get("name", "")),
            "student_number": number, "student_name": name,
            "display_label": f"{number} {name}".strip() if number or name else "学生情報未確認",
            "confidence": score, "review_required": needs_review,
            "warnings": sorted(set(warnings)), "seat_number": None,
            "identity_source": "answer_image_header", "created_at": _now(),
        }
        payload["artifact_sha256"] = _hash(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        self.session.add(DomainEvent(entity_type="student_identity", entity_id=submission.id,
                                     event_type="student_identity_extracted",
                                     payload={"artifact_ref": str(path.relative_to(self.root)),
                                              "artifact_sha256": payload["artifact_sha256"],
                                              "source_sha256": material.sha256,
                                              "review_required": needs_review}))
        self.session.flush()
        return payload

    def correct(self, submission_id: str, *, student_number: str, student_name: str,
                confidence: float = 1.0, teacher_user_id: str | None = None,
                reason: str = ""):
        """Append a teacher correction while preserving the extracted revision."""
        submission, material, _ = _source_for(self.session, submission_id, self.root)
        previous = self.load(submission_id)
        revision = 2
        while self.artifact_path(submission_id, material.sha256, revision).exists():
            revision += 1
        number = normalize_student_number(student_number)
        name = normalize_student_name(student_name)
        payload = {
            "schema_version": IDENTITY_VERSION, "revision": revision,
            "submission_id": submission.id, "test_id": submission.test_id,
            "source_sha256": material.sha256, "source_ref": material.storage_ref,
            "source_bbox": (previous or {}).get("source_bbox", header_geometry()),
            "raw_text": (previous or {}).get("raw_text", ""),
            "student_number_raw": student_number, "student_name_raw": student_name,
            "student_number": number, "student_name": name,
            "display_label": f"{number} {name}".strip() if number or name else "学生情報未確認",
            "confidence": float(confidence), "review_required": False,
            "warnings": [], "seat_number": None, "identity_source": "teacher_correction",
            "origin": "TEACHER_CORRECTION", "previous_artifact_sha256": (previous or {}).get("artifact_sha256"),
            "teacher_user_id": teacher_user_id, "reason": reason, "created_at": _now(),
        }
        payload["artifact_sha256"] = _hash(payload)
        path = self.artifact_path(submission_id, material.sha256, revision)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        self.session.add(DomainEvent(entity_type="student_identity", entity_id=submission.id,
                                     event_type="student_identity_corrected", actor_user_id=teacher_user_id,
                                     payload={"artifact_ref": str(path.relative_to(self.root)),
                                              "artifact_sha256": payload["artifact_sha256"],
                                              "previous_artifact_sha256": payload["previous_artifact_sha256"],
                                              "reason": reason}))
        self.session.flush()
        return payload
