"""Agent Catalog tests — Empty Agent, categories, presets, runtime integration.

Covers the Phase-30 follow-up: the deterministic Agent Catalog (presets
organized by category) and the special Empty Agent. Fixtures never touch the
real ``roles.json`` / ``opencode.json``; every runtime prompt is built against a
temp repo root.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import agent_catalog as ac
from scripts.core import prompt_library, roles, runtime_context
from scripts.core.agents import AGENT_SPEC_BY_AGENT

EXISTING_AGENTS = ("matthew", "alex", "sarah", "david", "elena", "max", "chloe")


class EmptyAgentTestCase(unittest.TestCase):
    def test_empty_agent_has_no_configuration(self):
        e = ac.empty_agent()
        self.assertEqual(e.id, ac.EMPTY_AGENT_ID)
        self.assertEqual(e.agent_key, "")
        self.assertEqual(e.role, "")
        self.assertEqual(e.skills, ())
        self.assertEqual(e.prompt_profiles, ())
        self.assertEqual(e.model, "")
        self.assertEqual(e.agent_mode, "")
        self.assertEqual(e.knowledge, ())

    def test_resolved_empty_agent_has_no_configuration(self):
        cfg = ac.resolve_preset_config(ac.empty_agent())
        self.assertTrue(cfg["empty"])
        self.assertEqual(cfg["agent_key"], "")
        self.assertEqual(cfg["role"], "")
        self.assertEqual(cfg["skills"], [])
        self.assertEqual(cfg["prompt_profiles"], [])
        self.assertEqual(cfg["knowledge"], [])

    def test_empty_agent_does_not_inherit_role_derived_skills(self):
        # The Empty Agent has no roles, so role-derived skills/profiles are empty
        # and it can never accidentally inherit them.
        self.assertEqual(runtime_context.role_derived_skill_ids_for_agent("empty"), [])
        self.assertEqual(runtime_context.role_derived_profile_ids_for_agent("empty"), [])

    def test_empty_agent_runtime_is_raw_request(self):
        # The Empty Agent receives only the user's request.
        self.assertEqual(ac.build_preset_runtime_prompt(ac.empty_agent(), "hello"), "hello")
        self.assertEqual(
            runtime_context.build_runtime_prompt("empty", user_request="plain prompt"),
            "plain prompt",
        )


class CategoryTestCase(unittest.TestCase):
    def test_category_returns_exactly_registered_presets(self):
        for cat in ac.list_categories():
            by_cat = {p.id for p in ac.presets_for_category(cat.id)}
            expected = {p.id for p in ac.list_presets() if p.category == cat.id}
            self.assertEqual(by_cat, expected)

    def test_no_cross_category_leak(self):
        self.assertEqual({p.id for p in ac.presets_for_category("research")},
                         {"researcher"})
        self.assertEqual({p.id for p in ac.presets_for_category("security")},
                         {"security-engineer"})
        self.assertNotIn("security-engineer",
                         {p.id for p in ac.presets_for_category("research")})

    def test_every_preset_belongs_to_a_known_category(self):
        cats = {c.id for c in ac.list_categories()}
        for p in ac.list_presets():
            self.assertIn(p.category, cats)


class PresetConfigTestCase(unittest.TestCase):
    def test_preset_has_deterministic_config(self):
        p = ac.get_preset("researcher")
        cfg = ac.resolve_preset_config(p)
        self.assertEqual(cfg["agent_key"], "sarah")
        self.assertEqual(cfg["role"], "researcher")
        self.assertEqual(cfg["skills"], ["structured-research", "source-verification"])
        self.assertEqual(cfg["prompt_profiles"], ["researcher-analyst"])
        self.assertEqual(cfg["agent_mode"], "all")
        self.assertEqual(cfg, ac.resolve_preset_config(p))  # deterministic

    def test_template_selection_populates_config(self):
        # Template → Preset → Model → Mode → Role → Skills → Prompt Profile.
        p = ac.get_preset("security-engineer")
        cfg = ac.resolve_preset_config(p)
        self.assertEqual(cfg["role"], "security-engineer")
        self.assertIn("security-reconnaissance", cfg["skills"])
        self.assertIn("security-validation", cfg["skills"])
        self.assertIn("security-auditor", cfg["prompt_profiles"])
        self.assertTrue(cfg["model"])  # resolved from the agent's runtime model

    def test_template_selection_produces_expected_model_and_mode(self):
        # The preset's model is the referenced agent's runtime model (from
        # opencode.json), and mode defaults deterministically to "all".
        from scripts.core import opencode_cfg

        p = ac.get_preset("security-engineer")
        cfg = ac.resolve_preset_config(p)
        self.assertEqual(cfg["model"], opencode_cfg.resolve_model("alex"))
        self.assertEqual(cfg["agent_mode"], "all")
        # An explicit model on a preset would win over the inherited default.
        explicit = ac.AgentPreset(
            id="x", display_name="X", category="security", agent_key="alex",
            role="security-engineer", model="opencode/big-pickle")
        self.assertEqual(ac.resolve_preset_config(explicit)["model"],
                         "opencode/big-pickle")

    def test_every_preset_has_valid_complete_configuration(self):
        # Requirement 15.4: every preset resolves a complete, valid config.
        for p in ac.list_presets():
            self.assertEqual(ac.validate_preset(p), [], f"{p.id}: invalid references")
            cfg = ac.resolve_preset_config(p)
            self.assertTrue(cfg["role"], f"{p.id}: missing role")
            self.assertTrue(cfg["skills"], f"{p.id}: missing skills")
            self.assertTrue(cfg["prompt_profiles"], f"{p.id}: missing prompt profiles")
            self.assertTrue(cfg["model"], f"{p.id}: missing resolved model")
            self.assertEqual(cfg["agent_mode"], "all", f"{p.id}: bad mode")


class RuntimeIntegrationTestCase(unittest.TestCase):
    def test_preset_runtime_contains_config(self):
        p = ac.get_preset("researcher")
        prompt = ac.build_preset_runtime_prompt(p, "do research")
        self.assertIn("## Agent Identity", prompt)
        self.assertIn("Researcher", prompt)            # role name
        self.assertIn("Structured Research", prompt)   # skill name
        self.assertIn("Research Analyst", prompt)      # prompt-profile name
        self.assertIn("do research", prompt)           # user request last

    def test_explicit_customization_overrides_preset_defaults(self):
        # Explicit role/skill/profile ids beat the preset's own defaults.
        prompt = runtime_context.build_runtime_prompt(
            "sarah", role_ids=[], skill_ids=["source-verification"],
            prompt_profile_ids=[], user_request="x")
        self.assertIn("Source Verification", prompt)
        self.assertNotIn("Structured Research", prompt)


class ValidationTestCase(unittest.TestCase):
    def test_no_duplicate_preset_ids(self):
        ids = [p.id for p in ac.list_presets()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_duplicate_role_ids(self):
        ids = [r.id for r in roles.list_roles()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_duplicate_prompt_profile_ids(self):
        ids = [p.id for p in prompt_library.list_prompts()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_builtin_catalog_is_valid(self):
        self.assertEqual(ac.validate_catalog(), [])

    def test_unknown_role_reference_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roles.save_roles({"roles": {"researcher": {"name": "Researcher"}},
                              "assignments": {}}, root)
            problems = ac.validate_catalog(root)
            self.assertTrue(any("unknown role" in p for p in problems))

    def test_unknown_skill_and_prompt_references_fail_validation(self):
        bad = ac.AgentPreset(
            id="x-bad", display_name="Bad", category="security",
            agent_key="alex", role="security-engineer",
            skills=("does-not-exist",), prompt_profiles=("also-missing",))
        problems = ac.validate_preset(bad)
        self.assertTrue(any("unknown skill" in p for p in problems))
        self.assertTrue(any("unknown prompt profile" in p for p in problems))

    def test_unknown_agent_key_fails_validation(self):
        bad = ac.AgentPreset(id="x-bad", display_name="Bad", category="security",
                             agent_key="nobody", role="security-engineer")
        problems = ac.validate_preset(bad)
        self.assertTrue(any("unknown agent key" in p for p in problems))


class ExistingAgentsPreservedTestCase(unittest.TestCase):
    def test_all_existing_agents_still_exist(self):
        for key in EXISTING_AGENTS:
            self.assertIn(key, AGENT_SPEC_BY_AGENT)

    def test_every_preset_references_an_existing_agent(self):
        for p in ac.list_presets():
            if p.agent_key:
                self.assertIn(p.agent_key, AGENT_SPEC_BY_AGENT)

    def test_every_existing_agent_is_used_by_at_least_one_preset(self):
        used = {p.agent_key for p in ac.list_presets() if p.agent_key}
        self.assertEqual(used, set(EXISTING_AGENTS))


class RoleAndPromptCategoryTestCase(unittest.TestCase):
    def test_role_category_filter(self):
        # Roles are grouped by category; only that category's roles are returned.
        self.assertEqual(ac.roles_in_category("security"), ("security-engineer",))
        self.assertIn("python-developer", ac.roles_in_category("development"))
        self.assertNotIn("security-engineer", ac.roles_in_category("development"))

    def test_prompt_category_filter(self):
        # Prompt profiles filter by category (reuse the prompt library's own
        # category grouping).
        for cat in prompt_library.CATEGORIES:
            profs = prompt_library.list_prompts_by_category(cat)
            self.assertTrue(all(p.category == cat for p in profs))

    def test_role_category_map_covers_all_builtin_roles(self):
        for r in roles.list_roles():
            self.assertIn(ac.role_category(r.id),
                          {c.id for c in ac.list_categories()} | {""})


class RepositoryTaxonomyTestCase(unittest.TestCase):
    def test_categories_carry_provenance(self):
        cats = {c.id: c for c in ac.list_categories()}
        self.assertIn("documentation", cats)
        self.assertIn("virgiliojr94/book-to-skill", cats["documentation"].sources)
        self.assertIn("Anil-matcha/Open-Generative-AI", cats["ai"].sources)

    def test_documentation_category_presets(self):
        self.assertEqual({p.id for p in ac.presets_for_category("documentation")},
                         {"technical-writer", "knowledge-engineer"})

    def test_repository_derived_roles_exist_and_resolve(self):
        for role_id in ("ai-llm-engineer", "technical-writer", "knowledge-engineer"):
            self.assertIsNotNone(roles.get_role(role_id))
            self.assertTrue(ac.role_category(role_id), role_id)
            self.assertTrue(ac.role_sources(role_id), role_id)

    def test_new_presets_resolve_deterministically(self):
        for pid in ("ai-llm-engineer", "technical-writer", "knowledge-engineer"):
            p = ac.get_preset(pid)
            cfg = ac.resolve_preset_config(p)
            self.assertTrue(cfg["role"])
            self.assertTrue(cfg["skills"])
            self.assertTrue(cfg["prompt_profiles"])
            self.assertTrue(cfg["model"])

    def test_role_sources_cover_role_category_map(self):
        # Every categorized role has an evidence record and vice versa.
        self.assertEqual(set(ac.ROLE_CATEGORY_MAP), set(ac.ROLE_SOURCES))

    def test_role_category_consistency_enforced(self):
        # A preset whose role's category conflicts with its own is flagged.
        bad = ac.AgentPreset(id="x-bad", display_name="Bad", category="security",
                             agent_key="alex", role="technical-writer")
        problems = ac.validate_preset(bad)
        self.assertTrue(any("belongs to category" in m for m in problems))

    def test_role_category_mapping_unknown_role_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            roles.save_roles({"roles": {"researcher": {"name": "Researcher"}},
                              "assignments": {}}, root)
            problems = ac.validate_catalog(root)
            self.assertTrue(any("role-category mapping references unknown role" in p
                                for p in problems))


if __name__ == "__main__":
    unittest.main()
