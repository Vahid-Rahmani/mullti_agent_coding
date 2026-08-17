"""Core package — multi-agent execution engine, state, and logic.

No UI/rendering dependencies. Import from here to access the agent definitions,
execution hub, state tracker, and command parser.

Agent contract: agents are plain (identity only), dispatch is plain, and
models/roles are runtime concerns (opencode.json / roles.json).
"""

from .agents import (
    AGENT_SPECS,
    AGENTS,
    DEFAULT_ENABLED_AGENTS,
    MASTER_SPEC,
    PROJECT_ROOT,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
    TABS,
)
from .command_parser import (
    build_help_text,
    parse_command,
)
from .progress import (
    _PROGRESS_BAR_WIDTH,
    DEFAULT_PROGRESS_WEIGHTS,
    TOKEN_CONTEXT_WINDOW,
    WORKING_LABEL,
    _estimate_token_percent,
    _weighted_progress,
)
from .run_hub import (
    HUB,
    _build_run_command,
    _opencode_command,
    _sanitize_prompt,
    _strip_ansi,
    prune_prompt,
)
from .state_tracker import (
    STATE,
)

__all__ = [
    "AGENTS",
    "AGENT_SPECS",
    "DEFAULT_ENABLED_AGENTS",
    "DEFAULT_PROGRESS_WEIGHTS",
    "HUB",
    "MASTER_SPEC",
    "PROJECT_ROOT",
    "STATE",
    "STATUS_ACTIVE",
    "STATUS_ERROR",
    "STATUS_IDLE",
    "STATUS_THINKING",
    "TABS",
    "TOKEN_CONTEXT_WINDOW",
    "WORKING_LABEL",
    "_PROGRESS_BAR_WIDTH",
    "_build_run_command",
    "_estimate_token_percent",
    "_opencode_command",
    "_sanitize_prompt",
    "_strip_ansi",
    "_weighted_progress",
    "build_help_text",
    "parse_command",
    "prune_prompt",
]
