from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import ConfigError, load_settings


def base_environment() -> dict[str, str]:
    return {
        "JW_USERNAME": "student",
        "JW_PASSWORD": "password",
        "GRADE_STATE_SALT": "x" * 32,
        "BARK_DEVICE_KEY": "device-key",
        "JW_SEMESTER": "2026-2027-1",
        "MONITOR_ENABLED": "true",
        "MONITOR_UNTIL": "2027-01-31",
        "COMPLETION_MODE": "count",
        "EXPECTED_GRADE_COUNT": "8",
    }


class ConfigTests(unittest.TestCase):
    def test_enabled_monitor_requires_stop_date(self) -> None:
        environment = base_environment()
        environment.pop("MONITOR_UNTIL")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ConfigError, "MONITOR_UNTIL"):
                load_settings()

    def test_count_mode_requires_positive_expected_count(self) -> None:
        environment = base_environment()
        environment["EXPECTED_GRADE_COUNT"] = "0"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ConfigError, "at least 1"):
                load_settings()

    def test_legacy_count_zero_uses_existing_course_names(self) -> None:
        environment = base_environment()
        environment["EXPECTED_GRADE_COUNT"] = "0"
        environment["EXPECTED_COURSE_NAMES"] = "课程A,课程B"
        with patch.dict(os.environ, environment, clear=True):
            configured = load_settings()
        self.assertEqual(configured.completion_mode, "names")
        self.assertEqual(configured.expected_course_names, ("课程A", "课程B"))

    def test_unset_completion_mode_defaults_to_stop_date(self) -> None:
        environment = base_environment()
        environment.pop("COMPLETION_MODE")
        environment["EXPECTED_GRADE_COUNT"] = "0"
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(load_settings().completion_mode, "date")

    def test_date_mode_does_not_require_a_completion_count(self) -> None:
        environment = base_environment()
        environment["COMPLETION_MODE"] = "date"
        environment["EXPECTED_GRADE_COUNT"] = "0"
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(load_settings().completion_mode, "date")


if __name__ == "__main__":
    unittest.main()
