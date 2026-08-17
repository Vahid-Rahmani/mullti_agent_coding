"""Model registry — deterministic lookup over the built-in catalog.

The registry answers three questions and nothing more: *what models exist*,
*what can they do*, and *which models match this capability filter*. It never
executes a model, never imports a provider SDK, and never touches credentials.
"""

from __future__ import annotations

from scripts.core.model_registry.builtin import BUILTIN_MODELS
from scripts.core.model_registry.schema import ModelSpec, validate_spec
from scripts.core.prompt_library.model_capabilities import (
    LEVELS,
    ModelCapabilityProfile,
)

_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


class ModelError(Exception):
    """Raised for unknown model ids or invalid registry usage."""


# Validate the built-ins once at import time (duplicate ids / bad shape fail
# loudly instead of silently poisoning lookups).
_MODELS: dict[str, ModelSpec] = {}
for _spec in BUILTIN_MODELS:
    validate_spec(_spec)
    if _spec.id in _MODELS:
        raise ModelError(f"duplicate model id in catalog: {_spec.id!r}")
    _MODELS[_spec.id] = _spec


def get_model(model_id: str) -> ModelSpec:
    """Look up a model by id; raise :class:`ModelError` when unknown."""
    spec = _MODELS.get(model_id or "")
    if spec is None:
        raise ModelError(f"unknown model {model_id!r}")
    return spec


def list_models() -> list[ModelSpec]:
    """All catalog models in deterministic (catalog) order."""
    return list(BUILTIN_MODELS)


def list_models_by_provider(provider: str) -> list[ModelSpec]:
    """Models belonging to one provider (metadata filter, no SDK involved)."""
    return [m for m in BUILTIN_MODELS if m.provider == (provider or "")]


def list_models_by_capability(**requirements: object) -> list[ModelSpec]:
    """Models meeting qualitative capability levels and/or a context minimum.

    Supported keyword requirements (all optional):
      ``reasoning`` / ``coding`` / ``tool_use`` / ``vision`` /
      ``structured_output`` — a qualitative level ("low"|"medium"|"high"); a
      model matches when its level is >= the required level.
      ``context_window`` — an int minimum; a model matches when its window is
      >= the minimum.
    """
    results: list[ModelSpec] = []
    for model in BUILTIN_MODELS:
        cap = model.capabilities
        if _capability_match(cap, requirements):
            results.append(model)
    return results


def _capability_match(cap: ModelCapabilityProfile,
                      requirements: dict) -> bool:
    for key, value in requirements.items():
        if key == "context_window":
            try:
                minimum = int(value)
            except (TypeError, ValueError):
                continue
            if cap.context_window < minimum:
                return False
            continue
        if key in ("reasoning", "coding", "tool_use", "vision",
                   "structured_output"):
            req = str(value or "")
            if req not in LEVELS:
                continue
            got = _LEVEL_ORDER.get(getattr(cap, key, "medium"), 1)
            if got < _LEVEL_ORDER[req]:
                return False
            continue
        if key == "latency":
            req = str(value or "")
            if req in LEVELS and _LEVEL_ORDER.get(cap.latency, 1) > _LEVEL_ORDER[req]:
                return False  # latency: lower is better
            continue
        if key == "cost":
            req = str(value or "")
            if req in LEVELS and _LEVEL_ORDER.get(cap.cost, 1) > _LEVEL_ORDER[req]:
                return False  # cost: lower is better
            continue
    return True


def model_providers() -> list[str]:
    """Distinct provider names present in the catalog (sorted, deterministic)."""
    return sorted({m.provider for m in BUILTIN_MODELS if m.provider})


__all__ = [
    "ModelError",
    "get_model",
    "list_models",
    "list_models_by_capability",
    "list_models_by_provider",
    "model_providers",
]
