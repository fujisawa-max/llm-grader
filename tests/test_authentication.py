import tempfile
import unittest
from pathlib import Path
from starlette.requests import Request

from scoring.auth import (ADMIN, TEACHER, SESSION_COOKIE, authorize_domain_path,
                          create_session, hash_password, request_user, verify_password)
from scoring.db import create_session_factory, init_database
from scoring.db.models import User
from scoring.domain import DomainService


def request(path="/api/v1/courses", cookie=None):
    headers = []
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE}={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": headers, "query_string": b""})


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine, self.factory = create_session_factory(f"sqlite:///{Path(self.tmp.name) / 'auth.db'}")
        init_database(self.engine)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scrypt_password_and_revocable_session(self):
        encoded = hash_password("correct horse battery")
        self.assertTrue(verify_password("correct horse battery", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        with self.factory() as s:
            user = User(display_name="Admin", email="admin@example.com", role=ADMIN,
                        password_hash=encoded, is_active=True)
            s.add(user)
            s.flush()
            token = create_session(s, user)
            s.commit()
            self.assertEqual(request_user(request(cookie=token), s).id, user.id)

    def test_teacher_course_scope_uses_session_owner(self):
        with self.factory() as s:
            teacher = User(display_name="Teacher", email="teacher@example.com", role=TEACHER,
                           password_hash=hash_password("teacher-pass"), is_active=True)
            other = User(display_name="Other", email="other@example.com", role=TEACHER,
                         password_hash=hash_password("other-pass"), is_active=True)
            s.add_all([teacher, other])
            s.flush()
            course = DomainService(s).course(teacher.id, name="Owned")
            token = create_session(s, teacher)
            s.commit()
            current = request_user(request(cookie=token), s)
            self.assertEqual(authorize_domain_path(request(f"/api/v1/courses/{course.id}", token), s, current).id, teacher.id)
            other_token = create_session(s, other)
            s.commit()
            with self.assertRaises(Exception):
                authorize_domain_path(request(f"/api/v1/courses/{course.id}", other_token), s,
                                      request_user(request(cookie=other_token), s))

    def test_expired_or_inactive_sessions_are_rejected(self):
        with self.factory() as s:
            user = User(display_name="Teacher", email="expired@example.com", role=TEACHER,
                        password_hash=hash_password("teacher-pass"), is_active=True)
            s.add(user)
            s.flush()
            token = create_session(s, user, ttl_seconds=-1)
            s.commit()
            with self.assertRaises(Exception):
                request_user(request(cookie=token), s)
            user.is_active = False
            token = create_session(s, user)
            s.commit()
            with self.assertRaises(Exception):
                request_user(request(cookie=token), s)


if __name__ == "__main__":
    unittest.main()
