"""Provider-neutral model capabilities — capabilities, not provider identities.

``ModelCapabilityProfile`` describes *what a model can do* (reasoning, coding,
context window, tool use, vision, latency, cost, structured output) with no
reference to a provider. ``ModelPreferences`` (in ``schema.py``) describes what
a prompt profile *requires*. The recommendation engine scores capabilities
against requirements deterministically — this module never calls an API and
never binds a role to a concrete model id.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import ModelPreferences, PromptProfile

# Qualitative capability levels.
LEVELS: tuple[str, ...] = ("low", "medium", "high")
# Context size buckets (preferences use these; capabilities use an int window).
CONTEXT_LEVELS: tuple[str, ...] = ("small", "medium", "large")


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """One provider-neutral model capability profile."""

    id: str = ""
    name: str = ""
    reasoning: str = "medium"           # low | medium | high
    coding: str = "medium"              # low | medium | high
    context_window: int = 128000        # tokens (numeric)
    tool_use: str = "medium"            # low | medium | high
    vision: str = "low"                 # low | medium | high
    latency: str = "medium"             # low | medium | high  (low = fast)
    cost: str = "medium"                # low | medium | high  (low = cheap)
    structured_output: str = "medium"   # low | medium | high

    @classmethod
    def from_dict(cls, data: dict) -> ModelCapabilityProfile:
        return cls(
            id=str(data.get("id") or data.get("model_id") or ""),
            name=str(data.get("name") or data.get("id") or ""),
            reasoning=str(data.get("reasoning") or "medium"),
            coding=str(data.get("coding") or "medium"),
            context_window=int(data.get("context_window") or 128000),
            tool_use=str(data.get("tool_use") or "medium"),
            vision=str(data.get("vision") or "low"),
            latency=str(data.get("latency") or "medium"),
            cost=str(data.get("cost") or "medium"),
            structured_output=str(data.get("structured_output") or "medium"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "reasoning": self.reasoning,
            "coding": self.coding,
            "context_window": self.context_window,
            "tool_use": self.tool_use,
            "vision": self.vision,
            "latency": self.latency,
            "cost": self.cost,
            "structured_output": self.structured_output,
        }


# Built-in *archetype* capability profiles. These are provider-neutral shapes
# (fast/light, balanced, strong-reasoning, …) so Phase 2 can rank and preview
# model requirements without coupling to any real provider — Phase 3 will map
# concrete models onto these archetypes.
BUILTIN_MODEL_ARCHETYPES: tuple[ModelCapabilityProfile, ...] = (
    ModelCapabilityProfile(
        id="fast-light", name="Fast / Light",
        reasoning="low", coding="medium", context_window=32000, tool_use="low",
        vision="low", latency="low", cost="low", structured_output="medium"),
    ModelCapabilityProfile(
        id="balanced", name="Balanced",
        reasoning="medium", coding="medium", context_window=128000, tool_use="medium",
        vision="medium", latency="medium", cost="medium", structured_output="high"),
    ModelCapabilityProfile(
        id="strong-reasoning", name="Strong Reasoning",
        reasoning="high", coding="high", context_window=200000, tool_use="high",
        vision="medium", latency="medium", cost="medium", structured_output="high"),
    ModelCapabilityProfile(
        id="code-specialist", name="Code Specialist",
        reasoning="medium", coding="high", context_window=200000, tool_use="high",
        vision="low", latency="medium", cost="medium", structured_output="high"),
    ModelCapabilityProfile(
        id="large-context", name="Large Context",
        reasoning="high", coding="medium", context_window=1000000, tool_use="medium",
        vision="medium", latency="medium", cost="high", structured_output="medium"),
    ModelCapabilityProfile(
        id="vision-capable", name="Vision Capable",
        reasoning="medium", coding="medium", context_window=128000, tool_use="medium",
        vision="high", latency="medium", cost="medium", structured_output="medium"),
)

# role → default model requirements (used when a profile has no explicit
# ``model_preferences``). Deterministic and provider-neutral.
_ROLE_MODEL_PREFS: dict[str, ModelPreferences] = {
    "software_engineer": ModelPreferences(
        reasoning="high", coding="high", context="large",
        tool_use="high", latency="medium", cost="medium"),
    "software_architect": ModelPreferences(
        reasoning="high", coding="medium", context="large",
        tool_use="medium", latency="medium", cost="medium"),
    "code_reviewer": ModelPreferences(
        reasoning="high", coding="medium", context="medium",
        tool_use="low", latency="medium", cost="low"),
    "debugger": ModelPreferences(
        reasoning="high", coding="medium", context="medium",
        tool_use="medium", latency="medium", cost="medium"),
    "qa_engineer": ModelPreferences(
        reasoning="medium", coding="medium", context="medium",
        tool_use="medium", latency="medium", cost="low"),
    "security_engineer": ModelPreferences(
        reasoning="high", coding="medium", context="large",
        tool_use="medium", latency="medium", cost="medium"),
    "devops_engineer": ModelPreferences(
        reasoning="medium", coding="low", context="medium",
        tool_use="high", latency="medium", cost="low"),
    "cloud_engineer": ModelPreferences(
        reasoning="medium", coding="low", context="medium",
        tool_use="high", latency="medium", cost="medium"),
    "data_engineer": ModelPreferences(
        reasoning="medium", coding="medium", context="large",
        tool_use="medium", latency="medium", cost="medium"),
    "ai_engineer": ModelPreferences(
        reasoning="high", coding="high", context="large",
        tool_use="high", latency="medium", cost="high"),
    "researcher": ModelPreferences(
        reasoning="high", coding="low", context="large",
        tool_use="medium", latency="medium", cost="medium"),
    "technical_writer": ModelPreferences(
        reasoning="medium", coding="low", context="medium",
        tool_use="low", latency="medium", cost="low"),
    "project_manager": ModelPreferences(
        reasoning="medium", coding="low", context="medium",
        tool_use="medium", latency="medium", cost="low"),
    "orchestrator": ModelPreferences(
        reasoning="high", coding="medium", context="large",
        tool_use="high", latency="medium", cost="medium"),
}


def role_model_preferences(role: str) -> ModelPreferences:
    """Default model requirements for a prompt role (deterministic)."""
    return _ROLE_MODEL_PREFS.get(role or "", ModelPreferences())


def preferences_for_profile(profile: PromptProfile) -> ModelPreferences:
    """The model requirements a profile implies.

    Uses the profile's explicit ``model_preferences`` when set, otherwise the
    role-level default — so every profile has deterministic requirements without
    duplicating them across all built-ins.
    """
    if profile.model_preferences is not None:
        return profile.model_preferences
    return role_model_preferences(profile.role)


def model_archetypes() -> list[ModelCapabilityProfile]:
    """The built-in provider-neutral capability archetypes (deterministic order)."""
    return list(BUILTIN_MODEL_ARCHETYPES)


__all__ = [
    "BUILTIN_MODEL_ARCHETYPES",
    "CONTEXT_LEVELS",
    "LEVELS",
    "ModelCapabilityProfile",
    "model_archetypes",
    "preferences_for_profile",
    "role_model_preferences",
]
