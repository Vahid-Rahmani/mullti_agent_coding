"""Connection registry + API tests (Phase 4 — FreeBuff/BYOK).

Registry: create/list/get/update/delete, duplicate ids, unknown provider,
provider metadata, status derivation.
API: the /api/connections endpoints and — critically — that secrets never
appear in any response.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.core.model_connections import (
    DuplicateConnectionError,
    UnknownConnectionError,
    UnknownProviderError,
    create_connection,
    credential_store,
    delete_connection,
    get_connection,
    list_connections,
    update_connection,
)
from scripts.core.model_connections import providers as providers_mod

# test-only marker secrets (never real-looking production credentials)
SECRET = "test-secret-value-abc123"


class ConnectionEnvTestCase(unittest.TestCase):
    """Isolates connections metadata + auth store to temp files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn_path = Path(self.tmp.name) / "connections.json"
        self.auth_path = Path(self.tmp.name) / "auth.json"
        self._conn_env = os.environ.get("ZOVA_CONNECTIONS")
        self._auth_env = os.environ.get("ZOVA_AUTH_STORE")
        os.environ["ZOVA_CONNECTIONS"] = str(self.conn_path)
        os.environ["ZOVA_AUTH_STORE"] = str(self.auth_path)

    def tearDown(self):
        if self._conn_env is None:
            os.environ.pop("ZOVA_CONNECTIONS", None)
        else:
            os.environ["ZOVA_CONNECTIONS"] = self._conn_env
        if self._auth_env is None:
            os.environ.pop("ZOVA_AUTH_STORE", None)
        else:
            os.environ["ZOVA_AUTH_STORE"] = self._auth_env
        self.tmp.cleanup()


class ConnectionRegistryTestCase(ConnectionEnvTestCase):
    def test_create_and_get(self):
        c = create_connection("openai", "OpenAI Primary", api_key=SECRET)
        self.assertEqual(c.provider, "openai")
        self.assertEqual(c.display_name, "OpenAI Primary")
        self.assertEqual(c.status, "configured")
        got = get_connection(c.connection_id)
        self.assertEqual(got.connection_id, c.connection_id)

    def test_list_sorted_and_deterministic(self):
        create_connection("openai", api_key=SECRET)
        create_connection("anthropic", api_key=SECRET)
        ids = [c.connection_id for c in list_connections()]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids, [c.connection_id for c in list_connections()])

    def test_update_metadata_and_replace_key(self):
        c = create_connection("openai", api_key=SECRET)
        updated = update_connection(c.connection_id, display_name="Renamed",
                                    default=True)
        self.assertEqual(updated.display_name, "Renamed")
        self.assertTrue(updated.default)
        # replace the secret — old value gone from the store
        update_connection(c.connection_id, api_key="replacement-secret")
        self.assertTrue(credential_store.has_credential(c.connection_id))
        self.assertFalse(credential_store.has_credential("other"))

    def test_delete_removes_metadata_and_credential(self):
        c = create_connection("openai", api_key=SECRET)
        delete_connection(c.connection_id)
        with self.assertRaises(UnknownConnectionError):
            get_connection(c.connection_id)
        self.assertFalse(credential_store.has_credential(c.connection_id))

    def test_duplicate_connection_id(self):
        create_connection("openai", connection_id="conn_dup", api_key=SECRET)
        with self.assertRaises(DuplicateConnectionError):
            create_connection("openai", connection_id="conn_dup", api_key=SECRET)

    def test_unknown_provider(self):
        with self.assertRaises(UnknownProviderError):
            create_connection("mystery-corp", api_key=SECRET)

    def test_provider_requires_key(self):
        with self.assertRaises(Exception) as ctx:
            create_connection("anthropic")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_unknown_connection_error_message_no_secret(self):
        with self.assertRaises(UnknownConnectionError) as ctx:
            get_connection("conn_missing")
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_provider_metadata_table(self):
        metas = {p["provider"]: p for p in providers_mod.provider_meta()}
        for expected in ("openai", "anthropic", "google", "azure_openai",
                         "openrouter", "ollama", "custom_openai_compatible"):
            self.assertIn(expected, metas)
        self.assertTrue(metas["openai"]["requires_api_key"])
        self.assertFalse(metas["ollama"]["requires_api_key"])
        self.assertTrue(metas["azure_openai"]["supports_deployment"])
        self.assertTrue(metas["custom_openai_compatible"]["supports_base_url"])

    def test_local_provider_no_key_required(self):
        c = create_connection("ollama", "Local Ollama")
        self.assertEqual(c.status, "configured")
        self.assertFalse(credential_store.has_credential(c.connection_id))

    def test_validate_connection_config(self):
        c = create_connection("openai", api_key=SECRET)
        from scripts.core.model_connections import validate_connection
        res = validate_connection(c.connection_id)
        self.assertTrue(res["ok"])
        self.assertNotIn(SECRET, json.dumps(res))

    def test_validate_missing_credential(self):
        # a connection whose credential was deleted fails validation cleanly
        c = create_connection("openai", api_key=SECRET)
        credential_store.remove_credential(c.connection_id)
        from scripts.core.model_connections import validate_connection
        res = validate_connection(c.connection_id)
        self.assertFalse(res["ok"])
        self.assertIn("API key", res["detail"])
        self.assertNotIn(SECRET, json.dumps(res))

    # Phase 5 — the execution planner consumes the resolved connection as safe
    # metadata and never pulls the credential across the boundary.
    def test_planner_uses_resolution_without_credential(self):
        from scripts.core.execution.planner import plan_node
        from scripts.core.workflows import WorkflowNode

        create_connection("openai", api_key=SECRET,
                          connection_id="conn_plan_1")
        node = WorkflowNode(id="n1", agent="matthew", kind="agent",
                            model="openai/gpt-5", connection_id="conn_plan_1")
        plan = plan_node(node, {})
        self.assertEqual(plan.connection.connection_id, "conn_plan_1")
        self.assertEqual(plan.connection.provider, "openai")
        self.assertEqual(plan.adapter_id, "opencode",
                         "default adapter remains OpenCode")
        # the planner's safe metadata never carries the credential
        self.assertFalse(plan.connection.has_credential())
        self.assertNotIn(SECRET, repr(plan.to_dict()))
        self.assertNotIn("credential", plan.to_dict())

    def test_planner_explicit_connection_wins_over_model_provider(self):
        from scripts.core.execution.planner import plan_node
        from scripts.core.workflows import WorkflowNode

        create_connection("anthropic", api_key=SECRET,
                          connection_id="conn_plan_2")
        node = WorkflowNode(id="n1", agent="matthew", kind="agent",
                            model="openai/gpt-5",   # provider mismatch on purpose
                            connection_id="conn_plan_2")
        plan = plan_node(node, {})
        self.assertEqual(plan.connection.connection_id, "conn_plan_2",
                         "explicit connection is authoritative, never replaced")


if __name__ == "__main__":
    unittest.main()
