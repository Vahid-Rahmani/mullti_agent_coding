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

    def test_settings_endpoints(self):
        meta = self.ctx.get("/api/settings").json()
        self.assertIn("connections", meta["sections"])
        self.assertTrue(any(p["id"] == "google" for p in meta["simple_providers"]))
        conns = self.ctx.get("/api/settings/connections").json()["providers"]
        self.assertTrue(any(c["id"] == "google" and "configured" in c for c in conns))
        self.assertTrue(all("key" not in c for c in conns), "keys must never leave the backend")

    def test_settings_endpoint_validation(self):
        r = self.ctx.post("/api/settings/connections/test", json={"provider": "zzz"})
        self.assertEqual(r.status_code, 404)
        # invalid inputs are rejected before any file write
        r = self.ctx.post("/api/settings/models", json={"agent": "zzz", "model": "opencode/x"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/settings/models", json={"agent": "matthew", "model": "no-slash"})
        self.assertEqual(r.status_code, 409)
        r = self.ctx.post("/api/settings/agents/matthew/mode", json={"mode": "architect"})
        self.assertEqual(r.status_code, 409)

    def test_settings_roles_and_profile_endpoints(self):
        meta = self.ctx.get("/api/settings").json()
        self.assertIn("roles", meta["sections"])
        self.assertIn("profile", meta["sections"])
        roles_data = self.ctx.get("/api/settings/roles").json()
        self.assertIn("roles", roles_data)
        self.assertIn("assignments", roles_data)
        self.assertTrue(any(r["id"] == "python-developer" for r in roles_data["roles"]))
        agent_roles = self.ctx.get("/api/settings/agents/matthew/roles").json()
        self.assertIn("role_ids", agent_roles)
        profile = self.ctx.get("/api/settings/profile").json()
        self.assertIn("technologies", profile)
        self.assertIn("suggested_roles", profile)
        # each suggested role carries a reason (why it was suggested)
        for sr in profile["suggested_roles"]:
            self.assertIn("id", sr)
            self.assertIn("reason", sr)

    def test_settings_role_assignment_rejects_unknown(self):
        r = self.ctx.put("/api/settings/agents/matthew/roles",
                         json={"role_ids": ["does-not-exist"]})
        self.assertEqual(r.status_code, 409)

    def test_task_role_override_endpoint(self):
        # valid predefined role -> written to the temp task node frontmatter
        r = self.ctx.put("/api/tasks/Task_Demo/role",
                         json={"role": "python-developer"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "python-developer")
        raw = self.task_path.read_text(encoding="utf-8")
        self.assertIn("role: python-developer", raw)
        # unknown role -> 409, no write
        r = self.ctx.put("/api/tasks/Task_Demo/role", json={"role": "nope"})
        self.assertEqual(r.status_code, 409)
        # clear -> empty override
        r = self.ctx.put("/api/tasks/Task_Demo/role", json={"role": None})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["role"], "")


class WorkflowApiTestCase(VaultTestCase):
    """Workflow REST endpoints, isolated via $ZOVA_WORKFLOWS temp dir."""

    def setUp(self):
        super().setUp()
        self.wf_dir = Path(self.tmp.name) / "workflows"
        self.wf_dir.mkdir(parents=True)
        self._orig_zova_wf = os.environ.get("ZOVA_WORKFLOWS")
        os.environ["ZOVA_WORKFLOWS"] = str(self.wf_dir)
        from scripts.web_ui.server import create_app
        import scripts.web_ui.routes as routes_mod
        self.routes_mod = routes_mod
        self.real_hub = routes_mod.HUB
        routes_mod.HUB = self.hub
        self.app = create_app(vault=self.vault, state=self.state)
        self.ctx = TestClient(self.app)

    def tearDown(self):
        self.routes_mod.HUB = self.real_hub
        if self._orig_zova_wf is None:
            os.environ.pop("ZOVA_WORKFLOWS", None)
        else:
            os.environ["ZOVA_WORKFLOWS"] = self._orig_zova_wf
        super().tearDown()

    def _wf(self, **overrides):
        body = {
            "id": "test-wf", "name": "Test",
            "nodes": [{"id": "a", "agent": "matthew", "kind": "agent"},
                      {"id": "b", "agent": "alex", "kind": "agent"}],
            "edges": [{"source": "a", "target": "b"}],
            "entry": ["a"],
        }
        body.update(overrides)
        return body

    def test_workspace_route_served(self):
        r = self.ctx.get("/workspace")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Agent Workspace", r.content)
        self.assertIn(b"workspace.js", r.content)

    def test_workflow_crud(self):
        self.assertEqual(self.ctx.get("/api/workflows").json()["workflows"], [])
        r = self.ctx.put("/api/workflows/test-wf", json=self._wf())
        self.assertEqual(r.status_code, 200)
        got = self.ctx.get("/api/workflows/test-wf").json()["workflow"]
        self.assertEqual(got["id"], "test-wf")
        self.assertEqual(len(self.ctx.get("/api/workflows").json()["workflows"]), 1)
        self.assertTrue(self.ctx.delete("/api/workflows/test-wf").json()["deleted"])

    def test_workflow_save_rejects_invalid_id(self):
        # an unsafe/invalid id is rejected before any file write. (Traversal
        # forms like "../x", "a/b", "a\b" are covered directly in
        # test_workflows.TestIds against normalize_workflow_id, the boundary
        # the handler delegates to.)
        r = self.ctx.put("/api/workflows/-bad", json=self._wf(id="-bad"))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.ctx.get("/api/workflows").json()["workflows"], [])

    def test_workflow_validate(self):
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        r = self.ctx.get("/api/workflows/test-wf/validate").json()
        self.assertTrue(r["valid"])
        # invalid: unconditional cycle
        bad = self._wf(edges=[{"source": "a", "target": "b"},
                              {"source": "b", "target": "a"}])
        self.ctx.put("/api/workflows/test-wf", json=bad)
        r = self.ctx.get("/api/workflows/test-wf/validate").json()
        self.assertFalse(r["valid"])
        self.assertTrue(any("cycle" in e["message"] for e in r["errors"]))

    def test_workflow_templates_and_recommend(self):
        templates = self.ctx.get("/api/workflows/templates").json()["templates"]
        self.assertIn("sequential", templates)
        seq = self.ctx.post("/api/workflows/from-template/sequential").json()["workflow"]
        self.assertEqual([n["id"] for n in seq["nodes"]],
                         ["architect", "developer", "tester", "reviewer"])
        rec = self.ctx.get("/api/workflows/recommend?agents=4").json()
        self.assertIn("workflow", rec)
        self.assertIn("reasons", rec)
        self.assertEqual(self.ctx.post("/api/workflows/from-template/nope").status_code, 404)

    def test_workflow_run_validation_and_start(self):
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        # invalid graph -> 409 before any run
        bad = self._wf(edges=[{"source": "a", "target": "b"},
                              {"source": "b", "target": "a"}])
        self.ctx.put("/api/workflows/test-wf", json=bad)
        self.assertEqual(self.ctx.post("/api/workflows/test-wf/run",
                                       json={"initial_state": {}}).status_code, 409)
        # valid graph -> start_run is called (real dispatch stubbed out)
        self.ctx.put("/api/workflows/test-wf", json=self._wf())
        with mock.patch.object(self.routes_mod.workflow_engine, "start_run",
                               return_value="run-abc") as start:
            r = self.ctx.post("/api/workflows/test-wf/run",
                              json={"initial_state": {"x": 1}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["run_id"], "run-abc")
        start.assert_called_once()
        # run status endpoint 404 for an unknown run
        self.assertEqual(self.ctx.get("/api/workflows/runs/nope").status_code, 404)

    def test_workflow_dry_run_previews_without_dispatching(self):
        body = self._wf(nodes=[
            {"id": "a", "agent": "matthew", "kind": "agent"},
            {"id": "b", "agent": "alex", "kind": "agent"},
            {"id": "c", "agent": "sarah", "kind": "agent"},
        ], edges=[{"source": "a", "target": "b"}, {"source": "a", "target": "c"}],
            entry=["a"])
        with mock.patch.object(self.routes_mod.workflow_engine, "start_run") as start:
            r = self.ctx.post("/api/workflows/test-wf/dry-run", json=body)
        self.assertEqual(r.status_code, 200)
        plan = r.json()
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["waves"][0], ["a"])
        self.assertEqual(set(plan["waves"][1]), {"b", "c"})
        self.assertEqual(set(plan["statuses"].values()), {"completed"})
        start.assert_not_called()   # a dry-run never starts a real run

    def test_workflow_dry_run_rejects_invalid_graph(self):
        body = self._wf(edges=[{"source": "a", "target": "b"},
                               {"source": "b", "target": "a"}])
        r = self.ctx.post("/api/workflows/test-wf/dry-run", json=body)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(any("cycle" in e["message"] for e in r.json()["detail"]["errors"]))


class UiAssetsTestCase(unittest.TestCase):
    """Static-asset checks for the dashboard UI (index.html / app.css / app.js)."""

    STATIC = Path(REPO_ROOT) / "scripts" / "web_ui" / "static"

    @classmethod
    def setUpClass(cls):
        cls.index = (cls.STATIC / "index.html").read_text(encoding="utf-8")
        cls.css = (cls.STATIC / "app.css").read_text(encoding="utf-8")
        cls.js = (cls.STATIC / "app.js").read_text(encoding="utf-8")

    def test_prompt_box_below_workspace_grid(self):
        ws = self.index.index('<main id="workspace"')
        grid = self.index.index('id="workspace-grid"', ws)
        box = self.index.index('id="prompt-box"', ws)
        self.assertGreater(box, grid, "prompt box must sit below the workspace grid")

    def test_prompt_box_elements(self):
        self.assertIn('id="prompt-input"', self.index)
        self.assertIn('<textarea', self.index)
        self.assertIn('id="prompt-send"', self.index)
        self.assertIn('id="prompt-target"', self.index)

    def test_toolbar_dispatch_removed(self):
        self.assertNotIn('id="dispatch-form"', self.index)
        self.assertNotIn('id="dispatch-input"', self.index)
        self.assertNotIn('id="dispatch-run"', self.index)

    def test_graph_zoom_controls_present(self):
        self.assertIn('id="zoom-in"', self.index)
        self.assertIn('id="zoom-out"', self.index)
        self.assertIn('id="zoom-reset"', self.index)

    def test_js_binds_prompt_box_and_zoom(self):
        self.assertIn('$("#prompt-box")', self.js)
        self.assertIn('$("#prompt-input")', self.js)
        self.assertIn("requestSubmit", self.js)
        self.assertIn("zoomBy(", self.js)
        self.assertIn("resetGraphView", self.js)
        self.assertIn('key === "Enter" && !e.shiftKey', self.js)
        self.assertIn('"graph-world"', self.js)

    def test_js_workspace_builds_into_grid(self):
        self.assertIn('$("#workspace-grid")', self.js)
        self.assertIn("wg.style.gridTemplateColumns", self.js)

    # ── Phase 23B: compact auto-grow prompt textarea ────────────────
    def test_prompt_autogrow_compact_default(self):
        self.assertIn("min-height: 56px", self.css)
        self.assertIn("max-height: 240px", self.css)
        self.assertIn("resize: none", self.css)
        self.assertIn('rows="2"', self.index)
        # autosize clamps between min and max and only scrolls at the cap
        self.assertIn("Math.min(240, Math.max(56, input.scrollHeight))", self.js)
        self.assertIn('input.style.overflowY = h >= 240 ? "auto" : "hidden"', self.js)
        # Enter=send / Shift+Enter=newline preserved
        self.assertIn('key === "Enter" && !e.shiftKey', self.js)

    # ── Phase 23B: graph mouse/touch panning ────────────────────────
    def test_graph_pan_handlers(self):
        for token in ("pointerdown", "pointermove", "pointerup", "pointercancel"):
            self.assertIn(token, self.js)
        self.assertIn("setPointerCapture", self.js)
        self.assertIn("releasePointerCapture", self.js)
        # pan delta converted to viewBox units and divided by current zoom
        self.assertIn("/ GraphView.scale", self.js)
        # middle-mouse pan tolerated, node-drag excluded
        self.assertIn("e.button !== 0 && e.button !== 1", self.js)
        self.assertIn('closest(".g-node")', self.js)
        # touch drag enabled on the canvas
        self.assertIn("touch-action: none", self.css)
        self.assertIn("cursor: grabbing", self.css)

    def test_drag_vs_click_guard(self):
        self.assertIn("if (panState.moved) { panState.moved = false; return; }", self.js)
        self.assertIn("panState.active", self.js)
        # zoom still cursor-anchored
        self.assertIn("zoomBy(Math.pow(1.15, -e.deltaY / 100), p.x, p.y)", self.js)

    # ── Phase 23B: readable node labels ─────────────────────────────
    def test_readable_node_labels(self):
        # halo-backed label font (readable over the edges)
        self.assertIn("font-size: 14px", self.css)
        self.assertIn("paint-order: stroke", self.css)
        self.assertIn("stroke: var(--bg)", self.css)
        # label position driven by the band-based LOD helper + truncation
        self.assertIn('lbl.setAttribute("y", GP.labelYOffset(r, band))', self.js)
        self.assertIn('lbl.classList.toggle("hidden"', self.js)
        self.assertNotIn("r + 12", self.js)
        self.assertIn("raw.length > 18 ? raw.slice(0, 16) +", self.js)

    # ── Phase 23B: zoom controls remain functional ──────────────────
    def test_zoom_controls_still_bound(self):
        self.assertIn('$("#zoom-in").addEventListener("click", () => zoomBy(1.3))', self.js)
        self.assertIn('$("#zoom-out").addEventListener("click", () => zoomBy(1 / 1.3))', self.js)
        self.assertIn('$("#zoom-reset").addEventListener("click", resetGraphView)', self.js)
        # zoom clamping lives in the shared graph-math camera (GP.zoomAtPoint)
        self.assertIn("GP.zoomAtPoint(", self.js)
        self.assertIn("zoomBy(", self.js)

    # ── Phase 24B: graph rebuild (layout, LOD, filters, core view) ──
    def test_graph_stage_and_filters_present(self):
        self.assertIn('id="graph-stage"', self.index)
        self.assertIn('id="graph-filters"', self.index)
        self.assertIn("refreshGraphView", self.js)
        self.assertIn("buildGraphFilters", self.js)
        self.assertIn("GP.applySectionFilter", self.js)
        self.assertIn("GP.coreGraph", self.js)
        self.assertIn("GP.presentFolders", self.js)
        self.assertIn("f-chip", self.css)

    def test_graph_band_culling_and_layout_plane(self):
        # edge culling on band change, hiding whole edge groups
        self.assertIn("GP.edgeVisibleFor(p, band, graphEls.byName, graphEls.sectionHubs)", self.js)
        self.assertIn('grp.style.display = show ? "" : "none"', self.js)
        # zoomed-out band hides everything but the section-hub spine
        self.assertIn('(band === "out" && !graphEls.sectionHubs[nd.name]) ? "none" : ""', self.js)
        self.assertIn("GP.sectionHubNames(nodes)", self.js)
        # layout runs in the larger section-aware world plane
        self.assertIn("GP.runLayout(nodes, edges, { iterations: 500 })", self.js)
        # band-specific edge weight/opacity in CSS
        self.assertIn('data-band="out"', self.css)
        self.assertIn('stroke-width: .5', self.css)
        self.assertIn('stroke-width: 1.1', self.css)

    # ── Phase 24D: graph window resize / detach / fullscreen ───────
    def test_graph_window_controls_present(self):
        for ident in ("graph-detach", "graph-fullscreen", "graph-restore",
                      "graph-vsplit", "graph-float", "graph-fresize"):
            self.assertIn(f'id="{ident}"', self.index)
        # the splitter sits between the graph panel and the related panel
        gp = self.index.index('id="graph-panel"')
        vs = self.index.index('id="graph-vsplit"', gp)
        rp = self.index.index('id="related-panel"', vs)
        self.assertLess(gp, vs)
        self.assertLess(vs, rp)
        # detach/restore are title-row icon buttons, restore starts hidden
        self.assertIn('id="graph-restore" class="icon-btn hidden"', self.index)

    def test_graph_window_js_hooks(self):
        for fn in ("detachGraph", "restoreGraph", "fullscreenGraph",
                   "reflowGraph", "saveGraphWindowState", "loadGraphWindowState"):
            self.assertIn(fn, self.js)
        self.assertIn("requestFullscreen", self.js)
        self.assertIn("fullscreenchange", self.js)
        self.assertIn('"#graph-float"', self.js)
        self.assertIn("graphWin.detached", self.js)
        self.assertIn('ssSet("graph.h"', self.js)
        # docked graph height restored from session storage at init
        self.assertIn('setProperty("--graph-h", loadGraphH() + "px")', self.js)
        # same DOM node is moved, so graph state survives detach
        self.assertIn("float.appendChild(panel)", self.js)
        self.assertIn("vsplit.parentNode.insertBefore(panel, vsplit)", self.js)

    def test_graph_window_css(self):
        self.assertIn(":fullscreen", self.css)
        self.assertIn("--graph-h", self.css)
        self.assertIn("#graph-panel.detached", self.css)
        self.assertIn("#graph-fresize", self.css)
        self.assertIn("nwse-resize", self.css)
        self.assertIn("row-resize", self.css)
        self.assertIn("cursor: move", self.css)
        self.assertIn("pointer-events: none", self.css)

    # ── Phase 25: settings modal (AI connections, models, modes) ─────
    def test_settings_assets(self):
        self.assertIn('id="settings-btn"', self.index)
        for ident in ("settings-backdrop", "settings-modal", "settings-nav",
                      "settings-content", "settings-close"):
            self.assertIn(f'id="{ident}"', self.index)
        self.assertIn('<script src="/static/settings.js"></script>', self.index)
        self.assertIn("window.MACSettings", self.js)  # settings.js loaded before app.js

    def test_settings_modal_css(self):
        for cls in (".settings-modal", ".settings-nav", ".conn-wizard",
                    ".sec-table", ".model-chips", ".adv-fields", ".verify-badge"):
            self.assertIn(cls, self.css)

    def test_roles_and_profile_settings_assets(self):
        """Roles + Repository-analysis sections are wired in settings.js."""
        settings_js = (self.STATIC / "settings.js").read_text(encoding="utf-8")
        for token in ("viewRoles", "viewProfile", "Create custom role",
                      "Agent role assignment", "Suggested roles",
                      "/api/settings/roles", "/api/settings/profile"):
            self.assertIn(token, settings_js)
        # role-detail styling exists for the role cards
        self.assertIn(".role-details", self.css)
        self.assertIn(".role-sub", self.css)

    def test_task_role_override_assets(self):
        """The task detail exposes a temporary role override (app.js)."""
        self.assertIn("role override", self.js)
        self.assertIn("/api/tasks/", self.js)
        self.assertIn("Set role override", self.js)

    def test_model_header_sync_and_searchable_combo(self):
        """Model header derives from current UI state; selector is searchable."""
        settings_js = (self.STATIC / "settings.js").read_text(encoding="utf-8")
        for token in ("modelCombo", "combo-search", "type to filter",
                      "ArrowDown", "ArrowUp", "Escape", "custom provider / model",
                      "refreshAgentModels"):
            self.assertIn(token, settings_js)
        # app.js refreshes the p-model header from Ag.agents[].model
        self.assertIn('card.querySelector(".p-model")', self.js)
        self.assertIn("refreshAgentModels", self.js)
        self.assertIn(".combo", self.css)

    # ── Agent-output session persistence (regression) ────────────────
    def test_agent_event_persists_session_before_panel_render(self):
        """onAgentEvent must persist into Ag.sessions[tag] BEFORE any DOM lookup,
        so events for agents without a rendered panel are never dropped."""
        js = self.js
        self.assertIn("Ag.sessions[tag] = Ag.sessions[tag] || []", js)
        self.assertIn("const card = panelEl(tag);", js)
        self.assertLess(
            js.index("Ag.sessions[tag] = Ag.sessions[tag] || []"),
            js.index("const card = panelEl(tag);"),
            "session persistence must precede the panel lookup")
        self.assertIn("if (!card) return;", js)
        # no wrap-and-drop path may remain inside onAgentEvent itself
        start = js.index("function onAgentEvent")
        end = js.index("function buildStatusTable")  # next function after it
        self.assertNotIn("if (card) {", js[start:end])

    def test_status_events_persisted_but_never_console_rows(self):
        """status events are persisted (never lost) but rendered only as dots,
        both live and on replay — session and DOM never diverge."""
        js = self.js
        self.assertIn("const PANEL_KINDS = [\"run\", \"line\", \"error\", \"usermsg\", \"taskline\"];", js)
        self.assertIn("if (PANEL_KINDS.includes(ev.kind) && !seen) {", js)
        self.assertIn("if (PANEL_KINDS.includes(ev.kind)) {", js)

    def test_agent_event_dedupe_and_tail(self):
        """Live events are de-duplicated by backend seq and capped by tail."""
        self.assertIn("e.n !== undefined && e.n === ev.n", self.js)
        self.assertIn("const SESSION_TAIL = 800;", self.js)

    def test_load_sessions_merges_never_replaces(self):
        """loadSessions merges the init snapshot over live events (never reverts
        already-received output)."""
        js = self.js
        self.assertIn("Merge, never replace", js)
        self.assertIn("Ag.sessions[tag] = merged;", js)

    def test_window_macapp_test_hook(self):
        """The headless test hook mirrors window.MACSettings."""
        self.assertIn("window.MACApp", self.js)

    def test_backend_restart_detection(self):
        """A backend restart resets WebState's "n" sequence; the frontend must
        detect the regression and clear the stale session mirror so the n-dedup
        never swallows the new process's output."""
        js = self.js
        self.assertIn("let lastBackendN = 0;", js)
        self.assertIn("function checkBackendRestart(snapN)", js)
        self.assertIn("Ag.sessions = {};", js)
        # pollState drives the detection on every /api/state poll
        self.assertIn("checkBackendRestart(snap.n)", js)


class WorkspaceAssetsTestCase(unittest.TestCase):
    """Static-asset checks for the Agent Workspace / workflow designer."""

    STATIC = Path(REPO_ROOT) / "scripts" / "web_ui" / "static"

    @classmethod
    def setUpClass(cls):
        cls.html = (cls.STATIC / "workspace.html").read_text(encoding="utf-8")
        cls.js = (cls.STATIC / "workspace.js").read_text(encoding="utf-8")
        cls.css = (cls.STATIC / "app.css").read_text(encoding="utf-8")
        cls.index = (cls.STATIC / "index.html").read_text(encoding="utf-8")

    def test_workspace_page_served_and_linked(self):
        # the page is linked from the dashboard topbar
        self.assertIn('href="/workspace"', self.index)
        self.assertIn("Agent Workspace", self.html)

    def test_workspace_layout_regions(self):
        for ident in ("ws-topbar", "ws-library", "ws-library-list", "ws-canvas",
                      "ws-world", "ws-edges", "ws-nodes", "ws-props",
                      "ws-props-body", "ws-run-legend"):
            self.assertIn(f'id="{ident}"', self.html)

    def test_workspace_controls(self):
        for ident in ("ws-new", "ws-save", "ws-validate", "ws-run",
                      "ws-run-cancel", "ws-template-select", "ws-recommend",
                      "ws-duplicate", "ws-delete", "ws-zoom-in", "ws-zoom-out",
                      "ws-zoom-reset"):
            self.assertIn(f'id="{ident}"', self.html)

    def test_workspace_js_model_independence(self):
        # a node carries agent/model/roles overrides, never touching AgentSpec
        for token in ("agent", "model", "roles", "instructions", "enabled"):
            self.assertIn(token, self.js)
        self.assertIn("Auto / runtime default", self.js)

    def test_workspace_js_canvas(self):
        for token in ("addNode", "renderEdges", "renderNodes", "onNodePointerDown",
                      "edgeKey", "select", "markDirty", "runWorkflow", "pollRun",
                      "validateWorkflow", "loadTemplate", "recommend"):
            self.assertIn(token, self.js)

    def test_workspace_css(self):
        for cls in (".ws-body", ".ws-topbar", ".ws-library", ".ws-canvas",
                    ".wf-node", ".wf-in", ".wf-out", ".ws-edge", ".ws-props",
                    ".st-completed", ".st-running", ".st-failed", ".st-skipped"):
            self.assertIn(cls, self.css)

    # ── model picker: searchable + display sync ─────────────────────
    def test_workspace_model_picker_searchable(self):
        for token in ("modelCombo", "combo-search", "type to filter (provider / model)",
                      "ArrowDown", "ArrowUp", "Escape", "custom provider / model"):
            self.assertIn(token, self.js)

    def test_workspace_model_selection_updates_display(self):
        # choosing a model writes node.model, marks dirty, and re-renders the card
        self.assertIn("node.model = value", self.js)
        self.assertIn("renderNodes()", self.js)
        # the node card's model line reads the live node.model (Auto when empty)
        self.assertIn('sub.textContent = n.model || "Auto / runtime default"', self.js)

    def test_workspace_model_auto_vs_explicit(self):
        # Auto is a real, selectable option distinct from an explicit override,
        # and reopening a node re-reads its persisted model
        self.assertIn('let value = node.model || ""', self.js)
        self.assertIn("combo-auto", self.js)
        self.assertIn("Auto → resolves to", self.js)
        self.assertIn(".combo-value.combo-auto", self.css)

    # ── v2: visual builder (add-agent, node design, dry-run, validation) ─
    def test_workspace_add_agent_and_search(self):
        self.assertIn('id="ws-add-agent"', self.html)
        self.assertIn('id="ws-agent-search"', self.html)
        self.assertIn("type to filter agents", self.html)
        self.assertIn("matchingAgents", self.js)

    def test_workspace_node_design(self):
        for token in ("wf-node-dot", "wf-node-agent", "wf-node-state",
                      "STATE_LABEL", "nodeState"):
            self.assertIn(token, self.js)
        self.assertIn(".wf-node-dot", self.css)
        self.assertIn(".wf-node-state", self.css)
        self.assertIn(".wf-node-agent", self.css)

    def test_workspace_dry_run_and_fit(self):
        self.assertIn('id="ws-dry-run"', self.html)
        self.assertIn("dryRunWorkflow", self.js)
        self.assertIn("fitToScreen", self.js)
        self.assertIn("/dry-run", self.js)

    def test_workspace_validation_display(self):
        self.assertIn('id="ws-validation"', self.html)
        self.assertIn("showValidation", self.js)
        self.assertIn("formatErrors", self.js)
        self.assertIn(".ws-validation", self.css)

    def test_workspace_presets(self):
        for label in ("Planner / Workers / Reviewer", "Parallel Specialists",
                      "Research / Analysis / Writer", "Empty Workflow",
                      "Developer / Reviewer / Retry"):
            self.assertIn(label, self.js)


if __name__ == "__main__":
    unittest.main()