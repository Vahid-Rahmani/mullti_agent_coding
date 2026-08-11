"""Registry — derives the full agent roster and routing from per-agent specs.

Every roster-level constant the control plane consumed from the old
monolithic ``agent_definitions`` module is rebuilt here from the individual
``AgentSpec`` modules, so a change to one agent propagates everywhere:

  * ``AGENTS`` / ``TABS``  — roster and tab bar order.
  * ``MODE_TO_AGENT``      — operational mode -> OpenCode agent routing.
  * ``_AGENT_PERSONAS``    — tab identity (display name + role badge).
  * ``ROLE_DESCRIPTIONS``  — long-form role text for Obsidian agent logs.

The model capability matrix (``MODE_OPTIONS_BY_MODEL``, ``MODELS_BY_AGENT``)
and the per-agent mode groups live in ``models.py``; they are imported and
re-exported here unchanged so legacy imports keep working.
"""

from __future__ import annotations

from .base import AgentSpec
from .matthew import SPEC as MATTHEW
from .alex import SPEC as ALEX
from .sarah import SPEC as SARAH
from .david import SPEC as DAVID
from .elena import SPEC as ELENA
from .max import SPEC as MAX
from .chloe import SPEC as CHLOE
from .master import SPEC as MASTER
from .models import (
    ALL_OPERATIONAL_MODES,
    ARCHITECT_MODES,
    BACKEND_MODES,
    DEVOPS_MODES,
    DOCS_MODES,
    FRONTEND_MODES,
    MODELS_BY_AGENT,
    MODE_OPTIONS_BY_MODEL,
    QA_MODES,
    SECURITY_MODES,
)

# Roster order matches opencode.json agents (M1..M7).
AGENT_SPECS: tuple[AgentSpec, ...] = (MATTHEW, ALEX, SARAH, DAVID, ELENA, MAX, CHLOE)
MASTER_SPEC: AgentSpec = MASTER

# (tag, display name, opencode agent name) — order matches opencode.json agents.
AGENTS: list[tuple[str, str, str | None]] = [
    (spec.tag, spec.name, spec.agent) for spec in AGENT_SPECS
]

# Tab bar order: the unified MASTER tab (all agents) + one tab per agent.
TABS: list[tuple[str, str, str | None]] = [
    (MASTER.tag, MASTER.name, MASTER.agent), *AGENTS,
]

_AGENT_TAGS = tuple(spec.tag for spec in AGENT_SPECS)
DEFAULT_ENABLED_AGENTS = frozenset(_AGENT_TAGS)

# Persisted settings tied to this exact seven-agent roster.
AGENT_ROSTER_VERSION = "2026-08-humanified-v1"

# Agent tags whose model and mode cannot be changed by the user.
IMMUTABLE_TAGS: set[str] = {spec.tag for spec in AGENT_SPECS if spec.immutable}

# Lookups for runtime code (e.g. resolving a locked agent's pinned model/mode).
AGENT_SPEC_BY_TAG: dict[str, AgentSpec] = {spec.tag: spec for spec in AGENT_SPECS}
AGENT_SPEC_BY_AGENT: dict[str, AgentSpec] = {
    spec.agent: spec for spec in AGENT_SPECS if spec.agent is not None
}

# Dynamic tab identity metadata (persona display name, role badge).
_AGENT_PERSONAS: dict[str, tuple[str, str]] = {
    spec.agent: (spec.persona, spec.role) for spec in AGENT_SPECS if spec.agent
}

# Long-form role descriptions for the Obsidian agent logs.
ROLE_DESCRIPTIONS: dict[str, str] = {
    spec.agent: spec.description for spec in AGENT_SPECS if spec.agent
}

# ------------------------------------------------------------------ mode routing

# User-facing operational modes resolve to configured OpenCode agent keys.
MODE_TO_AGENT: dict[str, str] = {}
for spec in AGENT_SPECS:
    for mode in spec.all_modes:
        MODE_TO_AGENT[mode] = spec.agent  # type: ignore[assignment]
