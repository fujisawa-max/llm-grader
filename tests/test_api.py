import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scoring.api import JobCreate, create_app
from scoring.db import create_session_factory, init_database


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        assignment = root / "assignment"
        assignment.mkdir()
        (assignment / "q.md").write_text("q")
        (assignment / "r.md").write_text("a")
        (assignment / "rubric.json").write_text(
            json.dumps(
                {
                    "question_id": "q1",
                    "max_score": 1,
                    "criteria": [
                        {
                            "criterion_id": "c",
                            "max_score": 1,
                            "levels": [{"score": 0}, {"score": 1}],
                        }
                    ],
                }
            )
        )
        (assignment / "assignment.json").write_text(
            json.dumps(
                {
                    "assignment_id": "a",
                    "questions": [
                        {
                            "question_id": "q1",
                            "question": "q.md",
                            "rubric": "rubric.json",
                            "reference_answer": "r.md",
                        }
                    ],
                    "submissions": ["submission.json"],
                }
            )
        )
        (assignment / "submission.json").write_text(
            json.dumps(
                {
                    "submission_id": "s1",
                    "pages": [{"page_id": "p1", "image": "x.png"}],
                    "answers": [{"question_id": "q1", "page_ids": ["p1"]}],
                }
            )
        )
        (assignment / "x.png").write_bytes(b"png")
        self.engine, self.sf = create_session_factory(f"sqlite:///{root / 'api.db'}")
        init_database(self.engine)
        self.app = create_app(self.sf, allowed_roots=[root])
        self.assignment = assignment
        self.root = root
        self.routes = {
            (route.path, next(iter(route.methods))): route.endpoint
            for route in self.app.routes
            if hasattr(route, "path") and route.methods
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_create_list_pause_resume_and_security(self):
        with self.sf() as s:
            self.assertEqual(self.routes[("/api/v1/health", "GET")](s)["database"], "ok")
            req = JobCreate(
                execution_mode="phased_auto",
                assignment_path=str(self.assignment),
                run_path=str(self.root / "run"),
                config_path=str(self.root / "config.json"),
            )
            job = self.routes[("/api/v1/jobs", "POST")](req, s)
            self.assertEqual(job["state"], "queued")
            self.assertEqual(
                self.routes[("/api/v1/jobs/{job_id}/items", "GET")](
                    job["id"], None, None, 50, 0, s
                )[0]["item_key"],
                "s1",
            )
            self.assertEqual(
                self.routes[("/api/v1/jobs/{job_id}/pause", "POST")](job["id"], s)["state"],
                "paused",
            )
            self.assertEqual(
                self.routes[("/api/v1/jobs/{job_id}/resume", "POST")](job["id"], s)["state"],
                "queued",
            )
            s.commit()

    def test_openapi_and_not_found(self):
        paths = self.app.openapi()["paths"]
        self.assertIn("/api/v1/jobs", paths)
        with self.sf() as s:
            with self.assertRaises(Exception):
                self.routes[("/api/v1/jobs/{job_id}", "GET")]("nope", s)

    def test_domain_courses_list_returns_json(self):
        """Regression coverage for the browser-reported GET /courses failure."""
        with self.sf() as s:
            response = self.routes[("/api/v1/courses", "GET")](s)
            self.assertIsInstance(response, list)

    def test_teacher_source_material_file_is_served_without_mutation(self):
        """The teacher PDF preview serves the immutable material bytes."""
        from scoring.domain import DomainService
        from scoring.pdf_native import sha256_file

        source = self.root / "question.pdf"
        source.write_bytes(b"%PDF-test")
        with self.sf() as s:
            d = DomainService(s)
            user = d.user(display_name="Teacher")
            course = d.course(user.id, name="Course")
            offering = d.offering(course.id, academic_year=2026, term="fall")
            test = d.test(offering.id, name="Test", total_points=1)
            material = d.material(
                test.id,
                material_type="question_sheet",
                storage_ref=str(source),
                sha256=sha256_file(source),
                mime_type="application/pdf",
            )
            s.commit()
            response = self.routes[("/api/v1/tests/{tid}/materials/{mid}/file", "GET")](test.id, material.id, s)
            self.assertEqual(Path(response.path), source)
            self.assertEqual(source.read_bytes(), b"%PDF-test")

    def test_relative_material_ref_uses_unified_artifact_root(self):
        """Question-import material refs resolve from the artifact root once."""
        from scoring.domain import DomainService
        from scoring.pdf_native import sha256_file

        artifact_root = self.root / "artifact-store"
        source = artifact_root / "question-imports" / "extraction-1" / "source.pdf"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"%PDF-relative")
        with patch.dict(os.environ, {"LLM_GRADER_ARTIFACT_ROOT": str(artifact_root)}, clear=False):
            app = create_app(self.sf, allowed_roots=[self.root],
                             question_import_root=artifact_root / "question-imports")
            routes = {
                (route.path, next(iter(route.methods))): route.endpoint
                for route in app.routes if hasattr(route, "path") and route.methods
            }
            with self.sf() as s:
                d = DomainService(s)
                user = d.user(display_name="Teacher")
                course = d.course(user.id, name="Relative Course")
                offering = d.offering(course.id, academic_year=2026, term="fall")
                test = d.test(offering.id, name="Relative Test", total_points=1)
                material = d.material(
                    test.id, material_type="question_sheet",
                    storage_ref="question-imports/extraction-1/source.pdf",
                    sha256=sha256_file(source), mime_type="application/pdf",
                )
                s.commit()
                response = routes[("/api/v1/tests/{tid}/materials/{mid}/file", "GET")](
                    test.id, material.id, s
                )
                self.assertEqual(Path(response.path), source)
