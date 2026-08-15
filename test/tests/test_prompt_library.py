"""Prompt Library tests — registry, workflow integration, and runtime fallback.

Covers the new ``scripts.core.prompt_library`` package plus its wiring into
``scripts.core.workflows`` (``prompt_profile`` field + validation) and
``scripts.core.workflow_engine`` (instruction fallback at dispatch). Uses temp
directories for persistence; never touches roles.json / opencode.json.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import prompt_library as P
from scripts.core import workflow_engine as E
from scripts.core import workflows as W


class TestRegistry(unittest.TestCase):
    def test_registry_loads_all_roles(self):
        roles = P.list_prompt_roles()
        for expected in ("software_engineer", "software_architect", "code_reviewer",
                         "debugger", "qa_engineer", "security_engineer",
                         "devops_engineer", "cloud_engineer", "data_engineer",
                         "ai_engineer", "researcher", "technical_writer",
                         "project_manager", "orchestrator"):
            self.assertIn(expected, roles)

    def test_all_ids_unique(self):
        profiles = P.list_prompts()
        self.assertEqual(len(profiles), 49, "49 built-in profiles expected")
        self.assertEqual(len({p.id for p in profiles}), len(profiles))

    def test_every_profile_is_well_formed(self):
        for profile in P.list_prompts():
            self.assertTrue(profile.id, profile)
            self.assertTrue(profile.name.strip(), profile.id)
            self.assertTrue(profile.prompt.strip(), profile.id)
            self.assertIn(profile.role, P.PROMPT_ROLES, profile.id)
            self.assertIn(profile.category, P.CATEGORIES, profile.id)
            self.assertTrue(profile.capabilities, profile.id)
            self.assertEqual(P.validate_profile(profile), [], profile.id)

    def test_lookup_by_id(self):
        p = P.get_prompt("software-engineer-expert")
        self.assertEqual(p.name, "Expert Software Engineer")
        self.assertEqual(p.role, "software_engineer")

    def test_unknown_id_raises_clear_error(self):
        with self.assertRaises(P.PromptError) as ctx:
            P.get_prompt("does-not-exist")
        self.assertIn("does-not-exist", str(ctx.exception))

    def test_role_filtering(self):
        eng = P.list_prompts_by_role("software_engineer")
        self.assertEqual({p.id for p in eng},
                         {"software-engineer", "software-engineer-expert",
                          "software-engineer-production"})
        self.assertEqual(P.list_prompts_by_role("no-such-role"), [])

    def test_category_filtering(self):
        sec = P.list_prompts_by_category("security")
        self.assertEqual({p.role for p in sec}, {"security_engineer"})

    def test_deterministic_ordering(self):
        a = [p.id for p in P.list_prompts()]
        b = [p.id for p in P.list_prompts()]
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))

    def test_meta_dict_omits_prompt_text(self):
        meta = P.get_prompt("software-engineer").meta_dict()
        self.assertNotIn("prompt", meta)
        self.assertIn("capabilities", meta)
        full = P.get_prompt("software-engineer").to_dict()
        self.assertIn("prompt", full)
        self.assertTrue(full["prompt"])

    def test_prompts_are_original_not_generic(self):
        # A real behaviour profile must establish principles, not a one-liner.
        text = P.get_prompt("software-engineer").prompt.lower()
        self.assertIn("inspect the existing code", text)
        self.assertIn("preserve existing behavior", text)
        self.assertGreater(len(text), 200)


class TestSuggestPromptsForRole(unittest.TestCase):
    def test_developer_maps_to_software_engineer(self):
        ids = {p.id for p in P.suggest_prompts_for_role("developer")}
        self.assertEqual(ids, {"software-engineer", "software-engineer-expert",
                               "software-engineer-production"})

    def test_python_developer_role_id(self):
        ids = {p.role for p in P.suggest_prompts_for_role("python-developer")}
        self.assertEqual(ids, {"software_engineer"})

    def test_fastapi_developer_role_id(self):
        ids = {p.role for p in P.suggest_prompts_for_role("fastapi-developer")}
        self.assertEqual(ids, {"software_engineer"})

    def test_architect_maps_to_software_architect(self):
        ids = {p.role for p in P.suggest_prompts_for_role("architect")}
        self.assertEqual(ids, {"software_architect"})

    def test_security_maps_to_security_engineer(self):
        ids = {p.role for p in P.suggest_prompts_for_role("security")}
        self.assertEqual(ids, {"security_engineer"})

    def test_ai_agent_engineer_maps_to_ai_engineer_not_software(self):
        # "ai-agent-engineer" contains both "agent" and "engineer"; the more
        # specific ai_engineer must win over the software_engineer fallback.
        ids = {p.role for p in P.suggest_prompts_for_role("ai-agent-engineer")}
        self.assertEqual(ids, {"ai_engineer"})

    def test_exact_prompt_role_matches(self):
        ids = {p.role for p in P.suggest_prompts_for_role("software_engineer")}
        self.assertEqual(ids, {"software_engineer"})

    def test_unknown_returns_empty(self):
        self.assertEqual(P.suggest_prompts_for_role("matthew"), [])
        self.assertEqual(P.suggest_prompts_for_role(""), [])


class TestWorkflowIntegration(unittest.TestCase):
    def _node(self, **kw):
        node = {"id": "a", "agent": "matthew", "kind": "agent"}
        node.update(kw)
        return node

    def _wf(self, nodes, entry=("a",)):
        return W.Workflow.from_dict({
            "id": "test-wf", "name": "Test", "nodes": nodes, "edges": [],
            "entry": list(entry),
        })

    def test_workflow_without_prompt_profile_remains_valid(self):
        wf = self._wf([self._node()])
        self.assertEqual(W.validate_workflow(wf), [])

    def test_workflow_with_prompt_profile_validates(self):
        wf = self._wf([self._node(prompt_profile="software-engineer-expert")])
        self.assertEqual(W.validate_workflow(wf), [])

    def test_unknown_prompt_profile_is_rejected(self):
        wf = self._wf([self._node(prompt_profile="nope")])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Prompt profile" in e["message"]
                            and "does not exist" in e["message"] for e in errs))

    def test_prompt_profile_persists_through_roundtrip(self):
        wf = self._wf([self._node(prompt_profile="software-engineer-expert")])
        with tempfile.TemporaryDirectory() as tmp:
            W.save_workflow(wf, Path(tmp))
            loaded = W.load_workflow("test-wf", Path(tmp))
        self.assertEqual(loaded.nodes[0].prompt_profile, "software-engineer-expert")

    def test_custom_instruction_persists_alongside_profile(self):
        wf = self._wf([self._node(prompt_profile="software-engineer-expert",
                                  instructions="Custom instructions here")])
        with tempfile.TemporaryDirectory() as tmp:
            W.save_workflow(wf, Path(tmp))
            loaded = W.load_workflow("test-wf", Path(tmp))
        node = loaded.nodes[0]
        self.assertEqual(node.prompt_profile, "software-engineer-expert")
        self.assertEqual(node.instructions, "Custom instructions here")

    def test_prompt_profile_is_optional_in_dict(self):
        # Nodes serialized before this feature (no prompt_profile key) still load.
        node = W.WorkflowNode.from_dict({"id": "a", "agent": "matthew", "kind": "agent"})
        self.assertEqual(node.prompt_profile, "")
        self.assertEqual(node.to_dict()["prompt_profile"], "")


class TestWorkflowTaskMetadata(unittest.TestCase):
    """The optional ``task`` field on a node (Phase 2) is backward compatible."""

    def _node(self, **kw):
        node = {"id": "a", "agent": "matthew", "kind": "agent"}
        node.update(kw)
        return node

    def _wf(self, nodes):
        return W.Workflow.from_dict({
            "id": "test-wf", "name": "Test", "nodes": nodes, "edges": [],
            "entry": ["a"],
        })

    def test_workflow_without_task_remains_valid(self):
        wf = self._wf([self._node()])
        self.assertEqual(wf.nodes[0].task, {})
        self.assertEqual(W.validate_workflow(wf), [])

    def test_task_metadata_persists(self):
        task = {"description": "audit auth", "category": "security",
                "capabilities": ["security", "vulnerability analysis"],
                "complexity": "medium", "risk": "high"}
        wf = self._wf([self._node(task=task)])
        with tempfile.TemporaryDirectory() as tmp:
            W.save_workflow(wf, Path(tmp))
            loaded = W.load_workflow("test-wf", Path(tmp))
        self.assertEqual(loaded.nodes[0].task, task)

    def test_task_field_is_optional_in_dict(self):
        node = W.WorkflowNode.from_dict({"id": "a", "agent": "matthew", "kind": "agent"})
        self.assertEqual(node.task, {})
        self.assertEqual(node.to_dict()["task"], {})


class TestEngineIntegration(unittest.TestCase):
    def _node(self, **kw):
        kw.setdefault("id", "a")
        kw.setdefault("agent", "matthew")
        kw.setdefault("kind", "agent")
        return W.WorkflowNode(**kw)

    def test_custom_instruction_wins_over_profile(self):
        node = self._node(prompt_profile="software-engineer-expert",
                          instructions="CUSTOM ONLY")
        prompt = E.build_node_prompt(node, {})
        self.assertIn("CUSTOM ONLY", prompt)
        self.assertNotIn("senior/staff level", prompt)  # profile text absent

    def test_empty_instruction_falls_back_to_profile(self):
        node = self._node(prompt_profile="software-engineer-expert", instructions="")
        prompt = E.build_node_prompt(node, {})
        self.assertIn("senior/staff level", prompt)  # profile text present

    def test_no_profile_uses_instruction_only(self):
        node = self._node(instructions="Just instructions")
        prompt = E.build_node_prompt(node, {})
        self.assertIn("Just instructions", prompt)

    def test_unknown_profile_is_ignored_not_fatal(self):
        # A stale/unknown profile id must not crash dispatch — it degrades to
        # no instruction rather than raising.
        node = self._node(prompt_profile="ghost-profile", instructions="")
        prompt = E.build_node_prompt(node, {})
        self.assertNotIn("ghost-profile", prompt)


if __name__ == "__main__":
    unittest.main()
