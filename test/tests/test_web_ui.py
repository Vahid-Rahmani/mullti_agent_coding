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


if __name__ == "__main__":
    unittest.main()