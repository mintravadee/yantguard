import re

import pytest
from fastapi.testclient import TestClient

from app.governance import admins, budgets, security, users
from app.governance.db import log_request
from app.main import app


@pytest.fixture
def client():
    c = TestClient(app, client=("127.0.0.1", 50000))
    admins.create_admin("boss", "correct horse")
    assert c.post("/dashboard/api/login", json={"username": "boss", "password": "correct horse"}).status_code == 200
    return c


@pytest.fixture(autouse=True)
def seed():
    users.create_department("Eng")
    users.create_user("alice", "Eng")
    budgets.set_budget("Eng", 1.0)
    log_request(user_name="alice", provider="groq", model="m", total_tokens=15, cost_usd=0.9,
                status_code=200, success=True, latency_ms=100)
    security.write_audit("alice", "Eng", "groq", [{"rule": "email", "action": "mask", "count": 1}])


def test_pages_and_files_are_served(client):
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Yant Guard" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert client.get("/dashboard/").status_code == 200
    for name, kind in (("dashboard.css", "text/css"), ("dashboard.js", "javascript"), ("login.js", "javascript")):
        r = client.get(f"/dashboard/static/{name}")
        assert r.status_code == 200 and kind in r.headers["content-type"]


def test_pages_have_no_inline_script_style_or_external_downloads(client):
    for html in (client.get("/dashboard").text, client.get("/dashboard/login").text):
        assert not re.search(r"<script(?![^>]*\bsrc=)", html)
        assert "style=" not in html and "onclick=" not in html
        assert not re.search(r'(src|href)="https?://', html)


def test_static_only_serves_the_known_files(client):
    assert client.get("/dashboard/static/index.html").status_code == 404
    assert client.get("/dashboard/static/..%2F..%2Fmain.py").status_code == 404


def test_summary_numbers(client):
    d = client.get("/dashboard/api/summary?days=30").json()
    assert d["kpis"]["requests"] == 1 and d["kpis"]["cost_usd"] == 0.9
    assert d["kpis"]["filter_masked"] == 1
    assert d["budgets"][0]["state"] == "warning" and d["budgets"][0]["percent"] == 90.0
    assert d["rules"]["email"] == "mask" and d["audit"][0]["rule"] == "email"
    assert d["requests"][0]["user"] == "alice"
    assert client.get("/dashboard/api/summary?days=0").status_code == 422
    assert client.get("/dashboard/api/summary?days=9999").status_code == 422


def test_dashboard_is_not_listed_in_api_docs():
    assert not any(p.startswith("/dashboard") for p in app.openapi()["paths"])
