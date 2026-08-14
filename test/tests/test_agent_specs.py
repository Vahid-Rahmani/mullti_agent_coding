"""Per-agent spec unit tests — each AgentSpec module is exercised independently.

A shared base class verifies the identity invariants every agent must satisfy;
one subclass per agent (M1..M7 plus the master coordinator) pins the exact
identity. Agents are **model-agnostic**: the runtime model is resolved from
``opencode.json`` (via ``opencode_cfg.resolve_model``), never from the spec.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import (
    agents,
    opencode_cfg,
)


def _load_spec(module_name):
    """Import a spec module by name and return its ``SPEC``."""
    return __import__(f"scripts.core.agents.{module_name}", fromlist=["SPEC"]).SPEC


class _AgentSpecTestCase(unittest.TestCase):
    """Shared invariants; subclasses pin the per-agent identity.

    Abstract base: ``setUpClass`` skips it so unittest only runs the concrete
    per-agent subclasses.
    """

    module_name = ""
    tag = ""
    name = ""
    agent = ""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not cls.module_name:
            raise unittest.SkipTest("abstract base; test via a concrete subclass")
        cls.spec = _load_spec(cls.module_name)

    def test_dedicated_module_holds_spec(self):
        self.assertIsNotNone(self.spec)

    def test_identity_fields(self):
        self.assertEqual(self.spec.tag, self.tag)
        self.assertEqual(self.spec.name, self.name)
        self.assertEqual(self.spec.agent, self.agent)

    def test_model_agnostic(self):
        """An AgentSpec must not pin a model — identity is model-independent."""
        self.assertFalse(hasattr(self.spec, "model"), "AgentSpec must not carry a model")

    def test_plain_fields_only(self):
        """No specialized fields survive on any agent spec."""
        for field in ("model", "modes", "extra_modes", "persona", "role",
                      "description", "immutable", "pinned_model", "pinned_mode"):
            self.assertFalse(hasattr(self.spec, field), field)

    def test_registry_consistency(self):
        self.assertIs(agents.AGENT_SPEC_BY_TAG[self.tag], self.spec)
        self.assertIs(agents.AGENT_SPEC_BY_AGENT[self.agent], self.spec)


class TestMatthewSpec(_AgentSpecTestCase):
    module_name = "matthew"
    tag = "m1"
    name = "Matthew"
    agent = "matthew"


class TestAlexSpec(_AgentSpecTestCase):
    module_name = "alex"
    tag = "m2"
    name = "Alex"
    agent = "alex"


class TestSarahSpec(_AgentSpecTestCase):
    module_name = "sarah"
    tag = "m3"
    name = "Sarah"
    agent = "sarah"


class TestDavidSpec(_AgentSpecTestCase):
    module_name = "david"
    tag = "m4"
    name = "David"
    agent = "david"


class TestElenaSpec(_AgentSpecTestCase):
    module_name = "elena"
    tag = "m5"
    name = "Elena"
    agent = "elena"


class TestMaxSpec(_AgentSpecTestCase):
    module_name = "max"
    tag = "m6"
    name = "Max"
    agent = "max"


class TestChloeSpec(_AgentSpecTestCase):
    module_name = "chloe"
    tag = "m7"
    name = "Chloe"
    agent = "chloe"


class TestMasterSpec(_AgentSpecTestCase):
    """Master is the coordinator: no OpenCode agent, model-agnostic too."""

    module_name = "master"
    tag = "master"
    name = "Master"
    agent = None

    def test_no_opencode_agent(self):
        self.assertIsNone(self.spec.agent)
        self.assertFalse(hasattr(self.spec, "model"))

    def test_master_not_in_specialist_roster(self):
        self.assertNotIn(self.spec, agents.AGENT_SPECS)
        self.assertIs(agents.MASTER_SPEC, self.spec)

    def test_registry_consistency(self):
        # Master is the coordinator tab, not a specialist: no tag/agent lookups.
        self.assertNotIn("master", agents.AGENT_SPEC_BY_TAG)
        self.assertIs(agents.MASTER_SPEC, self.spec)


class SpecModelIndependenceTestCase(unittest.TestCase):
    """The runtime model is resolved from opencode.json, never the spec.

    The same agent must be able to execute on ANY model — so resolution reads
    ``opencode.json`` only, and no spec module is edited when a model changes.
    """

    def _write_cfg(self, root, agent_model):
        cfg = {
            "model": "opencode/big-pickle",
            "agent": {
                "matthew": {"model": agent_model, "mode": "all", "fallback_models": []},
            },
        }
        (root / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")
        return root

    def test_every_roster_agent_resolves_a_model(self):
        for spec in agents.AGENT_SPECS:
            model = opencode_cfg.resolve_model(spec.agent)
            self.assertTrue(model, f"{spec.agent}: no runtime model in opencode.json")
            self.assertIn("/", model)

    def test_same_agent_resolves_any_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for m in ("google/gemini-3.5-flash-lite", "opencode/deepseek-v4-flash-free",
                      "mulerouter/qwen3-max", "ollama/qwen2.5-coder:7b"):
                self._write_cfg(root, m)
                self.assertEqual(opencode_cfg.resolve_model("matthew", repo_root=root), m)

    def test_resolve_model_falls_back_to_top_level_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            root.joinpath("opencode.json").write_text(
                json.dumps({"model": "opencode/big-pickle", "agent": {}}),
                encoding="utf-8")
            self.assertEqual(opencode_cfg.resolve_model("matthew", repo_root=root),
                             "opencode/big-pickle")

    def test_multiple_agents_with_different_models_are_independent(self):
        """Several agents may run on different (or identical) models at once,
        and changing one agent's model never affects another."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = {
                "model": "opencode/big-pickle",
                "agent": {
                    "matthew": {"model": "google/gemini-3.5-flash-lite", "mode": "all"},
                    "alex": {"model": "opencode/deepseek-v4-flash-free", "mode": "all"},
                    "david": {"model": "mulerouter/qwen3-max", "mode": "all"},
                    "elena": {"model": "opencode/deepseek-v4-flash-free", "mode": "all"},
                },
            }
            (root / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")
            self.assertEqual(opencode_cfg.resolve_model("matthew", repo_root=root),
                             "google/gemini-3.5-flash-lite")
            self.assertEqual(opencode_cfg.resolve_model("alex", repo_root=root),
                             "opencode/deepseek-v4-flash-free")
            self.assertEqual(opencode_cfg.resolve_model("david", repo_root=root),
                             "mulerouter/qwen3-max")
            # alex and elena intentionally share the same model
            self.assertEqual(opencode_cfg.resolve_model("elena", repo_root=root),
                             "opencode/deepseek-v4-flash-free")

    def test_apply_model_never_rewrites_spec(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_cfg(root, "opencode/deepseek-v4-flash-free")
            before = agents.AGENT_SPEC_BY_AGENT["matthew"]
            opencode_cfg.apply_agent_config(
                "matthew", model="google/gemini-3.5-flash-lite",
                repo_root=root, verify_cmd=[sys.executable, "-c", "pass"])
            # The spec is a frozen identity dataclass — it has no model and
            # the source module on disk is never rewritten by a model save.
            self.assertIs(agents.AGENT_SPEC_BY_AGENT["matthew"], before)
            self.assertFalse(hasattr(before, "model"))


class SpecModeAndFallbackTestCase(unittest.TestCase):
    """Regression guard for the two invariants that silently break dispatch.

    opencode's ``run`` command refuses ``mode: subagent`` agents and falls
    back to the default agent, so every roster agent must stay primary-capable
    (``all`` / ``primary``). And a fallback chain must never contain the
    agent's own primary model (a wasted retry of a just-failed model).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(Path(REPO_ROOT) / "opencode.json", encoding="utf-8") as fh:
            cls.config = json.load(fh)

    def test_every_roster_agent_is_primary_capable(self):
        for spec in agents.AGENT_SPECS:
            entry = self.config["agent"][spec.agent]
            self.assertNotEqual(
                entry.get("mode"), "subagent",
                f"{spec.agent}: subagent mode breaks standalone dispatch "
                "(opencode run --agent falls back to the default agent)",
            )
            self.assertIn(
                entry.get("mode"), ("all", "primary"),
                f"{spec.agent}: mode must be 'all' or 'primary'",
            )

    def test_no_self_referencing_fallback_chain(self):
        for spec in agents.AGENT_SPECS:
            entry = self.config["agent"][spec.agent]
            primary = entry.get("model") or self.config.get("model")
            chain = entry.get("fallback_models") or []
            self.assertNotIn(
                primary, chain,
                f"{spec.agent}: fallback chain retries its own primary model",
            )

    def test_verify_exits_zero_on_current_config(self):
        """The live config must satisfy the extended verify invariants."""
        from scripts.core.agents import __main__ as cli

        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = cli.main(["verify"])
        self.assertEqual(code, 0, f"verify failed: {buf.getvalue()}{err.getvalue()}")


class SpecCliTestCase(unittest.TestCase):
    """The launcher CLI (scripts/core/agents/__main__.py) contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from scripts.core.agents import __main__ as cli

        cls.cli = cli

    def _capture(self, argv):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = self.cli.main(argv)
        return code, buf.getvalue(), err.getvalue()

    def test_list_prints_seven_agent_keys(self):
        code, out, _ = self._capture(["list"])
        self.assertEqual(code, 0)
        self.assertEqual(
            [ln for ln in out.splitlines() if ln.strip()],
            ["matthew", "alex", "sarah", "david", "elena", "max", "chloe"],
        )

    def test_roster_prints_slot_aligned_rows(self):
        code, out, _ = self._capture(["roster"])
        self.assertEqual(code, 0)
        rows = [row.split() for row in out.splitlines() if row.strip()]
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(len(row), 4)  # tag agent name model
        self.assertEqual(rows[0][0], "m1")
        self.assertEqual(rows[0][1], "matthew")
        self.assertEqual(rows[3][1], "david")
        self.assertEqual(rows[3][3], opencode_cfg.resolve_model("david") or "")

    def test_model_by_key_and_tag_resolves_from_opencode_json(self):
        code, out, _ = self._capture(["model", "matthew"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), opencode_cfg.resolve_model("matthew") or "")
        code, out, _ = self._capture(["model", "m7"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), opencode_cfg.resolve_model("chloe") or "")

    def test_unknown_agent_exits_2(self):
        code, _out, err = self._capture(["model", "nobody"])
        self.assertEqual(code, 2)
        self.assertIn("unknown agent", err.lower())

    def test_unknown_command_exits_2(self):
        code, _out, _err = self._capture(["bogus"])
        self.assertEqual(code, 2)

    def test_verify_reports_in_sync(self):
        code, out, _ = self._capture(["verify"])
        self.assertEqual(code, 0)
        self.assertIn("in sync", out)


if __name__ == "__main__":
    unittest.main()
