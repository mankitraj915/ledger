from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from app.auth.security import TokenCodec
from tests.helpers import PASSWORD, Api

SECRET = "test-signing-key-that-is-at-least-32-bytes"


def register(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, object]:
    response = client.post(
        "/api/auth/register", json={"email": email, "name": "Ada", "password": password}
    )
    return {"status": response.status_code, "body": response.json()}


class TestRegister:
    def test_returns_token_and_normalised_user(self, client: TestClient) -> None:
        result = register(client, "Ada@Example.COM")
        assert result["status"] == 201
        body = result["body"]
        assert isinstance(body, dict)
        assert body["user"]["email"] == "ada@example.com"
        assert body["token_type"] == "bearer"
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["email"] == "ada@example.com"

    def test_duplicate_email_is_a_conflict_regardless_of_case(self, client: TestClient) -> None:
        register(client, "ada@example.com")
        result = register(client, "ADA@example.com")
        assert result["status"] == 409
        assert result["body"] == {
            "error": {"code": "email_taken", "message": "An account with this email already exists"}
        }

    def test_invalid_email_is_rejected_with_validation_envelope(self, client: TestClient) -> None:
        result = register(client, "not-an-email")
        assert result["status"] == 422
        body = result["body"]
        assert isinstance(body, dict)
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"][0]["loc"] == ["body", "email"]

    def test_short_password_is_rejected(self, client: TestClient) -> None:
        assert register(client, "ada@example.com", password="short")["status"] == 422


class TestLogin:
    def test_correct_password_returns_token(self, client: TestClient, api: Api) -> None:
        member = api.register()
        response = client.post(
            "/api/auth/login", json={"email": member.email.upper(), "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["user"]["id"] == member.id

    def test_wrong_password_and_unknown_email_are_indistinguishable(
        self, client: TestClient, api: Api
    ) -> None:
        member = api.register()
        wrong_password = client.post(
            "/api/auth/login", json={"email": member.email, "password": "wrong password"}
        )
        unknown_email = client.post(
            "/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        )
        for response in (wrong_password, unknown_email):
            assert response.status_code == 401
            assert response.headers["WWW-Authenticate"] == "Bearer"
            assert response.json()["error"]["code"] == "invalid_credentials"
        assert wrong_password.json() == unknown_email.json()


class TestBearerToken:
    def me(self, client: TestClient, token: str) -> tuple[int, str]:
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        return response.status_code, response.json()["error"]["message"]

    def test_missing_token(self, client: TestClient) -> None:
        response = client.get("/api/auth/me")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_garbage_token(self, client: TestClient) -> None:
        assert self.me(client, "not.a.jwt") == (401, "Invalid token")

    def test_expired_token(self, client: TestClient, api: Api) -> None:
        member = api.register()
        codec = TokenCodec(secret=SECRET, ttl=timedelta(minutes=5))
        token = codec.issue(member.id, now=datetime.now(UTC) - timedelta(hours=1))
        assert self.me(client, token) == (401, "Token has expired")

    def test_token_signed_with_another_key(self, client: TestClient, api: Api) -> None:
        member = api.register()
        forged = TokenCodec(secret="another-key-of-at-least-32-bytes!!", ttl=timedelta(hours=1))
        assert self.me(client, forged.issue(member.id)) == (401, "Invalid token")

    def test_unsigned_alg_none_token(self, client: TestClient, api: Api) -> None:
        member = api.register()
        now = datetime.now(UTC)
        token = jwt.encode(
            {"sub": str(member.id), "iat": now, "exp": now + timedelta(hours=1)},
            key=None,
            algorithm="none",
        )
        assert self.me(client, token) == (401, "Invalid token")

    def test_token_for_deleted_user(self, client: TestClient) -> None:
        token = TokenCodec(secret=SECRET, ttl=timedelta(hours=1)).issue(999_999)
        assert self.me(client, token) == (401, "Invalid token")


class TestPlumbing:
    def test_health_checks_the_database(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}

    def test_unknown_api_route_uses_error_envelope(self, client: TestClient) -> None:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_request_id_is_propagated_or_generated(self, client: TestClient) -> None:
        echoed = client.get("/api/health", headers={"X-Request-ID": "trace-123"})
        assert echoed.headers["X-Request-ID"] == "trace-123"
        unsafe = client.get("/api/health", headers={"X-Request-ID": "bad id; with spaces"})
        assert unsafe.headers["X-Request-ID"] != "bad id; with spaces"
        assert len(unsafe.headers["X-Request-ID"]) == 32
