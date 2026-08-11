"""Shared non-agent constants for the agents package.

Status values, model selector options, and default mode labels are
infrastructure constants used across the whole control plane; they are kept
here (not per-agent) so every agent module stays declarative and lean.
"""

from __future__ import annotations

from pathlib import Path

# Workspace root = the directory the launcher was launched from (so agents
# target whatever folder the terminal is started in), not the script dir.
PROJECT_ROOT = Path.cwd()

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

# Mode selector option.
AUTO_MODE = "Auto (Default)"
