"""Prompt registry — validated, immutable, deterministic access to the library.

Public API::

    get_prompt(prompt_id)            -> PromptProfile (raises PromptError)
    list_prompts()                   -> list[PromptProfile]  (sorted by id)
    list_prompts_by_role(role)       -> list[PromptProfile]
    list_prompts_by_category(cat)    -> list[PromptProfile]
    suggest_prompts_for_role(role)   -> list[PromptProfile]  (keyword mapping)
    list_prompt_roles()              -> tuple[str, ...]

The registry is built once from the validated built-ins and cached; profiles
are immutable (``frozen=True``) and exposed read-only by value. Unknown ids fail
with a clear :class:`PromptError`. Ordering is always deterministic (sorted by id).
"""

from __future__ import annotations

from .builtin import BUILTIN_PROFILES
from .schema import PROMPT_ROLES, PromptProfile


class PromptError(ValueError):
    """Raised for an unknown prompt id (mapped to HTTP 404 by routes)."""


# ---------------------------------------------------------------- registry cache


_REGISTRY: dict[str, PromptProfile] | None = None


def _registry() -> dict[str, PromptProfile]:
    """Build (once) and cache the id -> profile map from the validated built-ins."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = {p.id: p for p in BUILTIN_PROFILES}
    return _REGISTRY


# ---------------------------------------------------------------- lookups


def get_prompt(prompt_id: str) -> PromptProfile:
    """Return one profile by id, or raise :class:`PromptError` for an unknown id."""
    profile = _registry().get((prompt_id or "").strip())
    if profile is None:
        raise PromptError(f"unknown prompt profile {prompt_id!r}")
    return profile


def list_prompts() -> list[PromptProfile]:
    """All profiles, deterministically ordered by id."""
    return sorted(_registry().values(), key=lambda p: p.id)


def list_prompts_by_role(role: str) -> list[PromptProfile]:
    """Profiles whose ``role`` field equals ``role`` (exact match)."""
    role = (role or "").strip()
    return [p for p in list_prompts() if p.role == role]


def list_prompts_by_category(category: str) -> list[PromptProfile]:
    """Profiles whose ``category`` field equals ``category`` (exact match)."""
    category = (category or "").strip()
    return [p for p in list_prompts() if p.category == category]


def list_prompt_roles() -> tuple[str, ...]:
    """The canonical prompt roles, in schema order."""
    return PROMPT_ROLES


# ---------------------------------------------------------------- role suggestion


def _norm(value: str) -> str:
    """Lowercase and fold separators to spaces so ``software-engineer``,
    ``software_engineer`` and ``Software Engineer`` compare equal."""
    return " ".join((value or "").lower().replace("_", " ").replace("-", " ").split())


# Normalized prompt role -> canonical role (for exact-role suggestions).
_NORM_ROLE: dict[str, str] = {_norm(role): role for role in PROMPT_ROLES}

# Keyword -> prompt role, ordered most-specific first. A role-store id, an agent
# key, or a plain word (\"developer\", \"architect\", \"security\") maps to the
# first prompt role whose keyword it contains. This is deliberately deterministic
# and keyword-based (Phase 1) — no LLM-based selection.
_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("software_architect", ("architect", "architecture")),
    ("code_reviewer", ("review", "reviewer")),
    ("debugger", ("debug",)),
    ("qa_engineer", ("qa", "test", "testing", "quality", "e2e")),
    ("security_engineer", ("security", "secure", "threat", "audit")),
    ("devops_engineer", ("devops", "cicd", "ci/cd", "ci cd", "deploy", "infrastructure", "release")),
    ("cloud_engineer", ("cloud", "azure", "aws", "gcp", "networking", "network")),
    ("data_engineer", ("data", "etl", "pipeline", "warehouse")),
    ("ai_engineer", ("ai", "llm", "agent", "rag", "machine learning", "ml")),
    ("researcher", ("research", "researcher", "analyst", "literature")),
    ("technical_writer", ("writer", "documentation", "docs", "write")),
    ("project_manager", ("manager", "project", "pm", "planning", "delivery", "risk")),
    ("orchestrator", ("orchestrat", "coordinator", "workflow", "delegat")),
    ("software_engineer", ("developer", "engineer", "software", "coding", "code", "python", "fastapi")),
)


def suggest_prompts_for_role(role: str) -> list[PromptProfile]:
    """Deterministically suggest prompt profiles for a role/agent string.

    Matches a canonical prompt role exactly first (``software_engineer`` →
    ``software_engineer``); otherwise maps by keyword (``developer`` →
    ``software_engineer``, ``architect`` → ``software_architect``,
    ``security`` → ``security_engineer``, and so on). Returns ``[]`` when
    nothing maps.
    """
    key = _norm(role)
    if not key:
        return []
    exact = _NORM_ROLE.get(key)
    if exact is not None:
        return list_prompts_by_role(exact)
    for prompt_role, keywords in _KEYWORDS:
        if any(kw in key for kw in keywords):
            return list_prompts_by_role(prompt_role)
    return []


__all__ = [
    "PromptError",
    "get_prompt",
    "list_prompts",
    "list_prompts_by_role",
    "list_prompts_by_category",
    "suggest_prompts_for_role",
    "list_prompt_roles",
]
