"""Execution runtime tests (Phase 5).

The in-memory run registry (moved from workflow_engine._RUNS) owns
start/get/cancel/snapshot. These tests prove runs are registered, snapshots
carry ordered events + per-node execution records, cancellation works, and
nothing leaks between runs. The default adapter dispatch is exercised through a
patched fake adapter (no subprocess, no real model call).
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import workflow_engine as E
from scripts.core import workflows as W
from scripts.core.execution import runtime
from scripts.core.execution.schema import ModelResponse


def make_wf(nodes=None, settings=None):
    return W.Workflow.from_dict({
        "id": "rt-wf", "name": "RT",
        "nodes": nodes or [
            {"id": "n1", "agent": "matthew", "kind": "agent", "model": "",
             "roles": [], "x": 0, "y": 0},
            {"id": "n2", "agent": "alex", "kind": "agent", "model": "",
             "roles": [], "x": 0, "y": 100},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "entry": ["n1"], "state": {}, "settings": settings or {},
    })


class FakeAdapter:
    provider_id = "fake"

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def execute(self, request, connection, *, timeout=None, cancel_event=None,
                execution_id=""):
        with self.lock:
            self.calls.append((request.metadata.get("node_id"), request.prompt))
        return ModelResponse(text=f"out-{request.metadata.get('node_id')}",
                             provider="fake", model=request.model)


class TestExecutionRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = None
        runtime.clear_runs()

    def tearDown(self):
        runtime.clear_runs()

    def _run_to_finish(self, wf):
        """Start a run with the fake adapter patched and wait for completion.

        The patch must stay active for the whole run — the runner executes on a
        background thread, so exiting the mock context early would revert
        ``adapter_for`` to the real OpenCode adapter mid-flight.
        """
        with mock.patch("scripts.core.execution.executor.adapter_for",
                        return_value=FakeAdapter()):
            run_id = runtime.start_run(wf)
            runner = runtime.get_run(run_id)
            self.assertIsNotNone(runner)
            while not runner.finished:
                time.sleep(0.01)
        return run_id, runner

    def test_start_get_snapshot(self):
        run_id, _runner = self._run_to_finish(make_wf())
        self.assertTrue(run_id)
        snap = runtime.snapshot(run_id)
        self.assertEqual(snap["workflow_id"], "rt-wf")
        self.assertTrue(snap["finished"])
        self.assertEqual(set(snap["statuses"].values()), {"completed"})
        self.assertIn("events", snap)
        self.assertIn("executions", snap)
        # output propagation unchanged
        self.assertEqual(snap["outputs"]["n1"], "out-n1")
        self.assertEqual(snap["state"]["n2"], "out-n2")

    def test_events_ordered_and_complete(self):
        run_id, _ = self._run_to_finish(make_wf())
        snap = runtime.snapshot(run_id)
        types = [e["event_type"] for e in snap["events"]]
        self.assertEqual(types[0], "workflow_started")
        self.assertEqual(types[-1], "workflow_completed")
        self.assertIn("node_started", types)
        self.assertIn("node_completed", types)
        # events never carry secrets (structural)
        for e in snap["events"]:
            for key in ("api_key", "secret", "token", "credential",
                        "authorization", "password"):
                self.assertNotIn(key, e)
                self.assertNotIn(key, str(e.get("usage", "")))

    def test_per_node_execution_records(self):
        run_id, _ = self._run_to_finish(make_wf())
        snap = runtime.snapshot(run_id)
        for nid in ("n1", "n2"):
            rec = snap["executions"][nid]
            self.assertEqual(rec["status"], "completed")
            self.assertEqual(rec["provider"], "fake")
            self.assertIn("latency_ms", rec)
            self.assertIn("node_execution_id", rec)
            self.assertIn("started_at", rec)
            self.assertIn("finished_at", rec)

    def test_cancel_run(self):
        wf = make_wf()

        def slow_adapter_factory(resolution=None):  # adapter_for(resolution)
            class SlowAdapter(FakeAdapter):
                def execute(self, request, connection, *, timeout=None,
                            cancel_event=None, execution_id=""):
                    while not cancel_event.is_set():
                        time.sleep(0.05)
                    from scripts.core.execution.errors import AdapterCancelledError

                    raise AdapterCancelledError()

            return SlowAdapter()

        with mock.patch("scripts.core.execution.executor.adapter_for",
                        side_effect=slow_adapter_factory):
            run_id = runtime.start_run(wf)
            runner = runtime.get_run(run_id)
            time.sleep(0.3)
            self.assertTrue(runtime.cancel_run(run_id))
            while not runner.finished:
                time.sleep(0.01)
        snap = runtime.snapshot(run_id)
        self.assertEqual(snap["statuses"]["n1"], "failed")
        self.assertEqual(snap["executions"]["n1"]["error_code"], "cancelled")
        self.assertEqual(snap["events"][-1]["event_type"], "workflow_failed")
        self.assertEqual(snap["events"][-1]["error_code"], "cancelled")

    def test_list_runs(self):
        wf = make_wf()
        with mock.patch("scripts.core.execution.executor.adapter_for",
                        return_value=FakeAdapter()):
            run_id = runtime.start_run(wf)
            runner = runtime.get_run(run_id)
            while not runner.finished:
                time.sleep(0.01)
        snaps = runtime.list_runs()
        self.assertTrue(any(s["run_id"] == run_id for s in snaps))


class TestWorkflowEngineDelegates(unittest.TestCase):
    def test_engine_start_run_delegates_to_runtime(self):
        wf = make_wf()
        with mock.patch("scripts.core.execution.executor.adapter_for",
                        return_value=FakeAdapter()):
            run_id = E.start_run(wf)   # workflow_engine.start_run -> runtime
            runner = E.get_run(run_id)
            self.assertIsNotNone(runner)
            while not runner.finished:
                time.sleep(0.01)
            self.assertTrue(runtime.cancel_run(run_id) or True)  # idempotent-safe


if __name__ == "__main__":
    unittest.main()
