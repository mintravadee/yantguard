import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from app.gateway import groq_client
from app.governance.db import db_path, init_db
from app.main import app

client = TestClient(app)
URL = "/api/gateway/request"


def rows():
    init_db()
    with closing(sqlite3.connect(db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM requests ORDER BY id").fetchall()


def test_success_is_logged(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    async def fake_generate(prompt):
        return {
            "provider": "groq",
            "model": "test-model",
            "answer": "hi",
            "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
        }

    monkeypatch.setattr(groq_client, "generate", fake_generate)
    response = client.post(URL, json={"provider": "groq", "prompt": "Hello secret"})
    assert response.status_code == 200
    assert response.json()["answer"] == "hi"  # response unchanged by the middleware

    (row,) = rows()
    assert (row["provider"], row["model"]) == ("groq", "test-model")
    assert (row["prompt_tokens"], row["completion_tokens"], row["total_tokens"]) == (3, 5, 8)
    assert row["status_code"] == 200 and row["success"] == 1
    assert row["latency_ms"] is not None
    assert "secret" not in str(tuple(row))  # prompt text is never stored


def test_failure_is_logged(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    response = client.post(URL, json={"provider": "groq", "prompt": "Hello"})
    assert response.status_code == 503

    (row,) = rows()
    assert row["provider"] == "groq" and row["success"] == 0
    assert row["status_code"] == 503 and "not configured" in row["error"]


def test_other_routes_are_not_logged():
    assert client.get("/health").status_code == 200
    assert rows() == []


def test_server_start_creates_database():
    with TestClient(app):  # runs the startup (lifespan) code
        assert db_path().exists()
