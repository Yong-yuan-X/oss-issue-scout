from __future__ import annotations

from dataclasses import dataclass

from .github_api import Issue
from . import scoring_presets


@dataclass(frozen=True)
class ScoredIssue:
    issue: Issue
    score: int
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def score_issue(issue: Issue, preset: dict | None = None) -> ScoredIssue:

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


def score_issues(issues: list[Issue], preset: str | None = None) -> list[ScoredIssue]:
    if preset is None:
        preset_obj = scoring_presets.default
    elif isinstance(preset, str):
        try:
            preset_obj = getattr(scoring_presets, preset)
        except AttributeError as exc:
            raise ValueError(f"unknown preset: {preset}") from exc

    return sorted(
        (score_issue(issue, preset=preset_obj) for issue in issues),
        key=lambda scored: scored.score,
        reverse=True,
    )
