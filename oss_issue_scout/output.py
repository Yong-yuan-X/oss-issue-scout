"""Output renderers for scored issues."""

from __future__ import annotations

import json
from typing import Any

from .scoring import ScoredIssue


def render_results(results: list[ScoredIssue], output_format: str) -> str:
    if output_format == "table":
        return render_table(results)
    if output_format == "markdown":
        return render_markdown(results)
    if output_format == "json":
        return render_json(results)
    raise ValueError(f"Unsupported output format: {output_format}")


def render_table(results: list[ScoredIssue]) -> str:
    rows = [
        (
            str(result.score),
            result.issue.repo,
            result.issue.title,
            result.issue.url,
            _join(result.reasons),
            _join(result.warnings),
        )
        for result in results
    ]
    headers = ("score", "repo", "title", "url", "reasons", "warnings")
    return _plain_table(headers, rows)


def render_markdown(results: list[ScoredIssue]) -> str:
    headers = ("Score", "Repo", "Issue", "URL", "Reasons", "Warnings")
    rows = [
        (
            str(result.score),
            result.issue.repo,
            result.issue.title,
            result.issue.url,
            _join(result.reasons),
            _join(result.warnings),
        )
        for result in results
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_markdown(cell) for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def render_json(results: list[ScoredIssue]) -> str:
    payload: list[dict[str, Any]] = [
        {
            "score": result.score,
            "repo": result.issue.repo,
            "title": result.issue.title,
            "url": result.issue.url,
            "language": result.issue.language,
            "stars": result.issue.stars,
            "labels": list(result.issue.labels),
            "reasons": list(result.reasons),
            "warnings": list(result.warnings),
        }
        for result in results
    ]
    return json.dumps(payload, indent=2)


def _plain_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [
        max(len(header), *(len(row[index]) for row in rows)) if rows else len(header)
        for index, header in enumerate(headers)
    ]
    header_line = "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    divider = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
        for row in rows
    ]
    return "\n".join([header_line, divider, *body])


def _join(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "-"


def _escape_markdown(value: str) -> str:
    return value.replace("|", "\\|")
