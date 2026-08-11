"""ZOVA — MultiAgentCoding Retro Terminal UI.

The full-screen prompt_toolkit terminal application for the multi-agent system.
Depends on core/ for agent definitions, execution hub, and command logic;
depends on ui/ for rendering and palette.

Baseline-zero: plain dispatch — agents run their configured spec models with
the raw prompt. No settings modal, no mode menus, no overrides.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
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
from ..core.agents import (
    AGENTS, TABS, PROJECT_ROOT, STATUS_IDLE,
    STATUS_THINKING, STATUS_ACTIVE, STATUS_ERROR,
)
from ..core.command_parser import parse_command, build_help_text
from ..core.run_hub import HUB, _sanitize_prompt


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
        self.enabled_agents: set[str] = set(tag for tag, _, _ in AGENTS)
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

        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings

        commands = [
            "tab", "help", "cd", "status", "clear", "stop",
            "theme", "quit", "exit",
        ]
        completer = WordCompleter(commands + [t for t, _, _ in TABS], ignore_case=True)

        self.buffer = Buffer(
            name="input", multiline=True, completer=completer,
            history=InMemoryHistory(), accept_handler=self._on_accept,
        )

        from prompt_toolkit.filters import has_completions, has_focus

        kb = KeyBindings()
        input_focused = has_focus("input")

        @kb.add("enter", filter=input_focused & ~has_completions)
        def _enter(_event):
            self.buffer.validate_and_handle()

        @kb.add("c-j", filter=input_focused)
        def _ctrl_j(_event):
            self.buffer.insert_text("\n")

        @kb.add("c-c", filter=input_focused)
        def _ctrl_c(event):
            if self.buffer.text.strip():
                self.buffer.text = ""
                self.buffer.cursor_position = 0
            elif self.hub.running > 0:
                self._execute_esc_abort()
            else:
                event.app.exit()

        @kb.add("c-d", filter=input_focused)
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

        @kb.add("c-u", filter=input_focused)
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

    # ------------------------------------------------------------------ tabs

    def set_tab(self, tag: str) -> None:
        if tag in self.tab_lines:
            self.current_tab = tag
            self._clear_esc_state()

    def _handle_tab_mouse(self, tag: str, event) -> None:
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType
        if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            self.set_tab(tag)

    def _build_layout(self) -> None:
        """Construct (or rebuild) every layout window/float from live state."""
        from prompt_toolkit.layout import (
            BufferControl, Dimension, FormattedTextControl, HSplit, Window,
        )

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
                    width=max(1, _available_columns() - 2),
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
                self.current_tab,
                compact=_box_width() < 100,
                ultra_compact=_box_width() < 60,
                esc_pending_tag=self._esc_pending_tag,
            ),
            width=lambda: _box_width(),
        )
        self.prompt_box = box

        def _spacer():
            return Window(height=1, style="class:retro.spacer", dont_extend_height=True)

        content = HSplit([
            banner_window, _spacer(), dir_window, _spacer(),
            self.tab_window, _spacer(), self.console_window,
            self.loading_window, _spacer(), box,
        ])
        from prompt_toolkit.layout import FloatContainer
        self.layout_root = FloatContainer(content, floats=[])

    def _rebuild_layout(self) -> None:
        """Rebuild the layout after theme/density/font changes and rewire the app."""
        self._build_layout()
        if self._application is not None:
            from prompt_toolkit.layout import Layout
            self._application.layout = Layout(self.layout_root, focused_element=self.buffer)
            self._application.invalidate()

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

    def _invalidate_ui(self) -> None:
        try:
            from prompt_toolkit.application.current import get_app
            get_app().invalidate()
        except Exception:
            pass

    def _handle_esc(self) -> None:
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
                targets = None
            else:
                targets = [self.current_tab]
            err = self.hub.run(stripped, agents=targets, enabled_agents=self.enabled_agents)
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

    def _cmd_status(self, _arg: str) -> str:
        statuses = "  ".join(
            f"{tag.upper()}={self.hub.statuses.get(tag, STATUS_IDLE)}" for tag, _, _ in AGENTS
        )
        model, _mode = self.hub.resolve(self.current_tab)
        return "\n".join([
            f"DIR: {self.hub.workspace}",
            f"TAB: {self.current_tab} "
            f"MODEL: {model or 'auto'} "
            f"RUN: {self.hub.running}/{len(AGENTS)} "
            f"TARGET: {self.current_tab if self.current_tab != 'master' else 'all'}",
            statuses,
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
        self.theme = name
        self._rebuild_layout()
        self._invalidate_ui()
        return f"THEME changed: {old} → {name} ({THEMES[name].display_name})"

    def _cmd_quit(self, _arg: str) -> str:
        app = self._build_application()
        if app.is_running:
            app.exit()
        return ""

    _cmd_exit = _cmd_quit

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
