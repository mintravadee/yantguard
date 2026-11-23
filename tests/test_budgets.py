import pytest
from fastapi.testclient import TestClient

from app.gateway import groq_client
from app.governance import budgets, users
from app.governance.db import get_conn, init_db
from app.governance.users import GovernanceError
from app.main import app

client = TestClient(app)
URL = "/api/gateway/request"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "true")
    monkeypatch.setenv("GROQ_API_KEY", "k")

    async def generate(prompt):
        return {"provider": "groq", "model": "openai/gpt-oss-20b", "answer": "hi",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}}

    monkeypatch.setattr(groq_client, "generate", generate)
    users.create_department("Engineering")
    users.create_user("alice", "Engineering")
    users.grant_provider("Engineering", "groq")


def spend(user, usd, when="now"):
    init_db()
    with get_conn() as conn:
        created = "strftime('%Y-%m-%dT%H:%M:%fZ','now')" if when == "now" else f"'{when}'"
        conn.execute(
            f"INSERT INTO requests (created_at, user_name, provider, cost_usd, status_code, success) "
            f"VALUES ({created}, ?, 'groq', ?, 200, 1)", (user, usd))


def post(key):
    return client.post(URL, json={"provider": "groq", "prompt": "Hello"}, headers={"X-API-Key": key})


def test_no_budget_means_no_limit():
    spend("alice", 999)
    assert budgets.budget_status("Engineering")["state"] == "no_budget"
    assert post(users.create_api_key("alice")).status_code == 200


def test_states_ok_warning_exceeded():
    budgets.set_budget("Engineering", 10)
    assert budgets.budget_status("Engineering")["state"] == "ok"
    spend("alice", 8)
    s = budgets.budget_status("Engineering")
    assert s["state"] == "warning" and s["percent"] == 80.0 and s["remaining"] == 2
    spend("alice", 2)
    assert budgets.budget_status("Engineering")["state"] == "exceeded"


def test_warning_header_then_block_with_429():
    key = users.create_api_key("alice")
    budgets.set_budget("Engineering", 10)
    assert "x-budget-warning" not in post(key).headers
    spend("alice", 8.5)
    r = post(key)
    assert r.status_code == 200 and "85" in r.headers["x-budget-warning"]
    spend("alice", 5)
    r = post(key)
    assert r.status_code == 429 and "budget" in r.json()["detail"]


def test_blocked_request_is_logged_and_costs_nothing():
    key = users.create_api_key("alice")
    budgets.set_budget("Engineering", 1)
    spend("alice", 1)
    assert post(key).status_code == 429
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status_code"] == 429 and row["cost_usd"] is None and "monthly budget" in row["error"]


def test_only_this_month_and_this_department_count():
    users.create_department("Interns")
    users.create_user("ivy", "Interns")
    budgets.set_budget("Engineering", 10)
    spend("alice", 50, when="2020-01-15T10:00:00.000Z")  # old month
    spend("ivy", 50)                                      # other department
    assert budgets.budget_status("Engineering")["spent"] == 0


def test_raising_or_clearing_budget_unblocks():
    key = users.create_api_key("alice")
    budgets.set_budget("Engineering", 1)
    spend("alice", 2)
    assert post(key).status_code == 429
    budgets.set_budget("Engineering", 100)
    assert post(key).status_code == 200
    assert budgets.clear_budget("Engineering") == 1


def test_bad_input():
    with pytest.raises(GovernanceError):
        budgets.set_budget("Engineering", 0)
    with pytest.raises(GovernanceError):
        budgets.set_budget("Nope", 5)
