"""Core agent definitions and constants for MultiAgentCoding.

Contains the canonical agent roster, tab definitions, status/model/mode
constants, and persona mappings. No UI or rendering dependencies.
"""

from __future__ import annotations

from pathlib import Path

# Workspace root = the directory the launcher was launched from (so agents
# target whatever folder the terminal is started in), not the script dir.
PROJECT_ROOT = Path.cwd()

# (tag, display name, opencode agent name) — order matches opencode.json agents.
AGENTS: list[tuple[str, str, str]] = [
    ("m1", "Matthew", "matthew"),
    ("m2", "Alex", "alex"),
    ("m3", "Sarah", "sarah"),
    ("m4", "David", "david"),
    ("m5", "Elena", "elena"),
    ("m6", "Max", "max"),
    ("m7", "Chloe", "chloe"),
]

# Tab bar order: the unified MASTER tab (all agents) + one tab per agent.
TABS: list[tuple[str, str, str | None]] = [("master", "Master", None)] + [
    (tag, name, agent) for tag, name, agent in AGENTS
]

_AGENT_TAGS = tuple(tag for tag, _name, _agent in AGENTS)
DEFAULT_ENABLED_AGENTS = frozenset(_AGENT_TAGS)

# Persisted settings tied to this exact seven-agent roster.
AGENT_ROSTER_VERSION = "2026-08-humanified-v1"

# Hub status values (lowercase, mirroring the removed web layer).
STATUS_IDLE = "idle"
STATUS_THINKING = "thinking"
STATUS_ACTIVE = "active"
STATUS_ERROR = "error"

# Model selector options.
AUTO_MODEL = "Auto (Smart Hybrid Routing)"
MODEL_OPTIONS: list[str] = [
    AUTO_MODEL,
    "opencode/deepseek-v4-flash-free",
    "opencode/ling-3.0-tiny-free",
    "opencode/big-pickle",
    "ollama/qwen2.5-coder:7b",
    "mulerouter/gpt-5.5",
    "mulerouter/gpt-5.4-mini",
    "mulerouter/qwen3-max",
    "mulerouter/qwen3.7-max",
]

# Mode selector options.
AUTO_MODE = "Auto (Default)"
M7_AUDIT_MODE = "documentation-audit"
IMMUTABLE_TAGS: set[str] = {"m7"}

# Standard agent role modes shared across models.
_ARCHITECT_MODES = ["architect", "analyze", "plan", "matthew"]
_BACKEND_MODES = ["backend", "api", "build", "alex"]
_FRONTEND_MODES = ["frontend", "tui", "sarah"]
_QA_MODES = ["qa", "test", "tester", "david"]
_SECURITY_MODES = ["security", "review", "reviewer", "elena"]
_DEVOPS_MODES = ["devops", "automation", "max"]
_DOCS_MODES = ["docs", "documentation", "chloe"]
_COMPACT_MODES = ["compact", "compaction"]

# User-facing operational modes resolve to configured OpenCode agent keys.
MODE_TO_AGENT: dict[str, str] = {
    "architect": "matthew", "analyze": "matthew", "plan": "matthew", "matthew": "matthew",
    "backend": "alex", "api": "alex", "build": "alex", "alex": "alex",
    "frontend": "sarah", "tui": "sarah", "sarah": "sarah",
    "qa": "david", "test": "david", "tester": "david", "david": "david",
    "security": "elena", "review": "elena", "reviewer": "elena", "elena": "elena",
    "devops": "max", "automation": "max", "max": "max",
    "docs": "chloe", "documentation": "chloe", "chloe": "chloe",
    "compact": "chloe", "compaction": "chloe",
    M7_AUDIT_MODE: "chloe",
}

# Dynamic tab identity metadata.
_AGENT_PERSONAS: dict[str, tuple[str, str]] = {
    "matthew": ("Matthew", "Architect"),
    "alex": ("Alex", "Builder"),
    "sarah": ("Sarah", "Frontend"),
    "david": ("David", "QA"),
    "elena": ("Elena", "Security"),
    "max": ("Max", "DevOps"),
    "chloe": ("Chloe", "Documentation"),
}

ALL_OPERATIONAL_MODES: list[str] = [
    *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
    *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES,
]

MODE_OPTIONS_BY_MODEL: dict[str, list[str]] = {
    AUTO_MODEL: [AUTO_MODE, *ALL_OPERATIONAL_MODES],
    "opencode/deepseek-v4-flash-free": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES,
        *_QA_MODES, *_SECURITY_MODES, *_DEVOPS_MODES,
    ],
    "opencode/big-pickle": [
        *_QA_MODES, *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES,
        *_DEVOPS_MODES, *_SECURITY_MODES, *_DOCS_MODES,
    ],
    "opencode/ling-3.0-tiny-free": [
        M7_AUDIT_MODE, *_SECURITY_MODES, *_DOCS_MODES, *_COMPACT_MODES,
    ],
    "ollama/qwen2.5-coder:7b": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
        *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES,
    ],
    "mulerouter/gpt-5.5": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
        *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES,
    ],
    "mulerouter/gpt-5.4-mini": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
        *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES, *_COMPACT_MODES,
    ],
    "mulerouter/qwen3-max": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
        *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES,
    ],
    "mulerouter/qwen3.7-max": [
        *_ARCHITECT_MODES, *_BACKEND_MODES, *_FRONTEND_MODES, *_QA_MODES,
        *_SECURITY_MODES, *_DEVOPS_MODES, *_DOCS_MODES,
    ],
}
