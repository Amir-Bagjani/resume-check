#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PY:-python3}"
"$PY" -m venv .venv-pkg 2>/dev/null || true
. .venv-pkg/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r source/backend/requirements.txt "pyinstaller==6.22.3"
rm -rf build dist
pyinstaller --noconfirm packaging/resumecheck.spec
echo "artifact: dist/ResumeCheck.app (onefile launcher inside .app)"
echo "run: open dist/ResumeCheck.app"
