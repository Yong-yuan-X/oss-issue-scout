import contextlib
import io
import unittest
from unittest.mock import patch

from oss_issue_scout.cli import main
from oss_issue_scout.github_api import GitHubAPIError, Issue


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

        with patch("oss_issue_scout.cli.search_issues", return_value=[issue]) as search, contextlib.redirect_stdout(stdout):
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
        output = stdout.getvalue()
        self.assertIn("score", output)
        self.assertIn("example/project", output)

    def test_search_passes_selected_preset_to_scoring(self) -> None:
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

        with (
            patch("oss_issue_scout.cli.search_issues", return_value=[issue]),
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

    def test_search_handles_github_api_errors(self) -> None:
        stderr = io.StringIO()

        with patch("oss_issue_scout.cli.search_issues", side_effect=GitHubAPIError("rate limited")), contextlib.redirect_stderr(stderr):
            exit_code = main(["search", "--language", "python"])

        self.assertEqual(exit_code, 1)
        self.assertIn("rate limited", stderr.getvalue())

    def test_search_rejects_non_positive_limit(self) -> None:
        stderr = io.StringIO()

        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(stderr):
            main(["search", "--limit", "0"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("must be greater than 0", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
