# resume-check — full stack (v1)

Static Web UI + FastAPI backend for bulk resume screening. Backend serves the frontend; no build step, no database.

## Layout

- `frontend/` — static Web UI (see Files below)
- `backend/app/` — FastAPI backend (`main.py`, `routes_runs.py`, `runner.py`, `extraction.py`, `qualification.py`, `output_writer.py`, `report.py`, `models.py`)
- `backend/requirements.txt` — Python deps (fastapi, uvicorn, pypdf, python-docx, openpyxl, jdatetime, pytest, httpx)
- `backend/tests/` — pytest suite covering AC-001–AC-016 matrix

## Prerequisites

- Python 3.11+
- pip

## Install

```
pip install -r backend/requirements.txt
```

## Run (development)

From the `source/` directory:

```
uvicorn backend.app.main:app --reload
```

Open `http://127.0.0.1:8000/` — the Web UI is served at `/`, API under `/api`.

## Run tests

From the `source/` directory:

```
pytest backend/tests
```

Covers: experience estimator (pass/fail/unknown), fuzzy keyword matching (React variants, Vue-only miss), qualification matrix, unreadable-file Undetermined, top-level-only scan, empty-folder 422, missing-folder 404, no-criteria 400, full end-to-end run (Jalali folder, qualified-only copy, xlsx report, originals untouched), collision suffix, pause/resume/cancel.

> Note: tests were written but not executed in this environment (no Python runtime available). Run `pytest backend/tests` where Python 3.11+ exists before approval.

## API

- `GET /api/health` → `{status: ok}`
- `POST /api/folders/scan` `{folderPath}` → `{fileCount, files}`
- `POST /api/runs` `{folderPath, criteria:{minYears|null, keywords[]}}` → `{runId}`
- `GET /api/runs/{runId}` → `{state, found, processed, qualified, notQualified, undetermined, outputPath, results[]}`
- `POST /api/runs/{runId}/pause`, `/resume`, `/cancel`

## Files (frontend)

- `frontend/index.html` — setup, progress, results screens
- `frontend/styles.css` — responsive layout (single column under 720px)
- `frontend/js/app_setup.js` — folder scan, criteria chips, start gating
- `frontend/js/app_progress.js` — 2s polling, pause/resume/cancel
- `frontend/js/app_results.js` — summary cards, output path, filterable table

## API contracts consumed

- `POST /api/folders/scan` `{folderPath}` → `{fileCount, files?}`
- `POST /api/runs` `{folderPath, criteria:{minYears|null, keywords[]}}` → `{runId}`
- `GET /api/runs/{runId}` → `{state, found, processed, qualified, notQualified|not_qualified, undetermined, outputPath?, reportName?|reportFile?, criteria?|criteriaUsed?, screeningDateJalali?|screeningDate?, results[]}`
- `POST /api/runs/{runId}/pause`, `/resume`, `/cancel`

## Preview

Serve this directory with any static server (backend mounts it in production).
No install or build needed.

## Verification

Commands actually run:

```
node --check source/frontend/js/app_setup.js
node --check source/frontend/js/app_progress.js
node --check source/frontend/js/app_results.js
```

All three passed. `index.html` has no inline JS; manual browser check against stub API still required (backend not in this stage's scope).
