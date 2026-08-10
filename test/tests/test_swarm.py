"""Unit tests for scripts/swarm.py (Dynamic Swarm Role-Swapping protocol).

Covers the three protocol pillars:
1. Role rotation / peer assistance (find_stale_tasks, claim_task).
2. Dynamic tab renaming (title builder).
3. Inter-agent learning feedback loop (append_feedback, load_feedback,
   build_brief) and live per-slot swarm state (write_slot_state/read_swarm_state).
"""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import swarm

NOW = 1_000_000.0


class TitleTestCase(unittest.TestCase):
    """Dynamic tab renaming: 'M3 - Sarah · TUI & Frontend Engineer' -> 'M3-Helper->M1'."""

    def test_idle_title(self):
        self.assertEqual(swarm.title(3, "Sarah"), "M3 - Sarah")

    def test_working_title(self):
        self.assertEqual(swarm.title(4, "David", mode="working"), "M4 - David [working]")

    def test_helper_title_rotation(self):
        self.assertEqual(swarm.title(3, "Sarah", mode="helper", target=1), "M3-Helper->M1")

    def test_helper_title_requires_target(self):
        with self.assertRaises(ValueError):
            swarm.title(2, "Alex", mode="helper")

    def test_agent_to_slot_map_covers_all_seven(self):
        self.assertEqual(len(swarm.AGENT_TO_SLOT), 7)
        self.assertEqual(swarm.AGENT_TO_SLOT["david"], 4)


class FindStaleTasksTestCase(unittest.TestCase):
    """find_stale_tasks: idle workers detect lagging peers."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _drop_task(self, agent, age):
        p = self.inbox / f"{agent}.task"
        p.write_text(f"task for {agent}", encoding="utf-8")
        os.utime(p, (NOW - age, NOW - age))

    def test_fresh_tasks_not_lagging(self):
        self._drop_task("elena", age=5)
        stale = swarm.find_stale_tasks(self.inbox, "david", 20, now=NOW)
        self.assertEqual(stale, [])

    def test_old_unclaimed_task_is_lagging(self):
        self._drop_task("elena", age=120)
        stale = swarm.find_stale_tasks(self.inbox, "david", 20, now=NOW)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["agent"], "elena")
        self.assertEqual(stale[0]["slot"], 5)

    def test_own_task_never_suggested(self):
        self._drop_task("david", age=200)
        stale = swarm.find_stale_tasks(self.inbox, "david", 20, now=NOW)
        self.assertEqual(stale, [])

    def test_unknown_files_ignored_oldest_first(self):
        (self.inbox / "notes.txt").write_text("ignore me", encoding="utf-8")
        self._drop_task("max", age=50)
        self._drop_task("chloe", age=400)
        stale = swarm.find_stale_tasks(self.inbox, "david", 20, now=NOW)
        self.assertEqual([s["agent"] for s in stale], ["chloe", "max"])

    def test_missing_inbox_returns_empty(self):
        self.assertEqual(swarm.find_stale_tasks(self.inbox / "nope", "david", 20, now=NOW), [])


class ClaimTaskTestCase(unittest.TestCase):
    """claim_task: atomic rename claims a peer task exactly once."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_claim_wins_second_returns_none(self):
        (self.inbox / "elena.task").write_text("peer task", encoding="utf-8")
        claimed = swarm.claim_task(self.inbox, "elena", claimer_slot=4)
        self.assertIsNotNone(claimed)
        self.assertIn("elena", claimed.name)
        self.assertIn("claimed-by-m4", claimed.name)
        self.assertFalse((self.inbox / "elena.task").exists())
        # a second helper loses the race
        self.assertIsNone(swarm.claim_task(self.inbox, "elena", claimer_slot=6))

    def test_claim_missing_task_returns_none(self):
        self.assertIsNone(swarm.claim_task(self.inbox, "nobody", claimer_slot=4))


class FeedbackTestCase(unittest.TestCase):
    """Inter-agent learning: JSONL feedback store feeding build_brief."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.fb = Path(self._tmp.name) / "swarm_feedback.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_and_load_roundtrip(self):
        swarm.append_feedback(self.fb, slot=4, agent="david", mode="helper", target=5, ok=True, duration=5.5)
        swarm.append_feedback(self.fb, slot=3, agent="sarah", mode="own", ok=False, duration=2.0)
        records = swarm.load_feedback(self.fb, n=10)
        self.assertEqual(len(records), 2)
        self.assertTrue(records[0]["ok"])
        self.assertEqual(records[0]["agent"], "david")
        self.assertIn("ts", records[0])
        self.assertFalse(records[1]["ok"])

    def test_load_recent_n_only(self):
        for i in range(5):
            swarm.append_feedback(self.fb, slot=4, agent="david", mode="own", ok=True, duration=float(i))
        self.assertEqual(len(swarm.load_feedback(self.fb, n=2)), 2)
        self.assertEqual(len(swarm.load_feedback(self.fb, n=10)), 5)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(swarm.load_feedback(self.fb.with_name("missing.jsonl")), [])

    def test_build_brief_includes_activity_and_helpers(self):
        swarm.append_feedback(
            self.fb, slot=4, agent="david", mode="helper", target=5,
            ok=True, duration=12.5, task="task for elena",
        )
        swarm.append_feedback(
            self.fb, slot=3, agent="sarah", mode="own",
            ok=False, duration=3.0, task="plan failed",
        )
        swarm.write_slot_state(Path(self._tmp.name) / "swarm", 4, status="helper", title="M4-Helper->M5", target=5)
        brief = swarm.build_brief(self.fb, Path(self._tmp.name) / "swarm", own_agent="david")
        self.assertIn("helper->M5", brief)
        self.assertIn("FAILED", brief)
        self.assertIn("Live helpers: M4->M5", brief)

    def test_build_brief_without_state(self):
        swarm.append_feedback(self.fb, slot=1, agent="matthew", mode="own", ok=True, duration=1.0)
        brief = swarm.build_brief(self.fb, None, own_agent="matthew")
        self.assertIn("Recent swarm activity", brief)

    def test_build_brief_empty(self):
        brief = swarm.build_brief(self.fb, None, own_agent="david")
        self.assertIn("No prior swarm activity", brief)


class SwarmStateTestCase(unittest.TestCase):
    """Per-slot live state (tab renaming source of truth)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "swarm"

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_and_read_slot_state(self):
        swarm.write_slot_state(self.dir, 4, status="helper", title="M4-Helper->M5", target=5)
        state = swarm.read_swarm_state(self.dir)
        self.assertIn(4, state)
        self.assertEqual(state[4]["status"], "helper")
        self.assertEqual(state[4]["title"], "M4-Helper->M5")

    def test_read_missing_dir_returns_empty(self):
        self.assertEqual(swarm.read_swarm_state(self.dir / "nope"), {})


class SwarmCliTestCase(unittest.TestCase):
    """CLI entry points used by run_agent_worker.ps1."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_find_stale_cli_prints_json(self):
        inbox = self.root / "inbox"
        inbox.mkdir()
        p = inbox / "elena.task"
        p.write_text("x", encoding="utf-8")
        os.utime(p, (NOW - 120, NOW - 120))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = swarm.main(["find-stale", "--inbox", str(inbox), "--own", "david", "--stale", "20"])
        self.assertEqual(code, 0)
        got = json.loads(buf.getvalue())
        self.assertEqual(got[0]["agent"], "elena")

    def test_state_cli_json_b64(self):
        payload = {"status": "helper", "title": "M4-Helper->M5", "target": 5}
        b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = swarm.main(["state", "--swarm", str(self.root), "--slot", "4", "--json-b64", b64])
        self.assertEqual(code, 0)
        state = swarm.read_swarm_state(self.root)
        self.assertEqual(state[4]["title"], "M4-Helper->M5")

    def test_feedback_cli_json_b64(self):
        fb = self.root / "fb.jsonl"
        record = {"slot": 4, "agent": "david", "mode": "own", "ok": False, "duration": 1.5}
        b64 = base64.b64encode(json.dumps(record).encode("utf-8")).decode("ascii")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = swarm.main(["feedback", "--file", str(fb), "--json-b64", b64])
        self.assertEqual(code, 0)
        loaded = swarm.load_feedback(fb)
        self.assertEqual(len(loaded), 1)
        self.assertFalse(loaded[0]["ok"])


if __name__ == "__main__":
    unittest.main()