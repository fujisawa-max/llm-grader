"""Source registration only. Never starts extraction, reconstruction, or grading."""
import hashlib
import json
from pathlib import Path

import fitz
from sqlalchemy import select

from .db.models import TestMaterial, StudentSubmission, Student
from .domain import DomainService

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".pdf": "application/pdf"}
ROLES = {"question_sheet", "model_answer_source", "student_answer_source"}
MAX_PAGES = 100


def inspect_source(data, filename, content_type):
    suffix = Path(filename).suffix.lower()
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError("空ファイルまたは25MBを超えるファイルは登録できません")
    if suffix not in MIMES or content_type != MIMES[suffix]:
        raise ValueError("PNG・JPEG・PDFの形式と拡張子を確認してください")
    if not ((suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
            or (suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"))
            or (suffix == ".pdf" and data.startswith(b"%PDF-"))):
        raise ValueError("ファイル内容と形式が一致しません")
    try:
        with fitz.open(stream=data, filetype=suffix.lstrip(".")) as document:
            if document.needs_pass or not 0 < len(document) <= MAX_PAGES:
                raise ValueError("パスワード付きまたは100ページを超える資料は登録できません")
            for page in document:
                if page.rect.width * page.rect.height > 60_000_000:
                    raise ValueError("画像サイズが大きすぎます")
            return len(document)
    except (RuntimeError, fitz.FileDataError) as exc:
        raise ValueError("ファイルを読み取れません") from exc


def immutable_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as out:
            out.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("保存済み資料の整合性を確認してください")


def register_source(session, root, test_id, role, filename, content_type, data):
    if role not in ROLES:
        raise ValueError("資料の種類が不正です")
    count = inspect_source(data, filename, content_type)
    digest = hashlib.sha256(data).hexdigest()
    # Serialize registration against the Test row for PostgreSQL deduplication.
    from .db.models import Test
    session.scalar(select(Test).where(Test.id == test_id).with_for_update())
    prior = session.scalar(select(TestMaterial).where(
        TestMaterial.test_id == test_id, TestMaterial.material_type == role,
        TestMaterial.sha256 == digest))
    path = Path(root).resolve() / "sources" / test_id / (digest + Path(filename).suffix.lower())
    if prior:
        old = Path(prior.storage_ref)
        old = old if old.is_absolute() else Path(root) / old
        if not old.is_file() or hashlib.sha256(old.read_bytes()).hexdigest() != digest:
            raise ValueError("保存済み資料の整合性を確認してください")
        return prior, count, True
    immutable_write(path, data)
    material = DomainService(session).material(
        test_id, material_type=role, storage_ref=str(path),
        original_filename=Path(filename).name[:255], mime_type=content_type, sha256=digest)
    return material, count, False


def register_submission(session, root, test, material_ids, student_id=None,
                        student_identifier=None, display_name=None):
    """Combine explicitly ordered pages into the existing source manifest contract."""
    if not material_ids or len(material_ids) != len(set(material_ids)):
        raise ValueError("答案資料を選択し、重複するページを除いてください")
    materials = [session.get(TestMaterial, i) for i in material_ids]
    if any(m is None or m.test_id != test.id or m.material_type != "student_answer_source"
           for m in materials):
        raise ValueError("この試験の学生答案資料を選択してください")
    service = DomainService(session)
    # This lock protects both student number creation and attempt allocation.
    from .db.models import CourseOffering
    session.scalar(select(CourseOffering).where(
        CourseOffering.id == test.course_offering_id).with_for_update())
    if student_id:
        student = session.get(Student, student_id)
        if not student or student.course_offering_id != test.course_offering_id:
            raise ValueError("この科目の学生を選択してください")
    else:
        number = (student_identifier or "").strip()
        if not number or len(number) > 128:
            raise ValueError("学籍番号を文字列で入力してください")
        student = session.scalar(select(Student).where(
            Student.course_offering_id == test.course_offering_id,
            Student.student_identifier == number))
        if student and display_name and student.display_name != display_name:
            raise ValueError("同じ学籍番号の学生がいます。登録済み学生から選択してください")
        if not student:
            student = service.student(test.course_offering_id,
                                      student_identifier=number, display_name=display_name)
    signatures = [m.sha256 for m in materials]
    key = hashlib.sha256(json.dumps([test.id, student.id, signatures]).encode()).hexdigest()
    previous = session.scalar(select(StudentSubmission).where(
        StudentSubmission.test_id == test.id, StudentSubmission.submission_key == key))
    if previous:
        return previous
    directory = Path(root).resolve() / "submissions" / test.id / key
    pages = []
    for material in materials:
        source = Path(material.storage_ref)
        source = source if source.is_absolute() else Path(root) / source
        source = source.resolve()
        if not source.is_relative_to(Path(root).resolve()) or not source.is_file():
            raise ValueError("答案資料を読み取れません")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != material.sha256:
            raise ValueError("答案資料の整合性を確認してください")
        if material.mime_type == "application/pdf":
            with fitz.open(stream=data, filetype="pdf") as document:
                for page in document:
                    if len(pages) >= MAX_PAGES:
                        raise ValueError("答案は100ページ以内で登録してください")
                    pixels = page.get_pixmap(dpi=120)
                    name = f"page-{len(pages)+1:03d}.png"
                    immutable_write(directory / name, pixels.tobytes("png"))
                    pages.append({"page_id": name[:-4], "image": name})
        else:
            name = f"page-{len(pages)+1:03d}{source.suffix}"
            immutable_write(directory / name, data)
            pages.append({"page_id": Path(name).stem, "image": name})
    if len(pages) > MAX_PAGES:
        raise ValueError("答案は100ページ以内で登録してください")
    for page in pages:
        page["sha256"] = hashlib.sha256((directory / page["image"]).read_bytes()).hexdigest()
    document = {"submission_id": key, "test_id": test.id, "student_id": student.id,
                "pages": pages, "answers": [], "registration_only": True,
                "source_material_ids": material_ids, "source_sha256s": signatures}
    data = json.dumps(document, ensure_ascii=False, sort_keys=True).encode()
    path = directory / "source.json"
    immutable_write(path, data)
    material = service.material(test.id, material_type="student_answer",
                                storage_ref=str(path), mime_type="application/json",
                                sha256=hashlib.sha256(data).hexdigest())
    attempts = list(session.scalars(select(StudentSubmission.attempt_number).where(
        StudentSubmission.test_id == test.id, StudentSubmission.student_id == student.id)))
    return service.submission(test.id, student.id, material_id=material.id,
                              submission_key=key, attempt_number=max(attempts, default=0)+1)
