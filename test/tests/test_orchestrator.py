"""Orchestrator unit tests — uses temp vault fixtures, never the real vault.

Covers: task discovery, frontmatter parsing, status transitions, agent
resolution, context limiting, dry-run vs --yes dispatch, atomic report writes,
malformed-node error handling, and duplicate-execution prevention.
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import opencode_cfg
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


class OrchestratorTestCase(unittest.TestCase):
    """Shared fixture: a temp vault with 03-Tasks/ + a task node + linked nodes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.tasks = self.vault / "03-Tasks"
        self.tasks.mkdir(parents=True)
        self.task_path = self.tasks / "Task_Demo.md"
        self.task_path.write_text(TASK_TEXT, encoding="utf-8")
        # Linked nodes referenced by the task.
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
        # Distractor node that must NOT be read (unrelated).
        self.system = self.vault / "00-System"
        self.system.mkdir(parents=True)
        (self.system / "Vault_Map.md").write_text("unrelated", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()


class TestTaskDiscovery(OrchestratorTestCase):
    def test_lists_only_task_nodes(self):
        tasks = orch.list_tasks(self.vault)
        self.assertEqual([t.name for t in tasks], ["Task_Demo.md"])

    def test_missing_vault_raises(self):
        with self.assertRaises(orch.VaultError):
            orch.validate_vault(Path(self.tmp.name) / "nope")


class TestFrontmatter(OrchestratorTestCase):
    def test_parse_fields(self):
        fields, err = orch.parse_frontmatter(TASK_TEXT)
        self.assertIsNone(err)
        self.assertEqual(fields["status"], "planned")
        self.assertEqual(fields["assigned_agent"], "Agent_Matthew")
        self.assertEqual(fields["related_component"], "Component_RunHub")

    def test_malformed_frontmatter_reported_safely(self):
        bad = "# No frontmatter\njust body\n"
        fields, err = orch.parse_frontmatter(bad)
        self.assertEqual(fields, {})
        self.assertIn("missing frontmatter", err)


class TestReadTask(OrchestratorTestCase):
    def test_read_task_ok(self):
        fields, body, _raw = orch.read_task(self.task_path)
        self.assertEqual(fields["type"], "task")
        self.assertIn("Do the thing.", body)

    def test_missing_node_raises(self):
        with self.assertRaises(orch.VaultError):
            orch.read_task(self.tasks / "Task_Nope.md")


class TestTransitions(OrchestratorTestCase):
    def test_valid_chain(self):
        f = {"status": "planned"}
        for a, b in [("planned", "ready"), ("ready", "in_progress"),
                     ("in_progress", "completed")]:
            orch._transition("t", f, b)
            f["status"] = b

    def test_illegal_transition_raises(self):
        with self.assertRaises(orch.VaultError):
            orch._transition("t", {"status": "planned"}, "completed")

    def test_invalid_status_raises(self):
        with self.assertRaises(orch.VaultError):
            orch._transition("t", {"status": "planned"}, "banana")

    def test_set_status_writes_frontmatter_only(self):
        raw = self.task_path.read_text(encoding="utf-8")
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        after = self.task_path.read_text(encoding="utf-8")
        self.assertIn("status: ready", after)
        self.assertIn("status: planned", raw)  # changed
        # Human body preserved byte-for-byte:
        self.assertIn("## Acceptance Criteria\n\n- [ ] criterion one", after)


class TestAgentResolution(OrchestratorTestCase):
    def test_resolve_known_agent(self):
        fields, _b, _r = orch.read_task(self.task_path)
        resolved = orch.resolve_agent_node(fields)
        self.assertEqual(resolved, ("matthew", opencode_cfg.resolve_model("matthew")))

    def test_resolve_unknown_agent_none(self):
        self.assertIsNone(orch.resolve_agent_node({"assigned_agent": "Agent_Nobody"}))

    def test_resolve_missing_agent_none(self):
        self.assertIsNone(orch.resolve_agent_node({}))


class TestContextLimiting(OrchestratorTestCase):
    def test_context_limited_to_linked_nodes(self):
        fields, body, _raw = orch.read_task(self.task_path)
        ctx = orch.collect_context(self.vault, fields, body)
        stems = {p.stem for p in ctx}
        self.assertIn("Agent_Matthew", stems)
        self.assertIn("Component_RunHub", stems)
        self.assertNotIn("Vault_Map", stems)  # unrelated node never read
        self.assertLessEqual(len(ctx), orch.MAX_CONTEXT_NODES)


class TestDispatch(OrchestratorTestCase):
    def test_dispatch_dry_run_by_default(self):
        # The execution gate requires 'ready'; planned tasks are refused.
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo")
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        out = StringIO()
        with redirect_stdout(out):
            code = orch.cmd_dispatch(self.vault, "Task_Demo")
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", text)
        self.assertIn("--agent matthew --auto", text)
        self.assertIn("-m " + opencode_cfg.resolve_model("matthew"), text)
        # Node untouched by dry-run:
        self.assertIn("status: ready", self.task_path.read_text(encoding="utf-8"))

    def test_dispatch_refuses_duplicate(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo")

    def test_dispatch_without_agent_raises(self):
        path = self.tasks / "Task_Unassigned.md"
        path.write_text(TASK_TEXT.replace("assigned_agent: Agent_Matthew",
                                          "assigned_agent: Agents_Home"),
                        encoding="utf-8")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Unassigned")


class TestReport(OrchestratorTestCase):
    def test_report_appends_execution_log(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        err = StringIO()
        with redirect_stderr(err):
            code = orch.cmd_report(self.vault, "Task_Demo", "failed")
        self.assertEqual(code, 0)
        after = self.task_path.read_text(encoding="utf-8")
        self.assertIn("## Execution Log", after)
        self.assertIn("- ", after)
        self.assertIn("status: failed", after)
        # Human body preserved:
        self.assertIn("## Acceptance Criteria", after)

    def test_report_invalid_outcome_raises(self):
        with self.assertRaises(orch.VaultError):
            orch.cmd_report(self.vault, "Task_Demo", "banana")


class TestAtomicWrite(OrchestratorTestCase):
    def test_atomic_write_roundtrip(self):
        raw = self.task_path.read_text(encoding="utf-8")
        updated = orch._replace_frontmatter(raw, {"status": "ready", "updated": "2026-08-12"})
        orch._atomic_write(self.task_path, updated)
        fields, _b, _r = orch.read_task(self.task_path)
        self.assertEqual(fields["status"], "ready")
        self.assertEqual(fields["updated"], "2026-08-12")
        self.assertIn("Do the thing.", self.task_path.read_text(encoding="utf-8"))


class TestTaskRoleOverride(unittest.TestCase):
    """A task node's optional `role` field is a temporary override."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "roles.json").write_text(json.dumps({
            "roles": {
                "python-developer": {"name": "Python Developer",
                                      "responsibilities": ["Write Python"]},
                "security-engineer": {"name": "Security Engineer",
                                      "rules": ["No secrets"]},
            },
            "assignments": {"matthew": ["python-developer"]},
        }), encoding="utf-8")
        self._orig_root = orch._REPO_ROOT
        orch._REPO_ROOT = self.root

    def tearDown(self):
        orch._REPO_ROOT = self._orig_root
        self.tmp.cleanup()

    def _fields(self, role=None):
        fields = {"assigned_agent": "Agent_Matthew"}
        if role is not None:
            fields["role"] = role
        return fields

    def test_override_wins_over_assigned_roles(self):
        ctx = orch.task_role_context("matthew", self._fields("security-engineer"))
        self.assertIn("### Security Engineer", ctx)
        self.assertNotIn("### Python Developer", ctx)

    def test_no_override_uses_assigned_roles(self):
        ctx = orch.task_role_context("matthew", self._fields())
        self.assertIn("### Python Developer", ctx)

    def test_empty_override_falls_back_to_assigned(self):
        ctx = orch.task_role_context("matthew", self._fields(""))
        self.assertIn("### Python Developer", ctx)

    def test_unknown_override_raises(self):
        with self.assertRaises(orch.VaultError):
            orch.task_role_context("matthew", self._fields("nope"))

    def test_override_never_mutates_roles_json(self):
        before = (self.root / "roles.json").read_text(encoding="utf-8")
        orch.task_role_context("matthew", self._fields("security-engineer"))
        after = (self.root / "roles.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_frontmatter_adds_new_role_field(self):
        raw = TASK_TEXT
        updated = orch._replace_frontmatter(raw, {"role": "security-engineer"})
        self.assertIn("role: security-engineer", updated)
        self.assertIn("## Acceptance Criteria", updated)


class TestCli(unittest.TestCase):
    def test_unknown_command_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            orch.main(["bogus"])
        self.assertEqual(cm.exception.code, 2)

    def test_list_missing_vault_exits_2(self):
        err = StringIO()
        with redirect_stderr(err):
            code = orch.main(["list", "--vault", "C:/definitely/missing/vault"])
        self.assertEqual(code, 2)
        self.assertIn("error", err.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
