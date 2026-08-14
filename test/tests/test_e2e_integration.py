"""End-to-end integration tests (Phase 19).

Drives the REAL modules — orchestrator, context resolver, vault bridge,
knowledge sync, dashboard generator, health check — through the full workflow:

    Obsidian Task -> Orchestrator -> Context Resolver -> (mock) Agent
    -> Result -> Obsidian Task Update -> Dashboard

All scenarios run against TEMP vaults with a MOCK agent (never real opencode,
never production data). Verification gates:
  * no unauthorized file changes (scripts/, test/, real vault untouched)
  * exact task-state transitions
  * execution logs written (node Execution Log + orchestrator.log)
  * vault sync artifacts (backup + change-log row) for every write
  * graph integrity preserved (health check introduces no NEW errors)
  * dashboard reflects the task state after regeneration
  * safe failure / error recovery (never stuck in_progress, locks released)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import generate_dashboard as gd

from scripts.core import change_detector as cd
from scripts.core import health_check as hc
from scripts.core import knowledge_sync as ks
from scripts.core import orchestrator as orch

PASSING_REPORT = """## Agent Report
- actions performed: implemented feature; added tests
- files changed: scripts/core/example.py
- tests executed: python -m unittest test.tests.test_example
- test results: pass 12 tests, 0 failures
- remaining issues: none
"""

FAILING_REPORT = """## Agent Report
- actions performed: implemented feature
- files changed: scripts/core/example.py
- tests executed: python -m unittest test.tests.test_example
- test results: fail 3 tests, 0 passed
- remaining issues: flaky timer test
"""

NODE = ("---\ntype: {t}\nstatus: {s}\nowner: test\ncreated: 2026-08-11\n"
        "updated: 2026-08-11\n---\n\n# {name}\n")

TASK = """---
type: task
status: {status}
owner: orchestrator
priority: high
assigned_agent: Agent_Matthew
related_component: Component_RunHub
dependencies: []
created: 2026-08-11
updated: 2026-08-11
---

# {name}

## Title

{title}

## Description

{desc}

## Acceptance Criteria

- [ ] criterion one
- [ ] criterion two
"""


class E2ETestCase(unittest.TestCase):
    """Temp vault with the full minimal graph + workspace file manifest."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        for sec in hc.SECTIONS:
            (self.vault / sec).mkdir(parents=True)
        self.write("00-System/System_Core.md",
                   "---\ntype: system\nstatus: active\nowner: all\n"
                   "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n"
                   "[[Architecture_Home]] [[Agents_Home]] [[Tasks_Home]] "
                   "[[Decisions_Home]] [[Documentation_Home]] [[Testing_Home]]\n")
        self.write("01-Architecture/Architecture_Home.md",
                   NODE.format(t="architecture", s="active", name="Architecture_Home"))
        self.write("01-Architecture/System_Architecture.md",
                   NODE.format(t="architecture", s="active", name="System_Architecture"))
        self.write("01-Architecture/Component_RunHub.md",
                   NODE.format(t="architecture", s="active", name="Component_RunHub"))
        self.write("02-Agents/Agents_Home.md",
                   "---\ntype: agent\nstatus: active\nowner: all\n"
                   "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n[[Agent_Matthew]]\n")
        self.write("02-Agents/Agent_Matthew.md",
                   NODE.format(t="agent", s="active", name="Agent_Matthew"))
        self.write("03-Tasks/Tasks_Home.md",
                   NODE.format(t="task", s="active", name="Tasks_Home"))
        self.write("03-Tasks/Task_Backlog.md",
                   NODE.format(t="task", s="active", name="Task_Backlog"))
        self.write("04-Decisions/Decisions_Home.md",
                   NODE.format(t="decision", s="active", name="Decisions_Home"))
        self.write("05-Documentation/Documentation_Home.md",
                   NODE.format(t="documentation", s="active", name="Documentation_Home"))
        self.write("06-Testing/Testing_Home.md",
                   NODE.format(t="test", s="active", name="Testing_Home"))
        self.write("06-Testing/Test_Report_Suite.md",
                   NODE.format(t="test", s="active", name="Test_Report_Suite"))
        # Workspace manifest: files that must NEVER change during a scenario.
        # Covers the real vault too, so every scenario proves the production
        # vault is untouched (all writes target the temp vault).
        self.workspace = {p for p in (REPO_ROOT / "scripts").rglob("*")
                          if p.is_file() and "_logs" not in p.parts
                          and "__pycache__" not in p.parts}
        self.workspace |= {p for p in (REPO_ROOT / "test").rglob("*")
                           if p.is_file() and "__pycache__" not in p.parts}
        self.workspace |= {p for p in (REPO_ROOT / "obsidian_vault").rglob("*.md")
                           if p.is_file()}
        self.before_manifest = self._manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, content: str) -> None:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def task_path(self, name: str) -> Path:
        return self.vault / "03-Tasks" / f"{name}.md"

    def add_task(self, name: str, status: str = "ready",
                 title: str = "Demo", desc: str = "Do the thing.") -> Path:
        self.write(f"03-Tasks/{name}.md",
                   TASK.format(status=status, name=name, title=title, desc=desc))
        return self.task_path(name)

    def _manifest(self) -> dict[str, str]:
        """sha256 of every workspace file — used to prove nothing changed."""
        import hashlib
        out: dict[str, str] = {}
        for p in sorted(self.workspace):
            try:
                out[str(p.relative_to(REPO_ROOT)).replace(os.sep, "/")] = \
                    hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                pass
        return out

    def assert_workspace_untouched(self) -> None:
        after = self._manifest()
        changed = {k for k in self.before_manifest
                   if self.before_manifest[k] != after.get(k)}
        self.assertEqual(changed, set(),
                         f"unauthorized workspace change: {changed}")

    def status_of(self, name: str) -> str:
        fields, _b, _r = orch.read_task(self.task_path(name))
        return fields["status"]

    def body_of(self, name: str) -> str:
        _f, body, _r = orch.read_task(self.task_path(name))
        return body

    def run_dispatch(self, name: str, report: str | None = PASSING_REPORT,
                     mock_agent: bool = False):
        if mock_agent:
            return orch.cmd_dispatch(self.vault, name, yes=True, mock=True)
        with mock.patch.object(orch, "_run_command_capture", return_value=report):
            return orch.cmd_dispatch(self.vault, name, yes=True)

    def graph_errors_after(self) -> list[str]:
        rep = hc.run_health(self.vault)
        return [i.message for i in rep.errors]


class TestSuccessfulTask(E2ETestCase):
    """The full happy-path workflow."""

    def test_full_workflow(self):
        # Snapshot shared _logs/ state first — the backup/change-log assertions
        # must prove THIS run wrote them, not a stale row from an earlier run.
        bdir = REPO_ROOT / "_logs" / "vault_backups"
        before_backups = {p.name for p in bdir.glob("Task_Ok-*.bak")} \
            if bdir.is_dir() else set()
        clog_path = REPO_ROOT / "_logs" / "vault_changes.jsonl"
        before_rows = (clog_path.read_text(encoding="utf-8").splitlines()
                       if clog_path.is_file() else [])
        self.add_task("Task_Ok")
        # 1. Ready-gate passes, context resolves, agent runs, status written.
        code = self.run_dispatch("Task_Ok", mock_agent=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.status_of("Task_Ok"), "completed")
        # 2. Execution log appended to the node.
        self.assertIn("## Execution Log", self.body_of("Task_Ok"))
        # 3. Vault sync artifacts created by THIS run: backup + change-log row.
        new_backups = [p for p in bdir.glob("Task_Ok-*.bak")
                       if p.name not in before_backups]
        self.assertGreaterEqual(len(new_backups), 1)
        new_rows = [line for line in clog_path.read_text(encoding="utf-8")
                    .splitlines() if line not in before_rows]
        self.assertTrue(any("Task_Ok" in r for r in new_rows),
                        f"no fresh change-log row for Task_Ok in {new_rows}")
        # 4. Lock released.
        self.assertFalse(orch._lock_path("Task_Ok").exists())
        # 5. Graph integrity: no NEW errors introduced on the temp vault.
        self.assertEqual(self.graph_errors_after(), [])
        # 6. Dashboard reflects the completed task.
        gd.write_dashboard(self.vault, gd.render_dashboard(self.vault))
        dash = (self.vault / "Dashboard.md").read_text(encoding="utf-8")
        self.assertIn("[[Task_Ok]]", dash)
        # 7. Workspace untouched.
        self.assert_workspace_untouched()


class TestFailedTask(E2ETestCase):
    def test_crash_writes_failed_and_recovers(self):
        self.add_task("Task_Bad")
        with mock.patch.object(orch, "_run_command_capture", return_value=None):
            code = orch.cmd_dispatch(self.vault, "Task_Bad", yes=True)
        self.assertEqual(code, 1)
        self.assertEqual(self.status_of("Task_Bad"), "failed")
        self.assertIn("## Execution Log", self.body_of("Task_Bad"))
        # Never stuck in_progress, lock released.
        self.assertFalse(orch._lock_path("Task_Bad").exists())
        self.assertEqual(self.graph_errors_after(), [])
        self.assert_workspace_untouched()


class TestBlockedTask(E2ETestCase):
    def test_failing_tests_write_blocked(self):
        self.add_task("Task_Blocked")
        code = self.run_dispatch("Task_Blocked", report=FAILING_REPORT)
        self.assertEqual(code, 1)
        self.assertEqual(self.status_of("Task_Blocked"), "blocked")
        self.assert_workspace_untouched()


class TestMalformedTask(E2ETestCase):
    def test_malformed_frontmatter_refused_safely(self):
        original = "# no frontmatter at all\n"
        self.write("03-Tasks/Task_Malformed.md", original)
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Malformed", yes=True)
        # Node byte-identical, nothing executed.
        self.assertEqual(self.task_path("Task_Malformed").read_text(encoding="utf-8"),
                         original)
        self.assert_workspace_untouched()


class TestMissingAgent(E2ETestCase):
    def test_unknown_agent_refused_before_run(self):
        path = self.add_task("Task_NoAgent")
        path.write_text(path.read_text(encoding="utf-8").replace(
            "assigned_agent: Agent_Matthew", "assigned_agent: Agent_Ghost"),
            encoding="utf-8")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_NoAgent", yes=True)
        self.assertEqual(self.status_of("Task_NoAgent"), "ready")  # unchanged
        self.assert_workspace_untouched()


class TestBrokenWikiLink(E2ETestCase):
    def test_broken_link_surfaces_in_health_check(self):
        self.add_task("Task_Link", desc="See [[Ghost_Node]] for details.")
        self.run_dispatch("Task_Link", mock_agent=True)
        errors = self.graph_errors_after()
        self.assertTrue(any("Ghost_Node" in e for e in errors),
                        f"expected broken-link error, got {errors}")
        self.assert_workspace_untouched()


class TestConflictingDocumentation(E2ETestCase):
    def test_conflict_reported_never_autofixed(self):
        # Component node claims a source file that does not exist.
        self.write("01-Architecture/Component_Phantom.md",
                   NODE.format(t="architecture", s="active", name="Component_Phantom")
                   + "Source files: `scripts/core/phantom.py`\n")
        conflicts = ks.check_conflicts(self.vault)
        self.assertTrue(any("phantom.py" in c for c in conflicts))
        # The component node is NOT modified by the check.
        text = (self.vault / "01-Architecture/Component_Phantom.md").read_text(encoding="utf-8")
        self.assertIn("phantom.py", text)
        self.assert_workspace_untouched()


class TestConcurrentExecution(E2ETestCase):
    def test_second_dispatch_refused_while_locked(self):
        self.add_task("Task_Lock")
        lock = orch._acquire_lock("Task_Lock")
        self.assertIsNotNone(lock)
        try:
            with self.assertRaises(orch.VaultError) as cm:
                orch.cmd_dispatch(self.vault, "Task_Lock", yes=True, mock=True)
            self.assertIn("already executing", str(cm.exception))
        finally:
            orch._release_lock(lock)
        # Task still 'ready' — the concurrent attempt changed nothing.
        self.assertEqual(self.status_of("Task_Lock"), "ready")
        self.assert_workspace_untouched()


class TestChangeDetectionNoExecution(E2ETestCase):
    def test_detection_never_triggers_agents(self):
        # Snapshot the temp vault, mutate a task, detect — must be a pure report.
        before = cd._snapshot_tree(self.vault, include_suffixes={".md"})
        self.add_task("Task_Detect")
        after = cd._snapshot_tree(self.vault, include_suffixes={".md"})
        changes = cd._diff_snap(before, after, cd.classify)
        self.assertTrue(any(c.kind == cd.ChangeKind.CREATED for c in changes))
        # No lock files, no status change, no execution side effects.
        self.assertFalse(any((REPO_ROOT / "_logs/locks").glob("*.lock")))
        self.assert_workspace_untouched()


if __name__ == "__main__":
    unittest.main()
