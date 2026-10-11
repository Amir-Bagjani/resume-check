"""Screening REST API: upload, run lifecycle, downloads."""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import runner, uploads
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
    keywords = raw.get("keywords", []) or []
    if min_years is not None:
        try:
            min_years = float(min_years)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="مقدار حداقل سابقه باید عدد باشد.")
        if min_years < 0:
            raise HTTPException(status_code=400, detail="مقدار حداقل سابقه نمی‌تواند منفی باشد.")
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    seen, deduped = set(), []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            deduped.append(k)
    if min_years is None and not deduped:
        raise HTTPException(status_code=400, detail="حداقل یک معیار غربال لازم است.")
    return ScreeningCriteria(min_years=min_years, keywords=deduped)


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
async def create_upload(files: list[UploadFile] = File(...)):
    """Stage the resumes chosen with the browser folder picker."""
    if not files:
        raise HTTPException(status_code=400, detail="هیچ فایلی انتخاب نشده است.")
    if len(files) > uploads.MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"تعداد فایل‌ها بیش از حد مجاز است (حداکثر {uploads.MAX_FILES} فایل).",
        )

    root = Path(tempfile.gettempdir()) / "resume-check-uploads"
    # Sweep leftovers from an upload that was never processed before adding more.
    try:
        uploads.sweep_stale(root)
        directory = uploads.new_upload_dir(root)
    except OSError:
        logger.exception("Cannot create upload staging directory")
        raise HTTPException(status_code=507, detail="امکان ذخیره موقت فایل‌ها وجود ندارد؛ دسترسی و فضای دیسک را بررسی کنید.") from None
    total = 0
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
        raise HTTPException(status_code=409, detail="گزارش Excel این اجرا در دسترس نیست.")
    directory = Path(tempfile.mkdtemp(prefix="resume-check-export-"))
    archive = directory / f"{category}-resumes.zip"
    root = f"{category}-resumes"
    names = {}
    try:
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zip_file:
            for result in results:
                path = runner.resume_file_path(run_id, result.filename)
                if path is None:
                    raise HTTPException(status_code=409, detail=f"خروجی کامل ساخته نشد؛ فایل در دسترس نیست: {result.filename}")
                name = _unique_name(uploads.safe_filename(result.filename.replace("/", "-").replace("\\", "-")), set(names.values()))
                try:
                    zip_file.write(path, f"{root}/resumes/{name}")
                except OSError:
                    raise HTTPException(status_code=409, detail=f"خروجی کامل ساخته نشد؛ خواندن فایل ناموفق بود: {result.filename}") from None
                names[result.filename] = name
            report = write_filtered_report(Path(source_report), run, names, directory)
            zip_file.write(report, f"{root}/{category}-report.xlsx")
        return FileResponse(archive, media_type="application/zip", filename=archive.name,
                            background=BackgroundTask(shutil.rmtree, directory, ignore_errors=True))
    except HTTPException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        logger.exception("Category export failed for run %s", run_id)
        raise HTTPException(status_code=500, detail="ساخت خروجی ZIP ناموفق بود؛ فضای دیسک و دسترسی به فایل‌ها را بررسی کنید.") from None


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
        return JSONResponse({"code": "file_not_found", "detail": "فایل این رزومه یافت نشد. ممکن است جابه‌جا یا حذف شده باشد."}, status_code=404)
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

    Works for every status: qualified resumes are copied into the output folder,
    the rest stay in the staged upload. Both are reachable only through the run id.
    """
    path = runner.resume_file_path(run_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="فایل رزومه در دسترس نیست.")
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
