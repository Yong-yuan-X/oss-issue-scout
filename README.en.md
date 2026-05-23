# oss-issue-scout

[![PyPI](https://img.shields.io/pypi/v/oss-issue-scout.svg)](https://pypi.org/project/oss-issue-scout/)

Find worthwhile open-source issues

The current version calls the GitHub API, searches open issues, and applies a simple score based on repository activity, issue activity, comments, labels, and related signals.
It is currently aimed at junior to intermediate developers who want a faster way to find approachable issues.

## Features

- Search GitHub open issues w/ presets chosen by users
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

## Options

```text
--language            Repository primary language, such as python
--stars-min           Minimum repository stars; defaults to at least 100
--label               Issue label, such as "good first issue"
--updated-days        Issue updated within the last N days
--repo-updated-days   Repository had issue activity within the last N days
--limit               Number of results, default 10
--preset              Search issues w/ presets (default, junior, intermediate, senior)
--format              Output format: table, markdown, json
```

Examples:

```powershell
oss-issue-scout search --language python
oss-issue-scout search --language python --label "help wanted" --stars-min 500 --limit 10
oss-issue-scout search --language python --format json
oss-issue-scout search --language "C++" --label "good first issue" --repo-updated-days 7
oss-issue-scout search --language python --preset intermediate --limit 20
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

The search will use preset chosen by users. If not chosen, will use the `default` preset

## Tests

```powershell
python -m unittest discover
```

Tests use mocked GitHub responses and do not call the real GitHub API.

## Next

This project is still small. If it helps you, please consider giving it a ⭐. Discussions will be opened after the project reaches 16+ ⭐.

If you have suggestions or run into problems, please open an issue.

Future versions will continue to improve recommendation quality and usability.

## Contributors

<a href="https://github.com/Yong-yuan-X/oss-issue-scout/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=Yong-yuan-X/oss-issue-scout" alt="Contributors" />
</a>
