from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from check_grades import main
from state import MonitorState, load_state, save_state


SEMESTER = "2026-2027-1"
EMPTY_TABLE = '<table id="dataList"><tr><th>学年学期</th><th>课程名称</th><th>成绩</th></tr></table>'
STALE_TABLE = EMPTY_TABLE.replace("</table>", f"<tr><td>{SEMESTER}</td><td>合成旧课程</td><td>90</td></tr></table>")


class GradeResponseFlowTests(unittest.TestCase):
    def run_response(self, response: str, directory: str) -> tuple[int, MagicMock, AsyncMock]:
        page = SimpleNamespace(
            url="https://jwxt.njfu.edu.cn/jsxsd/kscj/cjcx_list",
            goto=AsyncMock(), evaluate=AsyncMock(return_value=response),
            content=AsyncMock(return_value=STALE_TABLE),
        )
        context = SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        manager = MagicMock()
        manager.__aenter__.return_value = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        browser_module = ModuleType("playwright.async_api")
        browser_module.async_playwright = MagicMock(return_value=manager)
        environment = {
            "JW_USERNAME": "synthetic-student", "JW_PASSWORD": "synthetic-password",
            "JW_SEMESTER": SEMESTER, "GRADE_STATE_SALT": "synthetic-state-salt" * 3,
            "GRADE_STATE_PATH": str(Path(directory) / "state.json"),
            "FORCE_CHECK": "true", "MONITOR_ENABLED": "false",
            "COMPLETION_MODE": "count", "EXPECTED_GRADE_COUNT": "1",
            "NOTIFY_ON_FIRST_RUN": "true", "BARK_DEVICE_KEY": "synthetic-device",
        }
        with patch.dict("os.environ", environment, clear=True), patch.dict(sys.modules, {
            "playwright": ModuleType("playwright"), "playwright.async_api": browser_module,
        }), patch("config.load_dotenv"), patch("check_grades.time.sleep"), patch(
            "check_grades.send_channel",
        ) as sender, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = main()
        return status, sender, page.content

    def test_invalid_query_response_cannot_use_stale_page_or_change_baseline(self) -> None:
        invalid_responses = (
            '<form><input name="username"><input id="password"></form>',
            '{"success":false,"message":"synthetic session expired"}',
            '<html><p>系统维护，请稍后查询</p></html>',
            '<table id="dataList"><tr><th>课程名称</th></tr></table>',
        )
        for response in invalid_responses:
            for initialized in (False, True):
                with self.subTest(response_type=response[:15], initialized=initialized), TemporaryDirectory() as directory:
                    path = Path(directory) / "state.json"
                    original = MonitorState(SEMESTER, initialized=initialized)
                    if initialized:
                        original.observed_hashes.add("synthetic-existing-hash")
                        original.delivered("bark").add("synthetic-existing-hash")
                        save_state(path, original)
                    status, sender, content = self.run_response(response, directory)
                    self.assertEqual(status, 1)
                    restored = load_state(path, SEMESTER)
                    self.assertEqual(restored.initialized, initialized)
                    self.assertEqual(restored.observed_hashes, original.observed_hashes)
                    self.assertEqual(restored.delivered_by_channel, original.delivered_by_channel)
                    self.assertFalse(restored.complete)
                    self.assertEqual(restored.consecutive_failures, 1)
                    sender.assert_not_called()
                    content.assert_not_awaited()

    def test_valid_empty_query_is_a_baseline_not_completion(self) -> None:
        with TemporaryDirectory() as directory:
            status, sender, content = self.run_response(EMPTY_TABLE, directory)
            restored = load_state(Path(directory) / "state.json", SEMESTER)
            self.assertEqual(status, 0)
            self.assertTrue(restored.initialized)
            self.assertFalse(restored.complete)
            self.assertEqual(restored.observed_hashes, set())
            self.assertEqual(restored.consecutive_failures, 0)
            sender.assert_not_called()
            content.assert_not_awaited()

    def test_valid_grade_query_still_completes_normally(self) -> None:
        with TemporaryDirectory() as directory:
            status, sender, content = self.run_response(STALE_TABLE, directory)
            restored = load_state(Path(directory) / "state.json", SEMESTER)
            self.assertEqual(status, 0)
            self.assertTrue(restored.complete)
            self.assertEqual(len(restored.observed_hashes), 1)
            self.assertEqual(sender.call_count, 2)
            content.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
