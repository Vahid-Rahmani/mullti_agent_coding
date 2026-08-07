#!/usr/bin/env python3
"""
MultiAgentCoding — AI Agent Workspace GUI

An ultra-professional single-window workspace for the control-plane agents:
  * a prominent workspace header showing the current target path + Change Directory,
  * a status dashboard with 4-state badges for m1..m7 (⚪ Idle / 🟡 Thinking /
    🟢 Active / 🔴 Error) that navigate to the agent's tab on click,
  * a tabbed body: '💬 Master Console' plus one dedicated tab per agent,
  * an interactive control bar with RUN COMMAND, CLEAR LOGS, an auto-scroll
    toggle, and quick action shortcuts.

Submitting a prompt spawns one thread per agent running
    opencode run --agent <agent_name> --auto "<prompt>"
and routes each agent's stdout/stderr (with ANSI codes stripped) into its own tab.

Usage:
    python scripts/unified_app.py
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

# Workspace root = the directory the launcher was launched from (so `myagent`
# targets whatever folder it is run in), not the script directory.
PROJECT_ROOT = Path(os.getcwd())

# (tag, display name, opencode agent name) — order matches opencode.json agents.
AGENTS = [
    ("m1", "System Architect", "system-architect"),
    ("m2", "Analyst", "analyst"),
    ("m3", "Planner", "planner"),
    ("m4", "Backend Dev", "backend-dev"),
    ("m5", "Frontend Dev", "frontend-dev"),
    ("m6", "Tester", "tester"),
    ("m7", "Reviewer", "reviewer"),
]

# Per-tag accent colors (used for status badges, tab labels, and stream tags).
TAG_COLORS = {
    "m1": "#ff6b6b",
    "m2": "#4ecdc4",
    "m3": "#45b7d1",
    "m4": "#96ceb4",
    "m5": "#f9ca24",
    "m6": "#dda0dd",
    "m7": "#f7b731",
    "master": "#ffffff",
    "system": "#95a5a6",
}

# Status indicators (emoji-driven per spec).
STATUS_IDLE = "⚪ Idle"
STATUS_THINKING = "🟡 Thinking"
STATUS_ACTIVE = "🟢 Active"
STATUS_ERROR = "🔴 Error"

# Modern dark palette.
BG = "#1e1e1e"
PANEL = "#252526"
PANEL_ALT = "#2d2d30"
BORDER = "#3c3c3c"
TEXT = "#d4d4d4"
MUTED = "#9a9a9a"
ACCENT = "#0e639c"
ACCENT_ACTIVE = "#1177bb"
ERROR = "#ff5555"
STREAM_BG = "#121212"
HEADER_BG = "#1a1a1b"

FONT_FAMILY = "Consolas"
FONT_SIZE = 10
POLL_MS = 50  # how often the main thread drains the output queue

AGENT_TAB_LABELS = {tag: f"{tag} {name}" for tag, name, _ in AGENTS}

# Model selector options. "Auto" lets each agent use its configured hybrid
# model from opencode.json; selecting a concrete model overrides it via -m.
AUTO_MODEL = "Auto (Smart Hybrid Routing)"
MODEL_OPTIONS = [
    AUTO_MODEL,
    "opencode/deepseek-v4-flash-free",
    "opencode/ling-3.0-tiny-free",
    "opencode/big-pickle",
]

# Quick action shortcuts -> prompt templates prefilled into the prompt area.
QUICK_ACTIONS = [
    ("Analyze", "Analyze the current project and produce a requirements analysis."),
    ("Plan", "Plan the next implementation step for the current project."),
    ("Implement", "Implement the next planned task for the current project."),
    ("Test", "Write and run tests for the current project."),
    ("Review", "Review the latest changes in the current project."),
]

# Matches CSI (ANSI) sequences like \x1b[0m, \x1b[91m, \x1b[1m and OSC
# sequences like \x1b]...\x07.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a log string."""
    return _ANSI_RE.sub("", text)


def _opencode_command() -> str | None:
    """Resolve the opencode executable path (PATHEXT-aware, Windows-safe).

    On Windows the CLI is shipped as ``opencode.cmd``; passing the bare name to
    ``subprocess.Popen`` with ``shell=False`` fails with WinError 2 because
    CreateProcess does not resolve ``.cmd``/``.bat`` via PATHEXT. ``shutil.which``
    resolves the full path so the child process can be located and executed.
    """
    return shutil.which("opencode") or shutil.which("opencode.cmd")


class StreamView(tk.Text):
    """Read-only, dark-styled stream widget with per-agent tag colors."""

    def __init__(self, parent: tk.Widget, autoscroll: "tk.BooleanVar | None" = None) -> None:
        super().__init__(
            parent,
            wrap=tk.WORD,
            bg=STREAM_BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=(FONT_FAMILY, FONT_SIZE),
            state=tk.DISABLED,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            padx=10,
            pady=8,
        )
        self._autoscroll = autoscroll
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.yview)
        self.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tag_configure("tag", foreground="#ffffff")
        for tag, color in TAG_COLORS.items():
            self.tag_configure(
                f"tag_{tag}", foreground=color, font=(FONT_FAMILY, FONT_SIZE, "bold")
            )
        self.tag_configure("body", foreground=TEXT)
        self.tag_configure("error", foreground=ERROR)
        self.tag_configure("muted", foreground=MUTED)

    def _maybe_scroll(self) -> None:
        if self._autoscroll is None or self._autoscroll.get():
            self.see(tk.END)

    def append(self, text: str, tag: str = "") -> None:
        """Append a line (main thread only), stripping ANSI codes."""
        text = _strip_ansi(text)
        self.configure(state=tk.NORMAL)
        if tag:
            self.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.insert(tk.END, text + "\n", "body")
        self._maybe_scroll()
        self.configure(state=tk.DISABLED)

    def append_error(self, text: str, tag: str = "") -> None:
        """Append an error line (main thread only), stripping ANSI codes."""
        text = _strip_ansi(text)
        self.configure(state=tk.NORMAL)
        if tag:
            self.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.insert(tk.END, text + "\n", "error")
        self._maybe_scroll()
        self.configure(state=tk.DISABLED)

    def clear(self) -> None:
        """Clear all content (main thread only)."""
        self.configure(state=tk.NORMAL)
        self.delete("1.0", tk.END)
        self.configure(state=tk.DISABLED)


class StatusBadge(ttk.Frame):
    """One agent status badge: tag/name + live ⚪/🟡/🟢/🔴 indicator.

    Clicking the badge navigates the notebook to the agent's tab.
    """

    def __init__(
        self,
        parent: tk.Widget,
        tag: str,
        name: str,
        color: str,
        on_click: "callable[[str], None] | None" = None,
    ) -> None:
        super().__init__(parent, style="Card.TFrame", padding=(8, 6), cursor="hand2")
        self.tag = tag
        self.color = color
        self._on_click = on_click

        self.name_label = ttk.Label(
            self,
            text=f"{tag.upper()} · {name}",
            style="CardName.TLabel",
        )
        self.name_label.pack(anchor=tk.W)

        self.status_label = ttk.Label(
            self,
            text=STATUS_IDLE,
            style="CardStatus.TLabel",
        )
        self.status_label.pack(anchor=tk.W)

        for widget in (self, self.name_label, self.status_label):
            widget.bind("<Button-1>", self._handle_click)

        self.set_status_idle()

    def _handle_click(self, _event=None) -> None:
        if self._on_click:
            self._on_click(self.tag)

    def set_status(self, status: str) -> None:
        self.status_label.configure(text=status)

    def set_status_idle(self) -> None:
        self.set_status(STATUS_IDLE)

    def set_status_thinking(self) -> None:
        self.set_status(STATUS_THINKING)

    def set_status_active(self) -> None:
        self.set_status(STATUS_ACTIVE)

    def set_status_error(self) -> None:
        self.set_status(STATUS_ERROR)


class UnifiedApp(tk.Tk):
    """AI Agent Workspace GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MultiAgentCoding — AI Agent Workspace")
        self.geometry("1180x760")
        self.minsize(860, 540)
        self.configure(bg=BG)

        self.workspace = PROJECT_ROOT  # mutable; updated by Change Directory

        # Queue bridging worker threads -> Tk main thread.
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.procs: dict[str, subprocess.Popen] = {}
        self.procs_lock = threading.Lock()
        self.running = 0  # only mutated on the main thread
        self._closing = False

        self._build_ui()
        self.after(POLL_MS, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self._configure_styles()

        container = ttk.Frame(self, padding=10, style="App.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        self.autoscroll_var = tk.BooleanVar(value=True)
        self.model_vars: dict[str, tk.StringVar] = {}

        # 1. Active workspace header.
        header_bar = ttk.Frame(container, style="Header.TFrame", padding=(12, 10))
        header_bar.pack(fill=tk.X, pady=(0, 8))
        self.workspace_var = tk.StringVar(value=f"📂 Workspace: {self.workspace}")
        ttk.Label(
            header_bar,
            textvariable=self.workspace_var,
            style="HeaderTitle.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            header_bar,
            text="Change Directory…",
            style="Accent.TButton",
            command=self._on_change_directory,
        ).pack(side=tk.RIGHT)

        # 2. Agent status dashboard.
        dash = ttk.Frame(container, style="App.TFrame")
        dash.pack(fill=tk.X, pady=(0, 8))
        self.badges: dict[str, StatusBadge] = {}
        for i, (tag, name, _) in enumerate(AGENTS):
            badge = StatusBadge(dash, tag, name, TAG_COLORS[tag], on_click=self._goto_agent_tab)
            badge.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4 if i < 6 else 0))
            self.badges[tag] = badge

        # 3. Main body: tabbed interface.
        body = ttk.Frame(container, style="App.TFrame")
        body.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(body, style="App.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Master Console tab.
        master_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=2)
        self.notebook.add(master_frame, text="💬 Master Console")
        self._build_model_selector(master_frame, "master")
        self.master_stream = StreamView(master_frame, autoscroll=self.autoscroll_var)

        # One tab per agent.
        self.agent_streams: dict[str, StreamView] = {}
        self.agent_tabs: dict[str, tk.Widget] = {}
        for tag, name, _ in AGENTS:
            agent_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=2)
            self.notebook.add(agent_frame, text=AGENT_TAB_LABELS[tag])
            self._build_model_selector(agent_frame, tag)
            self.agent_streams[tag] = StreamView(agent_frame, autoscroll=self.autoscroll_var)
            self.agent_tabs[tag] = agent_frame

        # 4. Interactive control bar.
        control = ttk.Frame(container, style="App.TFrame")
        control.pack(fill=tk.X, pady=(8, 0))

        # Quick action shortcuts (top row of the control bar).
        quick_row = ttk.Frame(control, style="App.TFrame")
        quick_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(quick_row, text="Quick actions:", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        for label, template in QUICK_ACTIONS:
            ttk.Button(
                quick_row,
                text=label,
                style="Quick.TButton",
                command=lambda t=template: self._prefill_prompt(t),
            ).pack(side=tk.LEFT, padx=(0, 4))

        # Prompt entry + run/clear + autoscroll.
        input_row = ttk.Frame(control, style="App.TFrame")
        input_row.pack(fill=tk.X)

        # Prompt area (multiline: Enter submits, Shift+Enter inserts a newline).
        self.prompt_text = tk.Text(
            input_row,
            height=4,
            wrap=tk.WORD,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=(FONT_FAMILY, FONT_SIZE),
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            padx=8,
            pady=6,
        )
        self.prompt_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.prompt_text.bind("<Return>", self._on_run_command)
        self.prompt_text.bind("<Shift-Return>", self._on_insert_newline)

        ttk.Checkbutton(
            input_row, text="Auto-scroll", variable=self.autoscroll_var, style="Muted.TCheckbutton"
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.run_btn = ttk.Button(
            input_row, text="RUN COMMAND", style="Accent.TButton", command=self._on_run_command
        )
        self.run_btn.pack(side=tk.LEFT, padx=(8, 4))

        self.clear_btn = ttk.Button(
            input_row, text="CLEAR LOGS", style="Danger.TButton", command=self._on_clear_logs
        )
        self.clear_btn.pack(side=tk.LEFT)

        self.prompt_text.focus_set()

    def _build_model_selector(self, parent: tk.Widget, tag: str) -> None:
        """Add a readonly model dropdown row at the top of a tab."""
        row = ttk.Frame(parent, style="App.TFrame")
        row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(row, text="Model:", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        var = tk.StringVar(value=AUTO_MODEL)
        combo = ttk.Combobox(
            row,
            textvariable=var,
            values=MODEL_OPTIONS,
            state="readonly",
            width=40,
            font=(FONT_FAMILY, 9),
        )
        combo.pack(side=tk.LEFT)
        self.model_vars[tag] = var

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("App.TFrame", background=BG)
        style.configure("Header.TFrame", background=HEADER_BG, relief=tk.FLAT)
        style.configure(
            "HeaderTitle.TLabel",
            background=HEADER_BG,
            foreground="#ffffff",
            font=(FONT_FAMILY, 11, "bold"),
        )
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(FONT_FAMILY, 9))

        style.configure("App.TNotebook", background=BG, borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            background=PANEL,
            foreground=TEXT,
            padding=(12, 6),
            font=(FONT_FAMILY, 9),
            borderwidth=0,
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", PANEL_ALT)],
            foreground=[("selected", "#ffffff")],
        )

        style.configure("Card.TFrame", background=PANEL, relief=tk.FLAT)
        style.configure("CardName.TLabel", background=PANEL, foreground=TEXT, font=(FONT_FAMILY, 9, "bold"))
        style.configure("CardStatus.TLabel", background=PANEL, foreground=TEXT, font=(FONT_FAMILY, 9))

        style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT)
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#ffffff",
            padding=(14, 7),
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("Accent.TButton", background=[("active", ACCENT_ACTIVE)])
        style.configure(
            "Danger.TButton",
            background="#7a2f2f",
            foreground="#ffffff",
            padding=(12, 7),
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#9c3d3d")])
        style.configure(
            "Quick.TButton",
            background=PANEL_ALT,
            foreground=TEXT,
            padding=(10, 5),
            font=(FONT_FAMILY, 9),
        )
        style.map("Quick.TButton", background=[("active", ACCENT)], foreground=[("active", "#ffffff")])
        style.configure("Muted.TCheckbutton", background=BG, foreground=TEXT, font=(FONT_FAMILY, 9))

    # -------------------------------------------------------------- helpers

    def _append_master(self, text: str, tag: str = "master") -> None:
        if self._closing:
            return
        self.master_stream.append(text, tag=tag)

    def _append_master_muted(self, text: str) -> None:
        if self._closing:
            return
        self.master_stream.append(text, tag="")

    def _goto_agent_tab(self, tag: str) -> None:
        frame = self.agent_tabs.get(tag)
        if frame is not None:
            self.notebook.select(frame)

    def _get_prompt(self) -> str:
        """Read the current prompt text (stripped)."""
        return self.prompt_text.get("1.0", tk.END).strip()

    def _prefill_prompt(self, template: str) -> None:
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", template)
        self.prompt_text.focus_set()

    def _on_insert_newline(self, _event=None) -> str:
        """Shift+Enter inserts a newline instead of submitting."""
        self.prompt_text.insert(tk.INSERT, "\n")
        return "break"

    def _on_change_directory(self) -> None:
        chosen = filedialog.askdirectory(
            title="Select Workspace Target Directory",
            initialdir=str(self.workspace),
        )
        if chosen:
            self.workspace = Path(chosen)
            self.workspace_var.set(f"📂 Workspace: {self.workspace}")

    # ------------------------------------------------------------- actions

    def _resolve_model(self, tag: str) -> str | None:
        """Resolve the model override for a tab.

        Priority: the agent tab's dropdown (if not Auto), then the Master
        Console dropdown (if not Auto), then None (use the agent's configured
        hybrid model from opencode.json).
        """
        var = self.model_vars.get(tag)
        if var is not None and var.get() != AUTO_MODEL:
            return var.get()
        master = self.model_vars.get("master")
        if master is not None and master.get() != AUTO_MODEL:
            return master.get()
        return None

    def _on_run_command(self, event=None) -> str:
        prompt = self._get_prompt()
        if not prompt:
            return "break"
        self.prompt_text.delete("1.0", tk.END)
        self._append_master(f"▶ {prompt}")

        for tag, name, agent in AGENTS:
            thread = threading.Thread(
                target=self._run_agent,
                args=(tag, name, agent, prompt),
                name=f"agent-{tag}",
                daemon=True,
            )
            thread.start()
            self.badges[tag].set_status_thinking()
            self._append_master_muted(f"→ {tag.upper()} {name}: thinking")

        self.running += len(AGENTS)
        return "break"

    def _run_agent(self, tag: str, name: str, agent: str, prompt: str) -> None:
        """Worker thread: run opencode for one agent, stream lines to the queue."""
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. "
                    "Install opencode or add it to PATH before using this launcher."
                )
            cmd = [exe, "run", "--agent", agent, "--auto"]
            # --auto auto-approves tool permissions (bash/file ops) so they are
            # not auto-rejected. (opencode run has no --yes/-y flag.)
            model = self._resolve_model(tag)
            if model:
                cmd += ["-m", model]
            cmd.append(prompt)
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with self.procs_lock:
                self.procs[tag] = proc
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    self.events.put(("line", tag, name, line))
            returncode = proc.wait()
            with self.procs_lock:
                self.procs.pop(tag, None)
            if returncode != 0:
                self.events.put(("error", tag, name, f"exit code {returncode}"))
            else:
                self.events.put(("done", tag, name, True))
        except Exception as exc:  # noqa: BLE001 — surface any worker failure in the UI
            self.events.put(("error", tag, name, f"ERROR: {exc}"))
            self.events.put(("done", tag, name, False))
        else:
            self.events.put(("done", tag, name, True))

    # -------------------------------------------------------------- event loop

    def _poll_events(self) -> None:
        """Drain worker output on the main thread (Tk is not thread-safe)."""
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "line":
                    _, tag, name, line = event
                    self.agent_streams[tag].append(f"[{tag} {name}] {line}", tag=tag)
                    self.badges[tag].set_status_active()
                elif kind == "error":
                    _, tag, name, message = event
                    self.agent_streams[tag].append_error(f"[{tag} {name}] {message}", tag=tag)
                    self.badges[tag].set_status_error()
                    self._append_master_muted(f"✗ {tag.upper()} {name}: {message}")
                elif kind == "done":
                    _, tag, name, success = event
                    if success:
                        self.badges[tag].set_status_idle()
                        self._append_master_muted(f"✓ {tag.upper()} {name}: finished")
                    self.running = max(0, self.running - 1)
        except queue.Empty:
            pass
        if not self._closing:
            self.after(POLL_MS, self._poll_events)

    # ---------------------------------------------------------------- cleanup

    def _on_clear_logs(self) -> None:
        self.master_stream.clear()
        for stream in self.agent_streams.values():
            stream.clear()

    def _terminate_all(self) -> None:
        with self.procs_lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass

    def _on_close(self) -> None:
        self._closing = True
        self._terminate_all()
        self.destroy()


def main() -> None:
    app = UnifiedApp()
    app.mainloop()
    sys.exit(0)


if __name__ == "__main__":
    main()