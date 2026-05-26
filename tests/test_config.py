import unittest

from oss_issue_scout.config import (
    BACKFILL_DELAY_SECONDS,
    BACKFILL_PER_PAGE,
    BACKFILL_REPO_LIMIT,
    DEBUG_ENV,
    GITHUB_TOKEN_ENV,
    REQUEST_RETRY_ATTEMPTS,
    REQUEST_TIMEOUT_SECONDS,
)


class ConfigTests(unittest.TestCase):
    def test_environment_variable_names_are_configured(self) -> None:
        self.assertEqual(GITHUB_TOKEN_ENV, "GITHUB_TOKEN")
        self.assertEqual(DEBUG_ENV, "OSS_ISSUE_SCOUT_DEBUG")

    def test_api_runtime_defaults_are_configured(self) -> None:
        self.assertEqual(REQUEST_TIMEOUT_SECONDS, 20)
        self.assertEqual(REQUEST_RETRY_ATTEMPTS, 5)
        self.assertEqual(BACKFILL_PER_PAGE, 25)
        self.assertEqual(BACKFILL_REPO_LIMIT, 20)
        self.assertEqual(BACKFILL_DELAY_SECONDS, 1)


if __name__ == "__main__":
    unittest.main()
