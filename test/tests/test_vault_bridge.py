"""VaultBridge unit tests — uses temp vault fixtures, never the real vault.

Covers: vault resolution/validation, scoped task reads, frontmatter parsing,
relationship resolution, body preservation, backup creation, duplicate-execution
prevention, and change-log recording.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import orchestrator as orch  # noqa: E402
from scripts.core import vault_bridge as bridge  # noqa: E402

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


class BridgeTestCase(unittest.TestCase):
    """Shared fixture: a temp vault with tasks + linked nodes."""

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
        # Distractor node that must NOT be included in scoped reads.
        self.system = self.vault / "00-System"
        self.system.mkdir(parents=True)
        (self.system / "Vault_Map.md").write_text("unrelated", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def read_task(self):
        return orch.read_task(self.task_path)


class TestVaultResolution(BridgeTestCase):
    def test_validate_ok(self):
        orch.validate_vault(self.vault)  # must not raise

    def test_validate_missing_dir_raises(self):
        with self.assertRaises(orch.VaultError):
            orch.validate_vault(Path(self.tmp.name) / "nope")

    def test_validate_missing_tasks_dir_raises(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(orch.VaultError):
            orch.validate_vault(empty)

    def test_list_tasks_scoped(self):
        # A stray markdown file outside 03-Tasks must never appear.
        (self.vault / "Scratch_Note.md").write_text("x", encoding="utf-8")
        tasks = orch.list_tasks(self.vault)
        self.assertEqual([t.name for t in tasks], ["Task_Demo.md"])


class TestFrontmatterSafety(BridgeTestCase):
    def test_malformed_frontmatter_reported_safely(self):
        bad = self.tasks / "Task_Bad.md"
        bad.write_text("# No frontmatter\njust body\n", encoding="utf-8")
        fields, err = orch.parse_frontmatter(bad.read_text(encoding="utf-8"))
        self.assertEqual(fields, {})
        self.assertIn("missing frontmatter", err)

    def test_parse_frontmatter_fields(self):
        fields, err = orch.parse_frontmatter(TASK_TEXT)
        self.assertIsNone(err)
        self.assertEqual(fields["assigned_agent"], "Agent_Matthew")
        self.assertEqual(fields["related_component"], "Component_RunHub")


class TestRelationshipResolution(BridgeTestCase):
    def test_resolves_agent_and_component(self):
        fields, body, _raw = self.read_task()
        resolved, unresolved = bridge.resolve_relationships(self.vault, fields, body)
        self.assertIn("Agent_Matthew", resolved)
        self.assertIn("Component_RunHub", resolved)
        self.assertEqual(unresolved, [])
        self.assertNotIn("Vault_Map", resolved)  # unrelated node never resolved

    def test_unresolved_links_reported(self):
        fields, body, _raw = self.read_task()
        fields = dict(fields)
        fields["related_component"] = "Component_Nope"
        resolved, unresolved = bridge.resolve_relationships(self.vault, fields, body)
        self.assertIn("Component_Nope", unresolved)
        self.assertIn("Agent_Matthew", resolved)

    def test_extract_links_dedupes(self):
        fields, body, _raw = self.read_task()
        links = bridge.extract_links(fields, body)
        self.assertEqual(links.count("Agent_Matthew"), 1)
        self.assertEqual(len(links), len(set(links)))


class TestUpdateTask(BridgeTestCase):
    def test_update_preserves_body_byte_for_byte(self):
        def body_of(text):
            m = bridge.FRONTMATTER_RE.match(text)
            return text[m.end():] if m else text
        before = self.task_path.read_text(encoding="utf-8")
        body_before = body_of(before)
        bridge.update_task(self.task_path, "test", {"status": "ready"})
        after = self.task_path.read_text(encoding="utf-8")
        body_after = body_of(after)
        self.assertEqual(body_before, body_after)  # human content untouched
        self.assertIn("status: ready", after)

    def test_update_creates_backup(self):
        bdir = REPO_ROOT / "_logs" / "vault_backups"
        # Only consider backups created by THIS write — the shared _logs/ dir
        # accumulates Task_Demo backups from earlier runs/tests.
        before = {p.name for p in bdir.glob("Task_Demo-*.bak")} if bdir.is_dir() else set()
        bridge.update_task(self.task_path, "test", {"status": "ready"})
        backups = [p for p in bdir.glob("Task_Demo-*.bak") if p.name not in before]
        self.assertGreaterEqual(len(backups), 1)
        # Backup contains the PRE-write content.
        self.assertIn("status: planned", backups[-1].read_text(encoding="utf-8"))

    def test_rapid_writes_never_clobber_backups(self):
        # Two writes within the same second must produce two distinct backups
        # (counter suffix), never overwrite the earlier one. Only backups
        # created by THIS call count — the shared _logs/ dir accumulates
        # Task_Demo backups from earlier runs/tests.
        bdir = REPO_ROOT / "_logs" / "vault_backups"
        before = {p.name for p in bdir.glob("Task_Demo-*.bak")} if bdir.is_dir() else set()
        bridge.update_task(self.task_path, "test", {"status": "ready"})
        bridge.update_task(self.task_path, "test", {"status": "in_progress"})
        new = {p.name for p in bdir.glob("Task_Demo-*.bak")} - before
        # Distinct names exist: at least two separate backup files were kept.
        self.assertGreaterEqual(len(new), 2)
        # Both backups carry pre-write states (planned, then ready).
        contents = [
            (bdir / name).read_text(encoding="utf-8") for name in sorted(new)
        ]
        self.assertTrue(any("status: planned" in c for c in contents))
        self.assertTrue(any("status: ready" in c for c in contents))

    def test_update_records_change_log(self):
        clog = REPO_ROOT / "_logs" / "vault_changes.jsonl"
        before = clog.read_text(encoding="utf-8").splitlines() if clog.is_file() else []
        bridge.update_task(self.task_path, "test-caller", {"status": "ready"})
        records = [json.loads(line) for line in clog.read_text(encoding="utf-8").splitlines()]
        new_rows = records[len(before):]  # only rows appended by THIS call
        self.assertEqual(len(new_rows), 1)
        last = new_rows[0]
        self.assertEqual(last["caller"], "test-caller")
        self.assertIn("status", last["changed"])
        self.assertEqual(last["changed"]["status"]["old"], "planned")
        self.assertEqual(last["changed"]["status"]["new"], "ready")

    def test_update_with_new_body_replaces_body_only(self):
        bridge.update_task(self.task_path, "test",
                           {"status": "in_progress"},
                           new_body="# New Body\n")
        text = self.task_path.read_text(encoding="utf-8")
        self.assertIn("# New Body", text)
        self.assertIn("status: in_progress", text)
        self.assertNotIn("Acceptance Criteria", text)


class TestDuplicatePrevention(BridgeTestCase):
    def test_planned_is_dispatchable(self):
        fields, _b, _r = self.read_task()
        ok, why = bridge.is_dispatchable(fields)
        self.assertTrue(ok)
        self.assertIsNone(why)

    def test_in_progress_not_dispatchable(self):
        fields, _b, _r = self.read_task()
        ok, why = bridge.is_dispatchable({**fields, "status": "in_progress"})
        self.assertFalse(ok)
        self.assertIn("in_progress", why)

    def test_completed_not_dispatchable(self):
        fields, _b, _r = self.read_task()
        ok, _why = bridge.is_dispatchable({**fields, "status": "completed"})
        self.assertFalse(ok)

    def test_orchestrator_dispatch_refuses_duplicate_via_bridge(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        with self.assertRaises(orch.VaultError):
            orch.cmd_dispatch(self.vault, "Task_Demo")


class TestOrchestratorRoutesThroughBridge(BridgeTestCase):
    def test_set_status_writes_backup_and_change(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        self.assertIn("status: ready", self.task_path.read_text(encoding="utf-8"))
        bdir = REPO_ROOT / "_logs" / "vault_backups"
        self.assertGreaterEqual(len(list(bdir.glob("Task_Demo-*.bak"))), 1)
        clog = REPO_ROOT / "_logs" / "vault_changes.jsonl"
        records = [json.loads(line) for line in clog.read_text(encoding="utf-8").splitlines()]
        self.assertIn("set-status", {r["caller"] for r in records})

    def test_report_routes_through_bridge(self):
        orch.cmd_set_status(self.vault, "Task_Demo", "ready")
        orch.cmd_set_status(self.vault, "Task_Demo", "in_progress")
        orch.cmd_report(self.vault, "Task_Demo", "failed")
        after = self.task_path.read_text(encoding="utf-8")
        self.assertIn("status: failed", after)
        self.assertIn("## Execution Log", after)
        # Body content preserved alongside the appended log.
        self.assertIn("## Acceptance Criteria", after)


if __name__ == "__main__":
    unittest.main()
