from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from term_summary import inspect_term_summary, main


NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
SEMESTER = "2026-2027-1"


def summary(**updates):
    payload = {
        "schema_version": 1,
        "generated_at": NOW.isoformat(),
        "semester": SEMESTER,
        "first_monday": "2026-09-07",
        "last_class_date": "2027-01-08",
        "last_class_date_basis": "latest_generated_course_event",
        "term_source": "school_reported",
        "timetable_source": "school_web",
        "confidence": {"term": "reported", "last_class_date": "derived"},
        "has_manual_adjustments": False,
    }
    return {**payload, **updates}


class TermSummaryTests(unittest.TestCase):
    def inspect(self, payload):
        return inspect_term_summary(payload, SEMESTER, now=NOW)

    def test_school_summary_is_reference_not_exam_deadline(self):
        result = self.inspect(summary())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["last_class_date"], "2027-01-08")
        self.assertNotIn("suggested_monitor_until", result)
        self.assertNotIn("CHECK_START_DATE", result)
        self.assertNotIn("MONITOR_UNTIL", result)

    def test_manual_term_and_adjustments_are_preserved(self):
        result = self.inspect(summary(
            term_source="manual",
            timetable_source="school_app_api",
            confidence={"term": "configured", "last_class_date": "derived"},
            has_manual_adjustments=True,
        ))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["term_source"], "manual")
        self.assertTrue(result["has_manual_adjustments"])

    def test_missing_summary_and_missing_class_date_are_distinct(self):
        self.assertEqual(self.inspect(None)["status"], "missing")
        result = self.inspect(summary(last_class_date=None))
        self.assertEqual(result["status"], "ready")
        self.assertIsNone(result["last_class_date"])

    def test_rejects_unknown_versions_and_boolean_version(self):
        self.assertEqual(self.inspect(summary(schema_version=2))["status"], "unsupported_version")
        self.assertEqual(self.inspect(summary(schema_version=True))["status"], "invalid")

    def test_rejects_mismatched_semester(self):
        self.assertEqual(self.inspect(summary(semester="2025-2026-2"))["status"], "semester_mismatch")

    def test_rejects_fixture_unknown_and_malformed_sources(self):
        for source in ("fixture", "unknown", [], {}):
            with self.subTest(source=source):
                result = self.inspect(summary(timetable_source=source))
                self.assertEqual(result["status"], "untrusted_source")
                self.assertNotIn("last_class_date", result)

    def test_rejects_inconsistent_confidence_and_date_basis(self):
        for updates in (
            {"confidence": {"term": "configured", "last_class_date": "derived"}},
            {"last_class_date_basis": "last_exam"},
            {"has_manual_adjustments": "false"},
        ):
            with self.subTest(updates=updates):
                self.assertEqual(self.inspect(summary(**updates))["status"], "untrusted_source")

    def test_freshness_boundary_and_future_timestamp(self):
        for age, status in (
            (timedelta(days=14), "ready"),
            (timedelta(days=14, seconds=1), "stale"),
            (timedelta(seconds=-1), "future_timestamp"),
        ):
            with self.subTest(age=age):
                self.assertEqual(self.inspect(summary(generated_at=(NOW-age).isoformat()))["status"], status)

    def test_rejects_invalid_dates_timezone_and_ranges(self):
        for updates in (
            {"generated_at": "2026-10-26T12:00:00"},
            {"generated_at": "2026-10-26T12:00:00+08:00"},
            {"first_monday": "2026-09-08"},
            {"last_class_date": "2026-08-01"},
            {"last_class_date": "not a date"},
        ):
            with self.subTest(updates=updates):
                self.assertEqual(self.inspect(summary(**updates))["status"], "invalid")

    def test_unknown_fields_never_echo_private_content(self):
        result = self.inspect(summary(private_data="secret course or credential"))
        self.assertNotIn("secret course or credential", json.dumps(result))

    def test_cli_uses_explicit_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "term-summary.json"
            path.write_text(json.dumps(summary(generated_at=datetime.now(timezone.utc).isoformat())))
            output = io.StringIO()
            with patch("sys.argv", ["term_summary.py", str(path), "--semester", SEMESTER]), redirect_stdout(output):
                self.assertEqual(main(), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ready")


if __name__ == "__main__":
    unittest.main()
