# ResumeCheck — Standalone Build

Python 3.11 recommended. Each target builds on its own OS (no cross-compile).

| OS | Command | Output |
|---|---|---|
| Windows 10/11 x64 | `powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1` | `dist\ResumeCheck.exe` |
| macOS 11+ | `bash packaging/build_macos.sh` | `dist/ResumeCheck.app` + `dist/ResumeCheck` |
| Linux | `bash packaging/build_linux.sh` | `dist/ResumeCheck` |

## Exact local build

Windows (PowerShell, Python 3.11 from python.org with **tcl/tk and Tkinter** checked):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# artifact: dist\ResumeCheck.exe
```

macOS / Linux:

```bash
bash packaging/build_macos.sh   # dist/ResumeCheck.app + dist/ResumeCheck
bash packaging/build_linux.sh   # dist/ResumeCheck
```

Both scripts create `.venv-pkg`, pin `pyinstaller==6.22.3` plus pinned
`source/backend/requirements.txt`, then run the shared `resumecheck.spec`.

## CI build (no local Windows needed)

Release builds via tag push (`v*`) or manual run: `.github/workflows/build.yml`
builds on `windows-latest` / `macos-15-intel` (x86_64) / `macos-15` (arm64) /
`ubuntu-latest`, runs a real
backend/launcher test suite on each OS, then a headless smoke test of the produced
binary (12 DOCX resumes, Persian names, subfolders, case/sanitization collisions,
Windows reserved names, and a file over 1 MB → run → byte-identical downloads →
readable Persian Excel). An artifact is uploaded only after both checks pass:

| Artifact | File |
|---|---|
| `resumecheck-Windows` | `ResumeCheck.exe` |
| `resumecheck-macOS-x64` | `ResumeCheck.app` (Intel) |
| `resumecheck-macOS-arm64` | `ResumeCheck.app` (Apple Silicon) |
| `resumecheck-Linux` | `ResumeCheck` |

Each macOS job checks the runner and Python architecture before building. The
shared PyInstaller spec targets the running Python architecture (`target_arch=None`)
and validates native extension compatibility. CI checks the bundled executable with
`file` and `lipo` before smoke testing and uploading, rejecting a mismatched build.
Artifacts are downloaded from the Actions run; this workflow does not publish
GitHub Release assets. Standard macOS ARM64 runners support public and private
repositories, subject to the repository's Actions policies and available minutes.

Manual trigger: repo → Actions → `build-standalone` → Run workflow.
Tag release: `git tag v1.0.0 && git push origin v1.0.0`.

Run the same binary check locally after a build (with the source requirements
installed in the Python environment used for the test):

```powershell
python packaging/smoke.py dist\ResumeCheck.exe
```

On Linux: `python packaging/smoke.py ./dist/ResumeCheck`.
The smoke test uses isolated app data on Windows/Linux and stops its own process
tree after checking the output.

## End-user run

1. Double-click `ResumeCheck.exe` / `ResumeCheck.app` / `ResumeCheck`.
2. Browser opens automatically at `http://127.0.0.1:<port>/`.
3. Pick the resume folder, set criteria, run, view results, download Excel.
4. A small window stays open while the app runs — use **خروج از برنامه** to stop it.
   Closing the browser tab does NOT stop the backend; use the window's exit button.

When updating, exit the old app first, then launch the newly built executable and
use its browser URL. An existing instance otherwise keeps serving the old version.

PDF resumes render inside the existing preview dialog using locally bundled
PDF.js 6.3.289, including its worker, fonts and image decoders. This works offline
and does not use the browser's native PDF handler. Preview bytes use a separate
binary POST endpoint without PDF/download headers; explicit downloads still use
the original download link. Scrolling, text selection and zoom stay in the dialog.
Closing or switching previews aborts loading and releases the document worker.
DOCX previews keep the existing download fallback.

## Upload troubleshooting (Windows)

- Input resumes must be PDF or DOCX; Excel is the output format.
- Keep the ResumeCheck window open while selecting and processing files.
- Each file is limited to 32 MB, with at most 500 files and 512 MB total per upload.
- For a network/upload error, verify that the selected files are locally readable
  (download cloud-only files first), then choose the folder again.
- Disk/permission errors return a Persian message. Exception details are logged
  at `%LOCALAPPDATA%\ResumeCheck\logs\server.log`; local health checks bypass the
  system proxy. Check this log when reporting a failure.

Filename sanitization avoids Windows device names and adds suffixes on collisions,
including names differing only by case. Original input files are never renamed.

Data dirs (logs, single-instance lock): `%LOCALAPPDATA%\ResumeCheck`,
`~/Library/Application Support/ResumeCheck`, `~/.local/share/resume-check`.

## Notes / limits

- Windows/macOS show an unknown-publisher warning until the binary is code-signed
  (SmartScreen / Gatekeeper). No signing configured yet.
- Needs `python3 -m venv` working on the build machine (python.org / Xcode CLT).
- Dev flow unchanged: `./start.sh` still serves from source.
