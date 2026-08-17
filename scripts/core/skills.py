"""Skill registry — lightweight native reusable capabilities.

A :class:`Skill` sits between a *role* (reusable expertise) and a *prompt
profile* / *workflow* (the execution layer). Unlike a prompt profile — which is
a long "how to think" instruction — a Skill is an **operating procedure**: an
ordered, deterministic sequence of steps plus the capabilities it provides. It
is:

    * model-independent (never references a model id)
    * agent-independent (never references an agent key)
    * reusable + composable (referenced by id from workflow nodes, and may
      optionally compose a Prompt Profile for its "how to think" text)
    * explicitly identifiable (stable slug ids)
    * provenance-aware (adapted skills carry source/license/origin, exactly like
      :class:`~scripts.core.prompt_library.schema.PromptProfile`)

Skills are **built-in data** (like prompt profiles), not per-user config (like
roles.json). Nothing here introduces a runtime dependency on any external
repository — adapted skills are written in MultiAgentCoding's own words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.core.agents import PROJECT_ROOT
from scripts.core.prompt_library.schema import ORIGINS

# The coarse groupings a skill may declare. Kept small and distinct from prompt
# categories: a skill is a procedure, a prompt profile is a mindset.
SKILL_CATEGORIES: tuple[str, ...] = (
    "research",
    "quality",
    "communication",
    "seo",
    "security",
    "engineering",
    "orchestration",
    "knowledge",
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class SkillError(ValueError):
    """Raised for an unknown skill id (mapped to HTTP 404 by routes)."""


@dataclass(frozen=True)
class Skill:
    """One immutable, validated reusable capability / operating procedure."""

    id: str
    name: str
    description: str = ""
    category: str = ""                 # one of SKILL_CATEGORIES
    steps: tuple[str, ...] = ()        # the ordered operating procedure
    capabilities: tuple[str, ...] = ()
    prompt_profile: str = ""           # optional composed prompt-library id
    tags: tuple[str, ...] = ()
    version: str = "1.0.0"
    # Provenance — same style as PromptProfile.
    source: str = ""                   # upstream reference (e.g. "usestrix/strix")
    source_url: str = ""               # upstream URL
    license: str = ""                  # upstream license (e.g. "Apache-2.0")
    origin: str = "original"           # original | adapted | source-derived
    adaptation_note: str = ""          # how this skill relates to the source

    @classmethod
    def from_dict(cls, data: dict) -> Skill:
        def _list(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            return tuple(str(x) for x in value)

        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            category=str(data.get("category") or ""),
            steps=_list("steps"),
            capabilities=_list("capabilities"),
            prompt_profile=str(data.get("prompt_profile") or ""),
            tags=_list("tags"),
            version=str(data.get("version") or "1.0.0"),
            source=str(data.get("source") or ""),
            source_url=str(data.get("source_url") or ""),
            license=str(data.get("license") or ""),
            origin=str(data.get("origin") or "original"),
            adaptation_note=str(data.get("adaptation_note") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "steps": list(self.steps),
            "capabilities": list(self.capabilities),
            "prompt_profile": self.prompt_profile,
            "tags": list(self.tags),
            "version": self.version,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "origin": self.origin,
            "adaptation_note": self.adaptation_note,
        }


def validate_skill(skill: Skill) -> list[str]:
    """Return human-readable validation problems (empty == valid).

    Enforces: a slug id, a non-empty name, at least one procedure step (this is
    what distinguishes a Skill from a mere prompt), a known category, a semver
    version, and provenance rules identical to ``validate_profile`` (non-original
    skills require a source reference).
    """
    problems: list[str] = []
    if not skill.id:
        problems.append("id is required")
    elif not _SLUG_RE.match(skill.id):
        problems.append(f"invalid id {skill.id!r} (use [a-z0-9._-])")
    if not skill.name.strip():
        problems.append(f"{skill.id or '?'}: name is required")
    if not skill.steps:
        problems.append(f"{skill.id or '?'}: at least one procedure step is required")
    if skill.category not in SKILL_CATEGORIES:
        problems.append(f"{skill.id or '?'}: unknown category {skill.category!r}")
    if not skill.version or not _VERSION_RE.match(skill.version):
        problems.append(f"{skill.id or '?'}: invalid version {skill.version!r} "
                        "(use semver like 1.0.0)")
    if skill.origin not in ORIGINS:
        problems.append(f"{skill.id or '?'}: unknown origin {skill.origin!r}")
    if skill.origin != "original" and not skill.source.strip():
        problems.append(f"{skill.id or '?'}: origin {skill.origin!r} "
                        "requires a source reference")
    return problems


# ---------------------------------------------------------------- built-in skills


class SkillLibraryError(ValueError):
    """Raised for a malformed or duplicate built-in skill (a programming error)."""


def _build() -> tuple[Skill, ...]:
    built: list[Skill] = []
    seen: set[str] = set()
    for raw in BUILTIN_SKILL_DICTS:
        skill = Skill.from_dict(raw)
        problems = validate_skill(skill)
        if problems:
            raise SkillLibraryError(f"invalid built-in skill: {'; '.join(problems)}")
        if skill.id in seen:
            raise SkillLibraryError(f"duplicate skill id {skill.id!r}")
        seen.add(skill.id)
        built.append(skill)
    return tuple(built)


BUILTIN_SKILLS: tuple[Skill, ...] = ()
_SKILLS: dict[str, Skill] = {}


def list_skills() -> list[Skill]:
    """All built-in skills, deterministically ordered by id."""
    return sorted(_SKILLS.values(), key=lambda skill: skill.id)


def get_skill(skill_id: str) -> Skill:
    """Return one skill by id, or raise :class:`SkillError` when unknown."""
    skill = _SKILLS.get((skill_id or "").strip())
    if skill is None:
        raise SkillError(f"unknown skill {skill_id!r}")
    return skill


def list_skills_by_category(category: str) -> list[Skill]:
    """Return skills whose category equals ``category``."""
    return [skill for skill in list_skills() if skill.category == (category or "").strip()]


def resolve_skill_prompt(skill: Skill):
    """Return the optional prompt profile composed by ``skill``."""
    if not skill.prompt_profile:
        return None
    from scripts.core import prompt_library

    try:
        return prompt_library.get_prompt(skill.prompt_profile)
    except prompt_library.PromptError:
        return None


def render_skill_context(skill_ids: list[str] | tuple[str, ...] | None) -> str:
    """Build a deterministic prompt block for known skills."""
    resolved: list[Skill] = []
    seen: set[str] = set()
    for skill_id in skill_ids or ():
        if skill_id in seen:
            continue
        seen.add(skill_id)
        try:
            resolved.append(get_skill(skill_id))
        except SkillError:
            continue
    if not resolved:
        return ""
    blocks = []
    for skill in resolved:
        details = [f"### {skill.name}"]
        if skill.description:
            details.append(skill.description)
        details.extend(("Procedure:", "".join(f"{index}. {step}\n" for index, step in enumerate(skill.steps, 1))))
        blocks.append("\n".join(details))
    return "## Skills\n" + "\n".join(blocks) + "\n"


def _norm(value: str) -> str:
    return " ".join((value or "").lower().replace("_", " ").replace("-", " ").split())


_SKILL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("source-verification", ("verif", "citation", "cite", "provenance", "source check")),
    ("knowledge-extraction", ("knowledge extraction", "distill", "skill author", "book to skill", "convert document", "framework mining")),
    ("structured-research", ("research", "source collection", "collect source", "sources", "literature", "survey")),
    ("anti-slop-refinement", ("slop", "refine", "edit", "polish", "rewrite")),
    ("action-first-communication", ("action-first", "concise", "communicat")),
    ("competitive-analysis", ("competitor", "competitive", "gap analysis")),
    ("seo-research", ("seo", "keyword", "search intent", "ranking")),
    ("security-reconnaissance", ("recon", "attack surface", "scope", "enumerat")),
    ("security-validation", ("validate", "proof-of-concept", "poc", "pentest", "vulnerab", "finding")),
    ("fix-verify-loop", ("re-scan", "rescan", "remediat", "fix", "verify fix")),
    ("repository-analysis", ("repository", "codebase", "inspect", "audit code", "architecture review")),
    ("workflow-planning", ("multi-agent", "orchestrat", "workflow", "planning", "delegat", "handoff")),
)


def suggest_skills_for_task(text: str) -> list[Skill]:
    """Deterministically suggest skills from task keywords; never a taxonomy seed."""
    key = _norm(text)
    if not key:
        return []
    suggested: list[Skill] = []
    seen: set[str] = set()
    for skill_id, keywords in _SKILL_KEYWORDS:
        if any(keyword in key for keyword in keywords) and skill_id not in seen:
            try:
                suggested.append(get_skill(skill_id))
                seen.add(skill_id)
            except SkillError:
                continue
    return suggested


def _load_builtin_skill_dicts() -> tuple[dict, ...]:
    import json

    source = PROJECT_ROOT / "knowledge" / "taxonomy" / "skills.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SkillLibraryError("skills.json must contain a list")
    return tuple(data)


BUILTIN_SKILL_DICTS: tuple[dict, ...] = _load_builtin_skill_dicts()


# Build the validated registry once the built-in data is defined above.
_BUILT = _build()
BUILTIN_SKILLS = _BUILT
_SKILLS = {s.id: s for s in _BUILT}


__all__ = [
    "BUILTIN_SKILLS",
    "SKILL_CATEGORIES",
    "Skill",
    "SkillError",
    "SkillLibraryError",
    "get_skill",
    "list_skills",
    "list_skills_by_category",
    "render_skill_context",
    "resolve_skill_prompt",
    "suggest_skills_for_task",
    "validate_skill",
]
