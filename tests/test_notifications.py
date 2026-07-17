from __future__ import annotations

import unittest
from unittest.mock import patch

from notifications import NotificationError, NotificationSettings, _replace_placeholders, _request


class NotificationTests(unittest.TestCase):
    def test_detects_only_complete_channels(self) -> None:
        settings = NotificationSettings(
            bark_device_key="key",
            telegram_bot_token="token-without-chat-id",
            ntfy_topic="private-topic",
        )
        self.assertEqual(settings.realtime_channels(), ("bark", "ntfy"))

    def test_generic_webhook_template_replacement_is_recursive(self) -> None:
        template = {"message": {"title": "{title}", "lines": ["{content}"]}}
        self.assertEqual(
            _replace_placeholders(template, "新成绩", "课程A：90"),
            {"message": {"title": "新成绩", "lines": ["课程A：90"]}},
        )

    def test_reports_incomplete_paired_configuration(self) -> None:
        settings = NotificationSettings(
            telegram_bot_token="token-only",
            email_from="sender@example.com",
            generic_webhook_template='{"content":"{content}"}',
        )
        errors = settings.configuration_errors()
        self.assertEqual(len(errors), 3)

    def test_timeout_is_sanitized_as_notification_error(self) -> None:
        with patch("notifications.urlopen", side_effect=TimeoutError("secret URL details")):
            with self.assertRaisesRegex(NotificationError, "TimeoutError"):
                _request("https://example.com/private-token", payload={"message": "private"})


if __name__ == "__main__":
    unittest.main()
