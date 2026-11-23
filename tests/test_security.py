import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.gateway import groq_client
from app.governance import security, users
from app.governance.db import db_path, init_db
from app.main import app

client = TestClient(app)
URL = "/api/gateway/request"
VALID_CARD = "4111 1111 1111 1111"
VALID_THAI_ID = "1-1018-00123-45-6"  # checksum computed below in test


def thai_id():
    d = [1, 1, 0, 1, 8, 0, 0, 1, 2, 3, 4, 5]
    s = sum(x * (13 - i) for i, x in enumerate(d))
    return "".join(map(str, d)) + str((11 - s % 11) % 10)


# ------------------------------------------------------------ pure scanning

def test_email_phone_masked_by_default():
    r = security.scan_prompt("Mail bob@example.com or call 081-234-5678 please")
    assert r["text"] == "Mail [EMAIL] or call [PHONE] please"
    assert r["blocked"] == []
    assert {f["rule"] for f in r["findings"]} == {"email", "phone"}


def test_blocked_by_default():
    for text in (
        "key sk-abcdefghijklmnopqrstuvwxyz123456",
        "my password: hunter2",
        f"card {VALID_CARD}",
        "AKIAABCDEFGHIJKLMNOP",
    ):
        assert security.scan_prompt(text)["blocked"], text


def test_card_needs_valid_luhn():
    assert security.scan_prompt("order 4111 1111 1111 1112")["findings"] == []


def test_thai_id_checksum():
    assert security.scan_prompt(f"id {thai_id()}")["text"] == "id [THAI_ID]"
    bad = thai_id()[:-1] + str((int(thai_id()[-1]) + 1) % 10)
    assert security.scan_prompt(f"id {bad}")["findings"] == []


def test_normal_text_untouched():
    text = "Summarise the Q3 report: revenue grew 12% to 4,500,000 baht in 2026."
    r = security.scan_prompt(text)
    assert r["text"] == text and r["findings"] == []


def test_rule_actions_can_change():
    security.set_rule_action("email", "off")
    assert security.scan_prompt("a@b.com")["findings"] == []
    security.set_rule_action("email", "block")
    assert security.scan_prompt("a@b.com")["blocked"] == ["email"]
    with pytest.raises(users.GovernanceError):
        security.set_rule_action("nope", "mask")
    with pytest.raises(users.GovernanceError):
        security.set_rule_action("email", "explode")


# ------------------------------------------------------------ through the gateway

@pytest.fixture
def sent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    box = {}

    async def generate(prompt):
        box["prompt"] = prompt
        return {"provider": "groq", "model": "openai/gpt-oss-20b", "answer": "ok",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

    monkeypatch.setattr(groq_client, "generate", generate)
    return box


def post(prompt):
    return client.post(URL, json={"provider": "groq", "prompt": prompt})


def audit_rows():
    init_db()
    with closing(sqlite3.connect(db_path())) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()


def test_masked_prompt_reaches_provider_cleaned(sent):
    r = post("Write to bob@example.com about the invoice")
    assert r.status_code == 200
    assert sent["prompt"] == "Write to [EMAIL] about the invoice"
    assert "email x1" in r.headers["x-security-filter"]
    (row,) = audit_rows()
    assert (row["rule"], row["action"], row["match_count"]) == ("email", "masked", 1)
    assert "bob" not in str(tuple(row))  # the value itself is never stored


def test_blocked_prompt_never_reaches_provider(sent):
    r = post(f"Pay with {VALID_CARD}")
    assert r.status_code == 400 and "credit_card" in r.json()["detail"]
    assert "prompt" not in sent
    with closing(sqlite3.connect(db_path())) as conn:
        status, err = conn.execute("SELECT status_code, error FROM requests").fetchone()
    assert status == 400 and "credit_card" in err
    assert VALID_CARD not in err
    assert audit_rows()[0]["action"] == "blocked"


def test_clean_prompt_passes_untouched(sent):
    r = post("Hello there")
    assert r.status_code == 200 and sent["prompt"] == "Hello there"
    assert "x-security-filter" not in r.headers and audit_rows() == []


def test_filter_can_be_switched_off(sent, monkeypatch):
    monkeypatch.setenv("YANTGUARD_FILTER", "false")
    assert post(f"Pay with {VALID_CARD}").status_code == 200
    assert sent["prompt"].endswith(VALID_CARD)


def test_audit_records_user_and_department(sent, monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "true")
    users.create_department("Engineering")
    users.create_user("alice", "Engineering")
    users.grant_provider("Engineering", "groq")
    key = users.create_api_key("alice")
    r = client.post(URL, json={"provider": "groq", "prompt": "mail a@b.com"}, headers={"X-API-Key": key})
    assert r.status_code == 200
    row = audit_rows()[0]
    assert (row["user_name"], row["department"], row["provider"]) == ("alice", "Engineering", "groq")
