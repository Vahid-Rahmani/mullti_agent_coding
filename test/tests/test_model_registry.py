"""Model Registry tests (Phase 3) — lookup, filtering, determinism."""

import unittest

from scripts.core import model_registry
from scripts.core.model_registry import (
    ModelError,
    get_model,
    list_models,
    list_models_by_capability,
    list_models_by_provider,
    model_providers,
)


class ModelRegistryTestCase(unittest.TestCase):
    def test_registry_loads_with_unique_ids(self):
        models = list_models()
        self.assertTrue(models)
        ids = [m.id for m in models]
        self.assertEqual(len(ids), len(set(ids)), "model ids must be unique")

    def test_get_model_known(self):
        spec = get_model("opencode/deepseek-v4-flash-free")
        self.assertEqual(spec.id, "opencode/deepseek-v4-flash-free")
        self.assertTrue(spec.display_name)
        self.assertTrue(spec.provider)

    def test_get_model_unknown_raises(self):
        with self.assertRaises(ModelError):
            get_model("no/such-model")

    def test_list_models_deterministic(self):
        self.assertEqual([m.id for m in list_models()],
                         [m.id for m in list_models()])

    def test_list_models_by_provider(self):
        google = list_models_by_provider("google")
        self.assertTrue(google)
        self.assertTrue(all(m.provider == "google" for m in google))
        self.assertEqual(list_models_by_provider("does-not-exist"), [])

    def test_list_models_by_capability_reasoning(self):
        strong = list_models_by_capability(reasoning="high")
        self.assertTrue(strong)
        self.assertTrue(all(m.capabilities.reasoning == "high"
                            for m in strong))

    def test_list_models_by_capability_context_min(self):
        big = list_models_by_capability(context_window=100000)
        self.assertTrue(big)
        self.assertTrue(all(m.capabilities.context_window >= 100000
                            for m in big))
        small = list_models_by_capability(context_window=10_000_000)
        self.assertEqual(small, [])

    def test_list_models_by_capability_latency_lower_better(self):
        fast = list_models_by_capability(latency="low")
        self.assertTrue(fast)
        self.assertTrue(all(m.capabilities.latency == "low" for m in fast))

    def test_list_models_by_capability_combined(self):
        combined = list_models_by_capability(reasoning="high",
                                             context_window=100000)
        for m in combined:
            self.assertEqual(m.capabilities.reasoning, "high")
            self.assertGreaterEqual(m.capabilities.context_window, 100000)

    def test_model_providers_sorted(self):
        providers = model_providers()
        self.assertEqual(providers, sorted(providers))
        self.assertIn("google", providers)
        self.assertIn("openai", providers)
        self.assertIn("local", providers)

    def test_provider_neutral_no_sdk_imports(self):
        # The registry must never drag in provider SDKs.
        import sys
        for banned in ("openai", "anthropic", "google.generativeai"):
            self.assertNotIn(banned, sys.modules)


if __name__ == "__main__":
    unittest.main()
