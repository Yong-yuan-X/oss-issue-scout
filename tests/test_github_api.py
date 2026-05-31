import contextlib
import io
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from oss_issue_scout.github_api import (
    GitHubAPIError,
    Issue,
    MAX_GRAPHQL_PAGE_SIZE,
    MAX_GRAPHQL_SEARCH_PAGES,
    MAX_REST_SEARCH_PAGES,
    MIN_REPO_OPEN_ISSUES,
    _build_issue_query,
    _request_graphql,
    _request_json,
    backfill_issue_candidates,
    search_issue_candidates,
    search_issues,
)


class SearchIssuesTests(unittest.TestCase):
    def test_query_requires_unassigned_issues(self) -> None:
        query = _build_issue_query(
            language=None,
            stars_min=None,
            label=None,
            updated_days=None,
        )

        self.assertIn("no:assignee", query)

    def test_graphql_query_sorts_by_recently_updated(self) -> None:
        query = _build_issue_query(
            language="python",
            stars_min=100,
            label=None,
            updated_days=None,
            sort_updated_desc=True,
        )

        self.assertIn("sort:updated-desc", query)

    def test_query_quotes_search_values_with_special_characters(self) -> None:
        query = _build_issue_query(
            language="C++",
            stars_min=100,
            label="good first issue",
            updated_days=None,
        )

        self.assertIn('language:"C++"', query)
        self.assertIn('label:"good first issue"', query)

    def test_searches_github_and_maps_results(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_graphql),
        ):
            issues = search_issues(language="python", label="good first issue", updated_days=10, limit=5)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].repo, "example/project")
        self.assertEqual(issues[0].stars, 12_000)
        self.assertEqual(issues[0].labels, ("good first issue",))
        self.assertEqual(issues[0].repo_beginner_issue_count, 3)
        self.assertEqual(issues[0].repo_open_issue_count, MIN_REPO_OPEN_ISSUES)
        self.assertFalse(issues[0].has_open_pr)

    def test_search_without_token_uses_rest_api(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value=None),
            patch("oss_issue_scout.github_api._request_json", side_effect=_fake_rest),
            patch("oss_issue_scout.github_api._request_graphql") as request_graphql,
        ):
            issues = search_issues(language="python", limit=5)

        self.assertEqual([issue.repo for issue in issues], ["example/project"])
        request_graphql.assert_not_called()

    def test_rest_search_uses_built_issue_query(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value=None),
            patch("oss_issue_scout.github_api._request_json", side_effect=_fake_rest) as request_json,
        ):
            search_issue_candidates(
                query="timeout handling",
                language="C++",
                stars_min=500,
                label="good first issue",
                updated_days=10,
                limit=5,
            )

        params = request_json.call_args_list[0].args[1]
        self.assertIn('"timeout handling"', params["q"])
        self.assertIn('language:"C++"', params["q"])
        self.assertIn("stars:>=500", params["q"])
        self.assertIn('label:"good first issue"', params["q"])
        self.assertIn("no:assignee", params["q"])

    def test_graphql_search_uses_conservative_page_size(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_graphql) as request_graphql,
        ):
            search_issues(language="python", limit=20)

        self.assertEqual(
            request_graphql.call_args.args[1]["first"],
            MAX_GRAPHQL_PAGE_SIZE,
        )

    def test_graphql_resource_limit_falls_back_to_rest_api(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch(
                "oss_issue_scout.github_api._request_graphql",
                side_effect=GitHubAPIError("Resource limits for this query exceeded."),
            ) as request_graphql,
            patch("oss_issue_scout.github_api._request_json", side_effect=_fake_rest),
        ):
            issues = search_issues(language="python", limit=5)

        self.assertEqual([issue.repo for issue in issues], ["example/project"])
        request_graphql.assert_called_once()

    def test_backfills_repo_issues_with_rest_search(self) -> None:
        with patch("oss_issue_scout.github_api._request_json", side_effect=_fake_rest) as request_json:
            issues = backfill_issue_candidates(
                repo="example/project",
                known_issues=[
                    _issue(
                        repo="example/project",
                        title="Known",
                    )
                ],
                language="python",
                per_page=25,
                page=1,
            )

        search_call = request_json.call_args_list[0]
        self.assertEqual(search_call.args[0], "/search/issues")
        self.assertIn("repo:example/project", search_call.args[1]["q"])
        self.assertIn("language:python", search_call.args[1]["q"])
        self.assertEqual(search_call.args[1]["per_page"], "25")
        self.assertEqual([issue.repo for issue in issues], ["example/project"])
        self.assertEqual(request_json.call_count, 1)

    def test_filters_by_min_stars_from_graphql_repo_data(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_graphql),
        ):
            issues = search_issues(stars_min=50_000, limit=5)

        self.assertEqual(issues, [])

    def test_skips_repos_with_fewer_than_default_min_stars(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_low_star_graphql),
        ):
            issues = search_issues(limit=5)

        self.assertEqual(issues, [])

    def test_filters_by_repo_issue_activity_from_graphql_repo_data(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_stale_repo_activity),
        ):
            issues = search_issues(repo_updated_days=7, limit=5)

        self.assertEqual(issues, [])

    def test_skips_graphql_repos_with_two_or_fewer_open_issues(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_low_open_issue_count_graphql),
        ):
            issues = search_issues(limit=5)

        self.assertEqual(issues, [])

    def test_skips_rest_repos_with_two_or_fewer_open_issues(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value=None),
            patch("oss_issue_scout.github_api._request_json", side_effect=_fake_low_open_issue_count_rest),
        ):
            issues = search_issues(language="python", limit=5)

        self.assertEqual(issues, [])

    def test_fetches_more_pages_when_candidates_are_filtered(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_paginated_graphql),
        ):
            issues = search_issues(language="python", limit=2)

        self.assertEqual([issue.repo for issue in issues], ["example/one", "example/two"])

    def test_fetches_next_page_when_short_page_does_not_fill_limit(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_short_page_graphql),
        ):
            issues = search_issues(language="python", limit=2)

        self.assertEqual([issue.repo for issue in issues], ["example/one", "example/two"])

    def test_graphql_page_cap_does_not_mark_search_exhausted(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_graphql_with_more_pages),
        ):
            result = search_issue_candidates(language="python", limit=200)

        self.assertFalse(result.exhausted)
        self.assertTrue(result.page_limit_reached)

    def test_graphql_extends_page_cap_when_fewer_than_three_results(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch(
                "oss_issue_scout.github_api._request_graphql",
                side_effect=_fake_sparse_graphql_with_more_pages,
            ) as request_graphql,
        ):
            result = search_issue_candidates(language="python", limit=3)

        self.assertEqual([issue.repo for issue in result.issues], ["example/one", "example/two"])
        self.assertEqual(request_graphql.call_count, MAX_GRAPHQL_SEARCH_PAGES + 1)

    def test_graphql_limit_mid_page_does_not_mark_search_exhausted(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api._request_graphql", side_effect=_fake_graphql_single_page_with_extra_nodes),
        ):
            result = search_issue_candidates(language="python", limit=2)

        self.assertEqual(len(result.issues), 2)
        self.assertFalse(result.exhausted)

    def test_rest_page_cap_does_not_mark_search_exhausted(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value=None),
            patch("oss_issue_scout.github_api._request_json", side_effect=_fake_rest_with_more_pages),
        ):
            result = search_issue_candidates(language="python", limit=200)

        self.assertFalse(result.exhausted)
        self.assertTrue(result.page_limit_reached)

    def test_rest_extends_page_cap_when_fewer_than_three_results(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value=None),
            patch(
                "oss_issue_scout.github_api._request_json",
                side_effect=_fake_sparse_rest_with_more_pages,
            ) as request_json,
        ):
            result = search_issue_candidates(language="python", limit=3)

        search_pages = [
            int(call.args[1]["page"])
            for call in request_json.call_args_list
            if call.args[0] == "/search/issues" and "page" in call.args[1]
        ]
        self.assertEqual(
            [issue.repo for issue in result.issues],
            ["example/one", "example/two", "example/three"],
        )
        self.assertEqual(search_pages, list(range(1, MAX_REST_SEARCH_PAGES + 2)))

    def test_non_positive_limit_returns_no_results_without_api_call(self) -> None:
        with (
            patch("oss_issue_scout.github_api._request_graphql") as request_graphql,
            patch("oss_issue_scout.github_api._request_json") as request_json,
        ):
            issues = search_issues(language="python", limit=0)

        self.assertEqual(issues, [])
        request_graphql.assert_not_called()
        request_json.assert_not_called()

    def test_graphql_requires_github_token(self) -> None:
        with patch("oss_issue_scout.github_api._get_token", return_value=None):
            with self.assertRaises(GitHubAPIError) as raised:
                _request_graphql("query { viewer { login } }", {})

        self.assertIn("GITHUB_TOKEN", str(raised.exception))

    def test_graphql_timeout_raises_github_api_error(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch("oss_issue_scout.github_api.urlopen", side_effect=TimeoutError),
        ):
            with self.assertRaises(GitHubAPIError) as raised:
                _request_graphql("query { viewer { login } }", {})

        self.assertIn("timed out", str(raised.exception))

    def test_graphql_retries_transient_bad_gateway(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch(
                "oss_issue_scout.github_api.urlopen",
                side_effect=[
                    _http_error(502),
                    _json_response({"data": {"viewer": {"login": "octocat"}}}),
                ],
            ) as urlopen,
            patch("oss_issue_scout.github_api.sleep"),
        ):
            data = _request_graphql("query { viewer { login } }", {})

        self.assertEqual(data, {"viewer": {"login": "octocat"}})
        self.assertEqual(urlopen.call_count, 2)

    def test_graphql_retries_transient_errors_up_to_attempt_limit(self) -> None:
        with (
            patch("oss_issue_scout.github_api._get_token", return_value="token"),
            patch(
                "oss_issue_scout.github_api.urlopen",
                side_effect=[
                    _http_error(502),
                    _http_error(502),
                    _http_error(502),
                    _http_error(502),
                    _http_error(502),
                ],
            ) as urlopen,
            patch("oss_issue_scout.github_api.sleep"),
        ):
            with self.assertRaises(GitHubAPIError):
                _request_graphql("query { viewer { login } }", {})

        self.assertEqual(urlopen.call_count, 5)

    def test_rest_timeout_raises_github_api_error(self) -> None:
        with patch("oss_issue_scout.github_api.urlopen", side_effect=TimeoutError):
            with self.assertRaises(GitHubAPIError) as raised:
                _request_json("/search/issues", {"q": "is:issue"})

        self.assertIn("timed out", str(raised.exception))

    def test_rest_retries_transient_bad_gateway(self) -> None:
        with (
            patch(
                "oss_issue_scout.github_api.urlopen",
                side_effect=[
                    _http_error(502),
                    _json_response({"items": []}),
                ],
            ) as urlopen,
            patch("oss_issue_scout.github_api.sleep"),
        ):
            data = _request_json("/search/issues", {"q": "is:issue"})

        self.assertEqual(data, {"items": []})
        self.assertEqual(urlopen.call_count, 2)

    def test_rest_logs_rate_limit_headers_in_debug_mode(self) -> None:
        stderr = io.StringIO()

        with (
            patch("oss_issue_scout.github_api.DEBUG_ENABLED", True),
            patch(
                "oss_issue_scout.github_api.urlopen",
                side_effect=_http_error(
                    403,
                    body=b"secondary rate limit",
                    headers={
                        "x-ratelimit-resource": "search",
                        "x-ratelimit-limit": "30",
                        "x-ratelimit-remaining": "0",
                        "x-ratelimit-reset": "1770000000",
                        "retry-after": "60",
                    },
                ),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            with self.assertRaises(GitHubAPIError):
                _request_json("/search/issues", {"q": "is:issue"})

        output = stderr.getvalue()
        self.assertIn("rate limit headers", output)
        self.assertIn("resource=search", output)
        self.assertIn("remaining=0", output)
        self.assertIn("retry-after=60", output)


def _fake_graphql(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(
                repo="example/project",
                stars=12_000,
                title="Improve docs",
                labels=("good first issue",),
                beginner_count=3,
            )
        ],
        has_next_page=False,
    )


def _fake_rest(path: str, params: dict[str, str] | None = None) -> dict:
    if path == "/search/issues" and params and params.get("per_page") == "1":
        if " is:open" in params.get("q", ""):
            return {"total_count": MIN_REPO_OPEN_ISSUES, "items": []}
        if "label:" in params.get("q", ""):
            return {"total_count": 3, "items": []}
        return {"items": [{"updated_at": "2026-05-20T00:00:00Z"}]}

    if path == "/search/issues" and params and params.get("page") not in (None, "1"):
        return {"items": []}

    if path == "/search/issues":
        return {
            "items": [
                {
                    "title": "Improve docs",
                    "html_url": "https://github.com/example/project/issues/1",
                    "repository_url": "https://api.github.com/repos/example/project",
                    "repository": {
                        "full_name": "example/project",
                        "language": "Python",
                        "stargazers_count": 12_000,
                    },
                    "labels": [{"name": "good first issue"}],
                    "updated_at": "2026-05-19T00:00:00Z",
                    "comments": 1,
                }
            ]
        }

    raise AssertionError(f"Unexpected API request: {path} {params}")


def _fake_stale_repo_activity(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(
                repo="example/project",
                stars=12_000,
                title="Improve docs",
                repo_last_issue_updated_at="2026-04-01T00:00:00Z",
            )
        ],
        has_next_page=False,
    )


def _fake_low_star_graphql(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(
                repo="example/project",
                stars=99,
                title="Improve docs",
            )
        ],
        has_next_page=False,
    )


def _fake_low_open_issue_count_graphql(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(
                repo="example/project",
                stars=12_000,
                title="Improve docs",
                open_issue_count=2,
            )
        ],
        has_next_page=False,
    )


def _fake_paginated_graphql(query: str, variables: dict) -> dict:
    if variables.get("after") is None:
        return _graphql_response(
            nodes=[
                _graphql_issue_node(
                    repo=f"example/filtered-{index}",
                    stars=99,
                    title=f"Filtered {index}",
                )
                for index in range(30)
            ],
            has_next_page=True,
            end_cursor="page-2",
        )

    return _graphql_response(
        nodes=[
            _graphql_issue_node(repo="example/one", stars=12_000, title="One"),
            _graphql_issue_node(repo="example/two", stars=12_000, title="Two"),
        ],
        has_next_page=False,
    )


def _fake_short_page_graphql(query: str, variables: dict) -> dict:
    if variables.get("after") is None:
        return _graphql_response(
            nodes=[
                _graphql_issue_node(
                    repo="example/filtered",
                    stars=99,
                    title="Filtered",
                )
            ],
            has_next_page=True,
            end_cursor="page-2",
        )

    return _graphql_response(
        nodes=[
            _graphql_issue_node(repo="example/one", stars=12_000, title="One"),
            _graphql_issue_node(repo="example/two", stars=12_000, title="Two"),
        ],
        has_next_page=False,
    )


def _fake_graphql_with_more_pages(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(
                repo=f"example/page-{variables.get('after') or 'first'}",
                stars=12_000,
                title="One",
            )
        ],
        has_next_page=True,
        end_cursor=f"page-{variables.get('after') or 1}",
    )


def _fake_sparse_graphql_with_more_pages(query: str, variables: dict) -> dict:
    page = _graphql_page_number(variables.get("after"))
    if page == 1:
        nodes = [_graphql_issue_node(repo="example/one", stars=12_000, title="One")]
    elif page <= MAX_GRAPHQL_SEARCH_PAGES:
        nodes = [
            _graphql_issue_node(
                repo=f"example/filtered-{page}",
                stars=99,
                title=f"Filtered {page}",
            )
        ]
    else:
        nodes = [_graphql_issue_node(repo="example/two", stars=12_000, title="Two")]

    return _graphql_response(
        nodes=nodes,
        has_next_page=page <= MAX_GRAPHQL_SEARCH_PAGES,
        end_cursor=f"page-{page}",
    )


def _fake_graphql_single_page_with_extra_nodes(query: str, variables: dict) -> dict:
    return _graphql_response(
        nodes=[
            _graphql_issue_node(repo="example/one", stars=12_000, title="One"),
            _graphql_issue_node(repo="example/two", stars=12_000, title="Two"),
            _graphql_issue_node(repo="example/three", stars=12_000, title="Three"),
        ],
        has_next_page=False,
    )


def _fake_rest_with_more_pages(path: str, params: dict[str, str] | None = None) -> dict:
    if path == "/search/issues" and params and params.get("per_page") == "1":
        if " is:open" in params.get("q", ""):
            return {"total_count": MIN_REPO_OPEN_ISSUES, "items": []}
        if "label:" in params.get("q", ""):
            return {"total_count": 3, "items": []}
        return {"items": [{"updated_at": "2026-05-20T00:00:00Z"}]}

    if path == "/search/issues":
        page = int((params or {}).get("page") or "1")
        return {
            "items": [
                {
                    "title": f"Page {page}",
                    "html_url": f"https://github.com/example/page-{page}/issues/1",
                    "repository_url": f"https://api.github.com/repos/example/page-{page}",
                    "repository": {
                        "full_name": f"example/page-{page}",
                        "language": "Python",
                        "stargazers_count": 12_000,
                    },
                    "labels": [{"name": "good first issue"}],
                    "updated_at": "2026-05-19T00:00:00Z",
                    "comments": 1,
                }
            ]
        }

    raise AssertionError(f"Unexpected API request: {path} {params}")


def _fake_sparse_rest_with_more_pages(path: str, params: dict[str, str] | None = None) -> dict:
    if path == "/search/issues" and params and params.get("per_page") == "1":
        if " is:open" in params.get("q", ""):
            return {"total_count": MIN_REPO_OPEN_ISSUES, "items": []}
        if "label:" in params.get("q", ""):
            return {"total_count": 3, "items": []}
        return {"items": [{"updated_at": "2026-05-20T00:00:00Z"}]}

    if path == "/search/issues":
        page = int((params or {}).get("page") or "1")
        if page == 1:
            repos = ["example/one"]
        elif page <= MAX_REST_SEARCH_PAGES:
            repos = [f"example/filtered-{page}"]
        else:
            repos = ["example/two", "example/three"]
        return {"items": [_rest_issue_item(repo=repo, page=page) for repo in repos]}

    raise AssertionError(f"Unexpected API request: {path} {params}")


def _fake_low_open_issue_count_rest(path: str, params: dict[str, str] | None = None) -> dict:
    if path == "/search/issues" and params and params.get("per_page") == "1":
        if " is:open" in params.get("q", ""):
            return {"total_count": 2, "items": []}
        if "label:" in params.get("q", ""):
            return {"total_count": 3, "items": []}
        return {"items": [{"updated_at": "2026-05-20T00:00:00Z"}]}

    if path == "/search/issues":
        return {"items": [_rest_issue_item(repo="example/project", page=1)]}

    raise AssertionError(f"Unexpected API request: {path} {params}")


def _rest_issue_item(repo: str, page: int) -> dict:
    stars = 99 if "filtered" in repo else 12_000
    return {
        "title": f"Page {page}",
        "html_url": f"https://github.com/{repo}/issues/1",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "repository": {
            "full_name": repo,
            "language": "Python",
            "stargazers_count": stars,
        },
        "labels": [{"name": "good first issue"}],
        "updated_at": "2026-05-19T00:00:00Z",
        "comments": 1,
    }


def _issue(
    *,
    repo: str,
    title: str,
) -> Issue:
    return Issue(
        repo=repo,
        title=title,
        url=f"https://github.com/{repo}/issues/{title.replace(' ', '-')}",
        language="Python",
        stars=12_000,
        labels=("good first issue",),
        updated_days=1,
        repo_last_issue_updated_days=1,
        repo_beginner_issue_count=3,
        comments=1,
        has_open_pr=False,
        repo_open_issue_count=MIN_REPO_OPEN_ISSUES,
    )


def _graphql_page_number(after: str | None) -> int:
    if after is None:
        return 1
    return int(after.removeprefix("page-")) + 1


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")


def _json_response(payload: dict) -> _JsonResponse:
    return _JsonResponse(payload)


def _http_error(
    code: int,
    *,
    body: bytes = b"Bad Gateway",
    headers: dict[str, str] | None = None,
) -> HTTPError:
    return HTTPError(
        url="https://api.github.com/graphql",
        code=code,
        msg="Bad Gateway",
        hdrs=headers,
        fp=io.BytesIO(body),
    )


def _graphql_response(
    *,
    nodes: list[dict],
    has_next_page: bool,
    end_cursor: str | None = None,
) -> dict:
    return {
        "search": {
            "pageInfo": {
                "hasNextPage": has_next_page,
                "endCursor": end_cursor,
            },
            "nodes": nodes,
        }
    }


def _graphql_issue_node(
    *,
    repo: str,
    stars: int,
    title: str,
    labels: tuple[str, ...] = ("good first issue",),
    beginner_count: int = 0,
    open_issue_count: int = MIN_REPO_OPEN_ISSUES,
    repo_last_issue_updated_at: str = "2026-05-20T00:00:00Z",
) -> dict:
    return {
        "title": title,
        "url": f"https://github.com/{repo}/issues/1",
        "number": 1,
        "updatedAt": "2026-05-19T00:00:00Z",
        "comments": {"totalCount": 1},
        "labels": {"nodes": [{"name": label} for label in labels]},
        "repository": {
            "nameWithOwner": repo,
            "stargazerCount": stars,
            "primaryLanguage": {"name": "Python"},
            "issues": {
                "nodes": [
                    {
                        "updatedAt": repo_last_issue_updated_at,
                    }
                ]
            },
            "openIssues": {"totalCount": open_issue_count},
            "goodFirstIssues": {"totalCount": beginner_count},
            "helpWantedIssues": {"totalCount": 0},
        },
    }


if __name__ == "__main__":
    unittest.main()
