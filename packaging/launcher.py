"""Standalone launcher: single instance, pre-bound socket, health wait, browser, clean exit."""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HEALTH_PATH = "/api/health"
START_TIMEOUT = 30.0
STARTUP_WAIT = 8.0

for _stream in (sys.stdout, sys.stderr):
    # The Windows console defaults to a legacy code page: Persian log lines
    # from the bundled server would crash with UnicodeEncodeError otherwise.
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
del _stream

if getattr(sys, "frozen", False):
    _BASE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    _SRC = Path(__file__).resolve().parent.parent / "source"
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    _BASE = _SRC


def _paths():
    from backend.app.paths import instance_file, log_dir

    return instance_file(), log_dir()


def _log_file() -> Path:
    _, logs = _paths()
    return logs / "server.log"


def _log(msg: str) -> None:
    try:
        with open(_log_file(), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _health_ok(port: int) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=2) as r:
            return r.status == 200 and json.load(r).get("status") == "ok"
    except Exception:
        return False


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not usable on Windows; ask the kernel instead.
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(0x00100000, False, pid)
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT: still running
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


HEADLESS = os.environ.get("RESUMECHECK_HEADLESS", "").strip().lower() in ("1", "true", "yes")


def _read_instance(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _reuse_running(path: Path) -> str | None:
    """URL of a live instance, else None. Waits briefly if one is still starting."""
    data = _read_instance(path)
    if not data:
        return None
    port, pid = data.get("port"), data.get("pid")
    url = f"http://127.0.0.1:{port}/" if isinstance(port, int) else None
    if url and _health_ok(port):
        return url
    if isinstance(pid, int) and _pid_alive(pid) and url:
        deadline = time.time() + STARTUP_WAIT
        while time.time() < deadline:
            if _health_ok(port):
                return url
            if not _pid_alive(pid):
                break
            time.sleep(0.5)
        return url if _health_ok(port) else None
    try:
        path.unlink()
    except OSError:
        pass
    return None


def _claim_instance(path: Path, port: int) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps({"port": port, "pid": os.getpid()}))
        return True
    except OSError:
        return False


def _open_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception as exc:
        _log(f"browser open failed: {exc}")
        return False


def _bind_free() -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    option = socket.SO_EXCLUSIVEADDRUSE if os.name == "nt" else socket.SO_REUSEADDR
    sock.setsockopt(socket.SOL_SOCKET, option, 1)
    sock.bind(("127.0.0.1", 0))
    return sock, int(sock.getsockname()[1])


_SERVER: dict = {"obj": None, "thread": None, "owner": False}
_CONSOLE: dict = {"out": sys.stdout, "err": sys.stderr}


def _start_server(sock: socket.socket, port: int):
    from backend.app.main import app
    import uvicorn

    with open(_log_file(), "a", encoding="utf-8") as lf:
        sys.stdout = lf
        sys.stderr = lf
        backend_logger = logging.getLogger("backend")
        handler = logging.StreamHandler(lf)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        backend_logger.setLevel(logging.INFO)
        backend_logger.addHandler(handler)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
        server = uvicorn.Server(config)
        _SERVER["obj"] = server
        try:
            server.run(sockets=[sock])
        finally:
            backend_logger.removeHandler(handler)


def _stop_own_server() -> None:
    server = _SERVER.get("obj")
    if server is not None:
        server.should_exit = True
    thread = _SERVER.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=10)


def _wait_healthy(port: int) -> bool:
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        thread = _SERVER.get("thread")
        if _SERVER.get("obj") is None and (thread is None or not thread.is_alive()):
            if time.time() > deadline - START_TIMEOUT + 3:
                return False
        if _health_ok(port):
            return True
        time.sleep(0.25)
    return _health_ok(port)


def _install_sigterm(root=None) -> None:
    def _handle(signum, frame):
        _log(f"signal {signum}; shutting down")
        server = _SERVER.get("obj")
        if server is not None:
            server.should_exit = True
        if root is not None:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    try:
        signal.signal(signal.SIGTERM, _handle)
    except Exception:
        pass


def _show_gui(url: str, browser_ok: bool) -> None:
    try:
        import tkinter as tk
    except Exception:
        _console_loop(url)
        return

    try:
        root = tk.Tk()
    except Exception as exc:
        _log(f"tk init failed: {exc}")
        _console_loop(url)
        return

    _install_sigterm(root)
    root.title("ResumeCheck — غربالگری رزومه")
    root.resizable(False, False)
    tk.Label(root, text="برنامه در حال اجراست", font=("", 13, "bold")).pack(padx=24, pady=(16, 4))
    tk.Label(root, text="این پنجره را باز نگه دارید. بستن تب مرورگر برنامه را متوقف نمی‌کند.").pack(padx=24)
    row = tk.Frame(root)
    row.pack(padx=24, pady=8, fill="x")
    entry = tk.Entry(row, width=40, justify="center")
    entry.insert(0, url)
    entry.config(state="readonly")
    entry.pack(side="left", expand=True, fill="x")
    tk.Button(row, text="کپی", command=lambda: (root.clipboard_clear(), root.clipboard_append(url))).pack(
        side="left", padx=(8, 0)
    )
    if not browser_ok:
        tk.Label(root, text="مرورگر خودکار باز نشد — نشانی بالا را در مرورگر وارد کنید.").pack()
    btns = tk.Frame(root)
    btns.pack(pady=(4, 16))
    tk.Button(btns, text="باز کردن در مرورگر", command=lambda: _open_browser(url)).pack(side="left", padx=4)
    tk.Button(btns, text="خروج از برنامه", command=lambda: _quit(root)).pack(side="left", padx=4)
    root.protocol("WM_DELETE_WINDOW", lambda: _quit(root))
    root.mainloop()


def _quit(root=None) -> None:
    _stop_own_server()
    if _SERVER.get("owner"):
        path, _ = _paths()
        try:
            path.unlink()
        except OSError:
            pass
    if root is not None:
        try:
            root.destroy()
        except Exception:
            pass
    else:
        raise SystemExit(0)


def _console_loop(url: str) -> None:
    _install_sigterm()
    out = _CONSOLE.get("out") or sys.stdout
    try:
        print(f"ResumeCheck: {url}", file=out, flush=True)
        print("Press Ctrl+C to stop.", file=out, flush=True)
    except Exception:
        pass
    try:
        while True:
            thread = _SERVER.get("thread")
            if thread is None or not thread.is_alive():
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    _quit()


def _fatal(msg: str) -> int:
    _log(f"FATAL: {msg}")
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("ResumeCheck — خطا", f"{msg}\n\nجزئیات در فایل گزارش ثبت شد:\n{_log_file()}")
        r.destroy()
    except Exception:
        try:
            print(f"ResumeCheck error: {msg}\nLog: {_log_file()}", file=_CONSOLE.get("err") or sys.stderr)
        except Exception:
            pass
    return 1


def main() -> int:
    multiprocessing.freeze_support()
    inst_path, _ = _paths()
    existing = _reuse_running(inst_path)
    if existing:
        _open_browser(existing)
        return 0

    try:
        sock, port = _bind_free()
    except OSError as exc:
        return _fatal(f"امکان رزرو پورت محلی وجود ندارد ({exc}).")

    thread = threading.Thread(target=_start_server, args=(sock, port), name="rc-server", daemon=True)
    _SERVER["thread"] = thread
    thread.start()

    if not _wait_healthy(port):
        logs = ""
        try:
            logs = _log_file().read_text(encoding="utf-8", errors="replace")[-1500:]
        except OSError:
            pass
        _log(f"startup failed, last log:\n{logs}")
        _stop_own_server()
        return _fatal("سرویس داخلی اجرا نشد. لطفاً دوباره تلاش کنید.")

    if not _claim_instance(inst_path, port):
        reused = _reuse_running(inst_path)
        if reused:
            _stop_own_server()
            _open_browser(reused)
            return 0
        data = _read_instance(inst_path)
        if data and isinstance(data.get("pid"), int) and _pid_alive(data["pid"]):
            _stop_own_server()
            return _fatal("نسخه دیگری از برنامه پاسخ نمی‌دهد. آن را ببندید و دوباره تلاش کنید.")
        try:
            inst_path.unlink()
        except OSError:
            pass
        if not _claim_instance(inst_path, port):
            _stop_own_server()
            return _fatal("امکان ثبت نمونه برنامه وجود ندارد.")
    _SERVER["owner"] = True

    url = f"http://127.0.0.1:{port}/"
    browser_ok = False if HEADLESS else _open_browser(url)
    if HEADLESS:
        # CI smoke-test mode: stay alive serving until SIGTERM/Ctrl+C,
        # then clean up the instance file like the GUI exit path.
        _install_sigterm()
        thread.join()
        if _SERVER.get("owner"):
            try:
                inst_path.unlink()
            except OSError:
                pass
        return 0
    _show_gui(url, browser_ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
