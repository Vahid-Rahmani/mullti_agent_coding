#!/usr/bin/env python3
"""
MultiAgentCoding — Unified Control Plane

A single-window launcher for the control-plane agents. One Tkinter window with:
  * a command input bar at the bottom where you type a prompt and press Enter,
  * a unified live terminal stream that shows every interaction in one place,
    with color-coded tags for each agent ([m1 System Architect] ... [m7 Reviewer]).

Submitting a prompt spawns one thread per agent running
    opencode run --agent <agent_name> "<prompt>"
and streams each agent's stdout/stderr into the single stream view.
No extra windows or split panes are opened.

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

# Per-tag foreground colors for the stream view.
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

FONT_FAMILY = "Consolas"
FONT_SIZE = 10
POLL_MS = 50  # how often the main thread drains the output queue


def _opencode_command() -> str | None:
    """Resolve the opencode executable path (PATHEXT-aware, Windows-safe).

    On Windows the CLI is shipped as ``opencode.cmd``; passing the bare name to
    ``subprocess.Popen`` with ``shell=False`` fails with WinError 2 because
    CreateProcess does not resolve ``.cmd``/``.bat`` via PATHEXT. ``shutil.which``
    resolves the full path so the child process can be located and executed.
    """
    return shutil.which("opencode") or shutil.which("opencode.cmd")


class UnifiedApp(tk.Tk):
    """Single-window unified launcher UI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("MultiAgentCoding — Unified Control Plane")
        self.geometry("1000x680")
        self.minsize(640, 400)
        self.configure(bg="#1e1e1e")

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
        container = ttk.Frame(self, padding=4)
        container.pack(fill=tk.BOTH, expand=True)

        # Title / status row.
        status_row = ttk.Frame(container)
        status_row.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(
            status_row,
            text="MultiAgentCoding — Unified Control Plane",
            font=(FONT_FAMILY, 10, "bold"),
        ).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_row, textvariable=self.status_var).pack(side=tk.RIGHT)

        # Unified live terminal stream.
        stream_frame = ttk.Frame(container)
        stream_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        self.stream = tk.Text(
            stream_frame,
            wrap=tk.WORD,
            bg="#121212",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            relief=tk.FLAT,
            font=(FONT_FAMILY, FONT_SIZE),
            state=tk.DISABLED,
        )
        scrollbar = ttk.Scrollbar(stream_frame, orient=tk.VERTICAL, command=self.stream.yview)
        self.stream.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stream.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Register text tags for each agent + master/system.
        self.stream.tag_configure("tag", foreground="#ffffff")
        for tag, color in TAG_COLORS.items():
            self.stream.tag_configure(f"tag_{tag}", foreground=color, font=(FONT_FAMILY, FONT_SIZE, "bold"))
        self.stream.tag_configure("body", foreground="#d4d4d4")
        self.stream.tag_configure("error", foreground="#ff5555")

        # Input bar (bottom) + Send button.
        input_row = ttk.Frame(container)
        input_row.pack(fill=tk.X, pady=(4, 0))

        self.entry = tk.Entry(
            input_row,
            bg="#2b2b2b",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            font=(FONT_FAMILY, FONT_SIZE),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
        self.entry.bind("<Return>", self._on_submit)

        self.send_btn = ttk.Button(input_row, text="Send to all agents", command=self._on_submit)
        self.send_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.entry.focus_set()

    # -------------------------------------------------------------- helpers

    def _append(self, text: str, tag: str = "") -> None:
        """Append a line to the stream (main thread only)."""
        if self._closing:
            return
        self.stream.configure(state=tk.NORMAL)
        if tag:
            self.stream.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.stream.insert(tk.END, text + "\n", "body")
        self.stream.see(tk.END)
        self.stream.configure(state=tk.DISABLED)

    def _append_error(self, text: str, tag: str = "") -> None:
        if self._closing:
            return
        self.stream.configure(state=tk.NORMAL)
        if tag:
            self.stream.insert(tk.END, f"[{tag}] ", (f"tag_{tag}", "tag"))
        self.stream.insert(tk.END, text + "\n", "error")
        self.stream.see(tk.END)
        self.stream.configure(state=tk.DISABLED)

    def _update_status(self) -> None:
        if self.running > 0:
            self.status_var.set(f"Running: {self.running} agent(s)")
        else:
            self.status_var.set("Ready")

    # ------------------------------------------------------------- actions

    def _on_submit(self, event=None) -> None:
        prompt = self.entry.get().strip()
        if not prompt:
            return
        self.entry.delete(0, tk.END)
        self._append(f"▶ {prompt}", tag="master")

        for tag, name, agent in AGENTS:
            thread = threading.Thread(
                target=self._run_agent,
                args=(tag, name, agent, prompt),
                name=f"agent-{tag}",
                daemon=True,
            )
            thread.start()

        self.running += len(AGENTS)
        self._update_status()

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
        except Exception as exc:  # noqa: BLE001 — surface any worker failure in the UI
            self.events.put(("error", tag, name, f"ERROR: {exc}"))
        finally:
            self.events.put(("done", tag, name))

    # -------------------------------------------------------------- event loop

    def _poll_events(self) -> None:
        """Drain worker output on the main thread (Tk is not thread-safe)."""
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "line":
                    _, tag, name, line = event
                    self._append(f"[{tag} {name}] {line}", tag=tag)
                elif kind == "error":
                    _, tag, name, message = event
                    self._append_error(f"[{tag} {name}] {message}", tag=tag)
                elif kind == "done":
                    self.running = max(0, self.running - 1)
                    self._update_status()
        except queue.Empty:
            pass
        if not self._closing:
            self.after(POLL_MS, self._poll_events)

    # ---------------------------------------------------------------- cleanup

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
