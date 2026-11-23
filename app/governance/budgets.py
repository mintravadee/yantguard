"""Step 6: monthly budget per department.

Spend = sum of cost_usd (Step 5) of this calendar month (UTC) for all users of
the department. At 80% the state is "warning"; at 100% the gateway refuses new
requests with HTTP 429 before anything is sent to a provider.
Requests whose model has no known price (cost None) cannot be counted.
"""
from app.governance.db import get_conn, init_db
from app.governance.users import GovernanceError, _department_id

WARN_AT = 0.8


def set_budget(department: str, monthly_limit_usd: float) -> None:
    if not isinstance(monthly_limit_usd, (int, float)) or monthly_limit_usd <= 0:
        raise GovernanceError("The budget must be a number greater than 0.")
    init_db()
    with get_conn() as conn:
        dept_id = _department_id(conn, department)
        conn.execute(
            """INSERT INTO department_budgets (department_id, monthly_limit_usd) VALUES (?, ?)
               ON CONFLICT(department_id) DO UPDATE SET monthly_limit_usd = excluded.monthly_limit_usd""",
            (dept_id, float(monthly_limit_usd)),
        )


def clear_budget(department: str) -> int:
    init_db()
    with get_conn() as conn:
        dept_id = _department_id(conn, department)
        return conn.execute("DELETE FROM department_budgets WHERE department_id = ?", (dept_id,)).rowcount


def _status_from(department, limit, spent) -> dict:
    if limit is None:
        return {"department": department, "limit": None, "spent": spent,
                "remaining": None, "percent": None, "state": "no_budget"}
    ratio = spent / limit
    state = "exceeded" if ratio >= 1 else "warning" if ratio >= WARN_AT else "ok"
    return {"department": department, "limit": limit, "spent": spent,
            "remaining": max(limit - spent, 0.0), "percent": round(ratio * 100, 1), "state": state}


def budget_status(department: str) -> dict:
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT d.name AS name, b.monthly_limit_usd AS lim,
                      (SELECT COALESCE(SUM(r.cost_usd), 0) FROM requests r
                         JOIN users u ON u.name = r.user_name
                        WHERE u.department_id = d.id
                          AND substr(r.created_at, 1, 7) = strftime('%Y-%m', 'now')) AS spent
               FROM departments d
               LEFT JOIN department_budgets b ON b.department_id = d.id
               WHERE d.name = ?""",
            (department,),
        ).fetchone()
    if row is None:
        raise GovernanceError(f"Unknown department '{department}'.")
    return _status_from(row["name"], row["lim"], row["spent"])


def all_budget_status() -> list:
    init_db()
    with get_conn() as conn:
        names = [r["name"] for r in conn.execute("SELECT name FROM departments ORDER BY name")]
    return [budget_status(n) for n in names]
