"""Small auth helper for HTTP tests running against the production auth middleware."""

from scoring.auth import hash_password


PASSWORD = "disposable-http-test-password"


def authenticate_fixture(client, session, user):
    if not user.email:
        user.email = f"{user.id}@fixture.invalid"
    if not user.password_hash:
        user.password_hash = hash_password(PASSWORD)
    session.commit()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client
