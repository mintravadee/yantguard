import pytest
from fastapi.testclient import TestClient

from app.dashboard import routes
from app.gateway import groq_client
from app.governance import admins, users
from app.main import app

API = "/dashboard/api"


@pytest.fixture(autouse=True)
def clean_rate_limit():
    routes._fails.clear()


def new_client(host="127.0.0.1"):
    return TestClient(app, client=(host, 50000))


def login(c, user="boss", pw="correct horse"):
    return c.post(f"{API}/login", json={"username": user, "password": pw})


# ------------------------------------------------------------ passwords and sessions
def test_password_hash_is_salted_and_checkable():
    a, b = admins.hash_password("secret-pass"), admins.hash_password("secret-pass")
    assert a != b and "secret-pass" not in a
    assert admins.check_password("secret-pass", a) and not admins.check_password("nope", a)
    assert not admins.check_password("x", "garbage")


def test_create_admin_rules():
    with pytest.raises(users.GovernanceError):
        admins.create_admin("ab", "long enough pw")      # name too short
    with pytest.raises(users.GovernanceError):
        admins.create_admin("boss", "short")            # password too short
    admins.create_admin("boss", "long enough pw")
    with pytest.raises(users.GovernanceError):
        admins.create_admin("boss", "another long pw")  # duplicate


# ------------------------------------------------------------ first-run setup
def test_session_info_before_and_after_setup():
    c = new_client()
    assert c.get(f"{API}/session").json() == {"authenticated": False, "username": None, "setup_needed": True}
    r = c.post(f"{API}/setup", json={"username": "boss", "password": "correct horse"})
    assert r.status_code == 200
    assert c.get(f"{API}/session").json() == {"authenticated": True, "username": "boss", "setup_needed": False}


def test_setup_only_from_this_computer_and_only_once():
    other = new_client("203.0.113.9")
    assert other.post(f"{API}/setup", json={"username": "boss", "password": "correct horse"}).status_code == 403
    assert admins.admin_count() == 0
    c = new_client()
    assert c.post(f"{API}/setup", json={"username": "boss", "password": "correct horse"}).status_code == 200
    assert new_client().post(f"{API}/setup", json={"username": "evil", "password": "another long pw"}).status_code == 409


def test_setup_rejects_weak_password():
    r = new_client().post(f"{API}/setup", json={"username": "boss", "password": "short"})
    assert r.status_code == 400 and "at least 8" in r.json()["detail"]


# ------------------------------------------------------------ login / logout
def test_protected_things_need_a_session():
    admins.create_admin("boss", "correct horse")
    c = new_client()
    for path in ("/summary", "/manage"):
        assert c.get(API + path).status_code == 401
    assert c.post(f"{API}/departments", json={"name": "X"}).status_code == 401
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/login"
    assert c.get("/dashboard/login").status_code == 200


def test_login_success_sets_a_safe_cookie_and_logout_ends_it():
    admins.create_admin("boss", "correct horse")
    c = new_client()
    r = login(c)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get(f"{API}/summary").status_code == 200
    assert c.post(f"{API}/logout").status_code == 200
    assert c.get(f"{API}/summary").status_code == 401


def test_wrong_credentials_get_the_same_answer():
    admins.create_admin("boss", "correct horse")
    c = new_client()
    a = login(c, "boss", "wrong password")
    b = login(c, "nobody", "whatever password")
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_login_is_rate_limited():
    admins.create_admin("boss", "correct horse")
    c = new_client()
    for _ in range(routes.MAX_FAILS):
        assert login(c, "boss", "bad password").status_code == 401
    assert login(c).status_code == 429  # even the right password waits
    assert new_client("198.51.100.7").post(f"{API}/login", json={"username": "boss", "password": "correct horse"}).status_code == 200


def test_session_cookie_is_not_the_stored_token():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    token = c.cookies.get(routes.COOKIE)
    from app.governance.db import get_conn
    with get_conn() as conn:
        stored = conn.execute("SELECT token_hash FROM admin_sessions").fetchone()[0]
    assert token and token != stored


def test_expired_session_is_refused():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    from app.governance.db import get_conn
    with get_conn() as conn:
        conn.execute("UPDATE admin_sessions SET expires_at = '2000-01-01T00:00:00.000Z'")
    assert c.get(f"{API}/summary").status_code == 401


def test_cross_site_post_is_refused():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    r = c.post(f"{API}/departments", json={"name": "Evil"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert c.post(f"{API}/departments", json={"name": "Good"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_form_posts_are_refused():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    assert c.post(f"{API}/departments", data={"name": "X"}).status_code == 422  # JSON only


# ------------------------------------------------------------ change password
def test_change_password_signs_out_other_sessions():
    admins.create_admin("boss", "correct horse")
    a, b = new_client(), new_client()
    login(a); login(b)
    r = a.post(f"{API}/password", json={"old_password": "correct horse", "new_password": "brand new pass"})
    assert r.status_code == 200
    assert a.get(f"{API}/summary").status_code == 200   # this session stays
    assert b.get(f"{API}/summary").status_code == 401   # the other one is gone
    assert login(new_client(), pw="correct horse").status_code == 401
    assert login(new_client(), pw="brand new pass").status_code == 200


def test_change_password_needs_the_old_one():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    r = c.post(f"{API}/password", json={"old_password": "wrong", "new_password": "brand new pass"})
    assert r.status_code == 400 and "wrong" in r.json()["detail"]


# ------------------------------------------------------------ management
@pytest.fixture
def admin():
    admins.create_admin("boss", "correct horse")
    c = new_client(); login(c)
    return c


def test_manage_departments_users_keys(admin, monkeypatch):
    assert admin.post(f"{API}/departments", json={"name": "Eng"}).status_code == 200
    assert admin.post(f"{API}/departments", json={"name": "Eng"}).status_code == 400  # duplicate
    r = admin.post(f"{API}/users", json={"name": "alice", "department": "Eng"})
    key = r.json()["key"]
    assert r.status_code == 200 and key.startswith("yg-")
    assert users.authenticate(key)["user"] == "alice"
    assert admin.post(f"{API}/users", json={"name": "bob", "department": "Nope"}).status_code == 400

    new = admin.post(f"{API}/users/alice/keys", json={"replace": True}).json()["key"]
    assert users.authenticate(key) is None and users.authenticate(new)["user"] == "alice"
    prefix = new[:10]
    assert admin.post(f"{API}/keys/revoke", json={"prefix": prefix}).json()["revoked"] == 1
    assert users.authenticate(new) is None

    assert admin.post(f"{API}/users/alice/active", json={"active": False}).status_code == 200
    d = admin.get(f"{API}/manage").json()
    assert d["users"][0]["active"] == 0 and d["departments"][0]["name"] == "Eng"
    assert admin.post(f"{API}/users/ghost/active", json={"active": False}).status_code == 400


def test_manage_access_budget_rules(admin):
    admin.post(f"{API}/departments", json={"name": "Eng"})
    assert admin.post(f"{API}/access", json={"department": "Eng", "provider": "groq", "allowed": True}).status_code == 200
    assert users.is_provider_allowed("Eng", "groq")
    admin.post(f"{API}/access", json={"department": "Eng", "provider": "groq", "allowed": False})
    assert not users.is_provider_allowed("Eng", "groq")
    assert admin.post(f"{API}/access", json={"department": "Eng", "provider": "bing", "allowed": True}).status_code == 400

    assert admin.post(f"{API}/budgets", json={"department": "Eng", "monthly_limit_usd": 5}).status_code == 200
    assert admin.get(f"{API}/manage").json()["departments"][0]["budget"] == 5
    admin.post(f"{API}/budgets", json={"department": "Eng", "monthly_limit_usd": None})
    assert admin.get(f"{API}/manage").json()["departments"][0]["budget"] is None
    assert admin.post(f"{API}/budgets", json={"department": "Eng", "monthly_limit_usd": -1}).status_code == 422

    assert admin.post(f"{API}/rules", json={"rule": "email", "action": "block"}).status_code == 200
    assert admin.get(f"{API}/manage").json()["rules"]["email"] == "block"
    assert admin.post(f"{API}/rules", json={"rule": "email", "action": "explode"}).status_code == 400


def test_changes_made_in_the_dashboard_take_effect_in_the_gateway(admin, monkeypatch):
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "true")
    monkeypatch.setenv("GROQ_API_KEY", "k")

    async def fake(prompt):
        return {"provider": "groq", "model": "m", "answer": "hi",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    monkeypatch.setattr(groq_client, "generate", fake)

    admin.post(f"{API}/departments", json={"name": "Eng"})
    key = admin.post(f"{API}/users", json={"name": "alice", "department": "Eng"}).json()["key"]
    gw = TestClient(app)
    call = lambda: gw.post("/api/gateway/request", json={"provider": "groq", "prompt": "hi"}, headers={"X-API-Key": key})
    assert call().status_code == 403                                   # nothing allowed yet
    admin.post(f"{API}/access", json={"department": "Eng", "provider": "groq", "allowed": True})
    assert call().status_code == 200
    admin.post(f"{API}/users/alice/active", json={"active": False})
    assert call().status_code == 401


def test_admin_activity_is_logged_without_secrets(admin):
    admin.post(f"{API}/departments", json={"name": "Eng"})
    key = admin.post(f"{API}/users", json={"name": "alice", "department": "Eng"}).json()["key"]
    actions = admins.recent_actions(20)
    assert {"signed in", "added department", "added user"} <= {a["action"] for a in actions}
    assert key not in str(actions) and "correct horse" not in str(actions)
