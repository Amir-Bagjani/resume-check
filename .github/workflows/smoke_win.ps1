# Windows CI smoke test: run ResumeCheck.exe headless, exercise real upload->run->viewer->excel.
#   .\.github\workflows\smoke_win.ps1 -Exe dist\ResumeCheck.exe
param([Parameter(Mandatory=$true)][string]$Exe)
$ErrorActionPreference = "Stop"

$full = (Resolve-Path $Exe).Path
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
python packaging/smoke.py "$full"
if ($LASTEXITCODE -ne 0) { throw "smoke.py failed with exit $LASTEXITCODE" }
Write-Host "Windows smoke test passed."
