# Jira Agent

Application for analyzing and visualizing Jira issues. Allows browsing issues, identifying unlinked elements, and analyzing task hierarchy.

## Features

- Fetching issues from Jira API
- Web interface for visualizing issues
- Identification of unlinked Epics, Stories, and Tasks
- Filtering and sorting issues
- In-memory cache for fast data access

## Requirements

- Python 3.8+
- Access to Jira API (URL, email, token)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd jira-agent
```

2. Create a `.env` file with configuration:
```
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_TOKEN=your-api-token
PROJECT_KEY=YOUR_PROJECT_KEY
```

3. Install dependencies (automatically on first run):
```bash
./run_python_venv.sh 2024-01-01 2024-12-31
```

## Usage

### Fetching data from Jira

```bash
./run_python_venv.sh <start_date> <end_date> [num_workers]
```

Example:
```bash
./run_python_venv.sh 2024-01-01 2024-12-31
```

### Running the web application

```bash
./run_web_app.sh
```

The application will be available at: http://127.0.0.1:5000

### Web application options

```bash
./run_web_app.sh --port 8080
./run_web_app.sh --host 0.0.0.0 --port 8080
```

## Project Structure

- `fetch_jira_issues.py` - Script for fetching issues from Jira
- `app.py` - Flask web application
- `run_python_venv.sh` - Script to run fetch_jira_issues.py
- `run_web_app.sh` - Script to run the web application
- `templates/index.html` - User interface
- `requirements.txt` - Python dependencies

## License

MIT
