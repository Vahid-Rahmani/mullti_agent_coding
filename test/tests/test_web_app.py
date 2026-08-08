"""Unit tests for scripts/web_app.py (Dyad-style web UI)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import web_app
from unified_app import AGENTS, AUTO_MODE, AUTO_MODEL


class CatalogTestCase(unittest.TestCase):
    """build_catalog merges desktop constants with opencode.json providers."""

    def setUp(self):
        self._orig_config = web_app.CONFIG_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.CONFIG_PATH = Path(self._tmp.name) / "opencode.json"

    def tearDown(self):
        web_app.CONFIG_PATH = self._orig_config
        self._tmp.cleanup()

    def _write_config(self, config):
        web_app.CONFIG_PATH.write_text(json.dumps(config), encoding="utf-8")

    def test_catalog_includes_desktop_models(self):
        catalog = web_app.build_catalog()
        self.assertIn(AUTO_MODEL, catalog["models"])
        self.assertIn("opencode/deepseek-v4-flash-free", catalog["models"])
        self.assertIn("architect", catalog["modesByModel"]["opencode/deepseek-v4-flash-free"])

    def test_catalog_merges_provider_models(self):
        self._write_config(
            {
                "provider": {
                    "mulerouter": {
                        "npm": "@ai-sdk/openai-compatible",
                        "options": {"baseURL": "https://api.mulerouter.ai/vendors/openai/v1"},
                        "models": {"gpt-5.5": {"name": "GPT 5.5"}},
                    }
                }
            }
        )
        catalog = web_app.build_catalog()
        self.assertIn("gpt-5.5", catalog["models"])
        # unknown provider model gets the default mode list
        self.assertEqual(catalog["modesByModel"]["gpt-5.5"], web_app.DEFAULT_MODES)

    def test_catalog_agents_and_colors(self):
        catalog = web_app.build_catalog()
        self.assertEqual(len(catalog["agents"]), 7)
        self.assertIn("m1", catalog["colors"])


class ProviderCrudTestCase(unittest.TestCase):
    """Provider CRUD round-trips through a temp opencode.json."""

    def setUp(self):
        self._orig_config = web_app.CONFIG_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.CONFIG_PATH = Path(self._tmp.name) / "opencode.json"
        # seed a minimal config with an unrelated key that must survive edits
        web_app.CONFIG_PATH.write_text(
            json.dumps({"default_agent": "build", "provider": {}}), encoding="utf-8"
        )

    def tearDown(self):
        web_app.CONFIG_PATH = self._orig_config
        self._tmp.cleanup()

    def _read(self):
        return json.loads(web_app.CONFIG_PATH.read_text(encoding="utf-8"))

    def test_add_list_update_delete_roundtrip(self):
        web_app.add_provider("openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"])
        providers = web_app.list_providers()
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "openrouter")
        self.assertEqual(providers[0]["models"], ["openrouter/auto"])

        web_app.update_provider("openrouter", None, "https://new.example/v1", ["openrouter/auto", "deepseek/deepseek-chat"])
        providers = web_app.list_providers()
        self.assertEqual(providers[0]["baseURL"], "https://new.example/v1")
        self.assertEqual(providers[0]["models"], ["deepseek/deepseek-chat", "openrouter/auto"])

        web_app.delete_provider("openrouter")
        self.assertEqual(web_app.list_providers(), [])

    def test_edits_preserve_unrelated_config_keys(self):
        web_app.add_provider("ollama", "", "http://localhost:11434/v1", ["qwen2.5-coder:7b"])
        config = self._read()
        self.assertEqual(config["default_agent"], "build")
        self.assertIn("ollama", config["provider"])

    def test_add_duplicate_raises(self):
        web_app.add_provider("ollama", "", "http://localhost:11434/v1", [])
        with self.assertRaises(Exception):
            web_app.add_provider("ollama", "", "http://localhost:11434/v1", [])

    def test_delete_missing_raises(self):
        with self.assertRaises(Exception):
            web_app.delete_provider("nope")


class ProviderStatusTestCase(unittest.TestCase):
    """provider_status / resolve_api_key / _auth_store read auth.json + env vars.

    Keys are only ever read in-memory; nothing here writes or logs key values.
    """

    def setUp(self):
        self._orig_auth = web_app.AUTH_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.AUTH_PATH = Path(self._tmp.name) / "auth.json"
        self._saved_env = {}
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "MY_CUSTOM_KEY"):
            self._saved_env[name] = os.environ.get(name)
            os.environ.pop(name, None)

    def tearDown(self):
        web_app.AUTH_PATH = self._orig_auth
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._tmp.cleanup()

    def _write_auth(self, data):
        web_app.AUTH_PATH.write_text(json.dumps(data), encoding="utf-8")

    def test_auth_path_defaults_to_opencode_share(self):
        self.assertEqual(
            self._orig_auth,
            Path.home() / ".local" / "share" / "opencode" / "auth.json",
        )

    def test_builtin_providers_have_required_fields(self):
        ids = {p["id"] for p in web_app.BUILTIN_PROVIDERS}
        self.assertEqual(ids, {"openai", "anthropic", "google"})
        for provider in web_app.BUILTIN_PROVIDERS:
            self.assertIn("npm", provider)
            self.assertIn("baseURL", provider)
            self.assertIn("envVar", provider)

    def test_auth_store_missing_returns_empty(self):
        self.assertEqual(web_app._auth_store(), {})

    def test_auth_store_corrupt_returns_empty(self):
        web_app.AUTH_PATH.write_text("{not json", encoding="utf-8")
        self.assertEqual(web_app._auth_store(), {})

    def test_auth_store_reads_entries(self):
        self._write_auth({"openai": {"type": "api", "key": "sk-test"}})
        store = web_app._auth_store()
        self.assertEqual(store["openai"]["key"], "sk-test")

    def test_resolve_api_key_none(self):
        key, source = web_app.resolve_api_key("openai")
        self.assertIsNone(key)
        self.assertEqual(source, "none")

    def test_resolve_api_key_from_auth(self):
        self._write_auth({"openai": {"type": "api", "key": "sk-auth"}})
        key, source = web_app.resolve_api_key("openai")
        self.assertEqual(key, "sk-auth")
        self.assertEqual(source, "auth")

    def test_resolve_api_key_env_precedence_over_auth(self):
        self._write_auth({"openai": {"type": "api", "key": "sk-auth"}})
        os.environ["OPENAI_API_KEY"] = "sk-env"
        key, source = web_app.resolve_api_key("openai")
        self.assertEqual(key, "sk-env")
        self.assertEqual(source, "env")

    def test_resolve_api_key_empty_env_falls_back_to_auth(self):
        self._write_auth({"openai": {"type": "api", "key": "sk-auth"}})
        os.environ["OPENAI_API_KEY"] = ""
        key, source = web_app.resolve_api_key("openai")
        self.assertEqual(key, "sk-auth")
        self.assertEqual(source, "auth")

    def test_resolve_api_key_custom_env_var(self):
        self._write_auth({"custom": {"type": "api", "key": "sk-auth"}})
        os.environ["MY_CUSTOM_KEY"] = "sk-custom"
        key, source = web_app.resolve_api_key("custom", "MY_CUSTOM_KEY")
        self.assertEqual(key, "sk-custom")
        self.assertEqual(source, "env")

    def test_provider_status_ready_from_auth(self):
        self._write_auth({"openai": {"type": "api", "key": "sk-test"}})
        status = web_app.provider_status("openai")
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["source"], "auth")
        self.assertEqual(status["envVar"], "OPENAI_API_KEY")

    def test_provider_status_ready_from_env(self):
        os.environ["OPENAI_API_KEY"] = "sk-env"
        status = web_app.provider_status("openai")
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["source"], "env")
        self.assertEqual(status["envVar"], "OPENAI_API_KEY")

    def test_provider_status_needs_setup_when_no_key(self):
        status = web_app.provider_status("openai")
        self.assertEqual(status["status"], "needs-setup")
        self.assertEqual(status["source"], "none")
        self.assertEqual(status["envVar"], "OPENAI_API_KEY")

    def test_provider_status_local_for_local_base_url(self):
        status = web_app.provider_status("ollama", None, "http://localhost:11434/v1")
        self.assertEqual(status["status"], "local")
        self.assertEqual(status["source"], "none")


class HubResolveTestCase(unittest.TestCase):
    """Hub.resolve mirrors the desktop GUI override priority."""

    def setUp(self):
        self.hub = web_app.WebHub()

    def test_agent_override_wins_over_master(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "review"},
            "m1": {"model": "opencode/deepseek-v4-flash-free", "mode": "architect"},
        }
        model, mode = self.hub.resolve("m1", overrides)
        self.assertEqual(model, "opencode/deepseek-v4-flash-free")
        self.assertEqual(mode, "architect")

    def test_master_override_when_agent_is_auto(self):
        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "review"},
            "m1": {"model": AUTO_MODEL, "mode": AUTO_MODE},
        }
        model, mode = self.hub.resolve("m1", overrides)
        self.assertEqual(model, "opencode/big-pickle")
        self.assertEqual(mode, "review")

    def test_all_auto_resolves_none_and_auto_mode(self):
        overrides = {
            "master": {"model": AUTO_MODEL, "mode": AUTO_MODE},
            "m1": {"model": AUTO_MODEL, "mode": AUTO_MODE},
        }
        model, mode = self.hub.resolve("m1", overrides)
        self.assertIsNone(model)
        self.assertEqual(mode, AUTO_MODE)

    def test_events_are_ansi_stripped_and_sequenced(self):
        self.hub.append_line("m1", "\x1b[0mclean\x1b[91m")
        self.hub.set_status("m1", web_app.STATUS_ACTIVE)
        with self.hub.lock:
            events = list(self.hub.events)
        self.assertEqual(events[0]["text"], "clean")
        self.assertEqual(events[1]["text"], web_app.STATUS_ACTIVE)
        self.assertEqual(events[1]["seq"], events[0]["seq"] + 1)


class EndpointTestCase(unittest.TestCase):
    """FastAPI TestClient smoke tests for read endpoints."""

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(web_app.app)

    def test_index_serves_ui(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("MultiAgentCoding", res.text)
        self.assertIn("Terminal Logs", res.text)
        self.assertIn("API &amp; Models", res.text)

    def test_catalog_endpoint(self):
        res = self.client.get("/api/catalog")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(AUTO_MODEL, data["models"])

    def test_status_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.json()["statuses"]), 7)

    def test_providers_endpoint_empty(self):
        res = self.client.get("/api/providers")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_run_requires_prompt(self):
        res = self.client.post("/api/run", json={"prompt": "   "})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()