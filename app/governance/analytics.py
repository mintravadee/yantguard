"""Step 8: read-only numbers for the dashboard (and, later, the desktop app).

Every function takes `days` (the time window, counted back from now) and
returns plain lists of dicts, so any front end can use them.
Costs are the "equivalent list price" from Step 5; requests with an unknown
model have no cost and count as 0 here.
"""
from app.governance.db import get_conn, init_db

SINCE = "r.created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)"
DEPT = "COALESCE(d.name, '(no user)')"
FROM = "FROM requests r LEFT JOIN users u ON u.name = r.user_name LEFT JOIN departments d ON d.id = u.department_id"

STATUS_LABELS = {
    200: "OK",
    400: "Blocked by security filter",
    401: "Bad or missing API key",
    403: "Provider not allowed",
    422: "Invalid request",
    429: "Budget used up",
    503: "Provider unavailable",
}


def _window(days: int) -> str:
    return f"-{int(days)} days"


def _rows(sql: str, params: tuple) -> list:
    init_db()
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def kpis(days: int = 30) -> dict:
    row = _rows(
        f"""SELECT COUNT(*) AS requests,
                   COALESCE(SUM(r.success), 0) AS successful,
                   COALESCE(SUM(r.cost_usd), 0) AS cost_usd,
                   COALESCE(SUM(r.total_tokens), 0) AS tokens,
                   AVG(CASE WHEN r.success = 1 THEN r.latency_ms END) AS avg_latency_ms
            FROM requests r WHERE {SINCE}""",
        (_window(days),),
    )[0]
    row["success_rate"] = (row["successful"] / row["requests"] * 100) if row["requests"] else None
    audit = _rows(
        """SELECT COALESCE(SUM(CASE WHEN action='blocked' THEN match_count END), 0) AS blocked,
                  COALESCE(SUM(CASE WHEN action='masked' THEN match_count END), 0) AS masked
           FROM audit_log WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)""",
        (_window(days),),
    )[0]
    row["filter_blocked"], row["filter_masked"] = audit["blocked"], audit["masked"]
    return row


def daily(days: int = 30) -> list:
    """One row per day and department: requests and cost."""
    return _rows(
        f"""SELECT substr(r.created_at, 1, 10) AS day, {DEPT} AS department,
                   COUNT(*) AS requests, COALESCE(SUM(r.cost_usd), 0) AS cost_usd
            {FROM} WHERE {SINCE}
            GROUP BY day, department ORDER BY day, department""",
        (_window(days),),
    )


def by_department(days: int = 30) -> list:
    return _rows(
        f"""SELECT {DEPT} AS department, COUNT(*) AS requests,
                   COALESCE(SUM(r.total_tokens), 0) AS tokens,
                   COALESCE(SUM(r.cost_usd), 0) AS cost_usd
            {FROM} WHERE {SINCE} GROUP BY department ORDER BY cost_usd DESC, requests DESC""",
        (_window(days),),
    )


def by_user(days: int = 30, limit: int = 10) -> list:
    return _rows(
        f"""SELECT COALESCE(r.user_name, '(no key)') AS user, {DEPT} AS department,
                   COUNT(*) AS requests, COALESCE(SUM(r.total_tokens), 0) AS tokens,
                   COALESCE(SUM(r.cost_usd), 0) AS cost_usd
            {FROM} WHERE {SINCE} GROUP BY user, department
            ORDER BY cost_usd DESC, requests DESC LIMIT ?""",
        (_window(days), limit),
    )


def by_model(days: int = 30) -> list:
    return _rows(
        f"""SELECT r.provider AS provider, COALESCE(r.model, '-') AS model, COUNT(*) AS requests,
                   COALESCE(SUM(r.cost_usd), 0) AS cost_usd,
                   AVG(r.latency_ms) AS avg_latency_ms
            FROM requests r WHERE {SINCE} AND r.success = 1
            GROUP BY provider, model ORDER BY requests DESC""",
        (_window(days),),
    )


def outcomes(days: int = 30) -> list:
    rows = _rows(
        f"SELECT r.status_code AS status_code, COUNT(*) AS requests FROM requests r WHERE {SINCE} "
        "GROUP BY status_code ORDER BY requests DESC",
        (_window(days),),
    )
    for r in rows:
        r["outcome"] = STATUS_LABELS.get(r["status_code"], f"HTTP {r['status_code']}")
    return rows


def security_summary(days: int = 30) -> list:
    return _rows(
        """SELECT rule, action, SUM(match_count) AS matches, COUNT(DISTINCT user_name) AS users
           FROM audit_log WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
           GROUP BY rule, action ORDER BY matches DESC""",
        (_window(days),),
    )


def recent_requests(limit: int = 50) -> list:
    return _rows(
        """SELECT r.id AS id, r.created_at AS time, COALESCE(r.user_name, '-') AS user,
                  r.provider AS provider, r.model AS model, r.total_tokens AS tokens,
                  r.cost_usd AS cost_usd, r.status_code AS status, r.latency_ms AS latency_ms,
                  r.error AS error
           FROM requests r ORDER BY r.id DESC LIMIT ?""",
        (limit,),
    )
