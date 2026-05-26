from __future__ import annotations

from dataclasses import dataclass

from . import scoring_presets
from .github_api import Issue


@dataclass(frozen=True)
class ScoredIssue:
    issue: Issue
    score: int
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def in_range(value: int, minimum: int, maximum: int | None) -> bool:
    return minimum <= value and (maximum is None or value <= maximum)


def score_issue(issue: Issue, preset: dict | None = None) -> ScoredIssue:
    score = 50
    reasons: list[str] = []
    warnings: list[str] = []

    if preset is None:
        preset = scoring_presets.default

    for factor_name, rules in preset.items():
        if factor_name == "special_rules":
            continue

        value = getattr(issue, factor_name)

        for rule in rules:
            if in_range(value, rule.minimum, rule.maximum):
                score += rule.score_delta

                if rule.rule_type == "reason":
                    reasons.append(rule.message)
                elif rule.rule_type == "warning":
                    warnings.append(rule.message)

    for rule in preset["special_rules"]:
        if (
            rule.labels_any.intersection(issue.labels)
            and issue.repo_beginner_issue_count >= rule.repo_beginner_issue_count_min
        ):
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
        preset_map = {
            "default": scoring_presets.default,
            "junior": scoring_presets.junior,
            "intermediate": scoring_presets.intermediate,
            "senior": scoring_presets.senior,
        }

        try:
            preset_obj = preset_map[preset]
        except KeyError as exc:
            raise ValueError(f"unknown preset: {preset}") from exc

    return sorted(
        (score_issue(issue, preset=preset_obj) for issue in issues),
        key=lambda scored: scored.score,
        reverse=True,
    )
