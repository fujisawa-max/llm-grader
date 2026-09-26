"""Batch H.3-G extraction/reconstruction for the remaining real submissions."""

import json
from pathlib import Path

from sqlalchemy import select

from scoring.db import models as m
from scoring.db.database import create_session_factory
from scoring.student_answer_runtime import RuntimeStudentAnswerStages
from scoring.runtime import RuntimeManager, RuntimeProfile

ROOT = Path("/opt/llm-scoring")
ARTIFACTS = ROOT / "artifacts"
MANIFEST = json.loads((ARTIFACTS / "h3d-minus1/import-report.json").read_text())["results"]
CAP = json.loads((ARTIFACTS / "h3e0a/capability.json").read_text())
READY = {("sampleQ1", "s1", "3.1"), ("sampleQ4", "s2", "2.1"), ("sampleQ4", "s2", "2.2")}
OUT = ARTIFACTS / "h3g-batch"


def manager_setup():
    registry = {
        x["name"]: x
        for x in json.loads(Path("/opt/llm-eval/vision-models.json").read_text())["models"]
    }
    names = {
        "ocr": "ricoh-qwen3vl-8b-q8",
        "math_ocr": "unimumer-qwen35-4b-q4km",
        "ornith_reconstruction": "ornith15-35b-q4km",
    }
    profiles = {}
    config = {
        "models": {},
        "generation": {
            "temperature": 0,
            "seed": 42,
            "top_k": 40,
            "top_p": 0.95,
            "min_p": 0.05,
            "repeat_penalty": 1.0,
            "max_output_tokens": 512,
        },
    }
    for role, name in names.items():
        model = registry[name]
        profiles[role] = RuntimeProfile.from_mapping(
            role,
            {
                "runtime_type": "managed",
                "model_id": name,
                "model_path": model["model"],
                "mmproj_path": model["mmproj"],
                "server_binary": model["server"],
                "context_size": model["context"],
                "batch_size": model["batch"],
                "ubatch_size": model["ubatch"],
                "startup_timeout_seconds": 180,
                "stop_timeout_seconds": 10,
                "vision": True,
                "log_path": str(OUT / f"{role}.log"),
                "additional_args": (["--reasoning", "off", "--chat-template-file",
                                     str(ROOT / "config/chat-templates/ricoh-nonthinking.jinja")]
                                    if role == "ocr" else ["--reasoning-budget", "0"]),
            },
        )
        config["models"][role] = {"model_id": name, "request_timeout_seconds": 300}
        if role == "ocr":
            config["models"][role]["generation"] = {"max_output_tokens": 2048}
    return RuntimeManager(profiles), config


def main(database_url="postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader", *, smoke=False):
    from scoring.batch_answers import BatchAnswerProcessor, selected_reconstructions
    OUT.mkdir(parents=True, exist_ok=True)
    manager, config = manager_setup()
    _, factory = create_session_factory(database_url)
    calls = {"ricoh":0,"unimumer":0,"ornith_reconstruction":0,"ornith_grading":0}
    def audit(event):
        if event.get('event') == 'call':
            calls[event['role']] += 1
    stages = RuntimeStudentAnswerStages(manager, config, audit=audit)
    targets = []
    smoke_set = {('sampleQ1','s1','1.1'),('sampleQ4','s1','2.1'),('sampleQ4','s1','3')}
    with factory() as session:
        for r in MANIFEST:
            sample = r['source']['original_filename'].split('_')[0]
            for q in session.scalars(select(m.TestQuestion).where(
                    m.TestQuestion.test_id==r['test_id'],m.TestQuestion.is_gradable.is_(True))):
                key=(sample,r['sample_identity'],q.question_number)
                if key in READY or (smoke and key not in smoke_set):
                    continue
                if selected_reconstructions(session,r['submission_id'],q.id):
                    continue
                targets.append((key,r['submission_id'],q.id))
    report={'targets':[], 'model_calls':calls, 'grading_jobs_created':0}
    for key,sid,qid in targets:
        with factory() as session:
            processor=BatchAnswerProcessor(session,stages,ARTIFACTS,ARTIFACTS/'h2b-verification',CAP)
            try:
                row=processor.process(sid,qid)
                session.commit()
            except Exception as exc:
                session.rollback()
                row={'final':'BLOCKED','blockers':[type(exc).__name__+':'+str(exc)]}
            row.update(sample=key[0],student=key[1],question=key[2],submission=sid,question_id=qid)
            report['targets'].append(row)
            path=OUT/('h3g0f-smoke.json' if smoke else 'report.json')
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
            path.chmod(0o600)
            print(json.dumps({k:row.get(k) for k in ('sample','student','question','final','blockers')},ensure_ascii=False),flush=True)
    return report


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--database-url',default='postgresql+psycopg://postgres:grader@127.0.0.1:55432/grader')
    parser.add_argument('--smoke',action='store_true')
    args=parser.parse_args()
    main(args.database_url,smoke=args.smoke)
