"""Domain services for course/test setup and rubric lifecycle."""
from datetime import datetime, timezone
import math
from uuid import uuid4
from sqlalchemy import select
from .db.models import (User, Course, CourseOffering, Test, TestQuestion, TestMaterial,
    ModelAnswer, GradingPolicy, RubricVersion, Student, StudentSubmission, SampleAnswer, SampleAnswerScore, DomainEvent)

TERMS = {"first_semester", "second_semester", "spring", "fall", "full_year", "other"}

class RubricGenerationService:
    """Synchronous-free interface; concrete workers may enqueue model generation later."""
    def generate(self, test, questions, model_answers, grading_policy, sample_answers):
        return {"questions": [{"question_id": q.id, "max_points": q.max_points, "criteria": []}
                              for q in questions]}, {"source": "stub", "status": "generated"}

def now(): return datetime.now(timezone.utc)

def validate_rubric(data, test=None):
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list): raise ValueError("rubric.questions is required")
    total = 0
    ids = set()
    for q in questions:
        if not isinstance(q, dict) or not q.get("question_id") or q["question_id"] in ids:
            raise ValueError("duplicate or missing question_id")
        ids.add(q["question_id"])
        maximum = q.get("max_points")
        if (isinstance(maximum, bool) or not isinstance(maximum, (int, float))
                or not math.isfinite(maximum) or maximum <= 0 or maximum != int(maximum)):
            raise ValueError("invalid rubric max_points")
        criteria = q.get("criteria", [])
        if not isinstance(criteria, list) or not criteria:
            raise ValueError("rubric criteria are required")
        criterion_ids = set()
        for c in criteria:
            if not isinstance(c, dict) or not c.get("id") or c["id"] in criterion_ids:
                raise ValueError("duplicate or missing criterion id")
            criterion_ids.add(c["id"])
            points_value = c.get("points")
            if (isinstance(points_value, bool) or not isinstance(points_value, (int, float))
                    or not math.isfinite(points_value) or points_value <= 0
                    or points_value != int(points_value) or not str(c.get("description") or "").strip()):
                raise ValueError("invalid criterion points or description")
        points = sum(float(c.get("points", 0)) for c in criteria)
        if abs(points - float(q.get("max_points", 0))) > 1e-6: raise ValueError("criteria points must equal max_points")
        total += float(q.get("max_points", 0))
    if test is not None and abs(total - float(test.total_points)) > 1e-6: raise ValueError("rubric total does not match test")
    return data

class DomainService:
    def __init__(self, session, *, artifact_root=None): self.s = session; self.artifact_root = artifact_root
    def _event(self, entity_type, entity_id, event_type, actor_user_id=None, payload=None):
        self.s.add(DomainEvent(entity_type=entity_type, entity_id=entity_id, event_type=event_type,
                               actor_user_id=actor_user_id, payload=payload or {}))
    def user(self, **v):
        x=User(id=str(uuid4()), **v); self.s.add(x); self.s.flush(); self._event("user",x.id,"user_created"); return x
    def course(self, owner_user_id, **v):
        if not self.s.get(User, owner_user_id): raise ValueError("owner not found")
        x=Course(id=str(uuid4()), owner_user_id=owner_user_id, **v); self.s.add(x); self.s.flush(); self._event("course",x.id,"course_created"); return x
    def offering(self, course_id, **v):
        if not self.s.get(Course, course_id): raise ValueError("course not found")
        if v.get("term") not in TERMS: raise ValueError("invalid term")
        x=CourseOffering(id=str(uuid4()), course_id=course_id, **v); self.s.add(x); self.s.flush(); self._event("offering",x.id,"offering_created"); return x
    def test(self, course_offering_id, **v):
        if not self.s.get(CourseOffering, course_offering_id): raise ValueError("offering not found")
        x=Test(id=str(uuid4()), course_offering_id=course_offering_id, **v); self.s.add(x); self.s.flush(); self._event("test",x.id,"test_created"); return x
    def transition_test(self, test_id, new_status):
        x = self.s.get(Test, test_id)
        if not x: raise ValueError("test not found")
        allowed = {"draft": {"setup"}, "setup": {"rubric_review"}, "rubric_review": {"ready"},
                   "ready": {"grading"}, "grading": {"completed"}, "completed": {"archived"}, "archived": set()}
        if new_status not in allowed.get(x.status, set()): raise ValueError("invalid test status transition")
        if new_status in {"ready", "grading"} and not self.readiness(test_id)["ready"]:
            raise ValueError("test is not ready")
        old=x.status; x.status = new_status; self.s.flush(); self._event("test",x.id,"test_status_changed",payload={"from":old,"to":new_status}); return x
    def question(self, test_id, **v):
        if not self.s.get(Test, test_id): raise ValueError("test not found")
        x=TestQuestion(id=str(uuid4()), test_id=test_id, **v); self.s.add(x); self.s.flush(); self._event("question",x.id,"question_created"); return x
    def material(self, test_id, **v):
        x=TestMaterial(id=str(uuid4()), test_id=test_id, **v); self.s.add(x); self.s.flush(); self._event("material",x.id,"material_created"); return x
    def model_answer(self, test_id, **v):
        q=v.get("question_id"); qobj=self.s.get(TestQuestion,q) if q else None
        if not self.s.get(Test, test_id): raise ValueError("test not found")
        if v.get("answer_text") is not None and len(v["answer_text"]) > 100000:
            raise ValueError("model answer too long")
        if q and not qobj: raise ValueError("question not found")
        if qobj and not qobj.is_gradable: raise ValueError("STRUCTURAL_ASSOCIATION_FORBIDDEN")
        mat=self.s.get(TestMaterial,v.get("material_id")) if v.get("material_id") else None
        if qobj and qobj.test_id != test_id: raise ValueError("question/test mismatch")
        if mat and mat.test_id != test_id: raise ValueError("material/test mismatch")
        n=(self.s.scalar(select(ModelAnswer.version).where(ModelAnswer.test_id==test_id, ModelAnswer.question_id==q).order_by(ModelAnswer.version.desc())) or 0)+1
        self.s.query(ModelAnswer).filter(ModelAnswer.test_id==test_id, ModelAnswer.question_id==q).update({"is_current":False})
        x=ModelAnswer(id=str(uuid4()), test_id=test_id, version=n, **v); self.s.add(x); self.s.flush(); self._event("model_answer",x.id,"model_answer_version_created"); return x
    def policy(self, test_id, **v):
        n=(self.s.scalar(select(GradingPolicy.version).where(GradingPolicy.test_id==test_id).order_by(GradingPolicy.version.desc())) or 0)+1
        self.s.query(GradingPolicy).filter(GradingPolicy.test_id==test_id).update({"is_current":False})
        x=GradingPolicy(id=str(uuid4()), test_id=test_id, version=n, **v); self.s.add(x); self.s.flush(); self._event("grading_policy",x.id,"grading_policy_version_created"); return x
    def rubric(self, test_id, rubric_json, **v):
        t=self.s.get(Test,test_id); validate_rubric(rubric_json,t)
        valid_ids={x.id for x in self.s.scalars(select(TestQuestion).where(TestQuestion.test_id==test_id, TestQuestion.is_gradable.is_(True)))}
        if any(q.get("question_id") not in valid_ids for q in rubric_json.get("questions", [])): raise ValueError("unknown question_id")
        n=(self.s.scalar(select(RubricVersion.version).where(RubricVersion.test_id==test_id).order_by(RubricVersion.version.desc())) or 0)+1
        x=RubricVersion(id=str(uuid4()), test_id=test_id, version=n, rubric_json=rubric_json, status="generated", **v); self.s.add(x); self.s.flush(); self._event("rubric",x.id,"rubric_created"); return x
    def approve_rubric(self, rid, user_id):
        x=self.s.get(RubricVersion,rid)
        if not x or x.status not in {"generated","draft"}: raise ValueError("rubric not approvable")
        validate_rubric(x.rubric_json, self.s.get(Test, x.test_id))
        valid_ids = {q.id for q in self.s.scalars(select(TestQuestion).where(TestQuestion.test_id == x.test_id, TestQuestion.is_gradable.is_(True)))}
        if any(q["question_id"] not in valid_ids for q in x.rubric_json["questions"]):
            raise ValueError("STRUCTURAL_OR_UNKNOWN_QUESTION")
        self.s.query(RubricVersion).filter(RubricVersion.test_id==x.test_id, RubricVersion.status=="approved").update({"status":"superseded"})
        self._event("rubric",x.id,"rubric_superseded",payload={"test_id":x.test_id})
        x.status="approved"; x.approved_at=now(); x.approved_by_user_id=user_id; self.s.flush(); self._event("rubric",x.id,"rubric_approved",actor_user_id=user_id); return x
    def student(self, offering_id, **v):
        x=Student(id=str(uuid4()), course_offering_id=offering_id, **v); self.s.add(x); self.s.flush(); self._event("student",x.id,"student_created"); return x
    def submission(self, test_id, student_id, **v):
        from .test_authoring import latest
        draft = latest(self.s, test_id)
        if draft and draft.state != 'confirmed' and not self.s.scalar(
                select(TestQuestion.id).where(TestQuestion.test_id == test_id).limit(1)):
            raise ValueError("AUTHORING_TEST_NOT_CONFIRMED")
        t=self.s.get(Test,test_id); st=self.s.get(Student,student_id)
        material=self.s.get(TestMaterial,v.get("material_id"))
        if not t or not st or st.course_offering_id != t.course_offering_id: raise ValueError("student/test offering mismatch")
        if not material or material.test_id != test_id: raise ValueError("material/test mismatch")
        x=StudentSubmission(id=str(uuid4()), test_id=test_id, student_id=student_id, **v); self.s.add(x); self.s.flush(); self._event("submission",x.id,"submission_created"); return x
    def sample_answer(self, test_id, **v):
        material_id=v.get("material_id")
        if material_id and (not self.s.get(TestMaterial, material_id) or self.s.get(TestMaterial, material_id).test_id != test_id): raise ValueError("material/test mismatch")
        x=SampleAnswer(id=str(uuid4()), test_id=test_id, **v); self.s.add(x); self.s.flush(); self._event("sample_answer",x.id,"sample_answer_created"); return x
    def sample_score(self, sample_answer_id, **v):
        sample=self.s.get(SampleAnswer,sample_answer_id); q=self.s.get(TestQuestion,v.get("question_id")) if v.get("question_id") else None
        if not sample: raise ValueError("sample answer not found")
        if q and q.test_id != sample.test_id: raise ValueError("question/test mismatch")
        if float(v["score"]) < 0 or float(v["score"]) > float(v["max_score"]): raise ValueError("score out of range")
        if q and float(v["max_score"]) != float(q.max_points): raise ValueError("max_score mismatch")
        x=SampleAnswerScore(id=str(uuid4()), sample_answer_id=sample_answer_id, **v); self.s.add(x); self.s.flush(); self._event("sample_answer_score",x.id,"teacher_score_created"); return x
    def readiness(self, test_id):
        t=self.s.get(Test,test_id); qs=list(self.s.scalars(select(TestQuestion).where(TestQuestion.test_id==test_id, TestQuestion.is_gradable.is_(True)))) if t else []
        ma=list(self.s.scalars(select(ModelAnswer).where(ModelAnswer.test_id==test_id,ModelAnswer.is_current==True))) if t else []
        pol=self.s.scalar(select(GradingPolicy).where(GradingPolicy.test_id==test_id,GradingPolicy.is_current==True)) if t else None
        rub=self.s.scalar(select(RubricVersion).where(RubricVersion.test_id==test_id,RubricVersion.status=="approved")) if t else None
        subs=list(self.s.scalars(select(StudentSubmission).where(StudentSubmission.test_id==test_id))) if t else []
        checks={"questions":bool(qs),"score_ready":bool(qs) and all(q.max_points is not None for q in qs),"model_answers":bool(ma),"grading_policy":pol is not None,"approved_rubric":rub is not None,"student_submissions":bool(subs)}
        from .grading_context import GradingReadinessService
        grading = GradingReadinessService(self.s, root=self.artifact_root).evaluate(test_id)
        checks["question_grading_readiness"] = grading["can_start_grading"]
        checks["model_answers"] = bool(qs) and grading["model_answer_ready_count"] == len(qs)
        checks["approved_rubric"] = bool(qs) and grading["rubric_ready_count"] == len(qs)
        checks["score_ready"] = bool(qs) and grading["score_ready_count"] == len(qs)
        return {"ready":all(checks.values()),"checks":checks,"blocking_reasons":[k for k,v in checks.items() if not v],"blocking_codes":[f"missing_{k}" for k,v in checks.items() if not v], "grading_readiness": grading}
