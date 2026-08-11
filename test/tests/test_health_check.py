"""HealthCheck unit tests — temp vaults with injected issues, never the real vault.

Covers: orphan detection, broken links, missing frontmatter, invalid task
statuses, missing agent references, cycles, duplicate names, reachability,
consistency, docs-vs-code conflicts, and the healthy list.
"""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import health_check as hc  # noqa: E402

FM = ("---\ntype: {t}\nstatus: {s}\nowner: test\ncreated: 2026-08-11\n"
      "updated: 2026-08-11\n---\n\n")


def node(t: str, s: str = "active", body: str = "") -> str:
    return FM.format(t=t, s=s) + (body or f"# {t}\n")


class HealthTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        for sec in hc.SECTIONS:
            (self.vault / sec).mkdir(parents=True)
        self.write("00-System/System_Core.md",
                   node("system", body="[[Architecture_Home]] [[Agents_Home]] [[Tasks_Home]]"))
        for hub, sec, t in (("Architecture_Home", "01-Architecture", "architecture"),
                            ("Agents_Home", "02-Agents", "agent"),
                            ("Tasks_Home", "03-Tasks", "task"),
                            ("Decisions_Home", "04-Decisions", "decision"),
                            ("Documentation_Home", "05-Documentation", "documentation"),
                            ("Testing_Home", "06-Testing", "test")):
            self.write(f"{sec}/{hub}.md", node(t, body=f"# {hub}\n"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, content: str) -> None:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def run_health(self):
        return hc.run_health(self.vault)

    def messages(self, report, severity=None, check=None):
        issues = report.errors if severity == "error" else report.warnings
        if check:
            issues = [i for i in issues if i.check == check]
        return [i.message for i in issues]


class TestFrontmatter(HealthTestCase):
    def test_missing_field_is_error(self):
        self.write("03-Tasks/Task_X.md", "# no frontmatter\n")
        report = self.run_health()
        self.assertTrue(any("Task_X" in m for m in self.messages(report, "error", "frontmatter")))

    def test_valid_nodes_not_flagged(self):
        report = self.run_health()
        self.assertFalse(self.messages(report, "error", "frontmatter"))


class TestBrokenLinks(HealthTestCase):
    def test_broken_link_is_error(self):
        self.write("05-Documentation/Doc_A.md",
                   node("documentation", body="[[Ghost_Node]]\n"))
        report = self.run_health()
        self.assertTrue(any("Ghost_Node" in m for m in self.messages(report, "error", "broken-link")))


class TestTaskStatus(HealthTestCase):
    def test_invalid_status_is_error(self):
        self.write("03-Tasks/Task_X.md", FM.format(t="task", s="banana") + "# Task_X\n")
        report = self.run_health()
        self.assertTrue(any("banana" in m for m in self.messages(report, "error", "task-status")))

    def test_hub_not_flagged(self):
        report = self.run_health()
        self.assertFalse(self.messages(report, "error", "task-status"))


class TestAgentRef(HealthTestCase):
    def test_missing_agent_is_error(self):
        content = ("---\ntype: task\nstatus: planned\nowner: test\n"
                   "created: 2026-08-11\nupdated: 2026-08-11\n"
                   "related_component: Component_A\nassigned_agent: Agent_Ghost\n"
                   "---\n\n# Task_X\n")
        self.write("03-Tasks/Task_X.md", content)
        report = self.run_health()
        self.assertTrue(any("Agent_Ghost" in m for m in self.messages(report, "error", "agent-ref")))


class TestOrphans(HealthTestCase):
    def test_unlinked_node_is_orphan_warning(self):
        self.write("05-Documentation/Doc_Alone.md", node("documentation"))
        report = self.run_health()
        self.assertTrue(any("Doc_Alone" in m for m in self.messages(report, "warning", "orphan")))


class TestCycles(HealthTestCase):
    def test_cycle_detected(self):
        # A genuine 3-node cycle (A->B->C->A). Mutual 2-cycles (A<->B) are
        # intentional bidirectional references and are NOT reported.
        self.write("01-Architecture/Component_A.md", node("architecture", body="[[Component_B]]"))
        self.write("01-Architecture/Component_B.md", node("architecture", body="[[Component_C]]"))
        self.write("01-Architecture/Component_C.md", node("architecture", body="[[Component_A]]"))
        self.write("01-Architecture/Architecture_Home.md",
                   node("architecture", body="[[Component_A]]"))
        report = self.run_health()
        cycles = self.messages(report, "warning", "cycle")
        self.assertTrue(cycles, "expected a cycle warning, got none")
        self.assertTrue(any("Component_A" in c for c in cycles))

    def test_mutual_pair_not_cycle(self):
        # A<->B is a benign bidirectional reference, not a dependency cycle.
        self.write("01-Architecture/Component_A.md", node("architecture", body="[[Component_B]]"))
        self.write("01-Architecture/Component_B.md", node("architecture", body="[[Component_A]]"))
        self.write("01-Architecture/Architecture_Home.md",
                   node("architecture", body="[[Component_A]] [[Component_B]]"))
        report = self.run_health()
        self.assertFalse(self.messages(report, "warning", "cycle"))


class TestDuplicates(HealthTestCase):
    def test_duplicate_stem_warning(self):
        self.write("01-Architecture/Dup.md", node("architecture"))
        self.write("05-Documentation/Dup.md", node("documentation"))
        report = self.run_health()
        self.assertTrue(any("Dup" in m for m in self.messages(report, "warning", "duplicate")))


class TestReachability(HealthTestCase):
    def test_unreachable_critical_node_is_error(self):
        # Add a second hub that System_Core does not link (simulate by unlinking).
        self.write("05-Documentation/Documentation_Home.md", node("documentation"))
        report = self.run_health()
        self.assertTrue(self.messages(report, "error", "reachability"))


class TestHealthyList(HealthTestCase):
    def test_healthy_nodes_exclude_flagged(self):
        self.write("03-Tasks/Task_Bad.md", "# no frontmatter\n")
        report = self.run_health()
        self.assertNotIn("Task_Bad", report.healthy)
        self.assertIn("System_Core", report.healthy)


class TestConsistency(HealthTestCase):
    def test_child_not_listed_in_hub_warning(self):
        self.write("02-Agents/Agent_Matthew.md", node("agent"))
        report = self.run_health()
        self.assertTrue(any("Agent_Matthew" in m and "Agents_Home" in m
                            for m in self.messages(report, "warning", "consistency")))


class TestConflicts(HealthTestCase):
    def test_docs_code_conflict_warning(self):
        # A component claiming a nonexistent source path.
        self.write("01-Architecture/Component_Phantom.md",
                   node("architecture", body="Source files: `scripts/core/nope.py`\n"))
        report = self.run_health()
        self.assertTrue(any("nope.py" in m for m in self.messages(report, "warning", "docs-code")))


if __name__ == "__main__":
    unittest.main()
