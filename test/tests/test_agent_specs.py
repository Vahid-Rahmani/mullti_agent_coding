"""Per-agent spec unit tests — each AgentSpec module is exercised independently.

A shared base class verifies the invariants every agent must satisfy; one
subclass per agent (M1..M7 plus the master coordinator) pins the exact
identity, mode set, configured model, and routing, so a change to one agent's
spec surfaces in that agent's test class only.

Also verifies the launcher contract: every spec's configured model must match
``opencode.json`` (the runtime OpenCode config) and must be a model the agent
can actually run (``MODELS_BY_AGENT`` capability matrix).
"""

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import agents  # noqa: E402


def _load_spec(module_name):
    """Import a spec module by name and return its ``SPEC``."""
    return __import__(f"scripts.core.agents.{module_name}", fromlist=["SPEC"]).SPEC


class _AgentSpecTestCase(unittest.TestCase):
    """Shared invariants; subclasses pin the per-agent values.

    Abstract base: ``setUpClass`` skips it so unittest only runs the concrete
    per-agent subclasses.
    """

    module_name = ""
    tag = ""
    name = ""
    agent = ""
    role = ""
    modes = ()
    extra_modes = ()
    model = ""
    immutable = False
    pinned_model = None
    pinned_mode = None

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
        self.assertEqual(self.spec.role, self.role)
        self.assertEqual(self.spec.persona, self.name)

    def test_modes_declared(self):
        self.assertEqual(tuple(self.spec.modes), tuple(self.modes))
        self.assertEqual(tuple(self.spec.extra_modes), tuple(self.extra_modes))

    def test_all_modes_are_unique(self):
        all_modes = self.spec.all_modes
        self.assertEqual(len(all_modes), len(set(all_modes)))

    def test_operational_modes_route_to_self(self):
        for mode in self.spec.modes:
            self.assertEqual(agents.MODE_TO_AGENT[mode], self.agent, mode)

    def test_extra_modes_route_to_self(self):
        for mode in self.spec.extra_modes:
            self.assertEqual(agents.MODE_TO_AGENT[mode], self.agent, mode)

    def test_operational_modes_offered_to_auto_model(self):
        for mode in self.spec.modes:
            self.assertIn(mode, agents.ALL_OPERATIONAL_MODES, mode)

    def test_extra_modes_not_operational(self):
        for mode in self.spec.extra_modes:
            self.assertNotIn(mode, agents.ALL_OPERATIONAL_MODES, mode)

    def test_model_configured_and_valid(self):
        self.assertEqual(self.spec.model, self.model)
        self.assertIn(self.spec.model, agents.MODEL_OPTIONS)

    def test_configured_model_is_capable(self):
        """The agent must be able to run on its own configured model."""
        self.assertIn(self.spec.model, agents.MODELS_BY_AGENT[self.agent])

    def test_description_mentions_agent(self):
        self.assertIn(self.name.lower(), self.spec.description.lower())

    def test_immutable_lock(self):
        self.assertEqual(self.spec.immutable, self.immutable)
        if self.immutable:
            self.assertEqual(self.spec.pinned_model, self.pinned_model)
            self.assertEqual(self.spec.pinned_mode, self.pinned_mode)
        else:
            self.assertIsNone(self.spec.pinned_model)
            self.assertIsNone(self.spec.pinned_mode)

    def test_registry_consistency(self):
        self.assertIs(agents.AGENT_SPEC_BY_TAG[self.tag], self.spec)
        self.assertIs(agents.AGENT_SPEC_BY_AGENT[self.agent], self.spec)


class TestMatthewSpec(_AgentSpecTestCase):
    module_name = "matthew"
    tag = "m1"
    name = "Matthew"
    agent = "matthew"
    role = "Architect"
    modes = ("architect", "analyze", "plan", "matthew")
    model = "opencode/deepseek-v4-flash-free"


class TestAlexSpec(_AgentSpecTestCase):
    module_name = "alex"
    tag = "m2"
    name = "Alex"
    agent = "alex"
    role = "Builder"
    modes = ("backend", "api", "build", "alex")
    model = "opencode/deepseek-v4-flash-free"


class TestSarahSpec(_AgentSpecTestCase):
    module_name = "sarah"
    tag = "m3"
    name = "Sarah"
    agent = "sarah"
    role = "Frontend"
    modes = ("frontend", "tui", "sarah")
    model = "opencode/deepseek-v4-flash-free"


class TestDavidSpec(_AgentSpecTestCase):
    module_name = "david"
    tag = "m4"
    name = "David"
    agent = "david"
    role = "QA"
    modes = ("qa", "test", "tester", "david")
    model = "opencode/big-pickle"


class TestElenaSpec(_AgentSpecTestCase):
    module_name = "elena"
    tag = "m5"
    name = "Elena"
    agent = "elena"
    role = "Security"
    modes = ("security", "review", "reviewer", "elena")
    model = "opencode/ling-3.0-tiny-free"


class TestMaxSpec(_AgentSpecTestCase):
    module_name = "max"
    tag = "m6"
    name = "Max"
    agent = "max"
    role = "DevOps"
    modes = ("devops", "automation", "max")
    model = "opencode/deepseek-v4-flash-free"


class TestChloeSpec(_AgentSpecTestCase):
    module_name = "chloe"
    tag = "m7"
    name = "Chloe"
    agent = "chloe"
    role = "Archivist"
    modes = ("docs", "documentation", "chloe", agents.ARCHIVIST_MODE)
    extra_modes = (agents.M7_AUDIT_MODE, "compact", "compaction")
    model = "opencode/ling-3.0-tiny-free"
    immutable = True
    pinned_model = "opencode/ling-3.0-tiny-free"
    pinned_mode = agents.M7_AUDIT_MODE


class TestMasterSpec(_AgentSpecTestCase):
    """Master is the coordinator: no OpenCode agent, no model, no modes."""

    module_name = "master"
    tag = "master"
    name = "Master"
    agent = None
    role = "Coordinator"
    modes = ()
    extra_modes = ()
    model = None

    def test_no_opencode_agent(self):
        self.assertIsNone(self.spec.agent)
        self.assertIsNone(self.spec.model)

    def test_master_not_in_specialist_roster(self):
        self.assertNotIn(self.spec, agents.AGENT_SPECS)
        self.assertIs(agents.MASTER_SPEC, self.spec)

    def test_registry_consistency(self):
        # Master is the coordinator tab, not a specialist: no tag/agent lookups.
        self.assertNotIn("master", agents.AGENT_SPEC_BY_TAG)
        self.assertIs(agents.MASTER_SPEC, self.spec)

    def test_operational_modes_route_to_self(self):  # no modes to route
        pass

    def test_extra_modes_route_to_self(self):
        pass

    def test_model_configured_and_valid(self):
        self.assertIsNone(self.spec.model)

    def test_configured_model_is_capable(self):
        pass  # master has no model by design


class ModelCapabilityTestCase(unittest.TestCase):
    """The capability matrix and its inverse are consistent."""

    def test_modes_by_agent_covers_every_agent(self):
        for spec in agents.AGENT_SPECS:
            self.assertIn(spec.agent, agents.MODELS_BY_AGENT)
            self.assertTrue(agents.MODELS_BY_AGENT[spec.agent], spec.agent)

    def test_auto_model_can_run_every_agent(self):
        for spec in agents.AGENT_SPECS:
            self.assertIn(
                agents.AUTO_MODEL, agents.MODELS_BY_AGENT[spec.agent], spec.agent
            )

    def test_ling_only_offers_fast_audit_agents(self):
        ling = agents.MODELS_BY_AGENT
        self.assertIn("opencode/ling-3.0-tiny-free", ling["elena"])
        self.assertIn("opencode/ling-3.0-tiny-free", ling["chloe"])
        self.assertNotIn("opencode/ling-3.0-tiny-free", ling["matthew"])
        self.assertNotIn("opencode/ling-3.0-tiny-free", ling["alex"])
        self.assertNotIn("opencode/ling-3.0-tiny-free", ling["david"])

    def test_matrix_and_inverse_agree(self):
        for agent_key, models in agents.MODELS_BY_AGENT.items():
            for model in models:
                spec = agents.AGENT_SPEC_BY_AGENT[agent_key]
                self.assertTrue(
                    any(mode in agents.MODE_OPTIONS_BY_MODEL[model] for mode in spec.all_modes),
                    f"{model} offers no mode for {agent_key}",
                )


class SpecModelConsistencyTestCase(unittest.TestCase):
    """Spec models must match opencode.json so launcher, terminal, and OpenCode agree."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with open(Path(REPO_ROOT) / "opencode.json", encoding="utf-8") as fh:
            cls.config = json.load(fh)

    def test_every_agent_model_matches_opencode_json(self):
        for spec in agents.AGENT_SPECS:
            json_model = self.config["agent"][spec.agent]["model"]
            self.assertEqual(spec.model, json_model, spec.agent)


class SpecCliTestCase(unittest.TestCase):
    """The launcher CLI (scripts/core/agents/__main__.py) contract."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from scripts.core.agents import __main__ as cli

        cls.cli = cli

    def _capture(self, argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout

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
            self.assertEqual(len(row), 5)  # tag agent name role model
        self.assertEqual(rows[0][0], "m1")
        self.assertEqual(rows[0][1], "matthew")
        self.assertEqual(rows[3][1], "david")
        self.assertEqual(rows[3][4], "opencode/big-pickle")

    def test_model_by_key_and_tag(self):
        code, out, _ = self._capture(["model", "matthew"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "opencode/deepseek-v4-flash-free")
        code, out, _ = self._capture(["model", "m7"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "opencode/ling-3.0-tiny-free")

    def test_models_lists_capable_models(self):
        code, out, _ = self._capture(["models", "chloe"])
        self.assertEqual(code, 0)
        models = out.split()
        self.assertIn("opencode/ling-3.0-tiny-free", models)
        self.assertNotIn("opencode/deepseek-v4-flash-free", models)

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
