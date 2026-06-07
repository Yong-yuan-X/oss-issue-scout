from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from time import sleep

from .config import (
    BACKFILL_DELAY_SECONDS,
    BACKFILL_PAGES_PER_REPO,
    BACKFILL_PER_PAGE,
    BACKFILL_REPO_LIMIT,
    CANDIDATE_MULTIPLIER,
    MAX_CANDIDATE_LIMIT,
    MAX_USER_LIMIT,
    MIN_RECOMMENDED_SCORE,
    RECOMMENDATION_SEARCH_PAGE_SIZE,
    RECOMMENDATION_SEARCH_PAGE_STEPS,
)
from .github_api import (
    GitHubAPIError,
    Issue,
    IssueSearchResult,
    backfill_issue_candidates,
    search_issue_candidates,
)
from .output import render_results
from .scoring import ScoredIssue, score_issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oss-issue-scout")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="search GitHub issues")
    search_parser.add_argument("--language")
    search_parser.add_argument("--query")
    search_parser.add_argument("--stars-min", type=int)
    search_parser.add_argument("--label")
    search_parser.add_argument("--updated-days", type=int)
    search_parser.add_argument("--repo-updated-days", type=int)
    search_parser.add_argument("--limit", type=_positive_int, default=6)
    search_parser.add_argument(
        "--preset",
        choices=("default", "junior", "intermediate", "senior"),
        default="default",
    )
    search_parser.add_argument(
        "--format",
        choices=("table", "markdown", "json"),
        default="table",
    )
    search_parser.set_defaults(func=_run_search)
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    if parsed > MAX_USER_LIMIT:
        raise argparse.ArgumentTypeError(f"must be at most {MAX_USER_LIMIT}")
    return parsed


def _run_search(args: argparse.Namespace) -> int:
    try:
        results = _search_recommended(args)
    except GitHubAPIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(render_results(results, args.format))
    return 0


def _search_recommended(args: argparse.Namespace) -> list[ScoredIssue]:
    candidate_limit = min(args.limit * CANDIDATE_MULTIPLIER, MAX_CANDIDATE_LIMIT)
    issues_by_url: dict[str, Issue] = {}

    search_result = search_issue_candidates(
        query=args.query,
        language=args.language,
        stars_min=args.stars_min,
        label=args.label,
        updated_days=args.updated_days,
        repo_updated_days=args.repo_updated_days,
        limit=candidate_limit,
    )
    selected_results = _select_search_results(
        args=args,
        search_result=search_result,
        issues_by_url=issues_by_url,
        allow_low_scores=(
            search_result.page_limit_reached
            or len(search_result.issues) >= MAX_CANDIDATE_LIMIT
        ),
    )
    if selected_results is not None:
        return selected_results

    for index, max_pages in enumerate(RECOMMENDATION_SEARCH_PAGE_STEPS):
        search_result = search_issue_candidates(
            query=args.query,
            language=args.language,
            stars_min=args.stars_min,
            label=args.label,
            updated_days=args.updated_days,
            repo_updated_days=args.repo_updated_days,
            limit=MAX_CANDIDATE_LIMIT,
            max_pages=max_pages,
            page_size=RECOMMENDATION_SEARCH_PAGE_SIZE,
        )
        is_final_step = index == len(RECOMMENDATION_SEARCH_PAGE_STEPS) - 1
        selected_results = _select_search_results(
            args=args,
            search_result=search_result,
            issues_by_url=issues_by_url,
            allow_low_scores=is_final_step,
        )
        if selected_results is not None:
            return selected_results

    return []


def _select_search_results(
    *,
    args: argparse.Namespace,
    search_result: IssueSearchResult,
    issues_by_url: dict[str, Issue],
    allow_low_scores: bool,
) -> list[ScoredIssue] | None:
    for issue in search_result.issues:
        issues_by_url.setdefault(issue.url, issue)

    scored_results = score_issues(list(issues_by_url.values()), args.preset)
    recommended_results = _select_results(
        scored_results,
        limit=args.limit,
        allow_low_scores=False,
    )
    if len(recommended_results) >= args.limit:
        return recommended_results

    if search_result.exhausted:
        backfill_results = _backfill_recommendations(
            args=args,
            issues_by_url=issues_by_url,
        )
        if len(backfill_results) >= args.limit:
            return backfill_results
        scored_results = score_issues(list(issues_by_url.values()), args.preset)
        allow_low_scores = True

    if allow_low_scores and (
        search_result.exhausted
        or search_result.page_limit_reached
        or len(issues_by_url) >= MAX_CANDIDATE_LIMIT
    ):
        return _select_results(
            scored_results,
            limit=args.limit,
            allow_low_scores=True,
        )

    return None


def _backfill_recommendations(
    *,
    args: argparse.Namespace,
    issues_by_url: dict[str, Issue],
) -> list[ScoredIssue]:
    repos = _backfill_repos(issues_by_url.values())
    if not repos:
        return []

    for page in range(1, BACKFILL_PAGES_PER_REPO + 1):
        for repo_index, repo in enumerate(repos):
            issues = _backfill_repo(
                args=args,
                repo=repo,
                known_issues=list(issues_by_url.values()),
                page=page,
            )
            for issue in issues:
                issues_by_url.setdefault(issue.url, issue)

            scored_results = score_issues(list(issues_by_url.values()), args.preset)
            recommended_results = _select_results(
                scored_results,
                limit=args.limit,
                allow_low_scores=False,
            )
            if len(recommended_results) >= args.limit:
                return recommended_results
            if _should_delay_backfill(repo_index, repos):
                sleep(BACKFILL_DELAY_SECONDS)

    return _select_results(
        score_issues(list(issues_by_url.values()), args.preset),
        limit=args.limit,
        allow_low_scores=False,
    )


def _backfill_repos(issues: Iterable[Issue]) -> list[str]:
    repos: list[str] = []
    seen = set()
    for issue in issues:
        repo = issue.repo
        if repo in seen:
            continue
        seen.add(repo)
        repos.append(repo)
        if len(repos) >= BACKFILL_REPO_LIMIT:
            break
    return repos


def _backfill_repo(
    *,
    args: argparse.Namespace,
    repo: str,
    known_issues: list[Issue],
    page: int,
) -> list[Issue]:
    try:
        return backfill_issue_candidates(
            repo=repo,
            known_issues=known_issues,
            language=args.language,
            stars_min=args.stars_min,
            label=args.label,
            updated_days=args.updated_days,
            repo_updated_days=args.repo_updated_days,
            per_page=BACKFILL_PER_PAGE,
            page=page,
        )
    except GitHubAPIError as error:
        if _is_rate_limit_error(error):
            return []
        raise


def _select_results(
    results: list[ScoredIssue],
    *,
    limit: int,
    allow_low_scores: bool,
) -> list[ScoredIssue]:
    selected: list[ScoredIssue] = []
    repo_counts: dict[str, int] = {}
    per_repo_limit = _per_repo_result_limit(limit)

    for result in results:
        if not allow_low_scores and result.score < MIN_RECOMMENDED_SCORE:
            continue
        repo = result.issue.repo
        if repo_counts.get(repo, 0) >= per_repo_limit:
            continue

        selected.append(result)
        repo_counts[repo] = repo_counts.get(repo, 0) + 1
        if len(selected) >= limit:
            break

    return selected


def _per_repo_result_limit(limit: int) -> int:
    if limit <= 5:
        return 1
    return limit // 5 + 1


def _is_rate_limit_error(error: GitHubAPIError) -> bool:
    return "rate limit" in str(error).casefold()


def _should_delay_backfill(repo_index: int, repos: list[str]) -> bool:
    return BACKFILL_DELAY_SECONDS > 0 and repo_index < len(repos) - 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
