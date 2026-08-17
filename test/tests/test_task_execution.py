"""End-to-end task-execution tests (Phase 29) — temp vaults, no real AI calls.

Covers the real Orchestrator dispatch path end-to-end with a mock agent:
successful execution + Agent Report persistence, failed execution, repeated
execution guard, dry-run non-destructiveness, per-task locking, and the
secret-free guarantee for persisted execution data. The real ``opencode``
binary is never invoked (``--mock`` or a stubbed runner).
"""

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import orchestrator as orch

TASK_TEXT = """---
type: task
status: planned
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


class TaskExecutionTestCase(unittest.TestCase):
    """Temp vault + a ready-to-run task node + linked context nodes."""

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

    def _ready(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")


class TestSuccessfulExecution(TaskExecutionTestCase):
    def test_mock_dispatch_completes_and_persists_report(self):
        self._ready()
        out = StringIO()
        with redirect_stdout(out):
            code = orch.cmd_dispatch(self.vault, "Task_Demo", yes=True, mock=True)
        self.assertEqual(code, 0)
        fields, body, _raw = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "completed")
        # Both the execution log and the structured Agent Report are persisted.
        self.assertIn("## Execution Log", body)
        self.assertIn("## Agent Report", body)
        report = orch._parse_agent_report(body)
        self.assertTrue(report["actions performed"])
        self.assertIn("pass", report["test results"].lower())
        log = orch._read_execution_log(body)
        self.assertTrue(any("completed" in entry for entry in log))

    def test_persisted_data_contains_no_credentials(self):
        self._ready()
        with redirect_stdout(StringIO()):
            orch.cmd_dispatch(self.vault, "Task_Demo", yes=True, mock=True)
        raw = self.task_path.read_text(encoding="utf-8").lower()
        for banned in ("api_key", "apikey", "secret", "password",
                       "authorization", "bearer", "token="):
            self.assertNotIn(banned, raw)

    def test_repeated_dispatch_refused_after_completion(self):
        self._ready()
        with redirect_stdout(StringIO()):
            orch.cmd_dispatch(self.vault, "Task_Demo", yes=True, mock=True)
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo", yes=True, mock=True)


class TestFailedExecution(TaskExecutionTestCase):
    def test_failed_run_writes_failed_status_without_report(self):
        self._ready()
        # The agent process "fails to start" — no output, no report.
        with mock.patch.object(orch, "_run_command_capture", return_value=None):
            code = orch.cmd_dispatch(self.vault, "Task_Demo", yes=True)
        self.assertEqual(code, 1)
        fields, body, _raw = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "failed")
        self.assertIn("## Execution Log", body)
        # No fabricated Agent Report — the failure stays inspectable but honest.
        self.assertNotIn("## Agent Report", body)
        log = orch._read_execution_log(body)
        self.assertTrue(any("failed" in entry for entry in log))


class TestDryRunSafety(TaskExecutionTestCase):
    def test_dry_run_does_not_execute_or_write(self):
        self._ready()
        before = self.task_path.read_text(encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = orch.cmd_dispatch(self.vault, "Task_Demo")  # no --yes
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertEqual(self.task_path.read_text(encoding="utf-8"), before)
        self.assertNotIn("## Execution Log", before)

    def test_dry_run_requires_ready_status(self):
        # A planned task cannot even dry-run: the ready-gate is the first check.
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo")


class TestLocking(TaskExecutionTestCase):
    def test_concurrent_dispatch_refused_when_lock_held(self):
        self._ready()
        lock = orch._acquire_lock(self.vault, "Task_Demo")
        self.assertIsNotNone(lock)
        try:
            with self.assertRaises(orch.VaultError):
                orch.cmd_dispatch(self.vault, "Task_Demo", yes=True, mock=True)
        finally:
            orch._release_lock(lock)

    def test_lock_reacquirable_after_release(self):
        lock = orch._acquire_lock(self.vault, "Task_Demo")
        self.assertIsNotNone(lock)
        orch._release_lock(lock)
        again = orch._acquire_lock(self.vault, "Task_Demo")
        self.assertIsNotNone(again)
        orch._release_lock(again)

    def test_lock_is_scoped_to_vault(self):
        # The lock lives under the vault's own _logs/locks, never the repo root.
        lock = orch._acquire_lock(self.vault, "Task_Demo")
        self.assertIsNotNone(lock)
        try:
            self.assertTrue(lock.is_relative_to(self.vault))
            expected_dir = self.vault / "_logs" / "locks"
            self.assertEqual(lock.parent, expected_dir)
            self.assertNotEqual(lock.parent, orch._REPO_ROOT / "_logs" / "locks")
        finally:
            orch._release_lock(lock)

    def test_two_vaults_lock_same_task_name_independently(self):
        # Regression: the lock key used to be the task name alone in a global
        # path, so two independent temp vaults collided. Each vault must be
        # able to hold a lock for the same task name at the same time.
        second_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(second_tmp.cleanup)
        other_vault = Path(second_tmp.name) / "vault"
        (other_vault / "03-Tasks").mkdir(parents=True)
        lock_a = orch._acquire_lock(self.vault, "Task_Demo")
        lock_b = orch._acquire_lock(other_vault, "Task_Demo")
        self.assertIsNotNone(lock_a)
        self.assertIsNotNone(lock_b)
        self.assertNotEqual(lock_a, lock_b)
        orch._release_lock(lock_a)
        orch._release_lock(lock_b)

    def test_lock_path_is_vault_scoped_and_stable(self):
        p1 = orch._lock_path(self.vault, "Task_Demo")
        p2 = orch._lock_path(self.vault, "Task_Demo")
        self.assertEqual(p1, p2)
        self.assertTrue(p1.is_relative_to(self.vault))

    def test_filesystem_error_raises_vault_error_not_held_lock(self):
        # A lock path that cannot be created (parent is a file, not a dir)
        # must raise VaultError, never be reported as "lock held".
        locks_dir = self.vault / "_logs" / "locks"
        locks_dir.parent.mkdir(parents=True, exist_ok=True)
        locks_dir.write_text("i am a file", encoding="utf-8")
        with self.assertRaises(orch.VaultError):
            orch._acquire_lock(self.vault, "Task_Demo")


if __name__ == "__main__":
    unittest.main()
