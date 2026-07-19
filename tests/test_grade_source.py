from __future__ import annotations

import unittest

from grade_source import GradeSourceError, _require_njfu_url, has_grade_table, parse_grades_html


class GradeSourceTests(unittest.TestCase):
    def test_parses_reordered_headers(self) -> None:
        html = """
        <table id="dataList">
          <tr><th>课程名称</th><th>课程编号</th><th>成绩</th><th>绩点</th><th>学分</th><th>课程属性</th><th>学年学期</th></tr>
          <tr><td>信号与系统</td><td>0802034</td><td>91</td><td>4.1</td><td>3.5</td><td>专业必修</td><td>2025-2026-2</td></tr>
        </table>
        """
        grades = parse_grades_html(html)
        self.assertEqual(len(grades), 1)
        self.assertEqual(grades[0].course_name, "信号与系统")
        self.assertEqual(grades[0].course_code, "0802034")
        self.assertEqual(grades[0].course_type, "专业必修")

    def test_ignores_empty_scores(self) -> None:
        html = """
        <table id="dataList">
          <tr><th>课程名称</th><th>成绩</th></tr>
          <tr><td>尚未出分课程</td><td></td></tr>
        </table>
        """
        self.assertEqual(parse_grades_html(html), [])

    def test_recognizes_valid_table_before_any_grade_exists(self) -> None:
        html = '<table id="dataList"><tr><th>课程名称</th><th>成绩</th></tr></table>'
        self.assertTrue(has_grade_table(html))
        self.assertEqual(parse_grades_html(html), [])

    def test_rejects_non_njfu_credentials_target(self) -> None:
        with self.assertRaises(GradeSourceError):
            _require_njfu_url("https://example.com/authserver/login")
        with self.assertRaises(GradeSourceError):
            _require_njfu_url("http://jwxt.njfu.edu.cn/authserver/login")
        with self.assertRaises(GradeSourceError):
            _require_njfu_url("https://unapproved.njfu.edu.cn/authserver/login")

    def test_accepts_current_njfu_unified_authentication_host(self) -> None:
        _require_njfu_url("https://uia.njfu.edu.cn/authserver/login")


if __name__ == "__main__":
    unittest.main()
