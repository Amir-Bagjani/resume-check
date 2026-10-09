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
builds on `windows-latest` / `macos-latest` / `ubuntu-latest`, runs a real
headless smoke test of the produced binary (upload Unicode-named DOCX → run →
viewer → Excel → shutdown), then uploads one artifact per OS:

| Artifact | File |
|---|---|
| `resumecheck-Windows` | `ResumeCheck.exe` |
| `resumecheck-macOS` | `ResumeCheck.app` |
| `resumecheck-Linux` | `ResumeCheck` |

Manual trigger: repo → Actions → `build-standalone` → Run workflow.
Tag release: `git tag v1.0.0 && git push origin v1.0.0`.

## End-user run

1. Double-click `ResumeCheck.exe` / `ResumeCheck.app` / `ResumeCheck`.
2. Browser opens automatically at `http://127.0.0.1:<port>/`.
3. Pick the resume folder, set criteria, run, view results, download Excel.
4. A small window stays open while the app runs — use **خروج از برنامه** to stop it.
   Closing the browser tab does NOT stop the backend; use the window's exit button.

Data dirs (logs, single-instance lock): `%LOCALAPPDATA%\ResumeCheck`,
`~/Library/Application Support/ResumeCheck`, `~/.local/share/resume-check`.

## Notes / limits

- Windows/macOS show an unknown-publisher warning until the binary is code-signed
  (SmartScreen / Gatekeeper). No signing configured yet.
- Needs `python3 -m venv` working on the build machine (python.org / Xcode CLT).
- Dev flow unchanged: `./start.sh` still serves from source.
