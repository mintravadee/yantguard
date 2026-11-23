"""The dashboard and admin console, served by the gateway under /dashboard.

  /dashboard/login        sign-in page (first run: create the admin account)
  /dashboard              the dashboard + management page (needs a session)
  /dashboard/api/...      JSON for the page; everything except login/setup needs a session

Security: PBKDF2 passwords, HttpOnly + SameSite=Strict session cookie, JSON-only POSTs,
Origin check, login rate limit, strict Content-Security-Policy. The server listens on
127.0.0.1 only, so other computers cannot reach it.
"""
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.governance import admins, analytics, budgets, security, users
from app.governance.users import GovernanceError

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "yg_session"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
FILES = {
    "dashboard.css": "text/css; charset=utf-8",
    "dashboard.js": "text/javascript; charset=utf-8",
    "login.js": "text/javascript; charset=utf-8",
}
# No inline scripts or styles, nothing loaded from other sites.
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
HEADERS = {"Content-Security-Policy": CSP, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

# ---------------------------------------------------------------- login rate limit
MAX_FAILS, WINDOW_SECONDS = 5, 300
_fails: dict = {}


def _blocked(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < WINDOW_SECONDS]
    return len(_fails[ip]) >= MAX_FAILS


# ---------------------------------------------------------------- dependencies
def current_admin(request: Request) -> dict:
    admin = admins.session_admin(request.cookies.get(COOKIE))
    if admin is None:
        raise HTTPException(401, "Please sign in.")
    return admin


def same_origin(request: Request) -> None:
    """Browsers send Origin on POSTs; refuse ones that come from another site."""
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host", ""):
        raise HTTPException(403, "Cross-site request refused.")


router = APIRouter(prefix="/dashboard", include_in_schema=False)
api = APIRouter(prefix="/dashboard/api", include_in_schema=False, dependencies=[Depends(same_origin)])
protected = APIRouter(dependencies=[Depends(current_admin)])


def _html(name: str) -> HTMLResponse:
    return HTMLResponse((STATIC / name).read_text("utf-8"), headers=HEADERS)


# ---------------------------------------------------------------- pages and files
@router.get("")
@router.get("/")
def dashboard_page(request: Request):
    if admins.session_admin(request.cookies.get(COOKIE)) is None:
        return RedirectResponse("/dashboard/login", status_code=303)
    return _html("index.html")


@router.get("/login")
def login_page():
    return _html("login.html")


@router.get("/static/{name}")
def dashboard_file(name: str):
    media = FILES.get(name)
    if media is None:
        raise HTTPException(404, "Not found")
    return Response((STATIC / name).read_bytes(), media_type=media, headers=HEADERS)


# ---------------------------------------------------------------- session
class Credentials(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=300)


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=300)
    new_password: str = Field(max_length=300)


def _set_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=admins.SESSION_HOURS * 3600, httponly=True,
                        samesite="strict", secure=request.url.scheme == "https", path="/")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@api.get("/session")
def session_info(request: Request):
    admin = admins.session_admin(request.cookies.get(COOKIE))
    return {"authenticated": admin is not None, "username": admin["username"] if admin else None,
            "setup_needed": admins.admin_count() == 0}


@api.post("/setup")
def setup(body: Credentials, request: Request, response: Response):
    """Create the first admin. Only while there is none, and only from this computer."""
    if admins.admin_count() > 0:
        raise HTTPException(409, "An admin already exists. Please sign in.")
    if _ip(request) not in LOOPBACK:
        raise HTTPException(403, "The first admin can only be created on the computer that runs Yant Guard.")
    try:
        admin_id = admins.create_admin(body.username, body.password)
    except GovernanceError as exc:
        raise HTTPException(400, str(exc)) from None
    admins.log_action(body.username.strip(), "admin account created")
    _set_cookie(response, request, admins.create_session(admin_id))
    return {"ok": True, "username": body.username.strip()}


@api.post("/login")
def login(body: Credentials, request: Request, response: Response):
    ip = _ip(request)
    if _blocked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")
    admin = admins.authenticate_admin(body.username, body.password)
    if admin is None:
        _fails.setdefault(ip, []).append(time.time())
        admins.log_action(None, "login failed", f"user '{body.username.strip()[:40]}'")
        raise HTTPException(401, "Wrong username or password.")
    _fails.pop(ip, None)
    admins.log_action(admin["username"], "signed in")
    _set_cookie(response, request, admins.create_session(admin["id"]))
    return {"ok": True, "username": admin["username"]}


@api.post("/logout")
def logout(request: Request, response: Response):
    admins.end_session(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@protected.post("/password")
def change_password(body: PasswordChange, request: Request, admin: dict = Depends(current_admin)):
    try:
        admins.change_password(admin["id"], body.old_password, body.new_password, request.cookies.get(COOKIE))
    except GovernanceError as exc:
        raise HTTPException(400, str(exc)) from None
    admins.log_action(admin["username"], "changed own password")
    return {"ok": True}


# ---------------------------------------------------------------- numbers
@protected.get("/summary")
def summary(days: int = Query(30, ge=1, le=365)):
    return {
        "days": days,
        "kpis": analytics.kpis(days),
        "budgets": budgets.all_budget_status(),
        "daily": analytics.daily(days),
        "by_department": analytics.by_department(days),
        "by_user": analytics.by_user(days, limit=15),
        "by_model": analytics.by_model(days),
        "outcomes": analytics.outcomes(days),
        "security": analytics.security_summary(days),
        "rules": security.get_rule_actions(),
        "audit": security.recent_audit(20),
        "requests": analytics.recent_requests(100),
    }


# ---------------------------------------------------------------- management
class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    department: str = Field(min_length=1, max_length=60)


class KeyIn(BaseModel):
    replace: bool = False


class PrefixIn(BaseModel):
    prefix: str = Field(min_length=3, max_length=20)


class ActiveIn(BaseModel):
    active: bool


class AccessIn(BaseModel):
    department: str = Field(max_length=60)
    provider: str = Field(max_length=30)
    allowed: bool


class BudgetIn(BaseModel):
    department: str = Field(max_length=60)
    monthly_limit_usd: float | None = Field(default=None, ge=0, le=1e9)  # null or 0 removes the limit


class RuleIn(BaseModel):
    rule: str = Field(max_length=40)
    action: str = Field(max_length=10)


def _run(admin: dict, action: str, detail: str, fn):
    """Run a management change, turn friendly errors into HTTP 400 and log who did it."""
    try:
        result = fn()
    except GovernanceError as exc:
        raise HTTPException(400, str(exc)) from None
    admins.log_action(admin["username"], action, detail)
    return result


@protected.get("/manage")
def manage_overview():
    perms = {r["department"]: r["providers"] for r in users.list_permissions()}
    status = {b["department"]: b for b in budgets.all_budget_status()}
    return {
        "providers": list(users.KNOWN_PROVIDERS),
        "departments": [{"name": n, "providers": perms[n], "budget": status[n]["limit"],
                         "spent": status[n]["spent"], "state": status[n]["state"]} for n in perms],
        "users": users.list_users(),
        "rules": security.get_rule_actions(),
        "actions": admins.recent_actions(20),
    }


@protected.post("/departments")
def add_department(body: DepartmentIn, admin: dict = Depends(current_admin)):
    _run(admin, "added department", body.name, lambda: users.create_department(body.name))
    return {"ok": True}


@protected.post("/users")
def add_user(body: UserIn, admin: dict = Depends(current_admin)):
    def make():
        users.create_user(body.name, body.department)
        return users.create_api_key(body.name.strip())
    key = _run(admin, "added user", f"{body.name.strip()} ({body.department})", make)
    return {"ok": True, "user": body.name.strip(), "key": key}


@protected.post("/users/{name}/keys")
def new_key(name: str, body: KeyIn, admin: dict = Depends(current_admin)):
    def make():
        if body.replace:
            row = next((r for r in users.list_users() if r["user"] == name), None)
            if row is None:
                raise GovernanceError(f"Unknown user '{name}'.")
            for prefix in [p.strip() for p in (row["key_prefixes"] or "").split(",") if p.strip()]:
                users.revoke_key(prefix)
        return users.create_api_key(name)
    key = _run(admin, "replaced key" if body.replace else "created key", name, make)
    return {"ok": True, "user": name, "key": key}


@protected.post("/keys/revoke")
def revoke_key(body: PrefixIn, admin: dict = Depends(current_admin)):
    count = _run(admin, "revoked key", body.prefix, lambda: users.revoke_key(body.prefix))
    return {"ok": True, "revoked": count}


@protected.post("/users/{name}/active")
def set_active(name: str, body: ActiveIn, admin: dict = Depends(current_admin)):
    _run(admin, "enabled user" if body.active else "disabled user", name,
         lambda: users.set_user_active(name, body.active))
    return {"ok": True}


@protected.post("/access")
def set_access(body: AccessIn, admin: dict = Depends(current_admin)):
    fn = users.grant_provider if body.allowed else users.revoke_provider
    _run(admin, "allowed provider" if body.allowed else "blocked provider",
         f"{body.department}: {body.provider}", lambda: fn(body.department, body.provider))
    return {"ok": True}


@protected.post("/budgets")
def set_budget(body: BudgetIn, admin: dict = Depends(current_admin)):
    limit = body.monthly_limit_usd
    if not limit:
        _run(admin, "removed budget", body.department, lambda: budgets.clear_budget(body.department))
    else:
        _run(admin, "set budget", f"{body.department}: ${limit:.2f}", lambda: budgets.set_budget(body.department, limit))
    return {"ok": True}


@protected.post("/rules")
def set_rule(body: RuleIn, admin: dict = Depends(current_admin)):
    _run(admin, "changed security rule", f"{body.rule} -> {body.action}",
         lambda: security.set_rule_action(body.rule, body.action))
    return {"ok": True}


api.include_router(protected)
