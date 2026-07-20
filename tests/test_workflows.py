from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowPolicyTests(unittest.TestCase):
    def test_disabled_monitor_skips_before_required_configuration(self) -> None:
        workflow = (ROOT / ".github/workflows/check-grades.yml").read_text(encoding="utf-8")
        preflight = workflow.split("- name: Preflight", 1)[1].split("- name: Set up Python", 1)[0]
        self.assertLess(
            preflight.index('if [ "$MONITOR_ENABLED" != "true" ]'),
            preflight.index('if [ -z "$JW_SEMESTER" ]'),
        )

    def test_upstream_code_updates_are_manual_only(self) -> None:
        workflow = (ROOT / ".github/workflows/sync-upstream.yml").read_text(encoding="utf-8")
        trigger = workflow.split("on:", 1)[1].split("concurrency:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertNotIn("schedule:", trigger)


if __name__ == "__main__":
    unittest.main()
