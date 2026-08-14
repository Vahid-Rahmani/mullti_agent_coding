"""Phase 2 Task Profile tests — classification, role mapping, prompt ranking.

Deterministic (no LLM): these assert that a task string maps to the same
category/role/prompt every time, that scores are bounded and ordered, and that
an explicit role overrides the inferred one.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import prompt_library as P

# section 17 built-in mappings → the first-ranked prompt id
SECTION_17_CASES = [
    ("write code", "software-engineer"),
    ("implement feature", "software-engineer-expert"),
    ("refactor code", "software-engineer-production"),
    ("design architecture", "system-architect"),
    ("review architecture", "architecture-reviewer"),
    ("debug error", "debugger-root-cause"),
    ("find bugs", "code-reviewer"),
    ("security audit", "security-auditor"),
    ("threat model", "security-threat-modeler"),
    ("write tests", "qa-test-engineer"),
    ("E2E tests", "qa-e2e-engineer"),
    ("CI/CD", "devops-cicd"),
    ("Azure infrastructure", "cloud-azure"),
    ("data pipeline", "data-pipeline-engineer"),
    ("LLM", "ai-llm-engineer"),
    ("RAG", "ai-llm-engineer"),
    ("AI agent", "ai-agent-engineer"),
    ("research", "researcher-technical"),
    ("documentation", "writer-documentation"),
    ("project planning", "pm-delivery"),
    ("multi-agent workflow", "orchestrator-multi-agent"),
]


class TestTaskProfile(unittest.TestCase):
    def test_schema_roundtrip(self):
        tp = P.TaskProfile(category="security",
                           capabilities=("security", "vulnerability analysis"),
                           complexity="high", risk="high", context="audit")
        d = tp.to_dict()
        rebuilt = P.TaskProfile.from_dict(d)
        self.assertEqual(rebuilt.category, "security")
        self.assertEqual(rebuilt.capabilities, ("security", "vulnerability analysis"))
        self.assertEqual(rebuilt.complexity, "high")
        self.assertEqual(rebuilt.risk, "high")
        self.assertEqual(rebuilt.context, "audit")

    def test_categories_known(self):
        for cat in ("development", "architecture", "debugging", "review",
                    "testing", "security", "devops", "cloud", "data", "ai",
                    "research", "documentation", "planning", "orchestration",
                    "general"):
            self.assertIn(cat, P.TASK_CATEGORIES)

    def test_classify_development(self):
        tp = P.classify_task("implement a new feature in the codebase")
        self.assertEqual(tp.category, "development")

    def test_classify_security_with_risk_and_complexity(self):
        tp = P.classify_task("audit the production authentication flow for "
                             "critical vulnerabilities")
        self.assertEqual(tp.category, "security")
        self.assertEqual(tp.risk, "high")
        self.assertIn("audit", tp.capabilities)

    def test_classify_high_complexity(self):
        tp = P.classify_task("design a complex distributed system")
        self.assertEqual(tp.complexity, "high")

    def test_classify_general_fallback(self):
        tp = P.classify_task("help me please")
        self.assertEqual(tp.category, "general")


class TestRoleMatching(unittest.TestCase):
    def test_coding_maps_to_software_engineer(self):
        self.assertEqual(P.suggest_roles_for_task("write some code")[0],
                         "software_engineer")

    def test_architecture_maps_to_architect(self):
        self.assertIn("software_architect",
                      P.suggest_roles_for_task("design the architecture"))

    def test_security_audit_maps_to_security(self):
        self.assertEqual(P.suggest_roles_for_task("security audit")[0],
                         "security_engineer")

    def test_ai_agent_maps_to_ai_engineer(self):
        self.assertEqual(P.suggest_roles_for_task("build an AI agent")[0],
                         "ai_engineer")

    def test_documentation_maps_to_writer(self):
        self.assertEqual(P.suggest_roles_for_task("write documentation")[0],
                         "technical_writer")

    def test_no_match_returns_empty(self):
        self.assertEqual(P.suggest_roles_for_task("xyzzy"), [])

    def test_task_profile_uses_its_category(self):
        tp = P.TaskProfile(category="security")
        self.assertEqual(P.suggest_roles_for_task(tp)[0], "security_engineer")


class TestPromptRecommendation(unittest.TestCase):
    def test_section_17_mappings(self):
        for task, expected in SECTION_17_CASES:
            recs = P.recommend_prompts(task)
            self.assertTrue(recs, f"no recommendation for {task!r}")
            self.assertEqual(recs[0].prompt_id, expected, task)

    def test_deterministic(self):
        a = P.recommend_prompts("security audit")
        b = P.recommend_prompts("security audit")
        self.assertEqual([r.prompt_id for r in a], [r.prompt_id for r in b])
        self.assertEqual([r.score for r in a], [r.score for r in b])

    def test_scores_bounded_and_sorted(self):
        recs = P.recommend_prompts("implement feature")
        scores = [r.score for r in recs]
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_reason_is_informative(self):
        recs = P.recommend_prompts("security audit")
        self.assertTrue(recs[0].reason.strip())
        self.assertIn("security", recs[0].reason.lower() or "security")

    def test_explicit_role_overrides_inferred(self):
        # "write code" infers software_engineer, but an explicit security role
        # must steer recommendations toward security profiles.
        recs = P.recommend_prompts("write code", role="security_engineer")
        self.assertTrue(recs)
        self.assertEqual(P.get_prompt(recs[0].prompt_id).role, "security_engineer")

    def test_unknown_task_returns_empty(self):
        self.assertEqual(P.recommend_prompts("zzz zzz"), [])

    def test_ranked_roles_are_consistent(self):
        # every recommendation must reference a profile in the same (primary) role
        # when a strong category signal is present
        recs = P.recommend_prompts("CI/CD")
        self.assertEqual(P.get_prompt(recs[0].prompt_id).role, "devops_engineer")

    def test_complexity_boosts_expert_profile(self):
        # high-complexity development work favors the expert/production profiles
        recs = P.recommend_prompts("implement a complex feature")
        top_ids = [r.prompt_id for r in recs[:2]]
        self.assertTrue(any("expert" in i or "production" in i for i in top_ids))


class TestScoring(unittest.TestCase):
    def test_capability_category_role_keyword_weights(self):
        # "security audit" is a near-perfect match for security-auditor: it has
        # the keyword boost + role + category + capability overlap.
        recs = P.recommend_prompts("security audit")
        top = recs[0]
        self.assertEqual(top.prompt_id, "security-auditor")
        self.assertGreater(top.score, 0.8)

    def test_no_ml_confidence_claim(self):
        # scores are deterministic matching scores — never framed as confidence
        recs = P.recommend_prompts("security audit")
        for r in recs:
            self.assertIsInstance(r.score, float)
            self.assertNotIn("confidence", r.reason.lower())


if __name__ == "__main__":
    unittest.main()
