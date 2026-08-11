"""UI palette — colors, banner, status symbols, and layout constants.

These are presentation-only constants used by the rendering layer.
No core logic dependencies.
"""

from __future__ import annotations

# ASCII pixel-art "ZOVA" banner (block glyphs).
BANNER = [
    "████████╗ ████████╗ ██╗   ██╗ ████████╗",
    "    ████╝ ██╗   ██╗ ██║   ██║ ██╔═══██╗",
    "   ████╝  ██║   ██║ ██║   ██║ ████████╗",
    "  ████╝   ██║   ██║ ╚██╗ ██╔╝ ██║   ██║",
    " ████╝    ╚██████╔╝  ╚████╔╝  ██║   ██║",
    "╚═══════╝ ╚═══════╝   ╚═══╝   ╚═╝   ╚═╝",
]

# GitHub-inspired ZOVA palette.
BLACK = "#0d1117"      # dark charcoal/slate global background
GREY = "#c9d1d9"       # regular text, logs, and muted status
WHITE = "#ffffff"      # panel content, borders, and bottom controls
ORANGE = "#f85149"     # enclosed agent-tab outlines
NEON = GREY             # compatibility alias; intentionally not green
GREY_BG = "#161b22"    # subtle input surface within the charcoal background
DIFF_ADD = "#3fb950"    # green  — git diff additions
DIFF_REMOVE = "#f85149"  # red    — git diff removals
DIFF_HEADER = "#58a6ff"  # blue   — diff file headers
DIFF_HUNK = "#79c0ff"    # cyan   — diff hunk markers

# Status symbols used in dashboard rendering.
# Import status constants lazily to avoid circular dependencies.
STATUS_SYMBOL: dict[str, tuple[str, str]] = {}
# Will be populated at init time


def _init_status_symbol() -> None:
    """Populate STATUS_SYMBOL using core constants (called at init time)."""
    from ..core.agents import STATUS_IDLE, STATUS_THINKING, STATUS_ACTIVE, STATUS_ERROR

    STATUS_SYMBOL.clear()
    STATUS_SYMBOL.update({
        STATUS_IDLE: ("●", GREY),
        STATUS_THINKING: ("●", GREY),
        STATUS_ACTIVE: ("●", GREY),
        STATUS_ERROR: ("✕", ORANGE),
    })


# Lower panel layout dimensions.
INPUT_MIN_LINES = 3
INPUT_MAX_LINES = 12
CONSOLE_MIN_LINES = 5
CONSOLE_PREFERRED_LINES = 12
