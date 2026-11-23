r"""Admin commands for Yant Guard users and API keys. Run from the repo root:

    .venv\Scripts\python.exe scripts\manage.py add-department Engineering
    .venv\Scripts\python.exe scripts\manage.py add-user alice --dept Engineering
    .venv\Scripts\python.exe scripts\manage.py create-key alice
    .venv\Scripts\python.exe scripts\manage.py list-users
    .venv\Scripts\python.exe scripts\manage.py revoke-key yg-AbCdEfG
    .venv\Scripts\python.exe scripts\manage.py disable-user alice
    .venv\Scripts\python.exe scripts\manage.py grant Engineering groq
    .venv\Scripts\python.exe scripts\manage.py revoke Engineering groq
    .venv\Scripts\python.exe scripts\manage.py permissions
    .venv\Scripts\python.exe scripts\manage.py set-budget Engineering 5
    .venv\Scripts\python.exe scripts\manage.py budgets
    .venv\Scripts\python.exe scripts\manage.py rules
    .venv\Scripts\python.exe scripts\manage.py set-rule email block
    .venv\Scripts\python.exe scripts\manage.py audit
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.governance import budgets, security, users  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Yant Guard admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("add-department").add_argument("name")
    p = sub.add_parser("add-user")
    p.add_argument("name")
    p.add_argument("--dept", required=True)
    sub.add_parser("create-key").add_argument("user")
    sub.add_parser("revoke-key").add_argument("prefix", help="first 10 characters of the key, e.g. yg-AbCdEfG")
    sub.add_parser("disable-user").add_argument("user")
    sub.add_parser("enable-user").add_argument("user")
    sub.add_parser("list-users")
    g = sub.add_parser("grant", help="let a department use a provider")
    g.add_argument("department")
    g.add_argument("provider")
    r = sub.add_parser("revoke", help="stop a department using a provider")
    r.add_argument("department")
    r.add_argument("provider")
    sub.add_parser("permissions")
    b = sub.add_parser("set-budget", help="monthly USD limit for a department (0 removes it)")
    b.add_argument("department")
    b.add_argument("amount", type=float)
    sub.add_parser("budgets")
    sub.add_parser("rules")
    sr = sub.add_parser("set-rule", help="mask, block or off")
    sr.add_argument("rule")
    sr.add_argument("action")
    sub.add_parser("audit")

    a = parser.parse_args()
    try:
        if a.cmd == "add-department":
            users.create_department(a.name)
            print(f"Department '{a.name}' created.")
        elif a.cmd == "add-user":
            users.create_user(a.name, a.dept)
            print(f"User '{a.name}' created in '{a.dept}'. Next: create-key {a.name}")
        elif a.cmd == "create-key":
            key = users.create_api_key(a.user)
            print(f"API key for '{a.user}':\n\n    {key}\n")
            print("Copy it now. It is stored only as a hash and cannot be shown again.")
        elif a.cmd == "revoke-key":
            n = users.revoke_key(a.prefix)
            print(f"Revoked {n} key(s).")
        elif a.cmd == "disable-user":
            users.set_user_active(a.user, False)
            print(f"User '{a.user}' disabled.")
        elif a.cmd == "enable-user":
            users.set_user_active(a.user, True)
            print(f"User '{a.user}' enabled.")
        elif a.cmd == "grant":
            users.grant_provider(a.department, a.provider)
            print(f"'{a.department}' may now use '{a.provider}'.")
        elif a.cmd == "revoke":
            n = users.revoke_provider(a.department, a.provider)
            print(f"'{a.department}' may no longer use '{a.provider}'." if n else "Nothing to revoke.")
        elif a.cmd == "permissions":
            for row in users.list_permissions():
                print(f"{row['department']:<15} {', '.join(row['providers']) or '(nothing allowed)'}")
        elif a.cmd == "set-budget":
            if a.amount == 0:
                budgets.clear_budget(a.department)
                print(f"'{a.department}' no longer has a budget.")
            else:
                budgets.set_budget(a.department, a.amount)
                print(f"'{a.department}' may spend ${a.amount:.2f} per month.")
        elif a.cmd == "budgets":
            for r in budgets.all_budget_status():
                if r["limit"] is None:
                    print(f"{r['department']:<15} no budget (spent ${r['spent']:.4f})")
                else:
                    print(f"{r['department']:<15} ${r['spent']:.4f} / ${r['limit']:.2f} ({r['percent']}%) {r['state']}")
        elif a.cmd == "rules":
            for rule, action in security.get_rule_actions().items():
                print(f"{rule:<12} {action}")
        elif a.cmd == "set-rule":
            security.set_rule_action(a.rule, a.action)
            print(f"Rule '{a.rule}' is now '{a.action}'.")
        elif a.cmd == "audit":
            rows = security.recent_audit(20)
            if not rows:
                print("Nothing caught yet.")
            for r in rows:
                print(f"#{r['id']} {r['created_at'][:19]} {r['user_name'] or '-'} {r['rule']} x{r['match_count']} {r['action']}")
        elif a.cmd == "list-users":
            rows = users.list_users()
            if not rows:
                print("No users yet.")
            for r in rows:
                state = "active" if r["active"] else "DISABLED"
                print(f"{r['user']:<15} {r['department']:<15} {state:<9} keys: {r['active_keys']} {r['key_prefixes'] or ''}")
    except users.GovernanceError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
