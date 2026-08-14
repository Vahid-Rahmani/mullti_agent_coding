"""Active-workflow integration tests — Workflow Designer → Home → Runtime.

Proves the active workflow is the **single source of truth** for both the Home
agent windows (``/api/active-workflow``) and the Home runtime path
(``/api/dispatch`` → ``workflow_engine``):

    TEST 1  Home reflects the workflow nodes exactly
    TEST 2  Replacing the workflow removes obsolete nodes
    TEST 3  WorkflowNode.x/y is the canonical layout Home receives
    TEST 4  Dispatch runs the active workflow graph (never a plain agent list)
    TEST 5  Edge conditions (success/failure) route correctly
    TEST 6  Each node keeps its own configured model
    TEST 7  Switching the active workflow switches Home + Runtime together
    TEST 8  No stale graph survives a workflow switch

Storage is isolated in a temp dir (``ZOVA_WORKFLOWS``), the hub is a fake and
the engine dispatch is monkeypatched/captured — no real agent process ever
launches, and ``roles.json`` / ``opencode.json`` / AgentSpec are untouched.
"""

import json  # noqa: F401  (kept for parity with sibling test files)
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

import scripts.web_ui.routes as routes_mod  # noqa: E402
from scripts.core import workflow_engine as E  # noqa: E402
from scripts.core import workflows as W  # noqa: E402
from scripts.web_ui.server import create_app  # noqa: E402
from scripts.web_ui.state import WebState  # noqa: E402


# ---------------------------------------------------------------- helpers


class FakeHub:
    """Stand-in for RunHub: records calls, exposes telemetry (no subprocess)."""

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


class FakeDispatch:
    """Records (node.id, agent, model, prompt); returns success unless told."""

    def __init__(self, outcomes=None):
        self.calls: list[tuple] = []
        self.outcomes = outcomes or {}
        self.lock = threading.Lock()

    def __call__(self, node, prompt, state, repo_root):
        with self.lock:
            self.calls.append((node.id, node.agent, node.model, prompt))
        outcome = self.outcomes.get(node.id, "success")
        return E.DispatchResult(outcome, f"out-{node.id}")


def make_workflow(wid, nodes, edges, entry=None):
    return W.Workflow.from_dict({
        "id": wid,
        "name": wid,
        "nodes": nodes,
        "edges": edges,
        "entry": entry if entry is not None else [nodes[0]["id"]],
    })


def run_sync(workflow, dispatch_fn, initial_state=None):
    """Run a workflow to completion and return the runner (blocking helper)."""
    runner = E.WorkflowRunner(workflow, dispatch_fn=dispatch_fn)
    runner.start(initial_state)
    while not runner.finished:
        time.sleep(0.01)
    return runner


# ---------------------------------------------------------------- fixtures

NODE_M = {"id": "m", "label": "Matthew", "agent": "matthew", "kind": "agent", "x": 100, "y": 200}
NODE_A = {"id": "a", "label": "Alex", "agent": "alex", "kind": "agent", "x": 500, "y": 200}
NODE_S = {"id": "s", "label": "Sarah", "agent": "sarah", "kind": "agent", "x": 900, "y": 200}
NODE_E = {"id": "e", "label": "Elena", "agent": "elena", "kind": "agent", "x": 500, "y": 500}

WF_A = make_workflow("wf-a", [NODE_M, NODE_A, NODE_S],
                     [{"source": "m", "target": "a"}, {"source": "a", "target": "s"}])
WF_B = make_workflow("wf-b", [NODE_M, NODE_E], [{"source": "m", "target": "e"}])


class ActiveWorkflowApiTestCase(unittest.TestCase):
    """API-level: /api/active-workflow + /api/dispatch with a fake hub/engine."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wf_root = Path(self.tmp.name)
        self._env = os.environ.get("ZOVA_WORKFLOWS")
        os.environ["ZOVA_WORKFLOWS"] = str(self.wf_root)

        self.real_hub = routes_mod.HUB
        self.fake = FakeHub()
        routes_mod.HUB = self.fake

        self.real_start_run = E.start_run
        self.state = WebState(hub=self.fake)
        self.state.update_prefs({"active_workflow_id": None})  # clean slate

        vault = Path(self.tmp.name) / "vault"
        self.app = create_app(vault=vault, state=self.state)
        self.ctx = TestClient(self.app)

    def tearDown(self):
        self.state.update_prefs({"active_workflow_id": None})
        E.start_run = self.real_start_run
        routes_mod.HUB = self.real_hub
        if self._env is None:
            os.environ.pop("ZOVA_WORKFLOWS", None)
        else:
            os.environ["ZOVA_WORKFLOWS"] = self._env
        self.tmp.cleanup()

    def _activate(self, wid):
        r = self.ctx.put("/api/active-workflow", json={"workflow_id": wid})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _home(self):
        return self.ctx.get("/api/active-workflow").json()

    # TEST 1 — Home reflects workflow nodes ---------------------------------
    def test_home_reflects_workflow_nodes(self):
        W.save_workflow(WF_A, self.wf_root)
        self._activate("wf-a")
        data = self._home()
        self.assertEqual(data["active_workflow_id"], "wf-a")
        nodes = data["workflow"]["nodes"]
        self.assertEqual(len(nodes), 3, "Home receives exactly the workflow's 3 nodes")
        self.assertEqual([n["agent"] for n in nodes], ["matthew", "alex", "sarah"])
        self.assertEqual(len(data["workflow"]["edges"]), 2)

    # TEST 2 — replacing the workflow removes obsolete nodes -----------------
    def test_replacing_workflow_removes_obsolete_nodes(self):
        W.save_workflow(WF_A, self.wf_root)
        W.save_workflow(WF_B, self.wf_root)
        self._activate("wf-a")
        self.assertEqual(len(self._home()["workflow"]["nodes"]), 3)
        self._activate("wf-b")
        data = self._home()
        nodes = data["workflow"]["nodes"]
        self.assertEqual(len(nodes), 2, "Home shows exactly Matthew + Elena")
        agents = {n["agent"] for n in nodes}
        self.assertEqual(agents, {"matthew", "elena"})
        self.assertNotIn("alex", agents, "Alex must not remain active")
        self.assertNotIn("sarah", agents, "Sarah must not remain active")

    # TEST C — two nodes using the SAME agent are independent --------------
    def test_duplicate_agent_nodes_are_independent(self):
        wf = make_workflow("wf-dup", [
            {"id": "n1", "agent": "matthew", "kind": "agent", "label": "Matthew #1", "x": 100, "y": 100},
            {"id": "n2", "agent": "matthew", "kind": "agent", "label": "Matthew #2", "x": 500, "y": 100},
        ], [{"source": "n1", "target": "n2"}])
        W.save_workflow(wf, self.wf_root)
        self._activate("wf-dup")
        nodes = self._home()["workflow"]["nodes"]
        self.assertEqual(len(nodes), 2, "two workflow nodes → two Home windows")
        self.assertEqual({n["id"] for n in nodes}, {"n1", "n2"})
        self.assertTrue(all(n["agent"] == "matthew" for n in nodes),
                        "both windows reference the same agent key")
        # the runtime treats them as two separate graph nodes too
        d = FakeDispatch()
        run_sync(wf, d)
        self.assertEqual([c[0] for c in d.calls], ["n1", "n2"],
                         "each node dispatches independently (node id identity)")

    # TEST 3 — layout synchronization (WorkflowNode.x/y is canonical) -------
    def test_layout_synchronization(self):
        wf = make_workflow("wf-l", [
            {"id": "m", "agent": "matthew", "kind": "agent", "x": 100, "y": 200},
            {"id": "a", "agent": "alex", "kind": "agent", "x": 500, "y": 200},
        ], [{"source": "m", "target": "a"}])
        W.save_workflow(wf, self.wf_root)
        self._activate("wf-l")
        nodes = self._home()["workflow"]["nodes"]
        by_id = {n["id"]: n for n in nodes}
        self.assertEqual(by_id["m"]["x"], 100)
        self.assertEqual(by_id["m"]["y"], 200)
        self.assertEqual(by_id["a"]["x"], 500)
        self.assertEqual(by_id["a"]["y"], 200)

    # TEST 4 — runtime uses the active workflow graph, not a plain agent list
    def test_dispatch_runs_active_workflow_not_hub(self):
        W.save_workflow(WF_A, self.wf_root)
        self._activate("wf-a")
        captured = {}

        def fake_start(wf, initial_state=None, dispatch_fn=None, repo_root=None):
            captured["wf"] = wf
            captured["state"] = initial_state
            return "run-abc"

        E.start_run = fake_start
        r = self.ctx.post("/api/dispatch", json={"prompt": "hello matthew"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["mode"], "workflow")
        self.assertEqual(r.json()["workflow_id"], "wf-a")
        self.assertEqual(r.json()["run_id"], "run-abc")
        self.assertEqual([n.agent for n in captured["wf"].nodes],
                         ["matthew", "alex", "sarah"])
        self.assertEqual(captured["state"], {"user_prompt": "hello matthew"})
        # the plain single-agent hub path must NOT have been used
        self.assertFalse(any(c[0] == "run" for c in self.fake.calls),
                         "HUB.run must not be called when a workflow is active")

    def test_dispatch_without_active_workflow_keeps_hub_path(self):
        r = self.ctx.post("/api/dispatch", json={"prompt": "do it", "agent": "m4"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.fake.calls[-1], ("run", "do it", ["m4"]))

    # TEST 7/8 — switching the active workflow switches Home + Runtime -------
    def test_switching_active_workflow_and_no_stale_graph(self):
        W.save_workflow(WF_A, self.wf_root)
        W.save_workflow(WF_B, self.wf_root)

        self._activate("wf-a")
        self.assertEqual(self._home()["workflow"]["id"], "wf-a")
        captured = {}

        def fake_start(wf, initial_state=None, dispatch_fn=None, repo_root=None):
            captured["id"] = wf.id
            return "run-x"

        E.start_run = fake_start
        self.ctx.post("/api/dispatch", json={"prompt": "go"})
        self.assertEqual(captured["id"], "wf-a")

        # switch to B: Home AND Runtime must both use B
        self._activate("wf-b")
        data = self._home()
        self.assertEqual(data["workflow"]["id"], "wf-b")
        agents = {n["agent"] for n in data["workflow"]["nodes"]}
        self.assertEqual(agents, {"matthew", "elena"}, "old wf-a nodes are gone")
        self.ctx.post("/api/dispatch", json={"prompt": "go"})
        self.assertEqual(captured["id"], "wf-b")

    def test_activate_unknown_workflow_404(self):
        r = self.ctx.put("/api/active-workflow", json={"workflow_id": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_clear_active_workflow(self):
        W.save_workflow(WF_A, self.wf_root)
        self._activate("wf-a")
        self.assertIsNotNone(self._home()["workflow"])
        r = self.ctx.delete("/api/active-workflow")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(self._home()["workflow"])

    def test_dispatch_invalid_active_workflow_is_409_not_fallback(self):
        # active id points at a missing workflow → error, never a silent fallback
        self.state.update_prefs({"active_workflow_id": "missing"})
        r = self.ctx.post("/api/dispatch", json={"prompt": "go"})
        self.assertEqual(r.status_code, 409)
        self.assertFalse(any(c[0] == "run" for c in self.fake.calls),
                         "must not silently fall back to the plain hub path")


class ActiveWorkflowRuntimeTestCase(unittest.TestCase):
    """Engine-level: the runtime resolves the same workflow graph the designer
    saves — structure, edge conditions, per-node models, and the user prompt."""

    # TEST 4 — runtime resolves the sequential graph ------------------------
    def test_runtime_resolves_sequential_graph(self):
        d = FakeDispatch()
        run_sync(WF_A, d, initial_state={"user_prompt": "hello matthew"})
        self.assertEqual([c[0] for c in d.calls], ["m", "a", "s"],
                         "runtime executes Matthew → Alex → Sarah in order")
        # the Home command is the primary task for every node
        for _nid, _agent, _model, prompt in d.calls:
            self.assertIn("hello matthew", prompt)

    # TEST 5 — edge conditions route correctly ------------------------------
    def test_edge_conditions_route(self):
        wf = make_workflow("wf-cond", [
            {"id": "a", "agent": "matthew", "kind": "agent"},
            {"id": "b", "agent": "alex", "kind": "agent"},
            {"id": "c", "agent": "sarah", "kind": "agent"},
        ], [
            {"source": "a", "target": "b", "condition": "success"},
            {"source": "a", "target": "c", "condition": "failure"},
        ])

        # success branch
        d = FakeDispatch()
        run_sync(wf, d)
        self.assertIn("a", [c[0] for c in d.calls])
        self.assertIn("b", [c[0] for c in d.calls], "success edge fires")
        self.assertNotIn("c", [c[0] for c in d.calls], "failure edge must not fire")

        # failure branch
        d2 = FakeDispatch(outcomes={"a": "failure"})
        run_sync(wf, d2)
        self.assertNotIn("b", [c[0] for c in d2.calls], "success edge must not fire")
        self.assertIn("c", [c[0] for c in d2.calls], "failure edge fires")

    # TEST 6 — per-node model ------------------------------------------------
    def test_per_node_models_are_preserved(self):
        wf = make_workflow("wf-model", [
            {"id": "m", "agent": "matthew", "kind": "agent", "model": "opencode/big-pickle"},
            {"id": "a", "agent": "alex", "kind": "agent", "model": ""},          # Auto
            {"id": "s", "agent": "sarah", "kind": "agent",
             "model": "ollama/qwen2.5-coder:7b"},
        ], [{"source": "m", "target": "a"}, {"source": "a", "target": "s"}])
        d = FakeDispatch()
        run_sync(wf, d, initial_state={"user_prompt": "build it"})
        models = {nid: model for nid, _agent, model, _prompt in d.calls}
        self.assertEqual(models["m"], "opencode/big-pickle")
        self.assertEqual(models["a"], "", "Auto passes through for runtime resolution")
        self.assertEqual(models["s"], "ollama/qwen2.5-coder:7b")

    # TEST 7 — switching changes the runtime graph too ------------------------
    def test_switching_workflow_changes_runtime_graph(self):
        d1 = FakeDispatch()
        run_sync(WF_A, d1)
        self.assertEqual([c[0] for c in d1.calls], ["m", "a", "s"])
        d2 = FakeDispatch()
        run_sync(WF_B, d2)
        self.assertEqual([c[0] for c in d2.calls], ["m", "e"],
                         "runtime follows the newly active workflow")
        self.assertNotIn("a", [c[0] for c in d2.calls], "no stale graph nodes")


if __name__ == "__main__":
    unittest.main()
