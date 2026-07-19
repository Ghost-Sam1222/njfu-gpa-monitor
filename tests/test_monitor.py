from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from check_grades import (
    completion_summary,
    deliver_email,
    deliver_realtime,
    fetch_grades_with_retry,
    format_grades,
    is_complete,
    run,
)
from grade_source import GradeSourceError
from config import Settings
from models import Grade
from notifications import NotificationSettings
from state import MonitorState


def settings() -> Settings:
    return Settings(
        base_url="https://jwxt.njfu.edu.cn",
        username="student",
        password="secret",
        cookie="",
        semester="2025-2026-2",
        enabled=True,
        monitor_until=date(2026, 7, 31),
        check_start_date=None,
        expected_course_names=(),
        expected_grade_count=1,
        completion_mode="count",
        notify_on_first_run=False,
        email_batch_size=3,
        final_report_enabled=True,
        state_salt="x" * 32,
        state_path=Path("state.json"),
        report_path=Path("report.html"),
        notifications=NotificationSettings(),
    )


class MonitorPolicyTests(unittest.TestCase):
    def test_realtime_message_keeps_compact_grade_format(self) -> None:
        grades = [Grade("2025-2026-2", "1", "体育（4）", "86", "1", "3.5", "必修")]
        self.assertEqual(
            format_grades(grades, 3.35),
            "体育（4）｜成绩：86，绩点：3.5，学分：1\n平均绩点：3.35",
        )

    def test_completion_message_only_adds_average_gpa(self) -> None:
        grades = [Grade("2025-2026-2", "1", "课程A", "90", "2", "4", "必修")]
        self.assertEqual(completion_summary(settings(), grades), "本学期成绩已全部到齐。\n平均绩点：4.00")

    def test_expected_count_uses_current_result_set(self) -> None:
        configured = replace(settings(), expected_grade_count=2)
        grades = [Grade(configured.semester, "1", "A", "90", "1", "4", "必修")]
        self.assertFalse(is_complete(configured, grades))

    def test_date_mode_completes_on_the_configured_stop_date(self) -> None:
        configured = replace(settings(), completion_mode="date")
        grades = [Grade(configured.semester, "1", "A", "90", "1", "4", "必修")]
        with patch("check_grades.shanghai_today", return_value=configured.monitor_until):
            self.assertTrue(is_complete(configured, grades))
        self.assertEqual(
            completion_summary(configured, grades),
            "已到设定的监控截止日期。\n平均绩点：4.00",
        )

    def test_date_mode_never_completes_an_empty_result(self) -> None:
        configured = replace(settings(), completion_mode="date")
        with patch("check_grades.shanghai_today", return_value=configured.monitor_until):
            self.assertFalse(is_complete(configured, []))

    def test_source_retry_recovers_from_a_transient_failure(self) -> None:
        item = Grade("2025-2026-2", "1", "课程A", "90", "1", "4", "必修")
        with patch(
            "check_grades.fetch_grades",
            side_effect=[GradeSourceError("temporary"), [item]],
        ) as fetch, patch("check_grades.time.sleep") as sleep:
            self.assertEqual(fetch_grades_with_retry(settings()), [item])
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_course_names_match_exactly_after_whitespace_normalization(self) -> None:
        configured = replace(settings(), completion_mode="names", expected_course_names=("高等 数学",))
        exact = [Grade(configured.semester, "1", "高等数学", "90", "1", "4", "必修")]
        similar = [Grade(configured.semester, "1", "高等数学实验", "90", "1", "4", "必修")]
        self.assertTrue(is_complete(configured, exact))
        self.assertFalse(is_complete(configured, similar))

    def test_course_names_normalize_fullwidth_punctuation(self) -> None:
        configured = replace(settings(), completion_mode="names", expected_course_names=("大学英语(4)",))
        grades = [Grade(configured.semester, "1", "大学英语（4）", "90", "1", "4", "必修")]
        self.assertTrue(is_complete(configured, grades))

    def test_successful_channel_is_not_retried(self) -> None:
        notifications = NotificationSettings(
            bark_device_key="bark-key",
            slack_webhook_url="https://hooks.slack.test/example",
        )
        configured = replace(settings(), notifications=notifications)
        item = Grade(configured.semester, "1", "课程A", "90", "1", "4", "必修")
        item_hash = item.identity(configured.state_salt)
        state = MonitorState(configured.semester, initialized=True)
        state.delivered("bark").add(item_hash)
        state.delivered("slack")
        sent: list[str] = []
        with patch("check_grades.send_channel", side_effect=lambda _settings, channel, _title, _body: sent.append(channel)):
            failures = deliver_realtime(configured, state, {item_hash: item}, False)
        self.assertEqual(failures, [])
        self.assertEqual(sent, ["slack"])

    def test_final_email_is_sent_once(self) -> None:
        notifications = NotificationSettings(
            email_from="sender@example.com",
            email_password="app-password",
            email_to="reader@example.com",
            email_smtp_server="smtp.example.com",
            email_smtp_port=465,
        )
        item = Grade("2025-2026-2", "1", "课程A", "90", "1", "4", "必修")
        state = MonitorState(item.semester, initialized=True)
        with TemporaryDirectory() as directory:
            configured = replace(
                settings(),
                notifications=notifications,
                report_path=Path(directory) / "report.html",
            )
            with patch("check_grades.send_email") as mocked_send:
                self.assertEqual(deliver_email(configured, state, [item], True, 1), [])
                self.assertEqual(deliver_email(configured, state, [item], True, 0), [])
            self.assertEqual(mocked_send.call_count, 1)

    def test_third_consecutive_source_failure_sends_one_health_alert(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(
                settings(),
                state_path=Path(directory) / "state.json",
                notifications=NotificationSettings(bark_device_key="bark-key"),
            )
            with patch("check_grades.load_settings", return_value=configured), patch(
                "check_grades.fetch_grades_with_retry", side_effect=GradeSourceError("login unavailable")
            ), patch("check_grades.deliver_health_alert") as alert:
                for _ in range(3):
                    with self.assertRaises(GradeSourceError):
                        run()
            alert.assert_called_once_with(configured, 3)


if __name__ == "__main__":
    unittest.main()
