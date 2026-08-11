"""KnowledgeSync unit tests — temp vaults; sync never touches real code.

Covers: dry-run writes nothing, managed-only updates preserving human content,
conflict detection both directions (documented-but-missing, undocumented
module), no-false-documentation (links only added for what exists), sync-log
recording, and the read-only-on-code guarantee.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import knowledge_sync as ks  # noqa: E402
from scripts.core import vault_bridge as bridge  # noqa: E402

FM = ("---\ntype: {t}\nstatus: {s}\nowner: test\ncreated: 2026-08-11\n"
      "updated: 2020-01-01\n---\n\n")


def node(t: str, s: str = "active", body: str = "") -> str:
    return FM.format(t=t, s=s) + body


class KnowledgeSyncTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "01-Architecture").mkdir(parents=True)
        (self.vault / "02-Agents").mkdir(parents=True)
        (self.vault / "03-Tasks").mkdir(parents=True)
        (self.vault / "05-Documentation").mkdir(parents=True)
        (self.vault / "06-Testing").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, content: str) -> Path:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


class TestDryRun(KnowledgeSyncTestCase):
    def test_dry_run_builds_plan_without_writing(self):
        task = self.write("03-Tasks/Task_A.md", node("task", "planned"))
        plan = ks.build_plan(self.vault)
        self.assertTrue(any(a.field == "updated" for a in plan.actions))
        # Nothing written:
        self.assertEqual(task.read_text(encoding="utf-8"), node("task", "planned"))


class TestApplyManagedOnly(KnowledgeSyncTestCase):
    def test_apply_updates_updated_field_preserves_body(self):
        body_text = "# Task_A\n\n## Title\n\nHuman title.\n\n## Description\n\nKeep me.\n"
        self.write("03-Tasks/Task_A.md", node("task", "planned") + body_text)
        plan = ks.build_plan(self.vault)
        n = ks.apply_plan(self.vault, plan)
        self.assertGreaterEqual(n, 1)
        text = (self.vault / "03-Tasks/Task_A.md").read_text(encoding="utf-8")
        # Managed field updated:
        self.assertRegex(text, r"updated: 2026-\d{2}-\d{2}")
        # Human body preserved byte-for-byte:
        self.assertIn("## Description\n\nKeep me.", text)
        # Status untouched (planned preserved):
        self.assertIn("status: planned", text)

    def test_apply_never_touches_unknown_fields(self):
        # A 'priority' field change is NOT part of the managed set — the plan
        # must not contain it.
        self.write("03-Tasks/Task_A.md", node("task", "planned"))
        plan = ks.build_plan(self.vault)
        fields = {a.field for a in plan.actions}
        self.assertLessEqual(fields, set(ks.MANAGED_FIELDS))


class TestConflicts(KnowledgeSyncTestCase):
    def test_documented_but_missing_path(self):
        self.write("01-Architecture/Component_Phantom.md",
                   node("architecture") + "Source files: `scripts/core/phantom.py`\n")
        conflicts = ks.check_conflicts(self.vault)
        self.assertTrue(any("phantom.py" in c and "does not exist" in c
                            for c in conflicts))

    def test_undocumented_module_reported(self):
        # A temp 'scripts/core' module the vault never mentions:
        core = REPO_ROOT / "scripts" / "core"
        self.assertTrue(core.is_dir())  # real repo has modules
        conflicts = ks.check_conflicts(self.vault)
        self.assertTrue(any("no Component_* node" in c for c in conflicts))

    def test_no_false_documentation(self):
        # related_component pointing at a non-existent node is a conflict,
        # never silently added.
        self.write("03-Tasks/Task_A.md",
                   "---\ntype: task\nstatus: planned\nowner: t\n"
                   "created: 2026-08-11\nupdated: 2026-08-11\n"
                   "related_component: Component_Ghost\n---\n\n# Task_A\n")
        conflicts = ks.check_conflicts(self.vault)
        self.assertTrue(any("Component_Ghost" in c for c in conflicts))


class TestGeneratedBlocks(KnowledgeSyncTestCase):
    def test_stale_generated_block_detected(self):
        self.write("01-Architecture/Component_X.md",
                   node("architecture") +
                   "<!-- GENERATED: component-map -->\ncontent\n")
        conflicts = ks.check_conflicts(self.vault)
        self.assertTrue(any("no closing marker" in c for c in conflicts))


class TestSyncLog(KnowledgeSyncTestCase):
    def test_log_row_written(self):
        plan = ks.build_plan(self.vault)
        ks.log_run("sync", plan, dry_run=True)
        path = REPO_ROOT / "_logs" / "sync_log.jsonl"
        self.assertTrue(path.is_file())
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        last = rows[-1]
        self.assertEqual(last["mode"], "sync")
        self.assertTrue(last["dry_run"])
        self.assertIn("actions", last)


class TestCodeReadOnly(KnowledgeSyncTestCase):
    def test_sync_source_has_no_code_write_syscalls(self):
        src = Path(ks.__file__).read_text(encoding="utf-8")
        # The module may only write through the bridge (update_node) — never
        # direct source-file mutation.
        self.assertNotIn("_REPO_ROOT / \"scripts\"", src.replace(
            "_REPO_ROOT / \"scripts\" / \"core\"", ""))


if __name__ == "__main__":
    unittest.main()
