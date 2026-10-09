# Windows CI smoke test: run ResumeCheck.exe headless, exercise real upload->run->viewer->excel.
#   .\.github\workflows\smoke_win.ps1 -Exe dist\ResumeCheck.exe
param([Parameter(Mandatory=$true)][string]$Exe)
$ErrorActionPreference = "Stop"

$full = (Resolve-Path $Exe).Path
py -3.11 -m pip install --quiet --upgrade pip
py -3.11 -m pip install --quiet python-docx
$env:RESUMECHECK_HEADLESS = "1"
$proc = Start-Process -FilePath $full -PassThru -RedirectStandardOutput smoke-server.log -RedirectStandardError smoke-server-err.log

try {
  py -3.11 packaging/smoke.py $full
  if ($LASTEXITCODE -ne 0) { throw "smoke.py failed with exit $LASTEXITCODE" }
} finally {
  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
  }
}
Write-Host "Windows smoke test passed."
