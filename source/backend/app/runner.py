"""Chunked run orchestrator: in-memory registry, chunks of 10, pause/cancel."""
from __future__ import annotations

import logging
import tempfile
import threading
import time
import uuid
from dataclasses import replace
from pathlib import Path

from .extraction import analyze_file, list_resume_files
from .locale import (
    detection_status_fa,
    experience_status_fa,
    final_status_fa,
    format_years,
    jalali_display_date,
    jalali_display_date_long,
    run_state_fa,
)
from .models import Applicant, FinalStatus, ScreeningCriteria, ScreeningRun, RunState
from .output_writer import REPORT_FILENAME, copy_resumes, make_output_dir
from .paths import user_data_dir
from .qualification import evaluate
from .report import criteria_text, save_review_report, write_report

CHUNK_SIZE = 10
logger = logging.getLogger(__name__)

_runs: dict[str, ScreeningRun] = {}
_queues: dict[str, list[str]] = {}
_lock = threading.Lock()
_timers: dict[str, threading.Timer] = {}

# Staging directories created by the browser upload flow, keyed by upload id.
_uploads: dict[str, Path] = {}

# Original filename -> name actually written in the run's output folder, per run.
# Names can differ when two resumes share a file name.
_output_files: dict[str, dict[str, str]] = {}

# Where a run over a browser upload should place its output folder. The picker gives
# relative paths only, so the caller supplies the user's real folder; when it is
# None the results stay on the server and are downloaded through the UI.
_output_targets: dict[str, Path | None] = {}


def set_output_target(upload_id: str, target: str | None) -> None:
    """Record the folder a run over this upload should write its output into."""
    if target:
        path = Path(target).expanduser()
        if not path.is_dir():
            raise ValueError("پوشه مقصد یافت نشد.")
    else:
        path = None
    with _lock:
        _output_targets[upload_id] = path


def _output_parent(upload_id: str | None) -> Path | None:
    """Writable, durable destination for uploads, or None for local-folder runs."""
    if not upload_id:
        return None
    with _lock:
        target = _output_targets.get(upload_id)
    # Keep durable copies outside staging: the upload TTL sweep deletes its entire tree.
    return target if target is not None else user_data_dir() / "outputs"


def register_upload(directory: Path) -> None:
    """Remember a staging directory so runs over it can be located later."""
    with _lock:
        _uploads[directory.name] = directory


def upload_dir(upload_id: str) -> Path | None:
    with _lock:
        return _uploads.get(upload_id)


def _is_uploaded_run(run: ScreeningRun) -> bool:
    """True when this run is processing a staged browser upload.

    Compared by directory name rather than full path: on macOS the temporary
    directory arrives as "/var/..." but resolves to "/private/var/...", so a string
    comparison of the two paths silently fails.
    """
    name = Path(run.folder_path).name
    with _lock:
        return any(d.name == name for d in _uploads.values())


def report_path(run_id: str) -> str | None:
    """Absolute path of the Excel report for a run, if it produced one."""
    run = get_run(run_id)
    if run is None or not run.output_path:
        return None
    candidate = Path(run.output_path) / REPORT_FILENAME
    return str(candidate) if candidate.is_file() else None


def suggested_report_name(run_id: str) -> str:
    """A readable default file name for the Save As dialog, e.g.
    ``گزارش-غربال-رزومه-1405-07-18.xlsx``."""
    from .output_writer import REPORT_FILENAME, jalali_today_str

    run = get_run(run_id)
    if run is None:
        return ""
    return f"گزارش-غربال-رزومه-{jalali_today_str()}{Path(REPORT_FILENAME).suffix}"


def qualified_file_path(run_id: str, filename: str) -> str | None:
    """Absolute path of a qualified resume copied into a run's output folder."""
    run = get_run(run_id)
    if run is None or not run.output_path:
        return None
    out = Path(run.output_path).resolve()
    target = (out / Path(filename).name).resolve()
    try:
        target.relative_to(out)  # refuse traversal out of the output folder
    except ValueError:
        return None
    return str(target) if target.is_file() else None


def source_label(run: ScreeningRun) -> str:
    """Which intake produced this run: the Jobinja Excel flow or a picked folder."""
    return "jobinja" if run.applicants else "folder"


def describe_missing_resume(run_id: str, filename: str) -> str:
    """Why a run's resume cannot be served. Persian text only, never a path."""
    run = get_run(run_id)
    if run is None:
        return "این بررسی دیگر در دسترس نیست؛ رزومه‌ها را دوباره بررسی کنید."
    requested = str(filename or "").strip()
    with _lock:
        stored_names = _output_files.get(run_id)
    stored = stored_names.get(requested) if stored_names is not None else None
    output_exists = bool(run.output_path) and Path(run.output_path).is_dir()
    staged_exists = Path(run.folder_path).is_dir()
    logger.warning("Resume not served: run=%s source=%s file=%s output_dir=%s stored=%s staged=%s",
                   run_id, source_label(run), requested, output_exists, stored is not None, staged_exists)
    if not run.output_path:
        return ("پوشهٔ خروجی این اجرا ساخته نشده است؛ تولید گزارش کامل نشده و نتایج ذخیره‌شده در دسترس نیستند.")
    if not output_exists:
        return "پوشهٔ خروجی این اجرا پیدا نشد؛ خروجی‌های قبلی جابه‌جا یا حذف شده‌اند."
    if stored_names is not None and stored is None:
        return "این فایل برای این اجرا ثبت نشده است؛ فهرست رزومه‌های دریافت‌شده را بررسی کنید."
    if stored and not (Path(run.output_path) / stored).is_file():
        return "نسخهٔ ذخیره‌شدهٔ این رزومه در پوشهٔ خروجی نیست؛ خروجی این اجرا ناقص است."
    if not staged_exists:
        return "فایل موقت این رزومه پاک شده و نسخهٔ ذخیره‌شده در دسترس نیست."
    return "فایل این رزومه در هیچ‌کدام از مسیرهای این اجرا پیدا نشد."


def resume_file_path(run_id: str, filename: str) -> str | None:
    """Path of any processed resume, whatever its screening status.

    The output folder holds every processed resume and is the durable copy, so it is
    searched first. The run's input folder is the fallback for files that could not
    be copied. Both roots are resolved and the result must stay inside one of them,
    so a crafted name cannot reach arbitrary files on disk.
    """
    run = get_run(run_id)
    if run is None:
        return None
    requested = str(filename or "").strip()
    if not requested:
        return None

    with _lock:
        stored_names = _output_files.get(run_id)
        stored = stored_names.get(requested) if stored_names is not None else None

    # The output folder, searched by the exact written name first, then by plain
    # basename for runs finalized before the mapping was recorded.
    names: list[str] = []
    if stored:
        names.append(stored)
    if stored_names is None:
        names.append(Path(requested).name)
    if run.output_path:
        out = Path(run.output_path).resolve()
        for name in dict.fromkeys(names):
            target = (out / name).resolve()
            try:
                target.relative_to(out)
            except ValueError:
                continue
            if target.is_file():
                return str(target)

    # Fall back to the staged input under its original relative path.
    folder = Path(run.folder_path).resolve()
    target = (folder / requested).resolve()
    try:
        target.relative_to(folder)
    except ValueError:
        return None
    return str(target) if target.is_file() else None


def _process_chunk(run_id: str) -> None:
    with _lock:
        run = _runs.get(run_id)
        if run is None or run.state != RunState.RUNNING:
            return
        queue = _queues.get(run_id, [])
        chunk = queue[:CHUNK_SIZE]
        _queues[run_id] = queue[CHUNK_SIZE:]
    for filename in chunk:
        try:
            facts = analyze_file(run.folder_path, filename)
            unreadable = not facts.raw_text.strip()
            result = evaluate(facts, run.criteria, unreadable=unreadable)
        except Exception:
            from .models import ResumeFacts
            result = evaluate(ResumeFacts(filename=filename), run.criteria, unreadable=True)
        applicant = next((a for a in run.applicants if a.filename == filename), None)
        if applicant is not None and applicant.name:
            result.candidate_name = applicant.name
        with _lock:
            run.results.append(result)
            run.processed += 1
            if result.final_status == FinalStatus.QUALIFIED:
                run.qualified += 1
            elif result.final_status == FinalStatus.NOT_QUALIFIED:
                run.not_qualified += 1
            else:
                run.undetermined += 1
    with _lock:
        remaining = len(_queues.get(run_id, []))
        still_running = run.state == RunState.RUNNING
    if remaining > 0 and still_running:
        # ponytail: short delay between chunks keeps pause/cancel responsive.
        t = threading.Timer(0.3, _process_chunk, args=(run_id,))
        _timers[run_id] = t
        t.daemon = True
        t.start()
    else:
        # Checked under the lock, then _finalize runs outside it: finalizing
        # touches the upload registry and takes the lock itself, and threading.Lock
        # is not reentrant, so calling it while holding the lock would deadlock.
        with _lock:
            should_finalize = run.state == RunState.RUNNING
        if should_finalize:
            _finalize(run)


def _finalize(run: ScreeningRun) -> None:
    try:
        _write_output(run)
    except Exception:
        # The run must leave RUNNING, otherwise the UI polls a finished job forever.
        logger.exception("Run output could not be written: run=%s folder=%s", run.run_id, run.folder_path)
        run.state = RunState.FAILED
        run.error = "تولید گزارش یا پوشهٔ خروجی ناموفق بود؛ نتایج بررسی‌شده در گزارش ثبت نشد. جزئیات کامل در لاگ برنامه است."
        return
    run.state = RunState.FINISHED


def _write_output(run: ScreeningRun) -> None:
    if run.processed == 0 and not run.applicants:
        run.output_path = None
        return
    # Browser uploads use the selected destination or writable user data storage.
    uploaded = _is_uploaded_run(run)
    target = _output_parent(_upload_id_for(run.folder_path)) if uploaded else None
    parent = target if target is not None else Path(run.folder_path)
    out = make_output_dir(str(parent))

    # Copy EVERY processed resume, whatever its status. The viewer opens rejected
    # and undetermined files too, and the staged upload is temporary, so the output
    # folder is the only durable copy. Names may be de-duplicated on collision, so
    # the written names are recorded and served back to the viewer.
    processed = [r.filename for r in run.results if r.filename]
    pairs = copy_resumes(run.folder_path, out, processed)
    _record_output_files(run, dict(pairs))

    missing = len(processed) - len(pairs)
    write_report(run, out, copied_count=len(pairs), missing_count=missing)
    run.output_path = str(out)


def _record_output_files(run: ScreeningRun, mapping: dict[str, str]) -> None:
    with _lock:
        _output_files[run.run_id] = mapping


def _upload_id_for(folder_path: str) -> str | None:
    name = Path(folder_path).name
    with _lock:
        return next((k for k, v in _uploads.items() if v.name == name), None)


def _discard_upload(folder_path: str) -> None:
    """Remove a staging directory once its run no longer needs the input files.

    Matched by directory name: the temporary path may appear as "/var/..." or its
    resolved "/private/var/..." form, so a full-path comparison would miss.
    """
    from . import uploads

    name = Path(folder_path).name
    with _lock:
        entry = next((k for k, v in _uploads.items() if v.name == name), None)
        directory = _uploads.pop(entry, None) if entry else None
    if directory is not None:
        uploads.cleanup_upload(directory)


def sweep_stale_uploads(max_age_seconds: int = 6 * 3600) -> int:
    """Delete staging directories older than the TTL and forget them.

    Runs are unaffected: the output folder already holds every processed resume,
    and staging is only a fallback for rows that somehow missed the copy. Without
    this, an upload that is never processed would sit on disk forever.
    """
    from . import uploads

    root = Path(tempfile.gettempdir()) / "resume-check-uploads"
    with _lock:
        known = {d.name: k for k, d in _uploads.items()}
    removed = 0
    if root.is_dir():
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                age = time.time() - entry.stat().st_mtime
            except OSError:
                continue
            if age > max_age_seconds:
                uploads.cleanup_upload(entry)
                with _lock:
                    key = known.get(entry.name)
                    if key is not None:
                        _uploads.pop(key, None)
                removed += 1
    return removed


def create_run(folder_path: str, criteria: ScreeningCriteria, applicants: list[Applicant] | None = None) -> ScreeningRun:
    folder_path = str(folder_path)
    name = Path(folder_path).name
    with _lock:
        is_upload = any(d.name == name for d in _uploads.values())
    files = ([a.filename for a in applicants if a.download_status == "downloaded"]
             if applicants else list_resume_files(folder_path, recursive=is_upload))
    run_id = uuid.uuid4().hex[:12]
    run = ScreeningRun(run_id=run_id, folder_path=folder_path, criteria=criteria, found=len(files),
                       applicants=applicants or [])
    with _lock:
        _runs[run_id] = run
        _queues[run_id] = files
    _process_chunk(run_id)
    return run


def get_run(run_id: str) -> ScreeningRun | None:
    with _lock:
        return _runs.get(run_id)


def review_resume(run_id: str, filename: str, status: FinalStatus) -> ScreeningRun:
    with _lock:
        run = _runs.get(run_id)
        if run is None:
            raise KeyError("بررسی موردنظر یافت نشد.")
        if run.state not in (RunState.FINISHED, RunState.CANCELLED):
            raise ValueError("ابتدا بررسی رزومه‌ها را پایان دهید.")
        result = next((r for r in run.results if r.filename == filename), None)
        if result is None:
            raise KeyError("رزومه موردنظر یافت نشد.")
        if status not in (FinalStatus.QUALIFIED, FinalStatus.NOT_QUALIFIED, FinalStatus.UNDETERMINED):
            raise ValueError("تصمیم بررسی نامعتبر است.")
        if result.final_status == status:
            raise ValueError("رزومه از قبل همین وضعیت را دارد.")
        decision = {FinalStatus.QUALIFIED: "تأیید دستی", FinalStatus.NOT_QUALIFIED: "رد دستی",
                    FinalStatus.UNDETERMINED: "نیازمند بررسی دستی"}[status]
        reviewed = replace(result, final_status=status, reason=decision + (" — " + result.reason if result.reason else ""))
        results = [reviewed if r is result else r for r in run.results]
        updated = replace(run, results=results,
                          qualified=sum(r.final_status == FinalStatus.QUALIFIED for r in results),
                          not_qualified=sum(r.final_status == FinalStatus.NOT_QUALIFIED for r in results),
                          undetermined=sum(r.final_status == FinalStatus.UNDETERMINED for r in results))
        if not run.output_path:
            raise OSError("Saved report unavailable")
        # Publish the new run only after the atomic workbook replacement succeeds.
        save_review_report(Path(run.output_path) / REPORT_FILENAME, updated)
        _runs[run_id] = updated
        return updated


def pause_run(run_id: str) -> bool:
    with _lock:
        run = _runs.get(run_id)
        if run is None or run.state != RunState.RUNNING:
            return False
        run.state = RunState.PAUSED
        return True


def resume_run(run_id: str) -> bool:
    with _lock:
        run = _runs.get(run_id)
        if run is None or run.state != RunState.PAUSED:
            return False
        run.state = RunState.RUNNING
    _process_chunk(run_id)
    return True


def cancel_run(run_id: str) -> bool:
    with _lock:
        run = _runs.get(run_id)
        if run is None or run.state not in (RunState.RUNNING, RunState.PAUSED):
            return False
        _queues[run_id] = []
        run.state = RunState.CANCELLED
    uploaded = _is_uploaded_run(run)
    target = _output_parent(_upload_id_for(run.folder_path)) if uploaded else None
    with _lock:
        if run.processed > 0 and run.output_path is None:
            try:
                parent = target if target is not None else Path(run.folder_path)
                out = make_output_dir(str(parent))
                processed = [r.filename for r in run.results if r.filename]
                pairs = copy_resumes(run.folder_path, out, processed)
                # The registry lock is already held; do not acquire it again.
                _output_files[run.run_id] = dict(pairs)
                written = [w for _, w in pairs]
                write_report(run, out, copied_count=len(written))
                run.output_path = str(out)
            except Exception:
                logger.exception("Cancelled run output could not be saved: run=%s source=%s destination=%s",
                                 run.run_id, run.folder_path, target)
                run.error = "پوشهٔ خروجی برای رزومه‌های لغوشده ذخیره نشد؛ جزئیات کامل در لاگ برنامه است."
    # The staged copies stay as a fallback, but the output folder now holds every
    # processed resume, so the viewer no longer depends on them.
    return True


def run_to_dict(run: ScreeningRun) -> dict:
    applicants = {a.filename: a for a in run.applicants if a.filename}
    return {
        "runId": run.run_id,
        "state": run.state.value,
        "folderPath": run.folder_path,
        "criteria": {"minYears": run.criteria.min_years},
        "criteriaUsed": _criteria_text(run.criteria),
        "found": run.found,
        "processed": run.processed,
        "qualified": run.qualified,
        "notQualified": run.not_qualified,
        "not_qualified": run.not_qualified,
        "undetermined": run.undetermined,
        "outputPath": run.output_path,
        "error": run.error,
        "reportName": REPORT_FILENAME,
        "results": [
            {
                "filename": r.filename,
                "candidateName": r.candidate_name,
                "jobinjaUrl": applicants[r.filename].jobinja_url if r.filename in applicants else None,
                "applicantId": applicants[r.filename].applicant_id if r.filename in applicants else None,
                "excelRow": applicants[r.filename].excel_row if r.filename in applicants else None,
                "declaredExperienceYears": r.declared_experience_years,
                "experienceSourceText": r.experience_source_text,
                "experienceSourceSection": r.experience_source_section,
                "experienceDetectionStatus": r.experience_detection_status.value,
                "experienceDetectionStatusFa": detection_status_fa(r.experience_detection_status.value),
                "skillsDetected": r.skills_detected,
                "experienceStatus": r.experience_status.value,
                "experienceStatusFa": experience_status_fa(r.experience_status.value),
                "declaredExperienceYearsFa": format_years(r.declared_experience_years),
                "finalStatus": r.final_status.value,
                "finalStatusFa": final_status_fa(r.final_status.value),
                "reason": r.reason,
            }
            for r in run.results
        ],
        "stateFa": run_state_fa(run.state.value),
        "screeningDateJalali": jalali_display_date(),
        "screeningDateJalaliLong": jalali_display_date_long(),
        "criteriaUsedFa": criteria_text(run.criteria),
        "source": "jobinja" if run.applicants else "folder",
        "downloadFailures": [
            {"applicantId": a.applicant_id, "excelRow": a.excel_row,
             "candidateName": a.name, "downloadStatus": a.download_status, "reason": a.download_error}
            for a in run.applicants if a.download_status != "downloaded"
        ],
    }


def _criteria_text(c: ScreeningCriteria) -> str:
    parts = []
    if c.min_years is not None:
        parts.append(f"حداقل {format_years(c.min_years)}")
    return " · ".join(parts) or "(هیچ)"
