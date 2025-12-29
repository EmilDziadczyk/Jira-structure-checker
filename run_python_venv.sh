#!/usr/bin/env bash

# Runs fetch_jira_issues.py in virtualenv with automatic venv creation.
# Works from anywhere - automatically finds the project directory.

set -Eeuo pipefail

# Find project directory based on this script's location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
DEFAULT_PYTHON_SCRIPT="$PROJECT_DIR/fetch_jira_issues.py"
DEFAULT_VENV_DIR="$PROJECT_DIR/venv"

VENV_DIR="$DEFAULT_VENV_DIR"
LOG_FILE=""
CRON_MODE=0
START_DATE=""
END_DATE=""
NUM_WORKERS=""

usage() {
  cat <<'USAGE'
Usage:
  run_python_venv.sh [startDate] [endDate] [numWorkers] [options]

Arguments:
  startDate     Start date in YYYY-MM-DD format (required)
  endDate       End date in YYYY-MM-DD format (required)
  numWorkers    Optional number of parallel threads (default: 5)

Options:
  -l, --log     FILE    Save stdout/stderr to file (useful for cron)
      --cron            Cron mode: sets safe minimum environment
  -h, --help            Help

Examples:
  ./run_python_venv.sh 2024-01-01 2024-12-31
  ./run_python_venv.sh 2024-01-01 2024-12-31 10
  ./run_python_venv.sh 2024-01-01 2024-12-31 --log /tmp/jira-agent.log
USAGE
}

# --- argument parsing ---
# First process all options
POSITIONAL_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
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
      POSITIONAL_ARGS+=("$1"); shift ;;
  esac
done

# Now process positional arguments (dates and workers)
for arg in "${POSITIONAL_ARGS[@]}"; do
  if [[ -z "$START_DATE" ]]; then
    START_DATE="$arg"
  elif [[ -z "$END_DATE" ]]; then
    END_DATE="$arg"
  elif [[ -z "$NUM_WORKERS" ]]; then
    NUM_WORKERS="$arg"
  else
    echo "❌ Too many arguments: $arg" >&2
    usage >&2
    exit 1
  fi
done

# Validate required arguments
if [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
  echo "❌ Error: startDate and endDate arguments are required" >&2
  usage >&2
  exit 1
fi

# Prepare arguments for fetch_jira_issues.py
PY_ARGS=("$START_DATE" "$END_DATE")
if [[ -n "$NUM_WORKERS" ]]; then
  PY_ARGS+=("$NUM_WORKERS")
fi

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
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_python_venv.sh start ====="
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
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_python_venv.sh end (exit=$exit_code) ====="
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
  # Check if packages are installed (check requests as an example)
  if [[ "$VENV_CREATED" -eq 1 ]] || ! python -c "import requests" 2>/dev/null; then
    echo "ℹ️  Installing dependencies from requirements.txt..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r "$REQUIREMENTS_FILE" --quiet
    echo "✅ Dependencies installed"
  fi
elif [[ "$VENV_CREATED" -eq 1 ]]; then
  # If venv was just created but no requirements.txt, install basic packages
  echo "ℹ️  Installing basic dependencies..."
  python -m pip install --upgrade pip --quiet
  python -m pip install requests python-dotenv --quiet
  echo "✅ Basic dependencies installed"
fi

echo "✅ Project:    $PROJECT_DIR"
echo "✅ Venv:       $VENV_DIR"
echo "✅ Script:     $PYTHON_SCRIPT"
echo "✅ Python:     $(command -v python)"
echo "✅ Start Date: $START_DATE"
echo "✅ End Date:   $END_DATE"
if [[ -n "$NUM_WORKERS" ]]; then
  echo "✅ Workers:    $NUM_WORKERS"
fi

echo ""
echo "▶️  Running fetch_jira_issues.py..."
python "$PYTHON_SCRIPT" "${PY_ARGS[@]}"

echo ""
echo "🏁 Program finished"

