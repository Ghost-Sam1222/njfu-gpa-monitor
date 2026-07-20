from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from setup_wizard import (
    cloud_target_allowed,
    codespace_host,
    has_notification_channel,
    incomplete_secret_groups,
    login_configuration_error,
    login_digest,
    normalize_completion_variables,
    restrict_default_workflow_permissions,
    suggested_repository,
    telegram_chat_ids,
    wait_for_workflow,
)


class SetupWizardTests(unittest.TestCase):
    def test_codespace_suggests_its_current_repository(self) -> None:
        environment = {
            "CODESPACES": "true",
            "GITHUB_REPOSITORY": "example/njfu-gpa-monitor",
            "GITHUB_USER": "reader",
        }
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(suggested_repository(), "example/njfu-gpa-monitor")

    def test_codespace_rejects_a_different_target_repository(self) -> None:
        environment = {
            "CODESPACES": "true",
            "GITHUB_REPOSITORY": "reader/njfu-gpa-monitor",
        }
        with patch.dict("os.environ", environment, clear=True):
            self.assertTrue(cloud_target_allowed("reader/njfu-gpa-monitor"))
            self.assertFalse(cloud_target_allowed("someone-else/njfu-gpa-monitor"))

    def test_codespace_forwarded_host_is_exact(self) -> None:
        environment = {
            "CODESPACE_NAME": "quiet-space-123",
            "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
        }
        with patch.dict("os.environ", environment, clear=True):
            self.assertEqual(codespace_host(8765), "quiet-space-123-8765.app.github.dev")

    def test_rejects_incomplete_channel_groups(self) -> None:
        errors = incomplete_secret_groups(
            {"TELEGRAM_BOT_TOKEN", "EMAIL_FROM", "NTFY_TOKEN", "GENERIC_WEBHOOK_TEMPLATE"}
        )
        self.assertEqual(len(errors), 4)

    def test_accepts_complete_channel_groups(self) -> None:
        errors = incomplete_secret_groups(
            {
                "TELEGRAM_BOT_TOKEN",
                "TELEGRAM_CHAT_ID",
                "EMAIL_FROM",
                "EMAIL_PASSWORD",
                "EMAIL_TO",
                "NTFY_TOKEN",
                "NTFY_TOPIC",
                "GENERIC_WEBHOOK_TEMPLATE",
                "GENERIC_WEBHOOK_URL",
            }
        )
        self.assertEqual(errors, ())

    def test_requires_at_least_one_complete_notification_channel(self) -> None:
        self.assertFalse(has_notification_channel({"BARK_SERVER", "EMAIL_FROM"}))
        self.assertTrue(has_notification_channel({"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"}))

    def test_migrates_legacy_zero_count_when_course_names_exist(self) -> None:
        variables = {
            "COMPLETION_MODE": "count",
            "EXPECTED_GRADE_COUNT": "0",
            "EXPECTED_COURSE_NAMES": "课程A,课程B",
        }
        self.assertEqual(normalize_completion_variables(variables), ("names", "0", "课程A,课程B"))
        self.assertEqual(variables["COMPLETION_MODE"], "names")

    @patch("setup_wizard.gh", return_value=SimpleNamespace(returncode=0))
    def test_restricts_default_workflow_permissions(self, mocked_gh) -> None:
        self.assertTrue(restrict_default_workflow_permissions("reader/repo"))
        self.assertIn("repos/reader/repo/actions/permissions/workflow", mocked_gh.call_args.args)
        self.assertIn("default_workflow_permissions=read", mocked_gh.call_args.args)

    def test_new_login_must_be_complete_and_verified(self) -> None:
        submitted = {"JW_USERNAME": "student", "JW_PASSWORD": "password", "JW_COOKIE": ""}
        self.assertTrue(login_configuration_error(set(), submitted, "2026-2027-1", ""))
        verified = login_digest("student", "password", "", "2026-2027-1")
        self.assertEqual(
            login_configuration_error(set(), submitted, "2026-2027-1", verified),
            "",
        )
        self.assertTrue(login_configuration_error(set(), submitted, "2026-2027-2", verified))

    def test_existing_login_can_be_kept_without_reentering_it(self) -> None:
        existing = {"JW_USERNAME", "JW_PASSWORD"}
        self.assertEqual(
            login_configuration_error(existing, {}, "2026-2027-1", "", "2026-2027-1"),
            "",
        )
        self.assertTrue(
            login_configuration_error(existing, {}, "2026-2027-2", "", "2026-2027-1")
        )

    @patch("setup_wizard.urlopen")
    def test_discovers_telegram_chat_without_exposing_token_to_browser(self, mocked_urlopen) -> None:
        response = MagicMock()
        response.read.return_value = b'{"ok":true,"result":[{"message":{"chat":{"id":42,"first_name":"Reader"}}}]}'
        mocked_urlopen.return_value.__enter__.return_value = response
        self.assertEqual(
            telegram_chat_ids("12345:abcdefghijklmnopqrstuvwxyz"),
            [{"id": "42", "label": "Reader"}],
        )

    @patch("setup_wizard.time.sleep")
    @patch("setup_wizard.latest_workflow_run")
    def test_waits_for_a_new_completed_workflow(self, latest, _sleep) -> None:
        latest.side_effect = [
            {"databaseId": 12, "status": "queued"},
            {"databaseId": 12, "status": "completed", "conclusion": "success"},
        ]
        result = wait_for_workflow("reader/repo", "test.yml", previous_id=11, attempts=2, delay=0)
        self.assertEqual(result["conclusion"], "success")


if __name__ == "__main__":
    unittest.main()
