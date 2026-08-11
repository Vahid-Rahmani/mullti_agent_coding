"""UI rendering — console fragments, panels, loading bars, and layout markup.

Rendering functions that produce prompt_toolkit styled fragments or text.
All visual concerns live here — no core execution logic.
"""

from __future__ import annotations

import re
import shutil
import textwrap
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .theme import Theme

from .palette import (
    BANNER, GREY, WHITE, ORANGE, NEON, GREY_BG,
    DIFF_ADD, DIFF_REMOVE, DIFF_HEADER, DIFF_HUNK,
    INPUT_MIN_LINES, INPUT_MAX_LINES, CONSOLE_MIN_LINES, CONSOLE_PREFERRED_LINES,
    _init_status_symbol,
)

from ..core.agents import (
    AGENTS, TABS, AUTO_MODE, AUTO_MODEL, STATUS_IDLE, STATUS_THINKING,
    STATUS_ACTIVE, STATUS_ERROR,
)
from ..core.progress import (
    _estimate_token_percent, _weighted_progress, _PROGRESS_BAR_WIDTH, WORKING_LABEL,
)
from ..core.run_hub import HUB, _sanitize_prompt, _agent_tab_identity

# Ensure status symbols are initialized before any rendering that uses them.
_init_status_symbol()
from .palette import STATUS_SYMBOL  # noqa: E402 — populated by _init_status_symbol

# -------------------------------------------------------------------- banner, dir, tag style


def _tag_style(tag: str) -> str:
    """prompt_toolkit style fragment for a light-grey agent tag prefix."""
    return f"bold {GREY}"


def _banner_fragments(visible: bool = True) -> list[tuple[str, str]]:
    """Banner fragments, or an empty frame after the first submission."""
    if not visible:
        return []
    return [("class:retro.banner", "\n".join(BANNER))]


def _dir_line(workspace: Path) -> str:
    """Directory status indicator line text."""
    return f"▶ DIR: {workspace}"


# -------------------------------------------------------------------- model bar


def _model_bar(
    overrides: dict[str, dict[str, str]],
    agents_filter: list[str] | None,
    current_tab: str = "master",
) -> str:
    """Plain status-bar text for compatibility and command output."""
    return "".join(text for _style, text in _model_bar_fragments(overrides, agents_filter, current_tab))


def _model_bar_fragments(
    overrides: dict[str, dict[str, str]],
    agents_filter: list[str] | None,
    current_tab: str = "master",
    on_control_click=None,
    compact: bool = False,
    ultra_compact: bool = False,
    esc_pending_tag: str | None = None,
    terminal_settings: dict | None = None,
) -> list[tuple]:
    """Render bottom chrome segments, optionally attaching mouse actions.

    ``terminal_settings`` (when provided) appends a read-only LAYOUT/SET
    segment so persisted theme/density/font overrides are visible at a glance.
    """
    model, mode = HUB.resolve(current_tab, overrides)
    target = current_tab if current_tab != "master" else (
        ",".join(agents_filter) if agents_filter else "all"
    )
    running = HUB.running
    if esc_pending_tag and running > 0:
        if esc_pending_tag == "master":
            esc_suffix = " ⚠ ESC: abort ALL"
        else:
            esc_suffix = f" ⚠ ESC: abort {esc_pending_tag.upper()}"
    else:
        esc_suffix = ""
    if ultra_compact:
        model_text = "Auto" if not model or model == AUTO_MODEL else model.split("/")[-1]
        mode_text = "Auto" if not mode or mode == AUTO_MODE else mode
        controls = [
            ("tab", f"T:{current_tab.upper()}"),
            ("model", f"M:{model_text}"),
            ("mode", f"D:{mode_text}"),
            ("target", f"G:{target[:8]}"),
            ("run", f"R:{running}/{len(AGENTS)}{esc_suffix}"),
        ]
    elif compact:
        model_text = "Auto" if not model or model == AUTO_MODEL else model
        mode_text = "Auto" if mode == AUTO_MODE else (mode or AUTO_MODE)
        controls = [
            ("tab", f"TAB {current_tab.upper()}"),
            ("model", f"AI MODEL {model_text}"),
            ("mode", f"MODE {mode_text}"),
            ("target", f"TARGET {target}"),
            ("run", f"RUN {running}/{len(AGENTS)}{esc_suffix}"),
        ]
    else:
        controls = [
            ("tab", f"TAB {current_tab.upper()}"),
            ("model", f"AI MODEL {model or AUTO_MODEL}"),
            ("mode", f"MODE {mode or AUTO_MODE}"),
            ("target", f"TARGET {target}"),
            ("run", f"RUN {running}/{len(AGENTS)}{esc_suffix}"),
        ]
    fragments: list[tuple] = []
    for index, (kind, label) in enumerate(controls):
        if index:
            fragments.append(("class:retro.model", " ▍"))
        handler = None
        if on_control_click is not None and kind in {"tab", "model", "mode", "target"}:
            def click(event, _kind=kind):
                on_control_click(_kind, event)
            handler = click
        style = "class:retro.control" if kind in {"tab", "model", "mode", "target"} else "class:retro.model"
        if kind in {"tab", "model", "mode", "target"}:
            visible = f"⟦ {label} ⟧ "
        else:
            visible = f"{label} "
        if handler is None:
            fragments.append((style, visible))
        else:
            fragments.append((style, visible, handler))
    if terminal_settings is not None:
        theme = str(terminal_settings.get("theme") or "classic")
        density = str(terminal_settings.get("density") or "comfortable")
        font = str(terminal_settings.get("font_size") or "medium")
        fragments.append(("class:retro.model", " ▍"))
        if ultra_compact:
            label = f"SET {theme[:1]}/{density[:1]}/{font[:1]}"
        elif compact:
            label = f"SET {theme}/{density}"
        else:
            label = f"SET {theme}·{density}·{font}"
        fragments.append(("class:retro.model", label + " "))
    return fragments


# -------------------------------------------------------------------- dashboard


def _dashboard_fragments(
    statuses: dict[str, str],
    current_tab: str = "master",
    on_tab_click=None,
    width: int | None = None,
    overrides: dict[str, dict[str, str]] | None = None,
    enabled_agents: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[tuple]:
    """Render MASTER/M1..M7 as visibly bordered tab buttons.

    ``enabled_agents`` (when provided) hides disabled agent tabs; MASTER is
    always shown.
    """
    fragments: list[tuple] = []
    row_width = 0
    for tag, _name_key, _agent in TABS:
        if enabled_agents is not None and tag != "master" and tag not in enabled_agents:
            continue
        status = statuses.get(tag, STATUS_IDLE)
        symbol, _color = STATUS_SYMBOL.get(status, STATUS_SYMBOL[STATUS_IDLE])
        active = tag == current_tab
        # Resolve dynamic persona name+role for this tab
        if tag != "master":
            display_name, role = _agent_tab_identity(tag, overrides or {})
            label = f"{tag.upper()}: {display_name} [{role}]"
        else:
            label = "MASTER"
        cell = f"⟦{symbol} {label}⟧ "
        if width is not None and len(cell.rstrip()) > max(10, width):
            short_label = "MASTER" if tag == "master" else tag.upper()
            cell = f"⟦{symbol} {short_label}⟧ "
        if active:
            style = "class:retro.tab.active"
        else:
            style = "class:retro.tab.inactive"
        if on_tab_click is None:
            fragment = (style, cell)
        else:
            def click(event, _tag=tag):
                on_tab_click(_tag, event)
            fragment = (style, cell, click)
        if width is not None:
            if row_width and row_width + len(cell) > max(10, width):
                fragments.append(("class:retro.dash", "\n"))
                row_width = 0
            row_width += len(cell)
        fragments.append(fragment)
    return fragments


# -------------------------------------------------------------------- progress bars & loading


def _progress_bar_fragments(
    percent: int,
    width: int = _PROGRESS_BAR_WIDTH,
    theme: Theme | None = None,
) -> list[tuple[str, str]]:
    """Render a percentage inside a compact retro progress bar."""
    if theme is None:
        from .theme import get_active
        theme = get_active()
    percent = max(0, min(100, int(percent)))
    label = f" {percent:3d}% "
    slots = max(4, width - len(label) - 2)
    filled = round(slots * percent / 100)
    empty = slots - filled
    style = theme.progress_bar_style()
    return [
        (style, "[" + "█" * filled),
        (style, label),
        ("class:retro.muted", "░" * empty + "]"),
    ]


def _working_fragments(
    now: float | None = None,
    theme: Theme | None = None,
) -> list[tuple[str, str]]:
    """Render a left-to-right pulsing/chasing ``working...`` label."""
    if theme is None:
        from .theme import get_active
        theme = get_active()
    travel = max(1, len(WORKING_LABEL) * 2 - 2)
    phase = int((time.monotonic() if now is None else now) * 10) % travel
    head = phase if phase < len(WORKING_LABEL) else travel - phase
    fragments: list[tuple[str, str]] = []
    for index, char in enumerate(WORKING_LABEL):
        distance = abs(index - head)
        fragments.append((theme.working_active_style(distance), char))
    return fragments


def _loading_bar_fragments(
    statuses: dict[str, str],
    progress: dict[str, int] | None = None,
    token_usage: dict[str, int] | None = None,
    current_tab: str = "master",
    session_tags: set[str] | list[str] | tuple[str, ...] | None = None,
    weights: dict[str, float] | None = None,
    now: float | None = None,
    width: int = 80,
    theme: Theme | None = None,
) -> list[tuple]:
    """Render the single loading bar shown immediately above the prompt."""
    if theme is None:
        from .theme import get_active
        theme = get_active()
    # Compact themes hide the loading bar entirely.
    if theme.loading_height == 0:
        return []
    progress = progress or {}
    token_usage = token_usage or {}
    width = max(24, int(width))
    active_tags = [
        tag for tag, _name, _agent in AGENTS
        if statuses.get(tag, STATUS_IDLE) in (STATUS_THINKING, STATUS_ACTIVE)
    ]
    if current_tab == "master":
        aggregate_tags = session_tags if session_tags is not None else active_tags
        visible_tags = list(aggregate_tags or [])
        active = bool(active_tags)
        percent = _weighted_progress(statuses, progress, visible_tags, weights) if active else 0
        label = "MASTER / ALL AGENTS"
        token_percent = (
            _weighted_progress(statuses, token_usage, visible_tags, weights, terminal_value=0)
            if visible_tags else 0
        )
    else:
        name = next((name for tag, name, _agent in AGENTS if tag == current_tab), current_tab.upper())
        percent = max(0, min(100, int(progress.get(current_tab, 0))))
        active = current_tab in active_tags
        label = f"{current_tab.upper()} {name}"
        token_percent = max(0, min(100, int(token_usage.get(current_tab, 0))))
        if not active:
            percent = 0
            token_percent = 0

    prefix = f" LOADING │ {label} "
    suffix = f" │ Token: {token_percent}% Used"
    working = _working_fragments(now, theme=theme) if active else [("class:retro.muted", "idle")]
    bar_width = max(10, min(_PROGRESS_BAR_WIDTH, width - len(prefix) - len(suffix) - 12))
    fragments: list[tuple] = [("class:retro.progress", prefix)]
    fragments.extend(_progress_bar_fragments(percent, bar_width, theme=theme))
    fragments.append(("class:retro.progress", " "))
    fragments.extend(working)
    fragments.append(("class:retro.progress", suffix))
    return fragments


# -------------------------------------------------------------------- structured panels


RUN_HEADER_PREFIX = "──── RUN "
_RUN_HEADER_MAX_PROMPT = 60


def _run_header(prompt: str, label: str) -> str:
    """Build a compact visible separator for one agent run."""
    display = " ".join(_sanitize_prompt(prompt).split())
    if len(display) > _RUN_HEADER_MAX_PROMPT:
        display = display[:_RUN_HEADER_MAX_PROMPT] + "…"
    return f"{RUN_HEADER_PREFIX}{label}: {display} ────"


BLOCK_THINKING = "thinking"
BLOCK_TODO = "todo"
BLOCK_EXECUTION = "execution"
_BLOCK_LABELS = {
    BLOCK_THINKING: "THINKING",
    BLOCK_TODO: "TODO / TASKS",
    BLOCK_EXECUTION: "EXECUTION / CODE",
}
_BLOCK_PANEL_STYLES = {
    BLOCK_THINKING: f"bold {WHITE}",
    BLOCK_TODO: f"bold {WHITE}",
    BLOCK_EXECUTION: f"bold {WHITE}",
}
_BLOCK_PANEL_WIDTH = 64
_PANEL_MIN_WIDTH = 24
_PANEL_MAX_WIDTH = 96


def _available_columns(fallback: tuple[int, int] = (100, 30)) -> int:
    """Return the active output width without forcing a terminal query."""
    try:
        from prompt_toolkit.application.current import get_app
        return max(1, get_app().output.get_size().columns)
    except Exception:
        try:
            return max(1, shutil.get_terminal_size(fallback).columns)
        except OSError:
            return fallback[0]


def _panel_width(width: int | None = None) -> int:
    """Compute a bounded panel width that fits the current viewport."""
    if width is not None:
        return max(1, min(_PANEL_MAX_WIDTH, width))
    return max(1, min(_PANEL_MAX_WIDTH, _available_columns() - 2))


def _classify_block(text: str, active: str = BLOCK_EXECUTION) -> tuple[str, str]:
    """Classify visible agent output without inferring hidden reasoning."""
    stripped = text.strip()
    upper = stripped.upper()
    if text.startswith("──── RUN "):
        return BLOCK_EXECUTION, BLOCK_EXECUTION

    if upper.startswith(("</THINK", "</THOUGHT", "</REASON")):
        return BLOCK_THINKING, BLOCK_EXECUTION
    if upper.startswith(("<THINK", "THINKING:", "THOUGHT:", "REASONING:")) or upper in {
        "THINKING", "THOUGHTS", "REASONING"
    }:
        return BLOCK_THINKING, BLOCK_THINKING

    todo_heading = upper.startswith((
        "TODO:", "TASK:", "TASKS:", "PLAN:", "CHECKLIST:",
        "## TODO", "## TASK", "## PLAN", "### TODO", "### TASK",
    )) or upper in {"TODO", "TASKS", "PLAN", "CHECKLIST"}
    todo_item = bool(re.match(r"^(?:[-*+]\s+)?\[[ X✓✗~-]\]\s+", stripped, re.IGNORECASE))
    if todo_heading or todo_item:
        return BLOCK_TODO, BLOCK_TODO
    if active == BLOCK_TODO and bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", stripped)):
        return BLOCK_TODO, BLOCK_TODO

    execution = (
        upper.startswith((
            "EXECUTION:", "CODE:", "OUTPUT:", "COMMAND:", "CMD:",
            "FILE:", "FILES:", "CHANGES:", "PATCH:", "DIFF:",
            "IMPLEMENTATION:", "RESULT:", "RUNNING:", "WRITING:",
            "EDITED:", "CREATED:", "UPDATED:", "TEST:", "TESTS:",
        ))
        or stripped.startswith(("```", "diff --", "+++ ", "--- ", "$ ", ">>> "))
        or bool(re.match(r"^(?:M|A|D|R)\s+.+", stripped))
    )
    if execution:
        return BLOCK_EXECUTION, BLOCK_EXECUTION
    if active == BLOCK_THINKING and stripped:
        return BLOCK_THINKING, BLOCK_THINKING
    return BLOCK_EXECUTION, BLOCK_EXECUTION


def _block_states(lines: list[tuple[str, str]]) -> dict[str, str]:
    """Infer each agent's current block state from a history prefix."""
    states: dict[str, str] = {}
    for tag, text in lines:
        _kind, states[tag] = _classify_block(text, states.get(tag, BLOCK_EXECUTION))
    return states


def _panel_groups(
    lines: list[tuple[str, str]],
    initial_states: dict[str, str] | None = None,
) -> list[tuple[str, list[tuple[str, str]]]]:
    """Group adjacent output by agent/category, preserving hidden context."""
    states = dict(initial_states or {})
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    for tag, text in lines:
        if text.startswith(RUN_HEADER_PREFIX):
            states[tag] = BLOCK_EXECUTION
            groups.append((f"{tag}:header", [(tag, text)]))
            continue
        kind, next_state = _classify_block(text, states.get(tag, BLOCK_EXECUTION))
        states[tag] = next_state
        key = f"{tag}:{kind}"
        if groups and groups[-1][0] == key:
            groups[-1][1].append((tag, text))
        else:
            groups.append((key, [(tag, text)]))
    return groups


_DIFF_PATTERNS = [
    (re.compile(r"^\+[^+]"), "diff_add"),                # added lines (at least 1 non-+ char)
    (re.compile(r"^-[^-]"), "diff_remove"),              # removed lines
    (re.compile(r"^diff --git"), "diff_header"),         # diff file header
    (re.compile(r"^[-+]{3}\s"), "diff_header"),          # +++/--- file markers
    (re.compile(r"^@@\s"), "diff_hunk"),                 # hunk markers
    (re.compile(r"^Index:"), "diff_header"),
    (re.compile(r"^(M|A|D|R)\d*\s"), "diff_add"),        # git status: modified/added
]


def _diff_style(text: str) -> str | None:
    """Return a prompt_toolkit style class for diff-colored lines."""
    for pattern, class_name in _DIFF_PATTERNS:
        if pattern.match(text.strip()):
            return f"class:retro.{class_name}"
    return None


_BLOCK_CONTENT_CLASSES = {
    BLOCK_THINKING: "retro.panel.thinking",
    BLOCK_TODO: "retro.panel.todo",
    BLOCK_EXECUTION: "retro.panel.execution",
}


def _content_style(kind: str, text: str) -> str:
    """Granular style class for a console line inside a categorized panel.

    Always carries the shared ``retro.panel.content`` surface plus the
    block-specific class (``retro.panel.execution`` / ``thinking`` / ``todo``)
    so component theme colors apply per stream. Diff lines additionally carry
    their diff class.
    """
    granular = _BLOCK_CONTENT_CLASSES.get(kind, "retro.panel.execution")
    if kind == BLOCK_EXECUTION:
        diff_cls = _diff_style(text)
        if diff_cls is not None:
            return f"class:retro.panel.content {diff_cls}"
    return f"class:retro.panel.content class:{granular}"


_SHORT_BLOCK_LABELS = {BLOCK_THINKING: "THINK", BLOCK_TODO: "TODO", BLOCK_EXECUTION: "EXEC"}


def _panel_border(
    kind: str,
    opening: bool,
    width: int | None = None,
    theme: Theme | None = None,
) -> tuple[str, str]:
    """Return a solid border sized to the current panel viewport."""
    if theme is None:
        from .theme import get_active
        theme = get_active()
    panel_width = _panel_width(width)
    style = f"bold {theme.fg_bright}"
    if opening:
        # Try full label, fall back to short label, then minimal.
        label = _BLOCK_LABELS[kind]
        prefix = f"{theme.panel_top_left}{theme.panel_horizontal} {label} "
        if len(prefix) + 1 > panel_width:
            label = _SHORT_BLOCK_LABELS.get(kind, label[:4].upper())
            prefix = f"{theme.panel_top_left}{theme.panel_horizontal} {label} "
        if len(prefix) + 1 > panel_width:
            prefix = f"{theme.panel_top_left}{theme.panel_horizontal} "
        dashes = max(0, panel_width - len(prefix) - 1)
        line = prefix + theme.panel_horizontal * dashes + theme.panel_top_right
        return style, line[:panel_width] + "\n"
    line = theme.panel_bottom(panel_width)
    return style, line + "\n"


def _console_fragments(
    lines: list[tuple[str, str]],
    prefix: bool = True,
    initial_states: dict[str, str] | None = None,
    width: int | None = None,
    theme: Theme | None = None,
) -> list[tuple[str, str]]:
    """Render all tabs through the same categorized bordered-panel renderer."""
    if theme is None:
        from .theme import get_active
        theme = get_active()
    fragments: list[tuple[str, str]] = []
    for group_key, group in _panel_groups(lines, initial_states):
        tag, kind = group_key.split(":", 1)
        if kind == "header":
            fragments.extend((f"bold {theme.fg_bright}", text + "\n") for _, text in group)
            continue
        if tag == "master":
            for _line_tag, text in group:
                diff_cls = _diff_style(text)
                style = diff_cls or "class:retro.console"
                fragments.append((style, text + "\n"))
            continue

        panel_width = _panel_width(width)
        style, border = _panel_border(kind, True, panel_width, theme=theme)
        fragments.append((style, border))
        pad = theme.panel_inner_pad
        inner_width = max(1, panel_width - 2 - pad * 2)
        for line_tag, text in group:
            prefix_text = f"[{line_tag}] " if prefix and line_tag and line_tag != "master" else ""
            wrapped = textwrap.wrap(
                text,
                width=max(1, inner_width - len(prefix_text)),
                replace_whitespace=False,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            ) or [""]
            for line_index, chunk in enumerate(wrapped):
                visible_prefix = prefix_text if line_index == 0 else " " * len(prefix_text)
                # Granular content style: shared surface + block class + diffs.
                content_style = _content_style(kind, chunk)
                # Left padding + border
                left_pad = " " * pad
                fragments.append((style, f"{theme.panel_vertical}{left_pad}"))
                if visible_prefix:
                    fragments.append((_tag_style(line_tag), visible_prefix))
                fragments.append((content_style, chunk))
                # Right padding
                right_fill = max(0, inner_width - len(visible_prefix) - len(chunk))
                fragments.append((style, " " * (pad + right_fill) + f"{theme.panel_vertical}\n"))
        style, border = _panel_border(kind, False, panel_width, theme=theme)
        fragments.append((style, border))
    return fragments
