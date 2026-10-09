"""Cross-platform EXE smoke test: start binary, upload Unicode-named DOCX, run, check viewer+Excel."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

HEALTH_TIMEOUT = 60.0
RUN_TIMEOUT = 60.0


def _read(base: str, path: str, timeout: float = 10.0):
    req = urllib.request.Request(f"{base}{path}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def _multipart(path: str, data: bytes, field: str = "files") -> tuple[bytes, str]:
    boundary = "----SmokeB1"
    head = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
        f'filename="batch_cv.docx"; filename*=utf-8\'\'batch%2F{path}\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n"
    ).encode("ascii")
    body = head + data + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, boundary


def _docx_bytes() -> bytes:
    from docx import Document
    from io import BytesIO

    doc = Document()
    doc.add_paragraph("Smoke Candidate")
    doc.add_paragraph("Over 7 years in software development.")
    doc.add_paragraph("React Python Docker")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _instance_port() -> int | None:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(os.path.expanduser("~\\AppData\\Local"))
        inst = os.path.join(base, "ResumeCheck", "instance.json")
    elif sys.platform == "darwin":
        inst = os.path.expanduser("~/Library/Application Support/ResumeCheck/instance.json")
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        inst = os.path.join(xdg, "resume-check", "instance.json")
    try:
        with open(inst, encoding="utf-8") as f:
            return json.load(f)["port"]
    except Exception:
        return None


def main(exe: str) -> int:
    env = dict(os.environ, RESUMECHECK_HEADLESS="1")
    log = open("smoke-server.log", "ab")
    proc = subprocess.Popen(
        [exe], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env
    )
    try:
        deadline = time.time() + HEALTH_TIMEOUT
        port = None
        while time.time() < deadline:
            port = _instance_port()
            if port:
                try:
                    status, _, body = _read(f"http://127.0.0.1:{port}", "/api/health")
                    if status == 200 and json.loads(body).get("status") == "ok":
                        break
                except Exception:
                    pass
            if proc.poll() is not None:
                print("server exited early", flush=True)
                return 1
            time.sleep(0.5)
        else:
            print("health check timed out", flush=True)
            return 1

        base = f"http://127.0.0.1:{port}"
        fa_name = "رزومه فارسی.docx"
        quoted = "".join(f"%{b:02X}" for b in fa_name.encode("utf-8"))
        body, boundary = _multipart(quoted, _docx_bytes())
        req = urllib.request.Request(
            f"{base}/api/uploads", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            up = json.load(r)
        upload_id = up["uploadId"]
        assert up["fileCount"] == 1, up

        payload = json.dumps({"criteria": {"minYears": 5, "keywords": ["React"]}, "outputFolder": None}).encode()
        req = urllib.request.Request(
            f"{base}/api/uploads/{upload_id}/run", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            run_id = json.load(r)["runId"]

        deadline = time.time() + RUN_TIMEOUT
        state = {}
        while time.time() < deadline:
            _, _, raw = _read(base, f"/api/runs/{run_id}")
            state = json.loads(raw)
            if state["state"] == "finished":
                break
            time.sleep(0.5)
        assert state.get("state") == "finished", state
        assert state["found"] == 1 and state["processed"] == 1, state
        fname = state["results"][0]["filename"]
        print(f"stored name: {fname}", flush=True)

        status, _, pdf = _read(base, f"/api/runs/{run_id}/resumes/{fname}")
        assert status == 200 and len(pdf) > 1000, status
        status, _, xlsx = _read(base, f"/api/runs/{run_id}/report")
        assert status == 200 and xlsx[:2] == b"PK", status
        print(f"smoke OK: viewer={len(pdf)}B excel={len(xlsx)}B", flush=True)
        return 0
    except Exception as exc:
        print(f"SMOKE FAILED: {exc}", flush=True)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
