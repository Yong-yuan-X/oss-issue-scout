# oss-issue-scout

[![PyPI](https://img.shields.io/pypi/v/oss-issue-scout.svg)](https://pypi.org/project/oss-issue-scout/)
[![Web App](https://img.shields.io/badge/Web%20App-Open-2ea44f)](https://yong-yuan-x.github.io/oss-issue-scout/)

Find worthwhile open-source issues

[中文 README](README.zh-CN.md)

The current version calls the GitHub API, searches open issues, and applies a simple score based on repository activity, issue activity, comments, labels, and related signals.
It is currently aimed at junior to intermediate developers who want a faster way to find approachable issues.

## Features

- Search GitHub open issues with selectable scoring presets
- Filter by language, label, stars, and update recency
- Skip issues that already have linked PRs
- Recommend only unassigned issues by default
- Skip repositories with fewer than 100 stars by default
- Render results as `table`, `markdown`, or `json`
- No third-party dependencies

## Usage

```powershell
pip install oss-issue-scout
oss-issue-scout search --language python --label "good first issue" --limit 5
```

Using a GitHub token is recommended. It can be about 3x faster than anonymous search and is less likely to hit rate limits. Set it as an environment variable first:

```powershell
$env:GITHUB_TOKEN="your_github_token"
```

```powershell
oss-issue-scout search --language python --limit 5
```

This example usually returns results in about 15 seconds.

## Web UI

The GitHub Pages version is a static trial version. It calls the GitHub API directly from your browser and applies a lightweight score in the frontend.
It does not run the Python backend, so search depth and sorting results may differ significantly from the CLI / local web backend.
If you want the more complete web scoring, run the project locally. A future update is planned to sync the Pages version with the backend logic.
The optional GitHub token is only sent to `api.github.com` and is not stored by the page.

Install the optional web dependencies before running the local web UI:

```powershell
python -m pip install -e ".[web]"
```

On Windows, start the frontend and backend together with:

```powershell
.\web\start_web.bat
```

The script starts the backend API at `http://localhost:5000`, serves the frontend at `http://localhost:8000`, and opens `http://localhost:8000`.

## Options

```text
--language            Repository primary language, such as python or c++; default: no language filter
--stars-min           Minimum repository stars; defaults to at least 100
--label               Issue label, such as "good first issue" or "bug"; default: no label filter
--updated-days        Issue updated within the last N days; default: no limit
--repo-updated-days   Repository had issue activity within the last N days; default: no limit
--exclude-repo        Exclude a repository (owner/name) from results; can be repeated; default: none
--limit               Number of results, default 6
--preset              Scoring preset: default, junior, intermediate, senior; default: default
--format              Output format: table, markdown, json; default: table
```

Examples:

```powershell
oss-issue-scout search
oss-issue-scout search --language python
oss-issue-scout search --language python --label "help wanted" --stars-min 500 --limit 5
oss-issue-scout search --language rust --format json
oss-issue-scout search --language "C++" --label "good first issue" --repo-updated-days 7
oss-issue-scout search --language c --preset intermediate --limit 10
oss-issue-scout search --language python --exclude-repo django/django --exclude-repo pandas-dev/pandas
```

## Scoring

The current score is intentionally simple. It considers:

- Repository stars: moderately active repos get a boost; very large repos may be penalized
- Issue update recency: recently updated issues get a boost; stale issues are penalized
- Repository issue activity: recent issue activity gets a boost
- Beginner-friendly labels: `good first issue` / `help wanted` only add points when the repo has at least 3 open issues with those labels
- Comment count: low discussion volume gets a boost; long discussions are penalized

The search step filters out:

- Closed issues
- Archived repositories
- Issues with linked PRs
- Assigned issues
- Repositories with fewer than 100 stars

Search uses the selected scoring preset. If not specified, it uses the `default` preset.

## Tests

```powershell
python -m unittest discover
```

Tests use mocked GitHub responses and do not call the real GitHub API.

## Next

This project is still small. If it helps you, please consider giving it a ⭐. Discussions will be opened after the project reaches 128+ ⭐.

If you have suggestions or run into problems, please open an issue.

Future versions will continue to improve recommendation quality and usability.

## Thanks Contributors

<a href="https://github.com/Yong-yuan-X/oss-issue-scout/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Yong-yuan-X/oss-issue-scout" alt="Contributors" />
</a>
