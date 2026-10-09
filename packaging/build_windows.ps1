# Build standalone ResumeCheck.exe on Windows 10/11 x64.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $MyInvocation.MyCommand.Path -Parent) -Parent
Set-Location $Root
if (-not (Test-Path .venv-pkg)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3.11 -m venv .venv-pkg }
  else { python -m venv .venv-pkg }
}
. .\.venv-pkg\Scripts\Activate.ps1
pip install --quiet --upgrade pip
pip install --quiet -r source\backend\requirements.txt "pyinstaller==6.22.3"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
pyinstaller --noconfirm packaging\resumecheck.spec
Write-Host "artifact: dist\ResumeCheck.exe"
Write-Host "run: double-click dist\ResumeCheck.exe (no admin, no Python needed)"
