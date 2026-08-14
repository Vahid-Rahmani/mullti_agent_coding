"""ModelSpec schema tests (Phase 3 model registry)."""

import unittest

from scripts.core.model_registry.schema import (
    PROVIDERS,
    STATUSES,
    ModelSpec,
    validate_spec,
)
from scripts.core.prompt_library.model_capabilities import (
    ModelCapabilityProfile,
)


class ModelSpecSchemaTestCase(unittest.TestCase):
    def test_from_dict_flat_capabilities(self):
        spec = ModelSpec.from_dict({
            "id": "openai/gpt-5",
            "display_name": "GPT-5",
            "provider": "openai",
            "family": "gpt",
            "reasoning": "high",
            "coding": "high",
            "context_window": 200000,
            "tool_use": "high",
            "vision": "medium",
            "latency": "medium",
            "cost": "high",
            "structured_output": "high",
        })
        self.assertEqual(spec.id, "openai/gpt-5")
        self.assertEqual(spec.provider, "openai")
        self.assertEqual(spec.capabilities.reasoning, "high")
        self.assertEqual(spec.capabilities.context_window, 200000)

    def test_from_dict_nested_capabilities(self):
        spec = ModelSpec.from_dict({
            "id": "x/y",
            "capabilities": {"reasoning": "low", "context_window": 32000},
        })
        self.assertEqual(spec.capabilities.reasoning, "low")
        self.assertEqual(spec.capabilities.context_window, 32000)

    def test_to_dict_roundtrip(self):
        spec = ModelSpec(
            id="google/gemini-3.6-flash", display_name="Gemini 3.6 Flash",
            provider="google", family="gemini",
            capabilities=ModelCapabilityProfile(
                reasoning="high", coding="high", context_window=128000,
                tool_use="high", vision="high", latency="medium", cost="low",
                structured_output="high"),
            modalities=("text", "image"))
        d = spec.to_dict()
        self.assertEqual(d["id"], spec.id)
        self.assertEqual(d["provider"], "google")
        self.assertEqual(d["context_window"], 128000)
        self.assertEqual(d["capabilities"]["reasoning"], "high")
        self.assertEqual(d["modalities"], ["text", "image"])
        self.assertEqual(d["status"], "available")
        # round-trips through from_dict
        again = ModelSpec.from_dict(d)
        self.assertEqual(again, spec)

    def test_validate_spec_accepts_valid(self):
        spec = ModelSpec(id="local/llama-3-70b", provider="local")
        validate_spec(spec)  # no raise

    def test_validate_spec_rejects_bad_id(self):
        with self.assertRaises(ValueError):
            validate_spec(ModelSpec(id="no-slash"))

    def test_validate_spec_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            validate_spec(ModelSpec(id="a/b", provider="mystery-corp"))

    def test_validate_spec_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            validate_spec(ModelSpec(id="a/b", status="banana"))

    def test_providers_and_statuses_constants(self):
        for expected in ("openai", "anthropic", "google", "azure_openai",
                         "local"):
            self.assertIn(expected, PROVIDERS)
        for expected in ("available", "preview", "deprecated"):
            self.assertIn(expected, STATUSES)

    def test_capability_profile_id_optional(self):
        # Phase 3 embeds capability profiles inside ModelSpec; the archetype
        # id must be optional so embedded profiles need no id.
        cap = ModelCapabilityProfile(reasoning="high", coding="high")
        self.assertEqual(cap.id, "")
        self.assertEqual(cap.reasoning, "high")


if __name__ == "__main__":
    unittest.main()
