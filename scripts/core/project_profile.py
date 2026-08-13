"""Project profile — repository analysis -> structured project context.

Scans a repository for language/framework/tooling signals and derives a
:class:`ProjectProfile` (technologies, suggested roles, repository
instructions). Suggestions are **never auto-applied**: they are
*detected*/*suggested* until the user approves by assigning the role in
``roles.json`` (see :mod:`scripts.core.roles`). The profile is resolved at
runtime and injected into dispatch context dynamically — it is never
duplicated into each agent's configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scripts.core.agents import PROJECT_ROOT
from scripts.core import roles

# Technology signal -> role ids. A repository exhibiting the signal gets the
# corresponding role *suggested* (not assigned).
_TECH_ROLES: dict[str, tuple[str, ...]] = {
    "python": ("python-developer",),
    "fastapi": ("fastapi-developer",),
    "ai-agents": ("ai-agent-engineer",),
    "docker": ("devops-engineer",),
    "ci": ("devops-engineer",),
    "javascript": ("qa-engineer",),
}

# Universal maintenance roles suggested for every repository.
_UNIVERSAL_ROLES: tuple[str, ...] = ("code-reviewer", "software-architect")

# Manifest filename -> technology signal.
_MANIFEST_SIGNALS: dict[str, str] = {
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
}

# Repository-instruction files folded into the profile's instruction context.
_INSTRUCTION_FILES: tuple[str, ...] = (
    "AGENTS.md", "CONTRIBUTING.md", "README.md",
)


@dataclass
class ProjectProfile:
    """Structured summary of one repository's context and suggested roles."""

    root: Path
    technologies: tuple[str, ...] = ()
    manifests: dict[str, tuple[str, ...]] = field(default_factory=dict)
    instructions: dict[str, str] = field(default_factory=dict)
    detected_roles: tuple[str, ...] = ()
    suggested_roles: tuple[str, ...] = ()
    approved_roles: tuple[str, ...] = ()


def _signal_for_fastapi(root: Path, manifests: dict[str, tuple[str, ...]]) -> bool:
    """Detect FastAPI from manifest content (requirements.txt / pyproject)."""
    for name in ("requirements.txt", "pyproject.toml"):
        for rel in manifests.get(name, ()):
            path = root / rel
            try:
                if "fastapi" in path.read_text(encoding="utf-8").lower():
                    return True
            except OSError:
                continue
    return False


def _signal_for_ai_agents(root: Path) -> bool:
    return (root / "opencode.json").is_file() or (root / ".opencode").is_dir() \
        or (root / "AGENTS.md").is_file()


def analyze_repository(repo_root: Path | None = None) -> ProjectProfile:
    """Scan a repository and derive a :class:`ProjectProfile`.

    Detection is deterministic and read-only. ``suggested_roles`` are derived
    from detected technologies plus universal maintenance roles; they are
    never written to ``roles.json`` (approval is the user's action).
    """
    root = Path(repo_root) if repo_root is not None else PROJECT_ROOT
    manifests: dict[str, tuple[str, ...]] = {}
    technologies: list[str] = []

    for name, signal in _MANIFEST_SIGNALS.items():
        path = root / name
        if path.is_file():
            manifests.setdefault(name, (name,))
            if signal not in technologies:
                technologies.append(signal)

    # CI/CD signals from .github/workflows.
    workflows = root / ".github" / "workflows"
    if workflows.is_dir() and any(workflows.glob("*.yml")) or \
            workflows.is_dir() and any(workflows.glob("*.yaml")):
        manifests.setdefault(".github/workflows", (".github/workflows",))
        if "ci" not in technologies:
            technologies.append("ci")

    # Source-tree signals (fastest wins, read-only).
    if any((root / "scripts").rglob("*.py")) or any((root / "test").rglob("*.py")):
        if "python" not in technologies:
            technologies.append("python")
    if any((root / "scripts").rglob("*.js")) or any((root / "test").rglob("*.js")):
        if "javascript" not in technologies:
            technologies.append("javascript")

    if "python" in technologies and _signal_for_fastapi(root, manifests):
        technologies.append("fastapi")
    if _signal_for_ai_agents(root):
        technologies.append("ai-agents")

    detected = tuple(technologies)
    suggested: list[str] = []
    for tech in detected:
        for rid in _TECH_ROLES.get(tech, ()):
            if rid not in suggested:
                suggested.append(rid)
    for rid in _UNIVERSAL_ROLES:
        if rid not in suggested:
            suggested.append(rid)

    instructions: dict[str, str] = {}
    for name in _INSTRUCTION_FILES:
        path = root / name
        try:
            if path.is_file():
                instructions[name] = path.read_text(encoding="utf-8")
        except OSError:
            continue

    assignments = roles.load_roles(root).get("assignments", {})
    approved = tuple(sorted({rid for role_ids in assignments.values() for rid in role_ids}))

    return ProjectProfile(
        root=root,
        technologies=detected,
        manifests=manifests,
        instructions=instructions,
        detected_roles=detected,
        suggested_roles=tuple(suggested),
        approved_roles=approved,
    )


def suggest_roles(profile: ProjectProfile | None = None,
                  repo_root: Path | None = None) -> list[str]:
    """Role ids suggested for a repository (detected + universal), minus those
    already approved (so the list is "still to consider")."""
    prof = profile if profile is not None else analyze_repository(repo_root)
    approved = set(prof.approved_roles)
    return [r for r in prof.suggested_roles if r not in approved]


def suggested_role_reasons(profile: ProjectProfile | None = None,
                           repo_root: Path | None = None) -> dict[str, str]:
    """Human reason for each *pending* suggested role (why it was suggested).

    Maps role id → the technology signal that produced it (or "universal
    maintenance role" for the always-suggested reviewer/architect pair). Only
    roles still to consider are included (approved ones are dropped).
    """
    prof = profile if profile is not None else analyze_repository(repo_root)
    reasons: dict[str, str] = {}
    for tech in prof.detected_roles:
        for rid in _TECH_ROLES.get(tech, ()):
            reasons.setdefault(rid, f"detected: {tech}")
    for rid in _UNIVERSAL_ROLES:
        reasons.setdefault(rid, "universal maintenance role")
    approved = set(prof.approved_roles)
    return {rid: reason for rid, reason in reasons.items() if rid not in approved}


def render_project_context(profile: ProjectProfile | None = None,
                           repo_root: Path | None = None) -> str:
    """Prompt-injectable summary of the project (technologies + instructions)."""
    prof = profile if profile is not None else analyze_repository(repo_root)
    parts: list[str] = []
    if prof.technologies:
        parts.append("## Project Profile")
        parts.append("Technologies: " + ", ".join(prof.technologies))
        if prof.suggested_roles:
            parts.append("Suggested roles: " + ", ".join(prof.suggested_roles))
    if prof.instructions.get("AGENTS.md"):
        parts.append("## Repository Instructions (AGENTS.md)\n" + prof.instructions["AGENTS.md"])
    return "\n".join(parts) + ("\n" if parts else "")
