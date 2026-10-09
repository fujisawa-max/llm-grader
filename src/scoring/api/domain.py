from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from ..domain import DomainService, TERMS
from ..domain_adapter import DomainGradingJobAdapter
from ..grading_context import GradingReadinessService, ContextError, asset_path
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from ..db.models import *
from ..pdf_native import sha256_file
from .schemas import (UserCreate, CourseCreate, CourseUpdate, OfferingCreate, OfferingUpdate,
                      TestCreate, TestUpdate, QuestionCreate, QuestionUpdate, MaterialCreate,
                      ModelAnswerCreate, PolicyCreate, SampleAnswerCreate, SampleScoreCreate,
                      StudentCreate, SubmissionCreate, RubricCreate, RubricApprove)

class MaterialReuse(BaseModel):
    material_type: str

class MaterialRoleChange(BaseModel):
    material_type: str

def router(db, artifact_root=None, allowed_roots=None, grading_visual_config=None,
           storage_root=None):
    r=APIRouter(prefix="/api/v1")
    visual_options = grading_visual_config or {}
    def obj(x):
        d={k:v for k,v in x.__dict__.items() if not k.startswith("_") and k != "password_hash"}
        for k,v in list(d.items()):
            if hasattr(v,"isoformat"): d[k]=v.isoformat()
        return d
    def actor(s):
        return s.info.get("auth_user")
    def owned_course_or_error(course_id, s):
        course = get(Course, course_id, s)
        current = actor(s)
        if current and current.role != "admin" and course.owner_user_id != current.id:
            raise HTTPException(403, "COURSE_ACCESS_DENIED")
        return course
    def owned_test_or_error(test_id, s):
        test = get(Test, test_id, s)
        if s.get(TestArchive, test_id):
            raise HTTPException(410, "TEST_ARCHIVED")
        offering = get(CourseOffering, test.course_offering_id, s)
        owned_course_or_error(offering.course_id, s)
        return test
    def get(model,i,s):
        x=s.get(model,i)
        if not x: raise HTTPException(404,"not found")
        return x
    @r.post("/users",status_code=201)
    def users(v:UserCreate,s=Depends(db)):
        current = actor(s)
        if current and current.role != "admin": raise HTTPException(403, "ADMIN_ROLE_REQUIRED")
        x=DomainService(s).user(**v.model_dump()); s.commit(); return obj(x)
    @r.get("/users")
    def users_list(s=Depends(db)):
        current = actor(s)
        if current and current.role != "admin": raise HTTPException(403, "ADMIN_ROLE_REQUIRED")
        return [obj(x) for x in s.scalars(select(User))]
    @r.get("/users/{i}")
    def user(i,s=Depends(db)):
        current = actor(s)
        if current and current.role != "admin": raise HTTPException(403, "ADMIN_ROLE_REQUIRED")
        return obj(get(User,i,s))
    @r.post("/courses",status_code=201)
    def courses(v:CourseCreate,s=Depends(db)):
        current = actor(s)
        values = v.model_dump()
        term = values.pop("offering", None)
        if current and (current.role != "admin" or not values.get("owner_user_id")):
            values["owner_user_id"] = current.id
        try:
            service = DomainService(s)
            x = service.course(**values)
            if term:
                term.pop("offering_id", None)
                service.offering(x.id, **term)
            s.commit()
            return obj(x)
        except ValueError as e:
            s.rollback()
            raise HTTPException(400,str(e))
    @r.get("/courses")
    def courses_list(s=Depends(db)):
        current = actor(s); query = select(Course)
        if current and current.role != "admin": query = query.where(Course.owner_user_id == current.id)
        return [obj(x) for x in s.scalars(query)]
    @r.get("/courses/{i}")
    def course(i,s=Depends(db)): return obj(owned_course_or_error(i,s))
    @r.patch("/courses/{i}")
    def course_patch(i,v:CourseUpdate,s=Depends(db)):
        x = owned_course_or_error(i,s)
        values = v.model_dump(exclude_unset=True)
        term = values.pop("offering", None)
        if term:
            if term["term"] not in TERMS:
                raise HTTPException(422, "開講時期が不正です")
            target = get(CourseOffering, term.get("offering_id"), s) if term.get("offering_id") else None
            if target and target.course_id != i:
                raise HTTPException(403, "COURSE_ACCESS_DENIED")
            if target:
                target.academic_year = term["academic_year"]
                target.term = term["term"]
                s.add(DomainEvent(entity_type="offering", entity_id=target.id, event_type="offering_updated"))
            else:
                DomainService(s).offering(i, academic_year=term["academic_year"], term=term["term"])
        for k, val in values.items():
            if val is not None or k in {"code", "description"}:
                setattr(x, k, val)
        x.updated_at = now()
        s.add(DomainEvent(entity_type="course",entity_id=x.id,event_type="course_updated"))
        s.commit()
        return obj(x)
    @r.post("/courses/{cid}/offerings",status_code=201)
    def offerings(cid,v:OfferingCreate,s=Depends(db)):
        owned_course_or_error(cid, s)
        try: x=DomainService(s).offering(cid,**v.model_dump()); s.commit(); return obj(x)
        except ValueError as e: raise HTTPException(400,str(e))
    @r.get("/courses/{cid}/offerings")
    def offerings_list(cid,s=Depends(db)):
        owned_course_or_error(cid, s)
        return [obj(x) for x in s.scalars(select(CourseOffering).where(CourseOffering.course_id==cid))]
    @r.get("/offerings/{i}")
    def offering(i,s=Depends(db)):
        x = get(CourseOffering,i,s); owned_course_or_error(x.course_id, s); return obj(x)
    @r.patch("/offerings/{i}")
    def offering_patch(i,v:OfferingUpdate,s=Depends(db)): x=get(CourseOffering,i,s); owned_course_or_error(x.course_id,s); [setattr(x,k,val) for k,val in v.model_dump(exclude_none=True).items()]; s.add(DomainEvent(entity_type="offering",entity_id=x.id,event_type="offering_updated")); s.commit(); return obj(x)
    @r.post("/offerings/{oid}/tests",status_code=201)
    def tests(oid,v:TestCreate,s=Depends(db)):
        offering_obj = get(CourseOffering, oid, s); owned_course_or_error(offering_obj.course_id, s)
        try: x=DomainService(s).test(oid,**v.model_dump()); s.commit(); return obj(x)
        except ValueError as e: raise HTTPException(400,str(e))
    @r.get("/offerings/{oid}/tests")
    def tests_list(oid,s=Depends(db)):
        offering_obj = get(CourseOffering, oid, s); owned_course_or_error(offering_obj.course_id,s)
        return [obj(x) for x in s.scalars(select(Test).where(Test.course_offering_id==oid, ~Test.id.in_(select(TestArchive.test_id))))]
    @r.get("/tests/{i}")
    def test(i,s=Depends(db)): return obj(owned_test_or_error(i,s))
    @r.patch("/tests/{i}")
    def test_patch(i,v:TestUpdate,s=Depends(db)):
        x=owned_test_or_error(i,s); d=v.model_dump(exclude_none=True)
        if "status" in d: raise HTTPException(409,"use transition endpoint for status")
        [setattr(x,k,val) for k,val in d.items()]; s.add(DomainEvent(entity_type="test",entity_id=x.id,event_type="test_updated")); s.commit(); return obj(x)
    @r.post("/tests/{tid}/questions",status_code=201)
    def questions(tid,v:QuestionCreate,s=Depends(db)):
        owned_test_or_error(tid,s)
        try: x=DomainService(s).question(tid,**v.model_dump()); s.commit(); return obj(x)
        except Exception as e: s.rollback(); raise HTTPException(409,str(e))
    @r.get("/tests/{tid}/questions")
    def questions_list(tid,s=Depends(db)):
        owned_test_or_error(tid,s)
        return [obj(x) for x in s.scalars(select(TestQuestion).where(TestQuestion.test_id==tid))]
    @r.patch("/questions/{i}")
    def question_patch(i,v:QuestionUpdate,s=Depends(db)):
        x=get(TestQuestion,i,s); owned_test_or_error(x.test_id,s)
        if (x.provenance or {}).get("origin") == "review_import":
            raise HTTPException(409, "imported_question_read_only")
        [setattr(x,k,val) for k,val in v.model_dump(exclude_none=True).items()]; s.commit(); return obj(x)
    @r.post("/tests/{tid}/materials", status_code=201)
    def materials(tid, v: MaterialCreate, s=Depends(db)):
        try:
            x = DomainService(s).material(tid, **v.model_dump()); s.commit(); return obj(x)
        except Exception as e:
            s.rollback(); raise HTTPException(400, str(e))
    @r.get("/tests/{tid}/materials")
    def materials_list(tid, s=Depends(db)):
        owned_test_or_error(tid, s)
        from ..source_registration import deleted_material_ids
        deleted = deleted_material_ids(s, tid)
        return [obj(x) for x in s.scalars(select(TestMaterial).where(TestMaterial.test_id == tid)) if x.id not in deleted]

    @r.delete("/tests/{tid}/materials/{mid}")
    def material_delete(tid: str, mid: str, s=Depends(db)):
        owned_test_or_error(tid, s)
        material = s.get(TestMaterial, mid)
        from ..source_registration import deleted_material_ids
        if not material or material.test_id != tid or mid in deleted_material_ids(s, tid):
            raise HTTPException(404, "material not found")
        s.add(DomainEvent(entity_type="material", entity_id=mid, actor_user_id=actor(s).id,
                          event_type="material_binding_deleted",
                          payload={"test_id": tid, "role": material.material_type}))
        s.commit()
        return {"deleted": True, "material_id": mid}

    @r.patch("/tests/{tid}/materials/{mid}/role")
    def material_role_change(tid: str, mid: str, body: MaterialRoleChange, s=Depends(db)):
        owned_test_or_error(tid, s)
        from ..source_registration import reuse_source, deleted_material_ids
        material = s.get(TestMaterial, mid)
        if not material or material.test_id != tid or mid in deleted_material_ids(s, tid):
            raise HTTPException(404, "material not found")
        try:
            collision = s.scalar(select(TestMaterial).where(TestMaterial.test_id == tid,
                TestMaterial.material_type == body.material_type, TestMaterial.sha256 == material.sha256))
            if collision and collision.id != mid and collision.id not in deleted_material_ids(s, tid):
                raise ValueError("同じファイルは変更先の資料の種類で登録済みです")
            replacement, reused = reuse_source(s, storage_root or artifact_root, tid, mid,
                body.material_type, allowed_roots)
            if replacement.id == mid:
                raise ValueError("資料の種類が同じです")
            s.add(DomainEvent(entity_type="material", entity_id=mid, actor_user_id=actor(s).id,
                              event_type="material_binding_deleted",
                              payload={"test_id": tid, "role": material.material_type,
                                       "replaced_by": replacement.id}))
            s.commit()
            return {**obj(replacement), "reused": reused}
        except ValueError as exc:
            s.rollback()
            raise HTTPException(409, str(exc)) from exc

    @r.post("/tests/{tid}/materials/upload", status_code=201)
    async def material_upload(tid: str, request: Request, s=Depends(db)):
        owned_test_or_error(tid, s)
        from urllib.parse import unquote
        from ..source_registration import register_source, MAX_SOURCE_BYTES
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_SOURCE_BYTES:
                raise HTTPException(413, "ファイルは25MB以内で登録してください")
        try:
            material, count, reused = register_source(
                s, storage_root or artifact_root, tid,
                request.headers.get("x-source-role"),
                unquote(request.headers.get("x-filename", "")),
                request.headers.get("content-type", "").split(";")[0], bytes(data))
            s.commit()
            return {**obj(material), "page_count": count, "reused": reused}
        except ValueError as exc:
            s.rollback()
            raise HTTPException(422, str(exc)) from exc

    @r.post("/tests/{tid}/materials/{mid}/reuse", status_code=201)
    def material_reuse(tid: str, mid: str, body: MaterialReuse, s=Depends(db)):
        owned_test_or_error(tid, s)
        from ..source_registration import reuse_source
        try:
            material, reused = reuse_source(s, storage_root or artifact_root, tid, mid, body.material_type, allowed_roots)
            s.commit()
            return {**obj(material), 'reused': reused}
        except ValueError as exc:
            s.rollback()
            raise HTTPException(422, str(exc)) from exc

    @r.get("/tests/{tid}/materials/{mid}/file")
    def material_file(tid, mid, s=Depends(db)):
        """Serve an immutable teacher source material after path/SHA checks.

        The UI only uses this for in-browser PDF previews.  The database row is
        still the source of truth and the bytes are never copied or rewritten.
        """
        material = get(TestMaterial, mid, s)
        from ..source_registration import deleted_material_ids
        if material.test_id != tid or mid in deleted_material_ids(s, tid):
            raise HTTPException(404, "material not found")
        stored = Path(material.storage_ref)
        # Question/context assets are rooted at ``artifact_root`` (the
        # question-imports directory), while TestMaterial storage references
        # are persisted relative to the unified artifact store.  Resolve
        # relative material refs against the latter first and retain the
        # question-import root for effective-context assets.
        root = Path(artifact_root or ".").resolve()
        material_root = Path(storage_root or root).resolve()
        path = (stored if stored.is_absolute() else material_root / stored).resolve()
        roots = [Path(x).resolve() for x in (allowed_roots or [root])]
        if not path.is_file() or not any(path == root or root in path.parents for root in roots):
            raise HTTPException(404, "material file not found")
        if material.sha256 and sha256_file(path) != material.sha256:
            raise HTTPException(409, "material_integrity_error")
        return FileResponse(path, media_type=material.mime_type or "application/octet-stream")
    def versioned(path, Model, method, schema):
        @r.post(path,status_code=201)
        def create(tid,v:schema,s=Depends(db)):
            try: x=method(DomainService(s),tid,**v.model_dump()); s.commit(); return obj(x)
            except Exception as e: s.rollback(); raise HTTPException(400,str(e))
        @r.get(path)
        def listing(tid,s=Depends(db)): return [obj(x) for x in s.scalars(select(Model).where(Model.test_id==tid))]
    versioned("/tests/{tid}/model-answers",ModelAnswer,DomainService.model_answer,ModelAnswerCreate)
    versioned("/tests/{tid}/grading-policies",GradingPolicy,DomainService.policy,PolicyCreate)
    @r.post("/tests/{tid}/sample-answers", status_code=201)
    def sample_answers(tid, v: SampleAnswerCreate, s=Depends(db)):
        try:
            x = DomainService(s).sample_answer(tid, **v.model_dump())
            s.commit(); return obj(x)
        except Exception as e:
            s.rollback(); raise HTTPException(400, str(e))
    @r.get("/tests/{tid}/sample-answers")
    def sample_answers_list(tid, s=Depends(db)):
        return [obj(x) for x in s.scalars(select(SampleAnswer).where(SampleAnswer.test_id == tid))]
    @r.post("/sample-answers/{sid}/scores", status_code=201)
    def sample_score(sid, v: SampleScoreCreate, s=Depends(db)):
        try:
            x = DomainService(s).sample_score(sid, **v.model_dump()); s.commit(); return obj(x)
        except ValueError as e:
            s.rollback(); raise HTTPException(409, str(e))
    @r.post("/tests/{tid}/rubrics",status_code=201)
    def rubric(tid,v:RubricCreate,s=Depends(db)):
        try:
            d=v.model_dump(); x=DomainService(s).rubric(tid,d.pop("rubric_json"),**d); s.commit(); return obj(x)
        except Exception as e: s.rollback(); raise HTTPException(400,str(e))
    @r.get("/tests/{tid}/rubrics")
    def rubrics(tid,s=Depends(db)): return [obj(x) for x in s.scalars(select(RubricVersion).where(RubricVersion.test_id==tid))]
    @r.get("/rubrics/{i}")
    def rubric_get(i,s=Depends(db)): return obj(get(RubricVersion,i,s))
    @r.post("/rubrics/{i}/approve")
    def approve(i,v:RubricApprove,s=Depends(db)):
        try: x=DomainService(s).approve_rubric(i,v.approved_by_user_id); s.commit(); return obj(x)
        except Exception as e: s.rollback(); raise HTTPException(409,str(e))
    @r.post("/offerings/{oid}/students",status_code=201)
    def students(oid,v:StudentCreate,s=Depends(db)):
        try: x=DomainService(s).student(oid,**v.model_dump()); s.commit(); return obj(x)
        except Exception as e: s.rollback(); raise HTTPException(409,str(e))
    @r.get("/offerings/{oid}/students")
    def students_list(oid,s=Depends(db)): return [obj(x) for x in s.scalars(select(Student).where(Student.course_offering_id==oid))]
    @r.post("/tests/{tid}/submissions",status_code=201)
    def submissions(tid,v:SubmissionCreate,s=Depends(db)):
        test = owned_test_or_error(tid, s)
        try:
            if v.material_ids is not None:
                from ..source_registration import register_submission
                x = register_submission(s, storage_root or artifact_root, test,
                                        v.material_ids, v.student_id,
                                        v.student_identifier, v.display_name)
            else:
                if not v.material_id or not v.student_id or not v.submission_key:
                    raise ValueError("学生と答案資料を指定してください")
                x = DomainService(s).submission(tid, **v.model_dump(include={
                    "student_id", "submission_key", "material_id", "attempt_number"}))
            s.commit()
            return obj(x)
        except ValueError as e:
            s.rollback()
            raise HTTPException(422, str(e)) from e
    @r.get("/tests/{tid}/submissions")
    def submissions_list(tid,s=Depends(db)): return [obj(x) for x in s.scalars(select(StudentSubmission).where(StudentSubmission.test_id==tid))]
    @r.get("/tests/{tid}/readiness")
    def readiness(tid,s=Depends(db)): return DomainService(s, artifact_root=artifact_root).readiness(tid)
    @r.get("/tests/{tid}/grading-readiness")
    def grading_readiness(tid, s=Depends(db)):
        get(Test, tid, s)
        return GradingReadinessService(s, root=artifact_root).evaluate(tid)
    @r.get("/test-questions/{qid}/effective-grading-context")
    def effective_context(qid, s=Depends(db)):
        get(TestQuestion, qid, s)
        try: return GradingReadinessService(s, root=artifact_root).context(qid)
        except ContextError as e:
            raise HTTPException(409, {"error": {"code": e.code, "message": "Context unavailable"}})
    @r.get("/tests/{tid}/submissions/{sid}/grading-input-readiness")
    def mapping_readiness(tid, sid, s=Depends(db)):
        from ..grading_mapping import GradingInputAssembler
        get(Test, tid, s)
        try:
            return GradingInputAssembler(s, tid, root=artifact_root, allowed_roots=allowed_roots).evaluate(sid)
        except ContextError as exc:
            raise HTTPException(404 if exc.code == "SUBMISSION_NOT_FOUND" else 409, exc.code)

    @r.get("/tests/{tid}/submissions/{sid}/questions/{qid}/grading-input-preview")
    def input_preview(tid, sid, qid, s=Depends(db)):
        q = get(TestQuestion, qid, s)
        if q.test_id != tid:
            raise HTTPException(404, "question not found")
        if not q.is_gradable:
            raise HTTPException(409, "ANSWER_MAPPED_TO_STRUCTURAL_QUESTION")
        from ..grading_mapping import GradingInputAssembler
        try:
            return GradingInputAssembler(s, tid, root=artifact_root,
                allowed_roots=allowed_roots, **visual_options).execution_preview(sid, qid)
        except (ContextError, ValueError) as exc:
            raise HTTPException(409, str(exc))

    @r.get('/tests/{tid}/submissions/{sid}/questions/{qid}/visual-assets/{aid}')
    def student_visual_asset(tid, sid, qid, aid, s=Depends(db)):
        if get(StudentSubmission, sid, s).test_id != tid or get(TestQuestion, qid, s).test_id != tid:
            raise HTTPException(404, 'asset not found')
        from ..student_visual import StudentVisualAssetService, safe_file
        root = visual_options.get('answer_root') or artifact_root
        try:
            asset = StudentVisualAssetService(s, root).get(aid, sid, qid)
            return FileResponse(safe_file(root, asset['artifact_ref'], asset['sha256']), media_type=asset['mime_type'])
        except ValueError:
            raise HTTPException(409, 'STUDENT_VISUAL_ASSET_UNAVAILABLE')

    @r.get("/tests/{tid}/test-question-assets/{aid}")
    def context_asset(tid, aid, s=Depends(db)):
        a = get(TestQuestionAsset, aid, s)
        if get(TestQuestion, a.question_id, s).test_id != tid: raise HTTPException(404, "asset not found")
        try: return FileResponse(asset_path(a, artifact_root), media_type=a.mime_type)
        except ContextError as e: raise HTTPException(409, e.code)
    @r.delete("/model-answers/{aid}")
    def retire_answer(aid, s=Depends(db)):
        a = get(ModelAnswer, aid, s)
        a.is_current = False
        s.add(DomainEvent(entity_type="model_answer", entity_id=aid, event_type="model_answer_retired"))
        s.commit()
        return {"id": aid, "is_current": False}
    @r.delete("/rubrics/{rid}")
    def retire_rubric(rid, s=Depends(db)):
        a = get(RubricVersion, rid, s)
        a.status = "superseded"
        s.add(DomainEvent(entity_type="rubric", entity_id=rid, event_type="rubric_retired"))
        s.commit()
        return {"id": rid, "status": "superseded"}
    @r.post("/tests/{tid}/transition")
    def transition(tid, v: dict, s=Depends(db)):
        try:
            x = DomainService(s, artifact_root=artifact_root).transition_test(tid, v.get("target_status")); s.commit(); return obj(x)
        except ValueError as e:
            s.rollback(); raise HTTPException(409, str(e))
    @r.get("/tests/{tid}/events")
    def test_events(tid, s=Depends(db)):
        get(Test, tid, s)
        return [obj(x) for x in s.scalars(select(DomainEvent).where(DomainEvent.entity_type == "test", DomainEvent.entity_id == tid).order_by(DomainEvent.created_at))]
    @r.get("/tests/{tid}/submissions/{sid}/grading-jobs/{jid}/result")
    def grading_result(tid, sid, jid, s=Depends(db)):
        job = get(GradingJob, jid, s)
        sub = get(StudentSubmission, sid, s)
        snapshot = (job.metadata_json or {}).get("grading_execution", {})
        bundle = snapshot.get("bundle", {})
        if (job.test_id != tid or sub.test_id != tid
                or bundle.get("student_answer", {}).get("submission_id") != sid):
            raise HTTPException(404, "result_not_found")
        item = job.items[0]
        return {"job_id": jid, "item_id": item.id, "state": job.state,
                "score": item.score, "max_points": item.max_score,
                "result": (item.metadata_json or {}).get("result"),
                "bundle": bundle, "snapshot_sha256": snapshot.get("snapshot_sha256"),
                "prompt_version": snapshot.get("prompt_version"),
                "model_id": snapshot.get("model_settings", {}).get("model_id"),
                "normalized_result_hash": item.normalized_result_hash}

    @r.post("/tests/{tid}/grading-jobs", status_code=201)
    def grading_job(tid, v: dict, s=Depends(db)):
        get(Test, tid, s)
        if v.get("input_stage") in {"selected_reconstruction", "student_visual_answer"}:
            from ..grading_execution import create_execution_job
            roots = [Path(p).resolve() for p in (allowed_roots or [Path.cwd()])]
            for key in ("run_path", "config_path"):
                if not isinstance(v.get(key), str) or not any(
                        Path(v[key]).resolve().is_relative_to(root) for root in roots):
                    raise HTTPException(422, "invalid_input_path")
            try:
                job = create_execution_job(s, tid, v.get("submission_id"), v.get("question_id"),
                    run_path=v["run_path"], config_path=v["config_path"], root=artifact_root,
                    allowed_roots=roots, **visual_options)
                s.add(GradingJobEvent(job_id=job.id, event_type="job_created", new_state="queued"))
                s.commit()
                return {"id": job.id, "state": job.state, "test_id": tid,
                        "snapshot_sha256": job.metadata_json["grading_execution"]["snapshot_sha256"]}
            except (ValueError, OSError, KeyError, TypeError):
                s.rollback()
                raise HTTPException(409, "GRADING_EXECUTION_NOT_READY")
        ready = DomainService(s, artifact_root=artifact_root).readiness(tid)
        if not ready["ready"]:
            raise HTTPException(409, {"error": {"code": "GRADING_NOT_READY", "message": "test is not ready", "details": ready}})
        rubric = s.scalar(select(RubricVersion).where(RubricVersion.test_id == tid, RubricVersion.status == "approved"))
        subs = list(s.scalars(select(StudentSubmission).where(StudentSubmission.test_id == tid)))
        required = {"assignment_path", "run_path", "config_path"}
        if not required.issubset(v):
            raise HTTPException(422, "assignment_path, run_path and config_path are required")
        roots = [Path(p).resolve() for p in (allowed_roots or [Path.cwd()])]
        for key in required:
            path = Path(v[key]).resolve()
            if not any(path.is_relative_to(root) for root in roots):
                raise HTTPException(422, "invalid_input_path")
        questions = list(s.scalars(select(TestQuestion).where(TestQuestion.test_id == tid, TestQuestion.is_gradable.is_(True))))
        answers = list(s.scalars(select(ModelAnswer).where(ModelAnswer.test_id == tid, ModelAnswer.is_current)))
        policy = s.scalar(select(GradingPolicy).where(GradingPolicy.test_id == tid, GradingPolicy.is_current))
        try:
            j, manifest = DomainGradingJobAdapter(s, artifact_root=artifact_root).create_legacy_job(
            get(Test, tid, s), rubric, questions, policy, subs, model_answers=answers,
            assignment_path=v["assignment_path"], run_path=v["run_path"], config_path=v["config_path"],
                execution_mode=v.get("execution_mode", "phased_auto"))
        except (ValueError, OSError, KeyError):
            s.rollback()
            raise HTTPException(409, {"error": {"code": "GRADING_INPUT_CONTRACT_MISMATCH", "message": "Assignment question IDs and approved rubric must match the domain snapshot"}})
        s.add(GradingJobEvent(job_id=j.id, event_type="job_created", new_state="queued"))
        s.add(DomainEvent(entity_type="grading_job", entity_id=j.id, event_type="grading_job_created",
                           payload={"test_id": tid, "rubric_version_id": rubric.id}))
        s.commit()
        return {"id": j.id, "state": j.state, "execution_mode": j.execution_mode,
                "test_id": j.test_id, "rubric_version_id": j.rubric_version_id,
                "total_items": j.total_items, "grading_input_manifest": manifest}
    return r
