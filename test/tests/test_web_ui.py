"""Web dashboard tests — temp-vault/TestClient fixtures, never the real vault.

Covers: WebState drain/sessions/prefs, VaultGraph building + relationships,
and the REST API surface (agents, dispatch validation, task assign/status
validation, task-dispatch argv, logs, static assets). Real agent dispatch and
task subprocesses are never executed — the hub is a fake and Popen is stubbed.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from scripts.web_ui import graph as vgraph  # noqa: E402
from scripts.web_ui.state import WebState  # noqa: E402

NODE_TEXT = (
    "---\ntype: {node_type}\nstatus: active\nowner: x\n"
    "created: 2026-08-11\nupdated: 2026-08-11\n---\n\n"
    "# {name}\n\n{body}\n"
)

TASK_TEXT = """\
---
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


def make_node(name, node_type="system", body=""):
    return NODE_TEXT.format(node_type=node_type, name=name, body=body)


class LineStream:
    """Minimal iterable with the surface Popen.stdout is expected to have."""

    def __init__(self, lines):
        self._lines = list(lines)
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line + "\n"


class FakeHub:
    """Stand-in for RunHub: records calls, exposes telemetry."""

    TAGS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7")

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.running = 0
        self.statuses = {t: "idle" for t in self.TAGS}
        self.progress = {t: 0 for t in self.TAGS}
        self.token_usage = {t: 0 for t in self.TAGS}
        self.prompts = {t: "" for t in self.TAGS}
        self.session_tags: set[str] = set()
        self.calls: list[tuple] = []

    def run(self, prompt, overrides=None, agents=None, system_prompts=None,
            enabled_agents=None):
        self.calls.append(("run", prompt, agents))
        return None if prompt.strip() else "Prompt must not be empty."

    def terminate_agent(self, tag):
        self.calls.append(("terminate_agent", tag))

    def terminate_all(self):
        self.calls.append(("terminate_all",))


class VaultTestCase(unittest.TestCase):
    """Temp vault fixture: 03-Tasks + task node + linked nodes + archives."""

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
            make_node("Agent_Matthew", "agent", ""), encoding="utf-8")

        self.system = self.vault / "00-System"
        self.system.mkdir(parents=True)
        (self.system / "System_Core.md").write_text(
            make_node("System_Core", "system", "[[Tasks_Home]]"), encoding="utf-8")
        (self.system / "Vault_Map.md").write_text(
            make_node("Vault_Map", "system", "[[System_Core]]"), encoding="utf-8")

        (self.vault / "03-Tasks" / "Tasks_Home.md").write_text(
            make_node("Tasks_Home", "task", ""), encoding="utf-8")

        # Archives and templates that must never appear in the graph.
        (self.vault / "prompts").mkdir(exist_ok=True)
        (self.vault / "prompts" / "P999.md").write_text("archive", encoding="utf-8")
        (self.tasks / "_TASK_TEMPLATE.md").write_text("tpl", encoding="utf-8")

        self.hub = FakeHub()
        self.state = WebState(hub=self.hub, session_tail=5)

    def tearDown(self):
        self.tmp.cleanup()


class WebStateTestCase(VaultTestCase):
    def test_drain_hub_and_own_events(self):
        self.hub.events.append({"seq": 1, "tag": "m4", "kind": "run", "text": "M4::hello"})
        self.hub.events.append({"seq": 2, "tag": "m4", "kind": "line", "text": "working"})
        self.state.push_task_line("Task_Demo", "dispatch output")
        drained = self.state.drain()
        self.assertEqual(len(drained), 3)
        sessions = self.state.sessions()
        self.assertIn("m4", sessions)
        self.assertEqual(sessions["m4"][0]["text"], "M4::hello")
        self.assertEqual(sessions["Task_Demo"][0]["text"], "dispatch output")

    def test_drain_cursor_is_sticky(self):
        self.hub.events.append({"seq": 1, "tag": "m1", "kind": "line", "text": "a"})
        self.assertEqual(len(self.state.drain()), 1)
        self.assertEqual(len(self.state.drain()), 0)
        self.hub.events.append({"seq": 2, "tag": "m1", "kind": "line", "text": "b"})
        self.assertEqual(len(self.state.drain()), 1)

    def test_session_tail_is_capped(self):
        for i in range(8):
            self.state.push_usermsg("m1", f"line {i}")
        self.state.drain()
        sess = self.state.sessions()["m1"]
        self.assertEqual(len(sess), 5)
        self.assertEqual(sess[0]["text"], "line 3")

    def test_prefs_max_six_and_valid_layout(self):
        prefs = self.state.update_prefs({
            "layout": "9",
            "agents_visible": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"],
        })
        self.assertEqual(prefs["layout"], "4")
        self.assertEqual(len(prefs["agents_visible"]), 6)


class VaultGraphTestCase(VaultTestCase):
    def test_graph_excludes_archives_and_templates(self):
        graph = vgraph.build_graph(self.vault)
        names = [n["name"] for n in graph["nodes"]]
        self.assertIn("Task_Demo", names)
        self.assertNotIn("P999", names)
        self.assertNotIn("_TASK_TEMPLATE", names)
        self.assertTrue(any(n["name"] == "System_Core" and n["degree"] >= 1
                            for n in graph["nodes"]))

    def test_graph_includes_root_nodes(self):
        root = self.vault / "Dashboard.md"
        root.write_text(make_node("Dashboard", "system", "[[System_Core]]"),
                        encoding="utf-8")
        graph = vgraph.build_graph(self.vault)
        dash = next((n for n in graph["nodes"] if n["name"] == "Dashboard"), None)
        self.assertIsNotNone(dash)
        self.assertEqual(dash["folder"], "root")

    def test_node_relationships_links_and_backlinks(self):
        rel = vgraph.node_relationships(self.vault, "System_Core")
        self.assertIn("Tasks_Home", [x["name"] for x in rel["links"]])
        self.assertIn("Vault_Map", [x["name"] for x in rel["backlinks"]])

    def test_find_node_missing_returns_none(self):
        self.assertIsNone(vgraph.find_node(self.vault, "Nope_Nope"))


class ApiTestCase(VaultTestCase):
    def setUp(self):
        super().setUp()
        from scripts.web_ui.server import create_app
        import scripts.web_ui.routes as routes_mod
        self.routes_mod = routes_mod
        self.real_hub = routes_mod.HUB
        # Point the routes module at the shared fake hub so dispatch/stop
        # never touch a real subprocess.
        self.orig_hub_attr = None
        routes_mod.HUB = self.hub
        self.app = create_app(vault=self.vault, state=self.state)
        self.ctx = TestClient(self.app)

    def tearDown(self):
        self.routes_mod.HUB = self.real_hub
        super().tearDown()

    def test_agents_endpoint(self):
        data = self.ctx.get("/api/agents").json()
        self.assertEqual(len(data["agents"]), 7)
        self.assertTrue(all(a["tag"] and a["name"] for a in data["agents"]))

    def test_dispatch_validates_prompt_and_target(self):
        r = self.ctx.post("/api/dispatch", json={"prompt": "", "agent": "m1"})
        self.assertEqual(r.status_code, 400)
        r = self.ctx.post("/api/dispatch", json={"prompt": "hi", "agent": "zzz"})
        self.assertEqual(r.status_code, 404)
        r = self.ctx.post("/api/dispatch", json={"prompt": "do it", "agent": "m4"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.hub.calls[-1], ("run", "do it", ["m4"]))

    def test_stop_endpoints(self):
        self.ctx.post("/api/stop/m4")
        self.assertIn(("terminate_agent", "m4"), self.hub.calls)
        self.ctx.post("/api/stop")
        self.assertIn(("terminate_all",), self.hub.calls)

    def test_tasks_list(self):
        tasks = self.ctx.get("/api/tasks").json()["tasks"]
        self.assertEqual([t["name"] for t in tasks], ["Task_Demo"])

    def test_assign_writes_frontmatter_and_status(self):
        res = self.ctx.post("/api/tasks/Task_Demo/assign", json={"agent": "matthew"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["assigned_agent"], "Agent_Matthew")
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("assigned_agent: Agent_Matthew", raw)
        self.assertIn("status: ready", raw)

    def test_assign_unknown_agent_404(self):
        r = self.ctx.post("/api/tasks/Task_Demo/assign", json={"agent": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_status_invalid_and_illegal_transition(self):
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "banana"})
        self.assertEqual(r.status_code, 400)
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "completed"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "ready"})
        self.assertEqual(r.status_code, 200)
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("status: ready", raw)

    def test_task_dispatch_argv(self):
        self.ctx.post("/api/tasks/Task_Demo/status", json={"status": "ready"})
        proc = mock.Mock()
        proc.pid = 4242
        proc.stdout = LineStream(["line one", "line two"])
        proc.wait.return_value = 0
        with mock.patch.object(self.routes_mod.subprocess, "Popen",
                               return_value=proc) as fake_popen:
            r = self.ctx.post("/api/tasks/Task_Demo/dispatch")
        self.assertEqual(r.status_code, 200)
        argv = fake_popen.call_args.args[0]
        self.assertEqual(argv[:2], [sys.executable, "-m"])
        self.assertIn("dispatch", argv)
        self.assertIn("--yes", argv)
        time.sleep(0.05)  # let the pump thread drain the fake stream
        proc.wait.assert_called_once()

    def test_task_dispatch_requires_ready(self):
        r = self.ctx.post("/api/tasks/Task_Demo/dispatch")
        self.assertEqual(r.status_code, 409)

    def test_vault_context(self):
        r = self.ctx.get("/api/vault/context/Task_Demo")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["root"], "Task_Demo")

    def test_logs_and_static_assets(self):
        self.assertEqual(self.ctx.get("/api/logs/orchestrator").status_code, 200)
        self.assertEqual(self.ctx.get("/api/logs/zzz").status_code, 404)
        index = self.ctx.get("/")
        self.assertIn(b"app.css", index.content)
        self.assertEqual(self.ctx.get("/static/app.css").status_code, 200)
        self.assertEqual(self.ctx.get("/static/app.js").status_code, 200)

    def test_prefs_roundtrip(self):
        data = self.ctx.post("/api/prefs", json={
            "layout": "6",
            "agents_visible": ["m1", "m2", "m3", "m4", "m5", "m6"],
        }).json()
        self.assertEqual(data["layout"], "6")
        self.assertEqual(self.ctx.get("/api/prefs").json()["layout"], "6")

    def test_events_endpoint(self):
        self.hub.events.append({"seq": 1, "tag": "m1", "kind": "line", "text": "x"})
        data = self.ctx.get("/api/events").json()
        self.assertEqual(len(data["events"]), 1)


if __name__ == "__main__":
    unittest.main()