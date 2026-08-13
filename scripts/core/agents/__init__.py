"""Agent definitions package — one module per agent, plus the registry.

Each agent (M1..M7) and the master coordinator has its own
``SPEC: AgentSpec`` module (``matthew.py``, ``alex.py``, ... ``chloe.py``,
``master.py``), so every agent can be configured, tested, and modified
independently. The ``registry`` module derives the shared roster from those
specs.

Agent contract: agents are plain — **identity only** (tag/name/agent key).
Models, roles, and providers are runtime concerns resolved from
``opencode.json`` / ``roles.json``, never from a spec module.
"""

from __future__ import annotations

from .base import AgentSpec
from .constants import (
    PROJECT_ROOT,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
)
from .matthew import SPEC as MATTHEW
from .alex import SPEC as ALEX
from .sarah import SPEC as SARAH
from .david import SPEC as DAVID
from .elena import SPEC as ELENA
from .max import SPEC as MAX
from .chloe import SPEC as CHLOE
from .master import SPEC as MASTER
from .registry import (
    AGENT_SPECS,
    AGENT_SPEC_BY_AGENT,
    AGENT_SPEC_BY_TAG,
    AGENTS,
    DEFAULT_ENABLED_AGENTS,
    MASTER_SPEC,
    TABS,
    _AGENT_TAGS,
)

__all__ = [
    "AgentSpec",
    "PROJECT_ROOT",
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_IDLE",
    "STATUS_THINKING",
    "MATTHEW",
    "ALEX",
    "SARAH",
    "DAVID",
    "ELENA",
    "MAX",
    "CHLOE",
    "MASTER",
    "AGENT_SPECS",
    "AGENT_SPEC_BY_AGENT",
    "AGENT_SPEC_BY_TAG",
    "AGENTS",
    "DEFAULT_ENABLED_AGENTS",
    "MASTER_SPEC",
    "TABS",
    "_AGENT_TAGS",
]
