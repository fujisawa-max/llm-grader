import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from scoring.db import Base
from scoring.domain import DomainService

@pytest.fixture
def s():
    e=create_engine("sqlite:///:memory:"); Base.metadata.create_all(e)
    with sessionmaker(e)() as x: yield x

def setup(s):
    d=DomainService(s); u=d.user(display_name="T"); c=d.course(u.id,name="C"); o=d.offering(c.id,academic_year=2026,term="fall"); t=d.test(o.id,name="X",total_points=10); q=d.question(t.id,question_number="1",max_points=10); return d,u,o,t,q

def test_domain_readiness_and_rubric(s):
    d,u,o,t,q=setup(s); m=d.material(t.id,material_type="student_submission_source",storage_ref="internal:x"); d.model_answer(t.id,question_id=q.id,answer_text="a"); d.policy(t.id,policy_text="p")
    r=d.rubric(t.id,{"questions":[{"question_id":q.id,"max_points":10,"criteria":[{"id":"c","description":"ok","points":10}]}]}); d.approve_rubric(r.id,u.id); st=d.student(o.id,student_identifier="S"); d.submission(t.id,st.id,submission_key="s",material_id=m.id); assert d.readiness(t.id)["ready"]

def test_rubric_rejects_wrong_points(s):
    d,u,o,t,q=setup(s)
    with pytest.raises(ValueError): d.rubric(t.id,{"questions":[{"question_id":q.id,"max_points":10,"criteria":[]}]})

def test_status_transition_requires_readiness(s):
    d,u,o,t,q=setup(s)
    with pytest.raises(ValueError): d.transition_test(t.id,"setup") if False else d.transition_test(t.id,"ready")

def test_status_valid_setup(s):
    d,u,o,t,q=setup(s); assert d.transition_test(t.id,"setup").status == "setup"

def test_cross_offering_submission_rejected(s):
    d,u,o,t,q=setup(s); c2=d.course(u.id,name="C2"); o2=d.offering(c2.id,academic_year=2026,term="fall"); st=d.student(o2.id,student_identifier="X"); m=d.material(t.id,material_type="student_submission_source",storage_ref="x")
    with pytest.raises(ValueError): d.submission(t.id,st.id,submission_key="x",material_id=m.id)

def test_model_answer_versions_increment(s):
    d,u,o,t,q=setup(s); a=d.model_answer(t.id,question_id=q.id,answer_text="1"); b=d.model_answer(t.id,question_id=q.id,answer_text="2"); assert (a.version,b.version)==(1,2); assert not a.is_current and b.is_current

def test_policy_versions_increment(s):
    d,u,o,t,q=setup(s); a=d.policy(t.id,policy_text="1"); b=d.policy(t.id,policy_text="2"); assert (a.version,b.version)==(1,2); assert not a.is_current and b.is_current

def test_rubric_supersedes(s):
    d,u,o,t,q=setup(s); data={"questions":[{"question_id":q.id,"max_points":10,"criteria":[{"id":"c","description":"ok","points":10}]}]}; a=d.rubric(t.id,data); d.approve_rubric(a.id,u.id); b=d.rubric(t.id,data); d.approve_rubric(b.id,u.id); assert a.status=="superseded" and b.status=="approved"

def test_sample_score_bounds(s):
    d,u,o,t,q=setup(s); a=d.sample_answer(t.id,sample_key="a")
    with pytest.raises(ValueError): d.sample_score(a.id,question_id=q.id,score=11,max_score=10)

def test_readiness_missing_material(s):
    d,u,o,t,q=setup(s); d.model_answer(t.id,question_id=q.id,answer_text="a"); d.policy(t.id,policy_text="p"); r=d.rubric(t.id,{"questions":[{"question_id":q.id,"max_points":10,"criteria":[{"id":"c","description":"ok","points":10}]}]}); d.approve_rubric(r.id,u.id); st=d.student(o.id,student_identifier="S"); assert not d.readiness(t.id)["ready"]

def test_generation_interface(s):
    from scoring.domain import RubricGenerationService
    d,u,o,t,q=setup(s); out,meta=RubricGenerationService().generate(t,[q],[],None,[]); assert "questions" in out and meta["status"]=="generated"
