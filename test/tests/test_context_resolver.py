"""ContextResolver unit tests — temp vault fixtures, never the real vault.

Covers: BFS traversal from a task node, depth caps, direct-dependency priority,
node-type filtering at deeper rings, circular-link detection and termination,
unresolved-link reporting, determinism, and context logging.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.core import context_resolver as cr  # noqa: E402
from scripts.core import orchestrator as orch  # noqa: E402

FM = ("---\ntype: {t}\nstatus: active\nowner: test\ncreated: 2026-08-11\n"
      "updated: 2026-08-11\n---\n\n")


def node(t: str, body: str = "") -> str:
    return FM.format(t=t) + body


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

Resolver demo task.

## Description

Walk the graph.

## Acceptance Criteria

- [ ] done
"""


class ResolverTestCase(unittest.TestCase):
    """Temp vault with a 3-level graph INCLUDING a deliberate cycle:

    Task_Demo
      ├─ Agent_Matthew ──┬─ System_Architecture   (d2, type architecture)
      │                  └─ Decision_X             (d2, decision)
      ├─ Component_RunHub ─┬─ Decision_X           (d2, decision)
      │                    └─ [[Component_RunHub]]  (CYCLE back to itself)
      └─ [[Task_Demo]]                              (CYCLE back to root)
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "03-Tasks").mkdir(parents=True)
        (self.vault / "02-Agents").mkdir(parents=True)
        (self.vault / "01-Architecture").mkdir(parents=True)
        (self.vault / "04-Decisions").mkdir(parents=True)
        (self.vault / "05-Documentation").mkdir(parents=True)
        (self.vault / "06-Testing").mkdir(parents=True)
        (self.vault / "00-System").mkdir(parents=True)

        self.task_path = self.vault / "03-Tasks" / "Task_Demo.md"
        self.task_path.write_text(TASK_TEXT, encoding="utf-8")

        (self.vault / "02-Agents" / "Agent_Matthew.md").write_text(
            node("agent", "## Purpose\n\nCoordinates architecture.\n\n"
                          "Links: [[System_Architecture]] [[Decision_X]]\n"),
            encoding="utf-8")
        (self.vault / "01-Architecture" / "Component_RunHub.md").write_text(
            node("architecture", "## Overview\n\nDispatch engine.\n\n"
                                  "Links: [[Decision_X]] [[Component_RunHub]]\n"),
            encoding="utf-8")
        (self.vault / "01-Architecture" / "System_Architecture.md").write_text(
            node("architecture", "## Map\n\nHigh-level map.\n"),
            encoding="utf-8")
        (self.vault / "04-Decisions" / "Decision_X.md").write_text(
            node("decision", "## Decision\n\nUse the bridge.\n"),
            encoding="utf-8")
        (self.vault / "05-Documentation" / "Doc_Guide.md").write_text(
            node("documentation", "## Guide\n\nHow to run.\n"),
            encoding="utf-8")
        (self.vault / "06-Testing" / "Test_Plan.md").write_text(
            node("test", "## Plan\n\nRun the suite.\n"),
            encoding="utf-8")
        # A task node deeper in the graph (should be pruned past depth 1).
        (self.vault / "03-Tasks" / "Task_Other.md").write_text(
            node("task", "## Other\n\nNot relevant.\n"), encoding="utf-8")
        # An unrelated distractor that nothing links to.
        (self.vault / "00-System" / "Vault_Map.md").write_text(
            node("system", "unrelated"), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self, **kw):
        return cr.resolve_context(self.vault, self.task_path, **kw)


class TestTraversal(ResolverTestCase):
    def test_direct_links_collected_first(self):
        pkg = self.resolve(max_depth=1)
        names = pkg.included_names()
        # Depth-1 (direct) nodes are present regardless of type filter.
        self.assertIn("Agent_Matthew", names)
        self.assertIn("Component_RunHub", names)
        self.assertEqual([n.depth for n in pkg.nodes if n.name == "Agent_Matthew"], [1])

    def test_depth_cap_limits_rings(self):
        pkg = self.resolve(max_depth=1)
        for ref in pkg.nodes:
            self.assertLessEqual(ref.depth, 1)

    def test_max_nodes_cap(self):
        pkg = self.resolve(max_depth=5, max_nodes=2)
        self.assertLessEqual(len(pkg.nodes), 2)

    def test_deeper_ring_type_filter(self):
        pkg = self.resolve(max_depth=3, max_nodes=20)
        names = pkg.included_names()
        # Relevant kinds at depth 2 are included...
        self.assertIn("System_Architecture", names)
        self.assertIn("Decision_X", names)
        # ...but a task node at depth > 1 is pruned (no Task_Other).
        self.assertNotIn("Task_Other", names)
        # Unrelated node never appears.
        self.assertNotIn("Vault_Map", names)

    def test_task_node_excluded_from_package(self):
        pkg = self.resolve(max_depth=3, max_nodes=20)
        self.assertNotIn("Task_Demo", pkg.included_names())


class TestCycles(ResolverTestCase):
    def test_cycle_terminates_and_is_reported(self):
        pkg = self.resolve(max_depth=5, max_nodes=50)
        # Traversal completed (bounded) and at least one cycle was recorded.
        self.assertGreaterEqual(len(pkg.cycles), 1)
        pairs = {tuple(sorted(c)) for c in pkg.cycles}
        self.assertIn(("Component_RunHub", "Component_RunHub"), pairs)

    def test_no_infinite_loop(self):
        # Would hang forever if cycle detection were broken.
        pkg = self.resolve(max_depth=10, max_nodes=100)
        self.assertLessEqual(len(pkg.nodes), 100)

    def test_shared_descendant_not_false_cycle(self):
        # Agent_Matthew and Component_RunHub BOTH link Decision_X — a shared
        # DAG descendant, NOT a cycle. It must appear once, with no false
        # cycle reported for the shared link.
        pkg = self.resolve(max_depth=2, max_nodes=50)
        self.assertEqual(pkg.included_names().count("Decision_X"), 1)
        shared = [(a, b) for a, b in pkg.cycles
                  if sorted((a, b)) in (
                      sorted(("Agent_Matthew", "Decision_X")),
                      sorted(("Component_RunHub", "Decision_X")),
                  )]
        self.assertEqual(shared, [])


class TestUnresolved(ResolverTestCase):
    def test_unresolved_links_reported(self):
        (self.vault / "02-Agents" / "Agent_Matthew.md").write_text(
            node("agent", "Links: [[Agent_Ghost]] [[Component_RunHub]]\n"),
            encoding="utf-8")
        pkg = self.resolve(max_depth=2, max_nodes=20)
        self.assertIn("Agent_Ghost", pkg.unresolved)
        # Resolved nodes still present.
        self.assertIn("Component_RunHub", pkg.included_names())


class TestDeterminism(ResolverTestCase):
    def test_two_runs_identical(self):
        a = self.resolve(max_depth=3, max_nodes=20)
        b = self.resolve(max_depth=3, max_nodes=20)
        self.assertEqual(a.included_names(), b.included_names())
        self.assertEqual(a.cycles, b.cycles)
        self.assertEqual(a.unresolved, b.unresolved)

    def test_context_log_row_written(self):
        self.resolve(max_depth=2, max_nodes=10)
        clog = REPO_ROOT / "_logs" / "context_log.jsonl"
        self.assertTrue(clog.is_file())
        rows = [json.loads(line) for line in clog.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["task"], "Task_Demo")
        self.assertIn("included", rows[-1])


class TestCli(ResolverTestCase):
    def test_context_command(self):
        out = []
        from contextlib import redirect_stdout
        from io import StringIO
        buf = StringIO()
        with redirect_stdout(buf):
            code = orch.main(["context", "Task_Demo", "--vault", str(self.vault)])
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("Agent_Matthew", text)
        self.assertIn("Component_RunHub", text)


if __name__ == "__main__":
    unittest.main()
