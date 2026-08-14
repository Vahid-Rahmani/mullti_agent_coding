"""Deterministic recommendation engines — transparent, keyword-based scoring.

Prompt recommendation (``recommend_prompts``) ranks Prompt Profiles against a
task; model recommendation (``recommend_model_capabilities``) returns the
model *requirements* a profile implies, or ranks supplied model capability
profiles against them. No LLM, no embeddings, no provider calls — the scores are
deterministic matching scores (not ML confidence), by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import task as task_module
from .model_capabilities import (
    ModelCapabilityProfile,
    preferences_for_profile,
)
from .registry import PromptError, get_prompt, list_prompts
from .schema import ModelPreferences, PromptProfile


@dataclass(frozen=True)
class PromptRecommendation:
    """One ranked prompt profile. ``score`` is a deterministic matching score."""

    prompt_id: str
    score: float
    reason: str

    def to_dict(self) -> dict:
        return {"prompt_id": self.prompt_id, "score": self.score,
                "reason": self.reason}


@dataclass(frozen=True)
class ModelRecommendation:
    """One ranked model capability profile (provider-neutral)."""

    model_id: str
    score: float
    reason: str

    def to_dict(self) -> dict:
        return {"model_id": self.model_id, "score": self.score,
                "reason": self.reason}


# ---------------------------------------------------------------- prompt ranking


# Scoring weights (documented; not tuned ML). ``score`` is normalized to [0, 1]
# against the theoretical maximum for the given inputs, so a perfect match is 1.0
# and a profile with no overlap is 0.0 (and is dropped).
_KEYWORD_WEIGHT = 40
_ROLE_WEIGHT = 30
_SECONDARY_ROLE_WEIGHT = 15
_CATEGORY_WEIGHT = 20
_CAPABILITY_WEIGHT = 10
_TAG_WEIGHT = 5
_COMPLEXITY_WEIGHT = 8
_RISK_WEIGHT = 8

# Tags that signal a profile is a good fit for high-complexity / high-risk work.
_HIGH_COMPLEXITY_TAGS = (
    "senior", "expert", "production", "distributed", "adversarial",
    "incident", "strategy", "performance", "reliability", "scalability",
    "architecture", "security", "threat-modeling",
)
_HIGH_RISK_TAGS = (
    "security", "risk", "reliability", "incident", "audit", "threat",
    "vulnerabilities", "production",
)


def recommend_prompts(task: str | task_module.TaskProfile | None = None,
                      role: str | None = None,
                      capabilities: list[str] | tuple[str, ...] | None = None,
                      complexity: str | None = None,
                      risk: str | None = None,
                      limit: int = 5) -> list[PromptRecommendation]:
    """Rank prompt profiles for a task (deterministic).

    ``task`` may be free text (classified on the fly) or a pre-built
    ``TaskProfile``. An explicit ``role`` overrides inferred roles and is the
    strongest signal (the user's explicit choice always wins). ``capabilities``,
    ``complexity`` and ``risk`` override the classification when given.
    """
    text = ""
    profile: task_module.TaskProfile | None = None
    if isinstance(task, task_module.TaskProfile):
        profile = task
        text = task_module.normalize(task.context)
    elif isinstance(task, str):
        profile = task_module.classify_task(task)
        text = task_module.normalize(task)

    category = profile.category if profile else "general"
    caps = [str(c) for c in (capabilities or ())] if capabilities is not None \
        else list(profile.capabilities if profile else ())
    complexity = (complexity or (profile.complexity if profile else "medium")).lower()
    risk = (risk or (profile.risk if profile else "medium")).lower()

    # role weights: explicit role is authoritative (30); otherwise the inferred
    # primary role leads (30) and secondary roles trail (15).
    role_weights: dict[str, int] = {}
    if role:
        role_weights[task_module.normalize(role).replace(" ", "_")] = _ROLE_WEIGHT
    else:
        roles = task_module.suggest_roles_for_task(task) if task is not None else []
        if roles:
            role_weights[roles[0]] = _ROLE_WEIGHT
            for r in roles[1:]:
                role_weights.setdefault(r, _SECONDARY_ROLE_WEIGHT)

    # category → prompt category. An explicit role is authoritative: derive the
    # prompt category from the role (not the task text), so e.g. a user-chosen
    # security role is never outranked by a task phrase like "write code".
    if role:
        prompt_category = _ROLE_CATEGORY.get(
            task_module.normalize(role).replace(" ", "_"))
    else:
        prompt_category = _CATEGORY_MAP.get(category)

    # keyword → prompt boosts (built-in Phase 2 mappings). Suppressed when the
    # user supplies an explicit role — the explicit choice is authoritative and
    # must not be overridden by a task-phrase heuristic.
    keyword_boosts: dict[str, list[str]] = {}
    keyword_weight = 0 if role else _KEYWORD_WEIGHT
    if not role:
        for keyword, prompt_id in task_module.task_keyword_prompt_ids(text):
            keyword_boosts.setdefault(prompt_id, []).append(keyword)

    denom = (keyword_weight + _ROLE_WEIGHT + _CATEGORY_WEIGHT
             + _CAPABILITY_WEIGHT * len(caps)
             + (_COMPLEXITY_WEIGHT if complexity == "high" else 0)
             + (_RISK_WEIGHT if risk == "high" else 0))

    results: list[PromptRecommendation] = []
    for p in list_prompts():
        raw = 0
        reasons: list[str] = []

        for keyword in keyword_boosts.get(p.id, [])[:1]:
            raw += _KEYWORD_WEIGHT
            reasons.append(f"task keyword '{keyword}'")

        w = role_weights.get(p.role)
        if w:
            raw += w
            reasons.append(f"role {p.role}")

        if prompt_category and p.category == prompt_category:
            raw += _CATEGORY_WEIGHT
            reasons.append("category match")

        for cap in caps:
            if cap in p.capabilities:
                raw += _CAPABILITY_WEIGHT
                reasons.append(f"capability {cap}")
            elif cap in p.tags:
                raw += _TAG_WEIGHT
                reasons.append(f"tag {cap}")

        if complexity == "high" and any(t in p.tags for t in _HIGH_COMPLEXITY_TAGS):
            raw += _COMPLEXITY_WEIGHT
            reasons.append("high-complexity fit")
        if risk == "high" and any(t in p.tags for t in _HIGH_RISK_TAGS):
            raw += _RISK_WEIGHT
            reasons.append("high-risk fit")

        if raw <= 0 or denom <= 0:
            continue
        score = round(min(1.0, raw / denom), 4)
        results.append(PromptRecommendation(
            prompt_id=p.id, score=score, reason=_compose_reason(reasons)))

    results.sort(key=lambda r: (-r.score, r.prompt_id))
    return results[: max(0, limit)]


_CATEGORY_MAP = {
    "development": "development",
    "architecture": "architecture",
    "debugging": "debugging",
    "review": "review",
    "testing": "testing",
    "security": "security",
    "devops": "devops",
    "cloud": "cloud",
    "data": "data",
    "ai": "ai",
    "research": "research",
    "documentation": "documentation",
    "planning": "management",
    "orchestration": "orchestration",
    "general": None,
}

# prompt role → prompt category (used to honour an explicit role).
_ROLE_CATEGORY = {
    "software_engineer": "development",
    "software_architect": "architecture",
    "code_reviewer": "review",
    "debugger": "debugging",
    "qa_engineer": "testing",
    "security_engineer": "security",
    "devops_engineer": "devops",
    "cloud_engineer": "cloud",
    "data_engineer": "data",
    "ai_engineer": "ai",
    "researcher": "research",
    "technical_writer": "documentation",
    "project_manager": "management",
    "orchestrator": "orchestration",
}


def _compose_reason(reasons: list[str]) -> str:
    if not reasons:
        return "no matching signals"
    return "Matches " + "; ".join(reasons) + "."


# ---------------------------------------------------------------- model ranking


_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
_CONTEXT_ORDER = {"small": 0, "medium": 1, "large": 2}
# Scoring weights (sum to 100).
_WEIGHTS = {
    "reasoning": 25,
    "coding": 20,
    "context": 20,
    "tool_use": 15,
    "latency": 10,
    "cost": 10,
}


def recommend_model_capabilities(
        task: str | task_module.TaskProfile | None = None,
        prompt_profile: PromptProfile | str | None = None,
        available_models: list[ModelCapabilityProfile | dict] | None = None,
) -> ModelPreferences | list[ModelRecommendation]:
    """Return model requirements, or rank models against them.

    * Without ``available_models`` → returns the :class:`ModelPreferences`
      (requirements) implied by the prompt profile (role defaults when the
      profile has no explicit preferences).
    * With ``available_models`` → returns ranked
      ``[{model_id, score, reason}]`` against those requirements.

    ``task`` may nudge requirements (high-complexity work prefers stronger
    reasoning) but never changes the user's explicit model selection — that is
    an authoritative runtime concern, outside this recommendation layer.
    """
    if isinstance(prompt_profile, str):
        try:
            prompt_profile = get_prompt(prompt_profile)
        except PromptError:
            prompt_profile = None

    if prompt_profile is None:
        prefs = ModelPreferences()
    else:
        prefs = preferences_for_profile(prompt_profile)

    prefs = _adjust_prefs_for_task(prefs, task)

    if available_models is None:
        return prefs

    results: list[ModelRecommendation] = []
    for model in available_models:
        cap = (model if isinstance(model, ModelCapabilityProfile)
               else ModelCapabilityProfile.from_dict(model))
        if not cap.id:
            continue
        score, reason = _score_model(cap, prefs)
        results.append(ModelRecommendation(model_id=cap.id, score=score,
                                           reason=reason))
    results.sort(key=lambda r: (-r.score, r.model_id))
    return results


def _adjust_prefs_for_task(prefs: ModelPreferences,
                           task: str | task_module.TaskProfile | None) -> ModelPreferences:
    if isinstance(task, str):
        task = task_module.classify_task(task)
    if isinstance(task, task_module.TaskProfile) and task.complexity == "high" \
            and prefs.reasoning != "high":
        return ModelPreferences(
            reasoning="high", coding=prefs.coding, context=prefs.context,
            tool_use=prefs.tool_use, latency=prefs.latency, cost=prefs.cost)
    return prefs


def _level_match(req: str, cap: str, lower_better: bool = False) -> float:
    """1.0 when a model meets a requirement, 0.5 one level off, else 0.

    For reasoning/coding/tool_use a higher level is better (``cap >= req``); for
    cost and latency a *lower* level is better (cheaper/faster than required).
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


def _score_model(cap: ModelCapabilityProfile,
                 prefs: ModelPreferences) -> tuple[float, str]:
    components = {
        "reasoning": _level_match(prefs.reasoning, cap.reasoning),
        "coding": _level_match(prefs.coding, cap.coding),
        "context": _context_match(prefs.context, cap.context_window),
        "tool_use": _level_match(prefs.tool_use, cap.tool_use),
        "latency": _level_match(prefs.latency, cap.latency, lower_better=True),
        "cost": _level_match(prefs.cost, cap.cost, lower_better=True),
    }
    total = sum(_WEIGHTS[k] * v for k, v in components.items())
    score = round(total / 100.0, 4)
    matched = [k for k, v in components.items() if v == 1.0]
    if not matched:
        reason = "no strong capability match"
    else:
        reason = "meets " + ", ".join(matched)
    return score, reason


__all__ = [
    "PromptRecommendation",
    "ModelRecommendation",
    "recommend_prompts",
    "recommend_model_capabilities",
]
