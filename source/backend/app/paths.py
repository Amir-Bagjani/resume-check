"""Frozen/dev path resolution + writable user dirs. No new deps."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent.parent.parent


def frontend_dir() -> Path:
    cand = bundle_dir() / "frontend"
    if cand.is_dir():
        return cand
    return Path(__file__).resolve().parent.parent.parent / "frontend"


def user_data_dir() -> Path:
    home = Path.home()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        d = base / "ResumeCheck"
    elif sys.platform == "darwin":
        d = home / "Library" / "Application Support" / "ResumeCheck"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
        d = base / "resume-check"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def instance_file() -> Path:
    return user_data_dir() / "instance.json"
