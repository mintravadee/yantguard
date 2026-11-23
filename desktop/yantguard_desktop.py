r"""Yant Guard desktop app: starts the gateway in the background and shows the
dashboard in its own window (pywebview). Run from source with scripts\run_desktop.bat,
or build YantGuard.exe with scripts\build_desktop.bat.

  YantGuard.exe --admin     opens the admin menu (users, keys, budgets, security rules)
  YantGuard.exe --browser   use the normal web browser instead of the app window
"""
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# Make "import app" work when started from source (desktop/ is not the repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paths import app_home, data_dir, is_frozen  # noqa: E402

TITLE = "Yant Guard"


def setup_logging() -> Path:
    """A windowed .exe has no console (stdout is None), so log to a file."""
    data_dir().mkdir(parents=True, exist_ok=True)
    log_file = data_dir() / "yantguard.log"
    logging.basicConfig(filename=log_file, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = open(log_file, "a", buffering=1, encoding="utf-8")
    return log_file


def load_env() -> None:
    """Read provider keys from .env next to the app, in the data folder, or in the repo."""
    from dotenv import load_dotenv
    candidates = [Path.cwd() / ".env", data_dir() / ".env", app_home() / ".env"]
    if is_frozen():
        candidates.insert(0, Path(sys.executable).parent / ".env")
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            load_dotenv(path)
            logging.info("Loaded settings from %s", path)
            return
    logging.warning("No .env found. Put GEMINI_API_KEY / GROQ_API_KEY in %s", data_dir() / ".env")


def pick_port(preferred: int = 8000) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free network port.")


def start_server(port: int):
    import uvicorn
    from app.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="yantguard-server", daemon=True).start()
    return server


def wait_until_ready(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def attach_console() -> None:
    """Give the windowed .exe a console window for --admin (Windows only)."""
    if sys.platform == "win32" and is_frozen():
        import ctypes
        ctypes.windll.kernel32.AllocConsole()
        sys.stdin = open("CONIN$", "r")
        sys.stdout = open("CONOUT$", "w", buffering=1)
        sys.stderr = sys.stdout


def show_error(message: str) -> None:
    logging.error(message)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, TITLE, 0x10)
    else:
        print(message, file=sys.stderr)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--admin" in argv:
        attach_console()
        load_env()
        from scripts import admin_menu
        code = admin_menu.main()
        if is_frozen():
            input("\nPress Enter to close this window.")
        return code

    log_file = setup_logging()
    load_env()
    port = pick_port()
    server = start_server(port)
    if not wait_until_ready(port):
        show_error(f"The Yant Guard server did not start. Details: {log_file}")
        return 1
    url = f"http://127.0.0.1:{port}/dashboard"
    logging.info("Server ready at %s", url)

    try:
        if "--browser" in argv:
            raise ImportError("--browser requested")
        import webview
        webview.create_window(TITLE, url, width=1280, height=840, min_size=(900, 600))
        webview.start()  # returns when the window is closed
    except Exception as exc:
        logging.warning("App window not available (%s). Opening the browser instead.", exc)
        import webbrowser
        webbrowser.open(url)
        print(f"Yant Guard is running at {url}. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    server.should_exit = True
    time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
