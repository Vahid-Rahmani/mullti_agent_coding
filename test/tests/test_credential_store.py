"""Credential store security tests (Phase 4).

These tests prove the security contract:
  * secrets are stored separately from connection metadata
  * the public surface never returns a secret
  * redaction removes secrets from errors/messages
  * workflow JSON never contains a secret
  * the store file stays compatible with the OpenCode auth-store format
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.core.model_connections import (
    create_connection,
    credential_store,
    get_connection,
)

SECRET = "test-secret-value-abc123"


class CredentialStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self.conn_path = Path(self.tmp.name) / "connections.json"
        self._auth_env = os.environ.get("ZOVA_AUTH_STORE")
        self._conn_env = os.environ.get("ZOVA_CONNECTIONS")
        os.environ["ZOVA_AUTH_STORE"] = str(self.auth_path)
        os.environ["ZOVA_CONNECTIONS"] = str(self.conn_path)

    def tearDown(self):
        if self._auth_env is None:
            os.environ.pop("ZOVA_AUTH_STORE", None)
        else:
            os.environ["ZOVA_AUTH_STORE"] = self._auth_env
        if self._conn_env is None:
            os.environ.pop("ZOVA_CONNECTIONS", None)
        else:
            os.environ["ZOVA_CONNECTIONS"] = self._conn_env
        self.tmp.cleanup()

    def test_secret_stored_separately_from_metadata(self):
        c = create_connection("openai", api_key=SECRET)
        meta = json.loads(self.conn_path.read_text(encoding="utf-8"))
        auth = json.loads(self.auth_path.read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, json.dumps(meta), "metadata file must not hold the secret")
        self.assertEqual(auth[c.connection_id]["key"], SECRET,
                         "secret lives in the auth store, keyed by connection id")

    def test_public_surface_never_returns_secret(self):
        c = create_connection("openai", api_key=SECRET)
        self.assertTrue(credential_store.has_credential(c.connection_id))
        # metadata dict has no secret-bearing keys (and never the value)
        d = get_connection(c.connection_id).to_dict()
        self.assertNotIn(SECRET, json.dumps(d))
        self.assertNotIn("key", d, "no key/value field in metadata")
        self.assertNotIn("secret", d)
        self.assertNotIn("token", d)
        self.assertNotIn("authorization", d)

    def test_internal_resolve_credential_exists(self):
        # _resolve_credential is the only way to read a secret and is marked
        # internal; verify it exists and returns the value (backend use only).
        c = create_connection("openai", api_key=SECRET)
        value = credential_store._resolve_credential(c.connection_id)
        self.assertEqual(value, SECRET)

    def test_redact_removes_secret_values(self):
        msg = f"connection failed for key {SECRET} at https://api.example.com/v1?key={SECRET}"
        out = credential_store.redact(msg, SECRET)
        self.assertNotIn(SECRET, out)
        self.assertIn("***", out)
        # URL query strings (key carriers) are scrubbed too
        self.assertNotIn("?key=", out)

    def test_safe_error_never_leaks_secret(self):
        create_connection("openai", api_key=SECRET)
        try:
            raise RuntimeError(f"boom with {SECRET}")
        except RuntimeError as exc:
            out = credential_store.safe_error(exc, SECRET)
        self.assertNotIn(SECRET, out)

    def test_workflow_json_never_contains_secret(self):
        # workflow nodes carry connection_id only; a full workflow payload must
        # never serialize the credential (the store is never consulted there).
        create_connection("openai", api_key=SECRET)
        from scripts.core.workflows import Workflow, WorkflowNode
        wf = Workflow(id="wf-sec", nodes=[
            WorkflowNode(id="n1", agent="matthew", model="openai/gpt-5",
                         connection_id="conn_openai_1")])
        payload = json.dumps(wf.to_dict())
        self.assertNotIn(SECRET, payload)
        self.assertNotIn("api_key", payload)

    def test_store_file_keeps_opencode_auth_format(self):
        c = create_connection("openai", api_key=SECRET)
        data = json.loads(self.auth_path.read_text(encoding="utf-8"))
        entry = data[c.connection_id]
        self.assertEqual(entry["type"], "api")
        self.assertEqual(entry["key"], SECRET)

    # Phase 5 — the execution boundary: the adapter may resolve the credential
    # only at execution time, and nothing it produces may carry it.
    def test_resolve_credential_available_only_at_execution_boundary(self):
        c = create_connection("openai", api_key=SECRET)
        # the internal resolver returns the value (backend use only)
        self.assertEqual(credential_store._resolve_credential(c.connection_id),
                         SECRET)
        # but a full workflow run pipeline never surfaces it: run a fake
        # adapter-backed workflow and inspect events/records/snapshots
        from unittest import mock

        from scripts.core import workflow_engine as E
        from scripts.core import workflows as W
        from scripts.core.execution.schema import ModelResponse

        class FakeAdapter:
            provider_id = "fake"

            def execute(self, request, connection, *, timeout=None,
                        cancel_event=None, execution_id=""):
                # the adapter is the one place allowed to see the credential
                self.seen = credential_store._resolve_credential(c.connection_id)
                return ModelResponse(text="ok", provider="fake",
                                     model=request.model)

        wf = W.Workflow.from_dict({
            "id": "wf-sec2", "name": "sec",
            "nodes": [{"id": "n1", "agent": "matthew", "kind": "agent",
                        "model": "openai/gpt-5", "connection_id": c.connection_id}],
            "edges": [], "entry": ["n1"], "state": {}, "settings": {},
        })
        adapter = FakeAdapter()
        with mock.patch("scripts.core.execution.executor.adapter_for",
                        return_value=adapter):
            runner = E.WorkflowRunner(wf)
            runner.start({})
            while not runner.finished:
                import time as _t

                _t.sleep(0.01)
        self.assertEqual(adapter.seen, SECRET, "adapter resolved the secret")
        snap = runner.snapshot()
        blob = repr(snap)
        self.assertNotIn(SECRET, blob)
        for key in ("api_key", "secret", "token", "credential",
                    "authorization", "password"):
            self.assertNotIn(key, blob.lower())
        # the record/event payloads specifically
        self.assertNotIn(SECRET, repr(snap["executions"]))
        self.assertNotIn(SECRET, repr(snap["events"]))


if __name__ == "__main__":
    unittest.main()
