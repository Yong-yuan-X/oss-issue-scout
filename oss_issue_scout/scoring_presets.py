from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RuleType = Literal["reason", "warning"]


@dataclass(frozen=True)
class ScoreRule:
    minimum: int
    maximum: int | None
    score_delta: int
    message: str
    rule_type: RuleType

@dataclass(frozen=True)
class SpecialRule:
    labels_any: set[str]
    repo_beginner_issue_count_min: int
    score_delta: int
    message: str
    rule_type: RuleType


#Presets
default = {
    "stars": [
        ScoreRule(
            minimum=500,
            maximum=4_999,
            score_delta=5,
            message="somewhat active repo",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=5_000,
            maximum=9_999,
            score_delta=10,
            message="moderately active repo",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=10_000,
            maximum=49_999,
            score_delta=15,
            message="active repo",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=50_000,
            maximum=99_999,
            score_delta=-10,
            message="large repo may be competitive",
            rule_type="warning",
        ),

        ScoreRule(
            minimum=100_000,
            maximum=None,
            score_delta=-15,
            message="very large repo may be competitive",
            rule_type="warning",
        ),
    ],

    "updated_days": [
        ScoreRule(
            minimum=0,
            maximum=1,
            score_delta=15,
            message="issue updated today",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=2,
            maximum=3,
            score_delta=10,
            message="issue updated in the last 3 days",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=4,
            maximum=14,
            score_delta=5,
            message="issue updated in the last 2 weeks",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=31,
            maximum=None,
            score_delta=-20,
            message="issue looks stale",
            rule_type="warning",
        ),
    ],

    "repo_last_issue_updated_days": [
        ScoreRule(
            minimum=0,
            maximum=3,
            score_delta=30,
            message="repo issue activity in the last 3 days",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=4,
            maximum=7,
            score_delta=15,
            message="repo issue activity this week",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=8,
            maximum=14,
            score_delta=-5,
            message="repo issue activity is slowing",
            rule_type="warning",
        ),
        ScoreRule(
            minimum=15,
            maximum=30,
            score_delta=-30,
            message="repo issue activity looks stale",
            rule_type="warning",
        ),
        ScoreRule(
            minimum=31,
            maximum=None,
            score_delta=-40,
            message="repo issue activity is stale",
            rule_type="warning",
        ),
    ],

    "comments": [
        ScoreRule(
            minimum=0,
            maximum=1,
            score_delta=15,
            message="low discussion volume",
            rule_type="reason",
        ),
        ScoreRule(
            minimum=5,
            maximum=None,
            score_delta=-15,
            message="long discussion",
            rule_type="warning",
        ),
    ],


    "special_rules": [
        SpecialRule(
            labels_any={"good first issue", "help wanted"},
            repo_beginner_issue_count_min=3,
            score_delta=10,
            message="welcoming label",
            rule_type="reason",
        ),
    ],
}

junior = {
    "stars": [
        ScoreRule(
            minimum=5,
            maximum=1_000,
            score_delta=15,
            message="small beginner-friendly repo",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=1_001,
            maximum=None,
            score_delta=-5,
            message="repo may be competitive",
            rule_type="warning",
        ),
    ],

    "updated_days": [
        ScoreRule(
            minimum=0,
            maximum=14,
            score_delta=15,
            message="issue updated recently",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=15,
            maximum=None,
            score_delta=-25,
            message="issue may be stale",
            rule_type="warning",
        ),
    ],

    "repo_last_issue_updated_days": [
        ScoreRule(
            minimum=0,
            maximum=14,
            score_delta=25,
            message="repo is actively maintained",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=15,
            maximum=None,
            score_delta=-30,
            message="repo activity is slowing or stale",
            rule_type="warning",
        ),
    ],

    "comments": [
        ScoreRule(
            minimum=0,
            maximum=2,
            score_delta=20,
            message="ideal discussion volume",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=3,
            maximum=10,
            score_delta=5,
            message="manageable discussion volume",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=11,
            maximum=None,
            score_delta=-40,
            message="issue may be too complex for beginners",
            rule_type="warning",
        ),
    ],

    "special_rules": [
        SpecialRule(
            labels_any={
                "good first issue",
                "documentation",
            },
            repo_beginner_issue_count_min=3,
            score_delta=20,
            message="beginner-friendly label",
            rule_type="reason",
        ),

        SpecialRule(
            labels_any={
                "help wanted",
            },
            repo_beginner_issue_count_min=3,
            score_delta=5,
            message="maintainers welcome contributions",
            rule_type="reason",
        ),
    ],
}


intermediate = {
    "stars": [
        ScoreRule(
            minimum=200,
            maximum=20_000,
            score_delta=15,
            message="active repo with manageable scale",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=20_001,
            maximum=None,
            score_delta=-10,
            message="large repo may be competitive",
            rule_type="warning",
        ),
    ],

    "updated_days": [
        ScoreRule(
            minimum=0,
            maximum=21,
            score_delta=15,
            message="issue updated recently",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=22,
            maximum=None,
            score_delta=-20,
            message="issue may be stale",
            rule_type="warning",
        ),
    ],

    "repo_last_issue_updated_days": [
        ScoreRule(
            minimum=0,
            maximum=21,
            score_delta=25,
            message="repo is actively maintained",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=22,
            maximum=None,
            score_delta=-25,
            message="repo activity is slowing",
            rule_type="warning",
        ),
    ],

    "comments": [
        ScoreRule(
            minimum=0,
            maximum=3,
            score_delta=20,
            message="low discussion volume",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=4,
            maximum=10,
            score_delta=5,
            message="moderate discussion volume",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=11,
            maximum=None,
            score_delta=-30,
            message="long discussion may indicate complexity",
            rule_type="warning",
        ),
    ],

    "special_rules": [
        SpecialRule(
            labels_any={
                "good first issue",
                "documentation",
                "enhancement",
            },
            repo_beginner_issue_count_min=3,
            score_delta=10,
            message="general contribution-friendly issue types",
            rule_type="reason",
        ),

        SpecialRule(
            labels_any={
                "help wanted",
                "bug",
            },
            repo_beginner_issue_count_min=3,
            score_delta=20,
            message="maintainers are looking for external help",
            rule_type="reason",
        ),
    ],
}


senior = {
    "stars": [
        ScoreRule(
            minimum=1_000,
            maximum=None,
            score_delta=10,
            message="active large-scale repo",
            rule_type="reason",
        ),
    ],

    "updated_days": [
        ScoreRule(
            minimum=0,
            maximum=30,
            score_delta=15,
            message="issue updated recently",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=31,
            maximum=None,
            score_delta=-10,
            message="issue may be stale",
            rule_type="warning",
        ),
    ],

    "repo_last_issue_updated_days": [
        ScoreRule(
            minimum=0,
            maximum=60,
            score_delta=20,
            message="repo has healthy activity",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=61,
            maximum=None,
            score_delta=-20,
            message="repo activity is stale",
            rule_type="warning",
        ),
    ],

    "comments": [
        ScoreRule(
            minimum=0,
            maximum=10,
            score_delta=10,
            message="discussion volume is acceptable",
            rule_type="reason",
        ),

        ScoreRule(
            minimum=11,
            maximum=None,
            score_delta=-10,
            message="long discussion may indicate complexity",
            rule_type="warning",
        ),
    ],

    "special_rules": [
        SpecialRule(
            labels_any={
                "help wanted",
                "bug",
                "enhancement",
            },
            repo_beginner_issue_count_min=3,
            score_delta=20,
            message="technical issue suitable for experienced contributors",
            rule_type="reason",
        ),
    ],
}