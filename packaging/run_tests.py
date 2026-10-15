"""Run a pytest selection with a hard, cross-platform time limit.

GitHub Actions must never wait forever on a stuck test process. This wrapper
starts pytest in its own process group, forwards its output unbuffered, and on
timeout kills the whole tree (Windows: taskkill /T /F, POSIX: SIGKILL to the
group) and prints the tail of what pytest produced so the failing test is
visible. No third-party dependency.

    python packaging/run_tests.py <timeout-seconds> <pytest arguments...>
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

TAIL_LINES = 40


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    timeout = float(sys.argv[1])
    arguments = sys.argv[2:]
    # Accept both `run_tests.py 60 -m pytest x` and `run_tests.py 60 python -m pytest x`.
    while arguments and arguments[0] in ("python", "python3", "py", "-m", "pytest"):
        arguments.pop(0)
    command = [sys.executable, "-m", "pytest", *arguments]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    if os.name != "nt":
        env.pop("PYTHONFAULTHANDLER", None)

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
        start_new_session=os.name != "nt",
    )
    tail: list[str] = []

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            tail.append(line.rstrip("\n"))
            del tail[:-TAIL_LINES]

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if process.poll() is None:
        print(f"\nTIMEOUT after {timeout:.0f}s: killing pytest and its children", flush=True)
        _kill_tree(process)
        reader.join(timeout=10)
        print("---- last output ----", flush=True)
        for line in tail:
            print(line, flush=True)
        print("---------------------", flush=True)
        return 124
    reader.join(timeout=10)
    return process.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())