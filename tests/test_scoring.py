import unittest

from oss_issue_scout.github_api import Issue
from oss_issue_scout.scoring import score_issue, score_issues


class ScoringTests(unittest.TestCase):
    def test_score_contains_reasons(self) -> None:
        issue = Issue(
            repo="example/large",
            title="Improve docs",
            url="https://github.com/example/large/issues/1",
            language="python",
            stars=68_000,
            labels=("good first issue",),
            updated_days=2,
            repo_last_issue_updated_days=2,
            repo_beginner_issue_count=3,
            comments=1,
            has_open_pr=False,
        )

        scored = score_issue(issue)

        self.assertGreater(scored.score, 0)
        self.assertIn("large repo may be competitive", scored.warnings)
        self.assertIn("issue updated in the last 3 days", scored.reasons)
        self.assertIn("repo issue activity in the last 3 days", scored.reasons)

    def test_very_large_repos_are_penalized(self) -> None:
        issue = Issue(
            repo="example/huge",
            title="Small docs cleanup",
            url="https://github.com/example/huge/issues/1",
            language="python",
            stars=120_000,
            labels=("good first issue",),
            updated_days=2,
            repo_last_issue_updated_days=2,
            repo_beginner_issue_count=3,
            comments=1,
            has_open_pr=False,
        )

        scored = score_issue(issue)

        self.assertIn("very large repo may be competitive", scored.warnings)
        self.assertNotIn("active repo", scored.reasons)

    def test_score_issues_sorts_highest_first(self) -> None:
        issues = [
            Issue(
                repo="example/high",
                title="Small docs cleanup",
                url="https://github.com/example/high/issues/1",
                language="python",
                stars=12_000,
                labels=("good first issue",),
                updated_days=1,
                repo_last_issue_updated_days=1,
                repo_beginner_issue_count=3,
                comments=1,
                has_open_pr=False,
            ),
            Issue(
                repo="example/low",
                title="Long stale bug",
                url="https://github.com/example/low/issues/2",
                language="python",
                stars=80_000,
                labels=("bug",),
                updated_days=80,
                repo_last_issue_updated_days=80,
                repo_beginner_issue_count=0,
                comments=20,
                has_open_pr=False,
            ),
        ]
        scored = score_issues(issues)

        self.assertEqual(
            [result.score for result in scored],
            sorted((result.score for result in scored), reverse=True),
        )

    def test_beginner_label_bonus_requires_repo_depth(self) -> None:
        issue = Issue(
            repo="example/thin",
            title="Small docs cleanup",
            url="https://github.com/example/thin/issues/1",
            language="python",
            stars=12_000,
            labels=("good first issue",),
            updated_days=1,
            repo_last_issue_updated_days=1,
            repo_beginner_issue_count=2,
            comments=1,
            has_open_pr=False,
        )

        scored = score_issue(issue)

        self.assertNotIn("welcoming label", scored.reasons)

    def test_junior_preset_uses_junior_scoring_rules(self) -> None:
        issue = _issue(
            repo="example/small",
            title="Docs fix",
            stars=500,
            labels=("good first issue",),
            updated_days=1,
            repo_last_issue_updated_days=1,
            repo_beginner_issue_count=3,
            comments=1,
        )

        scored = score_issues([issue], preset="junior")[0]

        self.assertIn("small beginner-friendly repo", scored.reasons)
        self.assertIn("beginner-friendly label", scored.reasons)

    def test_preset_can_change_result_order(self) -> None:
        small_repo_issue = _issue(
            repo="example/small",
            title="Small repo docs",
            stars=500,
            labels=("good first issue",),
        )
        larger_repo_issue = _issue(
            repo="example/larger",
            title="Larger repo docs",
            stars=12_000,
            labels=("good first issue",),
        )

        default_results = score_issues([small_repo_issue, larger_repo_issue])
        junior_results = score_issues(
            [small_repo_issue, larger_repo_issue],
            preset="junior",
        )

        self.assertEqual(default_results[0].issue.repo, "example/larger")
        self.assertEqual(junior_results[0].issue.repo, "example/small")

    def test_unknown_preset_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as raised:
            score_issues([_issue(repo="example/repo")], preset="unknown")

        self.assertIn("unknown preset", str(raised.exception))


def _issue(
    *,
    repo: str,
    title: str = "Improve docs",
    stars: int = 12_000,
    labels: tuple[str, ...] = ("good first issue",),
    updated_days: int = 1,
    repo_last_issue_updated_days: int = 1,
    repo_beginner_issue_count: int = 3,
    comments: int = 1,
) -> Issue:
    return Issue(
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/issues/{title.replace(' ', '-')}",
        language="python",
        stars=stars,
        labels=labels,
        updated_days=updated_days,
        repo_last_issue_updated_days=repo_last_issue_updated_days,
        repo_beginner_issue_count=repo_beginner_issue_count,
        comments=comments,
        has_open_pr=False,
    )


if __name__ == "__main__":
    unittest.main()
