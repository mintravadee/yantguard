import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.gateway import gemini_client, groq_client
from app.governance import users
from app.governance.db import db_path
from app.main import app

client = TestClient(app)
URL = "/api/gateway/request"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "true")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    def fake(name):
        async def generate(prompt):
            return {"provider": name, "model": "m", "answer": "hi",
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        return generate

    monkeypatch.setattr(groq_client, "generate", fake("groq"))
    monkeypatch.setattr(gemini_client, "generate", fake("gemini"))
    users.create_department("Engineering")
    users.create_department("Interns")
    users.create_user("alice", "Engineering")
    users.create_user("ivy", "Interns")


def post(key, provider):
    return client.post(URL, json={"provider": provider, "prompt": "Hello"}, headers={"X-API-Key": key})


def last_row():
    with closing(sqlite3.connect(db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 1").fetchone()


def test_default_is_deny():
    key = users.create_api_key("alice")
    r = post(key, "groq")
    assert r.status_code == 403
    assert "not allowed to use 'groq'" in r.json()["detail"]
    row = last_row()
    assert row["status_code"] == 403 and row["user_name"] == "alice" and row["provider"] == "groq"
    assert "may not use" in row["error"]


def test_granted_provider_works_and_other_is_blocked():
    users.grant_provider("Engineering", "groq")
    key = users.create_api_key("alice")
    assert post(key, "groq").status_code == 200
    assert post(key, "gemini").status_code == 403


def test_permissions_are_per_department():
    users.grant_provider("Engineering", "groq")
    ivy = users.create_api_key("ivy")
    assert post(ivy, "groq").status_code == 403  # Interns have no grant


def test_revoke_takes_effect_immediately():
    users.grant_provider("Engineering", "groq")
    key = users.create_api_key("alice")
    assert post(key, "groq").status_code == 200
    assert users.revoke_provider("Engineering", "groq") == 1
    assert post(key, "groq").status_code == 403


def test_unknown_provider_still_gets_minimums_422():
    key = users.create_api_key("alice")
    r = client.post(URL, json={"provider": "openai", "prompt": "Hello"}, headers={"X-API-Key": key})
    assert r.status_code == 422


def test_bad_key_is_401_before_permission_check():
    assert post("yg-wrong", "groq").status_code == 401


def test_admin_functions():
    users.grant_provider("Engineering", "GROQ")  # case-insensitive
    users.grant_provider("Engineering", "groq")  # idempotent
    assert users.allowed_providers("Engineering") == ["groq"]
    assert users.list_permissions() == [
        {"department": "Engineering", "providers": ["groq"]},
        {"department": "Interns", "providers": []},
    ]
    with pytest.raises(users.GovernanceError, match="Unknown provider"):
        users.grant_provider("Engineering", "openai")
    with pytest.raises(users.GovernanceError, match="Unknown department"):
        users.grant_provider("Nope", "groq")
