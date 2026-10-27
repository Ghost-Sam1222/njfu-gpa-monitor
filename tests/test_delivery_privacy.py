from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from check_grades import main
from models import Grade


class DeliveryPrivacyTests(unittest.TestCase):
    def test_authorized_grade_delivery_is_not_copied_to_logs_or_cache(self) -> None:
        private_values = {
            "JW_USERNAME": "SYNTHETIC_STUDENT_123456789",
            "JW_PASSWORD": "SYNTHETIC_PASSWORD",
            "JW_COOKIE": "session=SYNTHETIC_COOKIE",
            "BARK_DEVICE_KEY": "SYNTHETIC_DEVICE_KEY",
            "EMAIL_PASSWORD": "SYNTHETIC_SMTP_PASSWORD",
            "HTTPS_PROXY": "http://SYNTHETIC_PROXY_USER:SYNTHETIC_PROXY_PASSWORD@example.invalid:8080",
        }
        grade = Grade("2026-2027-1", "SYNTHETIC_COURSE_CODE", "SYNTHETIC_COURSE_NAME",
                      "87.654321", "2.123456", "3.87654321", "SYNTHETIC_COURSE_TYPE")
        with TemporaryDirectory() as directory:
            state_path = Path(directory) / "grade_state.json"
            report_path = Path(directory) / "transcript.html"
            environment = {
                **private_values,
                "JW_SEMESTER": grade.semester,
                "FORCE_CHECK": "true",
                "COMPLETION_MODE": "count",
                "EXPECTED_GRADE_COUNT": "1",
                "NOTIFY_ON_FIRST_RUN": "true",
                "GRADE_STATE_SALT": "SYNTHETIC_STATE_SALT" * 3,
                "GRADE_STATE_PATH": str(state_path),
                "GRADE_REPORT_PATH": str(report_path),
                "EMAIL_FROM": "sender@example.invalid",
                "EMAIL_TO": "reader@example.invalid",
                "EMAIL_SMTP_SERVER": "smtp.example.invalid",
                "EMAIL_SMTP_PORT": "465",
                "MONITOR_ENABLED": "false",
            }
            response = MagicMock()
            response.__enter__.return_value = response
            response.status = 200
            response.read.return_value = b'{"code":200}'
            output = io.StringIO()
            with patch.dict("os.environ", environment, clear=True), patch("config.load_dotenv"), patch(
                "check_grades.fetch_grades", new_callable=AsyncMock, return_value=[grade],
            ), patch("bark_notify.urlopen", return_value=response) as bark, patch(
                "notifications.smtplib.SMTP_SSL",
            ) as smtp, redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(main(), 0)

            # Grade content is deliberately sent only to the configured channels.
            self.assertIn(grade.course_name, bark.call_args_list[0].args[0].data.decode("utf-8"))
            smtp.return_value.__enter__.return_value.sendmail.assert_called_once()
            report = report_path.read_text(encoding="utf-8")
            self.assertIn(grade.course_name, report)
            self.assertIn(grade.score, report)
            public_output = output.getvalue() + state_path.read_text(encoding="utf-8")
            for marker in (*private_values.values(), grade.course_code, grade.course_name,
                           grade.score, grade.credit, grade.gpa, grade.course_type):
                with self.subTest(marker_type="synthetic private value"):
                    self.assertNotIn(marker, public_output)
            for marker in private_values.values():
                self.assertNotIn(marker, report)


if __name__ == "__main__":
    unittest.main()
