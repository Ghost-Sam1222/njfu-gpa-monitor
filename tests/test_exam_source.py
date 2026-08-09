from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from exam_source import (
    ExamAuthenticationError,
    ExamFetchResult,
    ExamParseError,
    ExamProject,
    _infer_campus,
    _infer_exam_type,
    _infer_query_category,
    _discover_exam_projects,
    _is_login_url,
    _parse_datetime_range,
    _run_cli,
    describe_result,
    parse_exam_html,
    parse_exam_projects,
    parse_exam_projects_text,
    suggested_monitor_until,
    suggestion_for_setup,
)
from models import Exam


def make_exam(
    course_name: str = "测试课程",
    start: str = "2026-07-10T10:15:00",
    end: str = "2026-07-10T12:15:00",
    project_id: str = "project-1",
) -> Exam:
    return Exam(
        semester="2025-2026-2",
        exam_project_id=project_id,
        exam_project_name="期末考试（淮安校区）",
        exam_type="期末考试",
        campus="淮安校区",
        course_code="TEST001",
        course_name=course_name,
        start_time=datetime.fromisoformat(start),
        end_time=datetime.fromisoformat(end),
        location="测试教室",
    )


class ExamProjectTests(unittest.TestCase):
    def test_parses_njfu_project_response(self) -> None:
        projects = parse_exam_projects(
            [
                {"kw0401id": "a", "ksmc": "期末考试（新庄校区）"},
                {"kw0401id": "b", "ksmc": "期末考试机考（淮安校区）"},
            ]
        )
        self.assertEqual(projects, [
            ExamProject("a", "期末考试（新庄校区）"),
            ExamProject("b", "期末考试机考（淮安校区）"),
        ])

    def test_deduplicates_project_ids(self) -> None:
        projects = parse_exam_projects([
            {"kw0401id": "a", "ksmc": "期末考试"},
            {"kw0401id": "a", "ksmc": "期末考试"},
        ])
        self.assertEqual(len(projects), 1)

    def test_empty_project_list_is_valid(self) -> None:
        self.assertEqual(parse_exam_projects([]), [])

    def test_rejects_changed_project_schema(self) -> None:
        with self.assertRaises(ExamParseError):
            parse_exam_projects([{"id": "a", "name": "期末考试"}])

    def test_rejects_non_json_project_response(self) -> None:
        with self.assertRaises(ExamParseError):
            parse_exam_projects_text("<html>server error</html>")

    def test_accepts_utf8_bom_in_project_response(self) -> None:
        projects = parse_exam_projects_text('\ufeff[{"kw0401id":"a","ksmc":"期末考试"}]')
        self.assertEqual(projects, [ExamProject("a", "期末考试")])

    def test_recognizes_both_njfu_login_hosts(self) -> None:
        self.assertTrue(_is_login_url("https://authserver.njfu.edu.cn/authserver/login"))
        self.assertTrue(_is_login_url("https://uia.njfu.edu.cn/cas/login"))
        self.assertFalse(_is_login_url("https://jwxt.njfu.edu.cn/jsxsd/xsks/xsksap_query"))


class ExamRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_project_discovery_uses_school_page_loader(self) -> None:
        page = MagicMock()
        page.locator.return_value.count = AsyncMock(return_value=1)
        page.select_option = AsyncMock(return_value=["2025-2026-2"])
        page.evaluate = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.eval_on_selector_all = AsyncMock(return_value=[
            {"kw0401id": "p1", "ksmc": "期末考试（新庄校区）"}
        ])
        projects = await _discover_exam_projects(page, "2025-2026-2")
        self.assertEqual(projects, [ExamProject("p1", "期末考试（新庄校区）")])
        self.assertIn("onckKsmc", page.evaluate.await_args.args[0])

    async def test_project_discovery_requires_exam_form(self) -> None:
        page = MagicMock()
        page.locator.return_value.count = AsyncMock(return_value=0)
        with self.assertRaises(ExamAuthenticationError):
            await _discover_exam_projects(page, "2025-2026-2")


class ExamHTMLTests(unittest.TestCase):
    def test_parses_verified_njfu_table_shape(self) -> None:
        html = """
        <table id="dataList">
          <tr><th>序号</th><th>校区</th><th>考试校区</th><th>考试场次</th>
          <th>课程编号</th><th>课程名称</th><th>授课教师</th><th>考试时间</th>
          <th>考场</th><th>座位号</th><th>准考证号</th><th>备注</th><th>操作</th></tr>
          <tr><td>1</td><td>淮安校区</td><td>淮安校区</td><td>001</td>
          <td>TEST001</td><td>测试课程</td><td>测试教师</td><td>2026-07-10 10:15~12:15</td>
          <td>测试教室</td><td>18</td><td></td><td></td><td></td></tr>
        </table>
        """
        exams, recognized = parse_exam_html(html, "2025-2026-2", "p1", "期末考试（淮安校区）")
        self.assertTrue(recognized)
        self.assertEqual(len(exams), 1)
        self.assertEqual(exams[0].course_code, "TEST001")
        self.assertEqual(exams[0].course_name, "测试课程")
        self.assertEqual(exams[0].campus, "淮安校区")
        self.assertEqual(exams[0].location, "测试教室")
        self.assertEqual(exams[0].start_time, datetime(2026, 7, 10, 10, 15))
        self.assertEqual(exams[0].end_time, datetime(2026, 7, 10, 12, 15))

    def test_course_name_does_not_match_course_code_header(self) -> None:
        html = """
        <table><tr><th>课程编号</th><th>课程名称</th><th>考试时间</th><th>考场</th></tr>
        <tr><td>CODE9</td><td>课程九</td><td>2026-06-01 08:00~10:00</td><td>A101</td></tr></table>
        """
        exams, _ = parse_exam_html(html, "2025-2026-2", "p", "期末考试")
        self.assertEqual(exams[0].course_code, "CODE9")
        self.assertEqual(exams[0].course_name, "课程九")

    def test_explicit_empty_table_is_recognized(self) -> None:
        html = "<table><tr><th>课程名称</th><th>考试时间</th></tr><tr><td colspan='2'>未查询到数据</td></tr></table>"
        exams, recognized = parse_exam_html(html, "2025-2026-2", "p", "期末考试")
        self.assertTrue(recognized)
        self.assertEqual(exams, [])

    def test_unrelated_html_is_incomplete(self) -> None:
        exams, recognized = parse_exam_html("<html><p>系统提示</p></html>", "2025-2026-2", "p", "期末考试")
        self.assertFalse(recognized)
        self.assertEqual(exams, [])

    def test_unparseable_exam_time_is_not_silently_ignored(self) -> None:
        html = """
        <table><tr><th>课程名称</th><th>考试时间</th></tr>
        <tr><td>测试课程</td><td>时间另行通知</td></tr></table>
        """
        with self.assertRaises(ExamParseError):
            parse_exam_html(html, "2025-2026-2", "p", "期末考试")

    def test_login_page_raises_authentication_error(self) -> None:
        html = '<form><input name="username"><input name="password"></form>'
        with self.assertRaises(ExamAuthenticationError):
            parse_exam_html(html, "2025-2026-2", "p", "期末考试")

    def test_single_quoted_login_page_raises_authentication_error(self) -> None:
        html = "<form><input name='username'><input id='password'></form>"
        with self.assertRaises(ExamAuthenticationError):
            parse_exam_html(html, "2025-2026-2", "p", "期末考试")


class DateParsingTests(unittest.TestCase):
    def test_parses_full_range(self) -> None:
        start, end = _parse_datetime_range("2026-07-10 10:15~12:15", "2025-2026-2")
        self.assertEqual(start, datetime(2026, 7, 10, 10, 15))
        self.assertEqual(end, datetime(2026, 7, 10, 12, 15))

    def test_infers_year_across_autumn_semester(self) -> None:
        december, _ = _parse_datetime_range("12月20日 09:00~11:00", "2026-2027-1")
        january, _ = _parse_datetime_range("1月5日 09:00~11:00", "2026-2027-1")
        self.assertEqual(december, datetime(2026, 12, 20, 9, 0))
        self.assertEqual(january, datetime(2027, 1, 5, 9, 0))

    def test_single_time_does_not_invent_duration(self) -> None:
        start, end = _parse_datetime_range("2026-07-10 10:15", "2025-2026-2")
        self.assertEqual(start, end)

    def test_invalid_date_is_rejected(self) -> None:
        self.assertEqual(_parse_datetime_range("2026-02-30 09:00~11:00"), (None, None))


class ClassificationTests(unittest.TestCase):
    def test_project_name_classification(self) -> None:
        self.assertEqual(_infer_exam_type("期末考试机考（淮安校区）"), "机考")
        self.assertEqual(_infer_exam_type("开学补考"), "补考")
        self.assertEqual(_infer_campus("期末考试（新庄校区）"), "新庄校区")

    def test_query_category_matches_njfu_form_values(self) -> None:
        self.assertEqual(_infer_query_category("开学补考"), "1")
        self.assertEqual(_infer_query_category("期中考试"), "2")
        self.assertEqual(_infer_query_category("期末考试机考（淮安校区）"), "3")


class SuggestionTests(unittest.TestCase):
    def test_adds_30_days_to_latest_exam(self) -> None:
        exams = [
            make_exam(end="2026-07-02T10:00:00"),
            make_exam(start="2026-07-10T10:15:00", end="2026-07-10T12:15:00"),
        ]
        self.assertEqual(suggested_monitor_until(exams), date(2026, 8, 9))

    def test_description_counts_projects_even_when_they_have_no_rows(self) -> None:
        projects = (ExamProject("p1", "期末考试"), ExamProject("p2", "期末机考"))
        payload = describe_result(ExamFetchResult((make_exam(),), projects))
        self.assertEqual(payload["exam_count"], 1)
        self.assertEqual(payload["project_count"], 2)
        self.assertEqual(payload["suggested_monitor_until"], "2026-08-09")
        self.assertTrue(payload["complete"])

    def test_failed_project_makes_result_incomplete(self) -> None:
        project = ExamProject("p1", "期末考试")
        payload = describe_result(ExamFetchResult((), (project,), (project,)))
        self.assertFalse(payload["complete"])
        self.assertEqual(payload["failed_project_count"], 1)

    def test_setup_failure_is_sanitized(self) -> None:
        with patch("exam_source.fetch_exams", new=AsyncMock(side_effect=ExamParseError("private response"))):
            result = __import__("asyncio").run(suggestion_for_setup(object()))
        self.assertFalse(result["complete"])
        self.assertNotIn("private response", result["error"])


class CLITests(unittest.TestCase):
    def test_summary_is_private_safe(self) -> None:
        result = ExamFetchResult((make_exam(course_name="不应出现在摘要"),), (ExamProject("p", "期末考试"),))
        output = io.StringIO()
        environment = {"JW_USERNAME": "user", "JW_PASSWORD": "password"}
        with patch.dict("os.environ", environment, clear=True), patch(
            "exam_source.fetch_exams", new=AsyncMock(return_value=result)
        ), redirect_stdout(output):
            exit_code = _run_cli(["--semester", "2025-2026-2", "--format", "summary"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertNotIn("exams", payload)
        self.assertNotIn("不应出现在摘要", output.getvalue())

    def test_incomplete_query_has_distinct_exit_code(self) -> None:
        project = ExamProject("p", "期末考试")
        result = ExamFetchResult((), (project,), (project,))
        with patch.dict("os.environ", {"JW_COOKIE": "cookie"}, clear=True), patch(
            "exam_source.fetch_exams", new=AsyncMock(return_value=result)
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(_run_cli(["--format", "latest"]), 2)

    def test_missing_credentials_has_auth_exit_code(self) -> None:
        with patch.dict("os.environ", {}, clear=True), redirect_stderr(io.StringIO()):
            self.assertEqual(_run_cli([]), 3)


if __name__ == "__main__":
    unittest.main()
