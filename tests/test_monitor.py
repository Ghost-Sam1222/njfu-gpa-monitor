from __future__ import annotations

import json
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
    should_skip,
)
from grade_source import GradeSourceError
from config import Settings
from completion import cached_completion
from models import Grade
from notifications import NotificationError, NotificationSettings
from state import MonitorState, load_state


def settings() -> Settings:
    return Settings(
        base_url="https://jwxt.njfu.edu.cn",
        username="student",
        password="secret",
        cookie="",
        semester="2025-2026-2",
        enabled=True,
        force_check=False,
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
    def test_successful_completion_skips_later_scheduled_fetch(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            item = Grade(configured.semester, "SYNTH-1", "合成课程", "90", "1", "4", "必修")
            with patch("check_grades.shanghai_today", return_value=date(2026, 7, 1)), patch(
                "check_grades.load_settings", return_value=configured,
            ), patch("check_grades.fetch_grades_with_retry", return_value=[item]) as fetch, patch(
                "check_grades.send_channel",
            ):
                run()
                run()
            self.assertEqual(fetch.call_count, 1)
            with patch.dict("os.environ", {
                "JW_SEMESTER": configured.semester, "JW_USERNAME": configured.username,
                "GRADE_STATE_SALT": configured.state_salt, "GRADE_STATE_PATH": str(configured.state_path),
                "COMPLETION_MODE": "count", "EXPECTED_GRADE_COUNT": "1",
                "MONITOR_UNTIL": configured.monitor_until.isoformat(), "COMPLETION_CHANNELS": "bark",
            }, clear=True):
                self.assertTrue(cached_completion())

    def test_failed_completion_notification_retries_before_stopping(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            item = Grade(configured.semester, "SYNTH-1", "合成课程", "90", "1", "4", "必修")
            with patch("check_grades.shanghai_today", return_value=date(2026, 7, 1)), patch(
                "check_grades.load_settings", return_value=configured,
            ), patch("check_grades.fetch_grades_with_retry", return_value=[item]) as fetch, patch(
                "check_grades.send_channel", side_effect=[NotificationError("offline"), None],
            ) as sender:
                with self.assertRaisesRegex(RuntimeError, "Notification delivery failed"):
                    run()
                self.assertFalse(load_state(configured.state_path, configured.semester).complete)
                run()
                run()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(sender.call_count, 2)

    def test_changed_completion_target_resumes_without_replaying_grades(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            item = Grade(configured.semester, "SYNTH-1", "合成课程", "90", "1", "4", "必修")
            with patch("check_grades.shanghai_today", return_value=date(2026, 7, 1)), patch(
                "check_grades.load_settings", side_effect=[configured, replace(configured, expected_grade_count=2)],
            ), patch("check_grades.fetch_grades_with_retry", return_value=[item]) as fetch, patch(
                "check_grades.send_channel",
            ) as sender:
                run()
                run()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(sender.call_count, 1)
            self.assertFalse(load_state(configured.state_path, configured.semester).complete)

    def test_manual_force_check_still_fetches_after_completion(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            item = Grade(configured.semester, "SYNTH-1", "合成课程", "90", "1", "4", "必修")
            with patch("check_grades.shanghai_today", return_value=date(2026, 7, 1)), patch(
                "check_grades.load_settings", side_effect=[configured, replace(configured, force_check=True)],
            ), patch("check_grades.fetch_grades_with_retry", return_value=[item]) as fetch, patch(
                "check_grades.send_channel",
            ) as sender:
                run()
                run()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(sender.call_count, 1)

    def test_completion_flushes_remaining_email_without_final_report(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), final_report_enabled=False,
                                 report_path=Path(directory) / "report.html",
                                 notifications=NotificationSettings(email_from="sender@example.com",
                                     email_password="test-password", email_to="reader@example.com"))
            item = Grade(configured.semester, "SYNTH-1", "合成课程", "90", "1", "4", "必修")
            state = MonitorState(configured.semester, initialized=True)
            with patch("check_grades.send_email") as sender:
                self.assertEqual(deliver_email(configured, state, [item], True, 1), [])
            sender.assert_called_once()
            self.assertEqual(state.email_pending_count, 0)

    def test_manual_force_check_ignores_switch_and_date_window(self) -> None:
        configured = replace(
            settings(),
            enabled=False,
            force_check=True,
            check_start_date=date(2027, 1, 1),
            monitor_until=date(2026, 1, 1),
        )
        with patch("check_grades.shanghai_today", return_value=date(2026, 7, 31)):
            self.assertFalse(should_skip(configured))

    def test_scheduled_check_still_obeys_stop_date(self) -> None:
        configured = replace(settings(), monitor_until=date(2026, 7, 25))
        with patch("check_grades.shanghai_today", return_value=date(2026, 7, 31)):
            self.assertTrue(should_skip(configured))

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

    def test_reverting_a_delivered_correction_notifies_again(self) -> None:
        configured = replace(settings(), notifications=NotificationSettings(bark_device_key="test-key"))
        original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
        corrected = replace(original, score="85", gpa="3.5")
        state = MonitorState(configured.semester, initialized=True)
        state.delivered("bark").add(original.identity(configured.state_salt))
        marker = f"completion:{configured.semester}"
        state.delivered("bark").add(marker)
        with patch("check_grades.send_channel") as sender:
            for item in (corrected, original):
                self.assertEqual(deliver_realtime(
                    configured, state, {item.identity(configured.state_salt): item}, True,
                ), [])
        self.assertEqual(sender.call_count, 2)
        self.assertIn(marker, state.delivered("bark"))

    def test_failed_correction_does_not_renotify_the_last_delivered_value(self) -> None:
        configured = replace(settings(), notifications=NotificationSettings(bark_device_key="test-key"))
        original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
        corrected = replace(original, score="85", gpa="3.5")
        state = MonitorState(configured.semester, initialized=True)
        state.delivered("bark").add(original.identity(configured.state_salt))
        with patch("check_grades.send_channel", side_effect=NotificationError("offline")):
            self.assertEqual(len(deliver_realtime(
                configured, state, {corrected.identity(configured.state_salt): corrected}, False,
            )), 1)
        with patch("check_grades.send_channel") as sender:
            self.assertEqual(deliver_realtime(
                configured, state, {original.identity(configured.state_salt): original}, False,
            ), [])
        sender.assert_not_called()

    def test_channel_snapshots_remain_independent_across_a_failed_correction(self) -> None:
        configured = replace(settings(), notifications=NotificationSettings(
            bark_device_key="test-key", slack_webhook_url="https://hooks.slack.test/example",
        ))
        original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
        corrected = replace(original, score="85", gpa="3.5")
        state = MonitorState(configured.semester, initialized=True)
        for channel in ("bark", "slack"):
            state.delivered(channel).add(original.identity(configured.state_salt))
        def send(_settings, channel, _title, _body):
            if channel == "bark":
                raise NotificationError("offline")
        with patch("check_grades.send_channel", side_effect=send):
            self.assertEqual(len(deliver_realtime(
                configured, state, {corrected.identity(configured.state_salt): corrected}, False,
            )), 1)
        with patch("check_grades.send_channel") as sender:
            self.assertEqual(deliver_realtime(
                configured, state, {original.identity(configured.state_salt): original}, False,
            ), [])
        self.assertEqual([call.args[1] for call in sender.call_args_list], ["slack"])

    def test_legacy_known_versions_do_not_replay_then_track_reversions(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), force_check=True, state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
            corrected = replace(original, score="85", gpa="3.5")
            marker = f"completion:{configured.semester}"
            history = [item.identity(configured.state_salt) for item in (original, corrected)]
            configured.state_path.write_text(json.dumps({
                "schema_version": 2, "semester": configured.semester, "initialized": True,
                "observed_hashes": history, "delivered_by_channel": {"bark": history + [marker]},
                "email_pending_count": 2,
            }))
            with patch("check_grades.load_settings", return_value=configured), patch(
                "check_grades.fetch_grades_with_retry", return_value=[original],
            ), patch("check_grades.send_channel") as sender:
                run()
            self.assertEqual(sender.call_count, 0)
            migrated = load_state(configured.state_path, configured.semester)
            self.assertEqual(migrated.observed_hashes, {original.identity(configured.state_salt)})
            self.assertEqual(migrated.delivered("bark"), {original.identity(configured.state_salt), marker})
            self.assertEqual(migrated.email_pending_count, 2)
            with patch("check_grades.load_settings", return_value=configured), patch(
                "check_grades.fetch_grades_with_retry", side_effect=[[corrected], [original]],
            ), patch("check_grades.send_channel") as sender:
                run()
                run()
            self.assertEqual(sender.call_count, 2)

    def test_legacy_migration_still_notifies_a_never_seen_correction(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(settings(), force_check=True, expected_grade_count=2,
                                 state_path=Path(directory) / "state.json",
                                 notifications=NotificationSettings(bark_device_key="test-key"))
            original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
            corrected = replace(original, score="85", gpa="3.5")
            configured.state_path.write_text(json.dumps({
                "schema_version": 2, "semester": configured.semester, "initialized": True,
                "observed_hashes": [original.identity(configured.state_salt)],
                "delivered_by_channel": {"bark": [original.identity(configured.state_salt)]},
            }))
            with patch("check_grades.load_settings", return_value=configured), patch(
                "check_grades.fetch_grades_with_retry", return_value=[corrected],
            ), patch("check_grades.send_channel") as sender:
                run()
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(load_state(configured.state_path, configured.semester).observed_hashes,
                             {corrected.identity(configured.state_salt)})

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

    def test_failed_email_correction_then_reversion_cancels_duplicate_report(self) -> None:
        notifications = NotificationSettings(
            email_from="sender@example.com", email_password="test-password",
            email_to="reader@example.com", email_smtp_server="smtp.example.com", email_smtp_port=465,
        )
        with TemporaryDirectory() as directory:
            configured = replace(settings(), notifications=notifications, email_batch_size=1,
                                 report_path=Path(directory) / "report.html")
            original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
            corrected = replace(original, score="85", gpa="3.5")
            state = MonitorState(configured.semester, initialized=True)
            state.delivered("email").add(original.identity(configured.state_salt))
            with patch("check_grades.send_email", side_effect=NotificationError("offline")):
                self.assertEqual(len(deliver_email(configured, state, [corrected], False, 1)), 1)
            self.assertEqual(state.delivered("email"), {original.identity(configured.state_salt)})
            self.assertEqual(state.email_pending_count, 1)
            with patch("check_grades.send_email") as sender:
                self.assertEqual(deliver_email(configured, state, [original], False, 1), [])
            sender.assert_not_called()
            self.assertEqual(state.email_pending_count, 0)

    def test_email_snapshots_track_successful_reversions_and_keep_completion_marker(self) -> None:
        notifications = NotificationSettings(
            email_from="sender@example.com", email_password="test-password",
            email_to="reader@example.com", email_smtp_server="smtp.example.com", email_smtp_port=465,
        )
        with TemporaryDirectory() as directory:
            configured = replace(settings(), notifications=notifications, email_batch_size=1,
                                 report_path=Path(directory) / "report.html")
            original = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
            corrected = replace(original, score="85", gpa="3.5")
            marker = f"completion:{configured.semester}"
            state = MonitorState(configured.semester, initialized=True)
            state.delivered("email").update({original.identity(configured.state_salt), marker})
            with patch("check_grades.send_email") as sender:
                for item in (corrected, original):
                    self.assertEqual(deliver_email(configured, state, [item], True, 1), [])
                    self.assertEqual(state.delivered("email"), {item.identity(configured.state_salt), marker})
            self.assertEqual(sender.call_count, 2)

    def test_legacy_email_pending_count_survives_failure_and_retries(self) -> None:
        notifications = NotificationSettings(
            email_from="sender@example.com", email_password="test-password",
            email_to="reader@example.com", email_smtp_server="smtp.example.com", email_smtp_port=465,
        )
        with TemporaryDirectory() as directory:
            configured = replace(settings(), notifications=notifications, email_batch_size=2,
                                 state_path=Path(directory) / "state.json", report_path=Path(directory) / "report.html")
            item = Grade(configured.semester, "SYNTH-001", "合成课程", "80", "2", "3.0", "必修")
            marker = f"completion:{configured.semester}"
            configured.state_path.write_text(json.dumps({
                "schema_version": 2, "semester": configured.semester, "initialized": True,
                "observed_hashes": [item.identity(configured.state_salt)],
                "delivered_by_channel": {"email": [marker]}, "email_pending_count": 2,
            }))
            state = load_state(configured.state_path, configured.semester)
            with patch("check_grades.send_email", side_effect=NotificationError("offline")):
                self.assertEqual(len(deliver_email(configured, state, [item], True, 0)), 1)
            self.assertEqual(state.email_pending_count, 2)
            self.assertEqual(state.delivered("email"), {marker})
            with patch("check_grades.send_email") as sender:
                self.assertEqual(deliver_email(configured, state, [item], True, 0), [])
            self.assertEqual(sender.call_count, 1)
            self.assertEqual(state.email_pending_count, 0)
            self.assertEqual(state.delivered("email"), {item.identity(configured.state_salt), marker})

    def test_third_consecutive_source_failure_sends_one_health_alert(self) -> None:
        with TemporaryDirectory() as directory:
            configured = replace(
                settings(),
                force_check=True,
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
