"""No model execution: course transactions and immutable source registration."""

import asyncio
import hashlib
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx
import uvicorn
from sqlalchemy import select, func

from scoring.api.app import create_app
from scoring.db import create_session_factory, init_database
from scoring.db.models import Course, CourseOffering, GradingJob, User
from scoring.auth import hash_password


class TeacherPreparationTests(unittest.TestCase):
    def test_teacher_preparation_and_isolation(self):
        asyncio.run(self.exercise())

    async def exercise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine, factory = create_session_factory(f"sqlite:///{root / 'test.db'}")
            init_database(engine)
            with factory() as session:
                session.add_all(
                    [
                        User(
                            display_name=n,
                            email=f"{n}@example.invalid",
                            password_hash=hash_password("TestPassword123!"),
                            role="teacher",
                        )
                        for n in ("teacher", "other")
                    ]
                )
                session.commit()
            with patch.dict(
                os.environ,
                {"LLM_GRADER_ARTIFACT_ROOT": tmp, "LLM_GRADER_ALLOW_HEADER_AUTH": "false"},
            ):
                app = create_app(
                    factory, allowed_roots=[tmp], question_import_root=root / "imports"
                )
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            listener.setblocking(False)
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
            server_thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            server_thread.start()

            def wait_started():
                deadline = time.monotonic() + 10
                while (
                    not server.started and server_thread.is_alive() and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                if not server.started:
                    raise RuntimeError("temporary API server did not start")

            await asyncio.to_thread(wait_started)
            port = listener.getsockname()[1]
            try:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                    login = await client.post(
                        "/api/v1/auth/login",
                        json={"email": "teacher@example.invalid", "password": "TestPassword123!"},
                    )
                    self.assertEqual(login.status_code, 200)
                    owner = login.json()["user"]["id"]
                    bad = await client.post(
                        "/api/v1/courses",
                        json={"name": "bad", "offering": {"academic_year": 2026, "term": "bad"}},
                    )
                    self.assertEqual(bad.status_code, 400)
                    with factory() as s:
                        self.assertEqual(s.scalar(select(func.count()).select_from(Course)), 0)
                    result = await client.post(
                        "/api/v1/courses",
                        json={
                            "name": "AI",
                            "owner_user_id": "forged-owner",
                            "offering": {"academic_year": 2026, "term": "second_semester"},
                        },
                    )
                    self.assertEqual(result.status_code, 201, result.text)
                    c = result.json()
                    self.assertEqual(c["owner_user_id"], owner)
                    offerings = (await client.get(f"/api/v1/courses/{c['id']}/offerings")).json()
                    self.assertEqual(len(offerings), 1)
                    o = offerings[0]
                    updated = await client.patch(
                        f"/api/v1/courses/{c['id']}",
                        json={
                            "name": "AI ML",
                            "offering": {
                                "offering_id": o["id"],
                                "academic_year": 2027,
                                "term": "first_semester",
                            },
                        },
                    )
                    self.assertEqual(updated.status_code, 200)
                    self.assertEqual(updated.json()["name"], "AI ML")
                    with factory() as s:
                        self.assertEqual(s.get(CourseOffering, o["id"]).academic_year, 2027)
                    t = (
                        await client.post(
                            f"/api/v1/offerings/{o['id']}/tests",
                            json={"name": "Demo", "total_points": 100},
                        )
                    ).json()
                    path = f"/api/v1/tests/{t['id']}"
                    pdf = fitz.open()
                    for i in range(2):
                        pdf.new_page().insert_text((50, 50), f"Demo page {i + 1}")
                    data = pdf.tobytes()
                    png = pdf[0].get_pixmap().tobytes("png")
                    pdf.close()
                    headers = {
                        "Content-Type": "application/pdf",
                        "X-Filename": "demo.pdf",
                        "X-Source-Role": "question_sheet",
                    }
                    source = await client.post(
                        path + "/materials/upload", content=data, headers=headers
                    )
                    self.assertEqual(source.status_code, 201, source.text)
                    question = source.json()
                    self.assertEqual(question["page_count"], 2)
                    self.assertEqual(question["sha256"], hashlib.sha256(data).hexdigest())
                    again = (
                        await client.post(path + "/materials/upload", content=data, headers=headers)
                    ).json()
                    self.assertTrue(again["reused"])
                    self.assertEqual(again["id"], question["id"])
                    imported = await client.post(path + "/question-materials", content=data, headers=headers)
                    self.assertEqual(imported.status_code, 201, imported.text)
                    extraction = imported.json()
                    self.assertEqual(extraction["material_id"], question["id"])
                    retry = await client.post(path + "/question-materials", content=data, headers=headers)
                    self.assertEqual(retry.json()["id"], extraction["id"])
                    source_bytes = await client.get(path + f"/materials/{question['id']}/file")
                    self.assertEqual(hashlib.sha256(source_bytes.content).hexdigest(), question["sha256"])
                    headers["X-Source-Role"] = "model_answer_source"
                    model = (
                        await client.post(path + "/materials/upload", content=data, headers=headers)
                    ).json()
                    self.assertNotEqual(question["id"], model["id"])
                    self.assertEqual(model["material_type"], "model_answer_source")
                    for invalid in (b"", b"not a pdf"):
                        self.assertEqual(
                            (
                                await client.post(
                                    path + "/materials/upload", content=invalid, headers=headers
                                )
                            ).status_code,
                            422,
                        )
                    self.assertEqual(
                        (
                            await client.post(
                                path + "/materials/upload",
                                content=png,
                                headers={
                                    "Content-Type": "text/plain",
                                    "X-Filename": "invalid.txt",
                                    "X-Source-Role": "student_answer_source",
                                },
                            )
                        ).status_code,
                        422,
                    )
                    image = (
                        await client.post(
                            path + "/materials/upload",
                            content=png,
                            headers={
                                "Content-Type": "image/png",
                                "X-Filename": "neutral.png",
                                "X-Source-Role": "student_answer_source",
                            },
                        )
                    ).json()
                    submissions = []
                    for i in range(3):
                        payload = {
                            "material_ids": [image["id"]],
                            "student_identifier": f"00{i + 1}",
                            "display_name": f"Demo {i + 1}",
                        }
                        response = await client.post(path + "/submissions", json=payload)
                        self.assertEqual(response.status_code, 201, response.text)
                        sub = response.json()
                        submissions.append(sub)
                        duplicate = (await client.post(path + "/submissions", json=payload)).json()
                        self.assertEqual(duplicate["id"], sub["id"])
                        pages = await client.get(path + f"/submissions/{sub['id']}/answer-pages")
                        self.assertEqual(pages.status_code, 200, pages.text)
                        self.assertEqual(pages.json()["page_count"], 1)
                        image_read = await client.get(
                            path + f"/submissions/{sub['id']}/answer-artifacts/page-001"
                        )
                        self.assertEqual(image_read.content, png)
                    self.assertEqual(
                        (
                            await client.post(
                                path + "/submissions",
                                json={"material_ids": [model["id"]], "student_identifier": "S004"},
                            )
                        ).status_code,
                        422,
                    )
                    pdf_material = (
                        await client.post(
                            path + "/materials/upload",
                            content=data,
                            headers={**headers, "X-Source-Role": "student_answer_source"},
                        )
                    ).json()
                    multi = await client.post(
                        path + "/submissions",
                        json={
                            "material_ids": [image["id"], pdf_material["id"]],
                            "student_identifier": "S005",
                        },
                    )
                    self.assertEqual(multi.status_code, 201, multi.text)
                    self.assertEqual(
                        (
                            await client.get(
                                path + f"/submissions/{multi.json()['id']}/answer-pages"
                            )
                        ).json()["page_count"],
                        3,
                    )
                    await client.post("/api/v1/auth/logout")
                    await client.post(
                        "/api/v1/auth/login",
                        json={"email": "other@example.invalid", "password": "TestPassword123!"},
                    )
                    for url in [
                        f"/courses/{c['id']}",
                        f"/offerings/{o['id']}",
                        f"/tests/{t['id']}",
                        f"/tests/{t['id']}/materials/{question['id']}/file",
                    ]:
                        self.assertEqual((await client.get("/api/v1" + url)).status_code, 403, url)
                    self.assertEqual(
                        (
                            await client.patch(
                                f"/api/v1/courses/{c['id']}", json={"name": "hacked"}
                            )
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        (
                            await client.post(
                                path + "/materials/upload", content=data, headers=headers
                            )
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        (
                            await client.post(path + "/question-materials", content=data, headers=headers)
                        ).status_code,
                        403,
                    )
                    with factory() as session:
                        self.assertEqual(
                            session.scalar(select(func.count()).select_from(GradingJob)), 0
                        )
            finally:
                server.should_exit = True
                await asyncio.to_thread(server_thread.join, 5)
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
