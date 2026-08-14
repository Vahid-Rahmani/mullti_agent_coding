"""Phase 2 Model Capability tests — provider-neutral capabilities + ranking.

No provider calls, no API keys, no model switching. These verify that model
requirements are derived deterministically from a prompt profile (or its role),
that capability profiles round-trip, and that ranking is stable and bounded.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import prompt_library as P  # noqa: E402


class TestModelPreferences(unittest.TestCase):
    def test_preferences_roundtrip(self):
        prefs = P.ModelPreferences(reasoning="high", coding="high",
                                   context="large", tool_use="high")
        d = prefs.to_dict()
        self.assertEqual(d["reasoning"], "high")
        self.assertEqual(P.ModelPreferences.from_dict(d).context, "large")

    def test_role_defaults_are_deterministic(self):
        a = P.role_model_preferences("security_engineer")
        b = P.role_model_preferences("security_engineer")
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(a.reasoning, "high")

    def test_unknown_role_gets_defaults(self):
        prefs = P.role_model_preferences("nope")
        self.assertEqual(prefs.reasoning, "medium")

    def test_profile_preferences_fall_back_to_role(self):
        # built-in profiles have no explicit model_preferences → role defaults
        prof = P.get_prompt("security-auditor")
        prefs = P.preferences_for_profile(prof)
        self.assertEqual(prefs.reasoning, "high")
        self.assertEqual(prefs.coding, "medium")

    def test_profile_explicit_preferences_win(self):
        prof = P.get_prompt("security-auditor")
        override = P.ModelPreferences(reasoning="low", coding="low")
        explicit = P.PromptProfile(
            id=prof.id, name=prof.name, role=prof.role, category=prof.category,
            prompt=prof.prompt, capabilities=prof.capabilities,
            model_preferences=override)
        self.assertEqual(P.preferences_for_profile(explicit).reasoning, "low")


class TestModelCapabilityProfile(unittest.TestCase):
    def test_roundtrip(self):
        cap = P.ModelCapabilityProfile(id="x", name="X", reasoning="high",
                                       context_window=200000)
        d = cap.to_dict()
        rebuilt = P.ModelCapabilityProfile.from_dict(d)
        self.assertEqual(rebuilt.id, "x")
        self.assertEqual(rebuilt.context_window, 200000)
        self.assertEqual(rebuilt.reasoning, "high")

    def test_archetypes_are_provider_neutral(self):
        models = P.model_archetypes()
        self.assertTrue(models)
        for m in models:
            # no provider identity in the capability profile
            self.assertTrue(m.id)
            self.assertNotIn("/", m.id)  # not a "provider/model" id
            self.assertIsInstance(m.context_window, int)


class TestModelRecommendation(unittest.TestCase):
    def test_requirements_returned_without_models(self):
        result = P.recommend_model_capabilities(
            prompt_profile=P.get_prompt("software-engineer-expert"))
        self.assertIsInstance(result, P.ModelPreferences)
        self.assertEqual(result.reasoning, "high")
        self.assertEqual(result.coding, "high")

    def test_ranking_is_deterministic_and_bounded(self):
        prof = P.get_prompt("software-engineer-expert")
        a = P.recommend_model_capabilities(prompt_profile=prof,
                                           available_models=P.model_archetypes())
        b = P.recommend_model_capabilities(prompt_profile=prof,
                                           available_models=P.model_archetypes())
        self.assertEqual([r.model_id for r in a], [r.model_id for r in b])
        scores = [r.score for r in a]
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_strong_reasoning_archetype_wins_for_engineer(self):
        # software engineer wants high reasoning + coding + tool_use + large context
        recs = P.recommend_model_capabilities(
            prompt_profile=P.get_prompt("software-engineer-expert"),
            available_models=P.model_archetypes())
        self.assertEqual(recs[0].model_id, "strong-reasoning")

    def test_cost_direction_prefers_cheaper(self):
        # two otherwise-identical models differ only in cost: the cheaper one
        # must win for a cost-sensitive (low-cost) requirement.
        writer = P.get_prompt("writer-documentation")
        base = {"reasoning": "medium", "coding": "low", "context_window": 128000,
                "tool_use": "low", "latency": "medium"}
        expensive = dict(base, id="expensive", cost="high")
        cheap = dict(base, id="cheap", cost="low")
        recs = P.recommend_model_capabilities(
            prompt_profile=writer, available_models=[expensive, cheap])
        self.assertEqual(recs[0].model_id, "cheap")

    def test_high_complexity_task_bumps_reasoning(self):
        prefs = P.recommend_model_capabilities(
            task="design a complex distributed system",
            prompt_profile=P.get_prompt("qa-test-engineer"))
        self.assertEqual(prefs.reasoning, "high")  # qa default is medium

    def test_accepts_dict_models(self):
        dict_models = [{"id": "m", "name": "M", "reasoning": "high",
                        "coding": "high", "context_window": 200000,
                        "tool_use": "high", "latency": "medium", "cost": "medium"}]
        recs = P.recommend_model_capabilities(
            prompt_profile=P.get_prompt("software-engineer-expert"),
            available_models=dict_models)
        self.assertEqual(recs[0].model_id, "m")


if __name__ == "__main__":
    unittest.main()
