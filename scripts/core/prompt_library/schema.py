"""Prompt profile schema — the strongly typed shape for a Prompt Library entry.

A :class:`PromptProfile` is pure, immutable data. It decouples the *source*
prompt (a reusable, versioned behaviour profile) from the *final* instruction
an agent node actually runs: the workflow node keeps its own editable
``instructions`` field, and a node may optionally reference a profile via its
``prompt_profile`` id. Nothing here touches agents, roles, models, or
``opencode.json`` — recommended models stay empty in Phase 1 (model coupling
is a later phase, and agents/models are runtime concerns by design).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The 14 prompt roles the built-in library covers. These are *prompt* roles
# (semantic expertise categories), distinct from the role-store ids in
# roles.json (which are reusable agent assignments). ``suggest_prompts_for_role``
# maps role-store ids / agent keys / plain words onto these.
PROMPT_ROLES: tuple[str, ...] = (
    "software_engineer",
    "software_architect",
    "code_reviewer",
    "debugger",
    "qa_engineer",
    "security_engineer",
    "devops_engineer",
    "cloud_engineer",
    "data_engineer",
    "ai_engineer",
    "researcher",
    "technical_writer",
    "project_manager",
    "orchestrator",
)

# Where a profile came from. "original" = written for MultiAgentCoding;
# "adapted" = rewritten into our own words from an external source; "source-
# derived" = closely derived from an external source's text. Non-original
# profiles must carry a ``source`` reference (enforced by validate_profile).
ORIGINS: tuple[str, ...] = (
    "original",
    "adapted",
    "source-derived",
)

# The categories a profile may declare. A profile's category is a coarser
# grouping than its role (e.g. every security_engineer profile is "security").
CATEGORIES: tuple[str, ...] = (
    "development",
    "architecture",
    "review",
    "debugging",
    "testing",
    "security",
    "devops",
    "cloud",
    "data",
    "ai",
    "research",
    "documentation",
    "management",
    "orchestration",
)


@dataclass(frozen=True)
class ModelPreferences:
    """Provider-neutral model *requirements* a prompt profile implies.

    Qualitative levels only — this describes what a model must be good at,
    never a specific provider or model id. ``context`` uses small/medium/large;
    the other fields use low/medium/high. ``latency`` low = fast (interactive);
    ``cost`` low = cheap.
    """

    reasoning: str = "medium"   # low | medium | high
    coding: str = "medium"      # low | medium | high
    context: str = "medium"     # small | medium | large
    tool_use: str = "medium"    # low | medium | high
    latency: str = "medium"     # low | medium | high  (low = fast)
    cost: str = "medium"        # low | medium | high  (low = cheap)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ModelPreferences":
        data = data or {}
        return cls(
            reasoning=str(data.get("reasoning") or "medium"),
            coding=str(data.get("coding") or "medium"),
            context=str(data.get("context") or "medium"),
            tool_use=str(data.get("tool_use") or "medium"),
            latency=str(data.get("latency") or "medium"),
            cost=str(data.get("cost") or "medium"),
        )

    def to_dict(self) -> dict:
        return {
            "reasoning": self.reasoning,
            "coding": self.coding,
            "context": self.context,
            "tool_use": self.tool_use,
            "latency": self.latency,
            "cost": self.cost,
        }


@dataclass(frozen=True)
class PromptProfile:
    """One immutable, validated prompt profile."""

    id: str
    name: str
    description: str = ""
    role: str = ""          # one of PROMPT_ROLES
    category: str = ""      # one of CATEGORIES
    prompt: str = ""        # the actual behavioural prompt text
    capabilities: tuple[str, ...] = ()
    recommended_models: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    version: str = "1.0.0"
    # Provenance: which external source (if any) this profile was adapted from.
    source: str = ""           # upstream reference (e.g. "NirDiamant/GenAI_Agents")
    source_url: str = ""       # upstream URL
    license: str = ""          # upstream license (e.g. "MIT", "Apache-2.0")
    origin: str = "original"   # "original" | "adapted" | "source-derived"
    adaptation_note: str = ""  # how this profile relates to the source
    model_preferences: ModelPreferences | None = None  # optional override

    @classmethod
    def from_dict(cls, data: dict) -> "PromptProfile":
        def _list(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            return tuple(str(x) for x in value)

        prefs = data.get("model_preferences")
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            role=str(data.get("role") or ""),
            category=str(data.get("category") or ""),
            prompt=str(data.get("prompt") or ""),
            capabilities=_list("capabilities"),
            recommended_models=_list("recommended_models"),
            tags=_list("tags"),
            version=str(data.get("version") or "1.0.0"),
            source=str(data.get("source") or ""),
            source_url=str(data.get("source_url") or ""),
            license=str(data.get("license") or ""),
            origin=str(data.get("origin") or "original"),
            adaptation_note=str(data.get("adaptation_note") or ""),
            model_preferences=(ModelPreferences.from_dict(prefs)
                               if isinstance(prefs, dict) else None),
        )

    def to_dict(self) -> dict:
        """Full serialization, including the prompt text (for detail views)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "role": self.role,
            "category": self.category,
            "prompt": self.prompt,
            "capabilities": list(self.capabilities),
            "recommended_models": list(self.recommended_models),
            "tags": list(self.tags),
            "version": self.version,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "origin": self.origin,
            "adaptation_note": self.adaptation_note,
            "model_preferences": (self.model_preferences.to_dict()
                                  if self.model_preferences else None),
        }

    def meta_dict(self) -> dict:
        """UI metadata only — omits the (potentially large) prompt text so list
        endpoints stay light; the full text is available from the detail view."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "role": self.role,
            "category": self.category,
            "capabilities": list(self.capabilities),
            "recommended_models": list(self.recommended_models),
            "tags": list(self.tags),
            "version": self.version,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "origin": self.origin,
            "adaptation_note": self.adaptation_note,
            "model_preferences": (self.model_preferences.to_dict()
                                  if self.model_preferences else None),
        }


def validate_profile(profile: PromptProfile) -> list[str]:
    """Return human-readable validation problems (empty == valid).

    Enforces: non-empty id/name/prompt, a known role, a known category, and a
    version-like ``1.2.3`` string. Ids must be slugs so they are stable lookup
    keys. This is the single validation boundary every registry load passes
    through, so a malformed built-in can never silently ship.
    """
    problems: list[str] = []
    if not profile.id:
        problems.append("id is required")
    elif not _SLUG_RE.match(profile.id):
        problems.append(f"invalid id {profile.id!r} (use [a-z0-9._-])")
    if not profile.name.strip():
        problems.append(f"{profile.id or '?'}: name is required")
    if not profile.prompt.strip():
        problems.append(f"{profile.id or '?'}: prompt text is required")
    if profile.role not in PROMPT_ROLES:
        problems.append(f"{profile.id or '?'}: unknown role {profile.role!r}")
    if profile.category not in CATEGORIES:
        problems.append(f"{profile.id or '?'}: unknown category {profile.category!r}")
    if not profile.version or not _VERSION_RE.match(profile.version):
        problems.append(f"{profile.id or '?'}: invalid version {profile.version!r} "
                        "(use semver like 1.0.0)")
    if profile.origin not in ORIGINS:
        problems.append(f"{profile.id or '?'}: unknown origin {profile.origin!r} "
                        "(use original/adapted/source-derived)")
    if profile.origin != "original" and not profile.source.strip():
        problems.append(f"{profile.id or '?'}: origin {profile.origin!r} "
                        "requires a source reference")
    return problems


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


__all__ = [
    "PromptProfile",
    "ModelPreferences",
    "PROMPT_ROLES",
    "CATEGORIES",
    "ORIGINS",
    "validate_profile",
]
