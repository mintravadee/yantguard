"""Departments, users and API keys (Step 3)."""
import hashlib
import secrets
import sqlite3

from app.governance.db import get_conn, init_db

KEY_PREFIX = "yg-"

# Providers the gateway knows (must match Min's GatewayRequest.provider).
KNOWN_PROVIDERS = ("gemini", "groq")


class GovernanceError(ValueError):
    """A problem the admin can fix (unknown department, duplicate name, ...)."""


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_department(name: str) -> None:
    init_db()
    name = name.strip()
    if not name:
        raise GovernanceError("Department name cannot be empty.")
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO departments (name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise GovernanceError(f"Department '{name}' already exists.") from None


def create_user(name: str, department: str) -> None:
    init_db()
    name = name.strip()
    if not name:
        raise GovernanceError("User name cannot be empty.")
    with get_conn() as conn:
        dept = conn.execute(
            "SELECT id FROM departments WHERE name = ?", (department,)
        ).fetchone()
        if dept is None:
            raise GovernanceError(
                f"Unknown department '{department}'. Create it first with add-department."
            )
        try:
            conn.execute(
                "INSERT INTO users (name, department_id) VALUES (?, ?)", (name, dept["id"])
            )
        except sqlite3.IntegrityError:
            raise GovernanceError(f"User '{name}' already exists.") from None


def create_api_key(user_name: str) -> str:
    """Create a key for a user and return it. This is the only time it is visible."""
    init_db()
    with get_conn() as conn:
        user = conn.execute("SELECT id FROM users WHERE name = ?", (user_name,)).fetchone()
        if user is None:
            raise GovernanceError(f"Unknown user '{user_name}'.")
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO api_keys (user_id, key_hash, key_prefix) VALUES (?, ?, ?)",
            (user["id"], hash_key(key), key[:10]),
        )
    return key


def revoke_key(key_prefix: str) -> int:
    """Revoke active keys that start with the given prefix. Returns how many."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE api_keys SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE key_prefix = ? AND revoked_at IS NULL""",
            (key_prefix,),
        )
        return cur.rowcount


def set_user_active(user_name: str, active: bool) -> None:
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET is_active = ? WHERE name = ?", (int(active), user_name)
        )
        if cur.rowcount == 0:
            raise GovernanceError(f"Unknown user '{user_name}'.")


def authenticate(key):
    """Return {'user': ..., 'department': ...} for a valid key, otherwise None."""
    if not key or not isinstance(key, str):
        return None
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT u.name AS user, d.name AS department
               FROM api_keys k
               JOIN users u ON u.id = k.user_id
               JOIN departments d ON d.id = u.department_id
               WHERE k.key_hash = ? AND k.revoked_at IS NULL AND u.is_active = 1""",
            (hash_key(key.strip()),),
        ).fetchone()
    return dict(row) if row else None


def list_users():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.name AS user, d.name AS department, u.is_active AS active,
                      (SELECT COUNT(*) FROM api_keys k
                        WHERE k.user_id = u.id AND k.revoked_at IS NULL) AS active_keys,
                      (SELECT group_concat(k.key_prefix, ', ') FROM api_keys k
                        WHERE k.user_id = u.id AND k.revoked_at IS NULL) AS key_prefixes
               FROM users u JOIN departments d ON d.id = u.department_id
               ORDER BY d.name, u.name"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- permissions (Step 4)

def _department_id(conn, department: str) -> int:
    row = conn.execute("SELECT id FROM departments WHERE name = ?", (department,)).fetchone()
    if row is None:
        raise GovernanceError(f"Unknown department '{department}'.")
    return row["id"]


def _check_provider(provider: str) -> str:
    provider = (provider or "").strip().lower()
    if provider not in KNOWN_PROVIDERS:
        raise GovernanceError(
            f"Unknown provider '{provider}'. Choose one of: {', '.join(KNOWN_PROVIDERS)}."
        )
    return provider


def grant_provider(department: str, provider: str) -> None:
    init_db()
    provider = _check_provider(provider)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO department_providers (department_id, provider) VALUES (?, ?)",
            (_department_id(conn, department), provider),
        )


def revoke_provider(department: str, provider: str) -> int:
    init_db()
    provider = _check_provider(provider)
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM department_providers WHERE department_id = ? AND provider = ?",
            (_department_id(conn, department), provider),
        )
        return cur.rowcount


def allowed_providers(department: str) -> list:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT dp.provider FROM department_providers dp
               JOIN departments d ON d.id = dp.department_id
               WHERE d.name = ? ORDER BY dp.provider""",
            (department,),
        ).fetchall()
    return [r["provider"] for r in rows]


def is_provider_allowed(department: str, provider: str) -> bool:
    """Default is deny: a department can use a provider only after it was granted."""
    return (provider or "").strip().lower() in allowed_providers(department)


def list_permissions() -> list:
    """Every department with the providers it may use (empty list = none)."""
    init_db()
    with get_conn() as conn:
        depts = conn.execute("SELECT name FROM departments ORDER BY name").fetchall()
    return [{"department": d["name"], "providers": allowed_providers(d["name"])} for d in depts]
