"""ChangeDetector unit tests — temp trees, never the real vault/project.

Covers: created/modified/renamed/deleted detection, temp-file exclusion,
classification matrix, duplicate-event prevention, affected-node/component
mapping, and the read-only guarantee (detection never writes user files).
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import change_detector as cd


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


class ChangeDetectorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "proj"
        self.vault = self.root / "obsidian_vault"
        (self.vault / "03-Tasks").mkdir(parents=True)
        (self.vault / "01-Architecture").mkdir(parents=True)
        (self.vault / "02-Agents").mkdir(parents=True)
        (self.vault / "06-Testing").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def snap_vault(self):
        return cd._snapshot_tree(self.vault, include_suffixes={".md"})

    def snap_project(self):
        # Project snapshot: all source/config/markdown under self.root.
        out: dict[str, tuple[int, str]] = {}
        for dirpath, dirnames, filenames in os_walk(self.root):
            dirnames[:] = [d for d in dirnames
                           if d not in cd._EXCLUDE_DIRS and d != "obsidian_vault"]
            for fname in filenames:
                full = Path(dirpath) / fname
                rel = full.relative_to(self.root)
                if cd._excluded(rel):
                    continue
                if rel.suffix.lower() not in (cd._SOURCE_SUFFIXES
                                              | cd._CONFIG_SUFFIXES | {".md"}):
                    continue
                st = full.stat()
                out[str(rel).replace("/", "\\").replace("\\", "/")] = (
                    st.st_mtime_ns, cd._file_digest(full))
        return out


def os_walk(path):
    import os
    return os.walk(path)


class TestSnapshot(ChangeDetectorTestCase):
    def test_snapshot_excludes_temp_and_logs(self):
        _make_tree(self.root, {
            "obsidian_vault/01-Architecture/System_Architecture.md": "# map",
            "obsidian_vault/03-Tasks/Task_A.md": "# task",
            "scripts/core/run_hub.py": "def x(): pass",
            "scripts/core/tmp.txt.tmp": "noise",
            "notes.md~": "editor backup",
            "obsidian_vault/~$Task_A.md": "office lock",
        })
        data = cd.snapshot(vault=self.vault, project_root=self.root)
        keys = list(data["vault"]) + list(data["project"])
        self.assertIn("01-Architecture/System_Architecture.md", data["vault"])
        self.assertIn("03-Tasks/Task_A.md", data["vault"])
        self.assertIn("scripts/core/run_hub.py", data["project"])
        self.assertNotIn("scripts/core/tmp.txt.tmp", data["project"])
        self.assertNotIn("notes.md~", data["project"])
        self.assertNotIn("~$Task_A.md", data["vault"])


class TestDiff(ChangeDetectorTestCase):
    def test_created_modified_deleted(self):
        _make_tree(self.root, {"scripts/a.py": "v1", "scripts/b.py": "keep"})
        before = cd._snapshot_tree(self.root / "scripts")
        (self.root / "scripts/a.py").write_text("v2", encoding="utf-8")
        _make_tree(self.root, {"scripts/c.py": "new"})
        (self.root / "scripts/b.py").unlink()
        after = cd._snapshot_tree(self.root / "scripts")
        changes = cd._diff_snap(before, after, lambda p: cd.classify(p))
        kinds = {(c.kind, c.path) for c in changes}
        self.assertIn(("modified", "a.py"), kinds)
        self.assertIn(("created", "c.py"), kinds)
        self.assertIn(("deleted", "b.py"), kinds)

    def test_rename_detected_by_identical_content(self):
        _make_tree(self.root, {"old.py": "same-content"})
        before = cd._snapshot_tree(self.root)
        (self.root / "old.py").unlink()
        _make_tree(self.root, {"new.py": "same-content"})
        after = cd._snapshot_tree(self.root)
        changes = cd._diff_snap(before, after, lambda p: cd.classify(p))
        renames = [c for c in changes if c.kind == cd.ChangeKind.RENAMED]
        self.assertEqual(len(renames), 1)
        self.assertIn("old.py -> new.py", renames[0].path)

    def test_rename_then_created_not_both(self):
        # A rename must not ALSO be reported as created+deleted.
        _make_tree(self.root, {"a.py": "content"})
        before = cd._snapshot_tree(self.root)
        (self.root / "a.py").unlink()
        _make_tree(self.root, {"b.py": "content"})
        after = cd._snapshot_tree(self.root)
        changes = cd._diff_snap(before, after, lambda p: cd.classify(p))
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, cd.ChangeKind.RENAMED)

    def test_dedupe_key(self):
        c1 = cd.Change("x.py", "modified", "source code", "h1", "h2")
        c2 = cd.Change("x.py", "modified", "source code", "h1", "h2")
        self.assertEqual(c1.dedupe_key, c2.dedupe_key)


class TestClassify(ChangeDetectorTestCase):
    def test_classification_matrix(self):
        cases = {
            "01-Architecture/System_Architecture.md": "architecture",
            "02-Agents/Agent_Matthew.md": "agent",
            "03-Tasks/Task_X.md": "task",
            "05-Documentation/Doc_Guide.md": "documentation",
            "06-Testing/Test_Plan.md": "test",
            "scripts/core/run_hub.py": "source code",
            "test/tests/test_hub.py": "test",
            "opencode.json": "configuration",
            "launch_agents.bat": "configuration",
            "scripts/run_agent_worker.ps1": "configuration",
            "scripts/core/run_hub.py": "source code",
        }
        for path, expected in cases.items():
            self.assertEqual(cd.classify(path), expected, path)


class TestAffected(ChangeDetectorTestCase):
    def test_affected_nodes_from_component(self):
        _make_tree(self.root, {
            "obsidian_vault/01-Architecture/Component_RunHub.md": "# hub",
            "obsidian_vault/03-Tasks/Task_A.md":
                "---\ntype: task\nstatus: planned\nowner: o\n"
                "created: 2026-08-11\nupdated: 2026-08-11\n"
                "related_component: Component_RunHub\n---\n\n# Task_A\n",
        })
        nodes = cd.affected_nodes(self.vault, "scripts/core/run_hub.py")
        # Task_A's frontmatter names Component_RunHub; the component stem of
        # run_hub.py is 'run_hub', so it is matched via the 'RunHub' token.
        self.assertTrue(any("Task_A" in n for n in nodes), nodes)

    def test_affected_nodes_skip_hub_index_flood(self):
        # Hub/index files merely LIST a component in their children index —
        # that is not a dependency, so they must not appear as affected.
        _make_tree(self.root, {
            "obsidian_vault/01-Architecture/Architecture_Home.md":
                "# Home\n\n↓ Children: [[Component_RunHub]]\n",
            "obsidian_vault/03-Tasks/Task_A.md":
                "---\ntype: task\nstatus: planned\nowner: o\n"
                "created: 2026-08-11\nupdated: 2026-08-11\n"
                "related_component: Component_RunHub\n---\n\n# Task_A\n",
        })
        nodes = cd.affected_nodes(self.vault, "scripts/core/run_hub.py")
        self.assertIn("03-Tasks/Task_A", nodes)
        self.assertNotIn("01-Architecture/Architecture_Home", nodes)

    def test_affected_components_from_node(self):
        _make_tree(self.root, {
            "obsidian_vault/01-Architecture/Component_RunHub.md": "# hub",
            "obsidian_vault/03-Tasks/Task_A.md":
                "---\ntype: task\nstatus: planned\nowner: o\n"
                "created: 2026-08-11\nupdated: 2026-08-11\n"
                "related_component: Component_RunHub\n---\n\n# Task_A\n\n[[Component_RunHub]]\n",
        })
        comps = cd.affected_components(self.vault, "03-Tasks/Task_A.md")
        self.assertIn("Component_RunHub", comps)


class TestReadOnly(ChangeDetectorTestCase):
    def test_snapshot_never_writes_user_files(self):
        _make_tree(self.root, {"scripts/a.py": "v1"})
        before = list((self.root / "scripts").glob("*.py"))
        cd._snapshot_tree(self.root / "scripts")
        after = list((self.root / "scripts").glob("*.py"))
        self.assertEqual([p.name for p in before], [p.name for p in after])
        self.assertEqual((self.root / "scripts/a.py").read_text(encoding="utf-8"), "v1")


if __name__ == "__main__":
    unittest.main()
