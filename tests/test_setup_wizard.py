import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from scoring.api.app import create_app
from scoring.auth import hash_password
from scoring.db import create_session_factory, init_database
from scoring.db.models import User


class SetupWizardTests(unittest.TestCase):
    def make(self):
        root = Path(tempfile.mkdtemp())
        engine, factory = create_session_factory(f"sqlite:///{root / 'setup.db'}")
        init_database(engine)
        return engine, factory

    def test_first_admin_is_created_and_setup_closes(self):
        engine, factory = self.make()
        with TestClient(create_app(factory, allowed_roots=["/tmp"])) as client:
            self.assertEqual(client.get("/api/v1/setup/status").json(), {"setup_required": True})
            response = client.post("/api/v1/setup/initialize", json={
                "display_name": "Initial Admin", "email": "initial@example.com", "password": "InitialPass123!", "role": "teacher"})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["user"]["role"], "admin")
            self.assertNotIn("InitialPass123!", response.text)
            self.assertEqual(client.get("/api/v1/setup/status").json(), {"setup_required": False})
            self.assertEqual(client.post("/api/v1/setup/initialize", json={
                "display_name": "Other", "email": "other@example.com", "password": "OtherPass123!"}).status_code, 409)
        engine.dispose()

    def test_existing_teacher_does_not_get_promoted(self):
        engine, factory = self.make()
        with factory() as session:
            session.add(User(display_name="Teacher", email="teacher@example.com", role="teacher", password_hash=hash_password("TeacherPass123!")))
            session.commit()
        with TestClient(create_app(factory, allowed_roots=["/tmp"])) as client:
            self.assertTrue(client.get("/api/v1/setup/status").json()["setup_required"])
            self.assertEqual(client.post("/api/v1/setup/initialize", json={"display_name":"Admin", "email":"admin@example.com", "password":"AdminPass123!"}).status_code, 201)
        with factory() as session:
            self.assertEqual(session.query(User).filter_by(role="admin").count(), 1)
            self.assertEqual(session.query(User).filter_by(email="teacher@example.com").one().role, "teacher")
        engine.dispose()

    def test_invalid_and_duplicate_input(self):
        engine, factory = self.make()
        with factory() as session:
            session.add(User(display_name="Legacy", email="same@example.com", role="teacher"))
            session.commit()
        with TestClient(create_app(factory, allowed_roots=["/tmp"])) as client:
            self.assertEqual(client.post("/api/v1/setup/initialize", json={"display_name":"Admin", "email":"same@example.com", "password":"short"}).status_code, 422)
            self.assertEqual(client.post("/api/v1/setup/initialize", json={"display_name":"Admin", "email":"same@example.com", "password":"LongPass123!"}).status_code, 409)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
