from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from setup_wizard import (
    cloud_target_allowed,
    codespace_host,
    enable_workflow_writes,
    has_notification_channel,
    incomplete_secret_groups,
    suggested_repository,
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

    @patch("setup_wizard.gh", return_value=SimpleNamespace(returncode=0))
    def test_enables_only_the_workflow_content_permission(self, mocked_gh) -> None:
        self.assertTrue(enable_workflow_writes("reader/repo"))
        self.assertIn("repos/reader/repo/actions/permissions/workflow", mocked_gh.call_args.args)
        self.assertIn("default_workflow_permissions=write", mocked_gh.call_args.args)

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
