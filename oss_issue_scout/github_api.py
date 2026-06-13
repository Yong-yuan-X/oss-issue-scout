from __future__ import annotations

import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .config import (
    BACKFILL_PER_PAGE,
    DEBUG_ENABLED,
    DEFAULT_STARS_MIN,
    EXTENDED_SEARCH_MIN_RESULTS,
    EXTENDED_SEARCH_PAGE_MULTIPLIER,
    GITHUB_API_BASE,
    GITHUB_API_VERSION,
    GITHUB_GRAPHQL_URL,
    GITHUB_TOKEN_ENV,
    MAX_GRAPHQL_PAGE_SIZE,
    MAX_GRAPHQL_SEARCH_PAGES,
    MAX_REPO_WORKERS,
    MAX_REST_SEARCH_PAGES,
    MIN_REPO_OPEN_ISSUES,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_RETRY_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    TRANSIENT_HTTP_STATUS_CODES,
)

ISSUE_SEARCH_QUERY = """
query SearchIssues($query: String!, $first: Int!, $after: String) {
  search(query: $query, type: ISSUE, first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on Issue {
        title
        url
        number
        updatedAt
        comments {
          totalCount
        }
        labels(first: 20) {
          nodes {
            name
          }
        }
        repository {
          nameWithOwner
          stargazerCount
          primaryLanguage {
            name
          }
          issues(first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) {
            nodes {
              updatedAt
            }
          }
          openIssues: issues(first: 1, states: OPEN) {
            totalCount
          }
          goodFirstIssues: issues(first: 1, labels: ["good first issue"], states: OPEN) {
            totalCount
          }
          helpWantedIssues: issues(first: 1, labels: ["help wanted"], states: OPEN) {
            totalCount
          }
        }
      }
    }
  }
}
"""


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API request fails."""


@dataclass(frozen=True)
class Issue:
    """Represents a GitHub issue with repository metadata used for scoring."""

    repo: str
    title: str
    url: str
    language: str
    stars: int
    labels: tuple[str, ...]
    updated_days: int
    repo_last_issue_updated_days: int
    repo_beginner_issue_count: int
    comments: int
    has_open_pr: bool
    repo_open_issue_count: int = 0


@dataclass(frozen=True)
class IssueSearchResult:
    """Holds the results of an issue search along with pagination status."""

    issues: list[Issue]
    exhausted: bool
    page_limit_reached: bool = False


def search_issues(
    *,
    language: str | None = None,
    stars_min: int | None = None,
    label: str | None = None,
    updated_days: int | None = None,
    repo_updated_days: int | None = None,
    exclude_repos: tuple[str, ...] = (),
    limit: int = 10,
) -> list[Issue]:
    """Search GitHub issues and return a flat list, delegating to search_issue_candidates."""
    return search_issue_candidates(
        language=language,
        stars_min=stars_min,
        label=label,
        updated_days=updated_days,
        repo_updated_days=repo_updated_days,
        exclude_repos=exclude_repos,
        limit=limit,
    ).issues


def search_issue_candidates(
    *,
    query: str | None = None,
    language: str | None = None,
    stars_min: int | None = None,
    label: str | None = None,
    updated_days: int | None = None,
    repo_updated_days: int | None = None,
    exclude_repos: tuple[str, ...] = (),
    limit: int = 10,
    max_pages: int | None = None,
    page_size: int | None = None,
) -> IssueSearchResult:
    """Search GitHub issues using GraphQL (preferred) or REST, excluding specified repos."""
    exclude_repos_lower = {repo.strip().casefold() for repo in exclude_repos if repo.strip()}
    if _get_token():
        try:
            return _search_issue_candidates_graphql(
                query=query,
                language=language,
                stars_min=stars_min,
                label=label,
                updated_days=updated_days,
                repo_updated_days=repo_updated_days,
                exclude_repos=exclude_repos_lower,
                limit=limit,
                max_pages=max_pages,
                page_size=page_size,
            )
        except GitHubAPIError as error:
            if not _is_graphql_resource_limit_error(error):
                raise
            _debug("graphql resource limit exceeded; falling back to REST search")

    return _search_issue_candidates_rest(
        query=query,
        language=language,
        stars_min=stars_min,
        label=label,
        updated_days=updated_days,
        repo_updated_days=repo_updated_days,
        exclude_repos=exclude_repos_lower,
        limit=limit,
        max_pages=max_pages,
        page_size=page_size,
    )


def backfill_issue_candidates(
    *,
    repo: str,
    known_issues: list[Issue] | None = None,
    language: str | None = None,
    stars_min: int | None = None,
    label: str | None = None,
    updated_days: int | None = None,
    repo_updated_days: int | None = None,
    exclude_repos: tuple[str, ...] = (),
    per_page: int = BACKFILL_PER_PAGE,
    page: int = 1,
) -> list[Issue]:
    """Fetch additional issue candidates for a single repository via the REST search API."""
    if not repo or per_page <= 0 or page <= 0:
        return []
    exclude_lower = {r.strip().casefold() for r in exclude_repos if r.strip()}
    if repo.strip().casefold() in exclude_lower:
        _debug(f"repo backfill skipped excluded repo={repo}")
        return []

    effective_stars_min = max(stars_min or DEFAULT_STARS_MIN, DEFAULT_STARS_MIN)
    repo_cache: dict[str, dict[str, Any]] = {}
    repo_activity_cache: dict[str, int] = {}
    repo_open_issue_count_cache: dict[str, int] = {}
    repo_beginner_issue_count_cache: dict[str, int] = {}
    _prime_repo_caches(
        known_issues or [],
        repo_cache=repo_cache,
        repo_activity_cache=repo_activity_cache,
        repo_open_issue_count_cache=repo_open_issue_count_cache,
        repo_beginner_issue_count_cache=repo_beginner_issue_count_cache,
    )
    issues: list[Issue] = []
    skipped: Counter[str] = Counter()
    started = perf_counter()
    _debug(f"repo backfill start repo={repo} page={page} per_page={per_page}")

    with ThreadPoolExecutor(max_workers=MAX_REPO_WORKERS) as executor:
        data = _request_json(
            "/search/issues",
            {
                "q": _build_repo_issue_query(
                    repo=repo,
                    language=language,
                    label=label,
                    updated_days=updated_days,
                ),
                "sort": "updated",
                "order": "desc",
                "per_page": str(per_page),
                "page": str(page),
            },
        )
        items = data.get("items", [])
        _debug(f"repo backfill {repo}: received {len(items)} candidate issues")
        candidates = _candidate_items(items)
        skipped["pull_request_or_unknown_repo"] += len(items) - len(candidates)
        _append_rest_candidates(
            candidates=candidates,
            executor=executor,
            repo_cache=repo_cache,
            repo_activity_cache=repo_activity_cache,
            repo_open_issue_count_cache=repo_open_issue_count_cache,
            repo_beginner_issue_count_cache=repo_beginner_issue_count_cache,
            exclude_repos=frozenset(),
            language=language,
            stars_min=effective_stars_min,
            repo_updated_days=repo_updated_days,
            issues=issues,
            skipped=skipped,
            limit=None,
        )

    _debug(
        f"repo backfill done repo={repo} accepted={len(issues)} in {_elapsed(started)}"
    )
    if skipped:
        _debug(f"repo backfill skipped candidates: {_format_counts(skipped)}")
    return issues


def _search_issue_candidates_graphql(
    *,
    query: str | None = None,
    language: str | None = None,
    stars_min: int | None = None,
    label: str | None = None,
    updated_days: int | None = None,
    repo_updated_days: int | None = None,
    exclude_repos: set[str] = frozenset(),
    limit: int = 10,
    max_pages: int | None = None,
    page_size: int | None = None,
) -> IssueSearchResult:
    """Search GitHub issues via the GraphQL API, filtering out excluded repos."""
    if limit <= 0 or (max_pages is not None and max_pages <= 0):
        return IssueSearchResult(issues=[], exhausted=True)

    effective_stars_min = max(stars_min or DEFAULT_STARS_MIN, DEFAULT_STARS_MIN)
    search_query = _build_issue_query(
        query=query,
        language=language,
        stars_min=effective_stars_min,
        label=label,
        updated_days=updated_days,
        exclude_repos=exclude_repos,
        sort_updated_desc=True,
    )
    issues: list[Issue] = []
    skipped: Counter[str] = Counter()
    exhausted = False
    page_size = min(max(page_size or max(limit * 10, 30), 1), MAX_GRAPHQL_PAGE_SIZE)
    cursor: str | None = None
    search_started = perf_counter()
    allow_page_extension = max_pages is None
    max_pages = max_pages or MAX_GRAPHQL_SEARCH_PAGES
    _debug(
        f"graphql search start query={search_query!r} limit={limit} "
        f"page_size={page_size} max_pages={max_pages}"
    )

    page = 1
    while page <= max_pages:
        page_started = perf_counter()
        data = _request_graphql(
            ISSUE_SEARCH_QUERY,
            {
                "query": search_query,
                "first": page_size,
                "after": cursor,
            },
        )
        search = data.get("search") or {}
        nodes = search.get("nodes") or []
        page_info = search.get("pageInfo") or {}
        _debug(
            f"graphql page {page}: received {len(nodes)} candidate issues "
            f"in {_elapsed(page_started)}"
        )
        if not nodes:
            exhausted = True
            break

        consumed_all_nodes = True
        for index, node in enumerate(nodes):
            issue = _issue_from_graphql_node(node)
            if issue is None:
                skipped["invalid_node"] += 1
                continue
            if issue.stars < effective_stars_min:
                skipped["stars"] += 1
                continue
            if language and issue.language.casefold() != language.casefold():
                skipped["language"] += 1
                continue
            if (
                repo_updated_days is not None
                and issue.repo_last_issue_updated_days > repo_updated_days
            ):
                skipped["repo_activity"] += 1
                continue
            if issue.repo.casefold() in exclude_repos:
                skipped["excluded_repo"] += 1
                continue
            if issue.repo_open_issue_count < MIN_REPO_OPEN_ISSUES:
                skipped["repo_open_issues"] += 1
                continue

            issues.append(issue)
            _debug(f"accepted {len(issues)}/{limit}: {issue.repo}#{node.get('number')}")
            if len(issues) >= limit:
                consumed_all_nodes = index == len(nodes) - 1
                break

        has_next_page = bool(page_info.get("hasNextPage"))
        cursor = page_info.get("endCursor")
        if not has_next_page and consumed_all_nodes:
            exhausted = True
            break
        if len(issues) >= limit:
            break
        if allow_page_extension and _should_extend_search_pages(
            page=page,
            base_max_pages=MAX_GRAPHQL_SEARCH_PAGES,
            max_pages=max_pages,
            results_count=len(issues),
            limit=limit,
        ):
            max_pages = MAX_GRAPHQL_SEARCH_PAGES * EXTENDED_SEARCH_PAGE_MULTIPLIER
            _debug(
                f"graphql search extended to max_pages={max_pages} "
                f"after {len(issues)} accepted issues"
            )
        page += 1

    page_limit_reached = not exhausted and len(issues) < limit
    _debug(
        f"search done accepted={len(issues)} exhausted={exhausted} "
        f"page_limit_reached={page_limit_reached} in {_elapsed(search_started)}"
    )
    if skipped:
        _debug(f"graphql skipped candidates: {_format_counts(skipped)}")
    return IssueSearchResult(
        issues=issues,
        exhausted=exhausted,
        page_limit_reached=page_limit_reached,
    )


def _issue_from_graphql_node(node: Any) -> Issue | None:
    """Convert a GraphQL search result node into an Issue, or None if the node is invalid."""
    if not isinstance(node, dict):
        return None
    repository = node.get("repository")
    if not isinstance(repository, dict):
        return None

    labels = _graphql_labels(node.get("labels"))
    repo = str(repository.get("nameWithOwner") or "")
    if not repo:
        return None

    return Issue(
        repo=repo,
        title=str(node.get("title") or ""),
        url=str(node.get("url") or ""),
        language=_graphql_language(repository),
        stars=int(repository.get("stargazerCount") or 0),
        labels=labels,
        updated_days=_days_since(str(node.get("updatedAt") or "")),
        repo_last_issue_updated_days=_graphql_repo_activity_days(repository),
        repo_open_issue_count=_graphql_open_issue_count(repository),
        repo_beginner_issue_count=_graphql_beginner_issue_count(repository),
        comments=int((node.get("comments") or {}).get("totalCount") or 0),
        has_open_pr=False,
    )


def _search_issue_candidates_rest(
    *,
    query: str | None = None,
    language: str | None = None,
    stars_min: int | None = None,
    label: str | None = None,
    updated_days: int | None = None,
    repo_updated_days: int | None = None,
    exclude_repos: set[str] = frozenset(),
    limit: int = 10,
    max_pages: int | None = None,
    page_size: int | None = None,
) -> IssueSearchResult:
    """Search GitHub issues via the REST API, filtering out excluded repos."""
    if limit <= 0 or (max_pages is not None and max_pages <= 0):
        return IssueSearchResult(issues=[], exhausted=True)

    effective_stars_min = max(stars_min or DEFAULT_STARS_MIN, DEFAULT_STARS_MIN)
    search_query = _build_issue_query(
        query=query,
        language=language,
        stars_min=effective_stars_min,
        label=label,
        updated_days=updated_days,
        exclude_repos=exclude_repos,
    )
    repo_cache: dict[str, dict[str, Any]] = {}
    repo_activity_cache: dict[str, int] = {}
    repo_open_issue_count_cache: dict[str, int] = {}
    repo_beginner_issue_count_cache: dict[str, int] = {}
    issues: list[Issue] = []
    skipped: Counter[str] = Counter()
    exhausted = False
    per_page = min(max(page_size or max(limit * 10, 30), 1), 100)
    search_started = perf_counter()
    allow_page_extension = max_pages is None
    max_pages = max_pages or MAX_REST_SEARCH_PAGES
    _debug(
        f"rest search start query={query!r} limit={limit} per_page={per_page} "
        f"max_pages={max_pages} repo_workers={MAX_REPO_WORKERS}"
    )

    with ThreadPoolExecutor(max_workers=MAX_REPO_WORKERS) as executor:
        page = 1
        while page <= max_pages:
            page_started = perf_counter()
            data = _request_json(
                "/search/issues",
                {
                    "q": search_query,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": str(per_page),
                    "page": str(page),
                },
            )
            items = data.get("items", [])
            _debug(
                f"rest page {page}: received {len(items)} candidate issues "
                f"in {_elapsed(page_started)}"
            )
            if not items:
                exhausted = True
                break

            candidates = _candidate_items(items)
            skipped["pull_request_or_unknown_repo"] += len(items) - len(candidates)
            for index in range(0, len(candidates), MAX_REPO_WORKERS):
                batch = candidates[index : index + MAX_REPO_WORKERS]
                _append_rest_candidates(
                    candidates=batch,
                    executor=executor,
                    repo_cache=repo_cache,
                    repo_activity_cache=repo_activity_cache,
                    repo_open_issue_count_cache=repo_open_issue_count_cache,
                    repo_beginner_issue_count_cache=repo_beginner_issue_count_cache,
                    exclude_repos=exclude_repos,
                    language=language,
                    stars_min=effective_stars_min,
                    repo_updated_days=repo_updated_days,
                    issues=issues,
                    skipped=skipped,
                    limit=limit,
                )
                if len(issues) >= limit:
                    break

            if len(issues) >= limit:
                break
            if allow_page_extension and _should_extend_search_pages(
                page=page,
                base_max_pages=MAX_REST_SEARCH_PAGES,
                max_pages=max_pages,
                results_count=len(issues),
                limit=limit,
            ):
                max_pages = MAX_REST_SEARCH_PAGES * EXTENDED_SEARCH_PAGE_MULTIPLIER
                _debug(
                    f"rest search extended to max_pages={max_pages} "
                    f"after {len(issues)} accepted issues"
                )
            page += 1

    page_limit_reached = not exhausted and len(issues) < limit
    _debug(
        f"search done accepted={len(issues)} exhausted={exhausted} "
        f"page_limit_reached={page_limit_reached} in {_elapsed(search_started)}"
    )
    if skipped:
        _debug(f"rest skipped candidates: {_format_counts(skipped)}")
    return IssueSearchResult(
        issues=issues,
        exhausted=exhausted,
        page_limit_reached=page_limit_reached,
    )


def _should_extend_search_pages(
    *,
    page: int,
    base_max_pages: int,
    max_pages: int,
    results_count: int,
    limit: int,
) -> bool:
    return (
        page == base_max_pages
        and max_pages == base_max_pages
        and limit >= EXTENDED_SEARCH_MIN_RESULTS
        and results_count < EXTENDED_SEARCH_MIN_RESULTS
    )


def _candidate_items(items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    for item in items:
        if "pull_request" in item:
            continue

        repo = _repo_full_name(item)
        if repo is None:
            continue

        candidates.append((item, repo))
    return candidates


def _load_repo_metadata(
    *,
    batch: list[tuple[dict[str, Any], str]],
    executor: ThreadPoolExecutor,
    repo_cache: dict[str, dict[str, Any]],
) -> None:
    futures = {}
    for item, repo in batch:
        if repo in repo_cache or repo in futures:
            continue

        repo_info = _repo_info_from_search_result(item)
        if repo_info is not None:
            repo_cache[repo] = repo_info
            continue

        futures[repo] = (executor.submit(_get_repo, repo), perf_counter())

    for repo, (future, started) in futures.items():
        repo_cache[repo] = future.result()
        _debug(f"{repo}: repo metadata loaded in {_elapsed(started)}")


def _qualified_candidates(
    *,
    batch: list[tuple[dict[str, Any], str]],
    repo_cache: dict[str, dict[str, Any]],
    language: str | None,
    stars_min: int,
) -> list[dict[str, Any]]:
    qualified: list[dict[str, Any]] = []
    for item, repo in batch:
        repo_info = repo_cache[repo]
        stars = int(repo_info.get("stargazers_count") or 0)
        if stars < stars_min:
            continue

        repo_language = str(repo_info.get("language") or "")
        if language and repo_language.casefold() != language.casefold():
            continue

        qualified.append(
            {
                "item": item,
                "repo": repo,
                "language": repo_language,
                "stars": stars,
                "labels": _labels(item),
                "updated_days": _days_since(str(item.get("updated_at") or "")),
            }
        )
    return qualified


def _append_rest_candidates(
    *,
    candidates: list[tuple[dict[str, Any], str]],
    executor: ThreadPoolExecutor,
    repo_cache: dict[str, dict[str, Any]],
    repo_activity_cache: dict[str, int],
    repo_open_issue_count_cache: dict[str, int],
    repo_beginner_issue_count_cache: dict[str, int],
    exclude_repos: set[str] = frozenset(),
    language: str | None,
    stars_min: int,
    repo_updated_days: int | None,
    issues: list[Issue],
    skipped: Counter[str],
    limit: int | None,
) -> None:
    _load_repo_metadata(
        batch=candidates,
        executor=executor,
        repo_cache=repo_cache,
    )

    qualified = _qualified_candidates(
        batch=candidates,
        repo_cache=repo_cache,
        language=language,
        stars_min=stars_min,
    )
    skipped["metadata"] += len(candidates) - len(qualified)
    _load_repo_supplements(
        candidates=qualified,
        executor=executor,
        repo_activity_cache=repo_activity_cache,
        repo_open_issue_count_cache=repo_open_issue_count_cache,
        repo_beginner_issue_count_cache=repo_beginner_issue_count_cache,
    )

    for candidate in qualified:
        repo = candidate["repo"]
        if repo.casefold() in exclude_repos:
            skipped["excluded_repo"] += 1
            continue
        item = candidate["item"]
        if (
            repo_updated_days is not None
            and repo_activity_cache[repo] > repo_updated_days
        ):
            skipped["repo_activity"] += 1
            continue
        if repo_open_issue_count_cache[repo] < MIN_REPO_OPEN_ISSUES:
            skipped["repo_open_issues"] += 1
            continue

        issue = Issue(
            repo=repo,
            title=str(item.get("title") or ""),
            url=str(item.get("html_url") or ""),
            language=candidate["language"],
            stars=candidate["stars"],
            labels=candidate["labels"],
            updated_days=candidate["updated_days"],
            repo_last_issue_updated_days=repo_activity_cache[repo],
            repo_open_issue_count=repo_open_issue_count_cache[repo],
            repo_beginner_issue_count=repo_beginner_issue_count_cache.get(repo, 0),
            comments=int(item.get("comments") or 0),
            has_open_pr=False,
        )
        issues.append(issue)
        if limit is None:
            _debug(f"accepted backfill: {repo}#{item.get('number')}")
        else:
            _debug(f"accepted {len(issues)}/{limit}: {repo}#{item.get('number')}")
        if limit is not None and len(issues) >= limit:
            break


def _prime_repo_caches(
    known_issues: list[Issue],
    *,
    repo_cache: dict[str, dict[str, Any]],
    repo_activity_cache: dict[str, int],
    repo_open_issue_count_cache: dict[str, int],
    repo_beginner_issue_count_cache: dict[str, int],
) -> None:
    for issue in known_issues:
        repo_cache.setdefault(
            issue.repo,
            {
                "full_name": issue.repo,
                "language": issue.language,
                "stargazers_count": issue.stars,
            },
        )
        repo_activity_cache.setdefault(
            issue.repo,
            issue.repo_last_issue_updated_days,
        )
        repo_open_issue_count_cache.setdefault(
            issue.repo,
            issue.repo_open_issue_count,
        )
        repo_beginner_issue_count_cache.setdefault(
            issue.repo,
            issue.repo_beginner_issue_count,
        )


def _format_counts(counts: Counter[str]) -> str:
    return ", ".join(
        f"{name}={count}"
        for name, count in sorted(counts.items())
        if count
    )


def _load_repo_supplements(
    *,
    candidates: list[dict[str, Any]],
    executor: ThreadPoolExecutor,
    repo_activity_cache: dict[str, int],
    repo_open_issue_count_cache: dict[str, int],
    repo_beginner_issue_count_cache: dict[str, int],
) -> None:
    activity_futures = {}
    open_issue_count_futures = {}
    beginner_futures = {}

    for candidate in candidates:
        repo = candidate["repo"]
        if repo not in repo_activity_cache and repo not in activity_futures:
            activity_futures[repo] = (
                executor.submit(_get_repo_last_issue_updated_days, repo),
                perf_counter(),
            )
        if (
            repo not in repo_open_issue_count_cache
            and repo not in open_issue_count_futures
        ):
            open_issue_count_futures[repo] = (
                executor.submit(_get_repo_open_issue_count, repo),
                perf_counter(),
            )
        if (
            _has_beginner_label(candidate["labels"])
            and repo not in repo_beginner_issue_count_cache
            and repo not in beginner_futures
        ):
            beginner_futures[repo] = (
                executor.submit(_get_repo_beginner_issue_count, repo),
                perf_counter(),
            )

    for repo, (future, started) in activity_futures.items():
        repo_activity_cache[repo] = future.result()
        _debug(f"{repo}: repo issue activity loaded in {_elapsed(started)}")

    for repo, (future, started) in open_issue_count_futures.items():
        repo_open_issue_count_cache[repo] = future.result()
        _debug(f"{repo}: open issue count loaded in {_elapsed(started)}")

    for repo, (future, started) in beginner_futures.items():
        repo_beginner_issue_count_cache[repo] = future.result()
        _debug(f"{repo}: beginner issue count loaded in {_elapsed(started)}")


def _build_issue_query(
    *,
    query: str | None = None,
    language: str | None,
    stars_min: int | None,
    label: str | None,
    updated_days: int | None,
    exclude_repos: set[str] = frozenset(),
    sort_updated_desc: bool = False,
) -> str:
    """Build a GitHub search query string with optional filters and repo exclusions."""
    parts = ["is:issue", "is:open", "archived:false", "-linked:pr", "no:assignee"]
    if query:
        parts.append(_quote_query_value(query))
    if language:
        parts.append(f"language:{_quote_query_value(language)}")
    if stars_min is not None:
        parts.append(f"stars:>={stars_min}")
    if label:
        parts.append(f"label:{_quote_query_value(label)}")
    if updated_days is not None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=updated_days)
        parts.append(f"updated:>={cutoff.isoformat()}")
    for excluded in exclude_repos:
        parts.append(f"-repo:{excluded}")
    if sort_updated_desc:
        parts.append("sort:updated-desc")
    return " ".join(parts)


def _build_repo_issue_query(
    *,
    repo: str,
    language: str | None,
    label: str | None,
    updated_days: int | None,
) -> str:
    """Build a GitHub search query string scoped to a single repository."""
    parts = [
        f"repo:{repo}",
        "is:issue",
        "is:open",
        "-linked:pr",
        "no:assignee",
    ]
    if language:
        parts.append(f"language:{_quote_query_value(language)}")
    if label:
        parts.append(f"label:{_quote_query_value(label)}")
    if updated_days is not None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=updated_days)
        parts.append(f"updated:>={cutoff.isoformat()}")
    return " ".join(parts)


def _get_token() -> str | None:
    return os.environ.get(GITHUB_TOKEN_ENV)

def _request_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    token = _get_token()
    if not token:
        raise GitHubAPIError(
            "GitHub GraphQL API requires authentication. Set a GITHUB_TOKEN "
            "environment variable, then try again."
        )

    payload = json.dumps(
        {
            "query": query,
            "variables": variables,
        }
    ).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "oss-issue-scout",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(GITHUB_GRAPHQL_URL, data=payload, headers=headers, method="POST")
    started = perf_counter()
    for attempt in range(1, REQUEST_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
                _debug(f"POST /graphql completed in {_elapsed(started)}")
                errors = result.get("errors")
                if errors:
                    raise GitHubAPIError(_graphql_error_message(errors))
                data = result.get("data")
                if not isinstance(data, dict):
                    raise GitHubAPIError("GitHub GraphQL response did not include data.")
                return data
        except HTTPError as error:
            if _should_retry_http_error(error, attempt):
                _debug(
                    f"POST /graphql failed with HTTP {error.code} after "
                    f"{_elapsed(started)}; retrying"
                )
                _sleep_before_retry()
                continue

            _debug(f"POST /graphql failed with HTTP {error.code} after {_elapsed(started)}")
            _debug_rate_limit_headers(error)
            message = error.read().decode("utf-8", errors="replace")
            if error.code in (401, 403) and "rate limit" in message.casefold():
                raise GitHubAPIError(
                    "GitHub API rate limit exceeded. Set a GITHUB_TOKEN environment "
                    "variable to get a higher rate limit, then try again."
                ) from error
            if error.code in (401, 403):
                raise GitHubAPIError(
                    "GitHub GraphQL authentication failed. Check your GITHUB_TOKEN."
                ) from error
            raise GitHubAPIError(
                f"GitHub GraphQL request failed: HTTP {error.code} {message}"
            ) from error
        except TimeoutError as error:
            _debug(f"POST /graphql timed out after {_elapsed(started)}")
            raise GitHubAPIError(
                f"GitHub GraphQL request timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
            ) from error
        except URLError as error:
            _debug(f"POST /graphql failed after {_elapsed(started)}")
            raise GitHubAPIError(f"GitHub GraphQL request failed: {error.reason}") from error

    raise GitHubAPIError("GitHub GraphQL request failed.")


def _request_json(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{GITHUB_API_BASE}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "oss-issue-scout",
    }
    token = _get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(url, headers=headers)
    started = perf_counter()
    for attempt in range(1, REQUEST_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
                _debug(f"GET {path} completed in {_elapsed(started)}")
                return result
        except HTTPError as error:
            if _should_retry_http_error(error, attempt):
                _debug(
                    f"GET {path} failed with HTTP {error.code} after "
                    f"{_elapsed(started)}; retrying"
                )
                _sleep_before_retry()
                continue

            _debug(f"GET {path} failed with HTTP {error.code} after {_elapsed(started)}")
            _debug_rate_limit_headers(error)
            message = error.read().decode("utf-8", errors="replace")
            if error.code == 403 and "rate limit" in message.casefold():
                raise GitHubAPIError(
                    "GitHub API rate limit exceeded. Set a GITHUB_TOKEN environment "
                    "variable to get a higher rate limit, then try again."
                ) from error
            raise GitHubAPIError(f"GitHub API request failed: HTTP {error.code} {message}") from error
        except TimeoutError as error:
            _debug(f"GET {path} timed out after {_elapsed(started)}")
            raise GitHubAPIError(
                f"GitHub API request timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
            ) from error
        except URLError as error:
            _debug(f"GET {path} failed after {_elapsed(started)}")
            raise GitHubAPIError(f"GitHub API request failed: {error.reason}") from error

    raise GitHubAPIError("GitHub API request failed.")


def _get_repo(repo: str) -> dict[str, Any]:
    owner, name = repo.split("/", 1)
    return _request_json(f"/repos/{quote(owner)}/{quote(name)}")


def _get_repo_last_issue_updated_days(repo: str) -> int:
    data = _request_json(
        "/search/issues",
        {
            "q": f"repo:{repo} is:issue",
            "sort": "updated",
            "order": "desc",
            "per_page": "1",
        },
    )
    items = data.get("items", [])
    if not items:
        return 9999
    return _days_since(str(items[0].get("updated_at") or ""))


def _get_repo_beginner_issue_count(repo: str) -> int:
    data = _request_json(
        "/search/issues",
        {
            "q": f'repo:{repo} is:issue is:open label:"good first issue","help wanted"',
            "per_page": "1",
        },
    )
    return int(data.get("total_count") or 0)


def _get_repo_open_issue_count(repo: str) -> int:
    data = _request_json(
        "/search/issues",
        {
            "q": f"repo:{repo} is:issue is:open",
            "per_page": "1",
        },
    )
    return int(data.get("total_count") or 0)


def _repo_full_name(item: dict[str, Any]) -> str | None:
    repository_url = str(item.get("repository_url") or "")
    marker = f"{GITHUB_API_BASE}/repos/"
    if repository_url.startswith(marker):
        return repository_url.removeprefix(marker)
    repository = item.get("repository")
    if isinstance(repository, dict):
        full_name = repository.get("full_name")
        if isinstance(full_name, str):
            return full_name
    return None


def _repo_info_from_search_result(item: dict[str, Any]) -> dict[str, Any] | None:
    repository = item.get("repository")
    if not isinstance(repository, dict):
        return None
    if "stargazers_count" not in repository or "language" not in repository:
        return None
    return repository


def _labels(item: dict[str, Any]) -> tuple[str, ...]:
    labels = item.get("labels") or []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
    return tuple(names)


def _has_beginner_label(labels: tuple[str, ...]) -> bool:
    beginner_labels = {"good first issue", "help wanted"}
    return bool(beginner_labels.intersection(label.casefold() for label in labels))


def _graphql_error_message(errors: Any) -> str:
    if not isinstance(errors, list) or not errors:
        return "GitHub GraphQL request failed."
    messages = []
    seen_messages = set()
    for error in errors:
        if isinstance(error, dict):
            message = str(error.get("message") or "unknown GraphQL error")
            if str(error.get("type") or "").casefold() == "rate_limited":
                message = (
                    "GitHub API rate limit exceeded. Set a GITHUB_TOKEN environment "
                    "variable to get a higher rate limit, then try again."
                )
            if message in seen_messages:
                continue
            seen_messages.add(message)
            messages.append(message)
    return "; ".join(messages) if messages else "GitHub GraphQL request failed."


def _is_graphql_resource_limit_error(error: GitHubAPIError) -> bool:
    return "resource limits for this query exceeded" in str(error).casefold()


def _should_retry_http_error(error: HTTPError, attempt: int) -> bool:
    return (
        error.code in TRANSIENT_HTTP_STATUS_CODES
        and attempt < REQUEST_RETRY_ATTEMPTS
    )


def _sleep_before_retry() -> None:
    if REQUEST_RETRY_DELAY_SECONDS > 0:
        sleep(REQUEST_RETRY_DELAY_SECONDS)


def _debug_rate_limit_headers(error: HTTPError) -> None:
    headers = error.headers
    if not headers:
        return
    values = {
        "resource": headers.get("x-ratelimit-resource"),
        "limit": headers.get("x-ratelimit-limit"),
        "remaining": headers.get("x-ratelimit-remaining"),
        "reset": headers.get("x-ratelimit-reset"),
        "retry-after": headers.get("retry-after"),
    }
    details = ", ".join(
        f"{name}={value}"
        for name, value in values.items()
        if value is not None
    )
    if details:
        _debug(f"rate limit headers: {details}")


def _graphql_labels(labels_connection: Any) -> tuple[str, ...]:
    labels = []
    if isinstance(labels_connection, dict):
        labels = labels_connection.get("nodes") or []
    names: list[str] = []
    for label in labels:
        if isinstance(label, dict) and isinstance(label.get("name"), str):
            names.append(label["name"])
    return tuple(names)


def _graphql_language(repository: dict[str, Any]) -> str:
    primary_language = repository.get("primaryLanguage")
    if not isinstance(primary_language, dict):
        return ""
    return str(primary_language.get("name") or "")


def _graphql_repo_activity_days(repository: dict[str, Any]) -> int:
    issues = repository.get("issues")
    if not isinstance(issues, dict):
        return 9999
    nodes = issues.get("nodes") or []
    if not nodes:
        return 9999
    first_issue = nodes[0]
    if not isinstance(first_issue, dict):
        return 9999
    return _days_since(str(first_issue.get("updatedAt") or ""))


def _graphql_beginner_issue_count(repository: dict[str, Any]) -> int:
    good_first = repository.get("goodFirstIssues") or {}
    help_wanted = repository.get("helpWantedIssues") or {}
    return int(good_first.get("totalCount") or 0) + int(
        help_wanted.get("totalCount") or 0
    )


def _graphql_open_issue_count(repository: dict[str, Any]) -> int:
    open_issues = repository.get("openIssues") or {}
    return int(open_issues.get("totalCount") or 0)


def _days_since(value: str) -> int:
    if not value:
        return 9999
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    delta = datetime.now(timezone.utc) - timestamp
    return max(delta.days, 0)


def _quote_query_value(value: str) -> str:
    if not value.replace("_", "").replace("-", "").isalnum():
        return f'"{value}"'
    return value


def _debug(message: str) -> None:
    if DEBUG_ENABLED:
        print(f"[oss-issue-scout] {message}", file=sys.stderr)


def _elapsed(started: float) -> str:
    return f"{perf_counter() - started:.2f}s"