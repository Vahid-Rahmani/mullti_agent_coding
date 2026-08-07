#!/usr/bin/env python3
"""
MultiAgentCoding — Unified Control Plane (Tabbed Dashboard)

A modern single-window dashboard for the control-plane agents:
  * top header with 7 live status cards (m1..m7: 🟢 Idle / 🟡 Working / 🔴 Error),
  * a tabbed body: '💬 Master Console' (conversational feed + operation summary)
    plus one dedicated tab per agent (m1 System Architect ... m7 Reviewer),
  * a bottom input bar with 'RUN COMMAND' (broadcasts to all agents) and
    'CLEAR LOGS' buttons.

Submitting a prompt spawns one thread per agent running
    opencode run --agent <agent_name> "<prompt>"
and routes each agent's stdout/stderr into its own tab, keeping the Master
Console clean and readable.

Usage:
    python scripts/unified_app.py
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# Repo root = parent of this script's directory (scripts/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

# Per-tag accent colors (used for status cards, tab labels, and stream tags).
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
STATUS_IDLE = "🟢 Idle"
STATUS_WORKING = "🟡 Working"
STATUS_ERROR = "🔴 Error"

# Modern dark palette.
BG = "#1e1e1e"
PANEL = "#252526"
PANEL_ALT = "#2d2d30"
BORDER = "#3c3c3c"
TEXT = "#d4d4d4"
MUTED = "#9a9a9a"
ACCENT = "#0e639c"
ERROR = "#ff5555"
STREAM_BG = "#121212"

FONT_FAMILY = "Consolas"
FONT_SIZE = 10
POLL_MS = 50  # how often the main thread drains the output queue

AGENT_TAB_LABELS = {tag: f"{tag} {name}" for tag, name, _ in AGENTS}


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

    def __init__(self, parent: tk.Widget) -> None:
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
            padx=8,
            pady=6,
        )
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

    def append(self, text: str, tag: str = "") -> None:
        """Append a line (main thread only)."""
        self.configure(state=tk.NORMAL)
        if tag:
            self.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.insert(tk.END, text + "\n", "body")
        self.see(tk.END)
        self.configure(state=tk.DISABLED)

    def append_error(self, text: str, tag: str = "") -> None:
        """Append an error line (main thread only)."""
        self.configure(state=tk.NORMAL)
        if tag:
            self.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.insert(tk.END, text + "\n", "error")
        self.see(tk.END)
        self.configure(state=tk.DISABLED)

    def clear(self) -> None:
        """Clear all content (main thread only)."""
        self.configure(state=tk.NORMAL)
        self.delete("1.0", tk.END)
        self.configure(state=tk.DISABLED)


class StatusCard(ttk.Frame):
    """One agent status card: tag/name + live 🟢/🟡/🔴 indicator."""

    def __init__(self, parent: tk.Widget, tag: str, name: str, color: str) -> None:
        super().__init__(parent, style="Card.TFrame", padding=6)
        self.tag = tag
        self.color = color

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

        self.set_status_idle()

    def set_status(self, status: str) -> None:
        self.status_label.configure(text=status)

    def set_status_idle(self) -> None:
        self.set_status(STATUS_IDLE)

    def set_status_working(self) -> None:
        self.set_status(STATUS_WORKING)

    def set_status_error(self) -> None:
        self.set_status(STATUS_ERROR)


class UnifiedApp(tk.Tk):
    """Tabbed single-window unified dashboard."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MultiAgentCoding — Unified Control Plane")
        self.geometry("1100x720")
        self.minsize(800, 500)
        self.configure(bg=BG)

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

        container = ttk.Frame(self, padding=8, style="App.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        # 1. Top header: status cards row.
        header = ttk.Frame(container, style="App.TFrame")
        header.pack(fill=tk.X, pady=(0, 6))
        self.cards: dict[str, StatusCard] = {}
        for i, (tag, name, _) in enumerate(AGENTS):
            card = StatusCard(header, tag, name, TAG_COLORS[tag])
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4 if i < 6 else 0))
            self.cards[tag] = card

        # 2. Main body: tabbed interface.
        body = ttk.Frame(container, style="App.TFrame")
        body.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(body, style="App.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Master Console tab.
        master_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=2)
        self.notebook.add(master_frame, text="💬 Master Console")
        self.master_stream = StreamView(master_frame)

        # One tab per agent.
        self.agent_streams: dict[str, StreamView] = {}
        for tag, name, _ in AGENTS:
            agent_frame = ttk.Frame(self.notebook, style="App.TFrame", padding=2)
            self.notebook.add(agent_frame, text=AGENT_TAB_LABELS[tag])
            self.agent_streams[tag] = StreamView(agent_frame)

        # 3. Bottom input controls.
        input_row = ttk.Frame(container, style="App.TFrame")
        input_row.pack(fill=tk.X, pady=(6, 0))

        self.entry = tk.Entry(
            input_row,
            bg=PANEL,
            fg=TEXT,
            insertbackground=TEXT,
            relief=tk.FLAT,
            font=(FONT_FAMILY, FONT_SIZE),
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 0))
        self.entry.bind("<Return>", self._on_run_command)

        self.run_btn = ttk.Button(
            input_row, text="RUN COMMAND", style="Accent.TButton", command=self._on_run_command
        )
        self.run_btn.pack(side=tk.LEFT, padx=(6, 4))

        self.clear_btn = ttk.Button(
            input_row, text="CLEAR LOGS", style="Danger.TButton", command=self._on_clear_logs
        )
        self.clear_btn.pack(side=tk.LEFT)

        self.entry.focus_set()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("App.TFrame", background=BG)
        style.configure("App.TNotebook", background=BG, borderwidth=0)
        style.configure(
            "App.TNotebook.Tab",
            background=PANEL,
            foreground=TEXT,
            padding=(10, 5),
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
            padding=(12, 6),
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#1177bb")])
        style.configure(
            "Danger.TButton",
            background="#7a2f2f",
            foreground="#ffffff",
            padding=(12, 6),
            font=(FONT_FAMILY, 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", "#9c3d3d")])

    # -------------------------------------------------------------- helpers

    def _append_master(self, text: str, tag: str = "master") -> None:
        if self._closing:
            return
        self.master_stream.append(text, tag=tag)

    def _append_master_muted(self, text: str) -> None:
        if self._closing:
            return
        self.master_stream.append(text, tag="")

    def _update_status(self) -> None:
        pass  # status now lives on the per-agent cards

    # ------------------------------------------------------------- actions

    def _on_run_command(self, event=None) -> None:
        prompt = self.entry.get().strip()
        if not prompt:
            return
        self.entry.delete(0, tk.END)
        self._append_master(f"▶ {prompt}")

        for tag, name, agent in AGENTS:
            thread = threading.Thread(
                target=self._run_agent,
                args=(tag, name, agent, prompt),
                name=f"agent-{tag}",
                daemon=True,
            )
            thread.start()
            self.cards[tag].set_status_working()
            self._append_master_muted(f"→ {tag.upper()} {name}: started")

        self.running += len(AGENTS)

    def _run_agent(self, tag: str, name: str, agent: str, prompt: str) -> None:
        """Worker thread: run opencode for one agent, stream lines to the queue."""
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. "
                    "Install opencode or add it to PATH before using this launcher."
                )
            cmd = [exe, "run", "--agent", agent, prompt]
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
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
                elif kind == "error":
                    _, tag, name, message = event
                    self.agent_streams[tag].append_error(f"[{tag} {name}] {message}", tag=tag)
                    self.cards[tag].set_status_error()
                    self._append_master_muted(f"✗ {tag.upper()} {name}: {message}")
                elif kind == "done":
                    _, tag, name, success = event
                    if success:
                        self.cards[tag].set_status_idle()
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
