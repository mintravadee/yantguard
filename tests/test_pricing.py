import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from app.gateway import groq_client
from app.governance import pricing
from app.governance.db import db_path, init_db
from app.main import app

client = TestClient(app)


def test_calculate_cost_known_model():
    # 1M in + 1M out on gpt-oss-20b = 0.075 + 0.30
    assert pricing.calculate_cost("openai/gpt-oss-20b", 1_000_000, 1_000_000) == 0.375
    assert pricing.calculate_cost("openai/gpt-oss-20b", 1000, 500) == 0.000225


def test_prefix_match_and_unknown_model():
    assert pricing.calculate_cost("gemini-3.8-flash-001", 1_000_000, 0) == 0.30
    assert pricing.calculate_cost("mystery-model", 10, 10) is None
    assert pricing.calculate_cost(None, 10, 10) is None
    assert pricing.calculate_cost("openai/gpt-oss-20b", None, 10) is None


def test_override_file(tmp_path, monkeypatch):
    f = tmp_path / "prices.json"
    f.write_text('{"my-model": [1.0, 2.0]}')
    monkeypatch.setattr(pricing, "OVERRIDE_FILE", f)
    assert pricing.calculate_cost("my-model", 1_000_000, 1_000_000) == 3.0
    f.write_text("not json")  # broken file must not crash
    assert pricing.calculate_cost("openai/gpt-oss-20b", 1_000_000, 0) == 0.075


def test_cost_is_logged(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "false")

    async def fake(prompt):
        return {"provider": "groq", "model": "openai/gpt-oss-20b", "answer": "x",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}}

    monkeypatch.setattr(groq_client, "generate", fake)
    assert client.post("/api/gateway/request", json={"provider": "groq", "prompt": "hi"}).status_code == 200
    init_db()
    with closing(sqlite3.connect(db_path())) as conn:
        (cost,) = conn.execute("SELECT cost_usd FROM requests").fetchone()
    assert cost == 0.000225
