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
    
    if preset is None:
        preset = scoring_presets.default

    for factor in preset:
        if factor == "special_rules":
            for rule in preset[factor]:
                if rule.labels_any.intersection(issue.labels) and issue.repo_beginner_issue_count >= rule.repo_beginner_issue_count_min:
                    score += rule.score_delta

                    if rule.rule_type == "reason":
                        reasons.append(rule.message)
                    elif rule.rule_type == "warning":
                        warnings.append(rule.message)

        else:
            for rule in preset[factor]:
                if rule.minimum <= issue.stars <= rule.maximum:
                    score += rule.score_delta

                    if rule.rule_type == "reason":
                        reasons.append(rule.message)
                    elif rule.rule_type == "warning":
                        warnings.append(rule.message)

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
