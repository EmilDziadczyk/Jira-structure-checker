#!/usr/bin/env python3
"""
Agent do analizy jakości danych z JIRA dla projektu BP ONE.

Analizuje:
- Ilość danych bez parenta
- Ilość danych bez start date i end date
- Ilość danych gdzie end date jest w przeszłości
- Proponuje dodatkowe analizy
"""

import json
import os
import sys
from datetime import datetime
from collections import defaultdict, Counter
from dotenv import load_dotenv

load_dotenv()

DATA_FILE = "jira_issues_raw.json"
PROJECT_KEY = os.getenv("PROJECT_KEY", "BP ONE")


def load_issues():
    """Ładuje dane z pliku JSON."""
    if not os.path.exists(DATA_FILE):
        print(f"Błąd: Plik {DATA_FILE} nie istnieje.")
        print("Najpierw uruchom fetch_jira_issues.py aby pobrać dane z JIRA.")
        sys.exit(1)
    
    print(f"Ładowanie danych z {DATA_FILE}...")
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        issues = json.load(f)
    print(f"Załadowano {len(issues)} issues.\n")
    return issues


def filter_by_project(issues, project_key):
    """Filtruje issues według klucza projektu."""
    filtered = []
    for issue in issues:
        project = issue.get("fields", {}).get("project", {})
        issue_project_key = project.get("key", "")
        issue_project_name = project.get("name", "")
        
        # Sprawdź zarówno klucz jak i nazwę projektu
        if project_key.upper() in issue_project_key.upper() or project_key.upper() in issue_project_name.upper():
            filtered.append(issue)
    
    return filtered


def get_field_value(issue, field_name):
    """Pobiera wartość pola z issue, obsługując różne formaty."""
    fields = issue.get("fields", {})
    
    # Sprawdź bezpośrednio w fields
    if field_name in fields:
        return fields[field_name]
    
    # Sprawdź customfield_* (może być różne ID)
    for key, value in fields.items():
        if key.startswith("customfield_") and value is not None:
            # Sprawdź czy to może być pole daty
            if isinstance(value, str) and ("date" in key.lower() or "start" in key.lower() or "end" in key.lower()):
                # Możemy sprawdzić nazwę pola w schemacie, ale na razie zwróć wartość
                pass
    
    return None


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
    # Typowe ID dla Epic Start/End Date to często customfield_10020, customfield_10021
    # Ale mogą się różnić - zwykle mniejsze ID to start date
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


def analyze_data_quality(issues):
    """Wykonuje analizę jakości danych."""
    print("=" * 80)
    print("ANALIZA JAKOŚCI DANYCH - PROJEKT BP ONE")
    print("=" * 80)
    print()
    
    total_issues = len(issues)
    print(f"Łączna liczba issues: {total_issues}")
    print()
    
    # 1. Analiza issues bez parenta
    print("-" * 80)
    print("1. ANALIZA ISSUES BEZ PARENTA")
    print("-" * 80)
    
    issues_without_parent = []
    issues_by_type_without_parent = defaultdict(int)
    issues_by_type_total = defaultdict(int)
    
    for issue in issues:
        fields = issue.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "Unknown")
        parent = fields.get("parent")
        
        issues_by_type_total[issue_type] += 1
        
        if not parent:
            issues_without_parent.append(issue)
            issues_by_type_without_parent[issue_type] += 1
    
    print(f"Liczba issues bez parenta: {len(issues_without_parent)} ({len(issues_without_parent)/total_issues*100:.1f}%)")
    print()
    print("Podział według typu issue:")
    for issue_type in sorted(issues_by_type_total.keys()):
        total = issues_by_type_total[issue_type]
        without_parent = issues_by_type_without_parent[issue_type]
        percentage = (without_parent / total * 100) if total > 0 else 0
        print(f"  {issue_type:20s}: {without_parent:4d} / {total:4d} ({percentage:5.1f}%)")
    print()
    
    # 2. Analiza issues bez start date i end date
    print("-" * 80)
    print("2. ANALIZA ISSUES BEZ START DATE I END DATE")
    print("-" * 80)
    
    issues_without_dates = []
    issues_without_start_date = []
    issues_without_end_date = []
    issues_without_both_dates = []
    
    for issue in issues:
        start_date, end_date = find_date_fields(issue)
        
        has_start = start_date is not None
        has_end = end_date is not None
        
        if not has_start and not has_end:
            issues_without_both_dates.append(issue)
            issues_without_dates.append(issue)
        elif not has_start:
            issues_without_start_date.append(issue)
        elif not has_end:
            issues_without_end_date.append(issue)
    
    print(f"Liczba issues bez start date i end date: {len(issues_without_both_dates)} ({len(issues_without_both_dates)/total_issues*100:.1f}%)")
    print(f"Liczba issues bez start date: {len(issues_without_start_date)} ({len(issues_without_start_date)/total_issues*100:.1f}%)")
    print(f"Liczba issues bez end date: {len(issues_without_end_date)} ({len(issues_without_end_date)/total_issues*100:.1f}%)")
    print()
    
    # 3. Analiza issues gdzie end date jest w przeszłości
    print("-" * 80)
    print("3. ANALIZA ISSUES GDZIE END DATE JEST W PRZESZŁOŚCI")
    print("-" * 80)
    
    issues_with_past_end_date = []
    today = datetime.now()
    
    for issue in issues:
        start_date, end_date = find_date_fields(issue)
        
        if end_date:
            try:
                # Parsuj datę (może być w formacie ISO z czasem)
                if "T" in end_date:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.fromisoformat(end_date[:10])
                
                # Porównaj tylko daty (bez czasu)
                if end_dt.date() < today.date():
                    issues_with_past_end_date.append((issue, end_dt))
            except (ValueError, AttributeError) as e:
                # Nie można sparsować daty
                pass
    
    print(f"Liczba issues z end date w przeszłości: {len(issues_with_past_end_date)} ({len(issues_with_past_end_date)/total_issues*100:.1f}%)")
    
    if issues_with_past_end_date:
        print("\nPrzykładowe issues z przeszłym end date (najstarsze):")
        sorted_past = sorted(issues_with_past_end_date, key=lambda x: x[1])[:10]
        for issue, end_dt in sorted_past:
            key = issue.get("key", "N/A")
            summary = issue.get("fields", {}).get("summary", "N/A")[:60]
            print(f"  {key:15s} | {end_dt.strftime('%Y-%m-%d'):10s} | {summary}")
    print()
    
    # 4. Dodatkowe analizy
    print("-" * 80)
    print("4. DODATKOWE ANALIZY")
    print("-" * 80)
    
    # 4.1. Status issues
    status_counter = Counter()
    for issue in issues:
        status = issue.get("fields", {}).get("status", {}).get("name", "Unknown")
        status_counter[status] += 1
    
    print("\n4.1. Rozkład issues według statusu:")
    for status, count in status_counter.most_common(10):
        print(f"  {status:30s}: {count:4d} ({count/total_issues*100:5.1f}%)")
    
    # 4.2. Issues bez assignee
    issues_without_assignee = []
    for issue in issues:
        assignee = issue.get("fields", {}).get("assignee")
        if not assignee:
            issues_without_assignee.append(issue)
    
    print(f"\n4.2. Issues bez assignee: {len(issues_without_assignee)} ({len(issues_without_assignee)/total_issues*100:.1f}%)")
    
    # 4.3. Issues bez description
    issues_without_description = []
    for issue in issues:
        description = issue.get("fields", {}).get("description")
        if not description or (isinstance(description, dict) and not description.get("content")):
            issues_without_description.append(issue)
    
    print(f"4.3. Issues bez description: {len(issues_without_description)} ({len(issues_without_description)/total_issues*100:.1f}%)")
    
    # 4.4. Issues bez labels
    issues_without_labels = []
    for issue in issues:
        labels = issue.get("fields", {}).get("labels", [])
        if not labels:
            issues_without_labels.append(issue)
    
    print(f"4.4. Issues bez labels: {len(issues_without_labels)} ({len(issues_without_labels)/total_issues*100:.1f}%)")
    
    # 4.5. Issues z duplikatami summary
    summary_counter = Counter()
    for issue in issues:
        summary = issue.get("fields", {}).get("summary", "")
        if summary:
            summary_counter[summary.lower().strip()] += 1
    
    duplicate_summaries = {s: c for s, c in summary_counter.items() if c > 1}
    if duplicate_summaries:
        print(f"\n4.5. Issues z duplikatami summary: {sum(duplicate_summaries.values())} issues")
        print("   Top 5 duplikatów:")
        sorted_dups = sorted(duplicate_summaries.items(), key=lambda x: x[1], reverse=True)[:5]
        for summary, count in sorted_dups:
            print(f"     '{summary[:60]}': {count} wystąpień")
    
    # 4.6. Issues bez resolution (jeśli są zamknięte)
    closed_issues_without_resolution = []
    for issue in issues:
        status = issue.get("fields", {}).get("status", {}).get("name", "")
        resolution = issue.get("fields", {}).get("resolution")
        # Załóżmy że status "Done", "Closed", "Resolved" oznacza zamknięte
        if status.lower() in ["done", "closed", "resolved"] and not resolution:
            closed_issues_without_resolution.append(issue)
    
    if closed_issues_without_resolution:
        print(f"\n4.6. Zamknięte issues bez resolution: {len(closed_issues_without_resolution)}")
    
    # 4.7. Issues z nieprawidłową kolejnością dat (end date przed start date)
    issues_with_invalid_date_order = []
    for issue in issues:
        start_date, end_date = find_date_fields(issue)
        if start_date and end_date:
            try:
                if "T" in start_date:
                    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                else:
                    start_dt = datetime.fromisoformat(start_date[:10])
                
                if "T" in end_date:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                else:
                    end_dt = datetime.fromisoformat(end_date[:10])
                
                if end_dt < start_dt:
                    issues_with_invalid_date_order.append(issue)
            except (ValueError, AttributeError):
                pass
    
    if issues_with_invalid_date_order:
        print(f"\n4.7. Issues z end date przed start date: {len(issues_with_invalid_date_order)}")
    
    # 4.8. Issues z start date w przeszłości ale status OPEN
    print("\n4.8. Issues z start date w przeszłości (Status: OPEN):")
    issues_past_start_open = []
    today = datetime.now()
    for issue in issues:
        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "")
        
        # Sprawdź czy status jest OPEN (nie zamknięty)
        closed_statuses = ["done", "closed", "resolved", "cancelled", "rejected", "completed"]
        if status.lower() in closed_statuses:
            continue
        
        start_date, _ = find_date_fields(issue)
        if start_date:
            try:
                if "T" in start_date:
                    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                else:
                    start_dt = datetime.fromisoformat(start_date[:10])
                
                if start_dt.date() < today.date():
                    issues_past_start_open.append(issue)
            except (ValueError, AttributeError):
                pass
    
    print(f"   Liczba: {len(issues_past_start_open)} ({len(issues_past_start_open)/total_issues*100:.1f}%)")
    
    # 4.9. Issues In Progress bez assignee
    print("\n4.9. Issues In Progress bez assignee:")
    in_progress_no_assignee = []
    for issue in issues:
        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "")
        
        if status.lower() not in ["in progress", "inprogress"]:
            continue
        
        assignee = fields.get("assignee")
        if assignee:
            continue
        
        in_progress_no_assignee.append(issue)
    
    print(f"   Liczba: {len(in_progress_no_assignee)} ({len(in_progress_no_assignee)/total_issues*100:.1f}%)")
    
    print()
    print("=" * 80)
    print("PODSUMOWANIE")
    print("=" * 80)
    print(f"✓ Issues bez parenta: {len(issues_without_parent)}")
    print(f"✓ Issues bez start date i end date: {len(issues_without_both_dates)}")
    print(f"✓ Issues z end date w przeszłości: {len(issues_with_past_end_date)}")
    print(f"✓ Issues z start date w przeszłości (Status: OPEN): {len(issues_past_start_open)}")
    print(f"✓ Issues In Progress bez assignee: {len(in_progress_no_assignee)}")
    print(f"✓ Issues bez assignee: {len(issues_without_assignee)}")
    print(f"✓ Issues bez description: {len(issues_without_description)}")
    print("=" * 80)


def main():
    """Główna funkcja."""
    print("\n" + "=" * 80)
    print("AGENT ANALIZY JAKOŚCI DANYCH JIRA - PROJEKT BP ONE")
    print("=" * 80 + "\n")
    
    # Załaduj dane
    all_issues = load_issues()
    
    # Filtruj według projektu
    if PROJECT_KEY:
        print(f"Filtrowanie issues dla projektu: {PROJECT_KEY}")
        issues = filter_by_project(all_issues, PROJECT_KEY)
        print(f"Znaleziono {len(issues)} issues dla projektu {PROJECT_KEY}.\n")
    else:
        print("Uwaga: PROJECT_KEY nie jest ustawiony w .env, analizuję wszystkie issues.")
        issues = all_issues
    
    if not issues:
        print("Brak issues do analizy!")
        return
    
    # Wykonaj analizę
    analyze_data_quality(issues)


if __name__ == "__main__":
    main()

