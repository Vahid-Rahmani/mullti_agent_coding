"""Phase 25 settings backend tests — temp trees + stubbed subprocess/HTTP.

Never touches the real ``opencode.json``, the real ``scripts/core/agents``
modules, the real OpenCode auth store, the opencode CLI, or the network.
``apply_agent_config`` is exercised against a temp repo copy; the ``verify``
subprocess, the ``opencode auth``/``models`` CLI, and the HTTP probe are all
stubbed.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import opencode_cfg
from scripts.core.agents import AGENT_SPEC_BY_AGENT
from scripts.core.run_hub import HUB
from scripts.web_ui import settings as ui_settings

AGENT_KEYS = [s.agent for s in AGENT_SPEC_BY_AGENT.values()]


def _model_for(agent: str) -> str:
    # Models live in opencode.json (not the spec) — a fixed deterministic
    # default for the temp fixture.
    return "opencode/big-pickle"


def _base_opencode_json() -> dict:
    return {
        "model": "opencode/big-pickle",
        "small_model": "opencode/ling-3.0-tiny-free",
        "provider": {
            "ollama": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Ollama (local)",
                "options": {"baseURL": "http://localhost:11434/v1"},
                "models": {"qwen2.5-coder:7b": {"name": "Qwen2.5 Coder 7B (local)"}},
            }
        },
        "agent": {
            key: {"description": f"M{i} — plain agent.", "mode": "all",
                  "model": _model_for(key), "fallback_models": []}
            for i, key in enumerate(AGENT_KEYS, start=1)
        },
    }


class FakeProc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


class SettingsBaseTestCase(unittest.TestCase):
    """Temp repo tree: copies of the agent spec files + a temp opencode.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agents_dir = self.root / "scripts" / "core" / "agents"
        self.agents_dir.mkdir(parents=True)
        src_agents = Path(REPO_ROOT) / "scripts" / "core" / "agents"
        for name in ("base.py", "constants.py", "registry.py", "__init__.py",
                     "matthew.py", "alex.py", "sarah.py", "david.py",
                     "elena.py", "max.py", "chloe.py", "master.py"):
            shutil.copy2(src_agents / name, self.agents_dir / name)
        self.cfg_path = self.root / "opencode.json"
        self.cfg_path.write_text(json.dumps(_base_opencode_json(), indent=2),
                                 encoding="utf-8")
        self.auth_store = self.root / "auth.json"
        self.verify_cmd = [sys.executable, "-c", "pass"]

    def tearDown(self):
        self.tmp.cleanup()

    def _apply(self, agent, **kwargs):
        return opencode_cfg.apply_agent_config(
            agent, repo_root=self.root, verify_cmd=self.verify_cmd, **kwargs)

    def _read_cfg(self) -> dict:
        return json.loads(self.cfg_path.read_text(encoding="utf-8"))

    def _read_spec(self, agent: str) -> str:
        return (self.agents_dir / f"{agent}.py").read_text(encoding="utf-8")


@mock.patch("scripts.core.opencode_cfg.subprocess.run", return_value=FakeProc(0))
class AtomicApplyTestCase(SettingsBaseTestCase):
    def test_model_apply_writes_opencode_json_only(self, _run):
        before_spec = (self.agents_dir / "matthew.py").read_bytes()
        self._apply("matthew", model="opencode/new-flash-free")
        # The AgentSpec module is identity-only and must NOT be rewritten.
        self.assertEqual((self.agents_dir / "matthew.py").read_bytes(), before_spec)
        self.assertEqual(self._read_cfg()["agent"]["matthew"]["model"],
                         "opencode/new-flash-free")
        _run.assert_called_once()

    def test_mode_and_fallback_touch_opencode_json_only(self, _run):
        before_spec = (self.agents_dir / "alex.py").read_bytes()
        self._apply("alex", mode="subagent", description="M2 — reviewer",
                    fallback_models=["opencode/big-pickle", "ollama/qwen2.5-coder:7b"])
        self.assertEqual((self.agents_dir / "alex.py").read_bytes(), before_spec)
        entry = self._read_cfg()["agent"]["alex"]
        self.assertEqual(entry["mode"], "subagent")
        self.assertEqual(entry["description"], "M2 — reviewer")
        self.assertEqual(entry["fallback_models"],
                         ["opencode/big-pickle", "ollama/qwen2.5-coder:7b"])

    def test_tag_or_agent_key_accepted(self, _run):
        self._apply("m4", mode="primary")
        self.assertEqual(self._read_cfg()["agent"]["david"]["mode"], "primary")


class AtomicApplyErrorsTestCase(SettingsBaseTestCase):
    @mock.patch("scripts.core.opencode_cfg.subprocess.run", return_value=FakeProc(1))
    def test_model_apply_rolls_back_on_verify_failure(self, _run):
        before_cfg = self.cfg_path.read_bytes()
        with self.assertRaises(opencode_cfg.ConfigError):
            self._apply("matthew", model="opencode/new-flash-free")
        self.assertEqual(self.cfg_path.read_bytes(), before_cfg)

    def test_unknown_agent_rejected_before_any_write(self):
        before = self.cfg_path.read_bytes()
        with self.assertRaises(opencode_cfg.ConfigError):
            self._apply("zzz", model="opencode/big-pickle")
        self.assertEqual(self.cfg_path.read_bytes(), before)

    def test_invalid_model_rejected(self):
        for bad in ("no-slash", 'bad"model', "has space/x", "provider/\\n"):
            with self.assertRaises(opencode_cfg.ConfigError):
                self._apply("matthew", model=bad)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(opencode_cfg.ConfigError):
            self._apply("matthew", mode="architect")

    def test_oversized_fallback_chain_rejected(self):
        chain = [f"opencode/m{i}" for i in range(6)]
        with self.assertRaises(opencode_cfg.ConfigError):
            self._apply("matthew", fallback_models=chain)


class AuthStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "auth.json"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_save_key_writes_only_to_auth_store(self, _cli):
        ui_settings.save_key("google", "SECRET_VALUE", self.store)
        data = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(data["google"], {"type": "api", "key": "SECRET_VALUE"})
        self.assertIn("google", ui_settings.auth_status(self.store))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=True)
    def test_save_key_prefers_cli(self, _cli):
        ui_settings.save_key("openai", "K", self.store)
        _cli.assert_called_once_with("openai", "K")

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_remove_key(self, _cli):
        ui_settings.save_key("openai", "K", self.store)
        self.assertTrue(ui_settings.remove_api_key("openai", self.store))
        self.assertNotIn("openai", ui_settings.auth_status(self.store))
        self.assertFalse(ui_settings.remove_api_key("openai", self.store))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_masked_status_never_returns_key(self, _cli):
        ui_settings.save_key("anthropic", "TOP_SECRET", self.store)
        status = ui_settings.auth_status(self.store)
        self.assertIn("anthropic", status)
        self.assertNotIn("TOP_SECRET", str(status))
        conns = ui_settings.connections(auth_store=self.store)
        anthropic = [c for c in conns if c["id"] == "anthropic"]
        self.assertEqual(anthropic[0]["configured"], True)
        self.assertNotIn("key", anthropic[0])
        self.assertNotIn("TOP_SECRET", json.dumps(conns))


class ConnectionTestCase(SettingsBaseTestCase):
    def test_simple_providers_metadata_has_no_model_lists(self):
        for p in ui_settings.SIMPLE_PROVIDERS:
            self.assertNotIn("models", p)

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_connections_list_masks_keys(self, _cli):
        ui_settings.save_key("google", "GKEY", self.auth_store)
        ui_settings.save_key("myrouter", "RKEY", self.auth_store)
        conns = ui_settings.connections(repo_root=self.root, auth_store=self.auth_store)
        by_id = {c["id"]: c for c in conns}
        self.assertTrue(by_id["google"]["configured"])
        self.assertNotIn("key", by_id["google"])
        self.assertNotIn("GKEY", json.dumps(conns))
        self.assertNotIn("RKEY", json.dumps(conns))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_save_advanced_writes_block_without_key(self, _cli):
        res = ui_settings.save_connection(
            "myrouter", mode="advanced", base_url="https://api.example.com/v1",
            key="SUPERSECRET", models=["myrouter/gpt-x"],
            repo_root=self.root, auth_store=self.auth_store)
        block = self._read_cfg()["provider"]["myrouter"]
        self.assertEqual(block["options"]["baseURL"], "https://api.example.com/v1")
        self.assertIn("gpt-x", block["models"])   # full id normalized to bare form
        self.assertNotIn("SUPERSECRET", self.cfg_path.read_text(encoding="utf-8"))
        self.assertTrue(res["configured"])
        self.assertIn("myrouter", ui_settings.auth_status(self.auth_store))
        self.assertNotIn("key", res)
        self.assertNotIn("SUPERSECRET", json.dumps(res))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_save_simple_with_bare_discovered_models(self, _cli):
        # discovery returns bare ids; save must accept them and store bare form
        res = ui_settings.save_connection(
            "google", mode="simple", key="K",
            models=["gemini-2.5-flash", "google/gemini-2.5-pro"],
            repo_root=self.root, auth_store=self.auth_store)
        self.assertTrue(res["ok"])
        block = self._read_cfg()["provider"]["google"]
        self.assertIn("gemini-2.5-flash", block["models"])
        self.assertIn("gemini-2.5-pro", block["models"])

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_save_accepts_name_prefixed_model_id(self, _cli):
        """gemini/gemini-2.x (name prefix) must not be rejected or stored doubled."""
        res = ui_settings.save_connection(
            "google", mode="simple", key="K", models=["gemini/gemini-2.5-flash"],
            repo_root=self.root, auth_store=self.auth_store)
        self.assertTrue(res["ok"])
        block = self._read_cfg()["provider"]["google"]
        self.assertEqual(list(block["models"]), ["gemini-2.5-flash"])

    def test_advanced_save_without_key_reports_not_configured(self):
        res = ui_settings.save_connection(
            "myrouter", mode="advanced", base_url="https://api.example.com/v1",
            repo_root=self.root, auth_store=self.auth_store)
        self.assertFalse(res["configured"])
        self.assertFalse(res["key_pending"])

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_save_simple_after_test_without_models(self, _cli):
        """Phase 25A: a Simple connection can be saved with just a tested key."""
        res = ui_settings.save_connection("google", mode="simple", key="GKEY",
                                          repo_root=self.root, auth_store=self.auth_store)
        self.assertTrue(res["ok"])
        self.assertTrue(res["configured"])
        self.assertNotIn("google", self._read_cfg().get("provider", {}))  # no block required
        self.assertIn("google", ui_settings.auth_status(self.auth_store))

    def test_advanced_invalid_base_url_rejected(self):
        """Phase 25A: nonsense configuration must fail, not save."""
        with self.assertRaises(opencode_cfg.ConfigError):
            ui_settings.save_connection("myrouter", mode="advanced", base_url="nonsense",
                                        repo_root=self.root, auth_store=self.auth_store)
        with self.assertRaises(opencode_cfg.ConfigError):
            ui_settings.save_connection("myrouter", mode="advanced", base_url=None,
                                        repo_root=self.root, auth_store=self.auth_store)
        # and nothing was written
        self.assertNotIn("myrouter", self._read_cfg().get("provider", {}))

    def test_test_connection_rejects_invalid_base_url(self):
        res = ui_settings.test_connection("myrouter", base_url="nonsense")
        self.assertFalse(res["ok"])
        self.assertIn("Base URL", res["detail"])
        res2 = ui_settings.test_connection("myrouter", base_url="")
        self.assertFalse(res2["ok"])

    def test_connection_status_derivation(self):
        base = dict(repo_root=self.root, auth_store=self.auth_store)
        by_id = {c["id"]: c for c in ui_settings.connections(**base)}
        self.assertEqual(by_id["google"]["status"], "not_configured")
        # validation_failed override shows even without a stored key
        by_id = {c["id"]: c for c in ui_settings.connections(
            **base, status_overrides={"google": "validation_failed"})}
        self.assertEqual(by_id["google"]["status"], "validation_failed")
        # key + tested override → tested
        with mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False):
            ui_settings.save_key("google", "K", self.auth_store)
        by_id = {c["id"]: c for c in ui_settings.connections(
            **base, status_overrides={"google": "tested"})}
        self.assertEqual(by_id["google"]["status"], "tested")

    def test_canonical_model_id(self):
        self.assertEqual(ui_settings.canonical_model_id("google", "gemini-2.5-flash"),
                         "google/gemini-2.5-flash")
        self.assertEqual(ui_settings.canonical_model_id("google", "google/gemini-2.5-pro"),
                         "google/gemini-2.5-pro")
        # the user's exact requirement: name-prefixed form ≡ bare form
        self.assertEqual(ui_settings.canonical_model_id("google", "gemini/gemini-2.5-pro"),
                         "google/gemini-2.5-pro")
        with self.assertRaises(opencode_cfg.ConfigError):
            ui_settings.canonical_model_id("google", "openai/gpt-5.5")

    def test_normalize_model_id_name_alias_and_custom_provider_name(self):
        self.assertEqual(ui_settings.normalize_model_id("google", "gemini/gemini-2.5-flash"),
                         "gemini-2.5-flash")
        self.assertEqual(ui_settings.normalize_model_id("google", "google/gemini-2.5-flash"),
                         "gemini-2.5-flash")
        # custom provider: the name declared in opencode.json is also an alias
        cfg = self._read_cfg()
        cfg["provider"]["myrouter"] = {"name": "My Router", "options": {}}
        self.cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.assertEqual(ui_settings.normalize_model_id("myrouter", "my router/gpt-x", cfg),
                         "gpt-x")
        with self.assertRaises(opencode_cfg.ConfigError):
            ui_settings.normalize_model_id("google", "openai/gpt-5.5")

    def test_manual_model_validation(self):
        with self.assertRaises(opencode_cfg.ConfigError):
            opencode_cfg.validate_model_id("no-slash")
        self.assertEqual(opencode_cfg.validate_model_id("ollama/qwen2.5-coder:7b"),
                         "ollama/qwen2.5-coder:7b")

    def test_bare_model_id_validation(self):
        self.assertEqual(opencode_cfg.validate_bare_model_id("gemini-2.5-flash", "google"),
                         "gemini-2.5-flash")
        self.assertEqual(opencode_cfg.validate_bare_model_id("google/gemini-2.5-pro", "google"),
                         "gemini-2.5-pro")
        with self.assertRaises(opencode_cfg.ConfigError):
            opencode_cfg.validate_bare_model_id("openai/gpt-5.5", "google")  # wrong provider
        with self.assertRaises(opencode_cfg.ConfigError):
            opencode_cfg.validate_bare_model_id("has space", "google")
        with self.assertRaises(opencode_cfg.ConfigError):
            opencode_cfg.validate_bare_model_id('bad"model', "google")


class DiscoveryTestCase(SettingsBaseTestCase):
    @mock.patch("scripts.web_ui.settings._http_json",
                return_value=({"models": [
                    {"name": "models/gemini-2.5-flash", "displayName": "Flash"},
                    {"name": "models/gemini-2.5-pro", "displayName": "Pro"},
                ]}, 42))
    def test_gemini_discovery_parses_and_annotates(self, _http):
        res = ui_settings.discover_models("google", key="K", repo_root=self.root)
        # Only the live-discovered entries matter here; the configured source
        # may legitimately include any google/ model the roster currently pins.
        discovered = [m for m in res["models"] if m["source"] == "discovered"]
        ids = [m["id"] for m in discovered]
        self.assertIn("gemini-2.5-flash", ids)
        self.assertIn("gemini-2.5-pro", ids)
        self.assertTrue(discovered)
        url = _http.call_args.args[0]
        self.assertIn("generativelanguage.googleapis.com", url)
        self.assertIn("key=K", url)

    @mock.patch("scripts.web_ui.settings._http_json",
                return_value=({"data": [{"id": "gpt-5.5"}, {"id": "gpt-5.4-mini"}]}, 30))
    def test_openai_compatible_discovery(self, _http):
        res = ui_settings.discover_models("openai", key="K", repo_root=self.root)
        ids = [m["id"] for m in res["models"]]
        self.assertIn("gpt-5.5", ids)
        self.assertIn("Authorization", _http.call_args.kwargs["headers"])

    @mock.patch("scripts.web_ui.settings._http_json",
                return_value=({"data": [{"id": "claude-opus"}]}, 25))
    def test_anthropic_discovery_headers(self, _http):
        ui_settings.discover_models("anthropic", key="K", repo_root=self.root)
        headers = _http.call_args.kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "K")
        self.assertTrue(headers["anthropic-version"].startswith("20"))

    @mock.patch("scripts.web_ui.settings._cli_models", return_value=[])
    def test_discovery_merges_configured_models(self, _cli):
        res = ui_settings.discover_models("ollama", repo_root=self.root)
        ids = [m["id"] for m in res["models"]]
        self.assertIn("qwen2.5-coder:7b", ids)
        self.assertEqual(res["models"][0]["source"], "configured")
        _cli.assert_called_once_with("ollama")

    @mock.patch("scripts.web_ui.settings._http_json",
                return_value=({"data": [{"id": "m1"}]}, 10))
    def test_test_connection_ok(self, _http):
        res = ui_settings.test_connection("openai", key="K")
        self.assertTrue(res["ok"])
        self.assertIn("latency_ms", res)

    @mock.patch("scripts.web_ui.settings._http_json",
                side_effect=HTTPError("url", 401, "Unauthorized", {}, None))
    def test_test_connection_http_error_is_safe(self, _http):
        res = ui_settings.test_connection("openai", key="K")
        self.assertFalse(res["ok"])
        self.assertIn("401", res["detail"])

    @mock.patch("scripts.web_ui.settings._http_json",
                side_effect=urllib.error.URLError("https://api.example.com/v1/models?key=SUPERSECRET"))
    def test_test_connection_error_message_never_leaks_key_or_url(self, _http):
        res = ui_settings.test_connection("openai", key="SUPERSECRET")
        self.assertFalse(res["ok"])
        self.assertNotIn("SUPERSECRET", res["detail"])
        self.assertNotIn("?key=", res["detail"])

    def test_test_connection_unknown_provider_without_base_url(self):
        res = ui_settings.test_connection("nope")
        self.assertFalse(res["ok"])
        self.assertIn("Advanced", res["detail"])


class ModelCatalogTestCase(SettingsBaseTestCase):
    """Phase 25A: saved connections feed the model catalog (AI Models)."""

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_catalog_lists_saved_connection_with_configured_models(self, _cli):
        ui_settings.save_connection("google", mode="simple", key="GKEY",
                                    models=["gemini-2.5-flash"],
                                    repo_root=self.root, auth_store=self.auth_store)
        with mock.patch("scripts.web_ui.settings._http_json",
                        side_effect=HTTPError("url", 403, "Forbidden", {}, None)):
            cat = ui_settings.model_catalog(repo_root=self.root, auth_store=self.auth_store)
        google = next(p for p in cat["providers"] if p["provider"] == "google")
        self.assertTrue(google["configured"])
        self.assertFalse(google["available"])   # offline → isolated failure, not fatal
        self.assertIn("error", google)
        ids = [m["model_id"] for m in google["models"]]
        self.assertIn("google/gemini-2.5-flash", ids)
        flash = next(m for m in google["models"] if m["model_id"] == "google/gemini-2.5-flash")
        self.assertTrue(flash["enabled"])
        self.assertEqual(flash["source"], "configured")

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_catalog_discovery_dedupes_and_normalizes(self, _cli):
        """Live discovery merges into the catalog without duplicates; both
        ``gemini-2.5-flash`` and ``google/gemini-2.5-flash`` canonicalize to one model."""
        ui_settings.save_connection("google", mode="simple", key="GKEY",
                                    models=["gemini-2.5-flash"],
                                    repo_root=self.root, auth_store=self.auth_store)
        live = {"models": [{"name": "models/gemini-2.5-flash"},
                            {"name": "models/gemini-2.5-pro"}]}
        with mock.patch("scripts.web_ui.settings._http_json", return_value=(live, 20)):
            cat = ui_settings.model_catalog(repo_root=self.root, auth_store=self.auth_store)
        google = next(p for p in cat["providers"] if p["provider"] == "google")
        self.assertTrue(google["available"])
        ids = [m["model_id"] for m in google["models"]]
        self.assertEqual(len(ids), len(set(ids)), "catalog must not contain duplicates")
        self.assertIn("google/gemini-2.5-flash", ids)
        self.assertIn("google/gemini-2.5-pro", ids)
        flash = next(m for m in google["models"] if m["model_id"] == "google/gemini-2.5-flash")
        self.assertTrue(flash["enabled"])
        self.assertEqual(flash["source"], "configured")
        pro = next(m for m in google["models"] if m["model_id"] == "google/gemini-2.5-pro")
        self.assertFalse(pro["enabled"])
        self.assertEqual(pro["source"], "discovered")

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_catalog_isolates_failing_provider(self, _cli):
        ui_settings.save_connection("google", mode="simple", key="GKEY",
                                    models=["gemini-2.5-flash"],
                                    repo_root=self.root, auth_store=self.auth_store)
        ui_settings.save_connection("myrouter", mode="advanced", key="RKEY",
                                    base_url="https://api.example.com/v1",
                                    models=["gpt-x"],
                                    repo_root=self.root, auth_store=self.auth_store)

        def fake_http(url, headers=None):
            if "example.com" in url:
                raise HTTPError(url, 401, "Unauthorized", {}, None)
            return {"models": [{"name": "models/gemini-2.5-flash"}]}, 20

        with mock.patch("scripts.web_ui.settings._http_json", side_effect=fake_http):
            cat = ui_settings.model_catalog(repo_root=self.root, auth_store=self.auth_store)
        by_id = {p["provider"]: p for p in cat["providers"]}
        self.assertIn("google", by_id)
        self.assertIn("myrouter", by_id)
        self.assertTrue(by_id["google"]["available"])
        self.assertFalse(by_id["myrouter"]["available"])
        self.assertIn("error", by_id["myrouter"])

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_catalog_never_contains_keys(self, _cli):
        ui_settings.save_connection("google", mode="simple", key="SUPERSECRET",
                                    repo_root=self.root, auth_store=self.auth_store)
        with mock.patch("scripts.web_ui.settings._http_json",
                        side_effect=HTTPError("url", 403, "Forbidden", {}, None)):
            cat = ui_settings.model_catalog(repo_root=self.root, auth_store=self.auth_store)
        blob = json.dumps(cat)
        self.assertNotIn("SUPERSECRET", blob)
        self.assertNotIn("key", cat["providers"][0])


class AgentConfigViewTestCase(SettingsBaseTestCase):
    def test_agent_config_reads_opencode(self):
        agents = ui_settings.agent_config(repo_root=self.root)
        by_key = {a["agent"]: a for a in agents}
        self.assertEqual(len(by_key), 7)
        self.assertEqual(by_key["matthew"]["mode"], "all")
        self.assertEqual(by_key["matthew"]["model"],
                         self._read_cfg()["agent"]["matthew"]["model"])
        self.assertFalse(by_key["matthew"]["drift"])

    def test_agent_config_reflects_model_change_without_drift(self):
        cfg = self._read_cfg()
        cfg["agent"]["matthew"]["model"] = "opencode/different-model"
        self.cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        by_key = {a["agent"]: a for a in ui_settings.agent_config(repo_root=self.root)}
        self.assertEqual(by_key["matthew"]["model"], "opencode/different-model")
        self.assertFalse(by_key["matthew"]["drift"])  # no spec↔config drift by design

    def test_available_models_from_config(self):
        avail = ui_settings.available_models(repo_root=self.root)
        ids = [m["id"] for m in avail]
        self.assertIn("ollama/qwen2.5-coder:7b", ids)
        for key in AGENT_KEYS:
            model = self._read_cfg()["agent"][key].get("model")
            if model:
                self.assertIn(model, ids)


class PersistenceLifecycleTestCase(SettingsBaseTestCase):
    """Phase 25B: a saved model must be visible to every in-process reader
    immediately — settings, the /api/agents reader, and RunHub — with NO
    application restart, and the persisted files must contain the new model.

    These tests run the exact real failure sequence in ONE process:
    ``apply_agent_config`` followed by each read path, proving the frozen
    import-time registry is no longer what readers depend on.
    """

    def test_agent_config_returns_new_model_after_save_in_same_process(self):
        self._apply("matthew", model="opencode/fresh-new")
        by_key = {a["agent"]: a for a in ui_settings.agent_config(repo_root=self.root)}
        self.assertEqual(by_key["matthew"]["model"], "opencode/fresh-new")
        self.assertFalse(by_key["matthew"]["drift"])
        # The spec carries no model at all — readers resolve from opencode.json.
        self.assertFalse(hasattr(AGENT_SPEC_BY_AGENT["matthew"], "model"))

    def test_agents_route_reader_returns_new_model_after_save(self):
        self._apply("alex", model="opencode/fresh-alex")
        with mock.patch.object(opencode_cfg, "PROJECT_ROOT", self.root):
            spec = AGENT_SPEC_BY_AGENT["alex"]
            model = opencode_cfg.resolve_model(spec.agent)
        self.assertEqual(model, "opencode/fresh-alex")

    def test_run_hub_resolve_returns_new_model_after_save(self):
        self._apply("david", model="opencode/fresh-david")
        with mock.patch.object(opencode_cfg, "PROJECT_ROOT", self.root):
            model, _mode = HUB.resolve("m4")
        self.assertEqual(model, "opencode/fresh-david")

    def test_full_lifecycle_old_to_new_across_all_readers_and_disk(self):
        old = opencode_cfg.resolve_model("matthew", repo_root=self.root)
        new = "opencode/lifecycle-new"
        self.assertNotEqual(old, new)
        self._apply("matthew", model=new)
        # Settings reader (agent_config)
        by_key = {a["agent"]: a for a in ui_settings.agent_config(repo_root=self.root)}
        self.assertEqual(by_key["matthew"]["model"], new)
        self.assertFalse(by_key["matthew"]["drift"])
        # /api/agents equivalent reader + RunHub resolve (repo-root reads)
        with mock.patch.object(opencode_cfg, "PROJECT_ROOT", self.root):
            spec = AGENT_SPEC_BY_AGENT["matthew"]
            self.assertEqual(opencode_cfg.resolve_model(spec.agent), new)
            model, _mode = HUB.resolve("m1")
            self.assertEqual(model, new)
        # Only opencode.json changed on disk — the spec file is never rewritten.
        self.assertEqual(self._read_cfg()["agent"]["matthew"]["model"], new)
        self.assertNotIn(f'model="{new}"', self._read_spec("matthew"))


class SimpleProviderBlockTestCase(SettingsBaseTestCase):
    """Phase 25B: Simple-provider saves and manual model adds always rebuild
    the canonical provider block — a polluted google block (wrong npm / garbage
    baseURL from an old Advanced save) must never survive, Advanced providers
    keep their validation, and no API key ever leaks."""

    POLLUTED = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "google",
        "options": {"baseURL": "ascsdacas"},
        "models": {"gemini-3.5-flash": {"name": "Gemini 3.5 Flash"}},
    }

    def _pollute_google(self) -> None:
        cfg = self._read_cfg()
        cfg["provider"]["google"] = json.loads(json.dumps(self.POLLUTED))
        self.cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_simple_save_rebuilds_polluted_google_block(self, _cli):
        self._pollute_google()
        ui_settings.save_connection(
            "google", mode="simple", key="SECRET_K", models=["gemini-2.5-flash"],
            repo_root=self.root, auth_store=self.auth_store)
        block = self._read_cfg()["provider"]["google"]
        self.assertEqual(block["npm"], "@ai-sdk/google")       # canonical package
        self.assertEqual(block["name"], "Gemini")
        self.assertNotIn("baseURL", block["options"])          # no arbitrary Base URL
        self.assertNotIn("ascsdacas", json.dumps(block))        # pollution gone
        self.assertIn("gemini-2.5-flash", block["models"])
        self.assertNotIn("SECRET_K", json.dumps(self._read_cfg()))  # no key leak

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_simple_save_without_models_still_cleans_polluted_block(self, _cli):
        self._pollute_google()
        ui_settings.save_connection("google", mode="simple", key="K",
                                    repo_root=self.root, auth_store=self.auth_store)
        block = self._read_cfg()["provider"]["google"]
        self.assertEqual(block["npm"], "@ai-sdk/google")
        self.assertEqual(block["name"], "Gemini")
        self.assertNotIn("ascsdacas", json.dumps(block))
        self.assertNotIn("baseURL", json.dumps(block.get("options", {})))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_simple_save_without_models_and_without_block_writes_nothing(self, _cli):
        # key-only save on a clean config stays block-free (built-in provider)
        ui_settings.save_connection("google", mode="simple", key="K",
                                    repo_root=self.root, auth_store=self.auth_store)
        self.assertNotIn("google", self._read_cfg().get("provider", {}))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_simple_save_canonical_for_openai(self, _cli):
        ui_settings.save_connection("openai", mode="simple", key="K",
                                    models=["gpt-5.5"],
                                    repo_root=self.root, auth_store=self.auth_store)
        block = self._read_cfg()["provider"]["openai"]
        self.assertEqual(block["npm"], "@ai-sdk/openai")
        self.assertNotIn("baseURL", json.dumps(block.get("options", {})))

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_manual_model_rebuilds_polluted_google_block(self, _cli):
        self._pollute_google()
        res = ui_settings.add_manual_model("google", "gemini-3.1-flash-lite",
                                           repo_root=self.root)
        block = self._read_cfg()["provider"]["google"]
        self.assertEqual(block["npm"], "@ai-sdk/google")
        self.assertEqual(block["name"], "Gemini")
        self.assertNotIn("ascsdacas", json.dumps(block))
        self.assertIn("gemini-3.1-flash-lite", res["models"])
        self.assertIn("gemini-3.1-flash-lite", block["models"])

    @mock.patch("scripts.web_ui.settings._auth_login_cli", return_value=False)
    def test_manual_model_preserves_advanced_block(self, _cli):
        ui_settings.save_connection(
            "myrouter", mode="advanced", base_url="https://api.example.com/v1",
            models=["gpt-x"], repo_root=self.root, auth_store=self.auth_store)
        ui_settings.add_manual_model("myrouter", "gpt-x2", repo_root=self.root)
        block = self._read_cfg()["provider"]["myrouter"]
        self.assertEqual(block["options"]["baseURL"], "https://api.example.com/v1")
        self.assertIn("gpt-x", block["models"])
        self.assertIn("gpt-x2", block["models"])

    def test_advanced_save_rejected_for_simple_provider(self):
        # the pollution path itself: Advanced mode on a known Simple provider
        with self.assertRaises(opencode_cfg.ConfigError):
            ui_settings.save_connection(
                "google", mode="advanced", base_url="https://api.example.com/v1",
                repo_root=self.root, auth_store=self.auth_store)
        self.assertNotIn("google", self._read_cfg().get("provider", {}))


if __name__ == "__main__":
    unittest.main()
