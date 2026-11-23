import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test writes to its own temporary database."""
    monkeypatch.setenv("YANTGUARD_DB", str(tmp_path / "test.db"))


@pytest.fixture(autouse=True)
def keys_off_by_default(monkeypatch):
    """Older gateway tests send no key. Auth tests turn this back on."""
    monkeypatch.setenv("YANTGUARD_REQUIRE_KEY", "false")


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Real hashing takes ~0.3 s; tests use a cheap setting."""
    from app.governance import admins
    monkeypatch.setattr(admins, "ITERATIONS", 1000)
