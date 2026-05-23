from __future__ import annotations

from dataclasses import dataclass

from .github_api import Issue


@dataclass(frozen=True)
class ScoredIssue:
    issue: Issue
    score: int
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def score_issue(issue: Issue) -> ScoredIssue:

    score = 50
    reasons: list[str] = []
    warnings: list[str] = []
    
    # Need to add code later

    return ScoredIssue(
        issue=issue,
        score=max(score, 0),
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def score_issues(issues: list[Issue]) -> list[ScoredIssue]:

    return sorted(
        (score_issue(issue) for issue in issues),
        key=lambda scored: scored.score,
        reverse=True,
    )
