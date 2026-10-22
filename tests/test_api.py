import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import content, db, main
from tests.conftest import ADMIN_URL, reader_url


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_limiters():
    for b in (main._hits, main._contact_hits, main._login_hits):
        b.clear()


# ------------------------------ public API ------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_profile_and_projects(client):
    assert client.get("/api/profile").json()["name"] == content.PROFILE["name"]
    projects = client.get("/api/projects").json()
    assert len(projects) == len(content.PROJECTS)
    assert isinstance(projects[0]["stack"], list) and isinstance(projects[0]["highlights"], list)


def test_project_filters(client):
    first = content.PROJECTS[0]
    tech = first["stack"].split(",")[0].strip().lower()
    by_stack = client.get("/api/projects", params={"stack": tech}).json()
    assert first["slug"] in [p["slug"] for p in by_stack]
    by_status = client.get("/api/projects", params={"status": first["status"]}).json()
    assert {p["status"] for p in by_status} == {first["status"]}


def test_project_404(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404 and "ls projects" in r.json()["detail"]


def test_skills_filter(client):
    rows = client.get("/api/skills", params={"category": "language"}).json()
    assert rows and {r["category"] for r in rows} == {"language"}


def test_contact_validation_and_limit(client):
    bad = client.post("/api/contact", json={"name": "A", "email": "nope", "message": "hello there"})
    assert bad.status_code == 422
    ok = {"name": "Ada", "email": "ada@example.com", "message": "Hello, let's talk."}
    for _ in range(3):
        assert client.post("/api/contact", json=ok).status_code == 201
    assert client.post("/api/contact", json=ok).status_code == 429


# ------------------------------ read-only SQL ------------------------------

def test_query_select_ok(client):
    r = client.post("/api/query", json={"sql": "SELECT name, level FROM skills WHERE level = 5 ORDER BY name"})
    assert r.status_code == 200
    assert r.json()["columns"] == ["name", "level"] and r.json()["row_count"] >= 1


def test_query_can_read_jsonb_and_functions(client):
    r = client.post("/api/query", json={"sql": "SELECT slug, highlights FROM projects LIMIT 1"})
    assert r.status_code == 200 and isinstance(r.json()["rows"][0][1], list)


@pytest.mark.parametrize("sql", [
    "DROP TABLE projects",
    "SELECT * FROM projects; DROP TABLE skills",
    "SELECT * FROM contact_messages",
    "SELECT * FROM pg_user",
    "SELECT * FROM information_schema.tables",
    "SELECT set_config('role', 'postgres', true)",
    "SELECT pg_read_file('/etc/passwd')",
    "INSERT INTO skills VALUES ('x','y',1)",
    "WITH x AS (SELECT 1) DELETE FROM skills",
    "SELECT * FROM projects, contact_messages",
    "SELECT (SELECT message FROM contact_messages LIMIT 1)",
])
def test_query_blocks_unsafe(client, sql):
    assert client.post("/api/query", json={"sql": sql}).status_code == 400


def test_query_timeout(client):
    r = client.post("/api/query", json={"sql": "SELECT count(*) FROM generate_series(1, 2000000000)"})
    assert r.status_code == 400 and "too long" in r.json()["detail"]


def test_reader_role_is_least_privilege_at_the_database_level():
    """Even if the API checks were bypassed, the role itself cannot do harm."""
    with psycopg.connect(reader_url(ADMIN_URL), autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM skills").fetchone()[0] > 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM contact_messages")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("INSERT INTO skills VALUES ('x','y',1)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM experience")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DROP TABLE skills")


def test_query_disabled_without_reader_pool(client, monkeypatch):
    monkeypatch.setattr(db, "_ro_pool", None)
    assert client.post("/api/query", json={"sql": "SELECT 1"}).status_code == 503


# ------------------------------ limits, headers, proxy handling ------------------------------

def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 5)
    codes = [client.get("/api/profile").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_rate_limit_cannot_be_bypassed_by_spoofed_forwarded_for(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 5)
    codes = [client.get("/api/profile", headers={"X-Forwarded-For": f"10.0.0.{i}, 9.9.9.9"}).status_code for i in range(7)]
    assert codes[5] == 429  # the trusted (rightmost) entry is what counts


def test_body_size_limit(client):
    big = {"name": "A", "email": "a@b.co", "message": "x" * 25_000}
    assert client.post("/api/contact", json=big).status_code == 413


def test_security_headers(client):
    h = client.get("/").headers
    assert "script-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert "strict-origin" in h["referrer-policy"]
    assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]
    assert client.get("/api/profile").headers["cache-control"] == "no-store"
    assert "strict-transport-security" in client.get("/", headers={"X-Forwarded-Proto": "https"}).headers


def test_status_reports_traffic(client):
    client.get("/api/profile")
    s = client.get("/api/status").json()
    assert s["requests"] >= 1 and "p95" in s["latency_ms"]


# ------------------------------ admin ------------------------------
PASSWORD = "correct-horse-battery"
NEW_JOB = {"company": "Acme", "role": "Engineer", "start": "2024-01", "end": None, "summary": "Built things."}


def login(client, pw=PASSWORD):
    return client.post("/api/admin/login", json={"password": pw})


def auth(client):
    return {"Authorization": "Bearer " + login(client).json()["token"]}


def test_login_wrong_and_right(client):
    assert login(client, "nope").status_code == 401
    r = login(client)
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_login_is_rate_limited(client):
    codes = [login(client, "bad").status_code for _ in range(main.LOGIN_LIMIT + 1)]
    assert codes[-1] == 429


def test_login_disabled_without_or_with_weak_password(client, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert login(client, "short").status_code == 503
    monkeypatch.delenv("ADMIN_PASSWORD")
    assert login(client).status_code == 503


def test_add_and_delete_require_auth(client):
    assert client.post("/api/experience", json=NEW_JOB).status_code == 401
    assert client.delete("/api/experience/1").status_code == 401
    assert client.post("/api/experience", json=NEW_JOB, headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_and_tampered_tokens_rejected(client):
    expired = main.make_token(exp=time.time() - 10)
    assert client.post("/api/experience", json=NEW_JOB, headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    good = main.make_token()
    tampered = good[:-2] + ("AA" if good[-2:] != "AA" else "BB")
    assert client.post("/api/experience", json=NEW_JOB, headers={"Authorization": f"Bearer {tampered}"}).status_code == 401


def test_add_then_delete_experience(client):
    h = auth(client)
    created = client.post("/api/experience", json=NEW_JOB, headers=h)
    assert created.status_code == 201
    new_id = created.json()["id"]
    assert any(e["id"] == new_id for e in client.get("/api/experience").json())
    assert client.delete(f"/api/experience/{new_id}", headers=h).status_code == 204
    assert not any(e["id"] == new_id for e in client.get("/api/experience").json())
    assert client.delete(f"/api/experience/{new_id}", headers=h).status_code == 404


def test_experience_validation(client):
    h = auth(client)
    assert client.post("/api/experience", json={**NEW_JOB, "start": "2024-13"}, headers=h).status_code == 422
    assert client.post("/api/experience", json={**NEW_JOB, "start": "2024-05", "end": "2023-01"}, headers=h).status_code == 422
    assert client.post("/api/experience", json={**NEW_JOB, "company": ""}, headers=h).status_code == 422