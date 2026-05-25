from __future__ import annotations

import argparse
import sys

from .github_api import GitHubAPIError, search_issues
from .output import render_results
from .scoring import score_issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oss-issue-scout")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="search GitHub issues")
    search_parser.add_argument("--language")
    search_parser.add_argument("--stars-min", type=int)
    search_parser.add_argument("--label")
    search_parser.add_argument("--updated-days", type=int)
    search_parser.add_argument("--repo-updated-days", type=int)
    search_parser.add_argument("--limit", type=_positive_int, default=10)
    search_parser.add_argument("--preset", choices=["default", "junior", "intermediate", "senior"], default="default")
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
    return parsed


def _run_search(args: argparse.Namespace) -> int:
    try:
        issues = search_issues(
            language=args.language,
            stars_min=args.stars_min,
            label=args.label,
            updated_days=args.updated_days,
            repo_updated_days=args.repo_updated_days,
            limit=args.limit,
        )
    except GitHubAPIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    results = score_issues(issues, args.preset)[: args.limit]
    print(render_results(results, args.format))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
