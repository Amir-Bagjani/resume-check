"""ZIP-only checks with synthetic resumes; never process real documents."""
from io import BytesIO
import errno
import logging
from pathlib import Path
import sys
import time
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from backend.app import routes_runs, runner, uploads
from backend.app.main import app
from backend.app.models import FinalStatus, ResumeResult, ScreeningCriteria, ScreeningRun
from backend.app.output_writer import copy_resumes


@pytest.fixture
def export_run(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_runs.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runner, "user_data_dir", lambda: tmp_path / "user data")
    for registry in ("_runs", "_uploads", "_output_files", "_output_targets"):
        monkeypatch.setattr(runner, registry, {})
    client = TestClient(app)
    names = ["تیم اول/رزومه فارسی.docx", "تیم دوم/رزومه فارسی.docx",
             "cv.docx", "CV.docx", "cv+.docx", "cv#.docx", "CON.docx",
             "candidate with spaces.pdf"] + [f"رزومه {i}.pdf" for i in range(35)]
    contents = [f"synthetic resume {i}".encode() for i in range(43)]
    response = client.post("/api/uploads", files=[
        ("files", ("batch/" + name, data, "application/octet-stream"))
        for name, data in zip(names, contents)
    ])
    assert response.status_code == 200, response.text
    uploaded = response.json()
    assert uploaded["fileCount"] == 43
    folder = runner.upload_dir(uploaded["uploadId"])
    statuses = list(FinalStatus)
    run = ScreeningRun("zip-test", str(folder), ScreeningCriteria(min_years=5), found=43, processed=43,
                       results=[ResumeResult(filename=name, final_status=statuses[i % 3])
                                for i, name in enumerate(uploaded["files"])])
    runner._runs[run.run_id] = run
    runner._finalize(run)
    return client, run, contents, tmp_path


# The real trigger behind the export failure: resume text from a PDF carries
# control characters that Excel cells refuse, in the reason column.
CONTROL_TEXT = "مسئول توسعه و تیم ( دانشگاه صنعتی شریف\x00 ساختمان فناوری ) ۱۴۰۳ تا ۱۴۰۵"


@pytest.fixture
def analysed_run(tmp_path, monkeypatch):
    """An uploaded-folder run processed for real, with control characters in the text."""
    from backend.app import extraction

    monkeypatch.setattr(routes_runs.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runner, "user_data_dir", lambda: tmp_path / "user data")
    for registry in ("_runs", "_uploads", "_output_files", "_output_targets"):
        monkeypatch.setattr(runner, registry, {})
    original = extraction.analyze_file

    def analyze_file(folder_path, filename):
        facts = original(folder_path, filename)
        facts.experience_source_text = f"{facts.experience_source_text} {CONTROL_TEXT}".strip()
        return facts

    monkeypatch.setattr(runner, "analyze_file", analyze_file)
    from reportlab.pdfgen import canvas

    names = ["cv.pdf", "تیم دوم/cv.pdf", "نام فارسی با فاصله.pdf"]
    texts = ["7+ years of professional experience", "1+ years of professional experience",
             "3+ years of professional experience"]
    client = TestClient(app)
    files = []
    for name, text in zip(names, texts):
        buffer = BytesIO()
        canvas_ = canvas.Canvas(buffer)
        canvas_.drawString(30, 700, text)
        canvas_.save()
        files.append(("files", ("batch/" + name, buffer.getvalue(), "application/pdf")))
    uploaded = client.post("/api/uploads", files=files)
    assert uploaded.status_code == 200, uploaded.text
    folder = runner.upload_dir(uploaded.json()["uploadId"])
    run = runner.create_run(str(folder), ScreeningCriteria(min_years=5))
    for _ in range(200):
        if run.state.value in ("finished", "failed", "cancelled"):
            break
        time.sleep(0.02)
    assert run.state.value == "finished", run.error
    return client, run


def test_zip_and_report_survive_control_characters_in_resume_text(analysed_run):
    client, run = analysed_run
    assert run.processed == 3
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        resumes = [name for name in names if "/resumes/" in name]
        assert len(resumes) == 3 and "all-resumes/all-report.xlsx" in names
        # Same base name in two folders must not overwrite the other.
        assert len({name.casefold() for name in resumes}) == 3
        assert any("نام فارسی" in name for name in resumes)
        assert archive.testzip() is None
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(archive.read("all-resumes/all-report.xlsx")))
        try:
            rows = list(workbook.active.values)
            header = next(i for i, row in enumerate(rows) if row[0] == "نام فایل رزومه")
            assert len(rows[header + 1:]) == 3
            reasons = [row[9] for row in rows[header + 1:]]
            assert any("دانشگاه" in (reason or "") for reason in reasons)
            assert not any("\x00" in (reason or "") for reason in reasons)
            from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
            assert not any(ILLEGAL_CHARACTERS_RE.search(str(cell))
                           for row in rows for cell in row if isinstance(cell, str))
        finally:
            workbook.close()


def test_zip_reports_a_missing_report_instead_of_a_generic_error(analysed_run, caplog):
    client, run = analysed_run
    Path(run.output_path, "screening-report.xlsx").unlink()
    with caplog.at_level(logging.ERROR):
        response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "گزارش Excel این اجرا ساخته نشده است" in detail
    assert "فضای دیسک" not in detail
    assert "ZIP has no report" in caplog.text and "source=folder" in caplog.text


@pytest.mark.parametrize("frozen", [False, True])
def test_zip_all_43_survives_staging_cleanup(export_run, monkeypatch, caplog, frozen):
    client, run, contents, tmp_path = export_run
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI bundle"), raising=False)
    # Actual Windows CI uses native drive paths; elsewhere test CWD/bundle independence.
    other = tmp_path / "different working directory"
    other.mkdir()
    monkeypatch.chdir(other)
    report = Path(run.output_path) / "screening-report.xlsx"
    before = report.read_bytes()
    originals = {p: p.read_bytes() for p in Path(run.output_path).glob("*")}
    uploads.sweep_stale(tmp_path / "resume-check-uploads", max_age_seconds=0)
    assert not Path(run.folder_path).exists()
    with caplog.at_level(logging.INFO):
        response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        resumes = [name for name in names if "/resumes/" in name]
        assert len(resumes) == 43 and len(names) == 44
        assert len({name.casefold() for name in names}) == 44
        assert any("رزومه فارسی" in name for name in resumes)
        assert all("\\" not in name for name in names)
        assert archive.testzip() is None
        archive.extractall(tmp_path / "extracted")
        assert sorted((tmp_path / "extracted" / name).read_bytes() for name in resumes) == sorted(contents)
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(archive.read("all-resumes/all-report.xlsx")))
        try:
            rows = list(workbook.active.values)
            header = next(i for i, row in enumerate(rows) if row[0] == "نام فایل رزومه")
            assert len(rows[header + 1:]) == 43
        finally:
            workbook.close()
        print(f"ZIP opened: {len(resumes)} resumes, {len(names)} entries, {len(response.content)} bytes; names={names}")
    assert "expected=43 found=43 added=43 missing=0" in caplog.text
    assert f"frozen={frozen}" in caplog.text
    assert report.read_bytes() == before
    assert all(p.read_bytes() == data for p, data in originals.items())
    assert not list(tmp_path.glob("resume-check-export-*"))


@pytest.mark.parametrize("category,status", [("approved", FinalStatus.QUALIFIED),
                                            ("rejected", FinalStatus.NOT_QUALIFIED),
                                            ("needs-review", FinalStatus.UNDETERMINED)])
def test_zip_each_status(export_run, category, status):
    client, run, _, _ = export_run
    response = client.get(f"/api/runs/{run.run_id}/export/{category}")
    assert response.status_code == 200, response.text
    with ZipFile(BytesIO(response.content)) as archive:
        expected = sum(r.final_status == status for r in run.results)
        assert len(archive.namelist()) == expected + 1
        assert len([n for n in archive.namelist() if "/resumes/" in n]) == expected
        assert archive.testzip() is None


def test_zip_missing_source_is_error(export_run, caplog):
    client, run, _, tmp_path = export_run
    name = run.results[0].filename
    Path(runner.resume_file_path(run.run_id, name)).unlink()
    (Path(run.folder_path) / name).unlink()
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 409
    assert "1 فایل رزومه در پوشهٔ خروجی این اجرا نیست" in response.json()["detail"]
    assert "ZIP source missing" in caplog.text and name in caplog.text
    assert not list(tmp_path.glob("resume-check-export-*"))


def test_zip_missing_report_logs_output_location(export_run, caplog):
    client, run, _, _ = export_run
    (Path(run.output_path) / "screening-report.xlsx").unlink()
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 409
    assert "ZIP has no report" in caplog.text and run.run_id in caplog.text
    assert run.output_path not in caplog.text  # local paths stay out of the log


@pytest.mark.parametrize("failure", ["directory", "write", "read", "crc", "count"])
def test_zip_failure_never_downloads_partial_archive(export_run, monkeypatch, caplog, failure):
    client, run, _, tmp_path = export_run
    def fail(*args, **kwargs):
        if failure == "read":
            raise PermissionError(errno.EACCES, "source locked")
        raise OSError(errno.ENOSPC, "No space left on device")
    if failure == "directory":
        monkeypatch.setattr(routes_runs.tempfile, "mkdtemp", fail)
    elif failure in ("write", "read"):
        monkeypatch.setattr(ZipFile, "write", fail)
    elif failure == "crc":
        monkeypatch.setattr(ZipFile, "testzip", lambda self: "corrupt.pdf")
    else:
        monkeypatch.setattr(ZipFile, "namelist", lambda self: [])
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    # Disk/permission problems and content mismatches get their own message.
    expected = {"directory": "نوشتن فایل خروجی ممکن نشد", "write": "نوشتن فایل خروجی ممکن نشد",
                "read": "نوشتن فایل خروجی ممکن نشد",
                "crc": "محتوای خروجی با نتایج این اجرا مطابقت نداشت",
                "count": "خطای غیرمنتظره در لاگ برنامه ثبت شد"}[failure]
    assert expected in detail
    assert ("ZIP could not be written" if failure in ("directory", "write", "read")
            else "ZIP content did not match the run" if failure == "crc"
            else "ZIP failed") in caplog.text
    assert run.run_id in caplog.text and "source=folder" in caplog.text
    assert any(record.exc_info for record in caplog.records)
    assert not list(tmp_path.glob("resume-check-export-*"))


def test_zip_processed_count_mismatch_is_error(export_run):
    client, run, _, _ = export_run
    run.processed += 1
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 409
    assert "فهرست رزومه‌های این اجرا کامل نیست" in response.json()["detail"]


def test_zip_copy_failure_logs_and_keeps_staged_source(export_run, monkeypatch, caplog):
    client, run, _, tmp_path = export_run
    result = run.results[0]
    original = (Path(run.folder_path) / result.filename).read_bytes()
    def fail(*args, **kwargs):
        raise PermissionError(errno.EACCES, "destination denied")
    with monkeypatch.context() as patch:
        patch.setattr(runner, "copy_resumes", copy_resumes)
        patch.setattr("backend.app.output_writer.shutil.copy2", fail)
        runner._finalize(run)
    assert "Resume copy failed" in caplog.text
    assert (Path(run.folder_path) / result.filename).read_bytes() == original
    response = client.get(f"/api/runs/{run.run_id}/export/all")
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert len(archive.namelist()) == 44 and archive.testzip() is None


def test_zip_copy_native_nested_paths(tmp_path):
    source, output = tmp_path / "ورودی", tmp_path / "خروجی"
    (source / "تیم").mkdir(parents=True)
    output.mkdir()
    relative = str(Path("تیم") / "رزومه فارسی.docx")
    (source / relative).write_bytes(b"native Windows backslash on Windows CI")
    pairs = copy_resumes(str(source), output, [relative])
    assert pairs == [(relative, "تیم-رزومه فارسی.docx")]
    assert (output / pairs[0][1]).read_bytes() == (source / relative).read_bytes()


def test_packaged_zip_diagnostics_are_written_without_console(tmp_path, monkeypatch):
    import importlib.util
    from unittest.mock import Mock
    import uvicorn

    spec = importlib.util.spec_from_file_location("zip_launcher", Path(__file__).resolve().parents[3] / "packaging/launcher.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    def log_during_run(**kwargs):
        logging.getLogger("backend.app.routes_runs").info("ZIP validated: added=43 Persian=رزومه")
    server = Mock()
    server.run.side_effect = log_during_run
    log_path = tmp_path / "server.log"
    with monkeypatch.context() as patch:
        patch.setattr(sys, "stdout", None)
        patch.setattr(sys, "stderr", None)
        patch.setattr(launcher, "_log_file", lambda: log_path)
        patch.setattr(uvicorn, "Server", Mock(return_value=server))
        launcher._start_server(Mock(), 8123)
    assert "ZIP validated: added=43 Persian=رزومه" in log_path.read_text(encoding="utf-8")
