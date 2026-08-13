"""Role registry — reusable, model-independent role definitions.

Roles are structured data (expertise, responsibilities, tools, permissions,
rules, expected outputs) that live in a **separate config file** (``roles.json``
at the repo root, or the ``$ZOVA_ROLES`` override). Agents reference role ids
in a many-to-many ``assignments`` map, so:

    * one agent may have many roles,
    * many agents may share one role,
    * roles are editable/reusable without touching ``AgentSpec`` modules or
      ``opencode.json``, and are composed onto an agent at runtime.

Roles are strictly decoupled from models and providers: assigning a role never
changes an agent's model, and changing an agent's model never changes its role.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from scripts.core.agents import PROJECT_ROOT

# Precedence for resolving effective agent context (highest first).
PRECEDENCE: tuple[str, ...] = (
    "user_instruction",       # explicit instruction given with the task
    "user_role",              # role the user explicitly selected for the task
    "repository_instruction",  # AGENTS.md / project instructions
    "role_default",           # the assigned role's definition
    "agent_default",          # generic agent identity fallback
)


def roles_path(repo_root: Path | None = None) -> Path:
    """Location of the roles config file (``$ZOVA_ROLES`` > ``roles.json``)."""
    env = os.environ.get("ZOVA_ROLES", "").strip()
    if env:
        return Path(env).expanduser()
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    return root / "roles.json"


@dataclass(frozen=True)
class Role:
    """A single reusable role definition (structured, serializable)."""

    id: str
    name: str
    description: str = ""
    responsibilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, role_id: str, data: dict) -> "Role":
        def _list(key: str) -> tuple[str, ...]:
            value = data.get(key) or []
            return tuple(str(x) for x in value)

        return cls(
            id=role_id,
            name=str(data.get("name") or role_id),
            description=str(data.get("description") or ""),
            responsibilities=_list("responsibilities"),
            tools=_list("tools"),
            permissions=_list("permissions"),
            rules=_list("rules"),
            expected_outputs=_list("expected_outputs"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "responsibilities": list(self.responsibilities),
            "tools": list(self.tools),
            "permissions": list(self.permissions),
            "rules": list(self.rules),
            "expected_outputs": list(self.expected_outputs),
        }


class RoleError(ValueError):
    """Raised for invalid role/assignment operations (HTTP 409 by routes)."""


# ---------------------------------------------------------------- load / save


def load_roles(repo_root: Path | None = None) -> dict:
    """Load ``{roles: {id: {...}}, assignments: {agent: [role ids]}}``.

    Returns an empty structure when the file is missing/corrupt (never raises).
    """
    path = roles_path(repo_root)
    data: dict = {"roles": {}, "assignments": {}}
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data["roles"] = raw.get("roles") if isinstance(raw.get("roles"), dict) else {}
                data["assignments"] = (raw.get("assignments")
                                       if isinstance(raw.get("assignments"), dict) else {})
    except (OSError, ValueError):
        pass
    return data


def save_roles(data: dict, repo_root: Path | None = None) -> None:
    """Atomically persist the roles config (temp + ``os.replace``)."""
    path = roles_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- roles


def list_roles(repo_root: Path | None = None) -> list[Role]:
    data = load_roles(repo_root)
    return [Role.from_dict(rid, spec) for rid, spec in sorted(data["roles"].items())]


def get_role(role_id: str, repo_root: Path | None = None) -> Role | None:
    data = load_roles(repo_root)
    spec = data["roles"].get(role_id)
    return Role.from_dict(role_id, spec) if spec is not None else None


def create_role(role_id: str, *, name: str | None = None, description: str = "",
                responsibilities: list[str] | tuple[str, ...] = (),
                tools: list[str] | tuple[str, ...] = (),
                permissions: list[str] | tuple[str, ...] = (),
                rules: list[str] | tuple[str, ...] = (),
                expected_outputs: list[str] | tuple[str, ...] = (),
                repo_root: Path | None = None) -> Role:
    """Create or overwrite a (custom) role. Returns the stored Role."""
    role_id = _validate_role_id(role_id)
    role = Role(
        id=role_id,
        name=(name or role_id).strip() or role_id,
        description=description,
        responsibilities=tuple(str(x) for x in responsibilities),
        tools=tuple(str(x) for x in tools),
        permissions=tuple(str(x) for x in permissions),
        rules=tuple(str(x) for x in rules),
        expected_outputs=tuple(str(x) for x in expected_outputs),
    )
    data = load_roles(repo_root)
    data["roles"][role_id] = role.to_dict()
    save_roles(data, repo_root)
    return role


def delete_role(role_id: str, repo_root: Path | None = None) -> bool:
    """Delete a role definition and drop it from every assignment."""
    data = load_roles(repo_root)
    if role_id not in data["roles"]:
        return False
    del data["roles"][role_id]
    for agent in data["assignments"]:
        data["assignments"][agent] = [
            r for r in data["assignments"][agent] if r != role_id
        ]
    save_roles(data, repo_root)
    return True


def _validate_role_id(role_id: str) -> str:
    role_id = (role_id or "").strip().lower().replace(" ", "-")
    if not role_id or any(c in role_id for c in "/\\\"'"):
        raise RoleError(f"invalid role id {role_id!r}")
    return role_id


# ---------------------------------------------------------------- assignments


def roles_for_agent(agent: str, repo_root: Path | None = None) -> list[str]:
    """Ordered role ids currently assigned to an agent key."""
    data = load_roles(repo_root)
    assigned = data["assignments"].get(agent) or []
    return [r for r in assigned if r in data["roles"]]


def assign_roles(agent: str, role_ids: list[str] | tuple[str, ...],
                 repo_root: Path | None = None) -> list[str]:
    """Set an agent's full role list (many-to-many; ids must exist)."""
    data = load_roles(repo_root)
    normalized = []
    for rid in role_ids:
        rid = _validate_role_id(rid)
        if rid not in data["roles"]:
            raise RoleError(f"unknown role {rid!r}")
        if rid not in normalized:
            normalized.append(rid)
    data["assignments"][agent] = normalized
    save_roles(data, repo_root)
    return normalized


def add_role_to_agent(agent: str, role_id: str, repo_root: Path | None = None) -> list[str]:
    current = roles_for_agent(agent, repo_root)
    if role_id not in current:
        current.append(role_id)
    return assign_roles(agent, current, repo_root)


def remove_role_from_agent(agent: str, role_id: str, repo_root: Path | None = None) -> list[str]:
    current = [r for r in roles_for_agent(agent, repo_root) if r != role_id]
    return assign_roles(agent, current, repo_root)


def unassign_all(agent: str, repo_root: Path | None = None) -> None:
    data = load_roles(repo_root)
    data["assignments"].pop(agent, None)
    save_roles(data, repo_root)


# ---------------------------------------------------------------- rendering


def render_role_context(agent: str, role_ids: list[str] | None = None,
                        repo_root: Path | None = None) -> str:
    """Build a prompt-injectable Markdown block for an agent's roles.

    Returns ``""`` when the agent has no roles. Idempotent and deterministic.
    """
    ids = role_ids if role_ids is not None else roles_for_agent(agent, repo_root)
    if not ids:
        return ""
    roles = [get_role(rid, repo_root) for rid in ids]
    roles = [r for r in roles if r is not None]

    def _bullet(label: str, items: tuple[str, ...]) -> str:
        if not items:
            return ""
        return f"{label}:\n" + "".join(f"- {item}\n" for item in items)

    blocks = []
    for role in roles:
        parts = [f"### {role.name}"]
        if role.description:
            parts.append(role.description)
        parts.append(_bullet("Responsibilities", role.responsibilities))
        parts.append(_bullet("Tools", role.tools))
        parts.append(_bullet("Rules", role.rules))
        parts.append(_bullet("Expected outputs", role.expected_outputs))
        blocks.append("\n".join(p for p in parts if p))
    header = f"## Roles ({agent})\n"
    return header + "\n\n".join(blocks) + "\n"


def agent_context(agent: str, repo_root: Path | None = None) -> str:
    """Combined runtime context for an agent: its roles (if any)."""
    return render_role_context(agent, repo_root=repo_root)
