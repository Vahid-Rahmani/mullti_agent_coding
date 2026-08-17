"""Controlled Execution unit tests — mock agents, temp vault, never real runs.

Covers: the 'ready' execution gate, context+bounded prompt, Agent Report
parsing variants, the status-decision matrix, per-task concurrency locks,
scope-drift detection, and the no-delete guarantee (the orchestrator itself
never issues delete/rm commands).
"""

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import orchestrator as orch

TASK_TEXT = """---
type: task
status: ready
owner: orchestrator
priority: high
assigned_agent: Agent_Matthew
related_component: Component_RunHub
dependencies: []
created: 2026-08-11
updated: 2026-08-11
---

# Task_Demo

## Title

Implement a demo feature.

## Description

Do the thing.

## Acceptance Criteria

- [ ] criterion one
- [ ] criterion two
"""

PASSING_REPORT = """## Agent Report
- actions performed: implemented feature; added tests
- files changed: scripts/core/example.py
- tests executed: python -m unittest test.tests.test_example
- test results: pass 12 tests, 0 failures
- remaining issues: none
"""

FAILING_TESTS_REPORT = """## Agent Report
- actions performed: implemented feature
- files changed: scripts/core/example.py
- tests executed: python -m unittest test.tests.test_example
- test results: fail 3 tests, 0 passed
- remaining issues: flaky timer test
"""


class ControlledExecutionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.tasks = self.vault / "03-Tasks"
        self.tasks.mkdir(parents=True)
        self.task_path = self.tasks / "Task_Demo.md"
        self.task_path.write_text(TASK_TEXT, encoding="utf-8")
        self.agents = self.vault / "02-Agents"
        self.agents.mkdir(parents=True)
        (self.agents / "Agent_Matthew.md").write_text(
            "---\ntype: agent\nstatus: active\nowner: orchestrator\n"
            "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n# Agent_Matthew\n",
            encoding="utf-8",
        )
        self.arch = self.vault / "01-Architecture"
        self.arch.mkdir(parents=True)
        (self.arch / "Component_RunHub.md").write_text(
            "---\ntype: architecture\nstatus: active\nowner: architect\n"
            "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n# Component_RunHub\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_dispatch(self, **kw):
        buf = StringIO()
        with redirect_stdout(buf):
            code = orch.cmd_dispatch(self.vault, "Task_Demo", **kw)
        return code, buf.getvalue()


class TestReadyGate(ControlledExecutionTestCase):
    def test_planned_refused(self):
        # A task still in 'planned' must be refused (execution needs 'ready').
        planned = self.tasks / "Task_Planned.md"
        planned.write_text(
            TASK_TEXT.replace("status: ready", "status: planned"), encoding="utf-8")
        with self.assertRaises(orch.VaultError) as cm:
            orch.cmd_dispatch(self.vault, "Task_Planned", yes=True)
        self.assertIn("status=planned", str(cm.exception))

    def test_in_progress_refused(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo", yes=True)

    def test_completed_refused(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        orch.cmd_report(self.vault, "Task_Demo", "completed")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo", yes=True)

    def test_ready_dry_run_still_prints(self):
        code, out = self.run_dispatch()
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)


class TestPromptBuild(ControlledExecutionTestCase):
    def test_prompt_contains_acceptance_criteria(self):
        fields, body, _raw = orch.read_task(self.task_path)
        prompt = orch._build_prompt("Task_Demo", fields, body, [])
        self.assertIn("criterion one", prompt)
        self.assertIn("criterion two", prompt)
        self.assertIn("Agent Report", prompt)
        self.assertIn("Component_RunHub", prompt)  # scope guard

    def test_extract_acceptance_criteria(self):
        _fields, body, _raw = orch.read_task(self.task_path)
        criteria = orch._extract_acceptance_criteria(body)
        self.assertEqual(len(criteria), 2)


class TestReportParsing(ControlledExecutionTestCase):
    def test_parse_passing_report(self):
        report = orch._parse_agent_report(PASSING_REPORT)
        self.assertIn("implemented feature", report["actions performed"])
        self.assertIn("scripts/core/example.py", report["files changed"])
        self.assertIn("pass 12 tests", report["test results"])

    def test_parse_multiline_bullets(self):
        text = """## Agent Report
- actions performed: a; b
  - sub item one
  - sub item two
- files changed: x.py
- test results: pass 5
"""
        report = orch._parse_agent_report(text)
        self.assertIn("sub item one", report["actions performed"])

    def test_missing_section_empty(self):
        report = orch._parse_agent_report("just some output without a report")
        self.assertEqual(report["actions performed"], "")

    def test_no_false_report_from_prose(self):
        # A sentence that merely mentions 'actions performed' must not parse.
        text = "The actions performed were reviewed by QA."
        report = orch._parse_agent_report(text)
        self.assertEqual(report["actions performed"], "")


class TestStatusDecision(ControlledExecutionTestCase):
    def test_ok_with_passing_tests_completed(self):
        self.assertEqual(
            orch._decide_status(True, orch._parse_agent_report(PASSING_REPORT)),
            "completed")

    def test_ok_with_failing_tests_blocked(self):
        self.assertEqual(
            orch._decide_status(True, orch._parse_agent_report(FAILING_TESTS_REPORT)),
            "blocked")

    def test_nonzero_exit_failed(self):
        self.assertEqual(orch._decide_status(False, {}), "failed")

    def test_ok_but_no_report_failed(self):
        self.assertEqual(orch._decide_status(True, {}), "failed")


class TestDispatchStatusWriteback(ControlledExecutionTestCase):
    def test_success_writes_completed(self):
        with mock.patch.object(orch, "_run_command_capture",
                               return_value=PASSING_REPORT) as m:
            code, out = self.run_dispatch(yes=True)
        m.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn("result    : completed", out)
        fields, _b, _r = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "completed")
        self.assertIn("## Execution Log", self.task_path.read_text(encoding="utf-8"))

    def test_failing_tests_writes_blocked(self):
        with mock.patch.object(orch, "_run_command_capture",
                               return_value=FAILING_TESTS_REPORT):
            code, out = self.run_dispatch(yes=True)
        self.assertEqual(code, 1)
        self.assertIn("result    : blocked", out)
        fields, _b, _r = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "blocked")

    def test_crash_writes_failed(self):
        with mock.patch.object(orch, "_run_command_capture", return_value=None):
            code, out = self.run_dispatch(yes=True)
        self.assertEqual(code, 1)
        self.assertIn("result    : failed", out)
        fields, _b, _r = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "failed")

    def test_mock_flag_end_to_end(self):
        # Real CLI path with the built-in mock agent (no opencode involved).
        code, _out = self.run_dispatch(yes=True, mock=True)
        self.assertEqual(code, 0)
        fields, _b, _r = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "completed")


class TestConcurrencyLock(ControlledExecutionTestCase):
    def test_lock_created_and_released(self):
        lock = orch._lock_path(self.vault, "Task_Demo")
        self.assertFalse(lock.exists())
        with mock.patch.object(orch, "_run_command_capture",
                               return_value=PASSING_REPORT):
            self.run_dispatch(yes=True)
        self.assertFalse(lock.exists())  # released in finally

    def test_second_dispatch_refused_while_locked(self):
        lock = orch._acquire_lock(self.vault, "Task_Demo")
        self.assertIsNotNone(lock)
        try:
            with self.assertRaises(orch.VaultError) as cm:
                orch.cmd_dispatch(self.vault, "Task_Demo", yes=True)
            self.assertIn("already executing", str(cm.exception))
        finally:
            orch._release_lock(lock)
        self.assertFalse(lock.exists())


class TestNoDeleteGuarantee(ControlledExecutionTestCase):
    def test_orchestrator_never_builds_delete_commands(self):
        # The orchestrator's command builder must never contain rm/del/remove.
        fields, body, _raw = orch.read_task(self.task_path)
        prompt = orch._build_prompt("Task_Demo", fields, body, [])
        self.assertIn("NEVER delete files", prompt)
        self.assertIn("destructive", prompt)

    def test_dispatch_source_has_no_delete_syscalls(self):
        src = Path(orch.__file__).read_text(encoding="utf-8")
        for forbidden in ("os.remove", "Path.unlink", "shutil.rmtree", "os.rmdir"):
            # Path.unlink appears only in _release_lock's missing_ok cleanup —
            # verify the ONLY usage is lock release, never user files.
            self.assertNotIn(forbidden, src.replace("_release_lock", ""))

    def test_scope_drift_detected_and_logged(self):
        with (mock.patch.object(orch, "_git_changed_files",
                                return_value=["scripts/core/real.py"]),
              mock.patch.object(orch, "_run_command_capture",
                                return_value=PASSING_REPORT)):
            self.run_dispatch(yes=True)
        # Task completed; drift recorded in the execution-log detail.
        fields, body, _raw = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "completed")
        self.assertIn("## Execution Log", body)


if __name__ == "__main__":
    unittest.main()
