"""Runtime context — the canonical, deterministic agent dispatch context.

Phase 30 closes the Agent → Role → Skill → Prompt Profile → Task data flow: the
registries already define Roles / Skills / Prompt Profiles, but plain dispatch
only ever injected ``roles.json`` role assignments (and nothing else). This
module builds ONE structured runtime prompt used by every execution path, so a
configured agent actually receives its identity, roles, skills, and prompt
profiles at runtime.

Composition order (fixed and documented):

    Agent identity
    → Assigned roles
    → Skills
    → Prompt profiles / instruction
    → Project context
    → Workflow context
    → Task
    → User request

Nothing here is model- or provider-specific, and nothing introduces an external
runtime dependency. Provenance is preserved: prompt profiles and skills carry
their ``source``/``license``/``origin`` metadata (from the Phase 28 registries),
which is surfaced in the rendered context.

Backward compatibility: an agent with **no** roles, skills, prompt profiles, or
explicit task/project/workflow context receives its raw request unchanged —
exactly as it did before this phase.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.core import opencode_cfg, prompt_library, roles, skills
from scripts.core.agents import AGENT_SPEC_BY_AGENT, PROJECT_ROOT
from scripts.core.taxonomy.effective import load_effective


def agent_context_path(repo_root: Path | None = None) -> Path:
    """Location of the per-agent skill/prompt-profile assignment file.

    ``$ZOVA_AGENT_CONTEXT`` overrides the default ``agent_context.json`` at the
    repo root (mirrors ``roles.py``'s ``$ZOVA_ROLES`` override).
    """
    env = os.environ.get("ZOVA_AGENT_CONTEXT", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(repo_root if repo_root is not None else PROJECT_ROOT) / "agent_context.json"


def load_agent_context(repo_root: Path | None = None) -> dict:
    """Load ``{"skill_assignments": {agent: [ids]}, "prompt_assignments": {agent: [ids]}}``.

    Missing/corrupt files yield an empty structure (never raises).
    """
    data: dict = {"skill_assignments": {}, "prompt_assignments": {}}
    try:
        path = agent_context_path(repo_root)
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("skill_assignments", "prompt_assignments"):
                    value = raw.get(key)
                    if isinstance(value, dict):
                        data[key] = {
                            str(k): [str(x) for x in v]
                            for k, v in value.items()
                            if isinstance(v, list)
                        }
    except (OSError, ValueError):
        pass
    return data


def save_agent_context(data: dict, repo_root: Path | None = None) -> None:
    """Atomically persist the skill/prompt-profile assignments (temp + replace)."""
    path = agent_context_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _known_skill_ids() -> set[str]:
    return {s.id for s in skills.list_skills()}


def skills_for_agent(agent: str, repo_root: Path | None = None) -> list[str]:
    """Ordered, validated skill ids assigned to an agent key."""
    data = load_agent_context(repo_root)
    ids = data["skill_assignments"].get(agent) or []
    known = _known_skill_ids()
    return [s for s in ids if s in known]


def prompt_profiles_for_agent(agent: str, repo_root: Path | None = None) -> list[str]:
    """Ordered, deduplicated prompt-profile ids assigned to an agent key."""
    data = load_agent_context(repo_root)
    ids = data["prompt_assignments"].get(agent) or []
    return list(dict.fromkeys(ids))


def assign_skills(agent: str, skill_ids: list[str] | tuple[str, ...],
                  repo_root: Path | None = None) -> list[str]:
    """Set an agent's skill list (ids must exist; order preserved, deduped)."""
    known = _known_skill_ids()
    normalized: list[str] = []
    for sid in skill_ids:
        sid = str(sid).strip()
        if sid not in known:
            raise skills.SkillError(f"unknown skill {sid!r}")
        if sid not in normalized:
            normalized.append(sid)
    data = load_agent_context(repo_root)
    data["skill_assignments"][agent] = normalized
    save_agent_context(data, repo_root)
    return normalized


def assign_prompt_profiles(agent: str, profile_ids: list[str] | tuple[str, ...],
                           repo_root: Path | None = None) -> list[str]:
    """Set an agent's prompt-profile list (ids must exist; order preserved)."""
    normalized: list[str] = []
    for pid in profile_ids:
        pid = str(pid).strip()
        try:
            prompt_library.get_prompt(pid)
        except prompt_library.PromptError as exc:
            raise prompt_library.PromptError(f"unknown prompt profile {pid!r}") from exc
        if pid not in normalized:
            normalized.append(pid)
    data = load_agent_context(repo_root)
    data["prompt_assignments"][agent] = normalized
    save_agent_context(data, repo_root)
    return normalized


# ---------------------------------------------------------------- rendering


def render_agent_identity(agent: str, repo_root: Path | None = None) -> str:
    """A deterministic ``## Agent Identity`` block (empty for an unknown agent)."""
    spec = AGENT_SPEC_BY_AGENT.get(agent)
    if spec is None:
        return ""
    lines = ["## Agent Identity"]
    lines.append(f"- Name: {spec.name}")
    lines.append(f"- Agent key: {spec.agent or ''}")
    lines.append(f"- Tag: {spec.tag}")
    model = opencode_cfg.resolve_model(agent, repo_root) or ""
    if model:
        lines.append(f"- Model: {model}")
    return "\n".join(lines) + "\n"


def render_prompt_profile_context(profile_ids: list[str] | tuple[str, ...] | None) -> str:
    """A ``## Prompt Profile`` block for a set of profiles (provenance-aware).

    Unknown ids degrade to nothing; only non-empty profiles are rendered.
    """
    ids = [str(p) for p in (profile_ids or ()) if str(p).strip()]
    profiles: list = []
    seen: set[str] = set()
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        try:
            profiles.append(prompt_library.get_prompt(pid))
        except prompt_library.PromptError:
            continue
    if not profiles:
        return ""

    blocks: list[str] = []
    for profile in profiles:
        parts = [f"### {profile.name}"]
        if profile.role:
            parts.append(f"Role: {profile.role}")
        if profile.description:
            parts.append(profile.description)
        if profile.prompt.strip():
            parts.append(profile.prompt.strip())
        provenance: list[str] = []
        if profile.origin != "original":
            if profile.source:
                provenance.append(f"source: {profile.source}")
            if profile.license:
                provenance.append(f"license: {profile.license}")
        if provenance:
            parts.append("Provenance: " + "; ".join(provenance))
        blocks.append("\n".join(parts))
    return "## Prompt Profile\n" + "\n\n".join(blocks) + "\n"


def _dedupe(ids: list[str] | tuple[str, ...] | None) -> list[str]:
    out: list[str] = []
    for value in (ids or ()):
        value = str(value).strip()
        if value and value not in out:
            out.append(value)
    return out


# ---------------------------------------------------------------- role mapping

# Deterministic role id -> ordered skill ids. This is the automatic fallback
# used ONLY when no explicit skills are assigned (agent_context.json, a
# workflow node, or an explicit runtime argument). Skill ids are validated at
# import; the union across multiple roles is order-preserving and deduplicated.
ROLE_SKILL_MAP: dict[str, tuple[str, ...]] = {
    "researcher": ("structured-research", "source-verification"),
    "seo-researcher": ("structured-research", "source-verification",
                       "anti-slop-refinement"),
    "seo-writer": ("structured-research", "anti-slop-refinement",
                   "action-first-communication"),
    "security-engineer": ("security-reconnaissance", "security-validation"),
    "software-engineer": ("repository-analysis", "fix-verify-loop"),
    "python-developer": ("repository-analysis", "fix-verify-loop"),
    "fastapi-developer": ("repository-analysis", "fix-verify-loop"),
    "software-architect": ("repository-analysis", "workflow-planning"),
    "code-reviewer": ("repository-analysis", "anti-slop-refinement"),
    "qa-engineer": ("repository-analysis", "fix-verify-loop"),
    "devops-engineer": ("repository-analysis", "workflow-planning"),
    "ai-agent-engineer": ("workflow-planning", "repository-analysis"),
    "ai-llm-engineer": ("repository-analysis", "workflow-planning"),
    "technical-writer": ("anti-slop-refinement", "action-first-communication"),
    "knowledge-engineer": ("knowledge-extraction", "structured-research",
                           "source-verification"),
}


def skills_for_roles(role_ids: list[str] | tuple[str, ...] | None,
                     repo_root: Path | None = None) -> list[str]:
    """Union of skill ids mapped from a set of roles.

    Role order is preserved and duplicates are removed. Unknown roles and
    unknown skill ids degrade to nothing (never raise), so a valid role
    without a mapping still yields a valid runtime prompt.
    """
    return _taxonomy_edge_union(role_ids, "role_skill_edges", _known_skill_ids(), repo_root)


def prompt_profiles_for_roles(
        role_ids: list[str] | tuple[str, ...] | None,
        repo_root: Path | None = None) -> list[str]:
    """Union of prompt-profile ids suggested for a set of roles.

    Delegates to :func:`prompt_library.suggest_prompts_for_role` (deterministic
    keyword mapping, no LLM) and keeps the first-occurrence order across roles.
    """
    known = {profile.id for profile in prompt_library.list_prompts()}
    return _taxonomy_edge_union(role_ids, "role_prompt_edges", known, repo_root)


def _taxonomy_edge_union(
        role_ids: list[str] | tuple[str, ...] | None,
        edge_name: str,
        known_ids: set[str],
        repo_root: Path | None = None,
) -> list[str]:
    """Resolve a role-edge union from the effective taxonomy.

    The checked-in taxonomy remains the compatibility fallback for temporary
    project roots that have no generated taxonomy yet. Unknown roles simply
    contribute no edges, preserving the prior no-crash behavior.
    """
    try:
        taxonomy = load_effective(repo_root)
    except (FileNotFoundError, ValueError, OSError):
        taxonomy = load_effective(PROJECT_ROOT)
    edges = taxonomy.get(edge_name, {})
    out: list[str] = []
    for role_id in _dedupe(role_ids):
        for item_id in edges.get(role_id, []):
            if item_id in known_ids and item_id not in out:
                out.append(item_id)
    return out


def role_derived_skill_ids_for_agent(agent: str,
                                     repo_root: Path | None = None) -> list[str]:
    """Skills an agent's assigned roles automatically imply (for the UI/API)."""
    return skills_for_roles(_resolved_role_ids(agent, repo_root), repo_root)


def role_derived_profile_ids_for_agent(agent: str,
                                       repo_root: Path | None = None) -> list[str]:
    """Prompt profiles an agent's assigned roles automatically imply."""
    return prompt_profiles_for_roles(_resolved_role_ids(agent, repo_root), repo_root)


def _resolved_role_ids(agent: str, repo_root: Path | None) -> list[str]:
    """Explicit role assignments win; otherwise use the effective matrix."""
    try:
        taxonomy = load_effective(repo_root)
    except (FileNotFoundError, ValueError, OSError):
        taxonomy = load_effective(PROJECT_ROOT)
    assignment = taxonomy.get("agent_assignments", {}).get(agent, {})
    if taxonomy.get("coverage", {}).get("assignment_sources", {}).get(agent) == "override":
        return _dedupe(assignment.get("role_ids", []))
    explicit = roles.roles_for_agent(agent, repo_root)
    if explicit:
        return explicit
    return _dedupe(assignment.get("role_ids", []))


def _resolve_skills(agent: str,
                    skill_ids: list[str] | tuple[str, ...] | None,
                    eff_roles: list[str],
                    repo_root: Path | None) -> list[str]:
    """Effective skills: explicit arg > explicit agent assignment > role-derived."""
    if skill_ids is not None:
        return _dedupe(skill_ids)
    explicit = skills_for_agent(agent, repo_root)
    if explicit:
        return explicit
    return skills_for_roles(eff_roles, repo_root)


def _resolve_profiles(agent: str,
                      prompt_profile_ids: list[str] | tuple[str, ...] | None,
                      eff_roles: list[str],
                      repo_root: Path | None) -> list[str]:
    """Effective profiles: explicit arg > explicit agent assignment > role-derived."""
    if prompt_profile_ids is not None:
        return _dedupe(prompt_profile_ids)
    explicit = prompt_profiles_for_agent(agent, repo_root)
    if explicit:
        return explicit
    return prompt_profiles_for_roles(eff_roles, repo_root)


# ---------------------------------------------------------------- builder


def build_runtime_prompt(
    agent: str,
    *,
    role_ids: list[str] | tuple[str, ...] | None = None,
    skill_ids: list[str] | tuple[str, ...] | None = None,
    prompt_profile_ids: list[str] | tuple[str, ...] | None = None,
    instruction: str = "",
    task: str = "",
    project_context: str = "",
    workflow_context: str = "",
    user_request: str = "",
    repo_root: Path | None = None,
) -> str:
    """Compose the canonical runtime prompt for one agent (deterministic).

    Explicit ``*_ids`` override the agent's configured assignments; ``None``
    falls back to them. ``instruction`` (a workflow node's editable final
    instruction or resolved profile text) takes precedence over the profile
    list, mirroring the Phase 5 source-vs-editable distinction.

    Returns the raw ``user_request`` unchanged when nothing else is configured,
    preserving pre-Phase-30 behavior for unconfigured agents.
    """
    eff_roles = _dedupe(role_ids) if role_ids is not None else _resolved_role_ids(
        agent, repo_root)
    eff_skills = _resolve_skills(agent, skill_ids, eff_roles, repo_root)
    eff_profiles = _resolve_profiles(agent, prompt_profile_ids, eff_roles, repo_root)

    request = (user_request or "").strip()
    task_text = (task or "").strip()
    project = (project_context or "").strip()
    workflow = (workflow_context or "").strip()
    instr = (instruction or "").strip()

    has_context = bool(
        eff_roles or eff_skills or eff_profiles or instr
        or task_text or project or workflow
    )
    if not has_context:
        return request

    parts: list[str] = []
    identity = render_agent_identity(agent, repo_root).strip()
    if identity:
        parts.append(identity)
    if eff_roles:
        role_ctx = roles.render_role_context(
            agent, role_ids=eff_roles, repo_root=repo_root).strip()
        if role_ctx:
            parts.append(role_ctx)
    if eff_skills:
        skill_ctx = skills.render_skill_context(eff_skills).strip()
        if skill_ctx:
            parts.append(skill_ctx)
    if instr:
        parts.append("## Instruction\n" + instr)
    elif eff_profiles:
        profile_ctx = render_prompt_profile_context(eff_profiles).strip()
        if profile_ctx:
            parts.append(profile_ctx)
    if project:
        parts.append("## Project Context\n" + project)
    if workflow:
        parts.append(workflow)
    if task_text:
        parts.append("## Task\n" + task_text)
    if request:
        parts.append(request)
    return "\n\n".join(parts)


def _validate_role_skill_map() -> None:
    """Fail fast if a mapped skill id does not exist (a programming error)."""
    known = _known_skill_ids()
    for role_id, skill_ids in ROLE_SKILL_MAP.items():
        for sid in skill_ids:
            if sid not in known:
                raise RuntimeError(
                    f"ROLE_SKILL_MAP[{role_id!r}] references unknown skill {sid!r}")


_validate_role_skill_map()


__all__ = [
    "ROLE_SKILL_MAP",
    "agent_context_path",
    "assign_prompt_profiles",
    "assign_skills",
    "build_runtime_prompt",
    "load_agent_context",
    "prompt_profiles_for_agent",
    "prompt_profiles_for_roles",
    "render_agent_identity",
    "render_prompt_profile_context",
    "role_derived_profile_ids_for_agent",
    "role_derived_skill_ids_for_agent",
    "save_agent_context",
    "skills_for_agent",
    "skills_for_roles",
]
