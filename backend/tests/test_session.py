import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import HEADER, require_session

PAGE = {"Origin": "http://localhost:5173"}


@pytest.fixture
def client():
    # Enforce the key here, unlike in the other API tests.
    app.dependency_overrides.pop(require_session, None)
    return TestClient(app, base_url="http://localhost:8000")


def token(client):
    response = client.get("/api/session", headers=PAGE)
    assert response.status_code == 200
    return response.json()["token"]


def test_requests_without_the_key_are_refused(client):
    assert client.get("/api/runs").status_code == 401
    assert client.post("/api/undo", json={"journal_id": "x"}).status_code == 401
    assert client.post("/api/execute", json={"path": ".", "operations": []}).status_code == 401
    assert client.get("/api/runs", headers={HEADER: "guess"}).status_code == 401


def test_the_page_gets_a_key_that_works(client):
    key = token(client)

    assert len(key) >= 40
    assert client.get("/api/runs", headers={HEADER: key}).status_code == 200


def test_other_sites_and_programs_get_no_key(client):
    assert client.get("/api/session", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/session").status_code == 403  # No Origin: not a browser page.


def test_only_answers_requests_addressed_to_localhost(client):
    # DNS rebinding: a site whose name now points at 127.0.0.1.
    rebound = TestClient(app, base_url="http://evil.example:8000")
    assert rebound.get("/api/session", headers=PAGE).status_code == 403

    key = token(client)
    assert rebound.get("/api/runs", headers={HEADER: key}).status_code == 403
    for host in ("127.0.0.1:8000", "[::1]:8000", "localhost"):
        response = client.get("/api/runs", headers={HEADER: key, "Host": host})
        assert response.status_code == 200, host


def test_thumbnails_take_the_key_in_the_url(client):
    key = token(client)

    assert client.get("/api/thumbnail", params={"root": "x", "path": "y"}).status_code == 401
    # Past the key check; refused for not being a scanned folder.
    response = client.get("/api/thumbnail", params={"root": "x", "path": "y", "token": key})
    assert response.status_code == 403
    assert "key" not in response.json()["detail"]
    # Only thumbnails accept it that way.
    assert client.get("/api/runs", params={"token": key}).status_code == 401


def test_health_needs_no_key(client):
    assert client.get("/api/health").status_code == 200


def test_cors_lets_only_the_page_send_the_key_header(client):
    def preflight(origin):
        return client.options("/api/runs", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": HEADER,
        })

    allowed = preflight("http://localhost:5173")
    assert allowed.status_code == 200
    assert HEADER.lower() in allowed.headers["access-control-allow-headers"].lower()
    assert preflight("https://evil.example").status_code == 400
