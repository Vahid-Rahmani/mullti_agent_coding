"""Connection resolver tests (Phase 4).

Resolution order: explicit connection → model's provider connection (default
or sole) → local/default runtime → clear secret-free error.
"""

import os
import tempfile
import unittest
from pathlib import Path

from scripts.core.model_connections import (
    ResolutionError,
    create_connection,
    credential_store,
    resolve,
)

SECRET = "test-secret-value-abc123"


class ResolverTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["ZOVA_CONNECTIONS"] = str(Path(self.tmp.name) / "connections.json")
        os.environ["ZOVA_AUTH_STORE"] = str(Path(self.tmp.name) / "auth.json")

    def tearDown(self):
        os.environ.pop("ZOVA_CONNECTIONS", None)
        os.environ.pop("ZOVA_AUTH_STORE", None)
        self.tmp.cleanup()

    def test_explicit_connection_wins(self):
        conn = create_connection("openai", api_key=SECRET)
        r = resolve({"model": "openai/gpt-5",
                     "connection_id": conn.connection_id})
        self.assertEqual(r.source, "explicit")
        self.assertEqual(r.connection_id, conn.connection_id)
        self.assertEqual(r.provider, "openai")

    def test_explicit_connection_overrides_local_model(self):
        conn = create_connection("openai", api_key=SECRET)
        r = resolve({"model": "ollama/qwen2.5-coder:7b",
                     "connection_id": conn.connection_id})
        self.assertEqual(r.source, "explicit")
        self.assertEqual(r.connection_id, conn.connection_id)

    def test_model_provider_default_connection(self):
        create_connection("openai", "Primary", api_key=SECRET, default=True)
        create_connection("openai", "Secondary", api_key=SECRET)
        r = resolve({"model": "openai/gpt-5"})
        self.assertEqual(r.source, "provider-default")
        self.assertEqual(r.display_name, "Primary")

    def test_sole_connection_for_provider(self):
        create_connection("anthropic", api_key=SECRET)
        r = resolve({"model": "anthropic/claude-sonnet-4-5"})
        self.assertEqual(r.source, "provider-default")
        self.assertEqual(r.provider, "anthropic")
        self.assertTrue(r.credential_configured)

    def test_multiple_non_default_connections_require_explicit_choice(self):
        create_connection("openai", "A", api_key=SECRET)
        create_connection("openai", "B", api_key=SECRET)
        with self.assertRaises(ResolutionError) as ctx:
            resolve({"model": "openai/gpt-5"})
        msg = str(ctx.exception)
        self.assertIn("openai", msg)
        self.assertIn("select one explicitly", msg)
        self.assertNotIn(SECRET, msg)

    def test_missing_connection_for_required_provider(self):
        with self.assertRaises(ResolutionError) as ctx:
            resolve({"model": "anthropic/claude-sonnet-4-5"})
        msg = str(ctx.exception)
        self.assertIn("anthropic", msg)
        self.assertIn("create one", msg)
        self.assertNotIn(SECRET, msg)

    def test_local_model_resolves_to_local(self):
        r = resolve({"model": "ollama/qwen2.5-coder:7b"})
        self.assertEqual(r.source, "local")
        self.assertTrue(r.local)
        self.assertFalse(r.needs_credential)

    def test_no_model_no_connection_is_local_runtime(self):
        r = resolve({})
        self.assertEqual(r.source, "none")
        self.assertTrue(r.local)

    def test_unknown_explicit_connection_error(self):
        with self.assertRaises(ResolutionError) as ctx:
            resolve({"connection_id": "conn_nope"})
        self.assertIn("conn_nope", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_resolution_never_contains_secret(self):
        import json as _json
        create_connection("openai", api_key=SECRET)
        r = resolve({"model": "openai/gpt-5"})
        d = r.to_dict()
        self.assertNotIn(SECRET, _json.dumps(d))
        for key in ("key", "secret", "token", "authorization"):
            self.assertNotIn(key, d)

    def test_resolve_credential_internal(self):
        conn = create_connection("openai", api_key=SECRET)
        from scripts.core.model_connections.resolver import resolve_credential
        self.assertEqual(resolve_credential(conn.connection_id), SECRET)
        self.assertIsNone(resolve_credential("conn_missing"))

    def test_credential_flag_reflects_store(self):
        conn = create_connection("openai", api_key=SECRET)
        r = resolve({"connection_id": conn.connection_id})
        self.assertTrue(r.credential_configured)
        credential_store.remove_credential(conn.connection_id)
        r2 = resolve({"connection_id": conn.connection_id})
        self.assertFalse(r2.credential_configured)


if __name__ == "__main__":
    unittest.main()
