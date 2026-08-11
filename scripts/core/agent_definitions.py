"""Backward-compatible agent definitions facade.

The canonical agent definitions now live in ``scripts/core/agents/`` — one
module per agent (``matthew.py`` .. ``chloe.py``, ``master.py``) plus the
``registry`` that derives the shared roster and routing matrices. This module
re-exports the full legacy surface so existing imports keep working unchanged.
"""

from __future__ import annotations

from .agents import (  # noqa: F401
    AGENT_ROSTER_VERSION,
    AGENT_SPECS,
    AGENTS,
    ALL_OPERATIONAL_MODES,
    ARCHITECT_MODES,
    ARCHIVIST_MODE,
    AUTO_MODE,
    AUTO_MODEL,
    BACKEND_MODES,
    CHLOE,
    DEFAULT_ENABLED_AGENTS,
    DEVOPS_MODES,
    DOCS_MODES,
    FRONTEND_MODES,
    M7_AUDIT_MODE,
    MASTER_SPEC,
    MODELS_BY_AGENT,
    MODEL_OPTIONS,
    MODE_OPTIONS_BY_MODEL,
    MODE_TO_AGENT,
    PROJECT_ROOT,
    QA_MODES,
    ROLE_DESCRIPTIONS,
    SECURITY_MODES,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
    TABS,
    _AGENT_PERSONAS,
    _AGENT_TAGS,
)
