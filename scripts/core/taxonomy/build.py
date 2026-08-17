"""Deterministic Phase B taxonomy builder.

The builder is intentionally a read-only consumer of the existing role, skill,
and prompt registries. It produces a derived graph without changing runtime
resolution or those registries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.core import prompt_library, skills
from scripts.core.agents import PROJECT_ROOT
from scripts.core.roles import load_roles

from .capabilities import (
    capabilities_from_repositories,
    internal_evidence_from_capabilities,
    load_internal_capabilities,
    stable_capability_id,
)
from .coverage import build_coverage
from .evidence import load_source_records
from .overrides import load_overrides


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else PROJECT_ROOT


def build_taxonomy(root: Path | None = None) -> dict[str, Any]:
    root = _root(root)
    repositories = load_source_records(root / "knowledge" / "sources")
    internal_capabilities = load_internal_capabilities(root)
    capabilities = tuple(sorted((*capabilities_from_repositories(repositories), *internal_capabilities), key=lambda item: item.id))
    capability_ids = {c.id for c in capabilities}

    role_data = load_roles(root)
    relations = _load_relations(root)
    skill_records = {skill.id: skill for skill in skills.list_skills()}
    prompt_records = {profile.id: profile for profile in prompt_library.list_prompts()}

    role_edges: dict[str, dict[str, Any]] = {}
    for role_id in sorted(role_data["roles"]):
        skill_ids = relations["role_skill_edges"].get(role_id, ())
        role_caps = {
            stable_capability_id(cap)
            for sid in skill_ids
            for cap in skill_records.get(sid, ()).capabilities
            if stable_capability_id(cap) in capability_ids
        }
        role_caps.update(
            stable_capability_id(cap)
            for profile_id in relations["role_prompt_edges"].get(role_id, ())
            for profile in (prompt_records.get(profile_id),)
            if profile is not None
            for cap in profile.capabilities
            if stable_capability_id(cap) in capability_ids
        )
        role_caps = sorted(role_caps)
        category = _category_for(role_caps, capabilities)
        role_edges[role_id] = {"capabilities": role_caps, "category": category}

    skill_edges = {
        sid: {"capabilities": sorted(stable_capability_id(cap) for cap in skill.capabilities if stable_capability_id(cap) in capability_ids)}
        for sid, skill in sorted(skill_records.items())
    }
    prompt_edges = {
        pid: {"capabilities": sorted(stable_capability_id(cap) for cap in profile.capabilities if stable_capability_id(cap) in capability_ids)}
        for pid, profile in sorted(prompt_records.items())
    }
    role_skill_edges = {
        rid: [sid for sid in relations["role_skill_edges"].get(rid, ()) if sid in skill_records]
        for rid in role_edges
    }
    role_prompt_edges = {
        rid: [pid for pid in relations["role_prompt_edges"].get(rid, ()) if pid in prompt_records]
        for rid in role_edges
    }
    categories = _categories(capabilities)
    agent_assignments, coverage = build_coverage(
        capabilities=[_capability_dict(item) for item in capabilities],
        role_edges=role_edges,
        role_skill_edges=role_skill_edges,
        role_prompt_edges=role_prompt_edges,
        role_assignments=role_data["assignments"],
        agent_context=_agent_context(root),
        overrides=load_overrides(root),
    )
    return {
        "schema_version": 1,
        "generated_from": "knowledge/sources/*.md (frontmatter evidence)",
        "repositories": [_repository_dict(repo) for repo in repositories],
        "evidence": [_evidence_dict(item) for repo in repositories for item in repo.evidence]
        + [_evidence_dict(item) for item in internal_evidence_from_capabilities(internal_capabilities)],
        "capabilities": [_capability_dict(capability) for capability in capabilities],
        "categories": categories,
        "role_edges": role_edges,
        "skill_edges": skill_edges,
        "prompt_edges": prompt_edges,
        "role_skill_edges": role_skill_edges,
        "role_prompt_edges": role_prompt_edges,
        "agent_assignments": agent_assignments,
        "coverage": coverage,
    }


def write_taxonomy(root: Path | None = None) -> Path:
    root = _root(root)
    destination = root / "knowledge" / "taxonomy" / "taxonomy.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    taxonomy = build_taxonomy(root)
    validate_taxonomy(taxonomy)
    destination.write_text(json.dumps(taxonomy, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return destination


def validate_taxonomy(taxonomy: dict[str, Any]) -> None:
    """Validate the generated artifact before it is made visible to runtime."""
    required = {"repositories", "evidence", "capabilities", "categories", "role_skill_edges", "role_prompt_edges", "agent_assignments", "coverage"}
    missing = required - set(taxonomy)
    if taxonomy.get("schema_version") != 1 or missing:
        raise ValueError(f"invalid taxonomy artifact: missing {sorted(missing)}")
    if taxonomy["coverage"].get("uncovered_agents") or taxonomy["coverage"].get("uncovered_capabilities"):
        raise ValueError("invalid taxonomy artifact: incomplete coverage")


def _load_relations(root: Path) -> dict[str, dict[str, list[str]]]:
    data = json.loads((root / "knowledge" / "taxonomy" / "relations.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(data.get(key), dict) for key in ("role_skill_edges", "role_prompt_edges")):
        raise ValueError("relations.json must define role_skill_edges and role_prompt_edges")
    return data


def _category_for(capability_ids: list[str], capabilities: tuple) -> str:
    domains = [domain for capability in capabilities if capability.id in capability_ids for domain in capability.domains]
    return min(domains) if domains else "general"


def _categories(capabilities: tuple) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for capability in capabilities:
        for domain in capability.domains or ("general",):
            grouped.setdefault(domain, []).append(capability.id)
    return [{"id": domain, "name": domain.replace("-", " ").title(), "capabilities": sorted(ids)} for domain, ids in sorted(grouped.items())]


def _agent_context(root: Path) -> dict[str, dict[str, list[str]]]:
    """Read legacy agent context as a migration input without runtime imports."""
    path = root / "agent_context.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    skill_data = data.get("skill_assignments", {}) if isinstance(data, dict) else {}
    prompt_data = data.get("prompt_assignments", {}) if isinstance(data, dict) else {}
    agents = set(skill_data) | set(prompt_data)
    return {
        agent: {
            "skill_ids": [str(item) for item in skill_data.get(agent, [])],
            "prompt_profile_ids": [str(item) for item in prompt_data.get(agent, [])],
        }
        for agent in agents
        if isinstance(skill_data.get(agent, []), list) and isinstance(prompt_data.get(agent, []), list)
    }


def _repository_dict(repo: Any) -> dict[str, Any]:
    return {"id": repo.id, "source_url": repo.source_url, "url": repo.source_url, "license": repo.license, "source_type": repo.source_type, "extraction_mode": repo.extraction_mode, "code_reuse": repo.code_reuse, "domains": list(repo.domains)}


def _evidence_dict(item: Any) -> dict[str, Any]:
    return {"id": item.id, "repository": item.repository, "kind": item.kind, "summary": item.summary, "supports": list(item.supports), "confidence": item.confidence, "requires_inspection": item.requires_inspection}


def _capability_dict(item: Any) -> dict[str, Any]:
    return {"id": item.id, "name": item.name, "description": item.description, "domains": list(item.domains), "evidence": list(item.evidence), "source_repos": list(item.source_repos), "origin": item.origin, "license": item.license}


if __name__ == "__main__":
    print(write_taxonomy())
