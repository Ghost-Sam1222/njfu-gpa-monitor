from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from setup_wizard import Handler


class FirstRunSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_secrets: dict[str, str] = {}
        self.saved_variables: dict[str, str] = {}
        self.commands: list[tuple[str, ...]] = []
        self.server = SimpleNamespace(csrf_token="offline-test", verified_login_digest="")
        self.payload = {
            "repository": "reader/offline-monitor",
            "secrets": {"JW_USERNAME": "example-student", "JW_PASSWORD": "example-only"},
            "variables": {
                "JW_SEMESTER": "2026-2027-1",
                "COMPLETION_MODE": "date",
                "MONITOR_ENABLED": "false",
                "CHECK_START_DATE": "",
                "MONITOR_UNTIL": "",
                "CHECK_INTERVAL_HOURS": "6",
            },
            "run_test": False,
        }
        for target, replacement in (
            ("setup_wizard.gh", self.fake_gh),
            ("setup_wizard.shutil.which", MagicMock(return_value="offline-gh")),
            ("setup_wizard.cloud_target_allowed", MagicMock(return_value=True)),
            ("setup_wizard.latest_workflow_run", MagicMock(return_value=None)),
            ("setup_wizard.wait_for_workflow", MagicMock(return_value={
                "status": "completed", "conclusion": "success", "url": "https://example.invalid/run",
            })),
        ):
            mock_patch = patch(target, replacement)
            mock_patch.start()
            self.addCleanup(mock_patch.stop)
        self.source = self.enter_context(patch("setup_wizard.fetch_grades", new_callable=AsyncMock))
        self.source.return_value = []
        self.exams = self.enter_context(patch("setup_wizard.suggestion_for_setup", new_callable=AsyncMock))

    def enter_context(self, context):
        result = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return result

    def fake_gh(self, *args: str, stdin: str | None = None) -> SimpleNamespace:
        self.commands.append(args)
        output = ""
        if args[:2] == ("secret", "list"):
            output = "\n".join(self.saved_secrets)
        elif args[:2] == ("variable", "list"):
            output = json.dumps([{"name": key, "value": value} for key, value in self.saved_variables.items()])
        elif args[:2] == ("secret", "set"):
            self.saved_secrets[args[2]] = stdin
        elif args[:2] == ("variable", "set"):
            self.saved_variables[args[2]] = args[args.index("--body") + 1]
        elif args[:2] not in {
            ("auth", "status"), ("repo", "view"), ("workflow", "enable"), ("workflow", "run"),
        } and not (args[0] == "api" and args[3].endswith("/actions/permissions/workflow")):
            self.fail(f"Unexpected offline command: {args[:2]}")
        return SimpleNamespace(returncode=0, stdout=output)

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode()
        handler = Handler.__new__(Handler)
        handler.server = self.server
        handler.path = path
        handler.headers = {"X-CSRF-Token": "offline-test", "Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler._is_trusted_request = MagicMock(return_value=True)
        handler._json = MagicMock()
        handler.do_POST()
        return handler._json.call_args.args

    def verify(self) -> None:
        credentials = self.payload["secrets"]
        status, result = self.post("/api/verify-jw", {
            "username": credentials["JW_USERNAME"], "password": credentials["JW_PASSWORD"],
            "semester": self.payload["variables"]["JW_SEMESTER"],
        })
        self.assertEqual((status, result["status"]), (200, "empty"))
        self.assertIn("暂无已公布成绩", result["message"])

    def test_fresh_setup_requires_login_then_a_notification_channel(self) -> None:
        for credentials in ({}, self.payload["secrets"]):
            with self.subTest(credentials_present=bool(credentials)):
                status, result = self.post("/api/apply", {**self.payload, "secrets": credentials})
                self.assertEqual(status, 400)
                self.assertIn("验证教务登录", result["error"])
                self.assertEqual(self.saved_secrets, {})
        self.verify()
        status, result = self.post("/api/apply", self.payload)
        self.assertEqual(status, 400)
        self.assertIn("至少配置一种完整的通知渠道", result["error"])
        self.assertEqual(self.saved_secrets, {})
        self.exams.assert_not_called()

    def test_preexam_save_preserves_disabled_monitor_and_never_dispatches_grades(self) -> None:
        self.verify()
        self.payload["secrets"]["BARK_DEVICE_KEY"] = "offline-device"
        status, result = self.post("/api/apply", self.payload)
        self.assertEqual((status, result["test_status"]), (200, "not_requested"))
        self.assertEqual(self.saved_variables["MONITOR_ENABLED"], "false")
        self.assertNotIn("MONITOR_UNTIL", self.saved_variables)
        self.assertNotIn("CHECK_START_DATE", self.saved_variables)
        self.assertEqual(len(self.saved_secrets["GRADE_STATE_SALT"]), 64)
        self.assertNotIn("JW_PASSWORD", self.saved_variables)
        self.assertFalse(any(command[:2] == ("workflow", "run") for command in self.commands))
        self.assertEqual(self.source.await_count, 1)
        self.exams.assert_not_called()
        self.assertNotIn("example-only", json.dumps(result))
        self.assertTrue(result["login_verified"])
        self.assertFalse(result["monitor_enabled"])

    def test_missing_semester_cannot_verify_or_save(self) -> None:
        self.payload["variables"]["JW_SEMESTER"] = ""
        status, result = self.post("/api/verify-jw", {
            "username": "example-student", "password": "example-only", "semester": "",
        })
        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])
        self.assertEqual(self.post("/api/apply", self.payload)[0], 400)
        self.assertEqual(self.saved_secrets, {})
        self.source.assert_not_called()

    def test_changing_semester_after_verification_requires_reverification(self) -> None:
        self.verify()
        self.payload["variables"]["JW_SEMESTER"] = "2026-2027-2"
        self.payload["secrets"]["BARK_DEVICE_KEY"] = "offline-device"
        status, result = self.post("/api/apply", self.payload)
        self.assertEqual(status, 400)
        self.assertIn("尚未验证", result["error"])
        self.assertEqual(self.saved_secrets, {})

    def test_notification_test_does_not_verify_reused_login_or_enable_monitor(self) -> None:
        self.saved_secrets.update({"JW_USERNAME": "example-student", "JW_PASSWORD": "example-only", "BARK_DEVICE_KEY": "offline-device"})
        self.saved_variables["JW_SEMESTER"] = "2026-2027-1"
        self.payload.update(secrets={}, run_test=True)
        status, result = self.post("/api/apply", self.payload)
        self.assertEqual((status, result["test_status"]), (200, "success"))
        self.assertFalse(result["login_verified"])
        self.assertFalse(result["monitor_enabled"])
        self.assertEqual(self.saved_variables["MONITOR_ENABLED"], "false")
        dispatched = [command[2] for command in self.commands if command[:2] == ("workflow", "run")]
        self.assertEqual(dispatched, ["test-notifications.yml"])
        self.source.assert_not_called()
        self.exams.assert_not_called()

    def test_enabling_monitor_without_stop_date_makes_no_changes(self) -> None:
        self.payload["variables"]["MONITOR_ENABLED"] = "true"
        status, result = self.post("/api/apply", self.payload)
        self.assertEqual(status, 400)
        self.assertIn("必须填写停止日期", result["error"])
        self.assertEqual(self.saved_variables, {})
        self.assertEqual(self.saved_secrets, {})
        self.source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
