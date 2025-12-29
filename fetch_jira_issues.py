import os
import sys
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple
import requests
from dotenv import load_dotenv

load_dotenv()

JIRA_URL = os.getenv("JIRA_URL")          # e.g. https://appfire.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_TOKEN = os.getenv("JIRA_TOKEN")
PROJECT_KEY = os.getenv("PROJECT_KEY")

OUTPUT_FILE = "jira_issues_raw.json"

# ⚠️ For corporate/self-signed TLS. Set to True if you have proper CA configured.
VERIFY_SSL = False

# Number of parallel threads for fetching data
# Default is 5, can be increased if Jira API supports it
MAX_WORKERS = 5


def build_jql(project_key: str, start_date: str, end_date: str) -> str:
    """
    Build a JQL query string with a date range on `created`.
    Dates are expected in YYYY-MM-DD format.
    """
    return (
        f'project = {project_key} '
        f'AND created >= "{start_date}" '
        f'AND created <= "{end_date}" '
        f'ORDER BY created ASC'
    )


def fetch_issues_page(next_page_token: str | None, max_results: int, jql: str):
    """
    Fetch a single page from Jira enhanced search API (/rest/api/3/search/jql).
    Uses nextPageToken-based pagination (no startAt anymore).
    """
    if not JIRA_URL or not JIRA_EMAIL or not JIRA_TOKEN:
        raise ValueError("JIRA_URL, JIRA_EMAIL or JIRA_TOKEN is not set in .env")

    url = f"{JIRA_URL}/rest/api/3/search/jql"

    payload: dict = {
        "jql": jql,
        "maxResults": max_results,
        # You can restrict this list later if you want smaller payloads
        "fields": ["*all"],
    }

    # For the first page nextPageToken is omitted
    if next_page_token:
        payload["nextPageToken"] = next_page_token

    response = requests.post(
        url,
        json=payload,
        auth=(JIRA_EMAIL, JIRA_TOKEN),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        verify=VERIFY_SSL,
    )

    if response.status_code != 200:
        print("Jira API returned non-200 status code:")
        print("Status:", response.status_code)
        print("Body:", response.text[:500])
        raise RuntimeError("Failed to fetch issues from Jira")

    return response.json()



def fetch_all_issues_for_project(project_key: str, start_date: str, end_date: str):
    """
    Fetch ALL issues for a given project and date range using manual pagination
    against the enhanced JQL search API (/rest/api/3/search/jql).
    """
    all_issues = []
    max_results = 100

    jql = build_jql(project_key, start_date, end_date)
    print(f"Using JQL: {jql}")

    next_page_token = None
    page_index = 0

    while True:
        page_index += 1
        page = fetch_issues_page(next_page_token, max_results, jql)

        issues = page.get("issues", [])
        total = page.get("total", 0)

        if not issues:
            print("No issues returned in this page. Stopping pagination.")
            break

        all_issues.extend(issues)

        print(
            f"Fetched {len(issues)} issues in page {page_index} | "
            f"total so far: {len(all_issues)}"
            + (f" / {total}" if total else "")
        )

        # Enhanced search pagination: use nextPageToken
        next_page_token = page.get("nextPageToken")

        if not next_page_token:
            print("No nextPageToken in response. Reached last page.")
            break

    return all_issues


def split_date_range(start_date: str, end_date: str, num_chunks: int = None) -> List[Tuple[str, str]]:
    """
    Splits a date range into smaller intervals for parallel fetching.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        num_chunks: Number of intervals (if None, uses MAX_WORKERS)
    
    Returns:
        List of tuples (start, end) representing date intervals
    """
    if num_chunks is None:
        num_chunks = MAX_WORKERS
    
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
    
    total_days = (end_dt - start_dt).days + 1
    
    if total_days <= 0:
        return [(start_date, end_date)]
    
    # If the range is small, don't split it
    if total_days <= 30:
        return [(start_date, end_date)]
    
    # Split into intervals (at least 30 days each)
    days_per_chunk = max(30, total_days // num_chunks)
    chunks = []
    
    current_start = start_dt
    while current_start <= end_dt:
        current_end = min(current_start + timedelta(days=days_per_chunk - 1), end_dt)
        chunks.append((
            current_start.strftime("%Y-%m-%d"),
            current_end.strftime("%Y-%m-%d")
        ))
        current_start = current_end + timedelta(days=1)
    
    return chunks


def fetch_issues_for_date_range(project_key: str, start_date: str, end_date: str, chunk_id: int = None):
    """
    Fetches all issues for a given date range.
    Used as a wrapper function for parallel execution.
    """
    try:
        prefix = f"[Chunk {chunk_id}] " if chunk_id is not None else ""
        print(f"{prefix}Fetching issues from {start_date} to {end_date}...")
        
        issues = fetch_all_issues_for_project(project_key, start_date, end_date)
        
        print(f"{prefix}Completed: {len(issues)} issues fetched")
        return issues
    except Exception as e:
        prefix = f"[Chunk {chunk_id}] " if chunk_id is not None else ""
        print(f"{prefix}ERROR: Failed to fetch issues: {e}")
        raise


def fetch_all_issues_parallel(project_key: str, start_date: str, end_date: str, num_workers: int = None):
    """
    Fetches all issues in parallel by splitting the date range into intervals.
    
    Args:
        project_key: Jira project key
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        num_workers: Number of parallel threads (default MAX_WORKERS)
    
    Returns:
        List of all issues
    """
    if num_workers is None:
        num_workers = MAX_WORKERS
    
    # Split date range into intervals
    date_chunks = split_date_range(start_date, end_date, num_workers)
    
    print(f"\n{'='*60}")
    print(f"Parallel fetching strategy:")
    print(f"  Total date range: {start_date} to {end_date}")
    print(f"  Split into {len(date_chunks)} chunks")
    print(f"  Using {num_workers} worker threads")
    print(f"{'='*60}\n")
    
    all_issues = []
    
    # Parallel fetching for each date interval
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        # Start all tasks
        future_to_chunk = {
            executor.submit(fetch_issues_for_date_range, project_key, chunk_start, chunk_end, idx + 1): (chunk_start, chunk_end, idx + 1)
            for idx, (chunk_start, chunk_end) in enumerate(date_chunks)
        }
        
        # Collect results as they complete
        for future in as_completed(future_to_chunk):
            chunk_start, chunk_end, chunk_id = future_to_chunk[future]
            try:
                issues = future.result()
                all_issues.extend(issues)
            except Exception as e:
                print(f"[Chunk {chunk_id}] ERROR: {e}")
                # Continue with other intervals despite error
    
    # Sort results by creation date for consistency
    all_issues.sort(key=lambda x: x.get("fields", {}).get("created", ""))
    
    return all_issues



def save_issues_to_file(issues, filepath: str):
    """
    Save all issues to a JSON file.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(issues)} issues to file: {filepath}")


def main():
    # Read date arguments from CLI or use a wide default
    if len(sys.argv) == 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        print("No date range provided. Using a very wide default (2000-01-01 to 2100-01-01).")
        start_date = "2000-01-01"
        end_date = "2100-01-01"

    # Simple sanity check
    try:
        datetime.fromisoformat(start_date)
        datetime.fromisoformat(end_date)
    except ValueError:
        raise ValueError("Dates must be in YYYY-MM-DD format, e.g. 2024-01-01")

    # Optionally, number of workers can be passed as 4th argument
    num_workers = None
    if len(sys.argv) >= 4:
        try:
            num_workers = int(sys.argv[3])
            print(f"Using {num_workers} parallel workers (from command line)")
        except ValueError:
            print(f"Warning: Invalid number of workers '{sys.argv[3]}', using default ({MAX_WORKERS})")

    print("\n" + "="*60)
    print("Starting parallel fetch from Jira...")
    print("="*60 + "\n")
    
    # Use parallel fetching
    issues = fetch_all_issues_parallel(PROJECT_KEY, start_date, end_date, num_workers)

    print(f"\n{'='*60}")
    print(f"Total issues fetched: {len(issues)}")
    print(f"{'='*60}\n")
    
    save_issues_to_file(issues, OUTPUT_FILE)
    print("Done. JSON file is ready for the web UI / AI agent.")


if __name__ == "__main__":
    main()

