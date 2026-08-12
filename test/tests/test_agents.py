"""Unit tests for scripts/core/agents/ — the plain per-agent definitions.

Baseline-zero contract: each agent (M1..M7) plus the master coordinator is
configured by its own ``AgentSpec`` module carrying identity (tag/name/agent
key) and a configured model. No modes, personas, or role descriptions exist.
"""

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import agents  # noqa: E402


class AgentSpecModulesTestCase(unittest.TestCase):
    """Each agent has its own module with a standalone, independent SPEC."""

    def test_seven_agents_have_dedicated_modules(self):
        for module_name in ("matthew", "alex", "sarah", "david", "elena", "max", "chloe"):
            module = __import__(f"scripts.core.agents.{module_name}", fromlist=["SPEC"])
            self.assertIsNotNone(getattr(module, "SPEC", None), module_name)

    def test_master_coordinator_has_dedicated_module(self):
        module = __import__("scripts.core.agents.master", fromlist=["SPEC"])
        spec = module.SPEC
        self.assertEqual(spec.tag, "master")
        self.assertEqual(spec.name, "Master")
        self.assertIsNone(spec.agent)

    def test_specs_are_plain_and_consistent(self):
        """No specialized fields survive: specs carry identity + model only."""
        for spec in agents.AGENT_SPECS:
            self.assertTrue(spec.tag.startswith("m"))
            self.assertIn(spec.tag, {t for t, _n, _a in agents.AGENTS})
            self.assertIsNotNone(spec.agent)
            self.assertIsNotNone(spec.model)
            self.assertFalse(hasattr(spec, "modes"))
            self.assertFalse(hasattr(spec, "extra_modes"))
            self.assertFalse(hasattr(spec, "persona"))
            self.assertFalse(hasattr(spec, "role"))
            self.assertFalse(hasattr(spec, "description"))
            self.assertFalse(hasattr(spec, "immutable"))
            self.assertFalse(hasattr(spec, "pinned_model"))
            self.assertFalse(hasattr(spec, "pinned_mode"))

    def test_no_mode_or_persona_machinery_in_package(self):
        self.assertFalse(hasattr(agents, "MODE_TO_AGENT"))
        self.assertFalse(hasattr(agents, "MODE_OPTIONS_BY_MODEL"))
        self.assertFalse(hasattr(agents, "ALL_OPERATIONAL_MODES"))
        self.assertFalse(hasattr(agents, "ROLE_DESCRIPTIONS"))
        self.assertFalse(hasattr(agents, "_AGENT_PERSONAS"))
        self.assertFalse(hasattr(agents, "MODELS_BY_AGENT"))
        self.assertFalse(hasattr(agents, "AUTO_MODE"))
        self.assertFalse(hasattr(agents, "IMMUTABLE_TAGS"))


class RegistryDerivationTestCase(unittest.TestCase):
    """Registry derives the plain roster in order."""

    def test_roster_is_seven_in_order(self):
        tags = [tag for tag, _name, _agent in agents.AGENTS]
        self.assertEqual(tags, [f"m{i}" for i in range(1, 8)])
        names = [name for _tag, name, _agent in agents.AGENTS]
        self.assertEqual(
            names, ["Matthew", "Alex", "Sarah", "David", "Elena", "Max", "Chloe"]
        )
        agent_keys = [agent for _tag, _name, agent in agents.AGENTS]
        self.assertEqual(
            agent_keys, ["matthew", "alex", "sarah", "david", "elena", "max", "chloe"]
        )

    def test_tabs_lead_with_master(self):
        self.assertEqual(agents.TABS[0], ("master", "Master", None))
        self.assertEqual(len(agents.TABS), 8)

    def test_lookup_maps(self):
        for spec in agents.AGENT_SPECS:
            self.assertIs(agents.AGENT_SPEC_BY_TAG[spec.tag], spec)
            self.assertIs(agents.AGENT_SPEC_BY_AGENT[spec.agent], spec)


class ModelAssignmentTestCase(unittest.TestCase):
    """Every spec's configured model matches the verified opencode.json mirror."""

    def test_models_assigned(self):
        with open(Path(REPO_ROOT) / "opencode.json", encoding="utf-8") as fh:
            mirror = json.load(fh)["agent"]
        for spec in agents.AGENT_SPECS:
            self.assertEqual(spec.model, mirror[spec.agent]["model"], spec.agent)


class ResolutionTestCase(unittest.TestCase):
    """Every agent resolves to its configured spec model (no modes)."""

    def test_resolve_uses_spec_model(self):
        from scripts.core.run_hub import HUB

        for tag in ("m1", "m4", "m7"):
            model, mode = HUB.resolve(tag, {})
            spec = agents.AGENT_SPEC_BY_TAG[tag]
            self.assertEqual(model, spec.model)
            self.assertEqual(mode, "auto")

    def test_master_resolves_none(self):
        from scripts.core.run_hub import HUB

        model, mode = HUB.resolve("master", {})
        self.assertIsNone(model)
        self.assertEqual(mode, "auto")


if __name__ == "__main__":
    unittest.main()
