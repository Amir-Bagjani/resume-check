"""Chunked run orchestrator: in-memory registry, chunks of 10, pause/cancel."""
from __future__ import annotations

import tempfile
import threading
import time
import uuid
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
from .models import FinalStatus, ScreeningCriteria, ScreeningRun, RunState
from .output_writer import REPORT_FILENAME, copy_resumes, make_output_dir
from .qualification import evaluate
from .report import criteria_text, write_report

CHUNK_SIZE = 10

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
    """Folder the run should write into, or None to keep results server-side."""
    if not upload_id:
        return None
    with _lock:
        return _output_targets.get(upload_id)


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
        stored = _output_files.get(run_id, {}).get(requested)

    # The output folder, searched by the exact written name first, then by plain
    # basename for runs finalized before the mapping was recorded.
    names: list[str] = []
    if stored:
        names.append(stored)
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
    if run.processed == 0:
        run.output_path = None
        run.state = RunState.FINISHED
        return
    # Results go into the folder the user chose for this upload, exactly like the
    # original local-path flow. With no destination chosen they stay next to the
    # staged files so the UI can download them.
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
    run.state = RunState.FINISHED


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


def create_run(folder_path: str, criteria: ScreeningCriteria) -> ScreeningRun:
    folder_path = str(folder_path)
    name = Path(folder_path).name
    with _lock:
        is_upload = any(d.name == name for d in _uploads.values())
    files = list_resume_files(folder_path, recursive=is_upload)
    run_id = uuid.uuid4().hex[:12]
    run = ScreeningRun(run_id=run_id, folder_path=folder_path, criteria=criteria, found=len(files))
    with _lock:
        _runs[run_id] = run
        _queues[run_id] = files
    _process_chunk(run_id)
    return run


def get_run(run_id: str) -> ScreeningRun | None:
    with _lock:
        return _runs.get(run_id)


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
                _record_output_files(run, dict(pairs))
                written = [w for _, w in pairs]
                write_report(run, out, copied_count=len(written))
                run.output_path = str(out)
            except Exception:
                pass
    # The staged copies stay as a fallback, but the output folder now holds every
    # processed resume, so the viewer no longer depends on them.
    return True


def run_to_dict(run: ScreeningRun) -> dict:
    return {
        "runId": run.run_id,
        "state": run.state.value,
        "folderPath": run.folder_path,
        "criteria": {"minYears": run.criteria.min_years, "keywords": run.criteria.keywords},
        "criteriaUsed": _criteria_text(run.criteria),
        "found": run.found,
        "processed": run.processed,
        "qualified": run.qualified,
        "notQualified": run.not_qualified,
        "not_qualified": run.not_qualified,
        "undetermined": run.undetermined,
        "outputPath": run.output_path,
        "reportName": REPORT_FILENAME,
        "results": [
            {
                "filename": r.filename,
                "candidateName": r.candidate_name,
                "declaredExperienceYears": r.declared_experience_years,
                "experienceSourceText": r.experience_source_text,
                "experienceSourceSection": r.experience_source_section,
                "experienceDetectionStatus": r.experience_detection_status.value,
                "experienceDetectionStatusFa": detection_status_fa(r.experience_detection_status.value),
                "experienceStatus": r.experience_status.value,
                "experienceStatusFa": experience_status_fa(r.experience_status.value),
                "declaredExperienceYearsFa": format_years(r.declared_experience_years),
                "skillsDetected": r.skills_detected,
                "requiredFound": r.required_found,
                "requiredMissing": r.required_missing,
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
    }


def _criteria_text(c: ScreeningCriteria) -> str:
    parts = []
    if c.min_years is not None:
        parts.append(f"حداقل {format_years(c.min_years)}")
    if c.keywords:
        parts.append("فناوری‌ها: " + "، ".join(c.keywords))
    return " · ".join(parts) or "(هیچ)"
