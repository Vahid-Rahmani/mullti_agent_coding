"""Model selection engine — the Phase 3 boundary.

The pipeline is::

    Prompt Library (what the agent needs)
        → Model Registry (what each model can do)
        → select_models (which available model best matches)

``select_models`` is fully deterministic — no LLM, no embeddings, no provider
calls. Scores are transparent matching scores (not ML confidence), built from
documented weights over qualitative capability levels.

Rules that are architecturally important:

* **Explicit user model always wins.** An ``explicit_model`` is never dropped,
  never outranked, and never silently replaced — it is returned first and
  flagged ``explicit``.
* **Hard vs preferred requirements.** ``hard_requirements`` (e.g. a minimum
  ``context_window`` or a required ``reasoning`` level) exclude models that
  cannot do the job; soft preferences (``requirements``) only affect ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.core.model_registry.registry import (
    ModelError,
    get_model,
    list_models,
)
from scripts.core.model_registry.schema import ModelSpec
from scripts.core.prompt_library.model_capabilities import (
    ModelCapabilityProfile,
)
from scripts.core.prompt_library.schema import ModelPreferences

_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
_CONTEXT_ORDER = {"small": 0, "medium": 1, "large": 2}

# Deterministic scoring weights (documented; sum to 100):
#   capability match 40%  (reasoning 16 + coding 16 + vision 8)
#   context window   20%
#   tool use         10%
#   structured out   10%
#   latency          10%  (lower is better)
#   cost             10%  (lower is better)
_CAPABILITY_WEIGHTS = {"reasoning": 16, "coding": 16, "vision": 8}
_CONTEXT_WEIGHT = 20
_TOOL_USE_WEIGHT = 10
_STRUCTURED_OUTPUT_WEIGHT = 10
_LATENCY_WEIGHT = 10
_COST_WEIGHT = 10

# Preference keys supported by ModelPreferences (levels).
_LEVEL_KEYS = ("reasoning", "coding", "tool_use", "vision",
               "structured_output", "latency", "cost")


@dataclass(frozen=True)
class ModelSelection:
    """One ranked model candidate. ``explicit`` marks the user's own choice."""

    model_id: str
    score: float
    reason: str
    explicit: bool = False

    def to_dict(self) -> dict:
        return {"model_id": self.model_id, "score": self.score,
                "reason": self.reason, "explicit": self.explicit}


def select_models(
    requirements: ModelPreferences | dict | None = None,
    available_models: list[str | ModelSpec | dict] | None = None,
    provider: str | None = None,
    explicit_model: str | None = None,
    hard_requirements: dict | None = None,
) -> list[ModelSelection]:
    """Rank the best available model for a set of requirements.

    Parameters
    ----------
    requirements
        Soft preferences: a :class:`ModelPreferences` or a dict of levels
        (``reasoning``/``coding``/``context``/``tool_use``/``latency``/``cost``
        plus optional ``vision``/``structured_output``). Affects ranking only.
    available_models
        ``None`` → the whole registry catalog; otherwise a list of model ids,
        :class:`ModelSpec` objects, or dicts. Unknown ids are skipped (the
        explicit model is the only exception).
    provider
        Optional provider filter over the candidate set (metadata only).
    explicit_model
        The user's explicit choice — always returned first, flagged
        ``explicit``, never dropped even when it fails hard requirements or a
        provider filter.
    hard_requirements
        Optional ``{key: value}`` where ``context_window`` is an int minimum
        and capability keys are required levels. Models failing a hard
        requirement are excluded from ranking.

    Returns ranked :class:`ModelSelection` (highest score first; ties broken by
    model id). Deterministic for identical inputs.
    """
    prefs = _pref_levels(requirements)
    hard = dict(hard_requirements or {})

    specs = _resolve_available(available_models)
    if provider:
        specs = [s for s in specs if s.provider == (provider or "")]

    results: list[ModelSelection] = []
    for spec in specs:
        failed = _hard_fail(spec.capabilities, hard)
        if failed:
            continue
        score, reason = _score_spec(spec, prefs)
        results.append(ModelSelection(model_id=spec.id, score=score,
                                      reason=reason))

    results.sort(key=lambda r: (-r.score, r.model_id))

    if explicit_model:
        results = _place_explicit(results, explicit_model, prefs, hard)

    return results


# ---------------------------------------------------------------- helpers


def _pref_levels(requirements: ModelPreferences | dict | None) -> dict:
    if isinstance(requirements, ModelPreferences):
        base = {
            "reasoning": requirements.reasoning,
            "coding": requirements.coding,
            "context": requirements.context,
            "tool_use": requirements.tool_use,
            "latency": requirements.latency,
            "cost": requirements.cost,
        }
        extra: dict = {}
        return {**base, **extra}
    if isinstance(requirements, dict):
        return {str(k): str(v) for k, v in requirements.items()}
    return {}


def _resolve_available(
        available_models: list[str | ModelSpec | dict] | None) -> list[ModelSpec]:
    if available_models is None:
        return list_models()
    specs: list[ModelSpec] = []
    for entry in available_models:
        if isinstance(entry, ModelSpec):
            specs.append(entry)
        elif isinstance(entry, dict):
            spec = ModelSpec.from_dict(entry)
            if spec.id:
                specs.append(spec)
        elif isinstance(entry, str):
            try:
                specs.append(get_model(entry))
            except ModelError:
                continue
    return specs


def _hard_fail(cap: ModelCapabilityProfile, hard: dict) -> str | None:
    if not hard:
        return None
    minimum = hard.get("context_window")
    if minimum is not None:
        try:
            if cap.context_window < int(minimum):
                return (f"context window {cap.context_window} < required "
                        f"{int(minimum)}")
        except (TypeError, ValueError):
            pass
    for key in _LEVEL_KEYS:
        req = hard.get(key)
        if not req or req not in _LEVEL_ORDER:
            continue
        got = _LEVEL_ORDER.get(getattr(cap, key, "medium"), 1)
        required = _LEVEL_ORDER[req]
        if key in ("latency", "cost"):
            # lower is better: a model is only acceptable if no slower/costlier
            if got > required:
                return f"{key} {getattr(cap, key)} exceeds required {req}"
        elif got < required:
            return f"{key} {getattr(cap, key)} < required {req}"
    return None


def _score_spec(spec: ModelSpec, prefs: dict) -> tuple[float, str]:
    cap = spec.capabilities
    total = 0.0
    matched: list[str] = []
    for key, weight in _CAPABILITY_WEIGHTS.items():
        match = _level_match(prefs.get(key, "medium"),
                             getattr(cap, key, "medium"))
        total += weight * match
        if match >= 1.0:
            matched.append(key)
    ctx_match = _context_match(prefs.get("context", "medium"),
                               cap.context_window)
    total += _CONTEXT_WEIGHT * ctx_match
    if ctx_match >= 1.0:
        matched.append("context")
    tu_match = _level_match(prefs.get("tool_use", "medium"), cap.tool_use)
    total += _TOOL_USE_WEIGHT * tu_match
    if tu_match >= 1.0:
        matched.append("tool_use")
    so_match = _level_match(prefs.get("structured_output", "medium"),
                            cap.structured_output)
    total += _STRUCTURED_OUTPUT_WEIGHT * so_match
    if so_match >= 1.0:
        matched.append("structured_output")
    lat_match = _level_match(prefs.get("latency", "medium"), cap.latency,
                             lower_better=True)
    total += _LATENCY_WEIGHT * lat_match
    if lat_match >= 1.0:
        matched.append("latency")
    cost_match = _level_match(prefs.get("cost", "medium"), cap.cost,
                              lower_better=True)
    total += _COST_WEIGHT * cost_match
    if cost_match >= 1.0:
        matched.append("cost")

    score = round(total / 100.0, 4)
    if not matched:
        reason = "no strong capability match"
    else:
        reason = "meets " + ", ".join(matched)
    return score, reason


def _place_explicit(results: list[ModelSelection], explicit_model: str,
                    prefs: dict, hard: dict) -> list[ModelSelection]:
    """Ensure the user's explicit model is first, flagged, never dropped."""
    found = False
    out: list[ModelSelection] = []
    for r in results:
        if r.model_id == explicit_model:
            found = True
            out.append(ModelSelection(model_id=r.model_id, score=r.score,
                                      reason=r.reason, explicit=True))
        else:
            out.append(r)
    if not found:
        # explicit model not in the candidate set (e.g. provider-filtered or a
        # custom id) — still authoritative: score it directly if known, else
        # surface it as-is with a clear note.
        try:
            spec = get_model(explicit_model)
            score, reason = _score_spec(spec, prefs)
        except ModelError:
            score = 0.0
            reason = "explicit user selection (not in catalog)"
        out.append(ModelSelection(model_id=explicit_model, score=score,
                                  reason=reason, explicit=True))
    out.sort(key=lambda r: (0 if r.explicit else 1, -r.score, r.model_id))
    return out


def _level_match(req: str, cap: str, lower_better: bool = False) -> float:
    """1.0 when a model meets a requirement, 0.5 one level off, else 0.

    For reasoning/coding/tool_use/vision/structured_output a higher level is
    better (``cap >= req``); for cost and latency a *lower* level is better
    (cheaper/faster than required).
    """
    r = _LEVEL_ORDER.get(req, 1)
    c = _LEVEL_ORDER.get(cap, 1)
    diff = (r - c) if lower_better else (c - r)
    if diff >= 0:
        return 1.0
    if diff == -1:
        return 0.5
    return 0.0


def _context_level(window: int) -> str:
    if window >= 200000:
        return "large"
    if window >= 128000:
        return "medium"
    return "small"


def _context_match(req: str, window: int) -> float:
    r = _CONTEXT_ORDER.get(req, 1)
    c = _CONTEXT_ORDER.get(_context_level(window), 1)
    diff = c - r
    if diff >= 0:
        return 1.0
    if diff == -1:
        return 0.5
    return 0.0


__all__ = ["ModelSelection", "select_models"]
