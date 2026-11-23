import importlib.util
import socket
import sys
import urllib.request
from pathlib import Path

from app import paths

ROOT = Path(__file__).resolve().parents[1]


def load_desktop():
    spec = importlib.util.spec_from_file_location("yantguard_desktop", ROOT / "desktop" / "yantguard_desktop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_data_dir_from_source_is_repo_data(monkeypatch):
    monkeypatch.delenv("YANTGUARD_HOME", raising=False)
    assert paths.data_dir() == ROOT / "data"


def test_data_dir_when_packaged_is_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv("YANTGUARD_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths.data_dir() == tmp_path / "YantGuard" / "data"


def test_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("YANTGUARD_HOME", str(tmp_path))
    assert paths.data_dir() == tmp_path / "data"


def test_pick_port_prefers_8000_but_falls_back():
    d = load_desktop()
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        assert d.pick_port(taken) != taken
    assert isinstance(d.pick_port(), int)


def test_server_starts_and_serves_dashboard():
    d = load_desktop()
    port = d.pick_port(0)
    server = d.start_server(port)
    try:
        assert d.wait_until_ready(port, timeout=20)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/dashboard", timeout=5) as r:
            assert r.status == 200 and b"Yant Guard" in r.read()
    finally:
        server.should_exit = True


def test_env_file_is_loaded(monkeypatch, tmp_path):
    d = load_desktop()
    (tmp_path / ".env").write_text("YG_TEST_SETTING=hello\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YG_TEST_SETTING", raising=False)
    d.load_env()
    import os
    assert os.getenv("YG_TEST_SETTING") == "hello"
    monkeypatch.delenv("YG_TEST_SETTING", raising=False)
