from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from state import MonitorState, load_state, save_state


class StateTests(unittest.TestCase):
    def test_zero_grade_baseline_stays_initialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, MonitorState(semester="2025-2026-2", initialized=True))
            restored = load_state(path, "2025-2026-2")
            self.assertTrue(restored.initialized)
            self.assertEqual(restored.observed_hashes, set())

    def test_state_isolated_by_semester(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, MonitorState(semester="2025-2026-2", initialized=True, complete=True))
            restored = load_state(path, "2026-2027-1")
            self.assertFalse(restored.initialized)
            self.assertFalse(restored.complete)

    def test_channel_delivery_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = MonitorState(semester="2025-2026-2", initialized=True)
            state.delivered("bark").add("hash-a")
            save_state(path, state)
            self.assertEqual(load_state(path, state.semester).delivered("bark"), {"hash-a"})

    def test_failure_counter_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = MonitorState("2026-2027-1", consecutive_failures=3)
            save_state(path, state)
            self.assertEqual(load_state(path, state.semester).consecutive_failures, 3)


if __name__ == "__main__":
    unittest.main()
