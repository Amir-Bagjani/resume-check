# Build standalone ResumeCheck.exe on Windows 10/11 x64.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Python C:\...\python.exe
# With -Python the script reuses an existing interpreter (what CI does after
# installing the packaging dependencies) instead of creating .venv-pkg again.
param([string]$Python = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
Set-Location $Root
if (-not $Python) {
  $Python = Join-Path $Root ".venv-pkg\Scripts\python.exe"
  if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv-pkg }
    else { python -m venv .venv-pkg }
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv-pkg. Install Python 3.11 with pip and Tkinter." }
  }
  & $Python -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) { throw "pip setup failed." }
  & $Python -m pip install -r source\backend\requirements.txt "pyinstaller==6.22.3"
  if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
}
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Python -m PyInstaller --noconfirm packaging\resumecheck.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
if (-not (Test-Path "dist\ResumeCheck.exe")) { throw "PyInstaller finished without dist\ResumeCheck.exe" }
Write-Host "artifact: dist\ResumeCheck.exe"
Write-Host "run: double-click dist\ResumeCheck.exe (no admin, no Python needed)"