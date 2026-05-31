import unittest
from pathlib import Path
from unittest.mock import patch

from web.api import app

WEB_INDEX = Path(__file__).parents[1] / "web" / "index.html"


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    @patch("web.api._search_recommended", return_value=[])
    def test_search_passes_repo_updated_days_to_search(self, search) -> None:
        response = self.client.get("/api/search?updated_days=3&repo_updated_days=7")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(search.call_args.args[0].updated_days, 3)
        self.assertEqual(search.call_args.args[0].repo_updated_days, 7)

    @patch("web.api._search_recommended", return_value=[])
    def test_search_rejects_non_integer_repo_updated_days(self, search) -> None:
        response = self.client.get("/api/search?repo_updated_days=recent")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.get_json(),
            {"error": "Invalid repo_updated_days: must be an integer"},
        )
        search.assert_not_called()


class WebUiTests(unittest.TestCase):
    def test_search_form_wires_local_repo_activity_filter(self) -> None:
        html = WEB_INDEX.read_text(encoding="utf-8")

        self.assertIn('data-i18n="search-repo-days"', html)
        self.assertIn('id="search-repo-updated-days"', html)
        self.assertIn("const repoUpdatedDays = document.getElementById('search-repo-updated-days').value;", html)
        self.assertIn("url.searchParams.set('repo_updated_days', options.repoUpdatedDays || '');", html)


if __name__ == "__main__":
    unittest.main()
