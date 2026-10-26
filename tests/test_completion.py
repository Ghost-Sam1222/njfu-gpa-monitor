from __future__ import annotations

import os
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from completion import cached_completion, completion_key
from state import MonitorState, save_state


class CompletionTests(unittest.TestCase):
    def policy(self, **updates):
        return completion_key(**{
            "semester": "2026-2027-1", "mode": "names", "count": 0,
            "names": ("合成课程",), "until": "2027-02-10", "channels": ("bark",),
            "final_report": True, "salt": "x" * 32, **updates,
        })

    def test_key_is_salted_and_does_not_contain_names(self):
        self.assertEqual(len(self.policy()), 64)
        self.assertNotIn("合成课程", self.policy())
        self.assertNotEqual(self.policy(), self.policy(salt="y" * 32))

    def test_changed_targets_deadline_semester_or_channels_change_key(self):
        for update in (
            {"names": ("另一课程",)}, {"until": "2027-02-11"},
            {"semester": "2026-2027-2"}, {"channels": ("bark", "email")},
        ):
            with self.subTest(update=update):
                self.assertNotEqual(self.policy(), self.policy(**update))

    def test_cache_only_stops_matching_successful_completion(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            environment = {
                "JW_SEMESTER": "2026-2027-1", "GRADE_STATE_SALT": "x" * 32,
                "COMPLETION_MODE": "names", "EXPECTED_COURSE_NAMES": "合成课程",
                "MONITOR_UNTIL": "2027-02-10", "COMPLETION_CHANNELS": "bark",
                "GRADE_STATE_PATH": str(path),
            }
            state = MonitorState("2026-2027-1", initialized=True, complete=True, completion_key=self.policy())
            with patch.dict(os.environ, environment, clear=True):
                save_state(path, state)
                self.assertTrue(cached_completion())
                save_state(path, replace(state, complete=False))
                self.assertFalse(cached_completion())
                save_state(path, replace(state, completion_key=""))
                self.assertFalse(cached_completion())
                save_state(path, state)
                with patch.dict(os.environ, {"EXPECTED_COURSE_NAMES": "新增课程"}):
                    self.assertFalse(cached_completion())

    def test_missing_state_and_missing_salt_never_stop(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(cached_completion())
