"""Screening REST API: upload, run lifecycle, downloads."""
from __future__ import annotations

import logging
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal, Optional
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import jobinja, runner, uploads
from .extraction import list_resume_files
from .models import FinalStatus, RunState, ScreeningCriteria
from .output_writer import _unique_name
from .report import write_filtered_report

router = APIRouter()
logger = logging.getLogger(__name__)


class ScanRequest(BaseModel):
    folderPath: str


class StartRunRequest(BaseModel):
    folderPath: str
    criteria: dict


class ReviewRequest(BaseModel):
    filename: str
    decision: Literal["approved", "rejected", "needs-review"]


def _resolve_folder(folder_path: str) -> Path:
    p = Path(folder_path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail="پوشه یافت نشد.")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="مسیر واردشده یک پوشه نیست.")
    return p


def _parse_criteria(raw: dict) -> ScreeningCriteria:
    min_years = raw.get("minYears", raw.get("min_years"))
    if min_years is not None:
        try:
            min_years = float(min_years)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="مقدار حداقل سابقه باید عدد باشد.")
        if not math.isfinite(min_years) or min_years < 0:
            raise HTTPException(status_code=400, detail="مقدار حداقل سابقه نمی‌تواند منفی باشد.")
    if min_years is None:
        raise HTTPException(status_code=400, detail="حداقل سابقه کار الزامی است.")
    return ScreeningCriteria(min_years=min_years)


@router.post("/folders/scan")
def scan_folder(body: ScanRequest):
    if not body.folderPath or not body.folderPath.strip():
        raise HTTPException(status_code=400, detail="مسیر پوشه الزامی است.")
    folder = _resolve_folder(body.folderPath.strip())
    files = list_resume_files(str(folder))
    if not files:
        raise HTTPException(status_code=422, detail="هیچ رزومه پشتیبانی‌شده‌ای یافت نشد (فقط فایل‌های .pdf یا .docx در سطح پوشه).")
    return {"fileCount": len(files), "files": files}


@router.post("/runs")
def start_run(body: StartRunRequest):
    if not body.folderPath or not body.folderPath.strip():
        raise HTTPException(status_code=400, detail="مسیر پوشه الزامی است.")
    folder = _resolve_folder(body.folderPath.strip())
    criteria = _parse_criteria(body.criteria or {})
    files = list_resume_files(str(folder))
    if not files:
        raise HTTPException(status_code=422, detail="هیچ رزومه پشتیبانی‌شده‌ای یافت نشد.")
    run = runner.create_run(str(folder), criteria)
    return {"runId": run.run_id}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="اجرای موردنظر یافت نشد.")
    return runner.run_to_dict(run)


@router.post("/runs/{run_id}/review")
def review_resume(run_id: str, body: ReviewRequest):
    status = {"approved": FinalStatus.QUALIFIED, "rejected": FinalStatus.NOT_QUALIFIED,
              "needs-review": FinalStatus.UNDETERMINED}[body.decision]
    try:
        run = runner.review_resume(run_id, body.filename, status)
    except KeyError:
        raise HTTPException(status_code=404, detail="بررسی یا رزومه موردنظر یافت نشد.") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        logger.exception("Manual review could not be saved for run %s", run_id)
        raise HTTPException(status_code=500, detail="تصمیم ذخیره نشد؛ فایل Excel را ببندید و دسترسی و فضای دیسک را بررسی کنید، سپس دوباره تلاش کنید.") from None
    return runner.run_to_dict(run)


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="اجرای موردنظر یافت نشد.")
    if not runner.pause_run(run_id):
        raise HTTPException(status_code=409, detail="اجرا در حالت فعال نیست (پیش‌تر پایان یافته یا متوقف شده است).")
    return {"state": "paused"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="اجرای موردنظر یافت نشد.")
    if not runner.resume_run(run_id):
        raise HTTPException(status_code=409, detail="اجرا در حالت متوقف نیست.")
    return {"state": "running"}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="اجرای موردنظر یافت نشد.")
    if not runner.cancel_run(run_id):
        raise HTTPException(status_code=409, detail="اجرا پیش‌تر پایان یافته است.")
    return runner.run_to_dict(run)


# ---------------------------------------------------------------------------
# Browser upload: the folder picker cannot reveal a real path, so the selected
# files are staged and processed from the staging directory.
# ---------------------------------------------------------------------------


@router.post("/uploads")
async def create_upload(files: list[UploadFile] = File(...), upload_id: str | None = Form(None)):
    """Stage the resumes chosen with the browser folder picker.

    The client sends a folder in small batches (Chrome asks the user to confirm a
    bulk upload otherwise) and repeats ``upload_id`` so the batches land in one
    staging directory. Without it every call still starts a fresh upload.
    """
    if not files:
        raise HTTPException(status_code=400, detail="هیچ فایلی انتخاب نشده است.")
    if len(files) > uploads.MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"تعداد فایل‌ها بیش از حد مجاز است (حداکثر {uploads.MAX_FILES} فایل).",
        )

    root = Path(tempfile.gettempdir()) / "resume-check-uploads"
    continuing = uploads.staged_dir(root, upload_id) if upload_id else None
    try:
        if continuing is None:
            # Sweep leftovers from an upload that was never processed before adding more.
            uploads.sweep_stale(root)
            directory = uploads.new_upload_dir(root)
        else:
            directory = continuing
    except OSError:
        logger.exception("Cannot create upload staging directory")
        raise HTTPException(status_code=507, detail="امکان ذخیره موقت فایل‌ها وجود ندارد؛ دسترسی و فضای دیسک را بررسی کنید.") from None
    staged_before = uploads.list_uploaded(directory)
    if len(staged_before) + len(files) > uploads.MAX_FILES:
        uploads.cleanup_upload(directory)
        raise HTTPException(
            status_code=413,
            detail=f"تعداد فایل‌ها بیش از حد مجاز است (حداکثر {uploads.MAX_FILES} فایل).",
        )
    total = uploads.staged_bytes(directory)
    accepted: list[str] = []
    rejected: list[str] = []
    try:
        for upload in files:
            name = upload.filename or ""
            if not uploads.is_supported(name):
                rejected.append(name)
                continue
            # The client sends the browser-provided file name, which is the
            # folder-relative path (a/b/cv.docx). Keeping it means two resumes that
            # share a name in different sub-folders do not overwrite each other.
            data = await upload.read(uploads.MAX_FILE_BYTES + 1)
            total += len(data)
            if total > uploads.MAX_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="حجم کل فایل‌ها بیش از حد مجاز است.")
            try:
                stored = uploads.store_file(directory, name, data)
            except uploads.UploadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            accepted.append(stored.as_posix() if isinstance(stored, Path) else str(stored))
    except HTTPException:
        uploads.cleanup_upload(directory)
        raise
    except OSError:
        uploads.cleanup_upload(directory)
        logger.exception("Cannot write uploaded files")
        raise HTTPException(status_code=507, detail="امکان ذخیره موقت فایل‌ها وجود ندارد؛ دسترسی و فضای دیسک را بررسی کنید.") from None
    except Exception:
        logger.exception("Cannot stage uploaded files")
        uploads.cleanup_upload(directory)
        raise HTTPException(status_code=400, detail="بارگذاری فایل‌ها ناموفق بود.") from None

    stored = uploads.list_uploaded(directory)
    if not stored:
        uploads.cleanup_upload(directory)
        raise HTTPException(
            status_code=422,
            detail="هیچ فایل PDF یا DOCX معتبری در پوشه انتخاب‌شده یافت نشد.",
        )

    runner.register_upload(directory)
    return {
        "uploadId": directory.name,
        "folderName": _folder_name(files[0].filename or ""),
        "fileCount": len(stored),
        "files": stored,
        "skipped": len(rejected),
    }


def _folder_name(first_filename: str) -> str:
    """Best available folder label from webkitRelativePath, else the file name."""
    parts = Path(first_filename.replace("\\", "/")).parts
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


class StartUploadRunRequest(BaseModel):
    criteria: dict
    outputFolder: Optional[str] = None


@router.post("/jobinja/imports")
async def create_jobinja_import(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="فایل Excel جابینجا با پسوند XLSX انتخاب کنید.")
    data = await file.read(jobinja.MAX_EXCEL_BYTES + 1)
    try:
        applicants = jobinja.parse_excel(data)
        directory = uploads.new_upload_dir(Path(tempfile.gettempdir()) / "resume-check-uploads")
    except jobinja.JobinjaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except OSError:
        raise HTTPException(status_code=507, detail="فضای کاری دریافت رزومه‌ها قابل نوشتن نیست؛ فضای دیسک و دسترسی را بررسی کنید.") from None
    job = jobinja.ImportJob(directory.name, directory, uploads.safe_filename(file.filename), applicants)
    jobinja._imports[job.import_id] = job
    return jobinja.import_state(job)


def _jobinja_import(import_id: str) -> jobinja.ImportJob:
    job = jobinja._imports.get(import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="فایل Excel بارگذاری‌شده یافت نشد؛ دوباره آن را انتخاب کنید.")
    return job


@router.get("/jobinja/imports/{import_id}")
def get_jobinja_import(import_id: str):
    return jobinja.import_state(_jobinja_import(import_id))


@router.post("/jobinja/imports/{import_id}/run")
def start_jobinja_import(import_id: str, body: StartUploadRunRequest):
    job = _jobinja_import(import_id)
    criteria = _parse_criteria(body.criteria)
    try:
        jobinja.start_import(job, criteria, body.outputFolder)
    except jobinja.JobinjaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return jobinja.import_state(job)


@router.post("/jobinja/imports/{import_id}/cancel")
def cancel_jobinja_import(import_id: str):
    job = _jobinja_import(import_id)
    with job.lock:
        job.cancelled = True
        run_id = job.run_id
    if run_id is not None:
        runner.cancel_run(run_id)
    return jobinja.import_state(job)


@router.post("/uploads/{upload_id}/run")
def start_upload_run(upload_id: str, body: StartUploadRunRequest):
    """Start a screening run over a staged upload."""
    directory = runner.upload_dir(upload_id)
    if directory is None or not Path(directory).is_dir():
        raise HTTPException(status_code=404, detail="فایل‌های بارگذاری‌شده یافت نشد. دوباره پوشه را انتخاب کنید.")
    try:
        runner.set_output_target(upload_id, body.outputFolder)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    criteria = _parse_criteria(body.criteria or {})
    run = runner.create_run(directory, criteria)
    return {"runId": run.run_id, "outputPath": None}


@router.get("/runs/{run_id}/report")
def download_report(run_id: str):
    """Download the Persian Excel report produced by a run."""
    report_path = runner.report_path(run_id)
    if report_path is None or not Path(report_path).is_file():
        raise HTTPException(status_code=404, detail="گزارش این اجرا هنوز آماده نیست.")
    return FileResponse(
        report_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(report_path).name,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/runs/{run_id}/report-name")
def report_name(run_id: str):
    """Default file name to pre-fill the browser's Save As dialog."""
    from .output_writer import jalali_today_str

    name = runner.suggested_report_name(run_id)
    if not name:
        raise HTTPException(status_code=404, detail="گزارش این اجرا هنوز آماده نیست.")
    return {"fileName": name}


@router.get("/runs/{run_id}/export/{category}")
def download_category(run_id: str, category: Literal["all", "approved", "rejected", "needs-review"]):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="اجرای موردنظر یافت نشد.")
    if run.state not in (RunState.FINISHED, RunState.CANCELLED):
        raise HTTPException(status_code=409, detail="ابتدا بررسی رزومه‌ها را پایان دهید.")
    status = {"all": None, "approved": FinalStatus.QUALIFIED,
              "rejected": FinalStatus.NOT_QUALIFIED, "needs-review": FinalStatus.UNDETERMINED}[category]
    results = [r for r in run.results if status is None or r.final_status == status]
    if not results:
        raise HTTPException(status_code=404, detail="در این دسته رزومه‌ای برای دانلود وجود ندارد.")
    source_report = runner.report_path(run_id)
    if source_report is None:
        logger.error("ZIP has no report: run=%s source=%s processed=%d expected=%d output_exists=%s",
                     run_id, runner.source_label(run), run.processed, len(results),
                     bool(run.output_path) and Path(run.output_path).is_dir())
        raise HTTPException(
            status_code=409,
            detail="گزارش Excel این اجرا ساخته نشده است؛ نتایج ذخیره نشده‌اند. بررسی را دوباره اجرا کنید.")
    root = f"{category}-resumes"
    names = {}
    directory = None
    found = added = missing = 0
    try:
        logger.info("ZIP start: run=%s category=%s processed=%d expected=%d frozen=%s platform=%s "
                    "source=%s output=%s temp=%s cwd=%s bundle=%s",
                    run_id, category, run.processed, len(results), bool(getattr(sys, "frozen", False)),
                    sys.platform, Path(run.folder_path).resolve(), run.output_path, tempfile.gettempdir(),
                    Path.cwd(), getattr(sys, "_MEIPASS", None))
        if (category == "all" and len(results) != run.processed) or len({r.filename for r in results}) != len(results):
            logger.error("ZIP references do not match the run: run=%s source=%s category=%s processed=%d expected=%d",
                         run_id, runner.source_label(run), category, run.processed, len(results))
            raise HTTPException(status_code=409, detail="فهرست رزومه‌های این اجرا کامل نیست؛ بررسی را دوباره اجرا کنید.")
        files = []
        for result in results:
            path = runner.resume_file_path(run_id, result.filename)
            if path is None:
                missing += 1
                logger.error("ZIP source missing: run=%s filename=%s source=%s output=%s stored=%s",
                             run_id, result.filename, run.folder_path, run.output_path,
                             runner._output_files.get(run_id, {}).get(result.filename))
            else:
                found += 1
                logger.info("ZIP source resolved: run=%s filename=%s path=%s", run_id, result.filename, path)
                files.append((result.filename, path))
        if missing:
            logger.error("ZIP is incomplete: run=%s source=%s category=%s expected=%d found=%d missing=%d",
                         run_id, runner.source_label(run), category, len(results), found, missing)
            raise HTTPException(status_code=409, detail=f"خروجی کامل ساخته نشد؛ {missing} فایل رزومه در پوشهٔ خروجی این اجرا نیست.")
        directory = Path(tempfile.mkdtemp(prefix="resume-check-export-"))
        archive = directory / f"{category}-resumes.zip"
        logger.info("ZIP destination: run=%s archive=%s", run_id, archive)
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            for filename, path in files:
                name = _unique_name(uploads.safe_filename(filename.replace("/", "-").replace("\\", "-")), set(names.values()))
                zip_file.write(path, f"{root}/resumes/{name}")
                names[filename] = name
                added += 1
            report = write_filtered_report(Path(source_report), run, names, directory)
            zip_file.write(report, f"{root}/{category}-report.xlsx")
        with ZipFile(archive, "r") as zip_file:
            expected = {f"{root}/resumes/{name}" for name in names.values()} | {f"{root}/{category}-report.xlsx"}
            if added != len(results) or len(zip_file.infolist()) != len(results) + 1 or set(zip_file.namelist()) != expected:
                raise ValueError("ZIP entries do not match expected resumes and report")
            corrupt = zip_file.testzip()
            if corrupt is not None:
                raise ValueError(f"ZIP CRC validation failed: {corrupt}")
        logger.info("ZIP validated: run=%s expected=%d found=%d added=%d missing=%d size=%d archive=%s",
                    run_id, len(results), found, added, missing, archive.stat().st_size, archive)
        return FileResponse(archive, media_type="application/zip", filename=archive.name,
                            headers={"Cache-Control": "no-store"},
                            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True))
    except HTTPException:
        logger.warning("ZIP refused: run=%s source=%s category=%s expected=%d found=%d added=%d missing=%d",
                       run_id, runner.source_label(run), category, len(results), found, added, missing)
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        raise
    except OSError:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        logger.exception("ZIP could not be written: run=%s source=%s category=%s expected=%d found=%d added=%d",
                         run_id, runner.source_label(run), category, len(results), found, added)
        raise HTTPException(status_code=500, detail="نوشتن فایل خروجی ممکن نشد؛ فضای دیسک و دسترسی نوشتن را بررسی کنید.") from None
    except ValueError:
        # The archive or its report did not match the run results.
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        logger.exception("ZIP content did not match the run: run=%s source=%s category=%s expected=%d found=%d added=%d",
                         run_id, runner.source_label(run), category, len(results), found, added)
        raise HTTPException(status_code=500, detail="محتوای خروجی با نتایج این اجرا مطابقت نداشت؛ دوباره تلاش کنید.") from None
    except Exception:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)
        logger.exception("ZIP failed: run=%s source=%s category=%s expected=%d found=%d added=%d missing=%d",
                         run_id, runner.source_label(run), category, len(results), found, added, missing)
        raise HTTPException(status_code=500, detail="ساخت خروجی ZIP ناموفق بود؛ خطای غیرمنتظره در لاگ برنامه ثبت شد.") from None


# Content types served by the resume viewer. DOCX is an OOXML package, which browsers
# cannot render, so it is offered as a download with an explanatory message.
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/runs/{run_id}/preview")
def resume_preview(run_id: str, filename: str = Body(embed=True)):
    """Return PDF bytes to the internal renderer without a download filename."""
    run = runner.get_run(run_id)
    if run is None:
        return JSONResponse({"code": "run_not_found", "detail": "این بررسی دیگر در دسترس نیست؛ رزومه‌ها را دوباره بررسی کنید."}, status_code=404)
    if not any(result.filename == filename for result in run.results):
        return JSONResponse({"code": "invalid_reference", "detail": "ارجاع رزومه نامعتبر است."}, status_code=400)
    try:
        path = runner.resume_file_path(run_id, filename)
        if path is not None:
            with open(path, "rb") as source:
                header = source.read(1024)
    except PermissionError:
        logger.warning("PDF preview permission denied: run=%s", run_id, exc_info=True)
        return JSONResponse({"code": "permission_denied", "detail": "اجازه خواندن این رزومه وجود ندارد. دسترسی به فایل را بررسی کنید."}, status_code=403)
    except FileNotFoundError:
        path = None
    except (OSError, ValueError):
        logger.warning("PDF preview file access failed: run=%s", run_id, exc_info=True)
        return JSONResponse({"code": "file_access_failed", "detail": "خواندن فایل رزومه ناموفق بود؛ دسترسی و مسیر فایل را بررسی کنید."}, status_code=400)
    if path is None:
        return JSONResponse({"code": "file_not_found",
                             "detail": runner.describe_missing_resume(run_id, filename)},
                            status_code=404)
    if Path(path).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="پیش‌نمایش فقط برای PDF پشتیبانی می‌شود.")
    if not header:
        return JSONResponse({"code": "empty_pdf", "detail": "فایل PDF خالی است."}, status_code=422)
    if b"%PDF-" not in header:
        return JSONResponse({"code": "invalid_pdf", "detail": "فایل PDF نامعتبر یا خراب است."}, status_code=422)
    # PDF navigation/headers can activate browser viewers and download managers.
    return FileResponse(path, media_type="application/octet-stream", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/runs/{run_id}/resumes/{filename:path}")
def resume_file(run_id: str, filename: str, download: bool = False):
    """Serve one processed resume for the in-app viewer or as a download.

    Every status uses the durable output copy, with staged input as a fallback.
    Both are reachable only through the run id.
    """
    path = runner.resume_file_path(run_id, filename)
    if path is None:
        detail = runner.describe_missing_resume(run_id, filename)
        raise HTTPException(status_code=404, detail=detail)
    file_path = Path(path)
    media = _MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    if download:
        return FileResponse(file_path, media_type=media, filename=file_path.name)
    return FileResponse(
        file_path,
        media_type=media,
        filename=file_path.name,
        content_disposition_type="inline" if media == "application/pdf" else "attachment",
    )
