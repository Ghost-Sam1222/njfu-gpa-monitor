from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import AsyncMock, patch

from grade_source import GradeAuthenticationError
from verify_source import main


class VerifySourceTests(unittest.TestCase):
    def test_ready_and_empty_are_valid_without_logging_grades(self):
        environment = {"JW_USERNAME": "synthetic-user", "JW_PASSWORD": "synthetic-password", "JW_SEMESTER": "2026-2027-1"}
        for grades in ([], ["private grade must not be printed"]):
            with self.subTest(grades_present=bool(grades)), patch.dict("os.environ", environment, clear=True), patch(
                "verify_source.fetch_grades", new=AsyncMock(return_value=grades),
            ), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 0)
            self.assertNotIn("private grade", output.getvalue())
            self.assertNotIn("synthetic-password", output.getvalue())

    def test_login_failure_is_sanitized(self):
        environment = {"JW_COOKIE": "private-cookie", "JW_SEMESTER": "2026-2027-1"}
        with patch.dict("os.environ", environment, clear=True), patch(
            "verify_source.fetch_grades", new=AsyncMock(side_effect=GradeAuthenticationError("private response")),
        ), redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main(), 1)
        self.assertNotIn("private", output.getvalue())

    def test_missing_credentials_does_not_query_school(self):
        with patch.dict("os.environ", {"JW_SEMESTER": "2026-2027-1"}, clear=True), patch(
            "verify_source.fetch_grades", new=AsyncMock(),
        ) as fetch, redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 1)
        fetch.assert_not_awaited()
