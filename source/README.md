# resume-check — full stack (v1, Persian / RTL)

Static Web UI + FastAPI backend for bulk resume screening. Backend serves the frontend; no build step, no database.

The UI and the Excel report are fully Persian (fa-IR) with RTL layout and Jalali dates.

## Declared experience is the only source for the experience filter

The experience criterion compares **only** the number the candidate explicitly wrote in the resume.

- Never computed from employment dates, job-history spans, graduation year, or age.
- `"2+ years"` is compared as `2`; the `+` never inflates the value.
- `"Over 7 years"` → `7`, `"بیش از ۳ سال"` → `3`, `"حدود ۴ سال"` → `4`.
- A technology-specific claim (`"2+ years of React experience"`) is not read as total professional experience.
- Conflicting general statements resolve to the professional-summary one; when no reliable choice exists the result is `نیازمند بررسی` (Undetermined) rather than a guess.

| Statement | Extracted | Result at minimum 5 |
|---|---|---|
| 2+ years of experience | 2 | رد |
| Over 4 years of experience | 4 | رد |
| 5+ years of experience | 5 | تأیید |
| More than 5 years of experience | 5 | تأیید |
| بیش از ۲ سال سابقه کار | 2 | رد |
| ۱۰ سال سابقه حرفه‌ای | 10 | تأیید |
| Employment dates only | — | نیازمند بررسی |

## Layout

- `frontend/` — static Web UI, RTL (see Files below)
- `backend/app/` — FastAPI backend (`main.py`, `routes_runs.py`, `runner.py`, `extraction.py`, `qualification.py`, `output_writer.py`, `report.py`, `models.py`, `locale.py`)
- `backend/requirements.txt` — Python runtime deps (fastapi, uvicorn, pypdf, python-docx, openpyxl, jdatetime, pytest, httpx)
- `backend/requirements-dev.txt` — test-only deps (reportlab, for generating PDF fixtures)
- `backend/tests/` — pytest suite covering the declared-experience matrix and the filtering matrix

## Prerequisites

- Python 3.11+
- pip

## Start (recommended)

From the project root:

```
./start.sh            # creates .venv, installs deps on first run, serves on :8000
./start.sh 9000       # serve on a different port
./start.sh --reload   # auto-reload on code changes
./start.sh --test     # run the pytest suite
./start.sh --stop     # stop a server started in the background
```

Then open `http://127.0.0.1:8000/`.

## Install manually

```
pip install -r backend/requirements.txt          # runtime
pip install -r backend/requirements-dev.txt      # + test fixtures (reportlab)
```

## Run manually

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

Covers: declared-experience extraction (Latin/Persian/Arabic-Indic digits, written-out numbers, `+`/`over`/`more than`/`بیش از`/`حدود`, source text and section capture, technology-specific exclusion, conflict resolution), strict filtering against the minimum, fuzzy keyword matching, unreadable-file handling, top-level-only scan, empty-folder 422, missing-folder 404, no-criteria 400, full end-to-end run, PDF and DOCX processing, Persian Excel output with RTL sheet and Jalali dates, output-folder collision suffix, pause/resume/cancel.

## API

- `GET /api/health` → `{status: ok}`
- `POST /api/folders/scan` `{folderPath}` → `{fileCount, files}`
- `POST /api/runs` `{folderPath, criteria:{minYears|null, keywords[]}}` → `{runId}`
- `GET /api/runs/{runId}` → `{state, found, processed, qualified, notQualified, undetermined, outputPath, results[]}`
- `POST /api/runs/{runId}/pause`, `/resume`, `/cancel`

Each result carries both machine and Persian fields:

```json
{
  "filename": "candidate_a.docx",
  "declaredExperienceYears": 2,
  "declaredExperienceYearsFa": "۲ سال",
  "experienceSourceText": "I have 2+ years of professional experience.",
  "experienceSourceSection": "Professional Summary",
  "experienceDetectionStatus": "found",
  "experienceDetectionStatusFa": "یافت شد",
  "finalStatus": "Not Qualified",
  "finalStatusFa": "رد",
  "reason": "سابقه کار اعلام‌شده: ۲ سال. ... نتیجه: رد. ..."
}
```

## Files (frontend)

- `frontend/index.html` — setup, progress, results screens (`dir="rtl"`, `lang="fa"`)
- `frontend/styles.css` — RTL layout, Persian typography stack, right-anchored progress fill
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
pytest backend/tests          # 50 passed
node --check source/frontend/js/app_setup.js
node --check source/frontend/js/app_progress.js
node --check source/frontend/js/app_results.js
```

The Web UI was also driven in headless Chrome against a live backend (folder scan → criteria → run → results) to confirm RTL rendering, Persian numerals, and the Jalali date.
