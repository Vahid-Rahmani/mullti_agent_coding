"""Analyzer Core — Architecture Enforcer (mandatory pre-dispatch planning).

Deterministic, pure-stdlib implementation of the mandatory three-phase
pipeline that runs *before* any agent dispatch:

1. **Phase 1 — comprehensive data collection & requirements gathering.** The
   prompt is inspected for context, constraints, and file references; missing
   clarity is reported as ``gaps`` so nothing is assumed about paths, UI
   layout, or core logic before coding begins.
2. **Phase 2 — absolute modular separation & decoupling.** No monolithic
   files: every detected concern (backend logic, UI view, tests, security,
   devops, documentation, architecture) becomes its own module with its own
   suggested file path, with clear UI-vs-state boundaries.
3. **Phase 3 — granular agent responsibility assignment.** Exactly one
   structure/module/component is assigned to each specialized sub-agent via
   the canonical mode routing (``MODE_TO_AGENT``), so each agent owns exactly
   one deliverable and can work in parallel, isolated execution. The module
   map is additionally dispatched to the Architectural Obsidian Archivist
   (M7) for persistent ``docs/architecture/`` mapping.

The analyzer never talks to a model: it is a host-side planner that the
``RunHub`` runs on every dispatch (see ``scripts/core/run_hub.py``). Prompts
with no structural signal (greetings, casual chat) yield ``applicable=False``
and are dispatched untouched.

Usage (CLI):
    python -m scripts.core.analyzer "<prompt>" [--workspace PATH] [--json]
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Make the repo root importable so this works both as
# ``python -m scripts.core.analyzer`` (cwd on sys.path) and when executed
# directly as a script from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .agents import MODE_TO_AGENT, PROJECT_ROOT  # noqa: E402

# --------------------------------------------------------------------------- constants

# Category -> routing mode -> agent key. Derived from the canonical routing
# matrix so the analyzer always assigns through the same channels the UI uses.
_CATEGORY_TO_MODE: dict[str, str] = {
    "architecture": "architect",
    "backend": "backend",
    "frontend": "frontend",
    "qa": "qa",
    "security": "security",
    "devops": "devops",
    "documentation": "docs",
}
CATEGORY_TO_AGENT: dict[str, str] = {
    category: MODE_TO_AGENT[mode] for category, mode in _CATEGORY_TO_MODE.items()
}

# Phase 2 — suggested module paths per concern (decoupled by default; an
# explicit path in the prompt overrides the suggestion).
_CATEGORY_PATH: dict[str, str] = {
    "architecture": "docs/architecture/{slug}.md",
    "backend": "core/{slug}.py",
    "frontend": "ui/{slug}_view.py",
    "qa": "test/tests/test_{slug}.py",
    "security": "docs/security/{slug}.md",
    "devops": "scripts/{slug}.py",
    "documentation": "docs/{slug}.md",
}

# Concern detection — one keyword hit marks the concern as active.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "architecture": (
        "architect", "architecture", "schema", "routing", "blueprint", "refactor",
        "design", "structure", "flow", "map", "module", "component", "interface",
        "contract", "milestone", "decision", "plan",
    ),
    "backend": (
        "backend", "api", "endpoint", "auth", "login", "database", "server",
        "logic", "state", "model", "data", "storage", "algorithm", "function",
        "pipeline", "integration",
    ),
    "frontend": (
        "frontend", "ui", "ux", "view", "screen", "layout", "render", "theme",
        "widget", "page", "terminal", "cli", "modal", "keyboard", "style",
    ),
    "qa": (
        "test", "tests", "testing", "unittest", "pytest", "coverage",
        "regression", "assertion", "debug", "bug",
    ),
    "security": (
        "security", "secret", "audit", "permission", "encrypt", "vulnerab",
        "sanitize", "validate", "privacy",
    ),
    "devops": (
        "deploy", "devops", "launcher", "worker", "ci", "build", "automation",
        "powershell", "bash", "docker", "environment", "stability",
    ),
    "documentation": (
        "docs", "documentation", "readme", "changelog", "obsidian", "architecture note",
        "prompt log", "roadmap",
    ),
}

# Concern detection, word-boundary anchored. Short tokens like "ui" or "api"
# must never fire inside unrelated words ("bUild", "rapid", "capital"), while
# plurals and derived forms ("APIs", "tests", "mapping") still match via the
# ``\b`` prefix anchor. A few keywords additionally require a trailing
# boundary so they never fire inside longer words at all ("ci" in "city").
_EXACT_WORD_KEYWORDS = frozenset({"ci"})

_CATEGORY_PATTERNS: dict[str, "re.Pattern[str]"] = {
    category: re.compile(
        "|".join(
            r"\b" + re.escape(keyword) + (r"\b" if keyword in _EXACT_WORD_KEYWORDS else "")
            for keyword in keywords
        ),
        re.IGNORECASE,
    )
    for category, keywords in _CATEGORY_KEYWORDS.items()
}

# Explicit file-like references (Phase 1: never assume paths). The colon is
# included so Windows drive paths ("C:/...") survive intact instead of being
# truncated to "/...".
_PATH_TOKEN_RE = re.compile(r"[\w./\\:-]+\.[A-Za-z0-9]{1,6}")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Version tokens ("3.10", "v2.0", "1.18.15") look like paths but carry no
# file information — never treat them as explicit references. End-anchored so
# real digit-prefixed files ("2.5_api.py") are still recognized as paths.
_VERSION_TOKEN_RE = re.compile(r"^v?\d+(\.\d+)+$")
# URLs ("https://.../file.py") are references, but not workspace files.
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

# Words too generic to make a good module slug.
_STOPWORDS = frozenset(
    "a an the and or but for with without in on at to of from by via as into "
    "add adda new please fix build make create update change implement the "
    "this that these those it its my your our we us i you they them code app "
    "system feature task prompt".split()
)

# --------------------------------------------------------------------------- data model


@dataclass
class Module:
    """One decoupled component, owned by exactly one agent (Phase 3)."""

    component: str      # e.g. "authentication"
    category: str       # e.g. "backend"
    agent: str          # e.g. "alex"
    path: str           # suggested file path (no assumptions — prompt wins)
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "component": self.component,
            "category": self.category,
            "agent": self.agent,
            "path": self.path,
            "notes": self.notes,
        }


@dataclass
class MasterPlan:
    """The Analyzer Core output for one prompt."""

    prompt: str
    applicable: bool = False
    gaps: list[str] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)

    @property
    def agents(self) -> list[str]:
        """Agents assigned, in roster order (one component per agent)."""
        seen: set[str] = set()
        ordered: list[str] = []
        for module in self.modules:
            if module.agent not in seen:
                seen.add(module.agent)
                ordered.append(module.agent)
        return ordered

    def summary_line(self) -> str:
        if not self.applicable:
            return "[ANALYZER] no modular breakdown required (no structural signal)"
        return (
            f"[ANALYZER] master plan: {len(self.modules)} module(s) "
            f"-> {', '.join(self.agents)}"
        )

    def to_text(self) -> str:
        """Render the sequential, phase-structured plan for agent dispatch."""
        if not self.applicable:
            return "[MASTER PLAN — Analyzer Core]\nNo modular breakdown required (no structural signal)."
        # ASCII-only separators: the plan is printed to Windows consoles
        # (cp1252) and injected into agent prompts, so no box-drawing glyphs.
        lines = [
            "=== MASTER PLAN — Analyzer Core (mandatory, pre-dispatch) ===",
            "PHASE 1 · REQUIREMENTS GATHERING (no assumptions about paths/UI/logic)",
        ]
        preview = " ".join(self.prompt.split())[:90]
        lines.append(f"  · context: {preview}{'…' if len(self.prompt) > 90 else ''}")
        if self.gaps:
            lines.append("  · gaps (resolve before implementation):")
            lines += [f"      - {gap}" for gap in self.gaps]
        else:
            lines.append("  · gaps: none — requirements are concrete")
        lines.append("PHASE 2 · MODULAR DECOUPLING (no monolithic files)")
        for module in self.modules:
            lines.append(f"  · {module.category:<13} {module.path}")
        lines.append("PHASE 3 · GRANULAR ASSIGNMENT (exactly one component per agent)")
        for module in self.modules:
            lines.append(f"  · {module.agent:<9} -> {module.category}: {module.path}")
        lines.append(
            "PHASE 4 · ARCHIVIST\n  · module map dispatched to the Obsidian Archivist (M7) "
            "for persistent docs/architecture/ mapping"
        )
        return "\n".join(lines)

    def archivist_entries(self) -> list[str]:
        """Architecture-mapping lines handed to M7 for persistent storage."""
        return [
            f"module {module.component} -> {module.agent} ({module.path})"
            for module in self.modules
        ]

    def as_dict(self) -> dict:
        return {
            "applicable": self.applicable,
            "gaps": list(self.gaps),
            "modules": [module.as_dict() for module in self.modules],
        }


# --------------------------------------------------------------------------- Phase 1: requirements


def _explicit_paths(prompt: str) -> list[str]:
    """File-like references in the prompt (backticks first, then bare tokens).

    Version tokens ("3.10", "v2.0") are excluded: they match the path shape
    but reference nothing on disk.
    """
    paths = _BACKTICK_RE.findall(prompt)
    paths += [m.group(0) for m in _PATH_TOKEN_RE.finditer(prompt)]
    unique: list[str] = []
    for path in paths:
        if path in unique or _VERSION_TOKEN_RE.match(path) or _URL_RE.match(path):
            continue
        unique.append(path)
    return unique


def _slug(prompt: str, explicit_paths: list[str]) -> str:
    """A short, meaningful identifier for module paths."""
    if explicit_paths:
        base = Path(explicit_paths[0].replace("\\", "/")).stem
        if base and base not in _STOPWORDS:
            return re.sub(r"[^A-Za-z0-9_-]", "_", base.lower())
    words = [
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", prompt.lower())
        if w not in _STOPWORDS
    ]
    return "_".join(words[:3]) or "feature"


def _gaps(prompt: str, paths: list[str], workspace: Path | None = None) -> list[str]:
    """Phase 1 — report missing context instead of assuming it.

    ``workspace`` (when given) grounds the path checks: an absolute path
    escapes the workspace and a missing workspace directory both get flagged
    so the dispatch never runs against an assumed layout.
    """
    gaps: list[str] = []
    if not paths:
        gaps.append("no explicit file/module named — force a component breakdown before implementation")
    if len(prompt.strip()) < 24:
        gaps.append("prompt is terse — expand scope, constraints, and acceptance criteria")
    if "test" not in prompt.lower():
        gaps.append("no test strategy mentioned — David (QA) will propose coverage")
    if any(_is_absolute_ref(path) for path in paths):
        gaps.append("an explicit path is absolute — prefer workspace-relative references")
    if workspace is not None:
        ws = Path(workspace)
        if not ws.is_dir():
            gaps.append(f"workspace '{ws}' does not exist — verify the working directory")
    return gaps


def _is_absolute_ref(path: str) -> bool:
    """True for POSIX or Windows-drive absolute references (C:\\..., /...)."""
    return bool(
        re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith(("/", "\\"))
    )


# --------------------------------------------------------------------------- Phase 2 + 3


def _detect_categories(prompt: str) -> list[str]:
    """Phase 2 — the concerns present in the prompt, in roster order.

    Uses word-boundary-anchored patterns: "api" matches "APIs" but not
    "rapid"; "ui" matches a standalone "ui" but not "build".
    """
    detected = [
        category for category, pattern in _CATEGORY_PATTERNS.items()
        if pattern.search(prompt)
    ]
    # Keep the deterministic order of the category table (roster-aligned).
    return [category for category in CATEGORY_TO_AGENT if category in detected]


def build_master_plan(prompt: str, workspace: Path | None = None) -> MasterPlan:
    """Run the full Analyzer Core pipeline for one prompt.

    Returns a ``MasterPlan``; ``applicable`` is ``False`` for conversational
    prompts that carry no structural signal, in which case dispatch is
    unchanged.
    """
    prompt = (prompt or "").strip()
    plan = MasterPlan(prompt=prompt)

    explicit_paths = _explicit_paths(prompt)
    categories = _detect_categories(prompt)
    if not categories:
        # Conversational prompt: nothing to plan, nothing to gather.
        return plan  # applicable stays False

    plan.applicable = True
    slug = _slug(prompt, explicit_paths)

    # Phase 1
    plan.gaps = _gaps(prompt, explicit_paths, workspace)

    # Phase 2 + 3 — one module per concern, each owned by exactly one agent.
    # An explicit path in the prompt is honored once (for the first concern)
    # so every other module still gets its own decoupled suggested path.
    for index, category in enumerate(categories, start=1):
        agent = CATEGORY_TO_AGENT[category]
        component = _component_name(category, slug)
        path = explicit_paths[0] if explicit_paths and index == 1 else ""
        if not path:
            path = _CATEGORY_PATH[category].format(slug=slug)
        notes = _module_note(category, agent, slug, explicit_paths)
        plan.modules.append(
            Module(component=component, category=category, agent=agent, path=path, notes=notes)
        )
    return plan


def _component_name(category: str, slug: str) -> str:
    """Human-readable component label with category noise removed.

    ``slug`` can be made entirely of category keywords ("login backend api"
    -> slug ``login_backend_api``), so the category's own keywords are
    stripped first and the first remaining word names the feature. When the
    prompt named only the concern itself ("implement backend" -> slug
    ``backend``), the slug alone is the label — never "backend backend".
    If the first-word fallback merely repeats the category name
    ("security_audit" -> "security"), the category word is dropped instead.
    """
    words = [w for w in slug.split("_") if w not in _CATEGORY_KEYWORDS[category]]
    if not words:
        if len(slug.split("_")) == 1:
            return slug  # e.g. "implement backend" -> "backend"
        words = slug.split("_")[:1]
    feature = "_".join(words)
    if feature == category:
        rest = [w for w in slug.split("_") if w != category]
        if not rest:
            return category
        feature = "_".join(rest)
    if category == "architecture":
        return f"{feature} architecture"
    if category == "qa":
        return f"{feature} test suite"
    return f"{feature} {category}"


def _module_note(category: str, agent: str, slug: str, explicit_paths: list[str]) -> str:
    """Phase 3 note — one isolated responsibility, no cross-module edits."""
    if explicit_paths:
        return f"sole owner of {explicit_paths[0]} (isolated edit)"
    return f"sole owner of the {slug} {category} module (no monolithic edits)"


# --------------------------------------------------------------------------- CLI


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="*", help="the raw user prompt to analyze")
    parser.add_argument("--workspace", default=str(PROJECT_ROOT), help="active workspace (for context)")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = parser.parse_args(argv)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("error: a prompt is required", file=sys.stderr)
        return 2

    plan = build_master_plan(prompt, workspace=Path(args.workspace))
    if args.json:
        print(json.dumps({"prompt": plan.prompt, **plan.as_dict()}, indent=2))
    else:
        print(plan.to_text())
        if plan.applicable and plan.gaps:
            print("\nREQUIREMENTS GAPS (Phase 1):")
            for gap in plan.gaps:
                print(f"  - {gap}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
