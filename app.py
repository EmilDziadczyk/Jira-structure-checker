import json
import os
from collections import Counter
from dotenv import load_dotenv
from functools import lru_cache

from flask import Flask, render_template, abort, jsonify

load_dotenv()

app = Flask(__name__)

DATA_FILE = "jira_issues_raw.json"  # or "jira_issues.json" if you renamed it
JIRA_URL = os.getenv("JIRA_URL", "")

# Cache dla danych
_issues_cache = None
_file_mtime = None
_unlinked_cache = {}  # Cache dla wyników get_unlinked_issues: {issue_type: result}
_all_by_type_cache = {}  # Cache dla wyników get_all_issues_by_type: {issue_type: result}


def load_issues():
    """
    Ładuje dane z pliku JSON z cache'owaniem w pamięci.
    Cache jest automatycznie odświeżany, gdy plik się zmieni.
    """
    global _issues_cache, _file_mtime
    
    if not os.path.exists(DATA_FILE):
        abort(500, f"Data file {DATA_FILE} not found. Run fetch_jira_issues.py first.")
    
    # Sprawdź czas modyfikacji pliku
    current_mtime = os.path.getmtime(DATA_FILE)
    
    # Jeśli cache jest pusty lub plik się zmienił, załaduj dane
    if _issues_cache is None or _file_mtime != current_mtime:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _issues_cache = json.load(f)
        _file_mtime = current_mtime
        # Wyczyść cache wyników funkcji, gdy dane się zmieniły
        _unlinked_cache.clear()
        _all_by_type_cache.clear()
    
    return _issues_cache


def get_expected_parent_type(issue_type):
    """
    Zwraca oczekiwany typ parenta dla danego typu issue.
    """
    if issue_type == "Epic":
        return "Initiative"
    elif issue_type in ["Story", "Task", "Bug", "Spike", "Documentation"]:
        return "Epic"
    elif issue_type == "Sub-task":
        return "Story/Task"
    return None


def has_correct_parent(issue_type, parent):
    """
    Sprawdza czy issue ma odpowiedniego parenta zgodnie z hierarchią.
    """
    if not parent:
        return False
    
    parent_type = parent.get("fields", {}).get("issuetype", {}).get("name", "")
    expected = get_expected_parent_type(issue_type)
    
    if issue_type == "Epic":
        return parent_type == "Initiative"
    elif issue_type in ["Story", "Task", "Bug", "Spike", "Documentation"]:
        return parent_type == "Epic"
    elif issue_type == "Sub-task":
        return parent_type in ["Story", "Task"]
    
    return False


def count_issues_by_type(issues):
    """
    Liczy zgłoszenia według typu i zwraca informacje o niepodpiętych.
    
    Returns:
        dict z kluczami typu issue, wartościami zawierającymi:
        - total: całkowita liczba zgłoszeń tego typu
        - unlinked: liczba niepodpiętych zgłoszeń
        - expected_parent: typ oczekiwanego parenta (lub None)
    """
    result = {}
    
    for issue in issues:
        fields = issue.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "Unknown")
        parent = fields.get("parent")
        
        # Inicjalizuj słownik dla nowego typu
        if issue_type not in result:
            expected_parent = get_expected_parent_type(issue_type)
            result[issue_type] = {
                "total": 0,
                "unlinked": 0,
                "expected_parent": expected_parent
            }
        
        result[issue_type]["total"] += 1
        
        # Sprawdź czy jest niepodpięty
        if result[issue_type]["expected_parent"]:
            if not has_correct_parent(issue_type, parent):
                result[issue_type]["unlinked"] += 1
    
    return result


def extract_project_name(issues):
    if not issues:
        return "No data"
    return (
        issues[0]
        .get("fields", {})
        .get("project", {})
        .get("name", "Unknown project")
    )


def filter_issues_by_type(issues, desired_type, unlinked_only=False):
    """
    Returns a list of (key, summary, created_date).
    If unlinked_only is True, returns only issues that are not properly linked to their parent.
    """
    result = []
    for issue in issues:
        fields = issue.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name")
        if issue_type == desired_type:
            # Jeśli filtrujemy tylko niepodpięte, sprawdź czy issue jest niepodpięte
            if unlinked_only:
                parent = fields.get("parent")
                if has_correct_parent(issue_type, parent):
                    continue  # Pomiń podpięte
            
            key = issue.get("key", "")
            summary = fields.get("summary", "")
            created_raw = fields.get("created", "")
            created_date = created_raw.split("T")[0]  # show YYYY-MM-DD only
            result.append((key, summary, created_date))
    return result


def get_all_issues_by_type(issues, issue_type):
    """
    Zwraca listę wszystkich zgłoszeń danego typu (nie tylko niepodpiętych).
    Wyniki są cache'owane w pamięci dla szybszego dostępu.
    
    Returns:
        Lista słowników z kluczami: key, summary, created_date, creator_name, has_parent
    """
    global _all_by_type_cache
    
    # Sprawdź cache
    if issue_type in _all_by_type_cache:
        return _all_by_type_cache[issue_type]
    
    result = []
    
    for issue in issues:
        fields = issue.get("fields", {})
        current_type = fields.get("issuetype", {}).get("name")
        
        if current_type != issue_type:
            continue
        
        key = issue.get("key", "")
        summary = fields.get("summary", "")
        created_raw = fields.get("created", "")
        created_date = created_raw.split("T")[0]  # show YYYY-MM-DD only
        
        creator = fields.get("creator", {})
        creator_name = creator.get("displayName", creator.get("emailAddress", "Unknown"))
        
        parent = fields.get("parent")
        has_parent = has_correct_parent(issue_type, parent)
        
        result.append({
            "key": key,
            "summary": summary,
            "created_date": created_date,
            "creator_name": creator_name,
            "has_parent": has_parent
        })
    
    # Sortuj po dacie utworzenia (najnowsze pierwsze)
    result.sort(key=lambda x: x["created_date"], reverse=True)
    
    # Zapisz w cache
    _all_by_type_cache[issue_type] = result
    
    return result


def get_unlinked_issues(issues, issue_type):
    """
    Zwraca listę niepodlinkowanych zgłoszeń danego typu.
    Wyniki są cache'owane w pamięci dla szybszego dostępu.
    
    Returns:
        Lista słowników z kluczami: key, summary, created_date, creator_name, reporter_name
    """
    global _unlinked_cache
    
    # Sprawdź cache
    if issue_type in _unlinked_cache:
        return _unlinked_cache[issue_type]
    
    result = []
    expected_parent = get_expected_parent_type(issue_type)
    
    if not expected_parent:
        _unlinked_cache[issue_type] = result
        return result
    
    for issue in issues:
        fields = issue.get("fields", {})
        current_type = fields.get("issuetype", {}).get("name")
        
        if current_type != issue_type:
            continue
        
        parent = fields.get("parent")
        
        # Sprawdź czy jest niepodpięty
        if not has_correct_parent(issue_type, parent):
            key = issue.get("key", "")
            summary = fields.get("summary", "")
            created_raw = fields.get("created", "")
            created_date = created_raw.split("T")[0]  # show YYYY-MM-DD only
            
            creator = fields.get("creator", {})
            creator_name = creator.get("displayName", creator.get("emailAddress", "Unknown"))
            
            reporter = fields.get("reporter", {})
            reporter_name = reporter.get("displayName", reporter.get("emailAddress", "Unknown")) if reporter else "Unknown"
            
            result.append({
                "key": key,
                "summary": summary,
                "created_date": created_date,
                "creator_name": creator_name,
                "reporter_name": reporter_name
            })
    
    # Sortuj po dacie utworzenia (najnowsze pierwsze)
    result.sort(key=lambda x: x["created_date"], reverse=True)
    
    # Zapisz w cache
    _unlinked_cache[issue_type] = result
    
    return result


@app.route("/")
def index():
    issues = load_issues()
    type_counts = count_issues_by_type(issues)
    total_issues = len(issues)
    project_name = extract_project_name(issues)

    # Convert to list of tuples: (type_name, total_count, unlinked_count, expected_parent)
    type_counts_list = sorted(
        [
            (
                issue_type,
                data["total"],
                data["unlinked"],
                data["expected_parent"]
            )
            for issue_type, data in type_counts.items()
        ],
        key=lambda x: x[0]
    )

    # Filtruj tylko niepodpięte dla kolumn
    epics = filter_issues_by_type(issues, "Epic", unlinked_only=True)
    stories = filter_issues_by_type(issues, "Story", unlinked_only=True)
    tasks = filter_issues_by_type(issues, "Task", unlinked_only=True)

    return render_template(
        "index.html",
        project_name=project_name,
        total_issues=total_issues,
        type_counts=type_counts_list,
        epics=epics,
        stories=stories,
        tasks=tasks,
        jira_url=JIRA_URL,
    )


@app.route("/api/unlinked/<issue_type>")
def get_unlinked_api(issue_type):
    """
    API endpoint zwracający listę niepodlinkowanych zgłoszeń dla danego typu.
    """
    issues = load_issues()
    unlinked = get_unlinked_issues(issues, issue_type)
    
    return jsonify({
        "issue_type": issue_type,
        "count": len(unlinked),
        "issues": unlinked
    })


@app.route("/api/all/<issue_type>")
def get_all_by_type_api(issue_type):
    """
    API endpoint zwracający listę wszystkich zgłoszeń danego typu.
    """
    issues = load_issues()
    all_issues = get_all_issues_by_type(issues, issue_type)
    
    return jsonify({
        "issue_type": issue_type,
        "count": len(all_issues),
        "issues": all_issues
    })


if __name__ == "__main__":
    import sys
    
    # Obsługa argumentów --host i --port
    host = "127.0.0.1"
    port = 5000
    debug = True
    
    if "--host" in sys.argv:
        idx = sys.argv.index("--host")
        if idx + 1 < len(sys.argv):
            host = sys.argv[idx + 1]
    
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            try:
                port = int(sys.argv[idx + 1])
            except ValueError:
                print(f"Warning: Invalid port '{sys.argv[idx + 1]}', using default 5000")
    
    app.run(host=host, port=port, debug=debug)
