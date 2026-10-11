"""Packaging-only tests: launcher helpers, frozen static serve, upload->viewer->excel."""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import time
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "packaging" / "launcher.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("rc_launcher", SPEC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_docx(path: Path, lines: list[str]):
    from docx import Document

    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    doc.save(path)


def test_health_static_and_fa_packaging_scenarios():
    from backend.app.main import app

    c = TestClient(app)
    assert c.get("/api/health").json() == {"status": "ok"}
    html = c.get("/").text
    assert "غربالگری رزومه" in html
    css = c.get("/styles.css")
    assert css.status_code == 200 and len(css.text) > 1000
    assert "webkitRelativePath" in c.get("/js/app_setup.js").text
    # hostile Host header rejected (loopback-only)
    r = c.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 403


def test_upload_viewer_excel_roundtrip(tmp_path: Path):
    import sys as _sys

    from backend.app import runner

    if "backend.app.runner" in _sys.modules:
        r = _sys.modules["backend.app.runner"]
    else:
        from backend.app import runner as r
    r._runs.clear()
    r._queues.clear()
    r._uploads.clear()
    r._output_files.clear()
    r._output_targets.clear()

    from backend.app.main import app

    c = TestClient(app)
    fa_dir = tmp_path / "رزومه ها"
    fa_dir.mkdir()
    cv = fa_dir / "رزومه فارسی.docx"
    _make_docx(cv, ["Test Candidate", "Over 7 years in software development.", "React Python"])

    with open(cv, "rb") as f:
        data = f.read()
    up = c.post("/api/uploads", files=[("files", ("batch/" + cv.name, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))])
    assert up.status_code == 200, up.text
    upload_id = up.json()["uploadId"]

    run = c.post(f"/api/uploads/{upload_id}/run", json={"criteria": {"minYears": 5, "keywords": ["React"]}, "outputFolder": None})
    assert run.status_code == 200, run.text
    run_id = run.json()["runId"]
    for _ in range(100):
        state = c.get(f"/api/runs/{run_id}").json()
        if state["state"] == "finished":
            break
        time.sleep(0.1)
    assert state["state"] == "finished"
    assert state["found"] >= 1

    fname = state["results"][0]["filename"]
    view = c.get(f"/api/runs/{run_id}/resumes/{fname}")
    assert view.status_code == 200
    xlsx = c.get(f"/api/runs/{run_id}/report")
    assert xlsx.status_code == 200
    assert xlsx.content[:2] == b"PK"
    # traversal blocked
    assert c.get(f"/api/runs/{run_id}/resumes/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_launcher_helpers_single_instance_and_port_bind(tmp_path: Path, monkeypatch):
    mod = _load_launcher()
    inst = tmp_path / "instance.json"
    monkeypatch.setattr(mod, "_paths", lambda: (inst, tmp_path))

    dead = {"port": 9, "pid": 999999}
    inst.write_text(json.dumps(dead), encoding="utf-8")
    assert mod._reuse_running(inst) is None
    assert not inst.exists()

    assert mod._claim_instance(inst, 8123) is True
    assert mod._claim_instance(inst, 8123) is False
    assert json.loads(inst.read_text(encoding="utf-8"))["port"] == 8123
    inst.unlink()

    sock, port = mod._bind_free()
    assert 1 <= port <= 65535
    clash = socket.socket()
    try:
        clash.bind(("127.0.0.1", port))
        reachable = False
    except OSError:
        reachable = True
    finally:
        clash.close()
        sock.close()
    assert reachable  # held port must refuse a second bind: no race at startup

    assert mod._pid_alive(-1) is False
    assert mod._pid_alive("nope") is False
    assert mod.HEADLESS in (True, False)


def test_spec_and_scripts_present():
    assert (ROOT / "packaging" / "resumecheck.spec").is_file()
    assert (ROOT / "packaging" / "build_windows.ps1").is_file()
    assert (ROOT / "packaging" / "build_macos.sh").is_file()
    assert (ROOT / "packaging" / "build_linux.sh").is_file()
    assert (ROOT / ".github" / "workflows" / "build.yml").is_file()
    spec_text = (ROOT / "packaging" / "resumecheck.spec").read_text(encoding="utf-8")
    assert "frontend" in spec_text and "launcher.py" in spec_text
    sys.modules.pop("rc_launcher", None)


@pytest.mark.parametrize("wait_result, alive", [(0x102, True), (0, False), (0xFFFFFFFF, False)])
def test_windows_pid_check_preserves_handle_and_checks_exit(monkeypatch, wait_result, alive):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace
    from unittest.mock import Mock

    mod = _load_launcher()
    handle = 0x100000001
    kernel = SimpleNamespace(
        OpenProcess=Mock(return_value=handle),
        WaitForSingleObject=Mock(return_value=wait_result),
        CloseHandle=Mock(),
    )
    monkeypatch.setattr(mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel), raising=False)
    assert mod._pid_alive(123) is alive
    assert kernel.OpenProcess.restype is wintypes.HANDLE
    kernel.WaitForSingleObject.assert_called_once_with(handle, 0)
    kernel.CloseHandle.assert_called_once_with(handle)


def test_windows_socket_is_exclusive(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    mod = _load_launcher()
    sock = Mock()
    sock.getsockname.return_value = ("127.0.0.1", 8123)
    monkeypatch.setattr(mod, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(mod, "socket", SimpleNamespace(
        socket=Mock(return_value=sock), AF_INET=2, SOCK_STREAM=1,
        SOL_SOCKET=65535, SO_EXCLUSIVEADDRUSE=-5,
    ))
    assert mod._bind_free() == (sock, 8123)
    sock.setsockopt.assert_called_once_with(65535, -5, 1)


def test_launcher_health_bypasses_system_proxy(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *args):
            pass

    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("no_proxy", "")
    with HTTPServer(("127.0.0.1", 0), HealthHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            assert _load_launcher()._health_ok(server.server_port)
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_launcher_server_works_without_console(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import uvicorn

    server = Mock()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        mod = _load_launcher()
        patch.setattr(mod, "_log_file", lambda: tmp_path / "server.log")
        patch.setattr(uvicorn, "Server", Mock(return_value=server))
        sock = Mock()
        mod._start_server(sock, 8123)
        server.run.assert_called_once_with(sockets=[sock])
