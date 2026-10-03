"""Screening REST API: folder scan, run lifecycle."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import runner
from .extraction import list_resume_files
from .models import ScreeningCriteria

router = APIRouter()


class ScanRequest(BaseModel):
    folderPath: str


class StartRunRequest(BaseModel):
    folderPath: str
    criteria: dict


def _resolve_folder(folder_path: str) -> Path:
    p = Path(folder_path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail="Folder not found.")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a folder.")
    return p


def _parse_criteria(raw: dict) -> ScreeningCriteria:
    min_years = raw.get("minYears", raw.get("min_years"))
    keywords = raw.get("keywords", []) or []
    if min_years is not None:
        try:
            min_years = float(min_years)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="minYears must be a number.")
        if min_years < 0:
            raise HTTPException(status_code=400, detail="minYears must be non-negative.")
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    seen, deduped = set(), []
    for k in keywords:
        if k.lower() not in seen:
            seen.add(k.lower())
            deduped.append(k)
    if min_years is None and not deduped:
        raise HTTPException(status_code=400, detail="At least one screening criterion is required.")
    return ScreeningCriteria(min_years=min_years, keywords=deduped)


@router.post("/folders/scan")
def scan_folder(body: ScanRequest):
    if not body.folderPath or not body.folderPath.strip():
        raise HTTPException(status_code=400, detail="folderPath is required.")
    folder = _resolve_folder(body.folderPath.strip())
    files = list_resume_files(str(folder))
    if not files:
        raise HTTPException(status_code=422, detail="No supported resumes found (top-level .pdf/.docx only).")
    return {"fileCount": len(files), "files": files}


@router.post("/runs")
def start_run(body: StartRunRequest):
    if not body.folderPath or not body.folderPath.strip():
        raise HTTPException(status_code=400, detail="folderPath is required.")
    folder = _resolve_folder(body.folderPath.strip())
    criteria = _parse_criteria(body.criteria or {})
    files = list_resume_files(str(folder))
    if not files:
        raise HTTPException(status_code=422, detail="No supported resumes found.")
    run = runner.create_run(str(folder), criteria)
    return {"runId": run.run_id}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return runner.run_to_dict(run)


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not runner.pause_run(run_id):
        raise HTTPException(status_code=409, detail="Run is not running (already finished or paused).")
    return {"state": "paused"}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not runner.resume_run(run_id):
        raise HTTPException(status_code=409, detail="Run is not paused.")
    return {"state": "running"}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if not runner.cancel_run(run_id):
        raise HTTPException(status_code=409, detail="Run already finished.")
    return runner.run_to_dict(run)
