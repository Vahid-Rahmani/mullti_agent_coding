"""Agent definitions package — one module per agent, plus the registry.

Each specialized agent (M1..M7) and the master coordinator has its own
``SPEC: AgentSpec`` module (``matthew.py``, ``alex.py``, ... ``chloe.py``,
``master.py``), so every agent can be configured, tested, and modified
independently. The ``registry`` module derives the shared roster, routing,
and mode matrices from those specs.
"""

from __future__ import annotations

from .base import AgentSpec
from .constants import (
    AUTO_MODE,
    AUTO_MODEL,
    MODEL_OPTIONS,
    PROJECT_ROOT,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
)
from .chloe import (
    ARCHIVIST_MODE,
    COMPACT_MODES,
    M7_AUDIT_MODE,
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
    AGENT_ROSTER_VERSION,
    AGENTS,
    ALL_OPERATIONAL_MODES,
    ARCHITECT_MODES,
    BACKEND_MODES,
    DEFAULT_ENABLED_AGENTS,
    DEVOPS_MODES,
    DOCS_MODES,
    FRONTEND_MODES,
    IMMUTABLE_TAGS,
    MASTER_SPEC,
    MODELS_BY_AGENT,
    MODE_OPTIONS_BY_MODEL,
    MODE_TO_AGENT,
    QA_MODES,
    ROLE_DESCRIPTIONS,
    SECURITY_MODES,
    TABS,
    _AGENT_PERSONAS,
    _AGENT_TAGS,
)

__all__ = [
    "AgentSpec",
    "AUTO_MODE",
    "AUTO_MODEL",
    "MODEL_OPTIONS",
    "PROJECT_ROOT",
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_IDLE",
    "STATUS_THINKING",
    "ARCHIVIST_MODE",
    "COMPACT_MODES",
    "M7_AUDIT_MODE",
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
    "AGENT_ROSTER_VERSION",
    "AGENTS",
    "ALL_OPERATIONAL_MODES",
    "ARCHITECT_MODES",
    "BACKEND_MODES",
    "DEFAULT_ENABLED_AGENTS",
    "DEVOPS_MODES",
    "DOCS_MODES",
    "FRONTEND_MODES",
    "IMMUTABLE_TAGS",
    "MASTER_SPEC",
    "MODELS_BY_AGENT",
    "MODE_OPTIONS_BY_MODEL",
    "MODE_TO_AGENT",
    "QA_MODES",
    "ROLE_DESCRIPTIONS",
    "SECURITY_MODES",
    "TABS",
    "_AGENT_PERSONAS",
    "_AGENT_TAGS",
]
