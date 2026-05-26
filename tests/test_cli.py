import contextlib
import io
import unittest
from unittest.mock import patch

from oss_issue_scout.cli import _select_results, main
from oss_issue_scout.github_api import GitHubAPIError, Issue, IssueSearchResult
from oss_issue_scout.scoring import ScoredIssue


class CliTests(unittest.TestCase):
    def test_search_outputs_matching_results(self) -> None:
        stdout = io.StringIO()
        issue = Issue(
            repo="example/project",
            title="Improve docs",
            url="https://github.com/example/project/issues/1",
            language="python",
            stars=12_000,
            labels=("good first issue",),
            updated_days=1,
            repo_last_issue_updated_days=1,
            repo_beginner_issue_count=3,
            comments=1,
            has_open_pr=False,
        )

        with patch(
            "oss_issue_scout.cli.search_issue_candidates",
            return_value=IssueSearchResult(issues=[issue], exhausted=False),
        ) as search, contextlib.redirect_stdout(stdout):
            exit_code = main(
                [
                    "search",
                    "--language",
                    "python",
                    "--repo-updated-days",
                    "7",
                    "--limit",
                    "1",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(search.call_args.kwargs["repo_updated_days"], 7)
        self.assertEqual(search.call_args.kwargs["limit"], 2)
        output = stdout.getvalue()
        self.assertIn("score", output)
        self.assertIn("example/project", output)

    def test_search_passes_selected_preset_to_scoring(self) -> None:
        issue = _issue("Preset issue")

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[issue],
                    exhausted=False,
                    page_limit_reached=True,
                ),
            ),
            patch("oss_issue_scout.cli.score_issues", return_value=[]) as score_issues,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = main(
                [
                    "search",
                    "--language",
                    "python",
                    "--preset",
                    "intermediate",
                ]
            )

        self.assertEqual(exit_code, 0)
        score_issues.assert_called_once_with([issue], "intermediate")

    def test_search_uses_default_limit_of_six(self) -> None:
        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(issues=[], exhausted=False),
            ) as search,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = main(["search"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(search.call_args_list[0].kwargs["limit"], 12)

    def test_search_backfills_repos_when_global_search_is_exhausted(self) -> None:
        stdout = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[_issue("High score")],
                    exhausted=True,
                ),
            ),
            patch(
                "oss_issue_scout.cli.backfill_issue_candidates",
                return_value=[
                    _issue("Backfilled high score", repo="example/other"),
                ],
            ) as backfill,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        backfill.assert_called_once()
        self.assertEqual(backfill.call_args.kwargs["repo"], "example/project")
        self.assertEqual(
            [issue.title for issue in backfill.call_args.kwargs["known_issues"]],
            ["High score"],
        )
        self.assertEqual(backfill.call_args.kwargs["per_page"], 25)
        self.assertEqual(backfill.call_args.kwargs["page"], 1)
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Backfilled high score", output)

    def test_search_stops_backfilling_after_results_are_filled(self) -> None:
        stdout = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[
                        _issue("High score", repo="example/one"),
                        _issue("Seed two", low_score=True, repo="example/two"),
                    ],
                    exhausted=True,
                ),
            ),
            patch(
                "oss_issue_scout.cli.backfill_issue_candidates",
                return_value=[
                    _issue("Backfilled high score", repo="example/two"),
                ],
            ) as backfill,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        backfill.assert_called_once()
        self.assertEqual(backfill.call_args.kwargs["repo"], "example/one")
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Backfilled high score", output)

    def test_search_skips_rate_limited_backfill_repo(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[
                        _issue("High score", repo="example/one"),
                        _issue("Seed two", low_score=True, repo="example/two"),
                        _issue("Seed three", low_score=True, repo="example/three"),
                    ],
                    exhausted=True,
                ),
            ),
            patch(
                "oss_issue_scout.cli.backfill_issue_candidates",
                side_effect=[
                    GitHubAPIError("GitHub API rate limit exceeded."),
                    [_issue("Backfilled high score", repo="example/three")],
                ],
            ) as backfill,
            patch("oss_issue_scout.cli.sleep") as sleep,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(backfill.call_count, 2)
        self.assertEqual(
            [call.kwargs["repo"] for call in backfill.call_args_list],
            ["example/one", "example/two"],
        )
        sleep.assert_called_once_with(1)
        self.assertEqual(stderr.getvalue(), "")
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Backfilled high score", output)

    def test_search_uses_low_score_backfill_when_global_search_is_exhausted(self) -> None:
        stdout = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[_issue("High score", repo="example/one")],
                    exhausted=True,
                ),
            ),
            patch(
                "oss_issue_scout.cli.backfill_issue_candidates",
                return_value=[
                    _issue("Backfilled low score", low_score=True, repo="example/two"),
                ],
            ),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Backfilled low score", output)

    def test_search_deepens_by_page_steps_before_using_low_scores(self) -> None:
        stdout = io.StringIO()

        with (
            patch("oss_issue_scout.cli.RECOMMENDATION_SEARCH_PAGE_STEPS", (1, 3)),
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                side_effect=[
                    IssueSearchResult(
                        issues=[
                            _issue("High score"),
                            _issue(
                                "Low score",
                                low_score=True,
                                repo="example/other",
                            ),
                        ],
                        exhausted=False,
                    ),
                    IssueSearchResult(
                        issues=[
                            _issue("High score"),
                            _issue(
                                "Low score",
                                low_score=True,
                                repo="example/other",
                            ),
                        ],
                        exhausted=False,
                        page_limit_reached=True,
                    ),
                    IssueSearchResult(
                        issues=[
                            _issue("High score"),
                            _issue(
                                "Low score",
                                low_score=True,
                                repo="example/other",
                            ),
                        ],
                        exhausted=False,
                        page_limit_reached=True,
                    ),
                ],
            ) as search,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [call.kwargs["limit"] for call in search.call_args_list],
            [4, 500, 500],
        )
        self.assertEqual(
            [call.kwargs.get("max_pages") for call in search.call_args_list],
            [None, 1, 3],
        )
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Low score", output)

    def test_search_deepens_to_candidate_cap_until_limit_is_filled(self) -> None:
        stdout = io.StringIO()

        with patch(
            "oss_issue_scout.cli.search_issue_candidates",
            side_effect=[
                IssueSearchResult(
                    issues=[_issue("High score"), _issue("Low score", low_score=True)],
                    exhausted=False,
                ),
                IssueSearchResult(
                    issues=[
                        _issue("High score"),
                        _issue("Low score", low_score=True),
                        _issue("Second high score", repo="example/other"),
                    ],
                    exhausted=False,
                ),
            ],
        ) as search, contextlib.redirect_stdout(stdout):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [call.kwargs["limit"] for call in search.call_args_list],
            [4, 500],
        )
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Second high score", output)
        self.assertNotIn("Low score", output)

    def test_search_uses_low_scores_when_search_is_exhausted_before_candidate_cap(self) -> None:
        stdout = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[
                        _issue("High score"),
                        _issue("Low score", low_score=True, repo="example/other"),
                    ],
                    exhausted=True,
                ),
            ),
            patch("oss_issue_scout.cli.backfill_issue_candidates", return_value=[]),
            patch("oss_issue_scout.cli.sleep"),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Low score", output)

    def test_search_uses_low_scores_when_candidate_cap_is_filled(self) -> None:
        stdout = io.StringIO()

        with (
            patch("oss_issue_scout.cli.MAX_CANDIDATE_LIMIT", 4),
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                return_value=IssueSearchResult(
                    issues=[
                        _issue("High score"),
                        _issue("Low score", low_score=True, repo="example/other"),
                        _issue("Low score 2", low_score=True),
                        _issue("Low score 3", low_score=True),
                    ],
                    exhausted=False,
                ),
            ) as search,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(search.call_args.kwargs["limit"], 4)
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Low score", output)

    def test_search_uses_low_scores_when_deep_search_is_exhausted_early(self) -> None:
        stdout = io.StringIO()

        with (
            patch(
                "oss_issue_scout.cli.search_issue_candidates",
                side_effect=[
                    IssueSearchResult(
                        issues=[
                            _issue("High score"),
                            _issue(
                                "Low score",
                                low_score=True,
                                repo="example/other",
                            ),
                        ],
                        exhausted=False,
                    ),
                    IssueSearchResult(
                        issues=[
                            _issue("High score"),
                            _issue(
                                "Low score",
                                low_score=True,
                                repo="example/other",
                            ),
                        ],
                        exhausted=True,
                    ),
                ],
            ),
            patch("oss_issue_scout.cli.backfill_issue_candidates", return_value=[]),
            patch("oss_issue_scout.cli.sleep"),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = main(["search", "--limit", "2"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("High score", output)
        self.assertIn("Low score", output)

    def test_search_includes_minimum_recommended_score(self) -> None:
        result = ScoredIssue(
            issue=_issue("Minimum score"),
            score=85,
            reasons=(),
            warnings=(),
        )

        self.assertEqual(
            _select_results([result], limit=1, allow_low_scores=False),
            [result],
        )

    def test_search_limits_results_from_same_repo_to_two_for_limit_six(self) -> None:
        results = [
            _scored_issue("A1", repo="example/one"),
            _scored_issue("A2", repo="example/one"),
            _scored_issue("A3", repo="example/one"),
            _scored_issue("B1", repo="example/two"),
            _scored_issue("B2", repo="example/two"),
            _scored_issue("C1", repo="example/three"),
            _scored_issue("D1", repo="example/four"),
        ]

        selected = _select_results(results, limit=6, allow_low_scores=False)

        self.assertEqual(
            [result.issue.title for result in selected],
            ["A1", "A2", "B1", "B2", "C1", "D1"],
        )

    def test_search_limits_results_from_same_repo_to_three_for_limit_ten(self) -> None:
        results = [
            _scored_issue("A1", repo="example/one"),
            _scored_issue("A2", repo="example/one"),
            _scored_issue("A3", repo="example/one"),
            _scored_issue("A4", repo="example/one"),
            _scored_issue("B1", repo="example/two"),
            _scored_issue("B2", repo="example/two"),
            _scored_issue("B3", repo="example/two"),
            _scored_issue("B4", repo="example/two"),
        ]

        selected = _select_results(results, limit=10, allow_low_scores=False)

        self.assertEqual(
            [result.issue.title for result in selected],
            ["A1", "A2", "A3", "B1", "B2", "B3"],
        )

    def test_search_handles_github_api_errors(self) -> None:
        stderr = io.StringIO()

        with patch("oss_issue_scout.cli.search_issue_candidates", side_effect=GitHubAPIError("rate limited")), contextlib.redirect_stderr(stderr):
            exit_code = main(["search", "--language", "python"])

        self.assertEqual(exit_code, 1)
        self.assertIn("rate limited", stderr.getvalue())

    def test_search_rejects_non_positive_limit(self) -> None:
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(stderr):
            main(["search", "--limit", "0"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("must be greater than 0", stderr.getvalue())

    def test_search_rejects_limit_above_maximum(self) -> None:
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(stderr):
            main(["search", "--limit", "251"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("must be at most 250", stderr.getvalue())


def _issue(
    title: str,
    *,
    low_score: bool = False,
    repo: str = "example/project",
) -> Issue:
    return Issue(
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/issues/{title.replace(' ', '-')}",
        language="python",
        stars=100 if low_score else 12_000,
        labels=() if low_score else ("good first issue",),
        updated_days=40 if low_score else 1,
        repo_last_issue_updated_days=40 if low_score else 1,
        repo_beginner_issue_count=0 if low_score else 3,
        comments=5 if low_score else 1,
        has_open_pr=False,
    )


def _scored_issue(title: str, *, repo: str) -> ScoredIssue:
    return ScoredIssue(
        issue=_issue(title, repo=repo),
        score=100,
        reasons=(),
        warnings=(),
    )


if __name__ == "__main__":
    unittest.main()
