#!/usr/bin/env python3
"""ZOVA — MultiAgentCoding Retro Terminal (entry point).

Thin re-export shim that preserves backward compatibility while the actual
implementation lives in ``scripts/core/`` and ``scripts/ui/``.

Usage:
    python scripts/terminal_app.py [--workspace <dir>] [--smoke]
"""

from __future__ import annotations

import subprocess
import sys
import threading  # noqa: F401 — re-exported for mock patching in tests
import time
from pathlib import Path

# Ensure the project root (parent of scripts/) is on sys.path so the
# `scripts.core.*` / `scripts.ui.*` package imports resolve regardless of
# how this entry point is invoked. Running `python scripts/terminal_app.py`
# puts the *script* directory (scripts/) on sys.path, not the repo root,
# so `import scripts.core` would otherwise fail with ModuleNotFoundError.
# scripts/ itself stays on the path for top-level legacy modules
# (agent_logger, obsidian_auditor, prompt_logger, ...).
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
for _path in (_PROJECT_ROOT, _SCRIPT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ── Re-export from core ──────────────────────────────────────────────
from scripts.core.agents import (  # noqa: F401, E402
    AGENTS, AGENT_ROSTER_VERSION, ALL_OPERATIONAL_MODES, ARCHIVIST_MODE,
    AUTO_MODE, AUTO_MODEL, DEFAULT_ENABLED_AGENTS,
    M7_AUDIT_MODE, MODEL_OPTIONS, MODE_OPTIONS_BY_MODEL, MODE_TO_AGENT,
    PROJECT_ROOT, STATUS_ACTIVE, STATUS_ERROR, STATUS_IDLE,
    STATUS_THINKING, TABS,
)
# Backward-compatible alias for legacy callers that use MODE_OPTIONS.
MODE_OPTIONS = MODEL_OPTIONS

from scripts.core.command_parser import (  # noqa: F401, E402
    _swarm_state, build_help_text, parse_command,
)
from scripts.core.intent_classifier import (  # noqa: F401, E402
    INTENT_CASUAL, INTENT_GREETING, INTENT_QUESTION, INTENT_TASK,
    _format_proposals, classify_intent,
)
from scripts.core.progress import (  # noqa: F401, E402
    DEFAULT_PROGRESS_WEIGHTS, TOKEN_CONTEXT_WINDOW, WORKING_LABEL,
    _estimate_token_percent, _weighted_progress, _PROGRESS_BAR_WIDTH,
)
from scripts.core.run_hub import (  # noqa: F401, E402
    HUB, RunHub,
    _agent_tab_identity, _build_run_command, _insecure_tls_env,
    _opencode_command, _sanitize_prompt, _strip_ansi, build_overrides_table,
    prune_prompt,
)
from scripts.core.state_tracker import StateTracker, STATE  # noqa: F401, E402
from scripts.core.self_evolve_bridge import (  # noqa: F401, E402
    SELF_EVOLVE_ENGINE, _after_self_evolve_run, _spawn_self_evolve_watcher,
    run_self_evolve,
)

# ── Re-export from UI ────────────────────────────────────────────────
from scripts.ui.palette import (  # noqa: F401, E402
    BANNER, BLACK, CONSOLE_MIN_LINES, CONSOLE_PREFERRED_LINES,
    DIFF_ADD, DIFF_HEADER, DIFF_HUNK, DIFF_REMOVE, GREY,
    GREY_BG, INPUT_MAX_LINES, INPUT_MIN_LINES, NEON, ORANGE, WHITE,
)
from scripts.ui.rendering import (  # noqa: F401, E402
    BLOCK_EXECUTION, BLOCK_THINKING, BLOCK_TODO, RUN_HEADER_PREFIX,
    STATUS_SYMBOL,
    _banner_fragments, _block_states, _classify_block, _console_fragments,
    _content_style, _dashboard_fragments, _dir_line, _loading_bar_fragments,
    _model_bar, _model_bar_fragments, _panel_border, _panel_groups,
    _progress_bar_fragments, _run_header, _tag_style, _working_fragments,
)
from scripts.ui.settings_modal import (  # noqa: F401, E402
    COLOR_COMPONENTS, _DEFAULT_COMPONENT_COLORS, SettingsModal,
)
from scripts.ui.theme import (  # noqa: F401, E402
    Theme, THEMES, get_active, set_active, set_active_theme, available_themes,
)
from scripts.ui.terminal_app import RetroTerminalApp, main  # noqa: F401, E402

if __name__ == "__main__":
    sys.exit(main())
