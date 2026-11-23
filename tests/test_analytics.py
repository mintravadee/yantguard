import pytest

from app.governance import analytics, security, users
from app.governance.db import get_conn, init_db


def add(user, provider="groq", model="m", cost=0.5, tokens=100, status=200, latency=100, when="now"):
    init_db()
    created = "strftime('%Y-%m-%dT%H:%M:%fZ','now')" if when == "now" else f"'{when}'"
    with get_conn() as conn:
        conn.execute(
            f"INSERT INTO requests (created_at, user_name, provider, model, total_tokens, cost_usd, "
            f"status_code, success, latency_ms) VALUES ({created}, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user, provider, model, tokens, cost, status, int(status == 200), latency))


@pytest.fixture(autouse=True)
def data():
    users.create_department("Eng")
    users.create_department("Ops")
    users.create_user("alice", "Eng")
    users.create_user("bob", "Ops")
    add("alice", cost=1.0, tokens=200, latency=100)
    add("alice", cost=0.5, tokens=100, latency=300)
    add("bob", cost=2.0, tokens=50)
    add("bob", status=429, cost=None, tokens=None)
    add(None, status=401, cost=None, tokens=None)
    add("alice", cost=99, when="2020-01-01T00:00:00.000Z")  # outside the window


def test_kpis():
    k = analytics.kpis(30)
    assert k["requests"] == 5 and k["successful"] == 3
    assert k["cost_usd"] == 3.5 and k["tokens"] == 350
    assert k["success_rate"] == 60.0 and k["avg_latency_ms"] == pytest.approx((100 + 300 + 100) / 3)


def test_kpis_empty_window():
    k = analytics.kpis(0)
    assert k["requests"] == 0 and k["success_rate"] is None


def test_by_department_and_user():
    dep = {r["department"]: r for r in analytics.by_department(30)}
    assert dep["Eng"]["cost_usd"] == 1.5 and dep["Ops"]["cost_usd"] == 2.0
    assert dep["(no user)"]["requests"] == 1
    top = analytics.by_user(30, limit=1)
    assert top[0]["user"] == "bob"


def test_daily_groups_by_day_and_department():
    rows = analytics.daily(30)
    assert {r["department"] for r in rows} == {"Eng", "Ops", "(no user)"}
    assert sum(r["cost_usd"] for r in rows) == 3.5


def test_outcomes_have_readable_labels():
    labels = {r["outcome"]: r["requests"] for r in analytics.outcomes(30)}
    assert labels["OK"] == 3 and labels["Budget used up"] == 1 and labels["Bad or missing API key"] == 1


def test_security_summary_and_kpis():
    security.write_audit("alice", "Eng", "groq", [{"rule": "email", "action": "mask", "count": 2},
                                                   {"rule": "credit_card", "action": "block", "count": 1}])
    s = {(r["rule"], r["action"]): r["matches"] for r in analytics.security_summary(30)}
    assert s[("email", "masked")] == 2 and s[("credit_card", "blocked")] == 1
    k = analytics.kpis(30)
    assert (k["filter_masked"], k["filter_blocked"]) == (2, 1)


def test_by_model_and_recent():
    assert analytics.by_model(30)[0]["requests"] == 3
    assert analytics.recent_requests(2)[0]["id"] > analytics.recent_requests(2)[1]["id"]
