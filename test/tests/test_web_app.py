"""Unit + integration tests for scripts/web_app.py (ZOVA WEB dashboard).

Covers the pure data collectors (agents / inbox / feedback / status / swarm),
task submission, the prompt sanitizer, and the live HTTP endpoints (GET /
api/status / api/swarm / api/logs + POST /api/tasks), plus the headless
``--smoke`` check.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import swarm
import web_app


class MockApp:
    """Minimal stand-in for the handler's ``app`` (workspace holder)."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)


def make_workspace(tmp: str):
    """Seed a realistic control-plane workspace inside ``tmp``."""
    root = Path(tmp)
    (root / "_logs" / "swarm").mkdir(parents=True)
    (root / "_inbox" / "done").mkdir(parents=True)
    (root / "_inbox" / "claimed").mkdir(parents=True)
    # Per-slot state: m4 helper -> m1, m5 idle working.
    swarm.write_slot_state(root / "_logs" / "swarm", 4, status="helper", target=1, title="M4-Helper->M1", agent="backend-dev")
    swarm.write_slot_state(root / "_logs" / "swarm", 5, status="working", title="M5 - Frontend Dev [working]", agent="frontend-dev")
    # Feedback records.
    (root / "_logs" / "swarm_feedback.jsonl").write_text(
        json.dumps({"ts": "2026-08-09T00:00:00+00:00", "slot": 4, "agent": "backend-dev", "mode": "helper", "target": 1, "ok": True, "duration": 3.0, "task": "fix login"})
        + "\n"
        + json.dumps({"ts": "2026-08-09T00:01:00+00:00", "slot": 5, "agent": "frontend-dev", "mode": "own", "ok": False, "duration": 1.2, "task": "style nav"})
        + "\n",
        encoding="utf-8",
    )
    # Logs.
    (root / "_logs" / "frontend-dev.log").write_text("line0\nline1\nline2\n", encoding="utf-8")
    # Inbox: one pending task for backend-dev.
    (root / "_inbox" / "backend-dev.task").write_text("fix the login redirect bug", encoding="utf-8")
    (root / "_inbox" / "done" / "planner-1.task").write_text("smoke", encoding="utf-8")
    (root / "_inbox" / "claimed" / "tester-claimed-by-m4-1.task").write_text("smoke", encoding="utf-8")
    return root


class SanitizePromptTestCase(unittest.TestCase):
    def test_strips_control_characters(self):
        self.assertEqual(web_app.sanitize_prompt("hello\x07\x1bworld"), "helloworld")

    def test_strips_whitespace(self):
        self.assertEqual(web_app.sanitize_prompt("   padded prompt  "), "padded prompt")

    def test_empty_and_none(self):
        self.assertEqual(web_app.sanitize_prompt(""), "")
        self.assertEqual(web_app.sanitize_prompt(None), "")


class CollectAgentsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_workspace(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_all_seven_slots_in_order(self):
        agents = web_app.collect_agents(self.root)
        self.assertEqual([a["slot"] for a in agents], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual([a["agent"] for a in agents], ["system-architect", "analyst", "planner", "backend-dev", "frontend-dev", "tester", "reviewer"])

    def test_helper_status_and_title(self):
        m4 = next(a for a in web_app.collect_agents(self.root) if a["slot"] == 4)
        self.assertEqual(m4["status"], "helper")
        self.assertEqual(m4["title"], "M4-Helper->M1")
        self.assertEqual(m4["target"], 1)

    def test_working_status_from_state_file(self):
        m5 = next(a for a in web_app.collect_agents(self.root) if a["slot"] == 5)
        self.assertEqual(m5["status"], "working")

    def test_idle_default_when_no_state(self):
        m6 = next(a for a in web_app.collect_agents(self.root) if a["slot"] == 6)
        self.assertEqual(m6["status"], "idle")
        self.assertEqual(m6["title"], "M6 - Tester")

    def test_log_tail_and_has_log(self):
        agents = web_app.collect_agents(self.root)
        m5 = next(a for a in agents if a["slot"] == 5)
        self.assertTrue(m5["has_log"])
        self.assertEqual(m5["log_tail"], ["line0", "line1", "line2"])
        m1 = next(a for a in agents if a["slot"] == 1)
        self.assertFalse(m1["has_log"])
        self.assertEqual(m1["log_tail"], [])

    def test_missing_logs_dir_is_harmless(self):
        agents = web_app.collect_agents(Path(self._tmp.name) / "nope")
        self.assertEqual(len(agents), 7)  # no crash, all idle


class CollectInboxTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_workspace(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pending_counts_and_metadata(self):
        inbox = web_app.collect_inbox(self.root)
        self.assertEqual([p["agent"] for p in inbox["pending"]], ["backend-dev"])
        self.assertIn("backend-dev.task", inbox["pending"][0]["path"])
        self.assertGreaterEqual(inbox["pending"][0]["age"], 0.0)

    def test_done_and_claimed_counts(self):
        inbox = web_app.collect_inbox(self.root)
        self.assertEqual(inbox["done"], 1)
        self.assertEqual(inbox["claimed"], 1)

    def test_missing_inbox(self):
        inbox = web_app.collect_inbox(Path(self._tmp.name) / "missing")
        self.assertEqual(inbox, {"pending": [], "done": 0, "claimed": 0})


class CollectStatusTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_workspace(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_status_payload_shape(self):
        status = web_app.collect_status(self.root)
        self.assertEqual(len(status["agents"]), 7)
        self.assertEqual(status["inbox"]["done"], 1)
        self.assertEqual(len(status["feedback"]), 2)
        self.assertIn("swarm", status["brief"].lower())
        self.assertEqual(status["workspace"], str(self.root))

    def test_swarm_payload_lists_helpers(self):
        swarm_payload = web_app.collect_swarm(self.root)
        helpers = swarm_payload["helpers"]
        self.assertEqual(len(helpers), 1)
        self.assertEqual(helpers[0]["slot"], 4)
        self.assertEqual(helpers[0]["target"], 1)
        self.assertEqual(len(swarm_payload["feedback"]), 2)


class SubmitTaskTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_submission_writes_task_file(self):
        ok, message, path = web_app.submit_task(self.root, "frontend-dev", "make a web")
        self.assertTrue(ok)
        self.assertEqual(message, "queued")
        self.assertEqual(path, self.root / "_inbox" / "frontend-dev.task")
        self.assertEqual(path.read_text(encoding="utf-8"), "make a web")

    def test_unknown_agent_rejected(self):
        ok, message, path = web_app.submit_task(self.root, "bogus-dev", "task")
        self.assertFalse(ok)
        self.assertIn("unknown agent", message)
        self.assertIsNone(path)

    def test_path_traversal_blocked(self):
        ok, _, _ = web_app.submit_task(self.root, "../evil", "task")
        self.assertFalse(ok)

    def test_empty_prompt_rejected(self):
        ok, message, _ = web_app.submit_task(self.root, "analyst", "   ")
        self.assertFalse(ok)
        self.assertIn("empty prompt", message)

    def test_prompt_sanitized_on_disk(self):
        ok, _, path = web_app.submit_task(self.root, "planner", "  plan\x07the\x1bthing  ")
        self.assertTrue(ok)
        self.assertEqual(path.read_text(encoding="utf-8"), "planthething")


class WebServerTestCase(unittest.TestCase):
    """Live HTTP integration tests against an ephemeral server."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_workspace(self._tmp.name)
        self.server = web_app.create_web_app(self.root)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def _post_task(self, agent, prompt):
        req = urllib.request.Request(
            self.base + "/api/tasks",
            data=json.dumps({"agent": agent, "prompt": prompt}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_index_page_served(self):
        status, html = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("ZOVA", html)
        self.assertIn("api/status", html)
        self.assertIn("QUEUE TASK", html)

    def test_healthz(self):
        status, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_api_status(self):
        status, body = self._get("/api/status")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(len(payload["agents"]), 7)
        m4 = next(a for a in payload["agents"] if a["slot"] == 4)
        self.assertEqual(m4["status"], "helper")

    def test_api_swarm(self):
        status, body = self._get("/api/swarm")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(len(payload["helpers"]), 1)

    def test_api_logs_valid_agent(self):
        status, body = self._get("/api/logs/frontend-dev")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["lines"], ["line0", "line1", "line2"])

    def test_api_logs_unknown_agent_404(self):
        status, body = self._get("/api/logs/hacker")
        self.assertEqual(status, 404)
        self.assertIn("unknown agent", json.loads(body)["error"])

    def test_unknown_route_404(self):
        status, body = self._get("/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("not found", json.loads(body)["error"])

    def test_post_task_creates_file(self):
        status, payload = self._post_task("tester", "run the suite")
        self.assertEqual(status, 201)
        self.assertTrue(payload["ok"])
        self.assertTrue((self.root / "_inbox" / "tester.task").exists())

    def test_post_task_invalid_agent_400(self):
        status, payload = self._post_task("nope", "x")
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])

    def test_post_task_invalid_json_400(self):
        req = urllib.request.Request(
            self.base + "/api/tasks",
            data=b"not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(ctx.exception.code, 400)


class SmokeTestCase(unittest.TestCase):
    def test_smoke_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_workspace(tmp)
            self.assertEqual(web_app.smoke(Path(tmp)), 0)


if __name__ == "__main__":
    unittest.main()