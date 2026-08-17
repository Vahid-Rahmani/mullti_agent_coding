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

from .alex import SPEC as ALEX
from .base import AgentSpec
from .chloe import SPEC as CHLOE
from .constants import (
    PROJECT_ROOT,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
)
from .david import SPEC as DAVID
from .elena import SPEC as ELENA
from .master import SPEC as MASTER
from .matthew import SPEC as MATTHEW
from .max import SPEC as MAX
from .registry import (
    _AGENT_TAGS,
    AGENT_SPEC_BY_AGENT,
    AGENT_SPEC_BY_TAG,
    AGENT_SPECS,
    AGENTS,
    DEFAULT_ENABLED_AGENTS,
    MASTER_SPEC,
    TABS,
)
from .sarah import SPEC as SARAH

__all__ = [
    "AGENTS",
    "AGENT_SPECS",
    "AGENT_SPEC_BY_AGENT",
    "AGENT_SPEC_BY_TAG",
    "ALEX",
    "CHLOE",
    "DAVID",
    "DEFAULT_ENABLED_AGENTS",
    "ELENA",
    "MASTER",
    "MASTER_SPEC",
    "MATTHEW",
    "MAX",
    "PROJECT_ROOT",
    "SARAH",
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_IDLE",
    "STATUS_THINKING",
    "TABS",
    "_AGENT_TAGS",
    "AgentSpec",
]
