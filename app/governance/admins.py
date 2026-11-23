"""Dashboard admin accounts, login sessions and the admin activity log.

Passwords: salted PBKDF2-SHA256. Sessions: a random token in an HttpOnly cookie;
only its SHA-256 hash is stored, so a copy of the database cannot be used to log in.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3

from app.governance.db import get_conn, init_db
from app.governance.users import GovernanceError

ITERATIONS = 600_000
SESSION_HOURS = 8
MIN_PASSWORD = 8
_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(test.hex(), digest)
    except Exception:
        return False


def _check_new_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise GovernanceError(f"The password must have at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise GovernanceError("The password is too long (200 characters at most).")


def admin_count() -> int:
    init_db()
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]


def create_admin(username: str, password: str) -> int:
    username = (username or "").strip()
    if not _USERNAME.match(username):
        raise GovernanceError("The username must be 3-40 characters: letters, digits, . _ -")
    _check_new_password(password)
    init_db()
    try:
        with get_conn() as conn:
            cur = conn.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                               (username, hash_password(password)))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise GovernanceError(f"Admin '{username}' already exists.") from None


_DUMMY = hash_password("x" * 12, 1000)  # keeps timing similar when the username does not exist


def authenticate_admin(username: str, password: str):
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT id, username, password_hash FROM admins WHERE username = ?",
                           ((username or "").strip(),)).fetchone()
    ok = check_password(password or "", row["password_hash"] if row else _DUMMY)
    return {"id": row["id"], "username": row["username"]} if (row and ok) else None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(admin_id: int) -> str:
    token = secrets.token_urlsafe(32)
    init_db()
    with get_conn() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
        conn.execute(
            "INSERT INTO admin_sessions (token_hash, admin_id, expires_at) "
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?))",
            (_token_hash(token), admin_id, f"+{SESSION_HOURS} hours"))
    return token


def session_admin(token):
    if not token:
        return None
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT a.id AS id, a.username AS username FROM admin_sessions s
               JOIN admins a ON a.id = s.admin_id
               WHERE s.token_hash = ? AND s.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (_token_hash(token),)).fetchone()
    return dict(row) if row else None


def end_session(token) -> None:
    if token:
        with get_conn() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (_token_hash(token),))


def change_password(admin_id: int, old: str, new: str, keep_token=None) -> None:
    """Change the password and sign out every other session of this admin."""
    _check_new_password(new)
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM admins WHERE id = ?", (admin_id,)).fetchone()
        if row is None or not check_password(old or "", row["password_hash"]):
            raise GovernanceError("The current password is wrong.")
        conn.execute("UPDATE admins SET password_hash = ? WHERE id = ?", (hash_password(new), admin_id))
        keep = _token_hash(keep_token) if keep_token else ""
        conn.execute("DELETE FROM admin_sessions WHERE admin_id = ? AND token_hash != ?", (admin_id, keep))


def log_action(admin_name, action: str, detail: str = "") -> None:
    init_db()
    with get_conn() as conn:
        conn.execute("INSERT INTO admin_log (admin_name, action, detail) VALUES (?, ?, ?)",
                     (admin_name, action, detail[:200]))


def recent_actions(limit: int = 20) -> list:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT id, created_at, admin_name, action, detail FROM admin_log "
                            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
