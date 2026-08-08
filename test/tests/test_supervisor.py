"""Unit tests for scripts/supervisor.py (web app supervisor + restart)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import supervisor
from self_evolve import SelfEvolveEngine


class BuildChildCmdTestCase(unittest.TestCase):
    """build_child_cmd produces the default web_app child argv."""

    def test_default_child_cmd(self):
        self.assertEqual(
            supervisor.build_child_cmd("python", 8501),
            ["python", "scripts/web_app.py", "--port", "8501", "--no-browser"],
        )


class DecideRelaunchTestCase(unittest.TestCase):
    """_decide_relaunch: marker parse, verify-on-marker, no-relaunch on failure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.marker = self.root / "_logs" / "restart.ctl"
        self.engine = SelfEvolveEngine(
            project_root=self.root,
            record_decision=mock.MagicMock(),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _write_marker(self, **payload):
        self.engine.write_restart_marker(control_path=self.marker, payload=payload)

    def test_no_marker_exits_cleanly_without_verify(self):
        with mock.patch.object(self.engine, "verify") as verify:
            self.assertFalse(supervisor._decide_relaunch(self.engine, self.marker))
        verify.assert_not_called()

    def test_marker_verify_pass_clears_marker_and_relaunches(self):
        self._write_marker(source="self-evolve", prompt="upgrade", ok=True)
        with mock.patch.object(
            self.engine, "verify", return_value={"ok": True, "stdout": "OK", "errors": []}
        ):
            self.assertTrue(supervisor._decide_relaunch(self.engine, self.marker))
        self.assertFalse(self.marker.exists())
        self.engine.record_decision.assert_not_called()

    def test_marker_verify_fail_records_rollback_and_no_relaunch(self):
        self._write_marker(source="self-evolve", prompt="upgrade", ok=True)
        with mock.patch.object(
            self.engine,
            "verify",
            return_value={"ok": False, "stdout": "", "errors": ["py_compile web_app.py failed"]},
        ):
            self.assertFalse(supervisor._decide_relaunch(self.engine, self.marker))
        # marker is left in place and a rollback decision is recorded
        self.assertTrue(self.marker.exists())
        self.engine.record_decision.assert_called_once()
        decision = self.engine.record_decision.call_args.args[0]
        self.assertIn("rollback", decision)
        self.assertIn("py_compile", decision)


class SupervisorLoopTestCase(unittest.TestCase):
    """run_supervisor drives spawn/wait/decide with a fake immediate-exit child."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.marker = self.root / "_logs" / "restart.ctl"
        self.engine = mock.MagicMock()

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_child(self):
        child = mock.MagicMock()
        child.poll.return_value = 0  # already exited
        child.returncode = 0
        return child

    def _run(self, watch=False, marker=None, engine=None, spawn=None):
        return supervisor.run_supervisor(
            child_cmd=["python", "x.py"],
            cwd=str(self.root),
            marker_path=marker or self.marker,
            engine=engine or self.engine,
            poll_interval=0,
            watch=watch,
            spawn=spawn or (lambda cmd, cwd: self._fake_child()),
            wait=lambda child, interval: child.returncode,
        )

    def _write_marker(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(json.dumps({"source": "self-evolve", "ok": True}), encoding="utf-8")

    def test_once_no_marker_exits_cleanly(self):
        self.engine.read_restart_marker.return_value = None
        self.assertEqual(self._run(), 0)
        self.engine.verify.assert_not_called()

    def test_once_verify_pass_clears_marker_and_relaunches_once(self):
        self._write_marker()
        self.engine.read_restart_marker.return_value = {"source": "self-evolve", "ok": True}
        self.engine.verify.return_value = {"ok": True, "stdout": "OK", "errors": []}
        self.assertEqual(self._run(), 1)
        self.assertFalse(self.marker.exists())

    def test_once_failed_verify_no_relaunch_and_rollback_recorded(self):
        self._write_marker()
        self.engine.read_restart_marker.return_value = {"source": "self-evolve", "prompt": "upgrade", "ok": True}
        self.engine.verify.return_value = {"ok": False, "stdout": "", "errors": ["boom"]}
        self.assertEqual(self._run(), 0)
        self.assertTrue(self.marker.exists())
        self.engine.record_decision.assert_called_once()

    def test_watch_relaunches_then_exits_cleanly_on_no_marker(self):
        self._write_marker()
        self.engine.read_restart_marker.side_effect = [
            {"source": "self-evolve", "ok": True},  # first exit: relaunch
            None,  # second exit: no marker -> clean exit
        ]
        self.engine.verify.return_value = {"ok": True, "stdout": "OK", "errors": []}
        spawned = []

        def spawn(cmd, cwd):
            spawned.append(cmd)
            return self._fake_child()

        result = supervisor.run_supervisor(
            child_cmd=["python", "x.py"],
            cwd=str(self.root),
            marker_path=self.marker,
            engine=self.engine,
            poll_interval=0,
            watch=True,
            spawn=spawn,
            wait=lambda child, interval: child.returncode,
        )
        self.assertEqual(result, 1)
        self.assertEqual(len(spawned), 2)


class AppendStateDecisionTestCase(unittest.TestCase):
    """append_state_decision writes StateTracker-compatible state.md bullets."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "state.md"

    def tearDown(self):
        self._tmp.cleanup()

    def test_appends_decision_to_existing_decisions_section(self):
        self.state_path.write_text(
            "# State\n\n## Phase\nidle\n\n## Decisions\n- earlier\n",
            encoding="utf-8",
        )
        supervisor.append_state_decision(self.state_path, "rollback: x")
        text = self.state_path.read_text(encoding="utf-8")
        self.assertIn("## Decisions", text)
        self.assertIn("- rollback: x", text)

    def test_appends_decision_when_section_missing(self):
        self.state_path.write_text("# State\n\n## Phase\nidle\n", encoding="utf-8")
        supervisor.append_state_decision(self.state_path, "rollback: y")
        text = self.state_path.read_text(encoding="utf-8")
        self.assertIn("## Decisions", text)
        self.assertIn("- rollback: y", text)

    def test_creates_state_file_when_missing(self):
        supervisor.append_state_decision(self.state_path, "rollback: z")
        self.assertTrue(self.state_path.exists())
        text = self.state_path.read_text(encoding="utf-8")
        self.assertIn("- rollback: z", text)

    def test_state_tracker_loads_supervisor_written_decision(self):
        import web_app

        supervisor.append_state_decision(self.state_path, "rollback: compatibility")
        state = web_app.StateTracker(path=self.state_path).load()
        self.assertTrue(any("rollback: compatibility" in d for d in state["decisions"]))


if __name__ == "__main__":
    unittest.main()