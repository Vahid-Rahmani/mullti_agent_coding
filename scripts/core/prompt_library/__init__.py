"""Prompt Library — reusable, versioned, role-typed prompt profiles.

A Prompt Profile is a *source* behaviour profile (role, category, capabilities,
prompt text). It is distinct from the *final* instruction an agent node runs:
a workflow node keeps its own editable ``instructions`` field and may optionally
reference a profile through its ``prompt_profile`` id. Nothing here couples an
agent to a model or provider (``recommended_models`` stays empty in Phase 1).

Usage::

    from scripts.core import prompt_library
    prompt_library.list_prompts()
    prompt_library.get_prompt("software-engineer-expert")
    prompt_library.suggest_prompts_for_role("developer")
"""

from __future__ import annotations

from .model_capabilities import (
    ModelCapabilityProfile,
    model_archetypes,
    preferences_for_profile,
    role_model_preferences,
)
from .recommend import (
    ModelRecommendation,
    PromptRecommendation,
    recommend_model_capabilities,
    recommend_prompts,
)
from .registry import (
    PromptError,
    get_prompt,
    list_prompts,
    list_prompts_by_category,
    list_prompts_by_role,
    list_prompt_roles,
    suggest_prompts_for_role,
)
from .schema import (
    CATEGORIES,
    PROMPT_ROLES,
    ModelPreferences,
    PromptProfile,
    validate_profile,
)
from .task import (
    TASK_CATEGORIES,
    TaskProfile,
    classify_task,
    suggest_roles_for_task,
)

__all__ = [
    "PromptError",
    "PromptProfile",
    "ModelPreferences",
    "ModelCapabilityProfile",
    "TaskProfile",
    "PROMPT_ROLES",
    "CATEGORIES",
    "TASK_CATEGORIES",
    "validate_profile",
    "get_prompt",
    "list_prompts",
    "list_prompts_by_role",
    "list_prompts_by_category",
    "list_prompt_roles",
    "suggest_prompts_for_role",
    "classify_task",
    "suggest_roles_for_task",
    "recommend_prompts",
    "recommend_model_capabilities",
    "role_model_preferences",
    "preferences_for_profile",
    "model_archetypes",
    "PromptRecommendation",
    "ModelRecommendation",
]
