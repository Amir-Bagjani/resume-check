"""Shared pytest hooks: report a stalled session instead of hanging forever.

On Windows a leftover background thread can deadlock pytest while it writes its
final summary (concurrent writes to the captured terminal). This watchdog turns
an invisible stall into a readable thread dump and a failed run. Set
``stallwatch_seconds`` (pytest -o) to tune or disable it with 0.
"""
from __future__ import annotations

import faulthandler
import sys
import threading

DEFAULT_STALL_SECONDS = 90


def pytest_addoption(parser):
    parser.addini("stallwatch_seconds", "Dump thread stacks and exit if the session stalls",
                  default=str(DEFAULT_STALL_SECONDS))


def pytest_sessionfinish(session, exitstatus):
    try:
        seconds = float(session.config.getini("stallwatch_seconds"))
    except (ValueError, TypeError):
        seconds = float(DEFAULT_STALL_SECONDS)
    if seconds <= 0:
        return
    # Armed only once the run is over, so a slow machine is never interrupted.
    faulthandler.dump_traceback_later(seconds, exit=True, file=sys.stderr)
    # The dump is timer based, so something must keep the process alive until it fires.
    threading.Thread(target=lambda: threading.Event().wait(seconds + 5), daemon=True).start()