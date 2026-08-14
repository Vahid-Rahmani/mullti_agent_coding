"""Execution schema tests (Phase 5).

Proves the provider-neutral request/response/record/event schemas validate,
serialize cleanly, and — structurally — cannot carry credentials.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core.execution import schema as S

SECRET = "sk-super-secret-test-value-abc123"


class TestModelRequest(unittest.TestCase):
    def test_requires_model_and_prompt(self):
        S.ModelRequest(model="m", prompt="p")
        with self.assertRaises(ValueError):
            S.ModelRequest(model="", prompt="p")
        with self.assertRaises(ValueError):
            S.ModelRequest(model="m", prompt="")

    def test_temperature_and_max_tokens_validation(self):
        with self.assertRaises(ValueError):
            S.ModelRequest(model="m", prompt="p", temperature=3.0)
        with self.assertRaises(ValueError):
            S.ModelRequest(model="m", prompt="p", max_tokens=0)

    def test_metadata_helpers(self):
        r = S.ModelRequest(model="m", prompt="p", metadata={
            "workflow_id": "wf", "node_id": "n1", "execution_id": "run1",
            "agent": "matthew"})
        self.assertEqual(r.workflow_id, "wf")
        self.assertEqual(r.node_id, "n1")
        self.assertEqual(r.execution_id, "run1")
        self.assertEqual(r.agent, "matthew")

    def test_to_dict_has_no_credential_surface(self):
        r = S.ModelRequest(model="m", prompt="p", metadata={"node_id": "n1"})
        payload = repr(r.to_dict())
        # note: "token" alone is intentionally NOT checked — ``max_tokens`` is a
        # legitimate sampling knob; credential-style tokens are what must never
        # appear (bare "token" as a key/secret value would still match these).
        for word in ("api_key", "secret", "password", "authorization",
                     "credential", "auth_token", "access_token", "api_token",
                     SECRET):
            self.assertNotIn(word, payload.lower())

    def test_serialized_object_cannot_contain_credentials(self):
        r = S.ModelRequest(model="m", prompt="p")
        self.assertNotIn(SECRET, repr(r.to_dict()))
        self.assertNotIn("api_key", r.to_dict().get("metadata", {}))
        self.assertNotIn("credential", r.to_dict())


class TestModelResponse(unittest.TestCase):
    def test_to_dict(self):
        resp = S.ModelResponse(text="hi", usage={"prompt_tokens": 5},
                               model="m", provider="opencode")
        d = resp.to_dict()
        self.assertEqual(d["text"], "hi")
        self.assertEqual(d["usage"], {"prompt_tokens": 5})
        self.assertNotIn(SECRET, repr(d))
        self.assertNotIn("credential", repr(d).lower())


class TestExecutionResult(unittest.TestCase):
    def test_status_validation(self):
        S.ExecutionResult(execution_id="r", node_execution_id="r-n1",
                          status="completed", started_at="t", finished_at="t",
                          latency_ms=1.0)
        S.ExecutionResult(execution_id="r", node_execution_id="r-n1",
                          status="failed", started_at="t", finished_at="t",
                          latency_ms=1.0)
        with self.assertRaises(ValueError):
            S.ExecutionResult(execution_id="r", node_execution_id="r-n1",
                              status="bogus", started_at="t", finished_at="t",
                              latency_ms=1.0)

    def test_to_dict_shape(self):
        res = S.ExecutionResult(execution_id="r", node_execution_id="r-n1",
                                status="completed", started_at="t",
                                finished_at="t", latency_ms=12.3,
                                response="out", model="m", provider="opencode",
                                error_code="")
        d = res.to_dict()
        self.assertEqual(d["node_execution_id"], "r-n1")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["latency_ms"], 12.3)
        # no credential field exists anywhere in the record
        self.assertNotIn(SECRET, repr(d))
        for key in ("api_key", "secret", "token", "password", "credential",
                    "authorization"):
            self.assertNotIn(key, d)


class TestExecutionEvent(unittest.TestCase):
    def test_event_type_validation(self):
        for t in S.EVENT_TYPES:
            S.ExecutionEvent(execution_id="r", workflow_id="w",
                             timestamp="t", event_type=t)
        with self.assertRaises(ValueError):
            S.ExecutionEvent(execution_id="r", workflow_id="w",
                             timestamp="t", event_type="bogus")

    def test_event_to_dict_is_secret_free(self):
        ev = S.ExecutionEvent(execution_id="r", workflow_id="w", timestamp="t",
                              event_type="node_completed", node_id="n1",
                              status="completed", model="m", provider="opencode",
                              latency_ms=1.0, usage={"prompt_tokens": 3},
                              error_code="")
        d = ev.to_dict()
        self.assertEqual(d["event_type"], "node_completed")
        self.assertEqual(d["node_id"], "n1")
        self.assertNotIn(SECRET, repr(d))
        self.assertNotIn("credential", repr(d).lower())

    def test_ordered_event_types(self):
        # the full observability set exists, in order
        self.assertEqual(S.EVENT_TYPES, (
            "workflow_started", "node_started", "node_completed", "node_failed",
            "workflow_completed", "workflow_failed"))


class TestTimestamps(unittest.TestCase):
    def test_utc_now_iso(self):
        ts = S.utc_now_iso()
        self.assertIn("T", ts)
        self.assertIn("+00:00", ts)


if __name__ == "__main__":
    unittest.main()
