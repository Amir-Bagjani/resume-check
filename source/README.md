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

Folder-upload UI checks use Node.js 22+ with no npm dependencies. From the project
root:

```
node --test source/frontend/tests/setup.test.cjs
```

These check file/count/total-size limits before the upload request, Persian paths,
network failures, retrying folder selection, and server permission messages.
The release workflow runs both suites on Windows, macOS, and Linux before building
and testing each standalone artifact; see `../packaging/README.md`.

Covers: declared-experience extraction (Latin/Persian/Arabic-Indic digits, written-out numbers, `+`/`over`/`more than`/`بیش از`/`حدود`, source text and section capture, technology-specific exclusion, conflict resolution), strict filtering against the minimum, unreadable-file handling, top-level-only scan, empty-folder 422, missing-folder 404, no-criteria 400, full end-to-end run, PDF and DOCX processing, Persian Excel output with RTL sheet and Jalali dates, output-folder collision suffix, pause/resume/cancel.

## API

- `GET /api/health` → `{status: ok}`
- `POST /api/folders/scan` `{folderPath}` → `{fileCount, files}`
- `POST /api/runs` `{folderPath, criteria:{minYears}}` → `{runId}`
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
- `frontend/js/app_setup.js` — folder/Jobinja upload, minimum experience, start gating
- `frontend/js/app_progress.js` — 2s polling, pause/resume/cancel
- `frontend/js/app_results.js` — summary cards, output path, filterable table

## API contracts consumed

- `POST /api/folders/scan` `{folderPath}` → `{fileCount, files?}`
- `POST /api/runs` `{folderPath, criteria:{minYears}}` → `{runId}`
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


## Jobinja Excel input

The setup screen supports both the existing PDF/DOCX folder picker and a Jobinja
XLSX export. Only the required minimum declared experience filters applicants;
detected technologies remain informational in the report. `2+`, `5+`, and `7+`
remain 2, 5, and 7 years; employment dates are not summed.

The first worksheet is read without relying on its name or fixed column numbers.
Hyperlink targets, literal `HYPERLINK` formulas, and URL text are supported. The
provided seven-column Jobinja export (524 applicants) is supported. Imports allow
up to 2,000 applicants; ordinary folder uploads retain their 500-file limit.

- `POST /api/jobinja/imports` — multipart `file`, an XLSX up to 10 MB; reads links
  without starting downloads.
- `POST /api/jobinja/imports/{id}/run` — `{criteria: {minYears: 5}}`; downloads then
  calls the existing screening runner.
- `GET /api/jobinja/imports/{id}` — real completed/downloaded/failed counts and
  the screening `runId` when ready.
- `POST /api/jobinja/imports/{id}/cancel` — stops subsequent downloads or cancels
  screening after the run starts.

Download the original applicant HTML URL unchanged, then follow the actual
`دانلود` anchor to Jobinja or its `jobinjacdn.com` storage. Requests use a browser
User-Agent, HTML Accept and Persian language headers, bounded gzip decoding, and
an in-memory cookie session per applicant (including redirects and downloads).
Download requests send the page Referer; cross-origin requests send only its
origin, excluding signed query strings. Cookies follow their domain/path rules
and are discarded after each applicant. When Jobinja returns its JavaScript
waiting page (`__arcsjs`), the waiting page is solved in-process: its two
obfuscated strings are evaluated and the `__arcsjs`/`__arcsjsc` cookies are set
for `jobinja.ir`, then the same URL is requested again — no browser is needed.
If the page template ever changes shape, the solver reports it and the optional
Playwright fallback opens an isolated headless **installed Chrome or Microsoft
Edge**, executes the page, waits up to 20 seconds for the download link, and
transfers its cookies to the existing downloader. Playwright is a dev dependency
(`backend/requirements-dev.txt`), not a runtime one: without it the app still
works and the UI says the browser fallback is unavailable. Browser requests and
HTTP redirects are checked against the same allowed domains and public DNS
addresses; service workers and WebSockets are blocked. No account login, personal
browser profile or browser installation/download is performed. Cookie values
never reach the trace or the report.
Install backend requirements when running from source. If neither Chrome nor
Edge can launch, the UI reports that requirement with the request trace.
**Run real Jobinja downloads through an internet connection inside Iran.** Missing download
links are reported as receipt errors, never as experience decisions. The original
URL is intentionally available in the Jobinja button and report, and is excluded
from diagnostics.

Expand **جزئیات خطاها و گزارش دریافت** in the results to read and copy the
failed applicant's request trace: request host, system proxy use, DNS check,
HTTP status/redirects, content type/encoding, bounded byte counts, download-link
counts and HTML script/login/challenge hints. Network failures include exception
class, errno and TLS verification code. Paths, signed queries, cookies and raw
HTML/resume content are excluded; hints are clues rather than a diagnosis.

Every successfully downloaded file is validated as PDF/DOCX, staged under a
unique name, and processed by the shared runner. The report preserves applicant
IDs, Excel row numbers, names, links, download status, and evaluation results; a
separate `دریافت رزومه‌ها` worksheet also includes failed receipts. ZIP includes
only successfully received and processed files, across all evaluation statuses.

Focused checks (no real applicant downloads):

```sh
PYTHONPATH=source python -m pytest source/backend/tests/test_jobinja.py source/backend/tests/test_zip.py -q
node --test source/frontend/tests/setup.test.cjs source/frontend/tests/jobinja.test.cjs source/frontend/tests/zip.test.cjs
python packaging/smoke.py /path/to/ResumeCheck --zip-only
```

The packaged smoke test validates real downloaded ZIP contents, the new XLSX API,
a failed-download report, and the bundled Persian font without contacting Jobinja.
All three standalone platforms need rebuilding to include these changes.
