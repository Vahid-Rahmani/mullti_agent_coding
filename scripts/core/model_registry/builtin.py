"""Built-in model catalog (Phase 3) — representative, documented metadata.

The catalog intentionally stays small: it lists the models the current
deployment actually runs (ground truth from ``opencode.json``) plus a handful
of clearly-documented representative entries for the other major providers.
Capability levels are qualitative catalog metadata used for deterministic
matching — they are NOT vendor benchmarks and will be refined when the
provider-adapter phase lands. No provider SDK is imported; provider names are
strings only.

Catalog entries with provider ``opencode``/``google``/``local`` mirror the
runtime roster; ``openai``/``anthropic``/``azure_openai`` entries are stable
placeholder ids (documented as such) so provider filtering and ranking work
end-to-end before any provider integration exists.
"""

from __future__ import annotations

from scripts.core.model_registry.schema import ModelSpec
from scripts.core.prompt_library.model_capabilities import (
    ModelCapabilityProfile,
)

BUILTIN_MODELS: tuple[ModelSpec, ...] = (
    # ---- project runtime models (ground truth from opencode.json) ---------
    ModelSpec(
        id="opencode/deepseek-v4-flash-free",
        display_name="DeepSeek V4 Flash (free)",
        provider="opencode", family="deepseek",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=128000,
            tool_use="high", vision="low", latency="medium", cost="low",
            structured_output="high"),
        modalities=("text",), status="available"),
    ModelSpec(
        id="google/gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        provider="google", family="gemini",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=128000,
            tool_use="high", vision="high", latency="medium", cost="low",
            structured_output="high"),
        modalities=("text", "image"), status="available"),
    ModelSpec(
        id="opencode/big-pickle",
        display_name="Big Pickle",
        provider="opencode", family="big-pickle",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=200000,
            tool_use="high", vision="medium", latency="medium", cost="low",
            structured_output="high"),
        modalities=("text",), status="available"),
    ModelSpec(
        id="opencode/ling-3.0-tiny-free",
        display_name="Ling 3.0 Tiny (free)",
        provider="opencode", family="ling",
        capabilities=ModelCapabilityProfile(
            reasoning="low", coding="medium", context_window=32000,
            tool_use="low", vision="low", latency="low", cost="low",
            structured_output="medium"),
        modalities=("text",), status="available"),
    ModelSpec(
        id="google/gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        provider="google", family="gemini",
        capabilities=ModelCapabilityProfile(
            reasoning="low", coding="medium", context_window=32000,
            tool_use="low", vision="medium", latency="low", cost="low",
            structured_output="medium"),
        modalities=("text", "image"), status="available"),
    ModelSpec(
        id="ollama/qwen2.5-coder:7b",
        display_name="Qwen 2.5 Coder 7B (local)",
        provider="local", family="qwen",
        capabilities=ModelCapabilityProfile(
            reasoning="medium", coding="medium", context_window=32000,
            tool_use="low", vision="low", latency="low", cost="low",
            structured_output="medium"),
        modalities=("text",), status="available"),

    # ---- representative catalog entries (documented placeholder metadata) --
    # Stable internal ids; capability levels are qualitative catalog estimates
    # for matching only. Refined when provider integration lands (Phase 4+).
    ModelSpec(
        id="openai/gpt-5",
        display_name="GPT-5 (catalog)",
        provider="openai", family="gpt",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=200000,
            tool_use="high", vision="high", latency="medium", cost="high",
            structured_output="high"),
        modalities=("text", "image"), status="available"),
    ModelSpec(
        id="anthropic/claude-sonnet-4-5",
        display_name="Claude Sonnet 4.5 (catalog)",
        provider="anthropic", family="claude",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=200000,
            tool_use="high", vision="high", latency="medium", cost="high",
            structured_output="high"),
        modalities=("text", "image"), status="available"),
    ModelSpec(
        id="azure-openai/gpt-5",
        display_name="Azure OpenAI GPT-5 (catalog)",
        provider="azure_openai", family="gpt",
        capabilities=ModelCapabilityProfile(
            reasoning="high", coding="high", context_window=200000,
            tool_use="high", vision="high", latency="medium", cost="high",
            structured_output="high"),
        modalities=("text", "image"), status="available"),
    ModelSpec(
        id="local/llama-3-70b",
        display_name="Llama 3 70B (local, catalog)",
        provider="local", family="llama",
        capabilities=ModelCapabilityProfile(
            reasoning="medium", coding="medium", context_window=128000,
            tool_use="medium", vision="low", latency="low", cost="low",
            structured_output="medium"),
        modalities=("text",), status="available"),
)

__all__ = ["BUILTIN_MODELS"]
