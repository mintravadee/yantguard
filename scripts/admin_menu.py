r"""Yant Guard admin menu: manage departments, users and API keys, and view the log.

Double-click admin.bat in the repo root, or run:
    .venv\Scripts\python.exe scripts\admin_menu.py
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.governance import budgets, security, users  # noqa: E402
from app.governance.db import get_conn, init_db  # noqa: E402


def ask(prompt: str) -> str:
    return input(prompt).strip()


def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["clip"], input=text.encode("ascii"), check=True)
        return True
    except Exception:
        return False


def departments() -> list:
    init_db()
    with get_conn() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM departments ORDER BY name")]


def pick_department() -> str:
    names = departments()
    if names:
        print("Departments:", ", ".join(names))
    name = ask("Department (type a new name to create it): ")
    if name and name not in names:
        users.create_department(name)
        print(f"  Department '{name}' created.")
    return name


def show_key(user: str, key: str) -> None:
    print(f"\nAPI key for '{user}':\n\n    {key}\n")
    if copy_to_clipboard(key):
        print("It has been copied to your clipboard (paste with Ctrl+V).")
    print("Keep it safe: it is stored only as a hash and cannot be shown again.")


def pick_user() -> str:
    rows = users.list_users()
    if not rows:
        print("No users yet. Use option 1 first.")
        return ""
    print("Users:", ", ".join(r["user"] for r in rows))
    return ask("User name: ")


def new_user() -> None:
    name = ask("New user name: ")
    if not name:
        return
    dept = pick_department()
    users.create_user(name, dept)
    print(f"User '{name}' created in '{dept}'.")
    show_key(name, users.create_api_key(name))


def new_key() -> None:
    user = pick_user()
    if user:
        show_key(user, users.create_api_key(user))


def replace_key() -> None:
    """Lost a key? Keys cannot be read back, so retire the old ones and issue a fresh one."""
    user = pick_user()
    if not user:
        return
    row = next((r for r in users.list_users() if r["user"] == user), None)
    if row is None:
        print(f"Unknown user '{user}'.")
        return
    old = [p.strip() for p in (row["key_prefixes"] or "").split(",") if p.strip()]
    if ask(f"Revoke {len(old)} active key(s) of '{user}' and create a new one? (yes/no): ").lower() != "yes":
        print("Nothing changed.")
        return
    for prefix in old:
        users.revoke_key(prefix)
    show_key(user, users.create_api_key(user))


def list_all() -> None:
    rows = users.list_users()
    if not rows:
        print("No users yet.")
    for r in rows:
        state = "active" if r["active"] else "DISABLED"
        print(f"  {r['user']:<15} {r['department']:<15} {state:<9} keys: {r['active_keys']}  {r['key_prefixes'] or ''}")


def revoke() -> None:
    list_all()
    prefix = ask("First 10 characters of the key to revoke (e.g. yg-AbCdEfG): ")
    if prefix:
        print(f"Revoked {users.revoke_key(prefix)} key(s).")


def toggle() -> None:
    user = pick_user()
    if not user:
        return
    choice = ask("Type 'disable' or 'enable': ").lower()
    if choice in ("disable", "enable"):
        users.set_user_active(user, choice == "enable")
        print(f"User '{user}' {choice}d.")


def show_log() -> None:
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, created_at, user_name, provider, model, total_tokens,
                      cost_usd, status_code, latency_ms, error
               FROM requests ORDER BY id DESC LIMIT 15"""
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    for r in rows:
        err = f" | {r['error']}" if r["error"] else ""
        print(f"  #{r['id']} {r['created_at'][:19]} | {r['user_name'] or '-'} | "
              f"{r['provider']}/{r['model']} | tokens {r['total_tokens']} | "
              f"cost {'-' if r['cost_usd'] is None else '$%.6f' % r['cost_usd']} | "
              f"HTTP {r['status_code']} | {r['latency_ms']} ms{err}")
    print(f"  ({total} request(s) in total)")


def pick_existing_department() -> str:
    names = departments()
    if not names:
        print("No departments yet. Create a user first (option 1).")
        return ""
    print("Departments:", ", ".join(names))
    return ask("Department: ")


def set_access() -> None:
    dept = pick_existing_department()
    if not dept:
        return
    provider = ask(f"Provider ({', '.join(users.KNOWN_PROVIDERS)}): ").lower()
    action = ask("Type 'allow' or 'block': ").lower()
    if action == "allow":
        users.grant_provider(dept, provider)
        print(f"'{dept}' may now use '{provider}'.")
    elif action == "block":
        n = users.revoke_provider(dept, provider)
        print(f"'{dept}' may no longer use '{provider}'." if n else "It was not allowed anyway.")
    else:
        print("Nothing changed.")


def show_access() -> None:
    rows = users.list_permissions()
    if not rows:
        print("No departments yet.")
    for r in rows:
        print(f"  {r['department']:<15} {', '.join(r['providers']) or '(nothing allowed)'}")


def set_budget() -> None:
    dept = pick_existing_department()
    if not dept:
        return
    value = ask("Monthly budget in USD (type 0 to remove the limit): ")
    try:
        amount = float(value)
    except ValueError:
        print("Please type a number, for example 5 or 12.50.")
        return
    if amount == 0:
        budgets.clear_budget(dept)
        print(f"'{dept}' no longer has a budget.")
    else:
        budgets.set_budget(dept, amount)
        print(f"'{dept}' may spend ${amount:.2f} per month.")


def show_budgets() -> None:
    rows = budgets.all_budget_status()
    if not rows:
        print("No departments yet.")
    for r in rows:
        if r["limit"] is None:
            print(f"  {r['department']:<15} no budget set (spent ${r['spent']:.4f} this month)")
            continue
        flag = {"ok": "", "warning": "  << WARNING: over 80%", "exceeded": "  << BLOCKED: budget used up"}[r["state"]]
        print(f"  {r['department']:<15} ${r['spent']:.4f} of ${r['limit']:.2f} ({r['percent']}%), "
              f"${r['remaining']:.4f} left{flag}")


def show_rules() -> None:
    for rule, action in security.get_rule_actions().items():
        note = "" if action == security.DEFAULTS[rule] else f"  (default: {security.DEFAULTS[rule]})"
        print(f"  {rule:<12} {action}{note}")


def set_rule() -> None:
    show_rules()
    rule = ask("Rule to change: ").lower()
    if not rule:
        return
    action = ask("New action - mask, block or off: ").lower()
    security.set_rule_action(rule, action)
    print(f"Rule '{rule}' is now '{action}'.")


def show_audit() -> None:
    rows = security.recent_audit(20)
    if not rows:
        print("Nothing caught yet.")
    for r in rows:
        print(f"  #{r['id']} {r['created_at'][:19]} | {r['user_name'] or '-'} ({r['department'] or '-'}) | "
              f"{r['rule']} x{r['match_count']} | {r['action'].upper()} | {r['provider']}")


MENU = [
    ("Create a user (and give them a key)", new_user),
    ("Create another key for a user", new_key),
    ("List users and departments", list_all),
    ("Revoke a key", revoke),
    ("Disable / enable a user", toggle),
    ("Show recent requests", show_log),
    ("Allow / block a provider for a department", set_access),
    ("Show who may use what", show_access),
    ("Lost a key? Replace a user's key", replace_key),
    ("Set a monthly budget for a department", set_budget),
    ("Show budgets (spent / left)", show_budgets),
    ("Show security filter rules", show_rules),
    ("Change a security rule (mask / block / off)", set_rule),
    ("Show security audit log", show_audit),
]


def main() -> int:
    init_db()
    while True:
        print("\n=== Yant Guard admin ===")
        for i, (label, _) in enumerate(MENU, 1):
            print(f" {i}. {label}")
        print(" 0. Quit")
        choice = ask("Choose: ")
        if choice in ("0", "q", ""):
            return 0
        if not choice.isdigit() or not 1 <= int(choice) <= len(MENU):
            print("Please type a number from the menu.")
            continue
        try:
            MENU[int(choice) - 1][1]()
        except users.GovernanceError as exc:
            print(f"Error: {exc}")
        except (EOFError, KeyboardInterrupt):
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
