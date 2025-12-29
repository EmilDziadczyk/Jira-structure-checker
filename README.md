# Jira Agent

Aplikacja do analizy i wizualizacji zgłoszeń z Jira. Pozwala na przeglądanie zgłoszeń, identyfikację niepodpiętych elementów oraz analizę hierarchii zadań.

## Funkcjonalności

- Pobieranie zgłoszeń z Jira API
- Wizualizacja zgłoszeń w interfejsie webowym
- Identyfikacja niepodpiętych Epików, Stories i Tasków
- Filtrowanie i sortowanie zgłoszeń
- Cache w pamięci dla szybkiego dostępu do danych

## Wymagania

- Python 3.8+
- Dostęp do Jira API (URL, email, token)

## Instalacja

1. Sklonuj repozytorium:
```bash
git clone <repository-url>
cd jira-agent
```

2. Utwórz plik `.env` z konfiguracją:
```
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_TOKEN=your-api-token
PROJECT_KEY=YOUR_PROJECT_KEY
```

3. Zainstaluj zależności (automatycznie przy pierwszym uruchomieniu):
```bash
./run_python_venv.sh 2024-01-01 2024-12-31
```

## Użycie

### Pobieranie danych z Jira

```bash
./run_python_venv.sh <start_date> <end_date> [num_workers]
```

Przykład:
```bash
./run_python_venv.sh 2024-01-01 2024-12-31
```

### Uruchomienie aplikacji webowej

```bash
./run_web_app.sh
```

Aplikacja będzie dostępna pod adresem: http://127.0.0.1:5000

### Opcje uruchomienia aplikacji webowej

```bash
./run_web_app.sh --port 8080
./run_web_app.sh --host 0.0.0.0 --port 8080
```

## Struktura projektu

- `fetch_jira_issues.py` - Skrypt do pobierania zgłoszeń z Jira
- `app.py` - Aplikacja Flask z interfejsem webowym
- `run_python_venv.sh` - Skrypt do uruchamiania fetch_jira_issues.py
- `run_web_app.sh` - Skrypt do uruchamiania aplikacji webowej
- `templates/index.html` - Interfejs użytkownika
- `requirements.txt` - Zależności Python

## Licencja

MIT

