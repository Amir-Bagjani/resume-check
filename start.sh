#!/usr/bin/env bash
# Start Resume Check (FastAPI backend + static Persian UI) on a local port.
#
#   ./start.sh              install deps if needed, then serve on :8000
#   ./start.sh 9000         serve on :9000
#   ./start.sh --reload     auto-reload on code changes
#   ./start.sh --test       run the pytest suite instead of serving
#   ./start.sh --stop       stop a server previously started in the background
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$ROOT/source"
VENV="$ROOT/.venv"
REQUIREMENTS="$SOURCE_DIR/backend/requirements.txt"
DEV_REQUIREMENTS="$SOURCE_DIR/backend/requirements-dev.txt"
PID_FILE="$ROOT/.server.pid"
LOG_FILE="$ROOT/.server.log"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11

PORT=8000
RELOAD=0
MODE="serve"

log()  { printf '\033[0;36m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[0;32m  ok\033[0m %s\n' "$1"; }
warn() { printf '\033[0;33m  !!\033[0m %s\n' "$1"; }
die()  { printf '\033[0;31merror:\033[0m %s\n' "$1" >&2; exit 1; }

usage() {
  # Print the header comment block (lines 2-8), dropping the shebang.
  sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

# ---------------------------------------------------------------- arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reload)  RELOAD=1; shift ;;
    --test)    MODE="test"; shift ;;
    --stop)    MODE="stop"; shift ;;
    --help|-h) usage ;;
    -*)        die "unknown option: $1 (try --help)" ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then PORT="$1"; shift
      else die "expected a port number, got: $1"; fi
      ;;
  esac
done

# ------------------------------------------------------------------- python
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python $MIN_PY_MAJOR.$MIN_PY_MINOR+ and retry."

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
  found="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  die "Python $found found but $MIN_PY_MAJOR.$MIN_PY_MINOR+ is required."
fi

# --------------------------------------------------------------- stop mode
stop_server() {
  local stopped=0
  if [[ -f "$PID_FILE" ]]; then
    local pid; pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" && stopped=1
      ok "stopped server (pid $pid)"
    fi
    rm -f "$PID_FILE"
  fi
  # Catch any process still holding the port, not just the recorded pid.
  local holding
  holding="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$holding" ]]; then
    kill $holding 2>/dev/null && stopped=1
    ok "freed port $PORT (pid: $holding)"
  fi
  if [[ $stopped -eq 0 ]]; then
    log "no running server found"
  fi
  return 0
}

if [[ "$MODE" == "stop" ]]; then
  stop_server
  exit 0
fi

# -------------------------------------------------------------- virtualenv
if [[ ! -d "$VENV" ]]; then
  log "creating virtualenv at .venv"
  python3 -m venv "$VENV"
  ok "virtualenv created"
fi

PY="$VENV/bin/python"
[[ -x "$PY" ]] || die "virtualenv is broken: $PY not found. Delete .venv and retry."

# ------------------------------------------------------------------ deps
if ! "$PY" -c "import fastapi, uvicorn, docx, openpyxl, pypdf, jdatetime" 2>/dev/null; then
  log "installing dependencies (this runs once)"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r "$REQUIREMENTS"
  [[ -f "$DEV_REQUIREMENTS" ]] && "$PY" -m pip install --quiet -r "$DEV_REQUIREMENTS"
  ok "dependencies installed"
else
  ok "dependencies already satisfied"
fi

# -------------------------------------------------------------- test mode
if [[ "$MODE" == "test" ]]; then
  log "running pytest suite"
  cd "$SOURCE_DIR"
  exec "$PY" -m pytest backend/tests "$@"
fi

# ------------------------------------------------------------------ serve
[[ -d "$SOURCE_DIR/backend/app" ]] || die "backend not found at $SOURCE_DIR/backend/app"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  die "port $PORT is already in use. Run './start.sh --stop' or pick another port."
fi

cd "$SOURCE_DIR"

ARGS=(backend.app.main:app --host 127.0.0.1 --port "$PORT")
[[ $RELOAD -eq 1 ]] && ARGS+=(--reload)

if [[ -t 1 ]]; then
  # Foreground with a clean Ctrl+C.
  trap 'printf "\n"; log "shutting down"; exit 0' INT
  log "Resume Check is starting on http://127.0.0.1:$PORT/"
  log "press Ctrl+C to stop"
  printf '\n'
  exec "$PY" -m uvicorn "${ARGS[@]}"
else
  # Non-interactive shell: run in the background and leave it serving.
  nohup "$PY" -m uvicorn "${ARGS[@]}" >"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  for _ in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      ok "server healthy (pid $(cat "$PID_FILE"))"
      log "UI:      http://127.0.0.1:$PORT/"
      log "API:     http://127.0.0.1:$PORT/api/health"
      log "logs:    $LOG_FILE"
      log "stop:    ./start.sh --stop"
      exit 0
    fi
    sleep 0.25
  done

  warn "server did not report healthy in time; last log lines:"
  tail -n 20 "$LOG_FILE" >&2 || true
  exit 1
fi