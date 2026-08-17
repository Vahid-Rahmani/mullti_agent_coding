"""Taxonomy-resolved Agent Catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from scripts.core import opencode_cfg, prompt_library, roles, skills
from scripts.core.agents import AGENT_SPEC_BY_AGENT
from scripts.core.taxonomy.effective import load_effective
from scripts.core.taxonomy.overrides import load_overrides, save_overrides

EMPTY_AGENT_ID = "empty"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class AgentCatalogError(ValueError):
    """Raised for an unknown catalog preset or invalid application."""


@dataclass(frozen=True)
class AgentCategory:
    id: str
    name: str
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "sources": list(self.sources)}


@dataclass(frozen=True)
class AgentPreset:
    id: str
    display_name: str
    category: str
    description: str = ""
    agent_key: str = ""
    model: str = ""
    agent_mode: str = ""
    role: str = ""
    role_ids: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    prompt_profiles: tuple[str, ...] = ()
    knowledge: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "display_name": self.display_name, "category": self.category, "description": self.description, "agent_key": self.agent_key, "model": self.model, "agent_mode": self.agent_mode, "role": self.role, "role_ids": list(self.role_ids), "skills": list(self.skills), "prompt_profiles": list(self.prompt_profiles), "knowledge": list(self.knowledge), "capabilities": list(self.capabilities), "provenance": list(self.provenance)}


def _effective(repo_root: Path | None = None) -> dict:
    try:
        return load_effective(repo_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise AgentCatalogError("effective taxonomy is unavailable") from exc


def empty_agent() -> AgentPreset:
    return AgentPreset(EMPTY_AGENT_ID, "Empty Agent", "", "A blank agent with no inherited taxonomy context.")


def is_empty_agent(preset_id: str) -> bool:
    return (preset_id or "").strip() == EMPTY_AGENT_ID


def list_categories(repo_root: Path | None = None) -> tuple[AgentCategory, ...]:
    taxonomy = _effective(repo_root)
    by_capability = {item["id"]: item.get("source_repos", []) for item in taxonomy["capabilities"]}
    return tuple(AgentCategory(item["id"], item["name"], tuple(sorted({source for capability in item["capabilities"] for source in by_capability.get(capability, [])}))) for item in taxonomy["categories"])


def list_presets(repo_root: Path | None = None) -> tuple[AgentPreset, ...]:
    taxonomy = _effective(repo_root)
    capabilities = {item["id"]: item for item in taxonomy["capabilities"]}
    role_edges = taxonomy["role_edges"]
    result = []
    for agent_key, assignment in sorted(taxonomy["agent_assignments"].items()):
        spec = AGENT_SPEC_BY_AGENT.get(agent_key)
        if spec is None:
            continue
        role_ids = tuple(assignment.get("role_ids", []))
        role = role_ids[0] if role_ids else ""
        capability_ids = tuple(assignment.get("capability_ids", []))
        result.append(AgentPreset(f"agent-{agent_key}", spec.name, role_edges.get(role, {}).get("category", ""), f"Taxonomy-derived configuration for {spec.name}.", agent_key, role=role, role_ids=role_ids, skills=tuple(assignment.get("skill_ids", [])), prompt_profiles=tuple(assignment.get("prompt_profile_ids", [])), capabilities=capability_ids, provenance=tuple(sorted({source for capability in capability_ids for source in capabilities.get(capability, {}).get("source_repos", [])}))))
    return tuple(result)


def get_preset(preset_id: str, repo_root: Path | None = None) -> AgentPreset:
    if is_empty_agent(preset_id):
        return empty_agent()
    for preset in list_presets(repo_root):
        if preset.id == (preset_id or "").strip():
            return preset
    raise AgentCatalogError(f"unknown agent preset {preset_id!r}")


def presets_for_category(category_id: str, repo_root: Path | None = None) -> tuple[AgentPreset, ...]:
    return tuple(preset for preset in list_presets(repo_root) if preset.category == (category_id or "").strip())


def get_category(category_id: str, repo_root: Path | None = None) -> AgentCategory | None:
    return next((item for item in list_categories(repo_root) if item.id == (category_id or "").strip()), None)


def role_category(role_id: str, repo_root: Path | None = None) -> str:
    return _effective(repo_root).get("role_edges", {}).get((role_id or "").strip(), {}).get("category", "")


def roles_in_category(category_id: str, repo_root: Path | None = None) -> tuple[str, ...]:
    return tuple(role for role, edge in sorted(_effective(repo_root)["role_edges"].items()) if edge.get("category") == (category_id or "").strip())


def role_categories(repo_root: Path | None = None) -> tuple[AgentCategory, ...]:
    used = {role_category(role.id, repo_root) for role in roles.list_roles(repo_root)}
    return tuple(category for category in list_categories(repo_root) if category.id in used)


def role_sources(role_id: str, repo_root: Path | None = None) -> tuple[str, ...]:
    taxonomy = _effective(repo_root)
    source_by_capability = {item["id"]: item.get("source_repos", []) for item in taxonomy["capabilities"]}
    return tuple(sorted({source for capability in taxonomy["role_edges"].get(role_id, {}).get("capabilities", []) for source in source_by_capability.get(capability, [])}))


def category_sources(category_id: str, repo_root: Path | None = None) -> tuple[str, ...]:
    category = get_category(category_id, repo_root)
    return category.sources if category else ()


def resolve_preset_config(preset: AgentPreset, repo_root: Path | None = None) -> dict:
    model = preset.model or (opencode_cfg.resolve_model(preset.agent_key, repo_root) if preset.agent_key else "") or ""
    return {**preset.to_dict(), "model": model, "agent_mode": preset.agent_mode or ("all" if preset.agent_key else ""), "empty": is_empty_agent(preset.id)}


def build_preset_runtime_prompt(preset: AgentPreset, user_request: str = "", repo_root: Path | None = None) -> str:
    from scripts.core import runtime_context

    if is_empty_agent(preset.id):
        return (user_request or "").strip()
    return runtime_context.build_runtime_prompt(preset.agent_key, role_ids=list(preset.role_ids) or ([preset.role] if preset.role else []), skill_ids=list(preset.skills), prompt_profile_ids=list(preset.prompt_profiles), user_request=user_request, repo_root=repo_root)


def apply_preset(preset: AgentPreset | str, repo_root: Path | None = None) -> dict:
    """Persist a selected preset as a curated assignment override."""
    value = get_preset(preset, repo_root) if isinstance(preset, str) else preset
    if is_empty_agent(value.id) or not value.agent_key:
        return resolve_preset_config(value, repo_root)
    overrides = load_overrides(repo_root)
    overrides.setdefault("agent_assignment_overrides", {})[value.agent_key] = {"capability_ids": list(value.capabilities), "role_ids": list(value.role_ids) or ([value.role] if value.role else []), "skill_ids": list(value.skills), "prompt_profile_ids": list(value.prompt_profiles)}
    save_overrides(overrides, repo_root)
    return resolve_preset_config(value, repo_root)


def validate_preset(preset: AgentPreset, repo_root: Path | None = None) -> list[str]:
    problems = []
    if not preset.id or not _SLUG_RE.match(preset.id):
        problems.append(f"preset: invalid id {preset.id!r}")
    if preset.category and preset.category not in {item.id for item in list_categories(repo_root)}:
        problems.append(f"{preset.id}: unknown category {preset.category!r}")
    if preset.agent_key and preset.agent_key not in AGENT_SPEC_BY_AGENT:
        problems.append(f"{preset.id}: unknown agent key {preset.agent_key!r}")
    if preset.role and preset.role not in {item.id for item in roles.list_roles(repo_root)}:
        problems.append(f"{preset.id}: unknown role {preset.role!r}")
    known_skills = {item.id for item in skills.list_skills()}
    known_prompts = {item.id for item in prompt_library.list_prompts()}
    problems.extend(f"{preset.id}: unknown skill {item!r}" for item in preset.skills if item not in known_skills)
    problems.extend(f"{preset.id}: unknown prompt profile {item!r}" for item in preset.prompt_profiles if item not in known_prompts)
    return problems


def validate_catalog(repo_root: Path | None = None) -> list[str]:
    categories, presets = list_categories(repo_root), list_presets(repo_root)
    problems = []
    if len({item.id for item in categories}) != len(categories):
        problems.append("duplicate category id")
    if len({item.id for item in presets}) != len(presets):
        problems.append("duplicate agent preset id")
    for preset in presets:
        problems.extend(validate_preset(preset, repo_root))
    return problems


__all__ = ["EMPTY_AGENT_ID", "AgentCatalogError", "AgentCategory", "AgentPreset", "apply_preset", "build_preset_runtime_prompt", "category_sources", "empty_agent", "get_category", "get_preset", "is_empty_agent", "list_categories", "list_presets", "presets_for_category", "resolve_preset_config", "role_categories", "role_category", "role_sources", "roles_in_category", "validate_catalog", "validate_preset"]
