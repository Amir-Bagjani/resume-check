"""Chunked run orchestrator: in-memory registry, chunks of 10, pause/cancel."""
from __future__ import annotations

import threading
import uuid
from pathlib import Path

from .extraction import analyze_file, list_resume_files
from .models import FinalStatus, ResumeResult, ScreeningCriteria, ScreeningRun, RunState
from .output_writer import copy_qualified, make_output_dir
from .qualification import evaluate
from .report import REPORT_FILENAME, write_report

CHUNK_SIZE = 10

_runs: dict[str, ScreeningRun] = {}
_queues: dict[str, list[str]] = {}
_lock = threading.Lock()
_timers: dict[str, threading.Timer] = {}


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
        with _lock:
            if run.state == RunState.RUNNING:
                _finalize(run)


def _finalize(run: ScreeningRun) -> None:
    if run.processed == 0:
        run.output_path = None
        run.state = RunState.FINISHED
        return
    out = make_output_dir(run.folder_path)
    qualified = [r.filename for r in run.results if r.final_status == FinalStatus.QUALIFIED]
    copy_qualified(run.folder_path, out, qualified)
    write_report(run, out)
    run.output_path = str(out)
    run.state = RunState.FINISHED


def create_run(folder_path: str, criteria: ScreeningCriteria) -> ScreeningRun:
    files = list_resume_files(folder_path)
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
    with _lock:
        if run.processed > 0 and run.output_path is None:
            try:
                out = make_output_dir(run.folder_path)
                qualified = [r.filename for r in run.results if r.final_status == FinalStatus.QUALIFIED]
                copy_qualified(run.folder_path, out, qualified)
                write_report(run, out)
                run.output_path = str(out)
            except Exception:
                pass
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
                "estimatedYears": r.estimated_years,
                "experienceStatus": r.experience_status.value,
                "skillsDetected": r.skills_detected,
                "requiredFound": r.required_found,
                "requiredMissing": r.required_missing,
                "finalStatus": r.final_status.value,
                "reason": r.reason,
            }
            for r in run.results
        ],
    }


def _criteria_text(c: ScreeningCriteria) -> str:
    parts = []
    if c.min_years is not None:
        parts.append(f"min {c.min_years} yrs")
    if c.keywords:
        parts.append("keywords: " + ", ".join(c.keywords))
    return " · ".join(parts) or "(none)"
