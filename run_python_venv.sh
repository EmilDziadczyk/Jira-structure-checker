#!/usr/bin/env bash

# Uruchamia fetch_jira_issues.py w virtualenv z automatycznym tworzeniem venv.
# Działa z dowolnego miejsca - automatycznie znajduje katalog projektu.

set -Eeuo pipefail

# Znajdź katalog projektu na podstawie lokalizacji tego skryptu
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
Użycie:
  run_python_venv.sh [startDate] [endDate] [numWorkers] [opcje]

Argumenty:
  startDate     Data początkowa w formacie YYYY-MM-DD (wymagane)
  endDate       Data końcowa w formacie YYYY-MM-DD (wymagane)
  numWorkers    Opcjonalna liczba równoległych wątków (domyślnie: 5)

Opcje:
  -l, --log     FILE    Zapisz stdout/stderr do pliku (przydatne pod cron)
      --cron            Tryb pod cron: ustawia bezpieczne minimum środowiska
  -h, --help            Pomoc

Przykłady:
  ./run_python_venv.sh 2024-01-01 2024-12-31
  ./run_python_venv.sh 2024-01-01 2024-12-31 10
  ./run_python_venv.sh 2024-01-01 2024-12-31 --log /tmp/jira-agent.log
USAGE
}

# --- parsowanie argumentów ---
# Najpierw przetwórz wszystkie opcje
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
      echo "❌ Nieznana opcja: $1" >&2
      usage >&2
      exit 1 ;;
    *)
      POSITIONAL_ARGS+=("$1"); shift ;;
  esac
done

# Teraz przetwórz argumenty pozycyjne (daty i workers)
for arg in "${POSITIONAL_ARGS[@]}"; do
  if [[ -z "$START_DATE" ]]; then
    START_DATE="$arg"
  elif [[ -z "$END_DATE" ]]; then
    END_DATE="$arg"
  elif [[ -z "$NUM_WORKERS" ]]; then
    NUM_WORKERS="$arg"
  else
    echo "❌ Zbyt wiele argumentów: $arg" >&2
    usage >&2
    exit 1
  fi
done

# Walidacja wymaganych argumentów
if [[ -z "$START_DATE" ]] || [[ -z "$END_DATE" ]]; then
  echo "❌ Błąd: wymagane są argumenty startDate i endDate" >&2
  usage >&2
  exit 1
fi

# Przygotuj argumenty dla fetch_jira_issues.py
PY_ARGS=("$START_DATE" "$END_DATE")
if [[ -n "$NUM_WORKERS" ]]; then
  PY_ARGS+=("$NUM_WORKERS")
fi

# Używamy domyślnych ścieżek
PYTHON_SCRIPT="$DEFAULT_PYTHON_SCRIPT"

# --- tryb cron ---
# Cron ma ubogie środowisko, więc ustawiamy sensowny PATH i trzymamy się absolutnych ścieżek.
if [[ "$CRON_MODE" -eq 1 ]]; then
  export LANG="${LANG:-en_US.UTF-8}"
  export LC_ALL="${LC_ALL:-en_US.UTF-8}"
  export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
fi

# Jeśli wskazano log, przekieruj cały output (również z activate/python)
if [[ -n "$LOG_FILE" ]]; then
  mkdir -p "$(dirname "$LOG_FILE")"
  exec >>"$LOG_FILE" 2>&1
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_python_venv.sh start ====="
fi

# --- cleanup / trap ---
cleanup() {
  local exit_code=$?
  # deactivate istnieje dopiero po aktywacji; sprawdzamy bezpiecznie
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

# --- walidacje ---
if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "❌ Katalog projektu nie istnieje: $PROJECT_DIR" >&2
  exit 1
fi

# --- auto-tworzenie virtualenv ---
VENV_CREATED=0
if [[ ! -d "$VENV_DIR" ]]; then
  echo "ℹ️  Virtualenv nie istnieje, tworzę nowy: $VENV_DIR"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv "$VENV_DIR"
    VENV_CREATED=1
  elif command -v python >/dev/null 2>&1; then
    python -m venv "$VENV_DIR"
    VENV_CREATED=1
  else
    echo "❌ Nie znaleziono python3 ani python w PATH" >&2
    exit 1
  fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "❌ Virtualenv nie istnieje: $VENV_DIR" >&2
  echo "Utwórz go poleceniem: python3 -m venv '$VENV_DIR'" >&2
  exit 1
fi

if [[ ! -f "$PYTHON_SCRIPT" ]]; then
  echo "❌ Nie znaleziono pliku Pythona: $PYTHON_SCRIPT" >&2
  exit 1
fi

# Pracuj w katalogu projektu (ważne, gdy skrypt używa plików względnych)
cd "$PROJECT_DIR"

# Aktywacja virtualenv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# --- instalacja zależności ---
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
if [[ -f "$REQUIREMENTS_FILE" ]]; then
  # Sprawdź czy pakiety są zainstalowane (sprawdzamy requests jako przykład)
  if [[ "$VENV_CREATED" -eq 1 ]] || ! python -c "import requests" 2>/dev/null; then
    echo "ℹ️  Instalowanie zależności z requirements.txt..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r "$REQUIREMENTS_FILE" --quiet
    echo "✅ Zależności zainstalowane"
  fi
elif [[ "$VENV_CREATED" -eq 1 ]]; then
  # Jeśli venv został właśnie utworzony, ale nie ma requirements.txt, zainstaluj podstawowe pakiety
  echo "ℹ️  Instalowanie podstawowych zależności..."
  python -m pip install --upgrade pip --quiet
  python -m pip install requests python-dotenv --quiet
  echo "✅ Podstawowe zależności zainstalowane"
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
echo "▶️  Uruchamianie fetch_jira_issues.py..."
python "$PYTHON_SCRIPT" "${PY_ARGS[@]}"

echo ""
echo "🏁 Program zakończony"

