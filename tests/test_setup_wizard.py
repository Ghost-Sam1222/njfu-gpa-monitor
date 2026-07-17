from __future__ import annotations

import unittest

from setup_wizard import incomplete_secret_groups


class SetupWizardTests(unittest.TestCase):
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
