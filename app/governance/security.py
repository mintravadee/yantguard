"""Step 7: security filter for prompts.

Each prompt is scanned before it is sent to a provider. A rule can be set to
  mask  - replace the value with a placeholder such as [EMAIL] and send on
  block - refuse the request (HTTP 400), nothing is sent
  off   - ignore this rule
The audit log stores WHO triggered WHICH rule and HOW MANY times - never the
sensitive value and never the prompt.

This is pattern matching (regex plus checksums for cards and Thai ID numbers).
It is fast and offline but only catches well-formed values. Names and
addresses need a smarter detector (e.g. Presidio) later; it can replace
find_matches() without changing the rest.
"""
import os
import re

from app.governance.db import get_conn, init_db
from app.governance.users import GovernanceError

ACTIONS = ("mask", "block", "off")

# (rule name, regex, default action, placeholder). Order matters: earlier rules win.
RULES = [
    ("api_key", re.compile(
        r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{35}|gsk_[A-Za-z0-9]{20,}"
        r"|yg-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,})"),
     "block", "[API_KEY]"),
    ("password", re.compile(r"(?i)(?:password|passwd|pwd|secret|รหัสผ่าน)\s*(?:is\s*)?[:=]\s*\S+"),
     "block", "[PASSWORD]"),
    ("thai_id", re.compile(r"(?<!\d)\d-?\d{4}-?\d{5}-?\d{2}-?\d(?!\d)"), "mask", "[THAI_ID]"),
    ("credit_card", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"), "block", "[CREDIT_CARD]"),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "mask", "[EMAIL]"),
    ("phone", re.compile(
        r"(?<![\d+])(?:(?:\+66|0)[\s-]?[2-9]\d?[\s-]?\d{3}[\s-]?\d{3,4}"
        r"|\+\d{1,3}[\s-]?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4})(?!\d)"),
     "mask", "[PHONE]"),
]
DEFAULTS = {name: action for name, _, action, _ in RULES}


def filter_enabled() -> bool:
    return os.getenv("YANTGUARD_FILTER", "true").strip().lower() not in ("0", "false", "no")


def _luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _thai_id_ok(digits: str) -> bool:
    if len(digits) != 13 or digits[0] == "0":
        return False
    s = sum(int(digits[i]) * (13 - i) for i in range(12))
    return (11 - s % 11) % 10 == int(digits[12])


def _valid(rule: str, text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if rule == "credit_card":
        return _luhn_ok(digits)
    if rule == "thai_id":
        return _thai_id_ok(digits)
    if rule == "phone":
        return 9 <= len(digits) <= 15
    return True


# ---------------------------------------------------------------- rule settings

def get_rule_actions() -> dict:
    """Default actions, overridden by the security_rules table."""
    init_db()
    actions = dict(DEFAULTS)
    with get_conn() as conn:
        for row in conn.execute("SELECT name, action FROM security_rules"):
            if row["name"] in actions and row["action"] in ACTIONS:
                actions[row["name"]] = row["action"]
    return actions


def set_rule_action(rule: str, action: str) -> None:
    rule, action = (rule or "").strip().lower(), (action or "").strip().lower()
    if rule not in DEFAULTS:
        raise GovernanceError(f"Unknown rule '{rule}'. Rules: {', '.join(DEFAULTS)}.")
    if action not in ACTIONS:
        raise GovernanceError(f"Action must be one of: {', '.join(ACTIONS)}.")
    init_db()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO security_rules (name, action) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET action = excluded.action""",
            (rule, action),
        )


# ---------------------------------------------------------------- scanning

def scan_prompt(text: str, actions: dict | None = None) -> dict:
    """Return {'text': masked text, 'findings': [{rule, action, count}], 'blocked': [rules]}."""
    actions = actions or get_rule_actions()
    work = text
    counts: dict = {}
    for name, pattern, _, placeholder in RULES:
        action = actions.get(name, "off")
        if action == "off":
            continue

        def repl(m, name=name, placeholder=placeholder):
            if not _valid(name, m.group(0)):
                return m.group(0)
            counts[name] = counts.get(name, 0) + 1
            return placeholder

        work = pattern.sub(repl, work)
    findings = [{"rule": r, "action": actions[r], "count": c} for r, c in counts.items()]
    blocked = [f["rule"] for f in findings if f["action"] == "block"]
    return {"text": work, "findings": findings, "blocked": blocked}


# ---------------------------------------------------------------- audit log

def write_audit(user_name, department, provider, findings) -> None:
    if not findings:
        return
    init_db()
    with get_conn() as conn:
        for f in findings:
            conn.execute(
                """INSERT INTO audit_log (user_name, department, provider, rule, action, match_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_name, department, provider, f["rule"],
                 "blocked" if f["action"] == "block" else "masked", f["count"]),
            )


def recent_audit(limit: int = 20) -> list:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, created_at, user_name, department, provider, rule, action, match_count
               FROM audit_log ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]
