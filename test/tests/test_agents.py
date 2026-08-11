"""Unit tests for scripts/core/agents/ — the decoupled per-agent definitions.

Verifies that each specialized agent (M1..M7) plus the master coordinator is
configured by its own ``AgentSpec`` module, and that the registry derives the
same roster, routing, and mode matrices the monolith used to provide.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

from scripts.core import agents  # noqa: E402
from scripts.core.agent_definitions import (  # noqa: E402 — backward-compat shim
    AGENTS as LEGACY_AGENTS,
    ARCHIVIST_MODE,
    M7_AUDIT_MODE,
    MODE_OPTIONS_BY_MODEL,
    MODE_TO_AGENT,
    TABS as LEGACY_TABS,
)


class AgentSpecModulesTestCase(unittest.TestCase):
    """Each agent has its own module with a standalone, independent SPEC."""

    def test_seven_specialists_have_dedicated_modules(self):
        for module_name in ("matthew", "alex", "sarah", "david", "elena", "max", "chloe"):
            module = __import__(f"scripts.core.agents.{module_name}", fromlist=["SPEC"])
            self.assertIsNotNone(getattr(module, "SPEC", None), module_name)

    def test_master_coordinator_has_dedicated_module(self):
        module = __import__("scripts.core.agents.master", fromlist=["SPEC"])
        spec = module.SPEC
        self.assertEqual(spec.tag, "master")
        self.assertEqual(spec.name, "Master")
        self.assertIsNone(spec.agent)
        self.assertEqual(spec.role, "Coordinator")

    def test_specs_are_consistent(self):
        for spec in agents.AGENT_SPECS:
            self.assertEqual(spec.persona, spec.name)
            self.assertTrue(spec.tag.startswith("m"))
            self.assertIn(spec.tag, {t for t, _n, _a in agents.AGENTS})
            self.assertTrue(spec.description)

    def test_no_agent_is_model_locked(self):
        """The model/mode lock mechanism is gone: every agent (M1..M7)
        is individually configurable from the settings screen."""
        self.assertFalse(hasattr(agents, "IMMUTABLE_TAGS"))
        for spec in agents.AGENT_SPECS:
            self.assertFalse(hasattr(spec, "immutable"))
            self.assertFalse(hasattr(spec, "pinned_model"))
            self.assertFalse(hasattr(spec, "pinned_mode"))


class RegistryDerivationTestCase(unittest.TestCase):
    """Registry derives the exact roster/matrices the monolith provided."""

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

    def test_shim_matches_registry(self):
        self.assertEqual(LEGACY_AGENTS, agents.AGENTS)
        self.assertEqual(LEGACY_TABS, agents.TABS)

    def test_personas_derive_from_specs(self):
        for spec in agents.AGENT_SPECS:
            self.assertEqual(
                agents._AGENT_PERSONAS[spec.agent],
                (spec.persona, spec.role),
            )

    def test_role_descriptions_cover_all_agents(self):
        keys = sorted(agents.ROLE_DESCRIPTIONS)
        self.assertEqual(
            keys, ["alex", "chloe", "david", "elena", "matthew", "max", "sarah"]
        )


class RoutingTestCase(unittest.TestCase):
    """Mode routing and per-model matrices survive the refactor untouched."""

    def test_mode_to_agent_routes_every_agent(self):
        expected = {
            "architect": "matthew", "analyze": "matthew", "plan": "matthew",
            "backend": "alex", "api": "alex", "build": "alex",
            "frontend": "sarah", "tui": "sarah",
            "qa": "david", "test": "david", "tester": "david",
            "security": "elena", "review": "elena", "reviewer": "elena",
            "devops": "max", "automation": "max",
            "docs": "chloe", "documentation": "chloe",
        }
        for mode, agent_key in expected.items():
            self.assertEqual(agents.MODE_TO_AGENT[mode], agent_key, mode)

    def test_chloe_special_modes_route_to_chloe(self):
        for mode in (ARCHIVIST_MODE, M7_AUDIT_MODE, "compact", "compaction"):
            self.assertEqual(agents.MODE_TO_AGENT[mode], "chloe", mode)

    def test_mode_options_by_model_preserved(self):
        # The ling model only runs audit/security/docs/compact modes (contract).
        ling = agents.MODE_OPTIONS_BY_MODEL["opencode/ling-3.0-tiny-free"]
        self.assertIn(M7_AUDIT_MODE, ling)
        self.assertIn("compact", ling)
        self.assertNotIn("build", ling)
        # Every other model offers the core operational modes.
        for model in agents.MODE_OPTIONS_BY_MODEL:
            if model == "opencode/ling-3.0-tiny-free":
                continue
            self.assertIn("build", agents.MODE_OPTIONS_BY_MODEL[model], model)

    def test_shim_routing_matches(self):
        self.assertEqual(MODE_TO_AGENT, agents.MODE_TO_AGENT)
        self.assertEqual(MODE_OPTIONS_BY_MODEL, agents.MODE_OPTIONS_BY_MODEL)

    def test_operational_modes_exclude_chloe_special_modes(self):
        self.assertNotIn(M7_AUDIT_MODE, agents.ALL_OPERATIONAL_MODES)
        self.assertNotIn("compact", agents.ALL_OPERATIONAL_MODES)
        self.assertIn(ARCHIVIST_MODE, agents.ALL_OPERATIONAL_MODES)


class ResolutionTestCase(unittest.TestCase):
    """No agent is locked: resolution is uniform across the whole roster."""

    def test_resolve_without_overrides_uses_auto(self):
        from scripts.core.run_hub import HUB

        model, mode = HUB.resolve("m7", {})
        self.assertIsNone(model)
        self.assertEqual(mode, agents.AUTO_MODE)

    def test_resolve_respects_m7_override_like_every_agent(self):
        from scripts.core.run_hub import HUB

        overrides = {
            "master": {"model": "opencode/big-pickle", "mode": "plan"},
            "m7": {"model": "opencode/deepseek-v4-flash-free", "mode": "docs"},
        }
        model, mode = HUB.resolve("m7", overrides)
        self.assertEqual(model, "opencode/deepseek-v4-flash-free")
        self.assertEqual(mode, "docs")


    def test_mode_options_keep_native_modes_on_unlocked_models(self):
        """Unlocking a model for an agent never strips its native modes: M7 on
        a model whose generic matrix lacks her docs modes still offers them."""
        from scripts.core.agents import mode_options_for

        options = mode_options_for("opencode/deepseek-v4-flash-free", "m7")
        self.assertIn("docs", options)
        self.assertIn(agents.ARCHIVIST_MODE, options)
        self.assertIn(agents.M7_AUDIT_MODE, options)
        self.assertIn("build", options)  # deepseek's generic modes remain
        # No target: plain capability-matrix modes only.
        plain = mode_options_for("opencode/deepseek-v4-flash-free")
        self.assertNotIn("docs", plain)


if __name__ == "__main__":
    unittest.main()
