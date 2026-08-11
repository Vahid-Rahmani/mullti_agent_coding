"""Shared non-agent constants for the agents package.

Status values and the workspace root are infrastructure constants used across
the whole control plane; they are kept here so every agent module stays
declarative and lean.
"""

from __future__ import annotations

from pathlib import Path

# Workspace root = the directory the launcher was launched from (so agents
# target whatever folder the terminal is started in), not the script dir.
PROJECT_ROOT = Path.cwd()

# Hub status values.
STATUS_IDLE = "idle"
STATUS_THINKING = "thinking"
STATUS_ACTIVE = "active"
STATUS_ERROR = "error"
