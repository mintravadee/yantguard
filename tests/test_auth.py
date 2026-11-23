import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.gateway import groq_client
from app.governance import users
from app.governance.db import db_path
from app.main import app

client = TestClient(app)
URL = "/api/gateway/request"
BODY = {"provider": "groq", "prompt": "Hello"}


@pytest.fixture(autouse=True)
def require_keys(monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def fake_generate(prompt):
        return {"provider": "groq", "model": "m", "answer": "hi",
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}

    monkeypatch.setattr(groq_client, "generate", fake_generate)


@pytest.fixture
def alice_key():
    users.create_department("Engineering")
    users.create_user("alice", "Engineering")
    users.grant_provider("Engineering", "groq")
    return users.create_api_key("alice")


def log_rows():
    with closing(sqlite3.connect(db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM requests ORDER BY id").fetchall()


def test_missing_key_is_rejected_and_logged():
    r = client.post(URL, json=BODY)
    assert r.status_code == 401
    (row,) = log_rows()
    assert row["status_code"] == 401 and row["provider"] == "groq" and row["user_name"] is None


def test_wrong_key_is_rejected(alice_key):
    r = client.post(URL, json=BODY, headers={"X-API-Key": "yg-not-a-real-key"})
    assert r.status_code == 401


def test_valid_key_works_and_user_is_logged(alice_key):
    r = client.post(URL, json=BODY, headers={"X-API-Key": alice_key})
    assert r.status_code == 200 and r.json()["answer"] == "hi"
    (row,) = log_rows()
    assert row["user_name"] == "alice" and row["success"] == 1 and row["total_tokens"] == 3


def test_key_is_stored_only_as_hash(alice_key):
    with closing(sqlite3.connect(db_path())) as conn:
        dump = " ".join(str(v) for t in ("api_keys", "requests") for row in conn.execute(f"SELECT * FROM {t}") for v in row)
    assert alice_key not in dump
    assert users.hash_key(alice_key) in dump


def test_revoked_key_is_rejected(alice_key):
    assert users.revoke_key(alice_key[:10]) == 1
    assert client.post(URL, json=BODY, headers={"X-API-Key": alice_key}).status_code == 401


def test_disabled_user_is_rejected(alice_key):
    users.set_user_active("alice", False)
    assert client.post(URL, json=BODY, headers={"X-API-Key": alice_key}).status_code == 401
    users.set_user_active("alice", True)
    assert client.post(URL, json=BODY, headers={"X-API-Key": alice_key}).status_code == 200


def test_other_routes_need_no_key():
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200


def test_can_switch_check_off(monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "false")
    assert client.post(URL, json=BODY).status_code == 200


def test_admin_errors_are_clear():
    with pytest.raises(users.GovernanceError, match="Unknown department"):
        users.create_user("bob", "Nope")
    users.create_department("HR")
    with pytest.raises(users.GovernanceError, match="already exists"):
        users.create_department("HR")
    with pytest.raises(users.GovernanceError, match="Unknown user"):
        users.create_api_key("ghost")


def test_list_users_shows_department_and_keys(alice_key):
    (row,) = users.list_users()
    assert row["user"] == "alice" and row["department"] == "Engineering" and row["active_keys"] == 1


def test_docs_get_an_authorize_button():
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["ApiKeyAuth"]["name"] == "X-API-Key"
    assert schema["paths"][URL]["post"]["security"] == [{"ApiKeyAuth": []}]
