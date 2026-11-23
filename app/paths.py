"""Where Yant Guard keeps its files.

Running from the source folder: <repo>/data (as always).
Running as the packaged Windows app: %LOCALAPPDATA%\\YantGuard\\data, because the
program folder may be read-only or temporary. Set YANTGUARD_HOME to choose another place.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_home() -> Path:
    override = os.getenv("YANTGUARD_HOME")
    if override:
        return Path(override)
    if is_frozen():
        return Path(os.getenv("LOCALAPPDATA") or Path.home()) / "YantGuard"
    return REPO_ROOT


def data_dir() -> Path:
    return app_home() / "data"
