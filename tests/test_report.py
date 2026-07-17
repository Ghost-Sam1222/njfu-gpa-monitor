from __future__ import annotations

import unittest

from models import Grade
from report import mask_student_id, render_transcript, weighted_average


def grade(name: str, score: str, credit: str, gpa: str) -> Grade:
    return Grade("2025-2026-2", "CODE", name, score, credit, gpa, "必修")


class ReportTests(unittest.TestCase):
    def test_weighted_averages(self) -> None:
        grades = [grade("A", "80", "1", "3"), grade("B", "100", "3", "5")]
        self.assertAlmostEqual(weighted_average(grades, "score") or 0, 95)
        self.assertAlmostEqual(weighted_average(grades, "gpa") or 0, 4.5)

    def test_report_escapes_course_content(self) -> None:
        html = render_transcript([grade("<script>alert(1)</script>", "优秀", "1", "")], "2025-2026-2", "2400000000")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("2400****000", html)

    def test_masks_short_student_id(self) -> None:
        self.assertEqual(mask_student_id("123"), "未显示")


if __name__ == "__main__":
    unittest.main()
