"""Core package — multi-agent execution engine, state, and logic.

No UI/rendering dependencies. Import from here to access the agent definitions,
execution hub, state tracker, and command parser.

Baseline-zero: agents are plain, dispatch is plain, and no external
integrations (Obsidian, analyzer, self-evolve, swarm) exist.
"""

from .agents import (  # noqa: F401
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
    DEFAULT_PROGRESS_WEIGHTS,
    TOKEN_CONTEXT_WINDOW,
    WORKING_LABEL,
    _estimate_token_percent,
    _weighted_progress,
    _PROGRESS_BAR_WIDTH,
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
