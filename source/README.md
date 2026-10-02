# resume-check — frontend (v1)

Static Web UI for bulk resume screening. No framework, no build step, no dependencies.
Served by FastAPI backend as static files; talks to backend REST API only.

## Files

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
