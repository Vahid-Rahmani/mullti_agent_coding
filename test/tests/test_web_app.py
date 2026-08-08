"""Unit tests for scripts/web_app.py (Dyad-style web UI)."""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

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


class ProviderModelTestCase(unittest.TestCase):
    """ProviderIn / ProviderPatch accept env_var + per-model limits."""

    def test_provider_in_accepts_env_var_and_limits(self):
        req = web_app.ProviderIn(
            name="openrouter",
            npm="@ai-sdk/openai-compatible",
            baseURL="https://openrouter.ai/api/v1",
            models=["openrouter/auto"],
            envVar="OPENROUTER_API_KEY",
            limits={"openrouter/auto": {"context": 200000, "output": 4096}},
        )
        self.assertEqual(req.envVar, "OPENROUTER_API_KEY")
        self.assertEqual(req.limits["openrouter/auto"]["context"], 200000)
        self.assertEqual(req.limits["openrouter/auto"]["output"], 4096)

    def test_provider_in_defaults(self):
        req = web_app.ProviderIn(name="ollama")
        self.assertIsNone(req.envVar)
        self.assertEqual(req.limits, {})

    def test_provider_patch_optional_fields(self):
        patch = web_app.ProviderPatch()
        self.assertIsNone(patch.npm)
        self.assertIsNone(patch.baseURL)
        self.assertIsNone(patch.models)
        self.assertIsNone(patch.envVar)
        self.assertIsNone(patch.limits)

    def test_provider_patch_accepts_env_var_and_limits(self):
        patch = web_app.ProviderPatch(
            envVar="MY_KEY", limits={"gpt-4o": {"context": 128000, "output": 8192}}
        )
        self.assertEqual(patch.envVar, "MY_KEY")
        self.assertEqual(patch.limits["gpt-4o"]["context"], 128000)


class ExtendedProviderCrudTestCase(unittest.TestCase):
    """env_var + per-model limits round-trip through a temp opencode.json.

    The env var is stored as an ``{env:VAR}`` reference in options.apiKey;
    the actual secret is never written to disk.
    """

    def setUp(self):
        self._orig_config = web_app.CONFIG_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.CONFIG_PATH = Path(self._tmp.name) / "opencode.json"
        web_app.CONFIG_PATH.write_text(
            json.dumps({"default_agent": "build", "provider": {}}), encoding="utf-8"
        )

    def tearDown(self):
        web_app.CONFIG_PATH = self._orig_config
        self._tmp.cleanup()

    def _read(self):
        return json.loads(web_app.CONFIG_PATH.read_text(encoding="utf-8"))

    def test_add_provider_env_var_writes_reference_not_secret(self):
        web_app.add_provider(
            "openrouter",
            "@ai-sdk/openai-compatible",
            "https://openrouter.ai/api/v1",
            ["openrouter/auto"],
            env_var="OPENROUTER_API_KEY",
        )
        config = self._read()
        options = config["provider"]["openrouter"]["options"]
        self.assertEqual(options["apiKey"], "{env:OPENROUTER_API_KEY}")
        # the actual secret must never be stored anywhere in the config
        self.assertNotIn("sk-", json.dumps(config))

    def test_add_provider_limits_roundtrip(self):
        web_app.add_provider(
            "openrouter",
            "@ai-sdk/openai-compatible",
            "https://openrouter.ai/api/v1",
            ["openrouter/auto", "deepseek/deepseek-chat"],
            limits={"openrouter/auto": {"context": 200000, "output": 4096}},
        )
        config = self._read()
        models = config["provider"]["openrouter"]["models"]
        self.assertEqual(
            models["openrouter/auto"]["limit"], {"context": 200000, "output": 4096}
        )
        # model without a limit has no limit key
        self.assertNotIn("limit", models["deepseek/deepseek-chat"])

    def test_update_provider_env_var_and_limits(self):
        web_app.add_provider(
            "openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"]
        )
        web_app.update_provider(
            "openrouter",
            None,
            None,
            None,
            env_var="OPENROUTER_API_KEY",
            limits={"openrouter/auto": {"context": 200000, "output": 4096}},
        )
        config = self._read()
        options = config["provider"]["openrouter"]["options"]
        self.assertEqual(options["apiKey"], "{env:OPENROUTER_API_KEY}")
        self.assertEqual(
            config["provider"]["openrouter"]["models"]["openrouter/auto"]["limit"],
            {"context": 200000, "output": 4096},
        )

    def test_update_provider_empty_env_var_clears_reference(self):
        web_app.add_provider(
            "openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"],
            env_var="OPENROUTER_API_KEY",
        )
        web_app.update_provider("openrouter", None, None, None, env_var="")
        config = self._read()
        self.assertNotIn("apiKey", config["provider"]["openrouter"].get("options", {}))

    def test_list_providers_includes_status_fields(self):
        web_app.add_provider(
            "openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"],
            env_var="OPENROUTER_API_KEY",
            limits={"openrouter/auto": {"context": 200000, "output": 4096}},
        )
        row = web_app.list_providers()[0]
        self.assertIn("status", row)
        self.assertIn("statusSource", row)
        self.assertIn("envVar", row)
        self.assertIn("isBuiltin", row)
        self.assertIn("limits", row)
        self.assertEqual(row["envVar"], "OPENROUTER_API_KEY")
        self.assertFalse(row["isBuiltin"])
        self.assertEqual(row["limits"]["openrouter/auto"]["context"], 200000)
        self.assertEqual(row["models"], ["openrouter/auto"])

    def test_add_provider_endpoint_env_var_and_limits(self):
        from fastapi.testclient import TestClient

        client = TestClient(web_app.app)
        res = client.post(
            "/api/providers",
            json={
                "name": "openrouter",
                "npm": "@ai-sdk/openai-compatible",
                "baseURL": "https://openrouter.ai/api/v1",
                "models": ["openrouter/auto"],
                "envVar": "OPENROUTER_API_KEY",
                "limits": {"openrouter/auto": {"context": 200000, "output": 4096}},
            },
        )
        self.assertEqual(res.status_code, 201)
        config = self._read()
        self.assertEqual(
            config["provider"]["openrouter"]["options"]["apiKey"], "{env:OPENROUTER_API_KEY}"
        )
        self.assertEqual(
            config["provider"]["openrouter"]["models"]["openrouter/auto"]["limit"],
            {"context": 200000, "output": 4096},
        )

    def test_update_provider_endpoint_env_var_and_limits(self):
        from fastapi.testclient import TestClient

        client = TestClient(web_app.app)
        web_app.add_provider(
            "openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"]
        )
        res = client.put(
            "/api/providers/openrouter",
            json={
                "envVar": "OPENROUTER_API_KEY",
                "limits": {"openrouter/auto": {"context": 200000, "output": 4096}},
            },
        )
        self.assertEqual(res.status_code, 200)
        config = self._read()
        self.assertEqual(
            config["provider"]["openrouter"]["options"]["apiKey"], "{env:OPENROUTER_API_KEY}"
        )
        self.assertEqual(
            config["provider"]["openrouter"]["models"]["openrouter/auto"]["limit"],
            {"context": 200000, "output": 4096},
        )


class ProviderMatrixTestCase(unittest.TestCase):
    """provider_matrix merges built-ins + detected auth keys + custom providers."""

    def setUp(self):
        self._orig_config = web_app.CONFIG_PATH
        self._orig_auth = web_app.AUTH_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.CONFIG_PATH = Path(self._tmp.name) / "opencode.json"
        web_app.AUTH_PATH = Path(self._tmp.name) / "auth.json"
        web_app.CONFIG_PATH.write_text(json.dumps({"provider": {}}), encoding="utf-8")
        self._saved_env = {}
        for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "MY_CUSTOM_KEY"):
            self._saved_env[name] = os.environ.get(name)
            os.environ.pop(name, None)

    def tearDown(self):
        web_app.CONFIG_PATH = self._orig_config
        web_app.AUTH_PATH = self._orig_auth
        for name, value in self._saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self._tmp.cleanup()

    def test_matrix_includes_builtins_with_status(self):
        rows = web_app.provider_matrix()
        names = {r["name"] for r in rows}
        self.assertIn("openai", names)
        self.assertIn("anthropic", names)
        self.assertIn("google", names)
        openai = next(r for r in rows if r["name"] == "openai")
        self.assertTrue(openai["isBuiltin"])
        self.assertEqual(openai["status"], "needs-setup")
        self.assertEqual(openai["statusSource"], "none")
        self.assertEqual(openai["envVar"], "OPENAI_API_KEY")

    def test_matrix_includes_detected_auth_keys(self):
        web_app.AUTH_PATH.write_text(
            json.dumps({"mulerouter": {"type": "api", "key": "sk-test"}}), encoding="utf-8"
        )
        rows = web_app.provider_matrix()
        names = {r["name"] for r in rows}
        self.assertIn("mulerouter", names)
        row = next(r for r in rows if r["name"] == "mulerouter")
        self.assertEqual(row["status"], "ready")
        self.assertEqual(row["statusSource"], "auth")
        self.assertFalse(row["isBuiltin"])

    def test_matrix_includes_custom_providers(self):
        web_app.add_provider(
            "openrouter", "@ai-sdk/openai-compatible", "https://openrouter.ai/api/v1", ["openrouter/auto"]
        )
        rows = web_app.provider_matrix()
        names = {r["name"] for r in rows}
        self.assertIn("openrouter", names)
        row = next(r for r in rows if r["name"] == "openrouter")
        self.assertEqual(row["models"], ["openrouter/auto"])
        self.assertFalse(row["isBuiltin"])

    def test_matrix_custom_overrides_builtin(self):
        web_app.add_provider(
            "openai", "@ai-sdk/openai", "https://custom.openai.example/v1", ["gpt-4o"]
        )
        rows = web_app.provider_matrix()
        row = next(r for r in rows if r["name"] == "openai")
        self.assertEqual(row["baseURL"], "https://custom.openai.example/v1")
        self.assertEqual(row["models"], ["gpt-4o"])
        self.assertTrue(row["isBuiltin"])


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

    def test_index_serves_provider_matrix_ui(self):
        """Settings modal renders a provider matrix grid with status badges."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("providerMatrix", res.text)
        self.assertIn("Add custom provider", res.text)
        self.assertIn("badge-ready", res.text)
        self.assertIn("badge-needs-setup", res.text)
        self.assertIn("badge-local", res.text)
        self.assertIn("chip-auth", res.text)
        self.assertIn("chip-env", res.text)
        self.assertIn("chip-none", res.text)

    def test_index_serves_provider_detail_ui(self):
        """Detail modal renders verify/discover, import, env var, and limits UI."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Verify &amp; discover", res.text)
        self.assertIn("Import models", res.text)
        self.assertIn("Max Output Tokens", res.text)
        self.assertIn("Context Window", res.text)
        self.assertIn("env var", res.text)
        self.assertIn('type="password"', res.text)
        # typed verify errors are surfaced to the user
        self.assertIn("Invalid API key", res.text)
        self.assertIn("Provider unreachable", res.text)
        # onboarding form collects an env var name too
        self.assertIn("pEnvVar", res.text)

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

    def test_providers_endpoint_returns_matrix_with_builtins(self):
        res = self.client.get("/api/providers")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        names = {r["name"] for r in data}
        self.assertIn("openai", names)
        self.assertIn("anthropic", names)
        self.assertIn("google", names)
        for row in data:
            self.assertIn("status", row)
            self.assertIn("statusSource", row)
            self.assertIn("envVar", row)
            self.assertIn("isBuiltin", row)
            self.assertIn("limits", row)

    def test_run_requires_prompt(self):
        res = self.client.post("/api/run", json={"prompt": "   "})
        self.assertEqual(res.status_code, 400)


class ModelDiscoveryTestCase(unittest.TestCase):
    """discover_models queries GET {base_url}/models with a Bearer key.

    urllib is mocked; no network calls happen in these tests.
    """

    def _mock_response(self, payload):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    def _mock_http_error(self, code):
        return HTTPError(f"https://api.example.com/v1/models", code, "err", {}, io.BytesIO(b""))

    def test_success_returns_model_ids(self):
        resp = self._mock_response({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], ["gpt-4o", "gpt-4o-mini"])
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["error"])
        # Bearer header, 6s timeout, URL is {base_url}/models
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.example.com/v1/models")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-test")
        self.assertEqual(urlopen.call_args.kwargs.get("timeout"), 6)

    def test_success_models_key_variant(self):
        resp = self._mock_response({"models": ["qwen2.5-coder:7b"]})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = web_app.discover_models("http://localhost:11434/v1", "sk-test")
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"], ["qwen2.5-coder:7b"])

    def test_401_invalid_key(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._mock_http_error(401)):
            result = web_app.discover_models("https://api.example.com/v1", "sk-bad")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "invalid_key")
        self.assertEqual(result["models"], [])
        self.assertIsNotNone(result["error"])

    def test_403_invalid_key(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._mock_http_error(403)):
            result = web_app.discover_models("https://api.example.com/v1", "sk-bad")
        self.assertEqual(result["status"], "invalid_key")

    def test_404_not_compatible(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._mock_http_error(404)):
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertEqual(result["status"], "not_compatible")

    def test_405_not_compatible(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._mock_http_error(405)):
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertEqual(result["status"], "not_compatible")

    def test_429_rate_limited(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._mock_http_error(429)):
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertEqual(result["status"], "rate_limited")

    def test_timeout_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertEqual(result["status"], "unreachable")

    def test_connection_error_unreachable(self):
        with mock.patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            result = web_app.discover_models("https://api.example.com/v1", "sk-test")
        self.assertEqual(result["status"], "unreachable")


class VerifyRequestModelTestCase(unittest.TestCase):
    """VerifyRequest / ImportModelsRequest pydantic shapes."""

    def test_verify_request_optional_fields(self):
        req = web_app.VerifyRequest(providerName="openai", baseURL="https://api.openai.com/v1")
        self.assertEqual(req.providerName, "openai")
        self.assertEqual(req.baseURL, "https://api.openai.com/v1")
        self.assertIsNone(req.envVar)
        self.assertIsNone(req.apiKey)

    def test_verify_request_with_key_and_env_var(self):
        req = web_app.VerifyRequest(
            providerName="custom", baseURL="https://api.example.com/v1",
            envVar="MY_KEY", apiKey="sk-inmem",
        )
        self.assertEqual(req.envVar, "MY_KEY")
        self.assertEqual(req.apiKey, "sk-inmem")

    def test_import_models_request(self):
        req = web_app.ImportModelsRequest(models=["gpt-4o", "gpt-4o-mini"])
        self.assertEqual(req.models, ["gpt-4o", "gpt-4o-mini"])


class VerifyEndpointTestCase(unittest.TestCase):
    """POST /api/providers/verify resolves a key and returns discovered models."""

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(web_app.app)
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

    def _mock_response(self, payload):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    def test_verify_with_provided_key(self):
        resp = self._mock_response({"data": [{"id": "gpt-4o"}]})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            res = self.client.post(
                "/api/providers/verify",
                json={"providerName": "custom", "baseURL": "https://api.example.com/v1", "apiKey": "sk-inmem"},
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["models"], ["gpt-4o"])
        # the in-memory key must never be echoed in the response
        self.assertNotIn("sk-inmem", res.text)

    def test_verify_resolves_key_from_auth(self):
        web_app.AUTH_PATH.write_text(
            json.dumps({"openai": {"type": "api", "key": "sk-auth"}}), encoding="utf-8"
        )
        resp = self._mock_response({"data": [{"id": "gpt-4o"}]})
        with mock.patch("urllib.request.urlopen", return_value=resp):
            res = self.client.post(
                "/api/providers/verify",
                json={"providerName": "openai", "baseURL": "https://api.openai.com/v1"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["models"], ["gpt-4o"])

    def test_verify_no_key_returns_400(self):
        res = self.client.post(
            "/api/providers/verify",
            json={"providerName": "openai", "baseURL": "https://api.openai.com/v1"},
        )
        self.assertEqual(res.status_code, 400)

    def test_verify_typed_error_passthrough(self):
        err = HTTPError("https://api.example.com/v1/models", 401, "Unauthorized", {}, io.BytesIO(b""))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            res = self.client.post(
                "/api/providers/verify",
                json={"providerName": "custom", "baseURL": "https://api.example.com/v1", "apiKey": "sk-bad"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "invalid_key")


class ImportModelsEndpointTestCase(unittest.TestCase):
    """POST /api/providers/{name}/import-models adds model IDs with default names."""

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(web_app.app)
        self._orig_config = web_app.CONFIG_PATH
        self._tmp = tempfile.TemporaryDirectory()
        web_app.CONFIG_PATH = Path(self._tmp.name) / "opencode.json"
        web_app.CONFIG_PATH.write_text(
            json.dumps(
                {
                    "provider": {
                        "mulerouter": {
                            "npm": "@ai-sdk/openai-compatible",
                            "options": {"baseURL": "https://api.mulerouter.ai/vendors/openai/v1"},
                            "models": {"gpt-5.5": {"name": "gpt-5.5"}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        web_app.CONFIG_PATH = self._orig_config
        self._tmp.cleanup()

    def _read(self):
        return json.loads(web_app.CONFIG_PATH.read_text(encoding="utf-8"))

    def test_import_adds_models_with_default_names(self):
        res = self.client.post(
            "/api/providers/mulerouter/import-models",
            json={"models": ["gpt-5.4-mini", "qwen3-max"]},
        )
        self.assertEqual(res.status_code, 200)
        config = self._read()
        models = config["provider"]["mulerouter"]["models"]
        self.assertEqual(models["gpt-5.4-mini"], {"name": "gpt-5.4-mini"})
        self.assertEqual(models["qwen3-max"], {"name": "qwen3-max"})
        # existing model preserved
        self.assertIn("gpt-5.5", models)

    def test_import_dedupes_on_reimport(self):
        self.client.post("/api/providers/mulerouter/import-models", json={"models": ["gpt-5.4-mini"]})
        res = self.client.post(
            "/api/providers/mulerouter/import-models", json={"models": ["gpt-5.4-mini"]}
        )
        self.assertEqual(res.status_code, 200)
        config = self._read()
        models = config["provider"]["mulerouter"]["models"]
        self.assertEqual(len(models), 2)  # gpt-5.5 + gpt-5.4-mini, no duplicates
        self.assertEqual(res.json()["imported"], 0)  # nothing new on re-import

    def test_import_unknown_provider_404(self):
        res = self.client.post("/api/providers/nope/import-models", json={"models": ["x"]})
        self.assertEqual(res.status_code, 404)

    def test_import_empty_models_ok(self):
        res = self.client.post("/api/providers/mulerouter/import-models", json={"models": []})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["imported"], 0)


class StateTrackerTestCase(unittest.TestCase):
    """StateTracker reads/writes workspace-root state.md (sections format)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state.md"
        self.tracker = web_app.StateTracker(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.tracker.load())

    def test_load_corrupt_returns_none(self):
        self.path.write_text("this is not a state file\nno sections here\n", encoding="utf-8")
        self.assertIsNone(self.tracker.load())

    def test_update_roundtrip(self):
        self.tracker.update(phase="running", last_run={"prompt": "hello", "started": "now"})
        data = self.tracker.load()
        self.assertIsNotNone(data)
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"], {"prompt": "hello", "started": "now"})

    def test_update_merges_existing_fields(self):
        self.tracker.update(phase="running")
        self.tracker.update(decisions=["first"])
        data = self.tracker.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["decisions"], ["first"])

    def test_record_run_sets_phase_and_last_run(self):
        self.tracker.record_run("prompt text", "2026-01-01T00:00:00")
        data = self.tracker.load()
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"], {"prompt": "prompt text", "started": "2026-01-01T00:00:00"})

    def test_record_run_multiline_prompt_roundtrips(self):
        self.tracker.record_run("line one\nline two", "t0")
        data = self.tracker.load()
        self.assertEqual(data["last_run"]["prompt"], "line one\nline two")

    def test_record_finish_appends_completed(self):
        self.tracker.record_finish("m1", True)
        self.tracker.record_finish("m2", False)
        data = self.tracker.load()
        self.assertIn("m1: ok", data["completed"])
        self.assertIn("m2: failed", data["completed"])

    def test_compression_evicts_old_completed(self):
        for i in range(25):
            self.tracker.record_finish(f"m{i}", True)
        data = self.tracker.load()
        self.assertLessEqual(len(data["completed"]), web_app.StateTracker.MAX_COMPLETED + 1)
        self.assertTrue(any("compressed" in entry for entry in data["completed"]))
        self.assertIn("m24: ok", data["completed"])

    def test_record_decision_appends(self):
        self.tracker.record_decision("use fastapi")
        self.tracker.record_decision("keep state.md in workspace root")
        data = self.tracker.load()
        self.assertEqual(
            data["decisions"], ["use fastapi", "keep state.md in workspace root"]
        )

    def test_pending_modification_roundtrip(self):
        self.tracker.record_pending_modification("patch scripts/unified_app.py")
        data = self.tracker.load()
        self.assertEqual(data["pending_modification"], "patch scripts/unified_app.py")
        self.tracker.clear_pending_modification()
        data = self.tracker.load()
        self.assertIsNone(data["pending_modification"])

    def test_restart_log_recording(self):
        self.tracker.record_restart("requested", "reason: upgrade")
        self.tracker.record_restart("verify", "failed")
        data = self.tracker.load()
        self.assertIn("requested: reason: upgrade", data["restart_log"])
        self.assertIn("verify: failed", data["restart_log"])

    def test_write_is_atomic_leaves_no_temp_files(self):
        self.tracker.update(phase="idle")
        leftovers = list(Path(self._tmp.name).glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_path_defaults_to_workspace_root_state_md(self):
        tracker = web_app.StateTracker()
        self.assertEqual(tracker.path, Path(web_app.PROJECT_ROOT) / "state.md")


class StateEndpointTestCase(unittest.TestCase):
    """GET /api/state + POST /api/state/refresh expose STATE.load()."""

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(web_app.app)
        self._orig_state = web_app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        web_app.STATE = web_app.StateTracker(path=Path(self._tmp.name) / "state.md")

    def tearDown(self):
        web_app.STATE = self._orig_state
        self._tmp.cleanup()

    def test_state_endpoint_checkpoint_null_on_missing_file(self):
        res = self.client.get("/api/state")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"checkpoint": None})

    def test_state_endpoint_returns_populated_checkpoint(self):
        web_app.STATE.update(phase="running", last_run={"prompt": "hello", "started": "t0"})
        res = self.client.get("/api/state")
        self.assertEqual(res.status_code, 200)
        data = res.json()["checkpoint"]
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"], {"prompt": "hello", "started": "t0"})

    def test_state_refresh_reloads_from_disk(self):
        web_app.STATE.update(phase="idle")
        state_path = web_app.STATE.path
        text = state_path.read_text(encoding="utf-8").replace(
            "## Phase\nidle", "## Phase\nrunning"
        )
        state_path.write_text(text, encoding="utf-8")
        res = self.client.post("/api/state/refresh")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["checkpoint"]["phase"], "running")


class _FakeProc:
    """Minimal stand-in for subprocess.Popen in _run_agent tests."""

    def __init__(self, lines=(), returncode=0):
        self.stdout = list(lines)
        self._rc = returncode

    def wait(self):
        return self._rc


class RunStateWiringTestCase(unittest.TestCase):
    """HUB.run/_run_agent/terminate_all write state.md via STATE."""

    def setUp(self):
        self._orig_state = web_app.STATE
        self._tmp = tempfile.TemporaryDirectory()
        web_app.STATE = web_app.StateTracker(path=Path(self._tmp.name) / "state.md")
        self.hub = web_app.WebHub()

    def tearDown(self):
        web_app.STATE = self._orig_state
        self._tmp.cleanup()

    def test_run_records_pruned_prompt_in_state(self):
        raw = "line one\n\n\n\nline two"
        pruned = web_app.prune_prompt(raw)
        self.assertNotEqual(pruned, raw)
        with mock.patch("threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        data = web_app.STATE.load()
        self.assertIsNotNone(data)
        self.assertEqual(data["phase"], "running")
        self.assertEqual(data["last_run"]["prompt"], pruned)
        self.assertTrue(thread_mock.called)

    def test_run_keeps_original_in_master_dispatches_pruned(self):
        raw = "line one\n\n\n\nline two"
        pruned = web_app.prune_prompt(raw)
        with mock.patch("threading.Thread") as thread_mock:
            self.hub.run(raw, {})
        self.assertTrue(any(f"▶ {raw}" in line for line in self.hub.buffers["master"]))
        for call in thread_mock.call_args_list:
            self.assertEqual(call.kwargs["args"][3], pruned)

    def test_run_agent_records_finish_ok(self):
        proc = _FakeProc(returncode=0)
        with mock.patch("web_app._opencode_command", return_value="opencode"), \
             mock.patch("web_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "System Architect", "system-architect", "prompt", None, None)
        data = web_app.STATE.load()
        self.assertIn("m1: ok", data["completed"])

    def test_run_agent_records_finish_failed(self):
        proc = _FakeProc(returncode=3)
        with mock.patch("web_app._opencode_command", return_value="opencode"), \
             mock.patch("web_app.subprocess.Popen", return_value=proc):
            self.hub._run_agent("m1", "System Architect", "system-architect", "prompt", None, None)
        data = web_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_run_agent_records_finish_failed_on_exception(self):
        with mock.patch("web_app._opencode_command", return_value=None):
            self.hub._run_agent("m1", "System Architect", "system-architect", "prompt", None, None)
        data = web_app.STATE.load()
        self.assertIn("m1: failed", data["completed"])

    def test_terminate_all_records_interruption(self):
        self.hub.terminate_all()
        data = web_app.STATE.load()
        self.assertIsNotNone(data)
        self.assertTrue(any("interrupted" in entry for entry in data["restart_log"]))


class WindowLauncherTestCase(unittest.TestCase):
    """Window launcher helpers: _find_edge, _wait_for_server, _launch_window."""

    def test_find_edge_returns_path(self):
        expected = os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")
        with mock.patch("os.path.isfile", return_value=True):
            self.assertEqual(web_app._find_edge(), expected)

    def test_find_edge_none_when_absent(self):
        with mock.patch("os.path.isfile", return_value=False):
            self.assertIsNone(web_app._find_edge())

    def test_wait_for_server_ok(self):
        resp = mock.MagicMock()
        resp.status = 200
        resp.__enter__.return_value = resp
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            self.assertTrue(web_app._wait_for_server("http://x", timeout=1))
        urlopen.assert_called_once_with("http://x", timeout=1)

    def test_wait_for_server_timeout(self):
        with mock.patch("urllib.request.urlopen", side_effect=URLError("down")):
            self.assertFalse(web_app._wait_for_server("http://x", timeout=1))

    def _import_without_webview(self, name, *args, **kwargs):
        if name == "webview":
            raise ImportError("no pywebview installed")
        return __import__(name, *args, **kwargs)

    def test_launch_window_pywebview(self):
        fake_webview = mock.MagicMock()

        def fake_import(name, *args, **kwargs):
            if name == "webview":
                return fake_webview
            return __import__(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            self.assertTrue(web_app._launch_window("http://x"))
        fake_webview.create_window.assert_called_once_with("MultiAgentCoding", "http://x")
        fake_webview.start.assert_called_once_with()

    def test_launch_window_edge_fallback(self):
        with mock.patch("builtins.__import__", side_effect=self._import_without_webview), \
             mock.patch.object(web_app, "_find_edge", return_value=r"C:\edge.exe"), \
             mock.patch("subprocess.run") as run:
            self.assertTrue(web_app._launch_window("http://x"))
        run.assert_called_once_with([r"C:\edge.exe", "--app", "http://x"], check=False)

    def test_launch_window_browser_fallback(self):
        with mock.patch("builtins.__import__", side_effect=self._import_without_webview), \
             mock.patch.object(web_app, "_find_edge", return_value=None), \
             mock.patch("webbrowser.open") as open_browser:
            self.assertTrue(web_app._launch_window("http://x"))
        open_browser.assert_called_once_with("http://x")


if __name__ == "__main__":
    unittest.main()