"""Workflow execution engine tests — graph semantics via an injected fake dispatch.

Never spawns opencode. A fake ``dispatch_fn`` records (node, model, prompt) and
returns a controlled outcome, so we can assert ordering, parallelism, fan-in,
conditional routing, bounded retry loops, disabled-node skipping, and
per-node model resolution — all without touching AgentSpec / roles.json /
opencode.json.
"""

import os
import sys
import threading
import time
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import workflow_engine as E  # noqa: E402
from scripts.core import workflows as W  # noqa: E402


def run_sync(workflow, dispatch_fn, initial_state=None):
    """Run a workflow to completion and return the runner (blocking helper)."""
    runner = E.WorkflowRunner(workflow, dispatch_fn=dispatch_fn)
    runner.start(initial_state)
    while not runner.finished:
        time.sleep(0.01)
    return runner


class FakeDispatch:
    """Records calls; returns success unless told otherwise."""

    def __init__(self, outcomes=None):
        self.calls = []  # (node.id, node.agent, node.model, prompt)
        self.outcomes = outcomes or {}  # node id -> "failure"
        self.lock = threading.Lock()

    def __call__(self, node, prompt, state, repo_root):
        with self.lock:
            self.calls.append((node.id, node.agent, node.model, prompt))
        outcome = self.outcomes.get(node.id, "success")
        return E.DispatchResult(outcome, f"out-{node.id}")


class TestSequential(unittest.TestCase):
    def test_nodes_run_in_order(self):
        wf = W.get_template("sequential")
        d = FakeDispatch()
        r = run_sync(wf, d)
        self.assertEqual([c[0] for c in d.calls],
                         ["architect", "developer", "tester", "reviewer"])
        self.assertEqual(set(r.snapshot()["statuses"].values()), {"completed"})


class TestParallel(unittest.TestCase):
    def test_fanout_runs_concurrently(self):
        wf = W.get_template("parallel")
        barrier = threading.Barrier(3, timeout=3)  # backend/frontend/security in flight

        def dispatch(node, prompt, state, repo_root):
            if node.id in ("backend", "frontend", "security"):
                try:
                    barrier.wait()  # blocks unless all three run in parallel
                except threading.BrokenBarrierError:
                    return E.DispatchResult("failure", "not parallel")
            return E.DispatchResult("success", node.id)

        r = run_sync(wf, dispatch)
        self.assertEqual(r.snapshot()["statuses"]["reviewer"], "completed")


class TestFanIn(unittest.TestCase):
    def test_merge_waits_for_all_branches(self):
        wf = W.Workflow.from_dict({
            "id": "fanin", "nodes": [
                {"id": "a", "agent": "matthew", "kind": "agent"},
                {"id": "b", "agent": "alex", "kind": "agent"},
                {"id": "c", "agent": "sarah", "kind": "agent"},
                {"id": "d", "agent": "david", "kind": "agent"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "a", "target": "c"},
                {"source": "b", "target": "d"},
                {"source": "c", "target": "d"},
            ],
            "entry": ["a"],
        })
        d = FakeDispatch()
        r = run_sync(wf, d)
        order = [c[0] for c in d.calls]
        self.assertEqual(order[0], "a")
        self.assertIn("b", order)
        self.assertIn("c", order)
        self.assertEqual(order[-1], "d")  # d runs after both b and c


class TestConditional(unittest.TestCase):
    def _wf(self):
        return W.Workflow.from_dict({
            "id": "cond", "nodes": [
                {"id": "router", "agent": "matthew", "kind": "agent"},
                {"id": "reviewer", "agent": "alex", "kind": "agent"},
                {"id": "developer", "agent": "sarah", "kind": "agent"},
            ],
            "edges": [
                {"source": "router", "target": "reviewer", "condition": "success"},
                {"source": "router", "target": "developer", "condition": "failure"},
            ],
            "entry": ["router"],
        })

    def test_success_routes_to_success_branch(self):
        r = run_sync(self._wf(), FakeDispatch({"router": "success"}))
        snap = r.snapshot()
        self.assertEqual(snap["statuses"]["reviewer"], "completed")
        self.assertEqual(snap["statuses"]["developer"], "skipped")

    def test_failure_routes_to_failure_branch(self):
        r = run_sync(self._wf(), FakeDispatch({"router": "failure"}))
        snap = r.snapshot()
        self.assertEqual(snap["statuses"]["developer"], "completed")
        self.assertEqual(snap["statuses"]["reviewer"], "skipped")


class TestRetryLoop(unittest.TestCase):
    def test_loop_is_bounded_by_max_iterations(self):
        wf = W.get_template("reflection")
        d = FakeDispatch({"reviewer": "failure"})  # reviewer always fails
        r = run_sync(wf, d)
        snap = r.snapshot()
        self.assertEqual(snap["statuses"]["developer"], "failed")
        self.assertEqual(snap["reason"]["developer"], "loop limit exceeded")
        # developer re-ran up to max_iterations (3), then hit the limit on the 4th
        self.assertEqual(r.visits["developer"], 4)

    def test_loop_exits_on_success(self):
        wf = W.get_template("reflection")
        d = FakeDispatch({"reviewer": "failure"})
        # first review fails, second passes -> developer re-runs once, then done
        calls = {"n": 0}

        def dispatch(node, prompt, state, repo_root):
            if node.id == "reviewer":
                calls["n"] += 1
                if calls["n"] == 1:
                    return E.DispatchResult("failure", "retry")
                return E.DispatchResult("success", "ok")
            return E.DispatchResult("success", "work")

        r = run_sync(wf, dispatch)
        snap = r.snapshot()
        self.assertEqual(snap["statuses"]["done"], "completed")
        self.assertEqual(r.visits["developer"], 2)
        self.assertEqual(r.visits["reviewer"], 2)


class TestDisabledNode(unittest.TestCase):
    def test_disabled_node_not_executed_and_blocks_downstream(self):
        wf = W.Workflow.from_dict({
            "id": "dis", "nodes": [
                {"id": "a", "agent": "matthew", "kind": "agent"},
                {"id": "b", "agent": "alex", "kind": "agent", "enabled": False},
                {"id": "c", "agent": "sarah", "kind": "agent"},
            ],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
            "entry": ["a"],
        })
        d = FakeDispatch()
        r = run_sync(wf, d)
        self.assertEqual([c[0] for c in d.calls], ["a"])  # b never dispatched
        snap = r.snapshot()
        self.assertEqual(snap["statuses"]["b"], "disabled")
        self.assertEqual(snap["statuses"]["c"], "skipped")


class TestModelResolution(unittest.TestCase):
    def test_same_agent_multiple_nodes_different_models(self):
        wf = W.Workflow.from_dict({
            "id": "multi", "nodes": [
                {"id": "d1", "label": "Developer #1", "agent": "matthew",
                 "kind": "agent", "model": "google/gemini-2.5-flash"},
                {"id": "d2", "label": "Developer #2", "agent": "matthew",
                 "kind": "agent", "model": "opencode/deepseek-v4-flash-free"},
                {"id": "d3", "label": "Developer #3", "agent": "matthew",
                 "kind": "agent", "model": "ollama/qwen2.5-coder:7b"},
            ],
            "edges": [],
            "entry": ["d1", "d2", "d3"],
        })
        d = FakeDispatch()
        r = run_sync(wf, d)
        by_node = {c[0]: c for c in d.calls}
        self.assertEqual(by_node["d1"][2], "google/gemini-2.5-flash")
        self.assertEqual(by_node["d2"][2], "opencode/deepseek-v4-flash-free")
        self.assertEqual(by_node["d3"][2], "ollama/qwen2.5-coder:7b")
        # all three reference the same agent identity
        self.assertEqual({c[1] for c in d.calls}, {"matthew"})

    def test_empty_model_is_auto(self):
        wf = W.Workflow.from_dict({
            "id": "auto", "nodes": [{"id": "a", "agent": "matthew", "kind": "agent"}],
            "edges": [], "entry": ["a"],
        })
        d = FakeDispatch()
        run_sync(wf, d)
        self.assertEqual(d.calls[0][2], "")  # no explicit override → Auto


class TestStateIsolation(unittest.TestCase):
    def test_outputs_recorded_and_initial_state_merged(self):
        wf = W.Workflow.from_dict({
            "id": "state", "nodes": [
                {"id": "a", "agent": "matthew", "kind": "agent"},
                {"id": "b", "agent": "alex", "kind": "agent"},
            ],
            "edges": [{"source": "a", "target": "b"}],
            "entry": ["a"], "state": {"base": "x"},
        })
        d = FakeDispatch()
        r = run_sync(wf, d, initial_state={"extra": "y"})
        state = r.snapshot()["state"]
        self.assertEqual(state["base"], "x")
        self.assertEqual(state["extra"], "y")
        self.assertEqual(state["a"], "out-a")
        self.assertEqual(state["b"], "out-b")


class TestDryRun(unittest.TestCase):
    """Dry-run previews the plan via the same scheduler without dispatching."""

    def test_dry_run_reports_waves_for_parallel_fanout_and_fanin(self):
        wf = W.get_template("parallel-specialists")
        plan = E.simulate_workflow(wf)
        self.assertEqual(plan["waves"][0], ["planner"])
        self.assertEqual(set(plan["waves"][1]), {"researcher", "developer", "analyst"})
        self.assertEqual(plan["waves"][2], ["aggregator"])
        self.assertEqual(set(plan["statuses"].values()), {"completed"})

    def test_dry_run_lists_conditional_edges_and_loop_bound(self):
        wf = W.get_template("reflection")
        plan = E.simulate_workflow(wf)
        conds = {(e["source"], e["target"]): e["condition"]
                 for e in plan["conditional_edges"]}
        self.assertEqual(conds[("reviewer", "done")], "success")
        self.assertEqual(conds[("reviewer", "developer")], "failure")
        self.assertEqual(plan["max_iterations"], 3)
        self.assertEqual(plan["start_nodes"], ["developer"])

    def test_dry_run_disabled_node_skips_downstream(self):
        wf = W.Workflow.from_dict({
            "id": "dry-dis", "nodes": [
                {"id": "a", "agent": "matthew", "kind": "agent"},
                {"id": "b", "agent": "alex", "kind": "agent", "enabled": False},
                {"id": "c", "agent": "sarah", "kind": "agent"},
            ],
            "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}],
            "entry": ["a"],
        })
        plan = E.simulate_workflow(wf)
        self.assertEqual(plan["statuses"]["a"], "completed")
        self.assertEqual(plan["statuses"]["b"], "disabled")
        self.assertEqual(plan["statuses"]["c"], "skipped")

    def test_dry_run_uses_no_op_dispatch(self):
        # simulate_workflow must never call the real (subprocess) dispatch
        wf = W.get_template("sequential")
        plan = E.simulate_workflow(wf)
        self.assertEqual(len(plan["waves"]), 4)
        self.assertNotIn("outputs", plan)  # plan shape, not a run snapshot


class TestPromptComposition(unittest.TestCase):
    def test_build_node_prompt_includes_roles_instructions_state(self):
        node = W.WorkflowNode(id="a", agent="matthew", roles=["python-developer"],
                              instructions="Implement feature X.", model="")
        prompt = E.build_node_prompt(node, {"k": "v"})
        self.assertIn("Python Developer", prompt)          # role context
        self.assertIn("Implement feature X.", prompt)       # instructions
        self.assertIn("Workflow state", prompt)             # state injected

    def test_node_roles_override_agent_assignments(self):
        node = W.WorkflowNode(id="a", agent="matthew", roles=["security-engineer"])
        prompt = E.build_node_prompt(node, {})
        self.assertIn("Security Engineer", prompt)
        self.assertNotIn("Python Developer", prompt)


if __name__ == "__main__":
    unittest.main()
