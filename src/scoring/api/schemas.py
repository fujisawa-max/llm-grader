from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Any

class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
class UserCreate(BaseModel): display_name: str; email: str | None = None
class UserResponse(APIModel):
    id: str; display_name: str; email: str | None = None; role: str = "teacher"
    is_active: bool; must_change_password: bool = False; created_at: datetime; updated_at: datetime
class LoginRequest(BaseModel): email: str; password: str
class SetupInitializeRequest(BaseModel):
    display_name: str
    email: str
    password: str
class AdminUserCreate(BaseModel):
    display_name: str
    email: str
    role: str = "teacher"
    initial_password: str | None = None
class AdminUserUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
class PasswordChangeRequest(BaseModel): current_password: str; new_password: str
class PasswordResetRequest(BaseModel): new_password: str | None = None
class CourseTerm(BaseModel):
    academic_year: int = Field(ge=1900, le=2200)
    term: str
    offering_id: str | None = None
class CourseCreate(BaseModel):
    owner_user_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    code: str | None = None
    description: str | None = None
    offering: CourseTerm | None = None
class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = None
    description: str | None = None
    is_archived: bool | None = None
    offering: CourseTerm | None = None
class OfferingCreate(BaseModel): academic_year: int; term: str; term_label: str | None = None; section: str | None = None; display_name: str | None = None
class OfferingUpdate(BaseModel): academic_year: int | None = Field(default=None, ge=1900, le=2200); term: str | None = None; term_label: str | None = None; section: str | None = None; display_name: str | None = None; is_archived: bool | None = None
class TestCreate(BaseModel): name: str; description: str | None = None; test_date: date | None = None; total_points: float = 0
class TestUpdate(BaseModel): name: str | None = None; description: str | None = None; test_date: date | None = None; total_points: float | None = None; status: str | None = None
class QuestionCreate(BaseModel): question_number: str; title: str | None = None; question_text: str | None = None; max_points: float; sort_order: int = 0
class QuestionUpdate(BaseModel): title: str | None = None; question_text: str | None = None; max_points: float | None = None; sort_order: int | None = None
class MaterialCreate(BaseModel): material_type: str; storage_ref: str; original_filename: str | None = None; mime_type: str | None = None; sha256: str | None = None
class ModelAnswerCreate(BaseModel): question_id: str | None = None; answer_text: str | None = None; material_id: str | None = None; provenance_json: dict[str, Any] | None = None
class PolicyCreate(BaseModel): policy_text: str
class SampleAnswerCreate(BaseModel): sample_key: str; material_id: str | None = None; transcription: str | None = None
class SampleScoreCreate(BaseModel): question_id: str | None = None; score: float = Field(ge=0); max_score: float = Field(gt=0); teacher_comment: str | None = None
class StudentCreate(BaseModel): student_identifier: str; display_name: str | None = None
class SubmissionCreate(BaseModel):
    student_id: str | None = None
    submission_key: str | None = None
    material_id: str | None = None
    attempt_number: int = 1
    material_ids: list[str] | None = Field(default=None, max_length=100)
    student_identifier: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, max_length=200)
class RubricCreate(BaseModel): rubric_json: dict[str, Any]; rubric_text: str | None = None; source_type: str = "manual"
class RubricApprove(BaseModel): approved_by_user_id: str
