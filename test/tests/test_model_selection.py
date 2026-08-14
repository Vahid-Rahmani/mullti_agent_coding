"""Model selection engine tests (Phase 3).

Covers deterministic ranking, hard vs soft requirements, provider filtering,
and the iron rule that an explicit user model is always preserved.
"""

import unittest

from scripts.core.model_registry import ModelSpec, select_models
from scripts.core.model_registry.selection import ModelSelection
from scripts.core.prompt_library import ModelPreferences
from scripts.core.prompt_library.model_capabilities import (
    ModelCapabilityProfile,
)

STRONG = ModelCapabilityProfile(
    reasoning="high", coding="high", context_window=200000, tool_use="high",
    vision="medium", latency="medium", cost="medium", structured_output="high")
FAST = ModelCapabilityProfile(
    reasoning="low", coding="medium", context_window=32000, tool_use="low",
    vision="low", latency="low", cost="low", structured_output="medium")


def spec(mid: str, cap: ModelCapabilityProfile) -> ModelSpec:
    return ModelSpec(id=mid, display_name=mid, provider="test", capabilities=cap)


REQ = ModelPreferences(reasoning="high", coding="high", context="large",
                       tool_use="high")


class ModelSelectionTestCase(unittest.TestCase):
    def test_deterministic_ranking(self):
        a = select_models(requirements=REQ)
        b = select_models(requirements=REQ)
        self.assertEqual([r.to_dict() for r in a],
                         [r.to_dict() for r in b])

    def test_strong_model_ranks_above_fast(self):
        models = [spec("fast", FAST), spec("strong", STRONG)]
        recs = select_models(requirements=REQ, available_models=models)
        self.assertEqual(recs[0].model_id, "strong")
        self.assertGreater(recs[0].score, recs[1].score)

    def test_hard_context_requirement_excludes_small_models(self):
        models = [spec("small", FAST), spec("big", STRONG)]
        recs = select_models(
            requirements=REQ, available_models=models,
            hard_requirements={"context_window": 100000})
        ids = [r.model_id for r in recs]
        self.assertIn("big", ids)
        self.assertNotIn("small", ids)

    def test_hard_capability_requirement_excludes_weak_models(self):
        models = [spec("small", FAST), spec("big", STRONG)]
        recs = select_models(
            requirements=REQ, available_models=models,
            hard_requirements={"reasoning": "high"})
        ids = [r.model_id for r in recs]
        self.assertEqual(ids, ["big"])

    def test_provider_filter(self):
        models = [
            ModelSpec(id="a/one", provider="alpha", capabilities=STRONG),
            ModelSpec(id="b/two", provider="beta", capabilities=STRONG),
        ]
        recs = select_models(requirements=REQ, available_models=models,
                             provider="alpha")
        self.assertEqual([r.model_id for r in recs], ["a/one"])

    def test_explicit_model_preserved_even_when_fails_hard(self):
        models = [spec("small", FAST), spec("big", STRONG)]
        recs = select_models(
            requirements=REQ, available_models=models,
            hard_requirements={"context_window": 100000},
            explicit_model="small")
        # explicit model is first and flagged, never dropped
        self.assertEqual(recs[0].model_id, "small")
        self.assertTrue(recs[0].explicit)
        ids = [r.model_id for r in recs]
        self.assertIn("small", ids)
        self.assertIn("big", ids)

    def test_explicit_model_not_in_catalog_is_surfaced(self):
        recs = select_models(requirements=REQ,
                             explicit_model="custom/whatever")
        self.assertEqual(recs[0].model_id, "custom/whatever")
        self.assertTrue(recs[0].explicit)

    def test_explicit_model_marked_in_full_catalog(self):
        recs = select_models(requirements=REQ,
                             explicit_model="opencode/big-pickle")
        self.assertEqual(recs[0].model_id, "opencode/big-pickle")
        self.assertTrue(recs[0].explicit)

    def test_no_requirements_uses_defaults(self):
        recs = select_models(available_models=[spec("fast", FAST)])
        self.assertEqual(len(recs), 1)
        self.assertTrue(0.0 <= recs[0].score <= 1.0)

    def test_requirements_accepts_dict(self):
        recs = select_models(
            requirements={"reasoning": "high", "coding": "high",
                          "context": "large", "tool_use": "high"},
            available_models=[spec("fast", FAST), spec("strong", STRONG)])
        self.assertEqual(recs[0].model_id, "strong")

    def test_unknown_ids_in_available_are_skipped(self):
        recs = select_models(
            requirements=REQ,
            available_models=["no/such-model", spec("strong", STRONG)])
        self.assertEqual([r.model_id for r in recs], ["strong"])

    def test_available_models_accepts_dicts(self):
        recs = select_models(
            requirements=REQ,
            available_models=[{
                "id": "strong", "reasoning": "high", "coding": "high",
                "context_window": 200000, "tool_use": "high",
                "latency": "medium", "cost": "medium",
            }])
        self.assertEqual(recs[0].model_id, "strong")

    def test_registry_default_when_no_available(self):
        recs = select_models(requirements=REQ)
        self.assertTrue(recs)
        self.assertTrue(all(isinstance(r, ModelSelection) for r in recs))
        # scores sorted descending
        scores = [r.score for r in recs]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_reason_mentions_matched_capabilities(self):
        recs = select_models(
            requirements=REQ, available_models=[spec("strong", STRONG)])
        self.assertIn("reasoning", recs[0].reason)

    def test_latency_and_cost_soft_preferences(self):
        slow_costly = ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=200000,
            tool_use="high", latency="high", cost="high")
        recs = select_models(
            requirements=ModelPreferences(
                reasoning="high", coding="high", context="large",
                tool_use="high", latency="low", cost="low"),
            available_models=[spec("slow", slow_costly),
                              spec("strong", STRONG)])
        self.assertEqual(recs[0].model_id, "strong")


if __name__ == "__main__":
    unittest.main()
