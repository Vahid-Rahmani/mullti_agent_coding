"""ZOVA — MultiAgentCoding Retro Terminal UI.

The full-screen prompt_toolkit terminal application for the agent swarm.
Depends on core/ for agent definitions, execution hub, and command logic;
depends on ui/ for rendering and palette.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from .palette import (
    BANNER, BLACK, GREY, WHITE, ORANGE, GREY_BG, NEON, INPUT_MAX_LINES,
)
from .theme import Theme, THEMES, get_active, set_active, available_themes
from .rendering import (
    _banner_fragments, _dir_line, _model_bar, _model_bar_fragments,
    _dashboard_fragments, _loading_bar_fragments, _run_header,
    _console_fragments, _block_states, _available_columns, _panel_width,
    STATUS_SYMBOL,
)
from .settings_modal import SettingsModal
from ..core.agents import (
    AGENTS, TABS, AUTO_MODE, AUTO_MODEL,
    MODEL_OPTIONS, MODE_OPTIONS_BY_MODEL, PROJECT_ROOT, STATUS_IDLE,
    STATUS_THINKING, STATUS_ACTIVE, STATUS_ERROR, mode_options_for,
)
from ..core.command_parser import parse_command, build_help_text, _swarm_state
from ..core.intent_classifier import _format_proposals
from ..core.run_hub import (
    HUB, _sanitize_prompt, build_overrides_table as core_build_overrides_table,
)
from ..core.self_evolve_bridge import run_self_evolve


def build_rounded_box(body, title_fragments=None, width=None):
    """A rounded prompt box (╭─╮ │ ╰─╯) around ``body``."""
    from prompt_toolkit.layout import FormattedTextControl, HSplit, VSplit, Window

    def fill(char: str):
        return Window(char=char, width=1, height=1, style="class:retro.box", dont_extend_height=True)

    def resolve_width() -> int:
        return width() if callable(width) else (width or 0)

    def resolve_title() -> list[tuple]:
        return title_fragments() if callable(title_fragments) else (title_fragments or [])

    def top_content() -> list[tuple]:
        w = resolve_width()
        title = resolve_title()
        middle = "".join(fragment[1] for fragment in title)
        if w and len(middle) > max(8, w - 6):
            limit = max(8, w - 7)
            compact: list[tuple] = [("class:retro.box", "╭─")]
            remaining = limit
            for fragment in title:
                text = fragment[1]
                if len(text) <= remaining:
                    compact.append(fragment)
                    remaining -= len(text)
                    continue
                if len(fragment) == 3:
                    compact.append((fragment[0], text[:max(1, remaining)], fragment[2]))
                    remaining = 0
                elif remaining:
                    compact.append((fragment[0], text[:remaining]))
                    remaining = 0
            used = sum(len(fragment[1]) for fragment in compact)
            compact.append(("class:retro.box", "─" * max(0, w - used - 1) + "╮"))
            total = sum(len(fragment[1]) for fragment in compact)
            if total > w:
                overflow = total - w
                last_style, last_text = compact[-1]
                compact[-1] = (last_style, last_text[:-overflow] if overflow < len(last_text) else "")
            return compact
        base = [("class:retro.box", "╭─")]
        base.extend(title)
        used = 2 + len(middle) + 1
        tail = "─" * max(0, w - used) if w else ""
        base.append(("class:retro.box", tail + "╮"))
        return base

    def bottom_content() -> list[tuple[str, str]]:
        w = resolve_width()
        if not w:
            return []
        line = "╰" + "─" * max(0, w - 2) + "╯"
        return [("class:retro.box", line[:w])]

    top = Window(content=FormattedTextControl(top_content), height=1, style="class:retro.box", dont_extend_height=True)
    bottom = Window(content=FormattedTextControl(bottom_content), height=1, style="class:retro.box", dont_extend_height=True)
    mid = VSplit([fill("│"), body, fill("│")])
    return HSplit([top, mid, bottom])


class RetroTerminalApp:
    """Full-screen prompt_toolkit terminal UI."""

    MAX_CONSOLE_LINES = 1000
    CONSOLE_TAIL = 20
    _ABORT_CONFIRM_TIMEOUT_S = 3.0

    def __init__(self, workspace: Path | None = None) -> None:
        self._active_theme_name: str = "classic"
        self.hub = HUB
        if self.hub.running == 0:
            with self.hub.lock:
                for tag, _name, _agent in AGENTS:
                    self.hub.statuses[tag] = STATUS_IDLE
                    self.hub.progress[tag] = 0
                    self.hub.token_usage[tag] = 0
        if workspace is not None:
            self.hub.workspace = Path(workspace).expanduser().resolve()
        self.overrides: dict[str, dict[str, str]] = {
            "master": {"model": AUTO_MODEL, "mode": AUTO_MODE}
        }
        self.system_prompts: dict[str, str] = {tag: "" for tag, _, _ in TABS}
        self.agents_filter: list[str] | None = None
        self.menu_kind: str | None = None
        self.menu_target: str | None = None
        self.menu_options: list[str] = []
        self.menu_left = 1
        self.menu_top = 1
        self.menu_width = 24
        self.menu_height = 3
        self.console_lines: list[tuple[str, str]] = []
        self.current_tab: str = "master"
        self.tab_lines: dict[str, list[tuple[str, str]]] = {tag: [] for tag, _, _ in TABS}
        self.tab_scroll: dict[str, int] = {tag: 0 for tag, _, _ in TABS}
        self._seq = 0
        self._last_status: dict[str, str] = {}
        self._esc_pending_tag: str | None = None
        self._esc_pending_time: float = 0.0
        self.banner_visible = True
        self._application = None
        self.enabled_agents: set[str] = set(tag for tag, _, _ in AGENTS)
        self.settings = SettingsModal(self)

        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.filters import Condition, has_completions, has_focus
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings

        commands = [
            "tab", "help", "cd", "model", "mode", "prompt", "prompts",
            "agents", "status", "overrides", "settings", "clear", "stop",
            "swarm", "proposals", "plan", "evolve", "archive", "quit", "exit", "theme",
        ]
        completer = WordCompleter(commands + MODEL_OPTIONS + [t for t, _, _ in TABS], ignore_case=True)

        self.buffer = Buffer(
            name="input", multiline=True, completer=completer,
            history=InMemoryHistory(), accept_handler=self._on_accept,
        )

        kb = KeyBindings()
        settings_open = Condition(lambda: self.settings.settings_open)

        @kb.add("enter", filter=settings_open)
        def _settings_enter(_event):
            # Activate the focused settings row (Enter = open submenu / apply).
            self.settings._settings_cycle(1)

        @kb.add("up", filter=settings_open)
        def _settings_up(_event):
            self.settings.navigate(-1)

        @kb.add("down", filter=settings_open)
        def _settings_down(_event):
            self.settings.navigate(1)

        theme_menu_open = Condition(lambda: self.settings.theme_menu_open)

        @kb.add("u", filter=theme_menu_open)
        def _theme_undo(_event):
            # Undo the last color change in the theme customizer.
            self.settings._theme_undo()

        @kb.add("enter", filter=has_focus("input") & ~has_completions & ~settings_open)
        def _enter(_event):
            self.buffer.validate_and_handle()

        # Ctrl+Shift+S and Ctrl+S both arrive as the same "c-s" control
        # sequence on real terminals; one binding covers both shortcuts.
        @kb.add("c-s")
        def _ctrl_s(_event):
            self.settings.toggle_settings()

        @kb.add("c-j", filter=has_focus("input"))
        def _ctrl_j(_event):
            self.buffer.insert_text("\n")

        @kb.add("c-c", filter=has_focus("input"))
        def _ctrl_c(event):
            if self.buffer.text.strip():
                self.buffer.text = ""
                self.buffer.cursor_position = 0
            elif self.hub.running > 0:
                self._execute_esc_abort()
            else:
                event.app.exit()

        @kb.add("c-d", filter=has_focus("input"))
        def _ctrl_d(event):
            event.app.exit()

        @kb.add("escape", eager=True)
        def _escape(_event):
            self._handle_esc()

        @kb.add("c-g")
        def _ctrl_g(_event):
            self._handle_esc()

        @kb.add("pageup")
        def _page_up(_event):
            self.tab_scroll[self.current_tab] = min(
                self.tab_scroll.get(self.current_tab, 0) + 10, self._max_scroll()
            )

        @kb.add("pagedown")
        def _page_down(_event):
            self.tab_scroll[self.current_tab] = max(
                self.tab_scroll.get(self.current_tab, 0) - 10, 0
            )

        @kb.add("c-u", filter=has_focus("input"))
        def _clear_input(_event):
            self.buffer.text = ""
            self.buffer.cursor_position = 0

        for _idx, (tag, _name, _agent) in enumerate(AGENTS):
            key = f"f{_idx + 1}"

            @kb.add(key)
            def _switch_agent_tab(_event, _tag=tag):
                self.set_tab(_tag)

        @kb.add("f8")
        def _switch_master_tab(_event):
            self.set_tab("master")

        @kb.add("c-t")
        def _next_tab(_event):
            self.set_tab(self._next_tab_tag())

        @kb.add("c-n")
        def _prev_tab(_event):
            self.set_tab(self._prev_tab_tag())

        self.key_bindings = kb
        self._build_layout()
        self._style_dict = dict(self.theme.style_dict)
        self.settings.load_persisted()

    def _build_layout(self) -> None:
        """Construct (or rebuild) every layout window/float from live state.

        Console/input heights come from the active theme so density and
        font-size settings change the visible layout immediately.
        """
        from prompt_toolkit.layout import (
            BufferControl, ConditionalContainer, Dimension, Float, FloatContainer,
            FormattedTextControl, HSplit, Window,
        )
        from prompt_toolkit.filters import Condition

        banner_window = Window(
            content=FormattedTextControl(lambda: _banner_fragments(self.banner_visible)),
            height=lambda: self.theme.banner_rows if self.banner_visible else 0,
            style="class:retro.banner", always_hide_cursor=True, dont_extend_height=True,
        )
        dir_window = Window(
            content=FormattedTextControl(lambda: [("class:retro.dir", _dir_line(self.hub.workspace))]),
            height=1, style="class:retro.dir", always_hide_cursor=True, dont_extend_height=True,
        )
        self.tab_window = Window(
            content=FormattedTextControl(
                lambda: _dashboard_fragments(
                    self.hub.statuses, self.current_tab, self._handle_tab_mouse,
                    width=max(1, _available_columns() - 2), overrides=self.overrides,
                    enabled_agents=self.enabled_agents,
                )
            ),
            height=Dimension(min=1, preferred=2, max=len(TABS)),
            wrap_lines=True, style="class:retro.dash", always_hide_cursor=True, dont_extend_height=True,
        )
        self.loading_window = Window(
            content=FormattedTextControl(
                lambda: _loading_bar_fragments(**self.hub.loading_snapshot(self.current_tab), width=_available_columns(), theme=self.theme)
            ),
            height=lambda: self.theme.loading_height, wrap_lines=False,
            style="class:retro.progress",
            always_hide_cursor=True, dont_extend_height=True,
        )
        self.console_window = Window(
            content=FormattedTextControl(lambda: self._console_fragments()),
            height=Dimension(min=self.theme.console_min_lines, preferred=self.theme.console_pref_lines),
            style="class:retro.console", always_hide_cursor=True, wrap_lines=True,
        )
        input_window = Window(
            content=BufferControl(buffer=self.buffer, focusable=True),
            height=Dimension(min=self.theme.input_min_lines, max=self.theme.input_max_lines),
            wrap_lines=True, style="class:retro.input",
        )

        def _box_width() -> int:
            try:
                from prompt_toolkit.application.current import get_app
                columns = get_app().output.get_size().columns
            except Exception:
                try:
                    columns = os.get_terminal_size().columns
                except OSError:
                    columns = 100
            return max(1, columns - 2)

        box = build_rounded_box(
            input_window,
            title_fragments=lambda: _model_bar_fragments(
                self.overrides, self.agents_filter, self.current_tab,
                self._handle_control_mouse,
                compact=_box_width() < 100,
                ultra_compact=_box_width() < 60,
                esc_pending_tag=self._esc_pending_tag,
                terminal_settings=self.settings.model_bar_settings(),
            ),
            width=lambda: _box_width(),
        )
        self.prompt_box = box

        menu_window = Window(
            content=FormattedTextControl(self._menu_fragments),
            height=Dimension(min=0, preferred=1, max=len(TABS) + 2),
            wrap_lines=False, style="class:retro.menu", always_hide_cursor=True, dont_extend_height=True,
        )
        backdrop_window = Window(
            content=FormattedTextControl(self._backdrop_fragments),
            style="class:retro.backdrop", always_hide_cursor=True, dont_extend_height=True,
        )

        def _spacer():
            return Window(height=1, style="class:retro.spacer", dont_extend_height=True)

        content = HSplit([
            banner_window, _spacer(), dir_window, _spacer(),
            self.tab_window, _spacer(), self.console_window,
            self.loading_window, _spacer(), box,
        ])
        self.menu_backdrop_float = Float(
            ConditionalContainer(backdrop_window, Condition(lambda: self.menu_kind is not None)),
            top=0, left=0,
            width=lambda: self._screen_size()[0],
            height=lambda: self._screen_size()[1],
            z_index=9, transparent=True,
        )
        self.menu_float = Float(
            ConditionalContainer(menu_window, Condition(lambda: self.menu_kind is not None)),
            top=self.menu_top, left=self.menu_left,
            width=lambda: self.menu_width, height=lambda: self.menu_height, z_index=10,
        )
        settings_backdrop_window = Window(
            content=FormattedTextControl(self._settings_backdrop_fragments),
            style="class:retro.backdrop", always_hide_cursor=True, dont_extend_height=True,
        )
        settings_window = Window(
            content=FormattedTextControl(lambda: self.settings._settings_fragments()),
            height=lambda: self.settings.settings_height,
            wrap_lines=False, style="class:retro.menu",
            always_hide_cursor=True, dont_extend_height=True,
        )
        self.settings_backdrop_float = Float(
            ConditionalContainer(
                settings_backdrop_window, Condition(lambda: self.settings.settings_open)
            ),
            top=0, left=0,
            width=lambda: self._screen_size()[0],
            height=lambda: self._screen_size()[1],
            z_index=19, transparent=True,
        )
        self.settings_float = Float(
            ConditionalContainer(settings_window, Condition(lambda: self.settings.settings_open)),
            top=1, left=2,
            width=lambda: max(1, self._screen_size()[0] - 4),
            height=lambda: self.settings.settings_height,
            z_index=20, transparent=True,
        )
        self.layout_root = FloatContainer(
            content,
            floats=[
                self.menu_backdrop_float, self.menu_float,
                self.settings_backdrop_float, self.settings_float,
            ],
        )

    def _rebuild_layout(self) -> None:
        """Rebuild the layout after theme/density/font changes and rewire the app."""
        self._build_layout()
        if self._application is not None:
            from prompt_toolkit.layout import Layout
            self._application.layout = Layout(self.layout_root, focused_element=self.buffer)
            self._application.invalidate()

    # ── theme property ───────────────────────────────────────────────

    @property
    def theme(self) -> Theme:
        return get_active()

    @theme.setter
    def theme(self, value: Theme | str) -> None:
        name = value if isinstance(value, str) else value.name
        set_active(name)
        self._active_theme_name = name
        self._rebuild_style()

    def _rebuild_style(self) -> None:
        self._style_dict = dict(self.theme.style_dict)
        if self._application is not None:
            from prompt_toolkit.styles import Style
            self._application.style = Style.from_dict(self._style_dict)
            self._application.invalidate()

    # ------------------------------------------------- settings delegation
    #
    # All settings state/logic lives in ``SettingsModal`` (ui/settings_modal.py).
    # The app keeps a clean public surface for the tests and slash commands by
    # delegating unknown attributes to the modal. The few integer fields that
    # tests mutate directly are exposed as real properties so writes land on
    # the modal instance.

    @property
    def settings_focus(self) -> int:
        return self.settings.settings_focus

    @settings_focus.setter
    def settings_focus(self, value: int) -> None:
        self.settings.settings_focus = value

    @property
    def agent_focus(self) -> int:
        return self.settings.agent_focus

    @agent_focus.setter
    def agent_focus(self, value: int) -> None:
        self.settings.agent_focus = value

    @property
    def theme_focus(self) -> int:
        return self.settings.theme_focus

    @theme_focus.setter
    def theme_focus(self, value: int) -> None:
        self.settings.theme_focus = value

    @property
    def submenu_focus(self) -> int:
        return self.settings.submenu_focus

    @submenu_focus.setter
    def submenu_focus(self, value: int) -> None:
        self.settings.submenu_focus = value

    @property
    def settings_height(self) -> int:
        return self.settings.settings_height

    @settings_height.setter
    def settings_height(self, value: int) -> None:
        self.settings.settings_height = value

    def __getattr__(self, name: str):
        # Delegate the remaining settings surface (flags, draft, fragments,
        # submenu helpers, ``_cmd_settings``) to the modal when present.
        settings = self.__dict__.get("settings")
        if settings is not None and hasattr(settings, name):
            return getattr(settings, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # ------------------------------------------------------------------ tabs

    def set_tab(self, tag: str) -> None:
        if tag in self.tab_lines:
            self.current_tab = tag
            self._clear_esc_state()

    def _handle_tab_mouse(self, tag: str, event) -> None:
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType
        if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            self.set_tab(tag)
            self.close_menu(event)

    def _handle_control_mouse(self, kind: str, event) -> None:
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType
        if event.event_type != MouseEventType.MOUSE_UP or event.button != MouseButton.LEFT:
            return
        self.open_menu(kind, event=event)
        self._invalidate_ui()

    def _screen_size(self) -> tuple[int, int]:
        try:
            from prompt_toolkit.application.current import get_app
            size = get_app().output.get_size()
            return max(1, size.columns), max(1, size.rows)
        except Exception:
            try:
                size = shutil.get_terminal_size((100, 30))
                return max(1, size.columns), max(1, size.lines)
            except OSError:
                return 100, 30

    def _position_menu(self, event=None) -> None:
        columns, rows = self._screen_size()
        labels = [f"[{i + 1}] {option}" for i, option in enumerate(self.menu_options)]
        content_width = max([len(f" {self.menu_kind or 'MENU'} OPTIONS ")] + [len(x) for x in labels])
        self.menu_width = min(max(18, content_width + 4), max(1, columns))
        self.menu_height = min(len(self.menu_options) + 2, max(1, rows))
        if event is not None:
            try:
                anchor_x = int(event.position.x)
                anchor_y = int(event.position.y)
            except (AttributeError, TypeError, ValueError):
                anchor_x, anchor_y = 1, rows - INPUT_MAX_LINES - 2
        else:
            anchor_x, anchor_y = 1, rows - INPUT_MAX_LINES - 2
        top = anchor_y - self.menu_height
        if top < 0:
            top = anchor_y + 1
        self.menu_left = max(0, min(anchor_x, max(0, columns - self.menu_width)))
        self.menu_top = max(0, min(top, max(0, rows - self.menu_height)))
        menu_float = getattr(self, "menu_float", None)
        if menu_float is not None:
            menu_float.left = self.menu_left
            menu_float.top = self.menu_top

    def _backdrop_fragments(self) -> list[tuple]:
        if self.menu_kind is None:
            return []
        columns, rows = self._screen_size()
        def dismiss(event):
            self._dismiss_mouse(event)
        return [("class:retro.backdrop", (" " * columns + "\n") * rows, dismiss)]

    def _settings_backdrop_fragments(self) -> list[tuple]:
        """Full-screen dim layer behind the settings modal."""
        if not self.settings.settings_open:
            return []
        columns, rows = self._screen_size()
        return [("class:retro.backdrop", (" " * columns + "\n") * rows)]

    def open_menu(self, kind: str, target: str | None = None, event=None) -> None:
        self.menu_kind = kind
        self.menu_target = target or self.current_tab
        if kind == "model":
            self.menu_options = list(MODEL_OPTIONS)
        elif kind == "mode":
            model, _mode = self.hub.resolve(self.menu_target, self.overrides)
            self.menu_options = mode_options_for(model, self.menu_target)
        elif kind == "target":
            self.menu_options = ["all"] + [tag for tag, _name, _agent in AGENTS]
        elif kind == "tab":
            self.menu_options = [tag for tag, _name, _agent in TABS]
        else:
            self.menu_kind = None
            self.menu_target = None
            self.menu_options = []
        if self.menu_kind is not None:
            self._position_menu(event)

    def _invalidate_ui(self) -> None:
        try:
            from prompt_toolkit.application.current import get_app
            get_app().invalidate()
        except Exception:
            pass

    def _dismiss_mouse(self, event) -> None:
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType
        if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            self.close_menu(event)

    def _handle_esc(self) -> None:
        if self.settings.settings_open:
            self.settings.handle_escape()
            return
        if self.menu_kind is not None:
            self.close_menu()
            return
        if self.hub.running == 0:
            self._clear_esc_state()
            self._echo("No agents are currently running. Esc / Ctrl+G aborts active runs.")
            return
        now = time.monotonic()
        timeout = self._ABORT_CONFIRM_TIMEOUT_S
        if self._esc_pending_tag is not None and (now - self._esc_pending_time) < timeout:
            self._execute_esc_abort()
            self._clear_esc_state()
        else:
            self._esc_pending_tag = self.current_tab
            self._esc_pending_time = now
            self._show_esc_warning()

    def _clear_esc_state(self) -> None:
        self._esc_pending_tag = None
        self._esc_pending_time = 0.0

    def _show_esc_warning(self) -> None:
        if self.current_tab == "master":
            msg = (
                "⚠  ESC: Press Esc again to ABORT ALL AGENTS "
                "(global cascade — every active agent will be terminated)"
            )
        else:
            name = next((n for t, n, _ in AGENTS if t == self.current_tab), self.current_tab.upper())
            msg = (
                f"⚠  ESC: Press Esc again to ABORT {self.current_tab.upper()} "
                f"({name}) only — other agents will keep running"
            )
        self._echo(msg)

    def _execute_esc_abort(self) -> None:
        if self.current_tab == "master":
            self.hub.terminate_all()
            self._echo("ABORTED: all agent processes terminated.")
        elif self.current_tab.startswith("m"):
            name = next((n for t, n, _ in AGENTS if t == self.current_tab), self.current_tab.upper())
            if self.hub.terminate_agent(self.current_tab):
                self._echo(f"ABORTED: {name} ({self.current_tab.upper()}) terminated.")
            else:
                self._echo(f"{name} ({self.current_tab.upper()}) was not running.")
        else:
            self._echo("No agent selected to abort.")
        self._clear_esc_state()

    def close_menu(self, event=None) -> None:
        self.menu_kind = None
        self.menu_target = None
        self.menu_options = []
        self._clear_esc_state()
        try:
            from prompt_toolkit.application.current import get_app
            app = get_app()
            app.layout.focus(self.buffer)
            app.invalidate()
        except Exception:
            pass

    def _menu_fragments(self) -> list[tuple]:
        if not self.menu_kind:
            return []
        width = max(1, self.menu_width)
        title = f" {self.menu_kind.upper()} OPTIONS "
        inner = max(0, width - 4)
        top_inner = max(0, width - 3)
        top = "╭─" + title[:top_inner].ljust(top_inner, "─") + "╮"
        bottom = "╰" + "─" * max(0, width - 2) + "╯"
        fragments: list[tuple] = [("class:retro.menu.border", top + "\n")]
        for index, option in enumerate(self.menu_options):
            label = f"[{index + 1}] {option}"
            visible = label[:inner]
            def click(event, _option=option):
                self._select_menu_option(_option, event)
            fragments.append(("class:retro.menu.border", "│ "))
            fragments.append(("class:retro.menu.item", visible.ljust(inner), click))
            fragments.append(("class:retro.menu.border", " │\n"))
        fragments.append(("class:retro.menu.border", bottom + "\n"))
        return fragments

    def _select_menu_option(self, option: str, event=None) -> None:
        kind = self.menu_kind
        if kind == "model":
            self._set_override(self.menu_target or self.current_tab, "model", option)
        elif kind == "mode":
            target = self.menu_target or self.current_tab
            model, _mode = self.hub.resolve(target, self.overrides)
            valid = mode_options_for(model, target)
            if option in valid:
                self._set_override(target, "mode", option)
        elif kind == "target":
            self.agents_filter = None if option == "all" else [option]
        elif kind == "tab":
            self.set_tab(option)
        self.close_menu(event)

    def _tab_order(self) -> list[str]:
        return [t for t, _, _ in TABS if t == "master" or t in self.enabled_agents]

    def _next_tab_tag(self) -> str:
        order = self._tab_order()
        return order[(order.index(self.current_tab) + 1) % len(order)]

    def _prev_tab_tag(self) -> str:
        order = self._tab_order()
        return order[(order.index(self.current_tab) - 1) % len(order)]

    # ------------------------------------------------------------------ console

    def _tab_source(self) -> list[tuple[str, str]]:
        if self.current_tab == "master":
            return self.console_lines
        return self.tab_lines[self.current_tab]

    def _max_scroll(self) -> int:
        return max(0, len(self._tab_source()) - self.CONSOLE_TAIL)

    def _console_fragments(self) -> list[tuple[str, str]]:
        source = self._tab_source()
        scroll = self.tab_scroll.get(self.current_tab, 0)
        tail = min(len(source), self.CONSOLE_TAIL)
        start = max(0, len(source) - tail - scroll)
        history_prefix = source[:start]
        initial_states = _block_states(history_prefix)
        return _console_fragments(
            source[start:], prefix=self.current_tab == "master",
            initial_states=initial_states,
            width=max(1, _available_columns() - 2),
            theme=self.theme,
        )

    def _drain(self) -> None:
        with self.hub.lock:
            events = [e for e in self.hub.events if e["seq"] > self._seq]
            if events:
                self._seq = max(e["seq"] for e in events)
        for event in events:
            kind = event["kind"]
            text = event["text"]
            tag = event["tag"]
            if kind == "run":
                # Structured run marker: "M4::prompt text"
                parts = text.split("::", 1)
                run_tag = parts[0].lower() if len(parts) >= 2 else tag
                prompt_snippet = parts[1] if len(parts) >= 2 else text
                header = _run_header(prompt_snippet, run_tag.upper())
                self.console_lines.append((tag, header))
                if tag != "master":
                    self.tab_lines[tag].append((tag, header))
            elif kind == "line":
                self.console_lines.append((tag, text))
                if tag != "master":
                    self.tab_lines[tag].append((tag, text))
            elif kind == "error":
                self.console_lines.append((tag, f"ERROR: {text}"))
                if tag != "master":
                    self.tab_lines[tag].append((tag, f"ERROR: {text}"))
            elif kind == "status":
                self._last_status[tag] = text
        if len(self.console_lines) > self.MAX_CONSOLE_LINES:
            self.console_lines = self.console_lines[-self.MAX_CONSOLE_LINES:]
        for tag, lines in self.tab_lines.items():
            if len(lines) > self.MAX_CONSOLE_LINES:
                self.tab_lines[tag] = lines[-self.MAX_CONSOLE_LINES:]

    def _build_application(self, input=None, output=None):
        if self._application is None:
            from prompt_toolkit.application import Application
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.styles import Style
            self._application = Application(
                layout=Layout(self.layout_root, focused_element=self.buffer),
                key_bindings=self.key_bindings,
                full_screen=True, mouse_support=True,
                style=Style.from_dict(self._style_dict),
                erase_when_done=True, input=input, output=output,
            )
        return self._application

    # ------------------------------------------------------------------ input

    def _echo(self, text: str) -> None:
        entry = ("master", text)
        self.console_lines.append(entry)
        if self.current_tab != "master":
            self.tab_lines[self.current_tab].append(entry)

    def _on_accept(self, _buffer) -> None:
        text = self.buffer.text
        self.buffer.text = ""
        self.buffer.cursor_position = 0
        stripped = text.strip()
        if not stripped:
            return
        self.banner_visible = False
        self._echo(f"▸ {stripped}")
        self._handle_input(stripped)

    def _handle_input(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        self._clear_esc_state()
        self.banner_visible = False
        cmd = parse_command(stripped)
        if cmd is None:
            if self.current_tab == "master":
                targets = self.agents_filter
            else:
                targets = [self.current_tab]
            err = self.hub.run(
                stripped, self.overrides, targets,
                system_prompts=self.system_prompts,
                enabled_agents=self.enabled_agents,
            )
            if err:
                self._echo(f"ERROR: {err}")
            return
        name, arg = cmd
        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            self._echo(f"unknown command: /{name} — try /help")
            return
        try:
            reply = handler(arg)
        except Exception as exc:
            reply = f"ERROR: {exc}"
        if reply:
            for line in reply.splitlines():
                self._echo(line)

    # ------------------------------------------------------------ slash commands

    def _cmd_tab(self, arg: str) -> str:
        if not arg:
            return f"TAB: {self.current_tab}"
        tag = arg.strip().lower()
        if tag == "next":
            tag = self._next_tab_tag()
        elif tag == "prev":
            tag = self._prev_tab_tag()
        if tag not in self.tab_lines:
            return f"ERROR: unknown tab '{tag}' (tabs: {', '.join(self._tab_order())})"
        self.set_tab(tag)
        return f"TAB: {tag}"

    def _cmd_help(self, _arg: str) -> str:
        return build_help_text()

    def _cmd_cd(self, arg: str) -> str:
        if not arg:
            return f"DIR: {self.hub.workspace}"
        path = Path(arg).expanduser()
        if not path.is_dir():
            return f"ERROR: not a directory: {path}"
        self.hub.workspace = path.resolve()
        return f"DIR changed → {self.hub.workspace}"

    _OVERRIDE_TARGETS = {"master", "all"} | {tag for tag, _, _ in AGENTS}

    def _split_override_arg(self, arg: str) -> tuple[str, str]:
        parts = arg.split(None, 1)
        if parts and parts[0].lower() in self._OVERRIDE_TARGETS:
            return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        return self.current_tab, arg

    def _set_override(self, target: str, key: str, value: str) -> None:
        """Write a model/mode override for a target (tab, ``master`` or ``all``).

        Every agent (M1..M7) is individually configurable; ``all`` fans out to
        the whole roster including the master default.
        """
        if target == "all":
            for tag, _, _ in TABS:
                self.overrides.setdefault(tag, {})[key] = value
        else:
            self.overrides.setdefault(target, {})[key] = value

    def _explicit_overrides(self, key: str | None = None) -> list[str]:
        out: list[str] = []
        for tag, _, _ in TABS:
            over = self.overrides.get(tag, {})
            parts = []
            model = over.get("model")
            if (key in (None, "model")) and model and model != AUTO_MODEL:
                parts.append(model)
            mode = over.get("mode")
            if (key in (None, "mode")) and mode and mode != AUTO_MODE:
                parts.append(f"mode:{mode}")
            if parts:
                out.append(f"{tag}={'/'.join(parts)}")
        return out

    def _model_status_line(self, target: str) -> str:
        model, _mode = self.hub.resolve(target, self.overrides)
        value = model or AUTO_MODEL
        if target != self.current_tab:
            return f"MODEL ({target}): {value}"
        return f"MODEL: {value}"

    def _mode_status_line(self, target: str) -> str:
        _model, mode = self.hub.resolve(target, self.overrides)
        value = mode or AUTO_MODE
        if target != self.current_tab:
            return f"MODE ({target}): {value}"
        return f"MODE: {value}"

    def _cmd_model(self, arg: str) -> str:
        target, value = self._split_override_arg(arg)
        if target == "all":
            if not value:
                over = self._explicit_overrides("model")
                return "MODEL (all tabs): " + ("; ".join(over) if over else "auto everywhere")
            if value == AUTO_MODEL or value.lower() == "auto":
                self._set_override("all", "model", AUTO_MODEL)
                return "MODEL: reset to auto for all tabs"
            if value not in MODEL_OPTIONS:
                return f"ERROR: unknown model '{value}' (options: {', '.join(MODEL_OPTIONS)})"
            self._set_override("all", "model", value)
            return f"MODEL: {value} (all tabs)"
        if not value:
            self.open_menu("model", target)
            return self._model_status_line(target) + " (menu opened)"
        if value == AUTO_MODEL or value.lower() == "auto":
            self._set_override(target, "model", AUTO_MODEL)
            return self._model_status_line(target)
        if value not in MODEL_OPTIONS:
            return f"ERROR: unknown model '{value}' (options: {', '.join(MODEL_OPTIONS)})"
        self._set_override(target, "model", value)
        return self._model_status_line(target)

    def _cmd_mode(self, arg: str) -> str:
        target, value = self._split_override_arg(arg)
        if target == "all":
            if not value:
                over = self._explicit_overrides("mode")
                return "MODE (all tabs): " + ("; ".join(over) if over else "auto everywhere")
            valid_modes = {m for opts in MODE_OPTIONS_BY_MODEL.values() for m in opts}
            if value == AUTO_MODE or value.lower() == "auto":
                self._set_override("all", "mode", AUTO_MODE)
                return "MODE: reset to auto for all tabs"
            if value not in valid_modes:
                return f"ERROR: '{value}' not a known mode (options: {', '.join(sorted(valid_modes))})"
            self._set_override("all", "mode", value)
            return f"MODE: {value} (all tabs)"
        model, _mode = self.hub.resolve(target, self.overrides)
        modes = mode_options_for(model, target)
        if not value:
            self.open_menu("mode", target)
            return self._mode_status_line(target) + " (menu opened)"
        if value == AUTO_MODE or value.lower() == "auto":
            self._set_override(target, "mode", AUTO_MODE)
            return self._mode_status_line(target)
        if value not in modes:
            return f"ERROR: '{value}' not valid for {model or AUTO_MODEL} (options: {', '.join(modes)})"
        self._set_override(target, "mode", value)
        return self._mode_status_line(target)

    def _cmd_overrides(self, _arg: str) -> str:
        return core_build_overrides_table(self.overrides)

    def _cmd_prompt(self, arg: str) -> str:
        target, value = self._split_override_arg(arg)
        if target == "all":
            targets = [tag for tag, _name, _agent in AGENTS]
        else:
            targets = [target]
        if not value:
            if target == "all":
                configured = [
                    f"{tag}: on" for tag, _name, _agent in AGENTS
                    if self.system_prompts.get(tag, "")
                ]
                return "PROMPT (all): " + (", ".join(configured) if configured else "off")
            return f"PROMPT ({target}): " + (self.system_prompts.get(target, "") or "off")
        if value.lower() in {"off", "clear", "none"}:
            for tag in targets:
                self.system_prompts[tag] = ""
            return f"PROMPT: cleared for {target}"
        sanitized = _sanitize_prompt(value)
        if not sanitized:
            return f"ERROR: specialized prompt for {target} must not be empty"
        for tag in targets:
            self.system_prompts[tag] = sanitized
        return f"PROMPT: configured for {target} ({len(sanitized)} chars)"

    def _cmd_prompts(self, _arg: str) -> str:
        lines = ["SPECIALIZED PROMPTS:"]
        for tag, name, _agent in AGENTS:
            text = self.system_prompts.get(tag, "")
            preview = "off" if not text else "on — " + " ".join(text.split())[:72]
            lines.append(f"  {tag.upper()} {name}: {preview}")
        return "\n".join(lines)

    def _cmd_agents(self, arg: str) -> str:
        if not arg:
            target = ",".join(self.agents_filter) if self.agents_filter else "all"
            return f"TARGET agents: {target}"
        valid = {tag for tag, _, _ in AGENTS}
        if arg.lower() == "all":
            self.agents_filter = None
            return "TARGET agents: all"
        tags = [t.strip().lower() for t in arg.split(",") if t.strip()]
        unknown = [t for t in tags if t not in valid]
        if unknown:
            return f"ERROR: unknown tag(s): {', '.join(unknown)} (valid: {', '.join(sorted(valid))})"
        self.agents_filter = tags
        return f"TARGET agents: {','.join(tags)}"

    def _cmd_agents_log(self, arg: str, _agents_dir_override=None) -> str:
        import agent_logger

        tag = arg.strip().lower() if arg.strip() else self.current_tab
        if tag == "master":
            tag = self.current_tab or "m1"
        if tag not in {t for t, _, _ in AGENTS}:
            return f"ERROR: unknown tag '{tag}' — use m1..m7"
        agents_dir = _agents_dir_override or (PROJECT_ROOT / "obsidian_vault" / "agents_logs")
        filename = agent_logger._safe_agent_filename(tag)
        log_path = agents_dir / filename
        if not log_path.is_file():
            return f"No log file for {tag.upper()}"
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return f"Cannot read log for {tag.upper()}"
        entries = [l for l in lines if l.startswith("### ")]
        if not entries:
            return f"{tag.upper()}: no run entries yet"
        recent = entries[-5:]
        return f"{tag.upper()} — last {len(recent)} run(s):\n" + "\n".join(recent)

    def _cmd_status(self, _arg: str) -> str:
        statuses = "  ".join(
            f"{tag.upper()}={self.hub.statuses.get(tag, STATUS_IDLE)}" for tag, _, _ in AGENTS
        )
        target = (
            self.current_tab
            if self.current_tab != "master"
            else (",".join(self.agents_filter) if self.agents_filter else "all")
        )
        model, mode = self.hub.resolve(self.current_tab, self.overrides)
        ts = self.settings.terminal_settings
        settings_summary = (
            f"SETTINGS: {len(self.enabled_agents)} agents · "
            f"theme {self.theme.name} · "
            f"density {ts.get('density', 'comfortable')} · "
            f"font {ts.get('font_size', 'medium')} · "
            f"borders {'on' if ts.get('panel_borders', True) else 'off'}"
        )
        return "\n".join([
            f"DIR: {self.hub.workspace}",
            f"TAB: {self.current_tab} "
            f"MODEL: {model or AUTO_MODEL} "
            f"MODE: {mode or AUTO_MODE} "
            f"RUN: {self.hub.running}/{len(AGENTS)} "
            f"TARGET: {target}",
            statuses,
            settings_summary,
        ])

    def _cmd_clear(self, _arg: str) -> str:
        self.console_lines = []
        for tag in self.tab_lines:
            self.tab_lines[tag] = []
        self.tab_scroll = {tag: 0 for tag in self.tab_lines}
        self.hub.clear()
        return ""

    def _cmd_stop(self, _arg: str) -> str:
        self._clear_esc_state()
        self.hub.terminate_all()
        return "stopped all running agents"

    def _cmd_swarm(self, _arg: str) -> str:
        return _swarm_state()

    def _cmd_proposals(self, _arg: str) -> str:
        return _format_proposals()

    def _cmd_plan(self, arg: str) -> str:
        """Analyzer Core — preview the mandatory pre-dispatch master plan.

        ``/plan <prompt>`` analyzes the given text; ``/plan`` analyzes the
        text currently in the input buffer. Shows Phase 1 (requirements),
        Phase 2 (modular decoupling) and Phase 3 (one component per agent).
        """
        prompt = arg.strip()
        if not prompt:
            prompt = self.buffer.text.strip()
        if not prompt:
            return "ERROR: nothing to analyze — type a prompt or use /plan <prompt>"
        try:
            from ..core.analyzer import build_master_plan

            plan = build_master_plan(prompt, workspace=self.hub.workspace)
        except Exception as exc:
            return f"ERROR: analyzer failed: {exc}"
        text = plan.to_text()
        if plan.applicable and plan.gaps:
            text += "\n\nREQUIREMENTS GAPS (Phase 1):\n" + "\n".join(
                f"  - {gap}" for gap in plan.gaps
            )
        return text

    def _cmd_evolve(self, arg: str) -> str:
        err = run_self_evolve(arg, self.overrides, self.system_prompts, self.enabled_agents)
        return err if err else "self-evolve dispatched"

    def _cmd_audit(self, _arg: str) -> str:
        if "m7" not in self.enabled_agents:
            return "M7 (Chloe) is disabled — re-enable M7 to run audits."
        if self.hub.running > 0:
            return "Agents are still running — audit will run automatically when M7 completes."
        try:
            import obsidian_auditor
            result = obsidian_auditor.audit_run()
            return result["summary"]
        except Exception as exc:
            return f"Audit error: {exc}"

    def _cmd_archive(self, arg: str) -> str:
        """Run the Architectural Obsidian Archivist (M7) on-demand.

        Optional ``arg`` is the prompt/decision text to capture; without it
        the archivist still refreshes the project's architecture map and
        lean Evolution file (rules 1-5). When the text carries a structural
        signal, the Analyzer Core first builds the mandatory master plan and
        its module map (one component per agent) is persisted into
        ``docs/architecture/`` alongside the captured decisions.
        """
        if self.hub.running > 0:
            return "Agents are still running — archive will run automatically when M7 completes."
        try:
            from ..core.archivist import archivist_run
            from ..core.analyzer import build_master_plan

            plan = build_master_plan(arg, workspace=self.hub.workspace)
            result = archivist_run(arg, workspace=self.hub.workspace, plan=plan)
            return result["summary"]
        except Exception as exc:
            return f"Archive error: {exc}"

    def _cmd_quit(self, _arg: str) -> str:
        app = self._build_application()
        if app.is_running:
            app.exit()
        return ""

    _cmd_exit = _cmd_quit

    def _cmd_theme(self, arg: str) -> str:
        names = available_themes()
        current = self._active_theme_name or "classic"
        if not arg:
            labels = [f"* {n}" if n == current else f"  {n}" for n in names]
            display = {n: THEMES[n].display_name for n in names}
            themed = [f"{labels[i]} — {display.get(names[i], names[i])}" for i in range(len(names))]
            return f"THEME: {current}\n" + "\n".join(themed) + "\n\nUse /theme <name> to switch."
        name = arg.strip().lower()
        if name not in THEMES:
            return f"ERROR: unknown theme '{name}'. Available: {', '.join(names)}"
        old = self._active_theme_name
        self.settings.terminal_settings["theme"] = name
        self.theme = name
        # Keep any persisted font-size scaling applied on the new theme.
        self.settings._apply_font_scale()
        self._rebuild_layout()
        self._invalidate_ui()
        return f"THEME changed: {old} → {name} ({THEMES[name].display_name})"

    # ------------------------------------------------------------------ run loop

    async def _poller(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            self._drain()
            if self._application is not None:
                self._application.invalidate()

    def run(self) -> int:
        from prompt_toolkit.input import create_input
        from prompt_toolkit.output import create_output

        self.console_lines.append(("master", "ZOVA terminal ready — F1..F7 select agent tabs, F8 MASTER, type /help for commands."))
        app = self._build_application(input=create_input(), output=create_output())

        def _start_poller() -> None:
            app.create_background_task(self._poller())

        app.run(pre_run=_start_poller)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZOVA — MultiAgentCoding Retro Terminal")
    parser.add_argument("--workspace", default=None, help="working directory for the agents")
    parser.add_argument(
        "--smoke", action="store_true",
        help="headless build check: construct the app and exit (no TTY required)",
    )
    args = parser.parse_args(argv)

    app = RetroTerminalApp(workspace=Path(args.workspace) if args.workspace else None)
    if args.smoke:
        print("SMOKE-OK: retro terminal app constructed (banner rows=%d)" % len(BANNER))
        return 0
    return app.run()


# NOTE: this module is a package member (``scripts.ui.terminal_app``) and
# uses relative imports, so it cannot be executed directly as ``__main__``.
# The documented entry point is ``scripts/terminal_app.py`` (the shim),
# which imports ``main`` from here.
