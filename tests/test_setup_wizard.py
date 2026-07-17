from __future__ import annotations

import unittest
from unittest.mock import patch

from setup_wizard import cloud_target_allowed, codespace_host, incomplete_secret_groups, suggested_repository


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


if __name__ == "__main__":
    unittest.main()
