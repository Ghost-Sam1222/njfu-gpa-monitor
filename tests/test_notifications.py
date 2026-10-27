from __future__ import annotations

import unittest
import io
from contextlib import redirect_stderr, redirect_stdout
from http.client import BadStatusLine, HTTPSConnection
from smtplib import SMTPAuthenticationError
from unittest.mock import patch

from notifications import NotificationError, NotificationSettings, _replace_placeholders, _request
from send_test_notifications import main as test_notifications_main


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

    def test_rejects_plain_http_notification_endpoints(self) -> None:
        settings = NotificationSettings(generic_webhook_url="http://example.com/hook")
        self.assertEqual(settings.configuration_errors(), ("GENERIC_WEBHOOK_URL must use HTTPS",))

    def test_malformed_private_notification_urls_do_not_escape_to_action_logs(self) -> None:
        marker = "SYNTHETIC_PRIVATE_ENDPOINT"
        endpoint = f"https://example.invalid/{marker}?copied=two words"

        def validate_without_connecting(request, **kwargs):
            # Use the real HTTP path validator without opening a socket.
            HTTPSConnection("example.invalid").putrequest("POST", request.selector)
            self.fail("The malformed path should have been rejected")

        for environment, target in (
            ({"GENERIC_WEBHOOK_URL": endpoint}, "notifications.urlopen"),
            ({"BARK_SERVER": endpoint, "BARK_DEVICE_KEY": "SYNTHETIC_DEVICE_KEY"}, "bark_notify.urlopen"),
        ):
            with self.subTest(channel=target):
                output = io.StringIO()
                with patch.dict("os.environ", environment, clear=True), patch(
                    target, side_effect=validate_without_connecting,
                ), redirect_stdout(output), redirect_stderr(output):
                    self.assertEqual(test_notifications_main(), 1)
                self.assertIn("InvalidURL", output.getvalue())
                self.assertNotIn(marker, output.getvalue())
                self.assertNotIn("SYNTHETIC_DEVICE_KEY", output.getvalue())

    def test_invalid_http_response_content_is_not_printed(self) -> None:
        marker = "SYNTHETIC_PRIVATE_RESPONSE"
        for environment, target in (
            ({"GENERIC_WEBHOOK_URL": "https://example.invalid/hook"}, "notifications.urlopen"),
            ({"BARK_DEVICE_KEY": "SYNTHETIC_DEVICE_KEY"}, "bark_notify.urlopen"),
        ):
            with self.subTest(channel=target):
                output = io.StringIO()
                with patch.dict("os.environ", environment, clear=True), patch(
                    target, side_effect=BadStatusLine(marker),
                ), redirect_stdout(output), redirect_stderr(output):
                    self.assertEqual(test_notifications_main(), 1)
                self.assertIn("BadStatusLine", output.getvalue())
                self.assertNotIn(marker, output.getvalue())

    def test_smtp_failure_does_not_print_credentials_or_remote_response(self) -> None:
        environment = {
            "EMAIL_FROM": "sender@example.invalid", "EMAIL_TO": "reader@example.invalid",
            "EMAIL_PASSWORD": "SYNTHETIC_SMTP_PASSWORD", "EMAIL_SMTP_SERVER": "smtp.example.invalid",
            "EMAIL_SMTP_PORT": "465",
        }
        output = io.StringIO()
        with patch.dict("os.environ", environment, clear=True), patch(
            "notifications.smtplib.SMTP_SSL",
            side_effect=SMTPAuthenticationError(535, b"SYNTHETIC_PRIVATE_RESPONSE"),
        ), redirect_stdout(output), redirect_stderr(output):
            self.assertEqual(test_notifications_main(), 1)
        self.assertIn("SMTPAuthenticationError", output.getvalue())
        for marker in (*environment.values(), "SYNTHETIC_PRIVATE_RESPONSE"):
            self.assertNotIn(marker, output.getvalue())


if __name__ == "__main__":
    unittest.main()
