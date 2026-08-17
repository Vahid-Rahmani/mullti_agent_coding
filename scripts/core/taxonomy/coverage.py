"""Deterministic Agent Capability Matrix and coverage reporting."""

from __future__ import annotations

from typing import Any

from scripts.core.agents.registry import AGENT_SPECS


def runtime_agent_keys() -> tuple[str, ...]:
    """Read the runtime roster dynamically from the agent registry."""
    return tuple(spec.agent for spec in AGENT_SPECS if spec.agent)


def build_coverage(
    *,
    capabilities: list[dict[str, Any]],
    role_edges: dict[str, dict[str, Any]],
    role_skill_edges: dict[str, list[str]],
    role_prompt_edges: dict[str, list[str]],
    role_assignments: dict[str, list[str]],
    agent_context: dict[str, dict[str, list[str]]],
    overrides: dict[str, Any],
) -> tuple[dict[str, dict[str, list[str]]], dict[str, Any]]:
    """Return complete matrix assignments and an auditable coverage report."""
    capability_domains = {item["id"]: set(item.get("domains", [])) for item in capabilities}
    available_roles = {role_id: set(edge.get("capabilities", [])) for role_id, edge in role_edges.items() if edge.get("capabilities")}
    assignments: dict[str, dict[str, list[str]]] = {}
    sources: dict[str, str] = {}
    overrides_by_agent = overrides.get("agent_assignment_overrides", {})

    for agent in runtime_agent_keys():
        explicit = overrides_by_agent.get(agent, {})
        roles = list(explicit.get("role_ids", role_assignments.get(agent, [])))
        caps = list(explicit.get("capability_ids", []))
        if roles or caps:
            sources[agent] = "override" if explicit else "explicit"
        assignments[agent] = {"capability_ids": sorted(set(caps)), "role_ids": sorted({role for role in roles if role in role_edges}), "skill_ids": [], "prompt_profile_ids": []}

    for agent in runtime_agent_keys():
        if not assignments[agent]["role_ids"] and not assignments[agent]["capability_ids"]:
            role = _fallback_role(available_roles, assignments)
            assignments[agent]["role_ids"] = [role]
            sources[agent] = "fallback"
        role_caps = set().union(*(available_roles.get(role, set()) for role in assignments[agent]["role_ids"]))
        assignments[agent]["capability_ids"] = sorted(set(assignments[agent]["capability_ids"]) | role_caps)

    # Ensure every researched capability has a visible, deterministic owner.
    for capability in sorted(capability_domains):
        if any(capability in assignment["capability_ids"] for assignment in assignments.values()):
            continue
        agent = _fallback_agent(capability, assignments, capability_domains)
        assignments[agent]["capability_ids"] = sorted(set(assignments[agent]["capability_ids"]) | {capability})
        if sources.get(agent) not in {"explicit", "override"}:
            sources[agent] = "fallback"

    for agent, assignment in assignments.items():
        derived_skills = _union(assignment["role_ids"], role_skill_edges)
        derived_prompts = _union(assignment["role_ids"], role_prompt_edges)
        context = agent_context.get(agent, {})
        assignment["skill_ids"] = list(context.get("skill_ids") or derived_skills)
        assignment["prompt_profile_ids"] = list(context.get("prompt_profile_ids") or derived_prompts)

    covered = {capability for assignment in assignments.values() for capability in assignment["capability_ids"]}
    report = {
        "uncovered_agents": [agent for agent, value in assignments.items() if not value["capability_ids"] or not value["role_ids"]],
        "uncovered_capabilities": sorted(set(capability_domains) - covered),
        "derived_assignments": sorted(agent for agent, source in sources.items() if source == "derived"),
        "fallback_assignments": sorted(agent for agent, source in sources.items() if source == "fallback"),
        "explicit_assignments": sorted(agent for agent, source in sources.items() if source in {"explicit", "override"}),
        "assignment_sources": {agent: sources.get(agent, "derived") for agent in runtime_agent_keys()},
    }
    return assignments, report


def _fallback_role(available_roles: dict[str, set[str]], assignments: dict[str, dict[str, list[str]]]) -> str:
    covered = {cap for assignment in assignments.values() for cap in assignment["capability_ids"]}
    return min(available_roles, key=lambda role: (-len(available_roles[role] - covered), role))


def _fallback_agent(capability: str, assignments: dict[str, dict[str, list[str]]], domains: dict[str, set[str]]) -> str:
    target_domains = domains[capability]
    return min(
        assignments,
        key=lambda agent: (
            0 if target_domains & set().union(*(domains.get(cap, set()) for cap in assignments[agent]["capability_ids"])) else 1,
            len(assignments[agent]["capability_ids"]),
            agent,
        ),
    )


def _union(role_ids: list[str], edges: dict[str, list[str]]) -> list[str]:
    return list(dict.fromkeys(item for role in role_ids for item in edges.get(role, [])))
