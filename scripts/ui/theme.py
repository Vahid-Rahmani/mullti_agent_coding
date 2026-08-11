"""UI Theme Manager — theme definitions, active theme tracking, and helpers.

Defines the ``Theme`` dataclass and a registry of named themes that control
colors, padding, border styles, and panel dimensions for the terminal UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    """Immutable theme configuration for the terminal UI."""

    name: str
    display_name: str

    # ── Background & base colors ──────────────────────────────────────
    bg: str                     # global background
    bg_input: str               # input surface background
    fg: str                     # general text / logs
    fg_bright: str              # panel content, borders, controls
    accent: str                 # tab outlines, error symbols
    muted: str                  # dim / spacer text

    # ── Diff / code review colors ─────────────────────────────────────
    diff_add: str               # added lines (green)
    diff_remove: str            # removed lines (red)
    diff_header: str            # diff header (cyan-ish)
    diff_hunk: str              # hunk marker (blue-ish)

    # ── Spacing & layout ──────────────────────────────────────────────
    spacer_height: int          # spacer window height (0 for none)
    banner_rows: int            # banner height (0 to hide)
    panel_inner_pad: int        # inner panel padding (chars each side)
    console_min_lines: int      # min console height
    console_pref_lines: int     # preferred console height
    input_min_lines: int        # min input height
    input_max_lines: int        # max input height
    loading_height: int         # loading bar height (0 to hide)

    # ── Panel border style ────────────────────────────────────────────
    panel_top_left: str = "╭"
    panel_top_right: str = "╮"
    panel_bottom_left: str = "╰"
    panel_bottom_right: str = "╯"
    panel_horizontal: str = "─"
    panel_vertical: str = "│"

    # ── Derived values (computed at init) ─────────────────────────────
    style_dict: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        # Build the CSS-style class dict for prompt_toolkit.
        style = {
            "retro": f"bg:{self.bg} fg:{self.fg}",
            "retro.banner": f"bold bg:{self.bg} fg:{self.fg_bright}",
            "retro.dir": f"bold bg:{self.bg} fg:{self.fg}",
            "retro.dash": f"bg:{self.bg} fg:{self.fg}",
            "retro.progress": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.muted": f"bg:{self.bg} fg:{self.muted}",
            "retro.console": f"bg:{self.bg} fg:{self.fg}",
            "retro.spacer": f"bg:{self.bg}",
            "retro.panel.content": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.panel.thinking": f"bg:{self.bg} fg:{self.fg_bright} italic",
            "retro.panel.todo": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.panel.execution": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.model": f"bold bg:{self.bg} fg:{self.fg_bright}",
            "retro.control": f"bold bg:{self.bg} fg:{self.fg_bright}",
            "retro.menu": f"bold bg:{self.bg} fg:{self.fg_bright}",
            "retro.menu.border": f"bold bg:{self.bg} fg:{self.fg_bright}",
            "retro.menu.item": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.backdrop": f"bg:{self.bg} fg:{self.bg}",
            "retro.box": f"bg:{self.bg} fg:{self.fg_bright}",
            "retro.tab.active": f"bold bg:{self.bg_input} fg:{self.accent}",
            "retro.tab.busy": f"bold bg:{self.bg} fg:{self.accent}",
            "retro.tab.inactive": f"bg:{self.bg} fg:{self.accent}",
            "retro.input": f"bg:{self.bg_input} fg:{self.fg_bright} bold",
            # Diff color classes
            "retro.diff.add": f"bg:{self.bg} fg:{self.diff_add}",
            "retro.diff.remove": f"bg:{self.bg} fg:{self.diff_remove}",
            "retro.diff.header": f"bg:{self.bg} fg:{self.diff_header}",
            "retro.diff.hunk": f"bg:{self.bg} fg:{self.diff_hunk}",
        }
        # Frozen dataclass: use object.__setattr__
        object.__setattr__(self, "style_dict", style)

    # ------------------------------------------------------------------ helpers

    @property
    def is_compact(self) -> bool:
        """True when the theme uses compact spacing."""
        return self.spacer_height == 0

    def panel_top(self, label: str, width: int) -> str:
        """Build a panel top border line like '╭─ THINKING ─────╮'."""
        tl, h, tr = self.panel_top_left, self.panel_horizontal, self.panel_top_right
        prefix = f"{tl}{h} {label} "
        if len(prefix) + 1 > width:
            short = label[:4].upper()
            prefix = f"{tl}{h} {short} "
        if len(prefix) + 1 > width:
            prefix = f"{tl}{h} "
        dashes = max(0, width - len(prefix) - 1)
        line = prefix + h * dashes + tr
        return line[:width]

    def panel_bottom(self, width: int) -> str:
        """Build a panel bottom border line like '╰───────────────╯'."""
        bl, h, br = self.panel_bottom_left, self.panel_horizontal, self.panel_bottom_right
        line = bl + h * max(0, width - 2) + br
        return line[:width]

    def progress_bar_style(self) -> str:
        """Style for the active progress-bar fill."""
        return f"bold {self.fg_bright}"

    def working_active_style(self, distance: int) -> str:
        """Style for the pulsing 'working...' label at a given distance."""
        if distance == 0:
            return f"bold {self.fg_bright}"
        elif distance <= 2:
            return f"bold {self.fg}"
        else:
            return f"bold {self.muted}"


# ══════════════════════════════════════════════════════════════════════
#  Theme Registry
# ══════════════════════════════════════════════════════════════════════

THEMES: dict[str, Theme] = {}


def register(theme: Theme) -> Theme:
    """Register a theme in the global registry."""
    THEMES[theme.name] = theme
    return theme


def get(name: str) -> Theme:
    """Return a registered theme by name, falling back to 'classic'."""
    return THEMES.get(name, THEMES.get("classic", CLASSIC))


# ══════════════════════════════════════════════════════════════════════
#  Classic Theme — matches the original retro palette and spacing
# ══════════════════════════════════════════════════════════════════════

CLASSIC = register(Theme(
    name="classic",
    display_name="Classic (Retro)",

    bg="#0d1117",
    bg_input="#161b22",
    fg="#c9d1d9",
    fg_bright="#ffffff",
    accent="#f85149",
    muted="#6e7681",

    diff_add="#3fb950",
    diff_remove="#f85149",
    diff_header="#58a6ff",
    diff_hunk="#79c0ff",

    spacer_height=1,
    banner_rows=6,
    panel_inner_pad=1,
    console_min_lines=5,
    console_pref_lines=12,
    input_min_lines=3,
    input_max_lines=12,
    loading_height=1,
))


# ══════════════════════════════════════════════════════════════════════
#  OpenCode Theme — compact, bordered panels, terminal diff colors
# ══════════════════════════════════════════════════════════════════════

OPENCODE = register(Theme(
    name="opencode",
    display_name="OpenCode (Compact)",

    # Darker, more terminal-authentic background
    bg="#0a0e14",
    bg_input="#0d1117",
    fg="#c9d1d9",
    fg_bright="#e6edf3",
    accent="#f0883e",           # warm orange accent instead of red
    muted="#484f58",

    # Strict git-terminal diff colors
    diff_add="#3fb950",         # green for additions
    diff_remove="#f85149",      # red for removals
    diff_header="#58a6ff",      # cyan/blue for file headers
    diff_hunk="#79c0ff",        # lighter blue for hunk markers

    # Compact: no spacers, smaller panels, reduced heights
    spacer_height=0,
    banner_rows=0,              # Hide banner in compact mode
    panel_inner_pad=1,
    console_min_lines=3,
    console_pref_lines=8,
    input_min_lines=2,
    input_max_lines=8,
    loading_height=0,           # No separate loading bar; inline in panel

    # Rounded but tighter panel borders
    panel_top_left="╭",
    panel_top_right="╮",
    panel_bottom_left="╰",
    panel_bottom_right="╯",
    panel_horizontal="─",
    panel_vertical="│",
))


# Convenience: current active theme object (mutable for dynamic switching).
# Rendering code should read this at call time, not at import time.
# The object (not just a registered name) is tracked so derived themes
# (e.g. font-size-scaled variants) can be activated too.
_active_theme: Theme = CLASSIC


def get_active() -> Theme:
    """Return the currently active theme object."""
    return _active_theme


def set_active(name: str) -> Theme:
    """Switch the active theme by registered name and return it."""
    global _active_theme
    theme = get(name)
    _active_theme = theme
    return theme


def set_active_theme(theme: Theme) -> Theme:
    """Activate an arbitrary (possibly derived) Theme object."""
    global _active_theme
    _active_theme = theme
    return theme


def available_themes() -> list[str]:
    """Return sorted list of registered theme names."""
    return sorted(THEMES.keys())
