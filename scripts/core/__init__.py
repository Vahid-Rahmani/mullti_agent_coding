"""Core package — multi-agent execution engine, state, and logic.

No UI/rendering dependencies. Import from here to access the agent definitions,
execution hub, state tracker, command parser, intent classifier, and
self-evolve bridge.
"""

from .agents import (  # noqa: F401
    AGENT_ROSTER_VERSION,
    AGENT_SPECS,
    AGENTS,
    ALL_OPERATIONAL_MODES,
    ARCHIVIST_MODE,
    AUTO_MODE,
    AUTO_MODEL,
    DEFAULT_ENABLED_AGENTS,
    M7_AUDIT_MODE,
    MASTER_SPEC,
    MODEL_OPTIONS,
    MODE_OPTIONS_BY_MODEL,
    MODE_TO_AGENT,
    PROJECT_ROOT,
    ROLE_DESCRIPTIONS,
    STATUS_ACTIVE,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_THINKING,
    TABS,
)
from .command_parser import (
    _swarm_state,
    build_help_text,
    parse_command,
)
# NOTE: the Analyzer Core (scripts/core/analyzer.py) is intentionally NOT
# imported here — eager import would make `python -m scripts.core.analyzer`
# re-execute the module (runpy double-import warning). It is importable as
# `scripts.core.analyzer` and loaded lazily by run_hub.
from .intent_classifier import (
    INTENT_CASUAL,
    INTENT_GREETING,
    INTENT_QUESTION,
    INTENT_TASK,
    _format_proposals,
    classify_intent,
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
    _agent_tab_identity,
    _build_run_command,
    _opencode_command,
    _sanitize_prompt,
    _strip_ansi,
    build_overrides_table,
    prune_prompt,
)
from .self_evolve_bridge import (
    SELF_EVOLVE_ENGINE,
    run_self_evolve,
)
from .config import (
    SessionConfig,
    TypographyConfig,
)
from .state_tracker import (
    STATE,
)
