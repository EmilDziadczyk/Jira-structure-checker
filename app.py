import json
import os
from collections import Counter
from datetime import datetime
from dotenv import load_dotenv
from functools import lru_cache

import requests
from flask import Flask, render_template, abort, jsonify

load_dotenv()

app = Flask(__name__)

DATA_FILE = "jira_issues_raw.json"  # or "jira_issues.json" if you renamed it
JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")
VERIFY_SSL = os.getenv("VERIFY_SSL", "false").lower() in ("true", "1", "yes")

# Data cache
_issues_cache = None
_file_mtime = None
_unlinked_cache = {}  # Cache for get_unlinked_issues results: {issue_type: result}
_all_by_type_cache = {}  # Cache for get_all_issues_by_type results: {issue_type: result}
_quality_analysis_cache = None  # Cache for quality analysis results


def load_issues():
    """
    Loads data from JSON file with in-memory caching.
    Cache is automatically refreshed when the file changes.
    """
    global _issues_cache, _file_mtime
    
    if not os.path.exists(DATA_FILE):
        abort(500, f"Data file {DATA_FILE} not found. Run fetch_jira_issues.py first.")
    
    # Check file modification time
    current_mtime = os.path.getmtime(DATA_FILE)
    
    # If cache is empty or file has changed, load data
    if _issues_cache is None or _file_mtime != current_mtime:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            _issues_cache = json.load(f)
        _file_mtime = current_mtime
        # Clear function result cache when data changes
        _unlinked_cache.clear()
        _all_by_type_cache.clear()
        global _quality_analysis_cache
        _quality_analysis_cache = None
    
    return _issues_cache


def get_expected_parent_type(issue_type):
    """
    Returns the expected parent type for a given issue type.
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
    Checks if an issue has the correct parent according to the hierarchy.
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
    Counts issues by type and returns information about unlinked ones.
    
    Returns:
        dict with issue type keys, values containing:
        - total: total number of issues of this type
        - unlinked: number of unlinked issues
        - expected_parent: expected parent type (or None)
    """
    result = {}
    
    for issue in issues:
        fields = issue.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "Unknown")
        parent = fields.get("parent")
        
        # Initialize dictionary for new type
        if issue_type not in result:
            expected_parent = get_expected_parent_type(issue_type)
            result[issue_type] = {
                "total": 0,
                "unlinked": 0,
                "expected_parent": expected_parent
            }
        
        result[issue_type]["total"] += 1
        
        # Check if it's unlinked
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
            # If filtering only unlinked, check if issue is unlinked
            if unlinked_only:
                parent = fields.get("parent")
                if has_correct_parent(issue_type, parent):
                    continue  # Skip linked issues
            
            key = issue.get("key", "")
            summary = fields.get("summary", "")
            created_raw = fields.get("created", "")
            created_date = created_raw.split("T")[0]  # show YYYY-MM-DD only
            result.append((key, summary, created_date))
    return result


def get_all_issues_by_type(issues, issue_type):
    """
    Returns a list of all issues of a given type (not only unlinked ones).
    Results are cached in memory for faster access.
    
    Returns:
        List of dictionaries with keys: key, summary, created_date, creator_name, has_parent
    """
    global _all_by_type_cache
    
    # Check cache
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
    
    # Sort by creation date (newest first)
    result.sort(key=lambda x: x["created_date"], reverse=True)
    
    # Save to cache
    _all_by_type_cache[issue_type] = result
    
    return result


def get_unlinked_issues(issues, issue_type):
    """
    Returns a list of unlinked issues of a given type.
    Results are cached in memory for faster access.
    
    Returns:
        List of dictionaries with keys: key, summary, created_date, creator_name, reporter_name
    """
    global _unlinked_cache
    
    # Check cache
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
        
        # Check if it's unlinked
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
    
    # Sort by creation date (newest first)
    result.sort(key=lambda x: x["created_date"], reverse=True)
    
    # Save to cache
    _unlinked_cache[issue_type] = result
    
    return result


def is_date_string(value):
    """Sprawdza czy string wygląda jak data."""
    if not isinstance(value, str) or not value:
        return False
    
    # Usuń timezone info dla parsowania
    value_clean = value.replace("Z", "").replace("+00:00", "")
    if "+" in value_clean:
        value_clean = value_clean.split("+")[0]
    if "-" in value_clean and len(value_clean) > 10:
        # Może być timezone offset, usuń go
        parts = value_clean.split("-")
        if len(parts) > 3:
            value_clean = "-".join(parts[:3])
    
    # Sprawdź czy zaczyna się od YYYY-MM-DD
    if len(value_clean) >= 10:
        try:
            # Spróbuj sparsować jako ISO format
            datetime.fromisoformat(value_clean[:19] if len(value_clean) >= 19 else value_clean[:10])
            return True
        except (ValueError, AttributeError):
            try:
                # Spróbuj tylko datę
                datetime.fromisoformat(value_clean[:10])
                return True
            except (ValueError, AttributeError):
                pass
    
    return False


def find_date_fields(issue):
    """Znajduje pola dat w issue (start date, end date)."""
    fields = issue.get("fields", {})
    
    start_date = None
    end_date = None
    
    # Standardowe pola JIRA
    if "duedate" in fields and fields["duedate"]:
        end_date = fields["duedate"]
    
    # Pobierz wszystkie customfield_* które są datami
    date_fields = []
    for key, value in fields.items():
        if key.startswith("customfield_") and value is not None:
            if is_date_string(value):
                date_fields.append((key, value))
    
    # Jeśli mamy pola dat, spróbuj zidentyfikować start i end
    if len(date_fields) >= 2:
        # Posortuj według ID pola (mniejsze ID = prawdopodobnie start date)
        try:
            sorted_fields = sorted(date_fields, key=lambda x: int(x[0].replace("customfield_", "")))
            start_date = sorted_fields[0][1]
            end_date = sorted_fields[1][1]
        except ValueError:
            # Jeśli nie można sparsować ID, użyj pierwszej jako start, drugiej jako end
            start_date = date_fields[0][1]
            end_date = date_fields[1][1]
    elif len(date_fields) == 1:
        # Tylko jedno pole daty - może to być end date
        end_date = date_fields[0][1]
    
    return start_date, end_date


def parse_date(date_str):
    """Parsuje datę z różnych formatów."""
    if not date_str:
        return None
    
    try:
        if "T" in date_str:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            return datetime.fromisoformat(date_str[:10])
    except (ValueError, AttributeError):
        return None


def is_open_status(status_name):
    """Sprawdza czy status jest otwarty (nie zamknięty)."""
    if not status_name:
        return True  # Jeśli brak statusu, traktuj jako otwarty
    
    closed_statuses = ["done", "closed", "resolved", "cancelled", "rejected", "completed"]
    status_lower = status_name.lower().strip()
    return status_lower not in closed_statuses


def get_issues_with_past_start_date_open(issues):
    """Znajduje issues gdzie start date jest w przeszłości i status to dokładnie OPEN (bez Waiting for release itp.)."""
    result = []
    today = datetime.now()
    
    for issue in issues:
        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "")
        
        # Tylko status "Open" — wykluczamy np. "Waiting for release", "In Progress" itd.
        if not status or status.strip().lower() != "open":
            continue
        
        start_date, _ = find_date_fields(issue)
        if start_date:
            start_dt = parse_date(start_date)
            if start_dt and start_dt.date() < today.date():
                key = issue.get("key", "")
                summary = fields.get("summary", "")
                created_raw = fields.get("created", "")
                created_date = created_raw.split("T")[0] if created_raw else ""
                
                creator = fields.get("creator", {})
                creator_name = creator.get("displayName", creator.get("emailAddress", "Unknown"))
                
                result.append({
                    "key": key,
                    "summary": summary,
                    "created_date": created_date,
                    "creator_name": creator_name,
                    "start_date": start_date.split("T")[0] if "T" in start_date else start_date[:10],
                    "status": status
                })
    
    return result


def _get_status_since_from_changelog(issue, status_name):
    """
    Z changelogu issue wyciąga datę ostatniego przejścia do podanego statusu (np. 'Waiting for release').
    Zwraca napis YYYY-MM-DD lub None, jeśli brak changelogu / brak takiej zmiany.
    """
    changelog = issue.get("changelog") or {}
    histories = changelog.get("histories") or []
    status_lower = (status_name or "").strip().lower()
    if not status_lower:
        return None
    for h in reversed(histories):  # od najstarszych; ostatnie dopasowanie = ostatnia zmiana do tego statusu
        created_raw = h.get("created") or ""
        items = h.get("items") or []
        for item in items:
            if (item.get("field") or "").lower() != "status":
                continue
            to_str = (item.get("toString") or item.get("to") or "")
            if isinstance(to_str, dict):
                to_str = to_str.get("name") or to_str.get("value") or ""
            if (to_str or "").strip().lower() == status_lower:
                if created_raw:
                    return created_raw.split("T")[0] if "T" in created_raw else created_raw[:10]
                return None
    return None


def _fetch_changelog_status_since(issue_keys, id_to_key, target_status="Waiting for release"):
    """
    Wywołuje Jira API POST /rest/api/3/changelog/bulkfetch i zwraca mapę issue_key -> data (YYYY-MM-DD)
    od kiedy status ustawiono na target_status (np. 'Waiting for release').
    """
    if not issue_keys or not JIRA_URL or not JIRA_EMAIL or not JIRA_TOKEN:
        return {}
    url = f"{JIRA_URL.rstrip('/')}/rest/api/3/changelog/bulkfetch"
    status_lower = (target_status or "").strip().lower()
    # Zbieramy najnowszą datę zmiany na target_status per issue (po issueId z odpowiedzi)
    latest_by_issue_id = {}  # issueId -> (created_ts, date_str)

    next_page_token = None
    for _ in range(100):  # limit stron
        payload = {
            "issueIdsOrKeys": issue_keys,
            "maxResults": 500,
        }
        if next_page_token:
            payload["nextPageToken"] = next_page_token
        try:
            resp = requests.post(
                url,
                json=payload,
                auth=(JIRA_EMAIL, JIRA_TOKEN),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                verify=VERIFY_SSL,
                timeout=60,
            )
        except requests.RequestException:
            return {}
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
        for log in data.get("issueChangeLogs") or []:
            issue_id = str(log.get("issueId") or "")
            for hist in log.get("changeHistories") or []:
                created = hist.get("created")
                if created is None:
                    continue
                # created może być Unix timestamp (s) lub ISO string
                if isinstance(created, (int, float)):
                    try:
                        dt = datetime.utcfromtimestamp(int(created) if created > 1e10 else int(created))
                        date_str = dt.strftime("%Y-%m-%d")
                    except (ValueError, OSError):
                        continue
                else:
                    created_str = str(created)
                    date_str = created_str.split("T")[0] if "T" in created_str else created_str[:10]
                for item in hist.get("items") or []:
                    if (item.get("field") or "").strip().lower() != "status":
                        continue
                    to_val = item.get("toString") or item.get("to")
                    if isinstance(to_val, dict):
                        to_val = to_val.get("name") or to_val.get("value") or ""
                    if (str(to_val or "").strip().lower()) != status_lower:
                        continue
                    # Zachowujemy najnowszą datę dla tego issue (większy ts = nowszy)
                    if isinstance(created, (int, float)):
                        ts_compare = int(created) // 1000 if created > 1e10 else int(created)  # ms vs s
                    else:
                        try:
                            ts_compare = int(datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp())
                        except (ValueError, TypeError):
                            ts_compare = 0
                    if issue_id not in latest_by_issue_id or ts_compare > latest_by_issue_id[issue_id][0]:
                        latest_by_issue_id[issue_id] = (ts_compare, date_str)
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
    return {id_to_key[uid]: date_str for uid, (_, date_str) in latest_by_issue_id.items() if uid in id_to_key}


def get_issues_waiting_for_release(issues):
    """
    Znajduje Epiki, Inicjatywy i Stories ze statusem 'Waiting for release'.
    Zwraca listę słowników z key, summary, issue_type, status, status_since (od kiedy ten status), id (do mapowania API).
    """
    allowed_types = {"epic", "initiative", "story"}
    target_status = "Waiting for release"
    result = []
    for issue in issues:
        fields = issue.get("fields", {})
        issue_type = (fields.get("issuetype") or {}).get("name") or ""
        if issue_type.strip().lower() not in allowed_types:
            continue
        status = (fields.get("status") or {}).get("name") or ""
        if status.strip().lower() != target_status.lower():
            continue
        key = issue.get("key", "")
        summary = fields.get("summary", "") or ""
        status_since = _get_status_since_from_changelog(issue, target_status)
        result.append({
            "key": key,
            "summary": summary,
            "issue_type": issue_type,
            "status": status,
            "status_since": status_since,
            "id": str(issue.get("id", "")),
        })
    return result


def get_in_progress_issues_without_assignee(issues):
    """Znajduje issues ze statusem In Progress bez assignee."""
    result = []
    
    for issue in issues:
        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "")
        
        # Sprawdź czy status to "In Progress" (case insensitive)
        if status.lower() not in ["in progress", "inprogress"]:
            continue
        
        assignee = fields.get("assignee")
        if assignee:
            continue  # Ma assignee, pomiń
        
        key = issue.get("key", "")
        summary = fields.get("summary", "")
        created_raw = fields.get("created", "")
        created_date = created_raw.split("T")[0] if created_raw else ""
        
        creator = fields.get("creator", {})
        creator_name = creator.get("displayName", creator.get("emailAddress", "Unknown"))
        
        result.append({
            "key": key,
            "summary": summary,
            "created_date": created_date,
            "creator_name": creator_name,
            "status": status
        })
    
    return result


def get_quality_analysis(issues):
    """Wykonuje analizę jakości danych i zwraca wyniki."""
    global _quality_analysis_cache
    
    if _quality_analysis_cache is not None:
        return _quality_analysis_cache
    
    total_issues = len(issues)
    
    # 1. Issues z start date w przeszłości ale status OPEN
    past_start_open = get_issues_with_past_start_date_open(issues)
    
    # 2. Issues In Progress bez assignee
    in_progress_no_assignee = get_in_progress_issues_without_assignee(issues)
    
    # 3. Epiki, Inicjatywy, Stories ze statusem Waiting for release
    waiting_for_release = get_issues_waiting_for_release(issues)
    
    result = {
        "total_issues": total_issues,
        "past_start_open": {
            "count": len(past_start_open),
            "percentage": (len(past_start_open) / total_issues * 100) if total_issues > 0 else 0
        },
        "in_progress_no_assignee": {
            "count": len(in_progress_no_assignee),
            "percentage": (len(in_progress_no_assignee) / total_issues * 100) if total_issues > 0 else 0
        },
        "waiting_for_release": {
            "count": len(waiting_for_release),
            "percentage": (len(waiting_for_release) / total_issues * 100) if total_issues > 0 else 0
        }
    }
    
    _quality_analysis_cache = result
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

    # Filter only unlinked for columns
    epics = filter_issues_by_type(issues, "Epic", unlinked_only=True)
    stories = filter_issues_by_type(issues, "Story", unlinked_only=True)
    tasks = filter_issues_by_type(issues, "Task", unlinked_only=True)
    
    # Get quality analysis
    quality_analysis = get_quality_analysis(issues)

    return render_template(
        "index.html",
        project_name=project_name,
        total_issues=total_issues,
        type_counts=type_counts_list,
        epics=epics,
        stories=stories,
        tasks=tasks,
        quality_analysis=quality_analysis,
        jira_url=JIRA_URL,
    )


@app.route("/api/unlinked/<issue_type>")
def get_unlinked_api(issue_type):
    """
    API endpoint returning a list of unlinked issues for a given type.
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
    API endpoint returning a list of all issues of a given type.
    """
    issues = load_issues()
    all_issues = get_all_issues_by_type(issues, issue_type)
    
    return jsonify({
        "issue_type": issue_type,
        "count": len(all_issues),
        "issues": all_issues
    })


@app.route("/api/quality/past-start-open")
def get_past_start_open_api():
    """
    API endpoint returning issues with past start date but OPEN status.
    """
    issues = load_issues()
    result = get_issues_with_past_start_date_open(issues)
    
    return jsonify({
        "analysis_type": "past_start_open",
        "count": len(result),
        "issues": result
    })


@app.route("/api/quality/in-progress-no-assignee")
def get_in_progress_no_assignee_api():
    """
    API endpoint returning In Progress issues without assignee.
    """
    issues = load_issues()
    result = get_in_progress_issues_without_assignee(issues)
    
    return jsonify({
        "analysis_type": "in_progress_no_assignee",
        "count": len(result),
        "issues": result
    })


@app.route("/api/quality/waiting-for-release")
def get_waiting_for_release_api():
    """
    API endpoint returning Epics, Initiatives, Stories with status Waiting for release.
    Pobiera z Jira changelog, żeby uzupełnić status_since (od kiedy status = Waiting for release).
    """
    issues = load_issues()
    result = get_issues_waiting_for_release(issues)

    if result and JIRA_URL and JIRA_EMAIL and JIRA_TOKEN:
        id_to_key = {item["id"]: item["key"] for item in result if item.get("id")}
        keys = [item["key"] for item in result]
        status_since_map = _fetch_changelog_status_since(keys, id_to_key)
        for item in result:
            item["status_since"] = status_since_map.get(item["key"]) or item.get("status_since")
        for item in result:
            item.pop("id", None)
    else:
        for item in result:
            item.pop("id", None)

    return jsonify({
        "analysis_type": "waiting_for_release",
        "count": len(result),
        "issues": result
    })


@app.route("/quality/<analysis_type>")
def quality_analysis_page(analysis_type):
    """
    Page displaying quality analysis results with sortable table.
    """
    issues = load_issues()
    
    if analysis_type == "past-start-open":
        result = get_issues_with_past_start_date_open(issues)
        title = "Issues z Start Date w przeszłości (Status: OPEN)"
    elif analysis_type == "in-progress-no-assignee":
        result = get_in_progress_issues_without_assignee(issues)
        title = "Issues In Progress bez Assignee"
    else:
        abort(404)
    
    return render_template(
        "quality_analysis.html",
        title=title,
        analysis_type=analysis_type,
        issues=result,
        count=len(result),
        jira_url=JIRA_URL,
    )


if __name__ == "__main__":
    import sys
    
    # Handle --host and --port arguments
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
