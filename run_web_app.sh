#!/usr/bin/env bash

# Uruchamia aplikację webową Flask w virtualenv z automatycznym tworzeniem venv.
# Działa z dowolnego miejsca - automatycznie znajduje katalog projektu.

set -Eeuo pipefail

# Znajdź katalog projektu na podstawie lokalizacji tego skryptu
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
Użycie:
  run_web_app.sh [opcje]

Opcje:
  -p, --port PORT    Port na którym uruchomić serwer (domyślnie: 5000)
  -h, --host HOST    Host na którym uruchomić serwer (domyślnie: 127.0.0.1)
  -l, --log FILE     Zapisz stdout/stderr do pliku (przydatne pod cron)
      --cron         Tryb pod cron: ustawia bezpieczne minimum środowiska
  -h, --help         Pomoc

Przykłady:
  ./run_web_app.sh
  ./run_web_app.sh --port 8080
  ./run_web_app.sh --host 0.0.0.0 --port 8080
  ./run_web_app.sh --log /tmp/jira-app.log
USAGE
}

# --- parsowanie argumentów ---
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
      echo "❌ Nieznana opcja: $1" >&2
      usage >&2
      exit 1 ;;
    *)
      echo "❌ Nieoczekiwany argument: $1" >&2
      usage >&2
      exit 1 ;;
  esac
done

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
  echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_web_app.sh start ====="
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
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') run_web_app.sh end (exit=$exit_code) ====="
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
  # Sprawdź czy pakiety są zainstalowane (sprawdzamy flask jako przykład)
  if [[ "$VENV_CREATED" -eq 1 ]] || ! python -c "import flask" 2>/dev/null; then
    echo "ℹ️  Instalowanie zależności z requirements.txt..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r "$REQUIREMENTS_FILE" --quiet
    echo "✅ Zależności zainstalowane"
  fi
elif [[ "$VENV_CREATED" -eq 1 ]]; then
  # Jeśli venv został właśnie utworzony, ale nie ma requirements.txt, zainstaluj podstawowe pakiety
  echo "ℹ️  Instalowanie podstawowych zależności..."
  python -m pip install --upgrade pip --quiet
  python -m pip install flask requests python-dotenv --quiet
  echo "✅ Podstawowe zależności zainstalowane"
fi

echo "✅ Project:    $PROJECT_DIR"
echo "✅ Venv:       $VENV_DIR"
echo "✅ Script:     $PYTHON_SCRIPT"
echo "✅ Python:     $(command -v python)"
echo "✅ Host:       $HOST"
echo "✅ Port:       $PORT"

echo ""
echo "▶️  Uruchamianie aplikacji webowej Flask..."
echo "🌐 Aplikacja będzie dostępna pod adresem: http://$HOST:$PORT"
echo ""

# Uruchom aplikację Flask
python "$PYTHON_SCRIPT" --host "$HOST" --port "$PORT"

