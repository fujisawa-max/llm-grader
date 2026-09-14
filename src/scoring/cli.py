"""CLI for preparing the supplied exam and running local inference."""

import argparse
import csv
import fcntl
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    LocalClient, digest, identifier, load_assignment, parse_response, read_json,
    validate_grade, write_json,
)
from .regions import for_question, process_regions, validate_layout

ROOT = Path(__file__).resolve().parents[2]
OCR_ENGINES = {"ricoh": ("ocr", "ocr"), "unimumer": ("math_ocr", "math_ocr")}


def now():
    return datetime.now(timezone.utc).isoformat()


def prepare(args):
    import pymupdf

    source = Path(args.source).resolve()
    target = Path(args.output).resolve()
    prefix = "basicMathM3SmallExam1"
    names = [f"{prefix}-{suffix}" for suffix in (
        "question.pdf", "modelAnswer.pdf", "answerSheet42.png", "answerSheet43.png")]
    for name in names:
        if not (source / name).is_file():
            raise ValueError(f"入力がありません: {name}")
    expected = read_json(ROOT / "examples/basic-math-small-exam1/source-pdf-hashes.json")
    if any(digest(source / name) != sha for name, sha in expected.items()):
        raise ValueError("PDFが教材テンプレートから変更されています。問題・ルーブリックを更新してください")
    if target.exists():
        raise ValueError(f"既存課題を上書きしません: {target}")
    staging = target.with_name(target.name + ".preparing-" + uuid.uuid4().hex[:8])
    shutil.copytree(ROOT / "examples/basic-math-small-exam1", staging)
    sources = staging / "sources"
    sources.mkdir()
    for name in names[:2]:
        shutil.copy2(source / name, sources / name)
        with pymupdf.open(source / name) as document:
            pages = []
            for index, page in enumerate(document, 1):
                pages.append(page.get_text())
                page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(
                    sources / f"{Path(name).stem}-{index:03}.png")
            (sources / f"{Path(name).stem}.txt").write_text("\n\f\n".join(pages), encoding="utf-8")
    assignment = read_json(staging / "assignment.json")
    for number in (42, 43):
        dest = staging / f"submissions/s{number}/images"
        dest.mkdir(parents=True)
        shutil.copy2(source / f"{prefix}-answerSheet{number}.png", dest / "page-001.png")
        write_json(dest.parent / "submission.json", {
            "schema_version": 1, "submission_id": f"s{number}",
            "pages": [{"page_id": "page-001", "image": "images/page-001.png"}],
            "answers": [{"question_id": q["question_id"], "page_ids": ["page-001"]}
                        for q in assignment["questions"]],
        })
    write_json(sources / "provenance.json", {
        "source_files": {name: digest(source / name) for name in names},
        "prepared_at": now(), "pdf_renderer": f"PyMuPDF {pymupdf.VersionBind}",
        "render_scale": 1.5, "transcription": "PDF本文抽出と画像確認による教材テンプレート",
    })
    load_assignment(staging)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(target)
    print(f"作成: {target}")


def validate(args):
    assignment, questions, submissions = load_assignment(args.assignment)
    unresolved = [q["question_id"] for q in questions
                  if q["rubric_data"].get("aggregation") == "unresolved"]
    print(json.dumps({"assignment_id": assignment["assignment_id"], "questions": len(questions),
                      "submissions": len(submissions), "unresolved_rubrics": unresolved},
                     ensure_ascii=False, indent=2))


def check(args):
    config = read_json(args.config)
    failed = False
    roles = [args.role] if args.role else ["ocr", "math_ocr", "grader"]
    for role in roles:
        try:
            info = LocalClient(config, role).preflight()
            print(f"{role}: OK {info['props']['model_alias']} vision=true")
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"{role}: ERROR {exc}")
            failed = True
    if failed:
        raise ValueError("接続設定またはモデル起動設定を確認してください")


def checkpoint(client, folder, stage, prompt, materials, images, validator,
               parser=parse_response, parser_signature=None):
    folder.mkdir(parents=True, exist_ok=True)
    status_file = folder / f"{stage}.status.json"
    result_file = folder / f"{stage}.json"
    signature = {
        "model": client.settings, "generation": client.generation, "prompt": prompt,
        "materials": materials, "images": [(label, digest(path)) for label, path in images],
    }
    if parser_signature is not None:
        signature["parser_sha256"] = parser_signature
    if status_file.exists():
        previous = read_json(status_file)
        if previous.get("state") == "success":
            if (previous["signature"] != json.loads(json.dumps(signature))
                    or previous["result_sha256"] != digest(result_file)):
                raise ValueError("チェックポイントの入力または結果が変更されています。新runを作成してください")
            return read_json(result_file)
    started = time.monotonic()
    attempt = uuid.uuid4().hex[:12]
    status = {"state": "running", "started_at": now(), "signature": signature, "attempt": attempt}
    write_json(status_file, status)
    try:
        raw = client.chat(prompt, materials, images)
        write_json(folder / f"{stage}.{attempt}.raw.json", raw)
        result = validator(parser(raw))
        write_json(result_file, result)
        status.update(state="success", result_sha256=digest(result_file))
    except Exception as exc:
        status.update(state="failed", error=str(exc))
        raise
    finally:
        status.update(finished_at=now(), duration_seconds=round(time.monotonic() - started, 3))
        write_json(status_file, status)
    return result


def validate_ocr(value, page_id):
    if value.get("page_id") != page_id or not isinstance(value.get("text"), str):
        raise ValueError("OCRページIDまたはtextが不正")
    if not isinstance(value.get("uncertainties"), list):
        raise ValueError("OCR uncertaintiesが不正")
    if not value["text"].strip():
        value["uncertainties"].append({"reason": "空のOCR出力。未記入と断定できません"})
    for key in ("student_id", "name"):
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"OCR {key}は文字列が必要")
        value.setdefault(key, "")
    return value


def identity_for_submission(run, submission):
    """Use OCR identity fields; never infer an identity from a filename."""
    page = submission["pages"][0]["page_id"]
    path = run / "submissions" / submission["submission_id"] / "ocr/ricoh" / f"{page}.json"
    if not path.exists():
        return {"student_id": "要確認", "name": "要確認"}
    value = read_json(path)
    return {"student_id": value.get("student_id", "").strip() or "要確認",
            "name": value.get("name", "").strip() or "要確認"}


def ocr_signature(engine, page, config, prompt):
    role, _ = OCR_ENGINES[engine]
    settings = config["models"][role]
    signature = {
        "model": settings,
        "generation": {**config.get("generation", {}), **settings.get("generation", {})},
        "prompt": prompt, "materials": {"page_id": page["page_id"]},
        "images": [[page["page_id"], digest(page["path"])]],
    }
    if engine == "unimumer":
        signature["parser_sha256"] = digest(ROOT / "src/scoring/math_ocr.py")
    return signature


def load_ocr(folder, page, config, prompt, engine):
    """Require a successful, untampered result from the selected OCR engine."""
    pid = page["page_id"]
    status = read_json(folder / f"{pid}.status.json")
    result = folder / f"{pid}.json"
    if (status.get("state") != "success"
            or status.get("signature") != ocr_signature(engine, page, config, prompt)
            or status.get("result_sha256") != digest(result)):
        raise ValueError(f"{engine}のOCRが失敗・変更済み、または画像・設定が一致しません")
    return validate_ocr(read_json(result), pid)


def reuse_ocr(source_run, target, submission_id, page, config, prompt, engine="ricoh"):
    """Import only a successful OCR with matching inputs and an intact result."""
    pid = page["page_id"]
    source = Path(source_run).resolve() / "submissions" / submission_id / "ocr" / engine
    status = read_json(source / f"{pid}.status.json")
    result_file = source / f"{pid}.json"
    expected = ocr_signature(engine, page, config, prompt)
    if (status.get("state") != "success" or status.get("signature") != expected
            or status.get("result_sha256") != digest(result_file)):
        raise ValueError("再利用元OCRが失敗・変更済み、または画像・OCR設定が一致しません")
    validate_ocr(read_json(result_file), pid)
    target.mkdir(parents=True, exist_ok=True)
    for path in source.glob(f"{pid}.*.raw.json"):
        shutil.copy2(path, target / path.name)
    shutil.copy2(result_file, target / result_file.name)
    status["reused_from"] = str(source)
    write_json(target / f"{pid}.status.json", status)


def validate_reconstruction(value, question_id, page_ids):
    if (value.get("question_id") != question_id or not isinstance(value.get("transcript"), str)
            or type(value.get("needs_review")) is not bool):
        raise ValueError("照合結果のID・transcript・needs_reviewが不正")
    for key in ("evidence", "uncertainties", "changes"):
        if not isinstance(value.get(key), list):
            raise ValueError(f"照合結果の{key}が不正")
        for item in value[key]:
            if item.get("page_id") not in page_ids:
                raise ValueError("照合結果のページ参照が不正")
    if not value["evidence"]:
        raise ValueError("照合結果に画像の根拠がありません")
    if value["uncertainties"] or not value["transcript"].strip():
        value["needs_review"] = True
    return value


def snapshot(args, config):
    run = Path(args.run).resolve()
    source = Path(args.assignment).resolve()
    if run == source or run.is_relative_to(source) or source.is_relative_to(run):
        raise ValueError("runと課題は別ディレクトリにしてください")
    files = {str(p.relative_to(source)): digest(p) for p in source.rglob("*") if p.is_file()}
    prompts = {name: (ROOT / f"prompts/{name}.md").read_text(encoding="utf-8")
               for name in ("ocr", "locate", "math_ocr", "reconstruct", "grade")}
    code = {p.name: digest(p) for p in (ROOT / "src/scoring").glob("*.py")}
    identity = {"files": files, "config": config, "prompts": prompts, "code": code}
    manifest_path = run / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest["identity"] != identity:
            raise ValueError("入力・設定・プロンプト・コードが変更されています。別の--runを指定してください")
        frozen = run / "inputs/assignment"
        frozen_files = {str(p.relative_to(frozen)): digest(p)
                        for p in frozen.rglob("*") if p.is_file()}
        if frozen_files != files:
            raise ValueError("保存した入力が変更されています")
    else:
        run.mkdir(parents=True, exist_ok=False)
        shutil.copytree(source, run / "inputs/assignment")
        write_json(manifest_path, {"created_at": now(), "identity": identity,
                                  "review_policy": "all_results_during_pilot"})
    return run, prompts


def run_exam(args):
    config = read_json(args.config)
    if config.get("max_in_flight_requests", 1) != 1:
        raise ValueError("逐次実行のみ対応")
    if config.get("execution_mode") not in {"resident_serial", "phased_manual"}:
        raise ValueError("未対応のexecution_mode")
    if config.get("execution_mode") == "phased_manual" and args.stage == "all":
        raise ValueError("phased_manualでは--stage ocrと--stage gradeを別々に実行してください")
    _, _, source_submissions = load_assignment(args.assignment)
    if args.submission and args.submission not in {s["submission_id"] for s in source_submissions}:
        raise ValueError("指定された答案IDがありません")
    lock_path = ROOT / "runs/.inference.lock"
    lock_path.parent.mkdir(exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("別の採点ランナーが実行中です") from exc
        run, prompts = snapshot(args, config)
        _, questions, submissions = load_assignment(run / "inputs/assignment")
        selected = getattr(args, "ocr_engine", "both")
        engines = list(OCR_ENGINES) if selected == "both" else [selected]
        if args.stage != "ocr" and selected != "both":
            raise ValueError("--ocr-engineは--stage ocr専用です。採点には両OCRが必要です")
        roles = ([OCR_ENGINES[e][0] for e in engines] if args.stage == "ocr"
                 else ["grader"] if args.stage == "grade" else ["ocr", "math_ocr", "grader"])
        clients = {}
        for role in roles:
            clients[role] = LocalClient(config, role)
            info = clients[role].preflight()
            write_json(run / f"server-{role}.json", info)
        for sub in submissions:
            sid = sub["submission_id"]
            if args.submission and args.submission != sid:
                continue
            folder = run / "submissions" / sid
            ocr = {page["page_id"]: {} for page in sub["pages"]}
            for page in sub["pages"]:
                pid = page["page_id"]
                source_run = getattr(args, "reuse_ocr_from", None)
                ricoh_folder = folder / "ocr/ricoh"
                source_status = (Path(source_run) / "submissions" / sid / "ocr/ricoh"
                                 / f"{pid}.status.json") if source_run else None
                if (source_status and source_status.is_file()
                        and not (ricoh_folder / f"{pid}.status.json").exists()):
                    reuse_ocr(source_run, ricoh_folder, sid, page, config, prompts["ocr"])
                recognize = args.stage != "grade" and "ricoh" in engines
                if recognize:
                    print(f"{sid}/{pid}: ricoh OCR", flush=True)
                    ricoh = checkpoint(clients["ocr"], ricoh_folder, pid, prompts["ocr"],
                                       {"page_id": pid}, [(pid, page["path"])],
                                       lambda v, p=pid: validate_ocr(v, p),
                                       parser=lambda raw: parse_response(raw, allow_reasoning=True))
                else:
                    ricoh = load_ocr(ricoh_folder, page, config, prompts["ocr"], "ricoh")
                page_questions = [q for q in questions if any(
                    a["question_id"] == q["question_id"] and pid in a["page_ids"]
                    for a in sub["answers"])]
                if not page_questions:
                    raise ValueError(f"設問と対応しないページ: {pid}")
                materials = {"task": "locate", "page_id": pid, "ricoh": ricoh,
                             "questions": [{"question_id": q["question_id"],
                                            "label": q.get("label", q["question_id"])}
                                           for q in page_questions]}
                qids = [q["question_id"] for q in page_questions]
                layout_hash = digest(ROOT / "src/scoring/regions.py")
                if recognize:
                    print(f"{sid}/{pid}: Ricoh 領域分割", flush=True)
                    layout = checkpoint(clients["ocr"], ricoh_folder, f"{pid}.layout",
                                        prompts["locate"], materials, [(pid, page["path"])],
                                        lambda v, p=pid, qs=qids: validate_layout(v, p, qs),
                                        parser=lambda raw: parse_response(raw, allow_reasoning=True),
                                        parser_signature=layout_hash)
                else:
                    settings = config["models"]["ocr"]
                    expected = {"model": settings,
                        "generation": {**config.get("generation", {}), **settings.get("generation", {})},
                        "prompt": prompts["locate"], "materials": materials,
                        "images": [[pid, digest(page["path"])]], "parser_sha256": layout_hash}
                    status = read_json(ricoh_folder / f"{pid}.layout.status.json")
                    path = ricoh_folder / f"{pid}.layout.json"
                    if (status.get("state") != "success" or status.get("signature") != expected
                            or status.get("result_sha256") != digest(path)):
                        raise ValueError("成功済みのRicoh領域分割が必要です。先に--ocr-engine ricohを実行してください")
                    layout = validate_layout(read_json(path), pid, qids)
                ocr[pid]["ricoh"] = ricoh
                if args.stage == "ocr" and selected == "ricoh":
                    continue
                ocr[pid]["unimumer"] = process_regions(
                    page, ricoh, layout, folder / "ocr/unimumer", config,
                    prompts["math_ocr"], checkpoint, clients.get("math_ocr"))
            if args.stage == "ocr":
                continue
            for q in questions:
                qid = q["question_id"]
                pids = next(a["page_ids"] for a in sub["answers"] if a["question_id"] == qid)
                page_paths = {p["page_id"]: p["path"] for p in sub["pages"]}
                images = [(pid, page_paths[pid]) for pid in pids]
                evidence = {pid: {"ricoh": ocr[pid]["ricoh"],
                                  "unimumer": for_question(ocr[pid]["unimumer"], qid)} for pid in pids}
                qfolder = folder / "questions" / qid
                print(f"{sid}/{qid}: Ornith照合", flush=True)
                reconstruction = checkpoint(
                    clients["grader"], qfolder, "reconstruction", prompts["reconstruct"],
                    {"question_id": qid, "target": q.get("label", qid), "ocr": evidence}, images,
                    lambda v, qi=qid, ps=pids: validate_reconstruction(v, qi, ps))
                print(f"{sid}/{qid}: Ornith採点", flush=True)
                grade = checkpoint(
                    clients["grader"], qfolder, "grading", prompts["grade"],
                    {"question_id": qid, "question": q["text"], "rubric": q["rubric_data"],
                     "reference_answer": q["reference_text"], "reconstruction": reconstruction,
                     "ocr": evidence}, images + [("問題図", p) for p in q["asset_paths"]],
                    lambda v, r=q["rubric_data"], ps=pids: validate_grade(v, r, ps))
                reasons = list(grade["review_reasons"])
                if reconstruction["needs_review"] or any(
                    o["uncertainties"] for by_engine in evidence.values() for o in by_engine.values()
                ):
                    reasons.append("OCRまたは読み取り照合に不確実箇所あり")
                reasons.extend(q["rubric_data"].get("review_notes", []))
                write_json(qfolder / "review.json", {"needs_review": True, "final_score": None,
                           "reasons": list(dict.fromkeys(reasons + ["初期試行のため全件教員確認"]))})
        summarize(run, questions, submissions)
        print(f"保存先: {run}")


def summarize(run, questions, submissions):
    totals = {}
    rows = []
    for sub in submissions:
        scores = []
        for q in questions:
            path = run / f"submissions/{sub['submission_id']}/questions/{q['question_id']}/grading.json"
            score = read_json(path)["score"] if path.exists() else None
            scores.append(score)
            rows.append({"submission_id": sub["submission_id"], **identity_for_submission(run, sub),
                         "question_id": q["question_id"],
                         "provisional_score": score, "max_score": q["rubric_data"]["max_score"],
                         "final_score": None, "status": "needs_review" if path.exists() else "pending"})
        totals[sub["submission_id"]] = None if None in scores else sum(scores)
    temporary = run / "summary.csv.tmp"
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(run / "summary.csv")
    write_json(run / "totals.json", {"provisional_scores": totals, "final_scores": {},
                                     "needs_review": True})


def export_reports(args):
    """Create an editable roster and red review PDFs from a completed run."""
    import pymupdf

    run = Path(args.run).resolve()
    assignment, questions, submissions = load_assignment(run / "inputs/assignment")
    report_dir = run / "reports"
    report_dir.mkdir(exist_ok=True)
    fields = ["submission_id", "student_id", "name"] + [q["question_id"] for q in questions]
    fields += ["total_score", "notes"]
    roster = []
    for sub in submissions:
        sid = sub["submission_id"]
        identity = identity_for_submission(run, sub)
        row = {"submission_id": sid, **identity}
        scores = []
        notes = []
        for q in questions:
            path = run / f"submissions/{sid}/questions/{q['question_id']}/grading.json"
            if not path.exists():
                row[q["question_id"]] = ""
                notes.append(f"{q['question_id']}: 未処理")
                continue
            grade = read_json(path)
            score = grade.get("score")
            row[q["question_id"]] = "" if score is None else score
            scores.append(score)
            review = run / f"submissions/{sid}/questions/{q['question_id']}/review.json"
            reasons = list(grade.get("review_reasons", []))
            if review.exists():
                reasons.extend(read_json(review).get("reasons", []))
            # A score below the maximum must remain visible in the roster even
            # when the grader did not emit an explicit review reason.
            if score is not None and score < q["rubric_data"]["max_score"]:
                reasons.append("減点: 採点基準の満点条件を満たしていない")
            reasons = list(dict.fromkeys(r for r in reasons if r))
            if reasons:
                notes.append(f"{q['question_id']}: " + "／".join(reasons))
        if row["student_id"] == "要確認" or row["name"] == "要確認":
            notes.append("学籍番号・氏名: OCR結果に記録がないため要確認（再OCRで取得）")
        row["total_score"] = "" if len(scores) != len(questions) or None in scores else sum(scores)
        row["notes"] = "；".join(notes) or ""
        roster.append(row)
    with (report_dir / "roster.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(roster)
    lines = ["答案採点一覧", "", "\t".join(fields)]
    lines.extend("\t".join(str(row.get(k, "")) for k in fields) for row in roster)
    (report_dir / "roster.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    annotated = report_dir / "annotated"
    annotated.mkdir(exist_ok=True)
    for sub, row in zip(submissions, roster):
        source = sub["pages"][0]["path"]
        document = pymupdf.open()
        pixmap = pymupdf.Pixmap(str(source))
        page = document.new_page(width=pixmap.width, height=pixmap.height)
        page.insert_image(page.rect, filename=str(source))
        # A compact editable summary is kept at the upper right.
        summary = f"学籍番号: {row['student_id']}\n氏名: {row['name']}\n合計: {row['total_score'] or '要確認'}"
        for q in questions:
            score = row.get(q["question_id"], "")
            grade_path = run / f"submissions/{sub['submission_id']}/questions/{q['question_id']}/grading.json"
            reason = "未処理"
            if grade_path.exists():
                grade = read_json(grade_path)
                reasons = list(grade.get("review_reasons", []))
                reasons.extend(c.get("reason", "") for c in grade.get("criteria", [])
                               if c.get("score") is not None
                               and c.get("score") < c.get("max_score", 0))
                if score != "" and score is not None and score < q["rubric_data"]["max_score"]:
                    reasons.append("減点: 採点基準の満点条件を満たしていない")
                reason = "／".join(dict.fromkeys(r for r in reasons if r)) or "採点根拠はgrading.jsonを参照"
            if score == "" or score is None:
                mark = "?"
            elif score == q["rubric_data"]["max_score"]:
                mark = "○"
            elif score == 0:
                mark = "×"
            else:
                mark = "△"
            summary += f"\n{q.get('label', q['question_id'])}: {mark} {score if score != '' else '要確認'}/{q['rubric_data']['max_score']}"

            # Locate the question's answer area from Ricoh's layout.  Bboxes
            # are normalized to 0..1000; expand the box so the annotation is
            # readable while remaining next to the student's work.
            layout_path = run / f"submissions/{sub['submission_id']}/ocr/ricoh/{sub['pages'][0]['page_id']}.layout.json"
            regions = read_json(layout_path).get("regions", []) if layout_path.exists() else []
            boxes = [r["bbox"] for r in regions if r.get("question_id") == q["question_id"] and len(r.get("bbox", [])) == 4]
            if boxes:
                x0 = min(b[0] for b in boxes) / 1000 * page.rect.width
                y1 = max(b[3] for b in boxes) / 1000 * page.rect.height
            else:
                index = questions.index(q)
                x0 = 40
                y1 = page.rect.height * (0.18 + index * 0.18)
            # Put a large comment box just below the detected area, bounded
            # by the page.  The generous dimensions prevent long Japanese
            # reasons from being clipped at 24pt.
            box_width, box_height = 2200, 850
            left = min(max(10, x0), page.rect.width - box_width - 10)
            top = min(max(10, y1 + 10), page.rect.height - box_height - 10)
            box = pymupdf.Rect(left, top, min(page.rect.width - 10, left + box_width),
                               min(page.rect.height - 10, top + box_height))
            if reason != "採点根拠はgrading.jsonを参照" or score in ("", None) or score < q["rubric_data"]["max_score"]:
                annot = page.add_freetext_annot(
                    box, f"{q.get('label', q['question_id'])}: {mark} {score if score != '' else '要確認'}/{q['rubric_data']['max_score']}\n{reason}",
                    fontsize=48, fontname="japan", text_color=(1, 0, 0),
                    fill_color=(1, 1, 1), align=0, opacity=0.30)
                annot.update()
        summary_box = pymupdf.Rect(page.rect.width * 0.58, 20, page.rect.width - 20, page.rect.height * 0.28)
        annot = page.add_freetext_annot(summary_box, summary, fontsize=52, fontname="japan",
                                        text_color=(1, 0, 0), fill_color=(1, 1, 1), align=0, opacity=0.30)
        annot.update()
        document.save(annotated / f"{sub['submission_id']}.pdf")
        document.close()
    print(f"一覧: {report_dir / 'roster.csv'}")
    print(f"PDF: {annotated}")


def compare(args):
    expected = read_json(args.expected)["expected_scores"]
    actual = read_json(Path(args.run) / "totals.json")["provisional_scores"]
    rows = [{"submission_id": sid, "expected": score, "actual": actual.get(sid),
             "difference": None if actual.get(sid) is None else actual[sid] - score}
            for sid, score in expected.items()]
    write_json(Path(args.run) / "comparison.json", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Ricoh + Uni-MuMER → Ornith Q8 ローカル答案採点")
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare-sample")
    prep.add_argument("--source", default="testData/BasicMathSmallExam1")
    prep.add_argument("--output", default="data/assignments/BasicMathSmallExam1")
    prep.set_defaults(func=prepare)
    val = commands.add_parser("validate")
    val.add_argument("--assignment", required=True)
    val.set_defaults(func=validate)
    chk = commands.add_parser("check")
    chk.add_argument("--config", default="config/local.json")
    chk.add_argument("--role", choices=["ocr", "math_ocr", "grader"])
    chk.set_defaults(func=check)
    run = commands.add_parser("run")
    run.add_argument("--assignment", required=True)
    run.add_argument("--config", default="config/local.json")
    run.add_argument("--run", required=True)
    run.add_argument("--stage", choices=["all", "ocr", "grade"], default="all")
    run.add_argument("--submission")
    run.add_argument("--ocr-engine", choices=["both", "ricoh", "unimumer"], default="both",
                     help="--stage ocrで実行する認識器。既定は両方を逐次実行")
    run.add_argument("--reuse-ocr-from", help="画像・OCR設定が一致する成功済みOCRを別runから再利用")
    run.set_defaults(func=run_exam)
    comp = commands.add_parser("compare")
    comp.add_argument("--run", required=True)
    comp.add_argument("--expected", required=True)
    comp.set_defaults(func=compare)
    report = commands.add_parser("export-reports")
    report.add_argument("--run", required=True)
    report.set_defaults(func=export_reports)
    args = parser.parse_args()
    try:
        if getattr(args, "submission", None):
            identifier(args.submission)
        args.func(args)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
