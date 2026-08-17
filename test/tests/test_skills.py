"""Skill abstraction tests — schema, registry, provenance, integration.

Covers the new ``scripts.core.skills`` module: the Skill schema and its
validation, unique ids, provenance rules (adapted skills must carry a source),
registry lookup / deterministic ordering, task suggestion, prompt rendering,
and workflow-node compatibility (skills referenced by id, validated by
``validate_workflow``). Uses temp directories where persistence is involved;
never touches roles.json / opencode.json.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import skills
from scripts.core import workflows as W

ADAPTED_SKILL_IDS = {
    "structured-research",
    "source-verification",
    "anti-slop-refinement",
    "action-first-communication",
    "seo-research",
    "competitive-analysis",
    "security-reconnaissance",
    "security-validation",
    "fix-verify-loop",
    "workflow-planning",
    "knowledge-extraction",
}


class TestSchema(unittest.TestCase):
    def test_skill_requires_id(self):
        skill = skills.Skill(id="", name="N", category="research", steps=("do",))
        problems = skills.validate_skill(skill)
        self.assertTrue(any("id is required" in m for m in problems))

    def test_skill_requires_name(self):
        skill = skills.Skill(id="s1", name=" ", category="research", steps=("do",))
        problems = skills.validate_skill(skill)
        self.assertTrue(any("name is required" in m for m in problems))

    def test_skill_requires_at_least_one_step(self):
        # a Skill is a procedure, not a prompt — no steps means it is invalid
        skill = skills.Skill(id="s1", name="N", category="research", steps=())
        problems = skills.validate_skill(skill)
        self.assertTrue(any("step" in m for m in problems))

    def test_skill_requires_known_category(self):
        skill = skills.Skill(id="s1", name="N", category="banana", steps=("do",))
        problems = skills.validate_skill(skill)
        self.assertTrue(any("unknown category" in m for m in problems))

    def test_skill_requires_slug_id(self):
        for bad in ("Uppercase", "has space", "a/b", ""):
            skill = skills.Skill(id=bad, name="N", category="research", steps=("do",))
            if bad == "":
                continue  # covered by test_skill_requires_id
            problems = skills.validate_skill(skill)
            self.assertTrue(any("invalid id" in m for m in problems), bad)

    def test_valid_skill_passes(self):
        skill = skills.Skill(
            id="my-skill", name="My Skill", description="d", category="engineering",
            steps=("one", "two"), capabilities=("coding",), version="1.0.0")
        self.assertEqual(skills.validate_skill(skill), [])

    def test_from_dict_roundtrip(self):
        skill = skills.get_skill("security-validation")
        back = skills.Skill.from_dict(skill.to_dict())
        self.assertEqual(back.id, skill.id)
        self.assertEqual(back.steps, skill.steps)
        self.assertEqual(back.source, skill.source)


class TestProvenance(unittest.TestCase):
    def test_adapted_skills_carry_source(self):
        ids = {s.id for s in skills.list_skills()}
        self.assertTrue(ADAPTED_SKILL_IDS.issubset(ids))
        for sid in ADAPTED_SKILL_IDS:
            skill = skills.get_skill(sid)
            self.assertEqual(skills.validate_skill(skill), [], sid)
            self.assertEqual(skill.origin, "adapted", sid)
            self.assertTrue(skill.source.strip(), sid)
            self.assertTrue(skill.source_url.startswith("https://"), sid)
            self.assertTrue(skill.license.strip(), sid)
            self.assertTrue(skill.adaptation_note.strip(), sid)

    def test_original_skill_defaults_to_original(self):
        skill = skills.get_skill("repository-analysis")
        self.assertEqual(skill.origin, "original")
        self.assertEqual(skill.source, "")
        self.assertEqual(skills.validate_skill(skill), [])

    def test_non_original_requires_source(self):
        skill = skills.Skill(id="no-source", name="No Source", category="research",
                             steps=("do",), origin="adapted")
        problems = skills.validate_skill(skill)
        self.assertTrue(any("requires a source reference" in m for m in problems))

    def test_unknown_origin_is_rejected(self):
        skill = skills.Skill(id="bad-origin", name="Bad", category="research",
                             steps=("do",), origin="stolen")
        problems = skills.validate_skill(skill)
        self.assertTrue(any("unknown origin" in m for m in problems))


class TestRegistry(unittest.TestCase):
    def test_all_ids_unique(self):
        all_skills = skills.list_skills()
        self.assertEqual(len(all_skills), 12, "12 built-in skills expected")
        self.assertEqual(len({s.id for s in all_skills}), len(all_skills))

    def test_deterministic_ordering(self):
        a = [s.id for s in skills.list_skills()]
        self.assertEqual(a, sorted(a))

    def test_get_skill_and_unknown_raises(self):
        self.assertEqual(skills.get_skill("seo-research").category, "seo")
        with self.assertRaises(skills.SkillError):
            skills.get_skill("does-not-exist")

    def test_category_filtering(self):
        sec = skills.list_skills_by_category("security")
        self.assertEqual({s.id for s in sec},
                         {"security-reconnaissance", "security-validation",
                          "fix-verify-loop"})
        self.assertEqual(skills.list_skills_by_category("no-such"), [])

    def test_skills_are_model_and_agent_independent(self):
        # no skill may reference a model id or an agent key
        for skill in skills.list_skills():
            self.assertNotIn("opencode/", skill.id)
            self.assertNotIn("agent", skill.category)


class TestSuggest(unittest.TestCase):
    def test_security_task_suggests_security_skills(self):
        out = {s.id for s in skills.suggest_skills_for_task(
            "find and validate vulnerabilities, then fix and re-scan")}
        self.assertIn("security-validation", out)
        self.assertIn("fix-verify-loop", out)

    def test_research_task_suggests_research_skills(self):
        out = {s.id for s in skills.suggest_skills_for_task(
            "collect sources and cite every claim")}
        self.assertIn("structured-research", out)
        self.assertIn("source-verification", out)

    def test_empty_returns_empty(self):
        self.assertEqual(skills.suggest_skills_for_task(""), [])
        self.assertEqual(skills.suggest_skills_for_task("zzz"), [])

    def test_suggestion_order_is_stable(self):
        a = [s.id for s in skills.suggest_skills_for_task("pentest and re-scan")]
        b = [s.id for s in skills.suggest_skills_for_task("pentest and re-scan")]
        self.assertEqual(a, b)


class TestRendering(unittest.TestCase):
    def test_render_includes_name_and_steps(self):
        ctx = skills.render_skill_context(["fix-verify-loop"])
        self.assertIn("## Skills", ctx)
        self.assertIn("Fix → Verify Loop", ctx)
        self.assertIn("1.", ctx)

    def test_render_empty_and_unknown_returns_empty(self):
        self.assertEqual(skills.render_skill_context([]), "")
        self.assertEqual(skills.render_skill_context(["nope"]), "")
        self.assertEqual(skills.render_skill_context(None), "")

    def test_render_deduplicates(self):
        ctx = skills.render_skill_context(["seo-research", "seo-research"])
        self.assertEqual(ctx.count("SEO Keyword Research"), 1)

    def test_resolve_skill_prompt(self):
        skill = skills.get_skill("seo-research")
        profile = skills.resolve_skill_prompt(skill)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.id, "seo-keyword-research")
        self.assertIsNone(skills.resolve_skill_prompt(
            skills.get_skill("repository-analysis")))


class TestWorkflowIntegration(unittest.TestCase):
    def _node(self, **kw):
        node = {"id": "a", "agent": "matthew", "kind": "agent"}
        node.update(kw)
        return node

    def _wf(self, nodes, evaluation=""):
        return W.Workflow.from_dict({
            "id": "test-wf", "name": "Test", "nodes": nodes, "edges": [],
            "entry": ["a"], "evaluation": evaluation,
        })

    def test_workflow_with_skills_validates(self):
        wf = self._wf([self._node(skills=["security-validation"])])
        self.assertEqual(W.validate_workflow(wf), [])

    def test_unknown_skill_rejected(self):
        wf = self._wf([self._node(skills=["nope"])])
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Skill" in e["message"] and "does not exist" in e["message"]
                            for e in errs))

    def test_skill_persists_through_roundtrip(self):
        node = W.WorkflowNode.from_dict(
            {"id": "a", "agent": "matthew", "kind": "agent",
             "skills": ["seo-research", "competitive-analysis"]})
        self.assertEqual(node.skills, ("seo-research", "competitive-analysis"))
        self.assertEqual(node.to_dict()["skills"],
                         ["seo-research", "competitive-analysis"])
        back = W.WorkflowNode.from_dict(node.to_dict())
        self.assertEqual(back.skills, ("seo-research", "competitive-analysis"))

    def test_node_without_skills_is_backward_compatible(self):
        node = W.WorkflowNode.from_dict(
            {"id": "a", "agent": "matthew", "kind": "agent"})
        self.assertEqual(node.skills, ())
        self.assertEqual(node.to_dict()["skills"], [])

    def test_workflow_evaluation_validates(self):
        wf = self._wf([self._node()], evaluation="agent-output-quality")
        self.assertEqual(W.validate_workflow(wf), [])

    def test_unknown_evaluation_rejected(self):
        wf = self._wf([self._node()], evaluation="nope")
        errs = W.validate_workflow(wf)
        self.assertTrue(any("Evaluation" in e["message"] and "does not exist" in e["message"]
                            for e in errs))

    def test_evaluation_roundtrips(self):
        wf = self._wf([self._node()], evaluation="security-findings-quality")
        self.assertEqual(wf.to_dict()["evaluation"], "security-findings-quality")
        back = W.Workflow.from_dict(wf.to_dict())
        self.assertEqual(back.evaluation, "security-findings-quality")

    def test_empty_roles_in_skills_normalize_away(self):
        node = W.WorkflowNode.from_dict(
            {"id": "a", "agent": "matthew", "kind": "agent",
             "skills": ["", "seo-research", " "]})
        self.assertEqual(node.skills, ("seo-research",))
        self.assertEqual(W.validate_workflow(self._wf([node.to_dict()])), [])


if __name__ == "__main__":
    unittest.main()
