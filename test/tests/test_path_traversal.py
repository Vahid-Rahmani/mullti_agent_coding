"""Path-traversal regression tests for vault node/task path resolution.

The fix centralizes safe name->path resolution in
``vault_bridge.resolve_child`` / ``resolve_task`` and routes the web-UI
``graph.find_node`` and ``routes._task_path`` (plus the orchestrator and
context-resolver task lookups) through it. These tests pin that an
attacker-controlled name can never resolve outside the vault / 03-Tasks/.
"""

import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi import HTTPException

from scripts.core import context_resolver as ctx
from scripts.core import orchestrator as orch
from scripts.core import vault_bridge as bridge
from scripts.web_ui import graph as vgraph
from scripts.web_ui import routes

TASK_TEXT = """---\ntype: task\nstatus: planned\nowner: orchestrator\npriority: high\nassigned_agent: Agent_Matthew\nrelated_component: Component_RunHub\ndependencies: []\ncreated: 2026-08-11\nupdated: 2026-08-11\n---\n\n# Task_Demo\n\nDo the thing.\n"""

NODE_TEXT = (
    "---\ntype: {node_type}\nstatus: active\nowner: x\n"
    "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n# {name}\n"
)

# Every form of traversal / absolute path / separator that must be rejected.
UNSAFE_NAMES = [
    "../secret",              # Unix parent traversal
    "../../secret",           # multi-level Unix traversal
    "..\\secret",             # Windows parent traversal
    "..\\..\\secret",         # multi-level Windows traversal
    "/etc/passwd",            # absolute Unix path
    "C:\\Windows\\win.ini",   # Windows absolute / drive path
    "C:/Windows/win.ini",     # drive path with forward slash
    "..\\../secret",          # mixed separators
    "..//../secret",          # mixed / doubled separators
    "subdir/Task_Demo",       # nested-looking name (Unix)
    "subdir\\Task_Demo",      # nested-looking name (Windows)
    ".",                      # current-dir dot component
    "..",                     # parent dot component
    "",                       # empty
    "foo\x00bar",             # embedded NUL
]


class PathTraversalTestCase(unittest.TestCase):
    """Direct tests of the resolver and both affected web-UI code paths."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.tasks = self.vault / "03-Tasks"
        self.tasks.mkdir(parents=True)
        self.task_path = self.tasks / "Task_Demo.md"
        self.task_path.write_text(TASK_TEXT, encoding="utf-8")

        # Root + section nodes so find_node's two branches are exercised.
        (self.vault / "Dashboard.md").write_text(
            NODE_TEXT.format(node_type="system", name="Dashboard"),
            encoding="utf-8",
        )
        agents = self.vault / "02-Agents"
        agents.mkdir(parents=True)
        (agents / "Agent_Matthew.md").write_text(
            NODE_TEXT.format(node_type="agent", name="Agent_Matthew"),
            encoding="utf-8",
        )

        # Decoys a traversal would reach if the boundary were missing: they
        # carry valid task frontmatter so an escape would resolve AND read them.
        (self.vault / "secret.md").write_text("TOP SECRET", encoding="utf-8")
        Path(self.tmp.name).joinpath("secret.md").write_text(
            "TOP SECRET", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    # ---- centralized resolver ------------------------------------------

    def test_resolve_child_rejects_unsafe_names(self):
        for name in UNSAFE_NAMES:
            self.assertIsNone(bridge.resolve_child(self.vault, name), name)

    def test_resolve_task_rejects_unsafe_names(self):
        for name in UNSAFE_NAMES:
            self.assertIsNone(bridge.resolve_task(self.vault, name), name)

    def test_resolve_task_accepts_valid_task(self):
        path = bridge.resolve_task(self.vault, "Task_Demo")
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "Task_Demo.md")
        self.assertEqual(path.parent, self.tasks.resolve())

    # ---- graph.find_node (root + section branches) ----------------------

    def test_find_node_rejects_unsafe_names(self):
        for name in UNSAFE_NAMES:
            self.assertIsNone(vgraph.find_node(self.vault, name), name)

    def test_find_node_finds_root_and_section_nodes(self):
        self.assertEqual(vgraph.find_node(self.vault, "Dashboard"),
                         (self.vault / "Dashboard.md").resolve())
        self.assertEqual(vgraph.find_node(self.vault, "Agent_Matthew"),
                         (self.vault / "02-Agents" / "Agent_Matthew.md").resolve())
        self.assertEqual(vgraph.find_node(self.vault, "Task_Demo"),
                         self.task_path.resolve())

    # ---- routes._task_path ----------------------------------------------

    def test_task_path_rejects_unsafe_names(self):
        for name in UNSAFE_NAMES:
            with self.assertRaises(HTTPException) as cm:
                routes._task_path(self.vault, name)
            self.assertEqual(cm.exception.status_code, 404, name)

    def test_task_path_accepts_valid_task(self):
        self.assertEqual(routes._task_path(self.vault, "Task_Demo"),
                         self.task_path.resolve())

    def test_task_path_does_not_leak_decoy(self):
        # The decoys exist and are valid tasks; an escape would return them.
        for name in ("../secret", "../../secret", "..\\secret"):
            with self.assertRaises(HTTPException):
                routes._task_path(self.vault, name)

    # ---- orchestrator / context-resolver (same pattern) -----------------

    def test_orchestrator_rejects_unsafe_task_names(self):
        for name in UNSAFE_NAMES:
            with self.assertRaises(bridge.VaultError):
                orch._task_file(self.vault, name)
        self.assertEqual(orch._task_file(self.vault, "Task_Demo"),
                         self.task_path.resolve())

    def test_cmd_show_and_context_reject_unsafe_names(self):
        with self.assertRaises(bridge.VaultError):
            orch.cmd_show(self.vault, "../secret")
        with self.assertRaises(bridge.VaultError):
            ctx.cmd_context(self.vault, "../../secret", 2, 10)


class _FakeHub:
    """Minimal hub surface WebState.snapshot() reads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.running = 0
        self.statuses = {}
        self.progress = {}
        self.token_usage = {}
        self.prompts = {}
        self.session_tags = set()


class ApiTraversalTestCase(unittest.TestCase):
    """End-to-end: the REST endpoints reject traversal without leaking files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.tasks = self.vault / "03-Tasks"
        self.tasks.mkdir(parents=True)
        (self.tasks / "Task_Demo.md").write_text(TASK_TEXT, encoding="utf-8")
        (self.vault / "Dashboard.md").write_text(
            NODE_TEXT.format(node_type="system", name="Dashboard"),
            encoding="utf-8",
        )
        Path(self.tmp.name).joinpath("secret.md").write_text(
            "TOP SECRET", encoding="utf-8")

        from fastapi.testclient import TestClient

        from scripts.web_ui.server import create_app
        from scripts.web_ui.state import WebState

        self.client = TestClient(create_app(vault=self.vault,
                                            state=WebState(hub=_FakeHub())))

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_node_endpoint_still_works(self):
        r = self.client.get("/api/vault/node/Dashboard")
        self.assertEqual(r.status_code, 200)

    def test_traversal_node_is_rejected_without_leak(self):
        for path in (
            "/api/vault/node/..%2F..%2Fsecret",
            "/api/vault/node/..%5C..%5Csecret",
        ):
            r = self.client.get(path)
            self.assertNotEqual(r.status_code, 200, path)
            self.assertNotIn("TOP SECRET", r.text, path)

    def test_traversal_task_is_rejected_without_leak(self):
        r = self.client.post("/api/tasks/..%2F..%2Fsecret/status",
                             json={"status": "ready"})
        self.assertNotEqual(r.status_code, 200)
        self.assertNotIn("TOP SECRET", r.text)


if __name__ == "__main__":
    unittest.main()
