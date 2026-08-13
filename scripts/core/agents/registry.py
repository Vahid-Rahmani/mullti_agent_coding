"""Registry — derives the plain agent roster from per-agent specs.

Every roster-level constant the control plane consumed is rebuilt here from
the individual ``AgentSpec`` modules, so a change to one agent propagates
everywhere:

  * ``AGENTS`` / ``TABS``  — roster and tab bar order.

Agent contract: agents carry only identity (tag/name/agent key). Models are a
runtime concern resolved from ``opencode.json`` (see
``scripts.core.opencode_cfg.resolve_model``); there are no operational modes,
personas, role descriptions, or mode routing in the specs.
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

# Lookups for runtime code (resolving each agent's identity).
AGENT_SPEC_BY_TAG: dict[str, AgentSpec] = {spec.tag: spec for spec in AGENT_SPECS}
AGENT_SPEC_BY_AGENT: dict[str, AgentSpec] = {
    spec.agent: spec for spec in AGENT_SPECS if spec.agent is not None
}
