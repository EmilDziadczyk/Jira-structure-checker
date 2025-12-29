#!/usr/bin/env bash

# Runs Flask web application in virtualenv with automatic venv creation.
# Works from anywhere - automatically finds the project directory.

set -Eeuo pipefail

# Find project directory based on this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
DEFAULT_PYTHON_SCRIPT="$PROJECT_DIR/app.py"
DEFAULT_VENV_DIR="$PROJECT_DIR/venv"

VENV_DIR="$DEFAULT_VENV_DIR"
LOG_FILE=""
CRON_MODE=0
PORT="${PORT:-5000}"
HOST="${HOST:-127.0.0.1}"

usage() {
  cat <<'USAGE'
Usage:
  run_web_app.sh [options]

Options:
  -p, --port PORT    Port to run server on (default: 5000)
  -h, --host HOST    Host to run server on (default: 127.0.0.1)
  -l, --log FILE     Save stdout/stderr to file (useful for cron)
      --cron         Cron mode: sets safe minimum environment
  -h, --help         Help

Examples:
  ./run_web_app.sh
  ./run_web_app.sh --port 8080
  ./run_web_app.sh --host 0.0.0.0 --port 8080
  ./run_web_app.sh --log /tmp/jira-app.log
USAGE
}

# --- argument parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--port)
      PORT="$2"; shift 2 ;;
    --host)
      HOST="$2"; shift 2 ;;
    -l|--log)
      LOG_FILE="$2"; shift 2 ;;
    --cron)
      CRON_MODE=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    -*)
      echo "❌ Unknown option: $1" >&2
      usage >&2
      exit 1 ;;
    *)
      echo "❌ Unexpected argument: $1" >&2
      usage >&2
      exit 1 ;;
  esac
done

# Use default paths
PYTHON_SCRIPT="$DEFAULT_PYTHON_SCRIPT"

# --- cron mode ---
# Cron has a minimal environment, so we set a sensible PATH and stick to absolute paths.
if [[ "$CRON_MODE" -eq 1 ]]; then
  export LANG="${LANG:-en_US.UTF-8}"
  export LC_ALL="${LC_ALL:-en_US.UTF-8}"
  export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
fi

# If log is specified, redirect all output (including from activate/python)
if [[ -n "$LOG_FILE" ]]; then
  mkdir -p "$(dirname "$LOG_FILE")"
  exec >>"$LOG_FILE" 2>&1
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_web_app.sh start ====="
fi

# --- cleanup / trap ---
cleanup() {
  local exit_code=$?
  # deactivate only exists after activation; check safely
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    # shellcheck disable=SC2317
    deactivate || true
  fi
  if [[ -n "$LOG_FILE" ]]; then
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_web_app.sh end (exit=$exit_code) ====="
  fi
  exit "$exit_code"
}
trap cleanup EXIT

# --- validations ---
if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "❌ Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi

# --- auto-create virtualenv ---
VENV_CREATED=0
if [[ ! -d "$VENV_DIR" ]]; then
  echo "ℹ️  Virtualenv does not exist, creating new one: $VENV_DIR"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV_DIR"
    VENV_CREATED=1
  elif command -v python >/dev/null 2>&1; then
    python -m venv "$VENV_DIR"
    VENV_CREATED=1
  else
    echo "❌ python3 or python not found in PATH" >&2
    exit 1
  fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "❌ Virtualenv does not exist: $VENV_DIR" >&2
  echo "Create it with: python3 -m venv '$VENV_DIR'" >&2
  exit 1
fi

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
  echo "❌ Python file not found: $PYTHON_SCRIPT" >&2
  exit 1
fi

# Work in project directory (important when script uses relative files)
cd "$PROJECT_DIR"

# Activate virtualenv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- install dependencies ---
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
if [[ -f "$REQUIREMENTS_FILE" ]]; then
  # Check if packages are installed (check flask as an example)
  if [[ "$VENV_CREATED" -eq 1 ]] || ! python -c "import flask" 2>/dev/null; then
    echo "ℹ️  Installing dependencies from requirements.txt..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r "$REQUIREMENTS_FILE" --quiet
    echo "✅ Dependencies installed"
  fi
elif [[ "$VENV_CREATED" -eq 1 ]]; then
  # If venv was just created but no requirements.txt, install basic packages
  echo "ℹ️  Installing basic dependencies..."
  python -m pip install --upgrade pip --quiet
  python -m pip install flask requests python-dotenv --quiet
  echo "✅ Basic dependencies installed"
fi

echo "✅ Project:    $PROJECT_DIR"
echo "✅ Venv:       $VENV_DIR"
echo "✅ Script:     $PYTHON_SCRIPT"
echo "✅ Python:     $(command -v python)"
echo "✅ Host:       $HOST"
echo "✅ Port:       $PORT"

echo ""
echo "▶️  Running Flask web application..."
echo "🌐 Application will be available at: http://$HOST:$PORT"
echo ""

# Run Flask application
python "$PYTHON_SCRIPT" --host "$HOST" --port "$PORT"

