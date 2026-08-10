#!/usr/bin/env python3
"""ZOVA — MultiAgentCoding Retro Terminal.

A full-screen, retro-CRT style terminal UI for the control-plane agents. It
replaces the browser workspace (``web_app.py``) and the desktop GUI
(``unified_app.py``) as the single interactive way to talk to the agent swarm.

Look & feel (Git-inspired palette):
  * dark charcoal  shared background (#0d1117)
  * light grey     regular text and logs (#c9d1d9)
  * white          panel content, borders, and bottom controls
  * orange-red     agent tab outlines (#f85149)


Layout (single unified window with per-agent tabs):
  * an ASCII pixel-art ``ZOVA`` banner pinned at the top,
  * a live directory status indicator under the banner,
  * a tab bar: ``MASTER`` + one tab per agent (M1..M7), each with its own
    console so agents operate independently; F1..F7 select an agent tab,
    F8 selects MASTER, Ctrl+T cycles tabs, or use ``/tab <tag>``,
  * a model status bar (active tab / model / mode / running count),
  * shared bordered output panels in every agent tab for thinking, todo/tasks,
    and execution/code activity,
  * an interactive rounded prompt box at the bottom for typing coding tasks
    or slash commands.

A task typed on an agent tab is dispatched to that agent only; on the
MASTER tab it goes to all agents (or the ``/agents`` filter).

The run machinery is identical to the removed layers:

    opencode run --agent <a> --auto [-m <model>] [-agent <mode>] "<prompt>"

one thread per agent, output streamed (ANSI-stripped) into a shared console.
Pure stdlib + `rich`/`prompt_toolkit` for rendering; all hub/state/command
logic is importable and unit-testable without a terminal.

Usage:
    python scripts/terminal_app.py [--workspace <dir>] [--smoke]

Slash commands (typed at the prompt):
    /tab [tag]       switch tab: master, m1..m7, 'next', 'prev'
    /help            show this help
    /cd <path>       change the agents' working directory
    /model [t] [n]   show/set a tab's model override; bare /model opens menu
    /mode [t] [n]    show/set a tab's mode override; bare /mode opens menu
    /prompt [t] [x]  set/clear a specialized system prompt for a tab
    /prompts         list configured specialized system prompts
    /overrides       table of every tab's effective model/mode and source
    /agents [tags]   dispatch only to m1,m4 (comma list) or all
    /status          print current status line
    /clear           clear the console
    /stop            terminate all running agents
    /swarm           print live swarm helper state
    /proposals       list detected optimization-loop proposals
    /evolve <prompt> run a self-evolve cycle (checkpoint + dispatch + verify)
    /quit | /exit    leave the terminal
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import agent_logger  # dynamic per-agent Obsidian vault logging
import prompt_logger  # automated Obsidian vault prompt tracking

# Workspace root = the directory the launcher was launched from (so agents
# target whatever folder the terminal is started in), not the script dir.
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

# Tab bar order: the unified MASTER tab (all agents) + one tab per agent.
# (tag, label, opencode agent name; ``agent`` is None for the master tab).
TABS: list[tuple[str, str, str | None]] = [("master", "Master", None)] + [
    (tag, name, agent) for tag, name, agent in AGENTS
]

# Hub status values (lowercase, mirroring the removed web layer).
STATUS_IDLE = "idle"
STATUS_THINKING = "thinking"
STATUS_ACTIVE = "active"
STATUS_ERROR = "error"

# Model selector options. "Auto" lets each agent use its configured hybrid
# model from opencode.json; selecting a concrete model overrides it via -m.
AUTO_MODEL = "Auto (Smart Hybrid Routing)"
MODEL_OPTIONS = [
    AUTO_MODEL,
    "opencode/deepseek-v4-flash-free",
    "opencode/ling-3.0-tiny-free",
    "opencode/big-pickle",
]

# Mode selector options. "Auto (Default)" keeps the tab's default agent; a
# concrete mode is passed as `--agent <mode>`.
AUTO_MODE = "Auto (Default)"
# M7 Reviewer immutable audit mode — permanently locked to documentation
# auditing, vault integrity verification, and Roadmap.md synchronization.
M7_AUDIT_MODE = "obsidian-audit"
# Agent tags whose model and mode cannot be changed by the user.
IMMUTABLE_TAGS: set[str] = {"m7"}
MODE_OPTIONS_BY_MODEL: dict[str, list[str]] = {
    AUTO_MODEL: [AUTO_MODE],
    "opencode/deepseek-v4-flash-free": ["architect", "build", "analyze"],
    "opencode/big-pickle": ["plan", "build", "analyze"],
    "opencode/ling-3.0-tiny-free": [M7_AUDIT_MODE, "review", "compact"],
}

# Matches CSI (ANSI) sequences like \x1b[0m, \x1b[91m, \x1b[1m and OSC
# sequences like \x1b]...\x07.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a log string."""
    return _ANSI_RE.sub("", text)


# Marker inserted between the retained head and tail of an over-long prompt.
_TRUNCATE_MARKER = "… [truncated] …"


def prune_prompt(prompt: str, max_chars: int = 12000) -> str:
    """Reduce a prompt to a compact, dispatch-safe size.

    Strips ANSI escapes, collapses runs of 3+ blank lines to a single blank
    line, dedupes consecutive identical lines, and — if the result still
    exceeds ``max_chars`` — keeps the head (~40%) and tail (~60%) joined by a
    truncation marker. Never raises; empty input returns an empty string.
    """
    if not prompt:
        return ""
    text = _strip_ansi(prompt)
    lines = text.splitlines()
    pruned: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            run_len = j - i
            pruned.extend([""] * (1 if run_len >= 3 else run_len))
            i = j
        else:
            if pruned and pruned[-1] == line:
                i += 1
                continue
            pruned.append(line)
            i += 1
    result = "\n".join(pruned)
    if len(result) <= max_chars:
        return result
    head_len = int(max_chars * 0.4)
    tail_len = max_chars - head_len - len(_TRUNCATE_MARKER)
    if tail_len <= 0:
        return _TRUNCATE_MARKER
    return result[:head_len] + _TRUNCATE_MARKER + result[-tail_len:]


def _opencode_command() -> str | None:
    """Resolve the opencode executable path (PATHEXT-aware, Windows-safe).

    On Windows the CLI is shipped as ``opencode.cmd``; passing the bare name
    to ``subprocess.Popen`` with ``shell=False`` fails with WinError 2 because
    CreateProcess does not resolve ``.cmd``/``.bat`` via PATHEXT.
    """
    return shutil.which("opencode") or shutil.which("opencode.cmd")


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_prompt(prompt: str) -> str:
    """Strip control characters and leading whitespace from a raw prompt."""
    return _CONTROL_CHARS_RE.sub("", prompt).lstrip()


def _build_run_command(
    exe: str, agent: str, prompt: str, model: str | None, mode: str | None = None
) -> list[str]:
    """Build the ``opencode run`` argv for one agent.

    ``--auto`` auto-approves tool permissions. A model override inserts
    ``-m <model>`` before the prompt; a concrete mode is passed as
    ``--agent <mode>``. The prompt is a single argv element (never a shell
    string); a dash-leading prompt is guarded by a ``--`` separator.
    """
    chosen_agent = mode if mode and mode != AUTO_MODE else agent
    cmd = [exe, "run", "--agent", chosen_agent, "--auto"]
    if model:
        cmd += ["-m", model]
    prompt = _sanitize_prompt(prompt)
    if prompt.startswith("-"):
        cmd.append("--")
    cmd.append(prompt)
    return cmd


# --------------------------------------------------------------------------- progress telemetry

# The CLI stream does not currently expose provider token counters or a known
# task-total. Keep the visual telemetry deterministic and transparent: output
# progress follows the run lifecycle, while token usage is estimated from
# streamed characters against a nominal context budget.
TOKEN_CONTEXT_WINDOW = 8192
_TOKEN_CHARS_PER_TOKEN = 4
WORKING_LABEL = "working..."
_PROGRESS_BAR_WIDTH = 24


def _estimate_token_percent(prompt: str, output: list[str] | tuple[str, ...]) -> int:
    """Estimate prompt+stream token usage as a bounded percentage."""
    chars = len(prompt) + sum(len(line) for line in output)
    tokens = chars / _TOKEN_CHARS_PER_TOKEN
    return max(0, min(100, round(tokens / TOKEN_CONTEXT_WINDOW * 100)))


def _progress_bar_fragments(percent: int, width: int = _PROGRESS_BAR_WIDTH) -> list[tuple[str, str]]:
    """Render a percentage inside a compact retro progress bar."""
    percent = max(0, min(100, int(percent)))
    label = f" {percent:3d}% "
    slots = max(4, width - len(label) - 2)
    filled = round(slots * percent / 100)
    empty = slots - filled
    return [
        (f"bold {NEON}", "[" + "█" * filled),
        (f"bold {NEON}", label),
        ("class:retro.muted", "░" * empty + "]"),
    ]


def _working_fragments(now: float | None = None) -> list[tuple[str, str]]:
    """Render a left-to-right pulsing/chasing ``working...`` label.

    The neutral ZOVA palette supplies the fade steps: muted grey -> white ->
    light grey -> muted grey. ``now`` is injectable for deterministic
    tests; production uses the monotonic clock and the poller's redraw loop.
    """
    travel = max(1, len(WORKING_LABEL) * 2 - 2)
    phase = int((time.monotonic() if now is None else now) * 10) % travel
    head = phase if phase < len(WORKING_LABEL) else travel - phase
    fragments: list[tuple[str, str]] = []
    for index, char in enumerate(WORKING_LABEL):
        distance = abs(index - head)
        if distance == 0:
            style = f"bold {WHITE}"
        elif distance == 1:
            style = f"bold {GREY}"
        elif distance == 2:
            style = f"bold {GREY}"
        else:
            style = "class:retro.muted"
        fragments.append((style, char))
    return fragments


DEFAULT_PROGRESS_WEIGHTS: dict[str, float] = {tag: 1.0 for tag, _name, _agent in AGENTS}


def _weighted_progress(
    statuses: dict[str, str],
    progress: dict[str, int],
    tags: set[str] | list[str] | tuple[str, ...] | None = None,
    weights: dict[str, float] | None = None,
    terminal_value: int | None = None,
) -> int:
    """Return a bounded weighted progress average for the supplied tasks.

    When ``tags`` is omitted, only currently processing agents participate.
    A supplied session set also retains completed tasks at 100%, preventing the
    Master bar from jumping backwards when one sub-process finishes early.
    """
    task_tags = list(tags) if tags is not None else [
        tag for tag, _name, _agent in AGENTS
        if statuses.get(tag, STATUS_IDLE) in (STATUS_THINKING, STATUS_ACTIVE)
    ]
    if not task_tags:
        return 0
    weights = weights or DEFAULT_PROGRESS_WEIGHTS
    total_weight = 0.0
    weighted_total = 0.0
    for tag in task_tags:
        weight = max(0.0, float(weights.get(tag, 1.0)))
        if not weight:
            continue
        value = (
            terminal_value
            if statuses.get(tag) == STATUS_IDLE and tags is not None and terminal_value is not None
            else (100 if statuses.get(tag) == STATUS_IDLE and tags is not None else progress.get(tag, 0))
        )
        weighted_total += weight * max(0, min(100, int(value)))
        total_weight += weight
    if not total_weight:
        return 0
    # Use conventional half-up rounding rather than Python's banker's
    # rounding so weighted values such as 62.5 display as 63%.
    return max(0, min(100, int(weighted_total / total_weight + 0.5)))


def _loading_bar_fragments(
    statuses: dict[str, str],
    progress: dict[str, int] | None = None,
    token_usage: dict[str, int] | None = None,
    current_tab: str = "master",
    session_tags: set[str] | list[str] | tuple[str, ...] | None = None,
    weights: dict[str, float] | None = None,
    now: float | None = None,
    width: int = 80,
) -> list[tuple]:
    """Render the single loading bar shown immediately above the prompt.

    Agent tabs show that tab's task. MASTER shows the weighted aggregate of
    the current run session. The inactive state still occupies this one fixed
    row, so the prompt never moves when work starts or finishes.
    """
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
            _weighted_progress(
                statuses, token_usage, visible_tags, weights, terminal_value=0
            )
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
    working = _working_fragments(now) if active else [("class:retro.muted", "idle")]
    bar_width = max(10, min(_PROGRESS_BAR_WIDTH, width - len(prefix) - len(suffix) - 12))
    fragments: list[tuple] = [("class:retro.progress", prefix)]
    fragments.extend(_progress_bar_fragments(percent, bar_width))
    fragments.append(("class:retro.progress", " "))
    fragments.extend(working)
    # The window has a fixed height of one row; do not append a newline, or
    # prompt_toolkit allocates an extra blank row between loading and prompt.
    fragments.append(("class:retro.progress", suffix))
    return fragments


# --------------------------------------------------------------------------- state tracker


def _state_escape(text: str) -> str:
    """Escape backslashes/newlines for a single-line state.md field."""
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def _state_unescape(text: str) -> str:
    """Invert _state_escape (only ``\\n`` and ``\\\\`` are escaped)."""
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt == "n" else nxt)
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


class StateTracker:
    """Read/write the workspace ``state.md`` checkpoint (sections format).

    Writes mirror ``_write_config`` (temp file + ``os.replace``) so a crash
    never leaves a half-written state file. Never touches ``knowledge/`` or
    writes API keys/secrets.
    """

    MAX_COMPLETED = 20

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else PROJECT_ROOT / "state.md"
        self.lock = threading.Lock()

    def load(self) -> dict | None:
        """Parse state.md into a dict, or None when missing/corrupt."""
        if not self.path.exists():
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        return self._parse(text)

    def update(self, **fields: object) -> dict:
        """Merge ``fields`` into the on-disk state and write atomically."""
        return self._mutate(lambda data: data.update(fields))

    def record_run(self, prompt: str, started: str) -> dict:
        return self.update(phase="running", last_run={"prompt": prompt, "started": started})

    def record_finish(self, tag: str, ok: bool) -> dict:
        return self._mutate(
            lambda data: data.setdefault("completed", []).append(
                f"{tag}: {'ok' if ok else 'failed'}"
            )
        )

    def record_decision(self, text: str) -> dict:
        return self._mutate(lambda data: data.setdefault("decisions", []).append(text))

    def record_pending_modification(self, detail: str) -> dict:
        return self.update(pending_modification=detail)

    def clear_pending_modification(self) -> dict:
        return self.update(pending_modification=None)

    def record_restart(self, action: str, result: str) -> dict:
        return self._mutate(
            lambda data: data.setdefault("restart_log", []).append(f"{action}: {result}")
        )

    # ------------------------------------------------------------ internals

    def _mutate(self, transform) -> dict:
        with self.lock:
            data = self.load() or {}
            transform(data)
            data = self._compress(data)
            self._write(data)
            return data

    def _compress(self, data: dict) -> dict:
        """Trim ``## Completed`` beyond MAX_COMPLETED into a summary line."""
        completed = list(data.get("completed") or [])
        if len(completed) > self.MAX_COMPLETED:
            excess = len(completed) - self.MAX_COMPLETED
            data["completed"] = [f"… {excess} earlier finishes compressed"] + completed[-self.MAX_COMPLETED:]
        return data

    def _parse(self, text: str) -> dict | None:
        """Split ``## Section`` blocks; None when no sections are present."""
        sections: dict[str, list[str]] = {}
        current: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current = stripped[3:].strip()
                sections[current] = []
            elif current is not None:
                sections[current].append(line)
        if not sections:
            return None

        phase_lines = sections.get("Phase") or []
        phase = phase_lines[0].strip() if phase_lines and phase_lines[0].strip() else "idle"

        last_run = None
        run_lines = sections.get("Last Run") or []
        if run_lines:
            prompt = ""
            started = ""
            for line in run_lines:
                if line.startswith("prompt:"):
                    prompt = _state_unescape(line[len("prompt:"):].strip())
                elif line.startswith("started:"):
                    started = line[len("started:"):].strip()
            last_run = {"prompt": prompt, "started": started}

        def bullets(name: str) -> list[str]:
            out = []
            for line in sections.get(name) or []:
                item = line.strip().lstrip("-").strip()
                if item:
                    out.append(item)
            return out

        pending = "\n".join(sections.get("Pending Modification") or []).strip()

        return {
            "phase": phase,
            "last_run": last_run,
            "completed": bullets("Completed"),
            "active_worktrees": bullets("Active Worktrees"),
            "decisions": bullets("Decisions"),
            "pending_modification": pending or None,
            "restart_log": bullets("Restart Log"),
        }

    def _render(self, data: dict) -> str:
        lines = ["# State", ""]
        lines += ["## Phase", str(data.get("phase") or "idle"), ""]
        last_run = data.get("last_run")
        if last_run:
            lines += [
                "## Last Run",
                f"prompt: {_state_escape(str(last_run.get('prompt', '')))}",
                f"started: {str(last_run.get('started', ''))}",
                "",
            ]
        for key, heading in (
            ("completed", "Completed"),
            ("active_worktrees", "Active Worktrees"),
            ("decisions", "Decisions"),
        ):
            lines += [f"## {heading}"]
            lines += [f"- {entry}" for entry in (data.get(key) or [])]
            lines.append("")
        lines += ["## Pending Modification"]
        pending = data.get("pending_modification")
        if pending:
            lines.append(str(pending))
        lines.append("")
        lines += ["## Restart Log"]
        lines += [f"- {entry}" for entry in (data.get("restart_log") or [])]
        lines.append("")
        return "\n".join(lines)

    def _write(self, data: dict) -> None:
        """Atomic write via temp file + replace."""
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(parent), suffix=".state.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._render(data))
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


STATE = StateTracker()

# --------------------------------------------------------------------------- run hub


class RunHub:
    """Thread-safe shared state for live agent runs (mirrors the removed WebHub).

    Events carry a monotonically increasing sequence number so the terminal
    can resume from any cursor. ``run`` spawns one worker thread per target
    agent; each thread streams ``opencode run`` output into per-tag buffers.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.statuses: dict[str, str] = {tag: STATUS_IDLE for tag, _, _ in AGENTS}
        self.progress: dict[str, int] = {tag: 0 for tag, _, _ in AGENTS}
        self.token_usage: dict[str, int] = {tag: 0 for tag, _, _ in AGENTS}
        self.prompts: dict[str, str] = {tag: "" for tag, _, _ in AGENTS}
        self.buffers: dict[str, list[str]] = {tag: [] for tag, _, _ in AGENTS}
        self.buffers["master"] = []
        self.events: list[dict] = []  # {"seq", "tag", "kind", "text"}
        self.seq = 0
        self.procs: dict[str, subprocess.Popen] = {}
        self.running = 0
        # Tags participating in the current dispatch session. Completed tasks
        # remain in this set until the session is fully idle, allowing Master
        # aggregation to count them as 100% instead of dropping their weight.
        self.session_tags: set[str] = set()
        self.progress_weights: dict[str, float] = dict(DEFAULT_PROGRESS_WEIGHTS)
        self.workspace: Path = PROJECT_ROOT

    # ------------------------------------------------------------ state writes

    def _emit(self, tag: str, kind: str, text: str) -> None:
        with self.lock:
            self.seq += 1
            self.events.append({"seq": self.seq, "tag": tag, "kind": kind, "text": _strip_ansi(text)})

    def set_status(self, tag: str, status: str) -> None:
        with self.lock:
            self.statuses[tag] = status
            if status == STATUS_THINKING:
                self.progress[tag] = max(self.progress.get(tag, 0), 8)
            elif status == STATUS_ACTIVE:
                self.progress[tag] = max(self.progress.get(tag, 0), 18)
            elif status == STATUS_IDLE:
                self.progress[tag] = 100
            elif status == STATUS_ERROR:
                # An errored worker is terminal for aggregation purposes; the
                # unified bar should not remain stuck on its partial value.
                self.progress[tag] = 100
        self._emit(tag, "status", status)

    def append_line(self, tag: str, text: str) -> None:
        with self.lock:
            self.buffers[tag].append(text)
            output_lines = len(self.buffers[tag])
            # No task-total is available from the CLI, so show steady
            # lifecycle progress without falsely claiming exact completion.
            self.progress[tag] = min(92, max(self.progress.get(tag, 0), 18 + output_lines * 3))
            self.token_usage[tag] = _estimate_token_percent(
                self.prompts.get(tag, ""), self.buffers[tag]
            )
        self._emit(tag, "line", text)

    def append_error(self, tag: str, text: str) -> None:
        with self.lock:
            self.buffers[tag].append(text)
            self.token_usage[tag] = _estimate_token_percent(
                self.prompts.get(tag, ""), self.buffers[tag]
            )
        self._emit(tag, "error", text)

    def clear(self) -> None:
        with self.lock:
            for buf in self.buffers.values():
                buf.clear()
            for tag, _name, _agent in AGENTS:
                self.statuses[tag] = STATUS_IDLE
                self.progress[tag] = 0
                self.token_usage[tag] = 0
                self.prompts[tag] = ""
            self.session_tags.clear()
        self._emit("master", "line", "── logs cleared ──")

    # ------------------------------------------------------------ running

    def resolve(self, tag: str, overrides: dict[str, dict[str, str]]) -> tuple[str | None, str]:
        """Resolve (model, mode) for a tag: tag override > master override > auto.

        Immutable tags (e.g. M7) ignore all overrides and always return their
        locked configuration."""
        if tag in IMMUTABLE_TAGS:
            # M7 is permanently locked to ling-3.0-tiny-free + obsidian-audit.
            return ("opencode/ling-3.0-tiny-free", M7_AUDIT_MODE)
        tab = overrides.get(tag, {})
        master = overrides.get("master", {})
        tab_model = tab.get("model")
        master_model = master.get("model")
        if tab_model and tab_model != AUTO_MODEL:
            model = tab_model
        elif master_model and master_model != AUTO_MODEL:
            model = master_model
        else:
            model = None
        tab_mode = tab.get("mode")
        master_mode = master.get("mode")
        if tab_mode and tab_mode != AUTO_MODE:
            mode = tab_mode
        elif master_mode and master_mode != AUTO_MODE:
            mode = master_mode
        else:
            mode = AUTO_MODE
        return model, mode

    def run(
        self,
        prompt: str,
        overrides: dict[str, dict[str, str]],
        agents: list[str] | None = None,
        system_prompts: dict[str, str] | None = None,
    ) -> str | None:
        """Spawn one worker thread per target agent.

        ``agents`` optionally restricts dispatch to a subset of tags (e.g.
        ``["m1", "m4"]``). Returns an error string, or None on success.
        """
        if not prompt.strip():
            return "Prompt must not be empty."
        targets = [a for a in AGENTS if not agents or a[0] in agents]
        if not targets:
            return "No agents matched the /agents filter."
        # Log the prompt into the Obsidian vault for end-to-end traceability.
        try:
            # Derive the active tab: the single-agent tag when filtered,
            # "master" when dispatching to all agents.
            _log_tab = agents[0] if agents and len(agents) == 1 else "master"
            _target_tags = [t[0] for t in targets] if agents else None
            _prompt_path = prompt_logger.log_prompt(
                prompt,
                target_agents=_target_tags,
                active_tab=_log_tab,
            )
            # Store the session ID for per-agent run back-linking.
            _prompt_log_id = _prompt_path.stem
            # Ensure agent log files exist for every dispatched agent.
            agent_logger.ensure_agent_logs(
                [t[0] for t in targets],
            )
        except Exception:
            pass  # prompt/agent logging is best-effort; never block the dispatch
        self.append_line("master", f"▶ {prompt}")
        pruned = prune_prompt(prompt)
        STATE.record_run(pruned, time.strftime("%Y-%m-%dT%H:%M:%S"))
        system_prompts = system_prompts or {}
        dispatch_prompts: dict[str, str] = {}
        with self.lock:
            if self.running == 0:
                self.session_tags.clear()
            self.session_tags.update(tag for tag, _name, _agent in targets)
            self.running += len(targets)
            for tag, _name, _agent in targets:
                specialized = system_prompts.get(tag) or system_prompts.get("master")
                dispatch_prompt = pruned
                if specialized and specialized.strip():
                    dispatch_prompt = (
                        "[SPECIALIZED SYSTEM PROMPT]\n"
                        + specialized.strip()
                        + "\n\n[USER TASK]\n"
                        + pruned
                    )
                dispatch_prompts[tag] = dispatch_prompt
                self.progress[tag] = 5
                self.token_usage[tag] = _estimate_token_percent(dispatch_prompt, [])
                self.prompts[tag] = dispatch_prompt
        for tag, _name, agent in targets:
            # A run separator resets the visible block context for this agent
            # and makes consecutive runs easy to scan in every tab.
            self._emit(tag, "run", _run_header(prompt, tag.upper()))
            model, mode = self.resolve(tag, overrides)
            self.set_status(tag, STATUS_THINKING)
            dispatch_prompt = dispatch_prompts.get(tag, pruned)
            threading.Thread(
                target=self._run_agent,
                args=(tag, agent, dispatch_prompt, model, mode, _prompt_log_id),
                name=f"term-{tag}",
                daemon=True,
            ).start()
        return None

    def _run_agent(
        self,
        tag: str,
        agent: str,
        prompt: str,
        model: str | None,
        mode: str | None,
        prompt_log_id: str | None = None,
    ) -> None:
        _start = time.time()
        ok = False
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. Install opencode or "
                    "add it to PATH before using the terminal."
                )
            cmd = _build_run_command(exe, agent, prompt, model, mode)
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
            with self.lock:
                self.procs[tag] = proc
            # Lines are stored without an embedded agent prefix: the console
            # renderer adds exactly one ``[m4]`` tag, so no double tags like
            # ``[m4] [m4 Backend Dev]`` ever appear.
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    self.append_line(tag, line)
                    self.set_status(tag, STATUS_ACTIVE)
            returncode = proc.wait()
            with self.lock:
                self.procs.pop(tag, None)
            if returncode != 0:
                self.append_error(tag, f"exit code {returncode}")
                self.set_status(tag, STATUS_ERROR)
            else:
                ok = True
                self.set_status(tag, STATUS_IDLE)
        except Exception as exc:  # noqa: BLE001 — surface in the UI
            self.append_error(tag, str(exc))
            self.set_status(tag, STATUS_ERROR)
        finally:
            with self.lock:
                self.running = max(0, self.running - 1)
                if self.running == 0:
                    # The session is complete; the next dispatch starts a new
                    # weighted denominator and the idle bar stays at 0%.
                    self.session_tags.clear()
            STATE.record_finish(tag, ok)
            # Append to the agent's Obsidian vault run log (best-effort).
            try:
                if prompt_log_id:
                    agent_logger.append_agent_run(
                        tag,
                        prompt,
                        prompt_log_id,
                        status="ok" if ok else "failed",
                        duration_s=time.time() - _start,
                    )
            except Exception:
                pass
            # M7 audit: when M7 finishes and the dispatch is complete, run
            # the vault integrity check + cross-reference + roadmap sync.
            if tag == "m7" and ok:
                self._run_m7_audit()

    def aggregate_progress(self) -> int:
        """Return the current weighted Master progress under the hub lock."""
        with self.lock:
            tags = set(self.session_tags)
            if not tags:
                tags = {
                    tag for tag, _name, _agent in AGENTS
                    if self.statuses.get(tag) in (STATUS_THINKING, STATUS_ACTIVE)
                }
            if not any(
                self.statuses.get(tag) in (STATUS_THINKING, STATUS_ACTIVE)
                for tag in tags
            ):
                return 0
            return _weighted_progress(
                self.statuses,
                self.progress,
                tags or None,
                self.progress_weights,
            )

    def loading_snapshot(self, current_tab: str) -> dict:
        """Copy the telemetry needed by the single loading-bar renderer."""
        with self.lock:
            return {
                "statuses": dict(self.statuses),
                "progress": dict(self.progress),
                "token_usage": dict(self.token_usage),
                "session_tags": set(self.session_tags),
                "weights": dict(self.progress_weights),
                "current_tab": current_tab,
            }

    def terminate_all(self) -> None:
        with self.lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        with self.lock:
            self.running = 0
            self.session_tags.clear()
            for tag, _name, _agent in AGENTS:
                if self.statuses.get(tag) in (STATUS_THINKING, STATUS_ACTIVE):
                    self.statuses[tag] = STATUS_IDLE
                    self.progress[tag] = 0
                    self.token_usage[tag] = 0
        self.append_line("master", "── terminated ──")
        STATE.record_restart("interrupted", "terminated by user")

    def _run_m7_audit(self) -> None:
        """Run the M7 vault audit (best-effort; never blocks the hub).

        Spawned on a daemon thread after M7 completes so the audit never
        blocks the hub or subsequent dispatches.
        """
        def _audit() -> None:
            try:
                import obsidian_auditor

                result = obsidian_auditor.audit_run()
                self.append_line("master", result["summary"])
                if not result["ok"]:
                    for issue in result.get("integrity", {}).get("issues", []):
                        self.append_line("m7", f"AUDIT: {issue}")
                    for orphan in result.get("cross_ref", {}).get("orphaned_prompts", []):
                        self.append_line("m7", f"AUDIT: orphaned prompt {orphan}")
            except Exception:
                pass  # audit failures are cosmetic — never disrupt the hub

        threading.Thread(
            target=_audit,
            name="m7-audit",
            daemon=True,
        ).start()


HUB = RunHub()

# --------------------------------------------------------------------------- self-evolve engine

from self_evolve import SelfEvolveEngine, detect_optimization_loops  # noqa: E402

SELF_EVOLVE_ENGINE = SelfEvolveEngine(
    project_root=PROJECT_ROOT,
    record_decision=lambda text: STATE.record_decision(text),
)


def _after_self_evolve_run(prompt: str, overrides: dict) -> None:
    """Wait for the dispatched swarm run, then verify and write the marker.

    The whole body is guarded so an unexpected verify/marker error is recorded
    to state.md instead of killing the terminal loop.
    """
    try:
        while HUB.running > 0:
            time.sleep(0.2)
        result = SELF_EVOLVE_ENGINE.verify()
        if result["ok"]:
            SELF_EVOLVE_ENGINE.write_restart_marker(
                payload={"source": "self-evolve", "prompt": prompt, "ok": True, "verified": True}
            )
        else:
            STATE.record_restart("verify", "failed: " + "; ".join(result.get("errors") or []))
    except Exception as exc:  # noqa: BLE001 — watcher must never crash the loop
        STATE.record_restart("verify", "exception: " + str(exc))


def _spawn_self_evolve_watcher(prompt: str, overrides: dict) -> None:
    """Start the verify+marker watcher on a daemon thread (patchable in tests)."""
    threading.Thread(
        target=_after_self_evolve_run,
        args=(prompt, overrides),
        name="self-evolve-watcher",
        daemon=True,
    ).start()


def run_self_evolve(
    prompt: str,
    overrides: dict,
    system_prompts: dict[str, str] | None = None,
) -> str | None:
    """Checkpoint + dispatch a self-evolve cycle (terminal '/evolve' command)."""
    if not prompt.strip():
        return "Usage: /evolve <prompt>"
    checkpoint = SELF_EVOLVE_ENGINE.checkpoint(prompt)
    err = HUB.run(prompt, overrides, system_prompts=system_prompts)
    if err:
        return err
    _spawn_self_evolve_watcher(prompt, overrides)
    return f"self-evolve checkpointed @ {checkpoint['git_head'] or 'no-git'}: {prompt}"


# --------------------------------------------------------------------------- retro chrome


def _swarm_state() -> str:
    """Live swarm helper state for the '/swarm' command (empty when absent)."""
    swarm_dir = PROJECT_ROOT / "_logs" / "swarm"
    if not swarm_dir.is_dir():
        return "no swarm state (_logs/swarm missing) — run launch_agents.bat first"
    try:
        from swarm import read_swarm_state

        state = read_swarm_state(swarm_dir)
    except Exception as exc:  # noqa: BLE001
        return f"swarm state unreadable: {exc}"
    if not state:
        return "swarm state is empty"
    rows = []
    for slot, data in sorted(state.items()):
        status = data.get("status", "?")
        target = data.get("target")
        title = data.get("title", "")
        rows.append(f"M{slot}: {status}" + (f" -> M{target}" if target else "") + (f" ({title})" if title else ""))
    return " | ".join(rows)


def build_help_text() -> str:
    """Text for the '/help' command."""
    return (
        "ZOVA commands:\n"
        "  /tab [tag]       switch tab: master, m1..m7, 'next', 'prev'\n"
        "  /help            show this help\n"
        "  /cd <path>       change the agents' working directory\n"
        "  /model [t] [n]   show/set a tab's model override\n"
        "                   (t = active tab, m1..m7, master, all; '' -> auto)\n"
        "  /mode [t] [n]    show/set a tab's mode override (same target syntax)\n"
        "  /prompt [t] [x]  set/clear a specialized system prompt (off by default)\n"
        "  /prompts         list all specialized prompts and their status\n"
        "  /overrides       table of per-tab model/mode overrides\n"
        "  /agents [tags]   dispatch only to m1,m4 (comma list) or 'all'\n"
        "  /status          print current status line\n"
        "  /clear           clear the console\n"
        "  /stop            terminate all running agents\n"
        "  /swarm           print live swarm helper state\n"
        "  /proposals       list detected optimization-loop proposals\n"
        "  /evolve <prompt> run a self-evolve cycle (checkpoint + dispatch + verify)\n"
        "  /quit | /exit    leave the terminal\n"
        "\n"
        "Tabs: F1..F7 select an agent (M1..M7), F8 selects MASTER (all agents),"
        "Ctrl+T cycles. A task typed on an agent tab dispatches to that agent\n"
        "only; on MASTER it goes to all agents (or the /agents filter).\n"
        "Anything else is dispatched to the agent swarm:\n"
        "  opencode run --agent <a> --auto [-m <model>] \"<prompt>\"\n"
    )


def build_overrides_table(overrides: dict[str, dict[str, str]]) -> str:
    """Render every tab's effective model/mode as an aligned table.

    One row per tab (MASTER + M1..M7) with the resolved model/mode and a
    SRC column: 'set' = explicit override on this tab, 'master' = inherited
    from the master override, 'auto' = no override anywhere.
    """
    rows: list[tuple[str, str, str, str]] = []
    for tag, _name, _agent in TABS:
        model, mode = HUB.resolve(tag, overrides)
        model_text = model or "auto"
        mode_text = "auto" if mode == AUTO_MODE else mode
        over = overrides.get(tag, {})
        master = overrides.get("master", {})
        explicit = (
            over.get("model") not in (None, AUTO_MODEL)
            or over.get("mode") not in (None, AUTO_MODE)
        )
        master_has = (
            master.get("model") not in (None, AUTO_MODEL)
            or master.get("mode") not in (None, AUTO_MODE)
        )
        src = "set" if explicit else ("master" if master_has else "auto")
        rows.append((tag.upper(), model_text, mode_text, src))
    label_w = max(len(r[0]) for r in rows)
    model_w = max(len(r[1]) for r in rows)
    mode_w = max(len(r[2]) for r in rows)

    def fmt(label: str, model: str, mode: str, src: str) -> str:
        return f"{label:<{label_w}}  {model:<{model_w}}  {mode:<{mode_w}}  {src}"

    header = fmt("TAB", "MODEL", "MODE", "SRC")
    lines = [header, "-" * len(header)]
    lines += [fmt(*row) for row in rows]
    return "\n".join(lines)


def parse_command(text: str) -> tuple[str, str] | None:
    """Split a slash command into (name, arg); None for non-commands."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped[1:].split(None, 1)
    name = (parts[0] if parts else "").lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return (name, arg)


def _format_proposals() -> str:
    """Render detected optimization proposals as console text."""
    proposals = detect_optimization_loops()
    if not proposals:
        return "no optimization-loop proposals detected"
    lines = []
    for p in proposals:
        lines.append(f"  [{p.id}] x{p.count} — {p.suggestion}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- retro rendering

# ASCII pixel-art "ZOVA" banner (block glyphs; one string per row).
BANNER = [
    "████████╗ ████████╗ ██╗   ██╗ ████████╗",
    "    ████╝ ██╗   ██╗ ██║   ██║ ██╔═══██╗",
    "   ████╝  ██║   ██║ ██║   ██║ ████████╗",
    "  ████╝   ██║   ██║ ╚██╗ ██╔╝ ██║   ██║",
    " ████╝    ╚██████╔╝  ╚████╔╝  ██║   ██║",
    "╚═══════╝ ╚═══════╝   ╚═══╝   ╚═╝   ╚═╝",
]

# GitHub-inspired ZOVA palette. Keep semantic aliases for existing helpers,
# but do not reintroduce the previous neon-green scheme.
BLACK = "#0d1117"      # dark charcoal/slate global background
GREY = "#c9d1d9"       # regular text, logs, and muted status
WHITE = "#ffffff"      # panel content, borders, and bottom controls
ORANGE = "#f85149"     # enclosed agent-tab outlines
NEON = GREY             # compatibility alias; intentionally not green
GREY_BG = "#161b22"    # subtle input surface within the charcoal background

STATUS_SYMBOL = {
    # Active/thinking work intentionally shares the neutral idle glyph: the
    # unified loading row above the prompt is the sole active-task indicator.
    STATUS_IDLE: ("●", GREY),
    STATUS_THINKING: ("●", GREY),
    STATUS_ACTIVE: ("●", GREY),
    STATUS_ERROR: ("✕", ORANGE),
}


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
) -> list[tuple]:
    """Render bottom chrome segments, optionally attaching mouse actions.

    The full labels remain the public/helper default. The prompt frame uses a
    compact form so every control remains visible and clickable on small
    terminals instead of being clipped by a long model name.
    """
    model, mode = HUB.resolve(current_tab, overrides)
    target = current_tab if current_tab != "master" else (
        ",".join(agents_filter) if agents_filter else "all"
    )
    running = HUB.running
    if ultra_compact:
        model_text = "Auto" if not model or model == AUTO_MODEL else model.split("/")[-1]
        mode_text = "Auto" if not mode or mode == AUTO_MODE else mode
        controls = [
            ("tab", f"T:{current_tab.upper()}"),
            ("model", f"M:{model_text}"),
            ("mode", f"D:{mode_text}"),
            ("target", f"G:{target[:8]}"),
            ("run", f"R:{running}/{len(AGENTS)}"),
        ]
    elif compact:
        model_text = "Auto" if not model or model == AUTO_MODEL else model
        mode_text = "Auto" if mode == AUTO_MODE else (mode or AUTO_MODE)
        controls = [
            ("tab", f"TAB {current_tab.upper()}"),
            ("model", f"AI MODEL {model_text}"),
            ("mode", f"MODE {mode_text}"),
            ("target", f"TARGET {target}"),
            ("run", f"RUN {running}/{len(AGENTS)}"),
        ]
    else:
        controls = [
            ("tab", f"TAB {current_tab.upper()}"),
            ("model", f"AI MODEL {model or AUTO_MODEL}"),
            ("mode", f"MODE {mode or AUTO_MODE}"),
            ("target", f"TARGET {target}"),
            ("run", f"RUN {running}/{len(AGENTS)}"),
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
            # Each actionable control is a complete white-framed button;
            # separators are intentionally outside the hit target.
            visible = f"⟦ {label} ⟧ "
        else:
            visible = f"{label} "
        if handler is None:
            fragments.append((style, visible))
        else:
            fragments.append((style, visible, handler))
    return fragments


def _dashboard_fragments(
    statuses: dict[str, str],
    current_tab: str = "master",
    on_tab_click=None,
    width: int | None = None,
) -> list[tuple]:
    """Render MASTER/M1..M7 as visibly bordered tab buttons.

    The default two-item fragments keep this helper convenient for headless
    rendering/tests. When ``on_tab_click`` is supplied, each complete tab cell
    gets a prompt_toolkit mouse handler as its third fragment item.
    """
    fragments: list[tuple] = []
    row_width = 0
    for tag, name, _agent in TABS:
        status = statuses.get(tag, STATUS_IDLE)
        symbol, _color = STATUS_SYMBOL.get(status, STATUS_SYMBOL[STATUS_IDLE])
        active = tag == current_tab
        label = "MASTER" if tag == "master" else f"{tag.upper()} {name}"
        # Every tab gets the same crisp outline. On narrow terminals the
        # display label is intentionally shortened rather than split halfway
        # through a button; the full name remains available at normal widths.
        cell = f"⟦{symbol} {label}⟧ "
        if width is not None and len(cell.rstrip()) > max(10, width):
            short_label = "MASTER" if tag == "master" else tag.upper()
            cell = f"⟦{symbol} {short_label}⟧ "
        if active:
            style = "class:retro.tab.active"
        else:
            # Do not encode task activity in individual tabs; the fixed
            # loading row immediately above the prompt owns that state.
            style = "class:retro.tab.inactive"
        if on_tab_click is None:
            fragment = (style, cell)
        else:
            def click(event, _tag=tag):
                on_tab_click(_tag, event)
            fragment = (style, cell, click)
        # Wrap complete cells between rows. Never let prompt_toolkit break a
        # long agent name in the middle of an outlined tab button.
        if width is not None:
            if row_width and row_width + len(cell) > max(10, width):
                fragments.append(("class:retro.dash", "\n"))
                row_width = 0
            row_width += len(cell)
        fragments.append(fragment)
    return fragments


# Lower panels are intentionally taller than the original one-line chrome, but
# remain Dimensions so prompt_toolkit can shrink them on short terminals.
INPUT_MIN_LINES = 3
INPUT_MAX_LINES = 12
CONSOLE_MIN_LINES = 5
CONSOLE_PREFERRED_LINES = 12


# Structured output panels. The stream remains stored as the compatible
# ``(tag, text)`` tuples; classification is presentation-only and shared by
# MASTER plus every M1..M7 tab.
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
# Kept as a compatibility fallback for callers that inspect the old constant;
# actual rendering uses the current output width on every frame.
_BLOCK_PANEL_WIDTH = 64
_PANEL_MIN_WIDTH = 24
_PANEL_MAX_WIDTH = 96


def _available_columns(fallback: tuple[int, int] = (100, 30)) -> int:
    """Return the active output width without forcing a terminal query."""
    try:
        from prompt_toolkit.application.current import get_app

        return max(1, get_app().output.get_size().columns)
    except Exception:  # headless tests and construction outside Application
        try:
            return max(1, shutil.get_terminal_size(fallback).columns)
        except OSError:
            return fallback[0]


def _panel_width(width: int | None = None) -> int:
    """Compute a bounded panel width that fits the current viewport.

    An explicit width is treated as the panel's exact outer width (useful for
    deterministic rendering/tests); an inferred viewport width leaves a small
    safety margin for surrounding layout columns.
    """
    if width is not None:
        return max(1, min(_PANEL_MAX_WIDTH, width))
    return max(1, min(_PANEL_MAX_WIDTH, _available_columns() - 2))


def _classify_block(text: str, active: str = BLOCK_EXECUTION) -> tuple[str, str]:
    """Classify visible agent output without inferring hidden reasoning.

    ``active`` is scoped by agent in ``_panel_groups``. This keeps interleaved
    M1..M7 streams independent while allowing headings and markdown checkboxes
    to keep subsequent lines in the same panel.
    """
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


def _panel_border(
    kind: str, opening: bool, width: int | None = None
) -> tuple[str, str]:
    """Return a solid neon border sized to the current panel viewport."""
    panel_width = _panel_width(width)
    style = f"bold {WHITE}"
    if opening:
        label = _BLOCK_LABELS[kind]
        # Keep the opening rule itself inside tiny viewports too. At the
        # absolute minimum, allow a one-cell rule and omit the label rather
        # than emitting a border wider than the requested viewport.
        prefix = f"╭─ {label} "
        if len(prefix) + 1 > panel_width:
            label = {BLOCK_THINKING: "THINK", BLOCK_TODO: "TODO", BLOCK_EXECUTION: "EXEC"}[kind]
            prefix = f"╭─ {label} "
        if len(prefix) + 1 > panel_width:
            prefix = "╭─ "
        dashes = max(0, panel_width - len(prefix) - 1)
        line = prefix + "─" * dashes + "╮"
        return style, line[:panel_width] + "\n"
    line = "╰" + "─" * max(0, panel_width - 2) + "╯"
    return style, line[:panel_width] + "\n"


def _content_style(kind: str, text: str) -> str:
    """Style panel content, emphasizing completed/pending todo states."""
    # Categorized chat/execution panels deliberately use solid white content;
    # the surrounding general console remains the light-grey log surface.
    return "class:retro.panel.content"


def _console_fragments(
    lines: list[tuple[str, str]],
    prefix: bool = True,
    initial_states: dict[str, str] | None = None,
    width: int | None = None,
) -> list[tuple[str, str]]:
    """Render all tabs through the same categorized bordered-panel renderer.

    MASTER keeps its legacy plain command chrome; agent output is wrapped in
    THINKING, TODO / TASKS, or EXECUTION / CODE panels. ``prefix=False`` is
    used by M1..M7 because the tab bar already identifies the agent.
    """
    fragments: list[tuple[str, str]] = []
    for group_key, group in _panel_groups(lines, initial_states):
        tag, kind = group_key.split(":", 1)
        if kind == "header":
            fragments.extend((f"bold {WHITE}", text + "\n") for _, text in group)
            continue
        if tag == "master":
            # General command/log content stays Git light-grey; only the
            # categorized agent panels below use solid white content.
            for line_tag, text in group:
                fragments.append(("class:retro.console", text + "\n"))
            continue

        panel_width = _panel_width(width)
        style, border = _panel_border(kind, True, panel_width)
        fragments.append((style, border))
        inner_width = max(1, panel_width - 4)
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
                fragments.append((style, "│ "))
                if visible_prefix:
                    fragments.append((_tag_style(line_tag), visible_prefix))
                fragments.append((_content_style(kind, chunk), chunk))
                fragments.append((style, " " * max(0, inner_width - len(visible_prefix) - len(chunk))))
                fragments.append((style, " │\n"))
        style, border = _panel_border(kind, False, panel_width)
        fragments.append((style, border))
    return fragments


# --------------------------------------------------------------------------- interactive app


def build_rounded_box(body, title_fragments=None, width=None):
    """A rounded prompt box (╭─╮ │ ╰─╯) around ``body``.

    Built from prompt_toolkit primitives because this prompt_toolkit version
    ships no ``RoundedFrame`` widget. ``title_fragments`` and ``width`` may be
    callables (re-evaluated every frame) so the model status bar embedded in
    the top border stays live.
    """
    from prompt_toolkit.layout import FormattedTextControl, HSplit, VSplit, Window

    def fill(char: str):
        # width=1 pins the border to a single column; without it the filler
        # expands across the whole row (painting '│' everywhere).
        return Window(
            char=char, width=1, height=1, style="class:retro.box", dont_extend_height=True
        )

    def resolve_width() -> int:
        return width() if callable(width) else (width or 0)

    def resolve_title() -> list[tuple]:
        return title_fragments() if callable(title_fragments) else (title_fragments or [])

    def top_content() -> list[tuple]:
        w = resolve_width()
        title = resolve_title()
        middle = "".join(fragment[1] for fragment in title)
        # Keep the right corner aligned even when a long model name meets a
        # narrow terminal. On truncation the title becomes display-only; at
        # normal widths its original mouse-aware fragments are preserved.
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
                    # Keep a clickable hit target for every control even on a
                    # narrow terminal; the visible label is abbreviated.
                    compact.append((fragment[0], text[:max(1, remaining)], fragment[2]))
                    remaining = 0
                elif remaining:
                    compact.append((fragment[0], text[:remaining]))
                    remaining = 0
            # Fill the remainder so the top edge always matches the bottom
            # edge, while retaining the clickable fragment handlers above.
            used = sum(len(fragment[1]) for fragment in compact)
            compact.append(("class:retro.box", "─" * max(0, w - used - 1) + "╮"))
            # A very small output can make the fixed suffix wider than the
            # viewport; clip the final rendered row as a last safety net.
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

    top = Window(
        content=FormattedTextControl(top_content),
        height=1,
        style="class:retro.box",
        dont_extend_height=True,
    )
    bottom = Window(
        content=FormattedTextControl(bottom_content),
        height=1,
        style="class:retro.box",
        dont_extend_height=True,
    )
    mid = VSplit([fill("│"), body, fill("│")])
    return HSplit([top, mid, bottom])


class RetroTerminalApp:
    """Full-screen prompt_toolkit terminal UI."""

    MAX_CONSOLE_LINES = 1000
    CONSOLE_TAIL = 20  # lines visible by default (scroll reveals more)

    def __init__(self, workspace: Path | None = None) -> None:
        self.hub = HUB
        # A newly created terminal starts with every agent visually inactive;
        # never reset a live swarm when another view is constructed.
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
        # Specialized instructions are opt-in and empty/off for every agent
        # at startup. They are prepended only to that agent's own dispatch.
        self.system_prompts: dict[str, str] = {tag: "" for tag, _, _ in TABS}
        self.agents_filter: list[str] | None = None
        self.menu_kind: str | None = None
        self.menu_target: str | None = None
        self.menu_options: list[str] = []
        # Screen-space anchor and dimensions for the active dropdown. These
        # are updated from the trigger's MouseEvent and clamped to the output
        # rectangle so menus stay beside/above the clicked control.
        self.menu_left = 1
        self.menu_top = 1
        self.menu_width = 24
        self.menu_height = 3
        self.console_lines: list[tuple[str, str]] = []  # (tag, text) MASTER log
        self.current_tab: str = "master"
        self.tab_lines: dict[str, list[tuple[str, str]]] = {tag: [] for tag, _, _ in TABS}
        self.tab_scroll: dict[str, int] = {tag: 0 for tag, _, _ in TABS}
        self._seq = 0
        self._last_status: dict[str, str] = {}

        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.filters import has_completions, has_focus
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import (
            BufferControl,
            ConditionalContainer,
            Dimension,
            Float,
            FloatContainer,
            FormattedTextControl,
            HSplit,
            Layout,
            Window,
        )
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.styles import Style

        commands = [
            "tab", "help", "cd", "model", "mode", "prompt", "prompts",
            "agents", "status", "overrides", "clear", "stop", "swarm",
            "proposals", "evolve", "quit", "exit",
        ]
        completer = WordCompleter(commands + MODEL_OPTIONS + [t for t, _, _ in TABS], ignore_case=True)

        self.buffer = Buffer(
            name="input",
            multiline=True,
            completer=completer,
            history=InMemoryHistory(),
            accept_handler=self._on_accept,
        )

        kb = KeyBindings()

        # In multiline mode, Enter inserts a newline by default; rebind it to
        # submit (validate_and_handle triggers the buffer's accept_handler).
        # Shift+Enter explicitly inserts a newline for multi-line prompts.
        # When the completion menu is open, Enter first accepts the completion.
        @kb.add("enter", filter=has_focus("input") & ~has_completions)
        def _enter(_event):
            self.buffer.validate_and_handle()

        @kb.add("c-j", filter=has_focus("input"))
        def _ctrl_j(_event):
            # Ctrl+J inserts a newline (Shift+Enter / Alt+Enter are not
            # representable in this prompt_toolkit on Windows terminals).
            self.buffer.insert_text("\n")

        @kb.add("c-c", filter=has_focus("input"))
        def _ctrl_c(event):
            if self.buffer.text.strip():
                self.buffer.text = ""
                self.buffer.cursor_position = 0
            else:
                event.app.exit()

        @kb.add("c-d", filter=has_focus("input"))
        def _ctrl_d(event):
            event.app.exit()

        @kb.add("escape")
        def _escape(_event):
            self.close_menu(_event)

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

        # --- tab switching -------------------------------------------------
        # F1..F7 select agent tabs M1..M7; F8 selects MASTER (all agents).

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

        banner_window = Window(
            content=FormattedTextControl(
                lambda: _banner_fragments(self.banner_visible)
            ),
            height=lambda: len(BANNER) if self.banner_visible else 0,
            style="class:retro.banner",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        dir_window = Window(
            content=FormattedTextControl(lambda: [("class:retro.dir", _dir_line(self.hub.workspace))]),
            height=1,
            style="class:retro.dir",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        self.tab_window = Window(
            content=FormattedTextControl(
                lambda: _dashboard_fragments(
                    self.hub.statuses,
                    self.current_tab,
                    self._handle_tab_mouse,
                    width=max(1, _available_columns() - 2),
                )
            ),
            height=Dimension(min=1, preferred=2, max=len(TABS)),
            wrap_lines=True,
            style="class:retro.dash",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        # The only loading indicator in the UI. It is a fixed one-line slot
        # immediately above the prompt frame; all agent tabs share this slot.
        self.loading_window = Window(
            content=FormattedTextControl(
                lambda: _loading_bar_fragments(**self.hub.loading_snapshot(self.current_tab), width=_available_columns())
            ),
            height=1,
            wrap_lines=False,
            style="class:retro.progress",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        self.console_window = Window(
            content=FormattedTextControl(lambda: self._console_fragments()),
            height=Dimension(min=CONSOLE_MIN_LINES, preferred=CONSOLE_PREFERRED_LINES),
            style="class:retro.console",
            always_hide_cursor=True,
            wrap_lines=True,
        )
        input_window = Window(
            content=BufferControl(buffer=self.buffer, focusable=True),
            height=Dimension(min=INPUT_MIN_LINES, max=INPUT_MAX_LINES),
            wrap_lines=True,
            style="class:retro.input",
        )

        def _box_width() -> int:
            """Use the active prompt_toolkit output size for aligned framing."""
            try:
                from prompt_toolkit.application.current import get_app

                columns = get_app().output.get_size().columns
            except Exception:  # headless construction / no active app
                try:
                    columns = os.get_terminal_size().columns
                except OSError:
                    columns = 100
            # Keep both corners inside the actual viewport, even for very
            # narrow output objects used by tests or embedded terminals.
            return max(1, columns - 2)

        box = build_rounded_box(
            input_window,
            title_fragments=lambda: _model_bar_fragments(
                self.overrides,
                self.agents_filter,
                self.current_tab,
                self._handle_control_mouse,
                compact=_box_width() < 100,
                ultra_compact=_box_width() < 60,
            ),
            width=lambda: _box_width(),
        )
        # Expose the prompt frame for layout tests and keep the loading slot's
        # adjacency to it explicit: loading_window, then prompt_box.
        self.prompt_box = box

        menu_window = Window(
            content=FormattedTextControl(self._menu_fragments),
            height=Dimension(min=0, preferred=1, max=len(TABS) + 2),
            wrap_lines=False,
            style="class:retro.menu",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        backdrop_window = Window(
            content=FormattedTextControl(self._backdrop_fragments),
            style="class:retro.backdrop",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        content = HSplit(
            [
                banner_window,
                dir_window,
                self.tab_window,
                self.console_window,
                self.loading_window,
                box,
            ]
        )
        self.menu_backdrop_float = Float(
            ConditionalContainer(backdrop_window, Condition(lambda: self.menu_kind is not None)),
            top=0,
            left=0,
            width=lambda: self._screen_size()[0],
            height=lambda: self._screen_size()[1],
            z_index=9,
            transparent=True,
        )
        self.menu_float = Float(
            ConditionalContainer(menu_window, Condition(lambda: self.menu_kind is not None)),
            top=self.menu_top,
            left=self.menu_left,
            width=lambda: self.menu_width,
            height=lambda: self.menu_height,
            z_index=10,
        )
        root = FloatContainer(
            content,
            floats=[self.menu_backdrop_float, self.menu_float],
        )
        self.layout_root = root
        self.key_bindings = kb
        self._style_dict = {
            "retro": f"bg:{BLACK} fg:{GREY}",
            "retro.banner": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.dir": f"bold bg:{BLACK} fg:{GREY}",
            "retro.dash": f"bg:{BLACK} fg:{GREY}",
            "retro.progress": f"bg:{BLACK} fg:{WHITE}",
            "retro.muted": f"bg:{BLACK} fg:{GREY}",
            "retro.console": f"bg:{BLACK} fg:{GREY}",
            "retro.panel.content": f"bg:{BLACK} fg:{WHITE}",
            "retro.model": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.control": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.menu": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.menu.border": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.menu.item": f"bg:{BLACK} fg:{WHITE}",
            "retro.backdrop": f"bg:{BLACK} fg:{BLACK}",
            "retro.box": f"bg:{BLACK} fg:{WHITE}",
            # Tabs retain the original dark background while every outline is
            # the requested Git-style orange-red.
            "retro.tab.active": f"bold bg:{GREY_BG} fg:{ORANGE}",
            "retro.tab.busy": f"bold bg:{BLACK} fg:{ORANGE}",
            "retro.tab.inactive": f"bg:{BLACK} fg:{ORANGE}",
            # Explicit bold white keeps the command prompt bright even when
            # the terminal's default input style is dimmed.
            "retro.input": f"bg:{GREY_BG} fg:{WHITE} bold",
        }
        self._application = None
        self.banner_visible = True

    # ------------------------------------------------------------------ tabs

    def set_tab(self, tag: str) -> None:
        """Switch the active tab (master or m1..m7). Unknown tags are ignored."""
        if tag in self.tab_lines:
            self.current_tab = tag

    def _handle_tab_mouse(self, tag: str, event) -> None:
        """Switch tabs after a primary mouse click on a tab cell."""
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType

        if (
            event.event_type == MouseEventType.MOUSE_UP
            and event.button == MouseButton.LEFT
        ):
            self.set_tab(tag)
            self.close_menu(event)

    def _handle_control_mouse(self, kind: str, event) -> None:
        """Open a bottom control menu anchored to the clicked control."""
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType

        if event.event_type != MouseEventType.MOUSE_UP or event.button != MouseButton.LEFT:
            return
        self.open_menu(kind, event=event)
        self._invalidate_ui()

    def _screen_size(self) -> tuple[int, int]:
        """Return the live output size, with a safe headless fallback."""
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
        """Place the menu above its trigger and clamp it to the viewport."""
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
        # Prefer directly above the trigger; flip below if the menu would
        # cross the top edge, then clamp both coordinates to the screen.
        top = anchor_y - self.menu_height
        if top < 0:
            top = anchor_y + 1
        self.menu_left = max(0, min(anchor_x, max(0, columns - self.menu_width)))
        self.menu_top = max(0, min(top, max(0, rows - self.menu_height)))
        # Float top/left are integer offsets (not reactive callables) in the
        # installed prompt_toolkit, so update the live object on each click.
        menu_float = getattr(self, "menu_float", None)
        if menu_float is not None:
            menu_float.left = self.menu_left
            menu_float.top = self.menu_top

    def _backdrop_fragments(self) -> list[tuple]:
        """Provide a full-screen click target that dismisses open menus."""
        if self.menu_kind is None:
            return []
        columns, rows = self._screen_size()
        def dismiss(event):
            self._dismiss_mouse(event)
        return [("class:retro.backdrop", (" " * columns + "\n") * rows, dismiss)]

    def open_menu(self, kind: str, target: str | None = None, event=None) -> None:
        """Open a clickable model, mode, target, or tab list."""
        self.menu_kind = kind
        self.menu_target = target or self.current_tab
        if kind == "model":
            self.menu_options = list(MODEL_OPTIONS)
        elif kind == "mode":
            model, _mode = self.hub.resolve(self.menu_target, self.overrides)
            self.menu_options = list(MODE_OPTIONS_BY_MODEL.get(model or AUTO_MODEL, [AUTO_MODE]))
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
        """Refresh safely from mouse callbacks and headless unit tests."""
        try:
            from prompt_toolkit.application.current import get_app

            get_app().invalidate()
        except Exception:
            pass

    def _dismiss_mouse(self, event) -> None:
        """Close an open menu when clicking ordinary content."""
        from prompt_toolkit.mouse_events import MouseButton, MouseEventType

        if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
            self.close_menu(event)

    def close_menu(self, event=None) -> None:
        """Close an open bottom menu and restore prompt focus when possible."""
        self.menu_kind = None
        self.menu_target = None
        self.menu_options = []
        try:
            from prompt_toolkit.application.current import get_app

            app = get_app()
            app.layout.focus(self.buffer)
            app.invalidate()
        except Exception:
            pass

    def _menu_fragments(self) -> list[tuple]:
        """Render a closed, bordered dropdown with clickable option rows."""
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
        """Apply a dropdown choice using the same command validation rules."""
        kind = self.menu_kind
        if kind == "model":
            self._set_override(self.menu_target or self.current_tab, "model", option)
        elif kind == "mode":
            target = self.menu_target or self.current_tab
            model, _mode = self.hub.resolve(target, self.overrides)
            valid = MODE_OPTIONS_BY_MODEL.get(model or AUTO_MODEL, [AUTO_MODE])
            if option in valid:
                self._set_override(target, "mode", option)
        elif kind == "target":
            self.agents_filter = None if option == "all" else [option]
        elif kind == "tab":
            self.set_tab(option)
        self.close_menu(event)

    def _tab_order(self) -> list[str]:
        return [t for t, _, _ in TABS]

    def _next_tab_tag(self) -> str:
        order = self._tab_order()
        return order[(order.index(self.current_tab) + 1) % len(order)]

    def _prev_tab_tag(self) -> str:
        order = self._tab_order()
        return order[(order.index(self.current_tab) - 1) % len(order)]

    # ------------------------------------------------------------------ console

    def _tab_source(self) -> list[tuple[str, str]]:
        """The console line list backing the active tab.

        MASTER shows every event (the shared log); agent tabs show only
        their own agent's lines.
        """
        if self.current_tab == "master":
            return self.console_lines
        return self.tab_lines[self.current_tab]

    def _max_scroll(self) -> int:
        """Upper bound for manual console scroll (lines above the tail)."""
        return max(0, len(self._tab_source()) - self.CONSOLE_TAIL)

    def _console_fragments(self) -> list[tuple[str, str]]:
        """Tail of the active tab's console, honoring the scroll offset.

        Shows the most recent ``CONSOLE_TAIL`` lines; scrolling up (PageUp)
        reveals older lines up to ``_max_scroll``.
        """
        source = self._tab_source()
        scroll = self.tab_scroll.get(self.current_tab, 0)
        tail = min(len(source), self.CONSOLE_TAIL)
        start = max(0, len(source) - tail - scroll)
        # Agent tabs use the same panel markup as MASTER, but omit repeated
        # agent prefixes because the active tab already identifies the agent.
        history_prefix = source[:start]
        initial_states = _block_states(history_prefix)
        return _console_fragments(
            source[start:],
            prefix=self.current_tab == "master",
            initial_states=initial_states,
            width=max(1, _available_columns() - 2),
        )

    def _drain(self) -> None:
        """Pull new hub events into the consoles (call from the UI thread).

        Every event lands in the MASTER log; agent-tagged events additionally
        land in that agent's tab. The view stays pinned to the tail while the
        user is at the bottom; a manual scroll offset (PageUp) is preserved
        across drains so live output doesn't yank the user back down.
        """
        with self.hub.lock:
            events = [e for e in self.hub.events if e["seq"] > self._seq]
            if events:
                self._seq = max(e["seq"] for e in events)
        for event in events:
            kind = event["kind"]
            text = event["text"]
            tag = event["tag"]
            if kind == "line":
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
        """Lazily build the prompt_toolkit Application.

        ``input``/``output`` are passed through; when omitted, prompt_toolkit
        attaches the real console at construction time, so callers that must
        stay headless (tests, ``--smoke``) pass ``DummyInput``/a capture
        output explicitly. ``run()`` always uses real console I/O.
        """
        if self._application is None:
            from prompt_toolkit.application import Application
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.styles import Style

            self._application = Application(
                layout=Layout(self.layout_root, focused_element=self.buffer),
                key_bindings=self.key_bindings,
                full_screen=True,
                mouse_support=True,
                style=Style.from_dict(self._style_dict),
                erase_when_done=True,
                input=input,
                output=output,
            )
        return self._application

    # ------------------------------------------------------------------ input

    def _echo(self, text: str) -> None:
        """Show a submitted prompt / command reply in the MASTER log and the
        active tab's console."""
        entry = ("master", text)
        self.console_lines.append(entry)
        if self.current_tab != "master":
            self.tab_lines[self.current_tab].append(entry)

    def _on_accept(self, _buffer) -> None:
        """Enter was pressed: run a slash command or dispatch the swarm."""
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
        """Route one submitted line (command or task prompt).

        A task typed on an agent tab dispatches to that agent only; on the
        MASTER tab it goes to all agents (or the ``/agents`` filter).
        """
        stripped = text.strip()
        if not stripped:
            return
        # Direct callers/tests and future input paths get the same lifecycle
        # behavior as the Buffer accept handler.
        self.banner_visible = False
        cmd = parse_command(stripped)
        if cmd is None:
            if self.current_tab == "master":
                targets = self.agents_filter  # None -> all agents
            else:
                targets = [self.current_tab]
            err = self.hub.run(
                stripped,
                self.overrides,
                targets,
                system_prompts=self.system_prompts,
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
        except Exception as exc:  # noqa: BLE001 — command handlers never crash the UI
            reply = f"ERROR: {exc}"
        if reply:
            for line in reply.splitlines():
                self._echo(line)

    # ------------------------------------------------------------ slash commands

    def _cmd_tab(self, arg: str) -> str:
        """/tab [tag] — show or switch the active tab (master, m1..m7)."""
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
        """Split a /model or /mode arg into (target, value).

        An optional leading target names a tab ('m1'..'m7', 'master') or
        'all'; without one the active tab is used. The remainder is the
        value (model name / mode / 'auto').
        """
        parts = arg.split(None, 1)
        if parts and parts[0].lower() in self._OVERRIDE_TARGETS:
            return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")
        return self.current_tab, arg

    def _set_override(self, target: str, key: str, value: str) -> None:
        """Write a per-tab override; 'all' writes every non-immutable tab."""
        if target == "all":
            for tag, _, _ in TABS:
                if tag in IMMUTABLE_TAGS:
                    continue
                self.overrides.setdefault(tag, {})[key] = value
        else:
            if target in IMMUTABLE_TAGS:
                return  # silently ignore — immutable tags reject overrides
            self.overrides.setdefault(target, {})[key] = value

    def _explicit_overrides(self, key: str | None = None) -> list[str]:
        """Human-readable list of tabs with non-auto overrides.

        ``key`` optionally filters to just 'model' or 'mode' overrides.
        """
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
        """Resolved model line for a target tab (override > master > auto)."""
        model, _mode = self.hub.resolve(target, self.overrides)
        value = model or AUTO_MODEL
        if target != self.current_tab:
            return f"MODEL ({target}): {value}"
        return f"MODEL: {value}"

    def _mode_status_line(self, target: str) -> str:
        """Resolved mode line for a target tab (override > master > auto)."""
        _model, mode = self.hub.resolve(target, self.overrides)
        value = mode or AUTO_MODE
        if target != self.current_tab:
            return f"MODE ({target}): {value}"
        return f"MODE: {value}"

    def _cmd_model(self, arg: str) -> str:
        """/model [target] [name] — show or set a tab's model override.

        Target is the active tab by default; 'm1'..'m7', 'master', or 'all'
        may be given explicitly. 'auto' (or the full AUTO_MODEL string)
        resets the tab to inherit from master / auto.
        """
        target, value = self._split_override_arg(arg)
        if target in IMMUTABLE_TAGS and value:
            return f"ERROR: {target.upper()} is immutable — model cannot be changed"
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
        """/mode [target] [name] — show or set a tab's mode override.

        Target semantics match ``/model``. The value is validated against the
        *resolved* model of the target tab (tab override > master > auto).
        """
        target, value = self._split_override_arg(arg)
        if target in IMMUTABLE_TAGS and value:
            return f"ERROR: {target.upper()} is immutable — mode cannot be changed"
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
        modes = MODE_OPTIONS_BY_MODEL.get(model or AUTO_MODEL, [AUTO_MODE])
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
        """/overrides — table of every tab's effective model/mode and source."""
        return build_overrides_table(self.overrides)

    def _cmd_prompt(self, arg: str) -> str:
        """/prompt [target] [text] — set or clear a specialized system prompt."""
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
        """/prompts — list specialized prompts, showing inactive entries as off."""
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
        return "\n".join(
            [
                f"DIR: {self.hub.workspace}",
                f"TAB: {self.current_tab} "
                f"MODEL: {model or AUTO_MODEL} "
                f"MODE: {mode or AUTO_MODE} "
                f"RUN: {self.hub.running}/{len(AGENTS)} "
                f"TARGET: {target}",
                statuses,
            ]
        )

    def _cmd_clear(self, _arg: str) -> str:
        self.console_lines = []
        for tag in self.tab_lines:
            self.tab_lines[tag] = []
        self.tab_scroll = {tag: 0 for tag in self.tab_lines}
        self.hub.clear()
        return ""

    def _cmd_stop(self, _arg: str) -> str:
        self.hub.terminate_all()
        return "stopped all running agents"

    def _cmd_swarm(self, _arg: str) -> str:
        return _swarm_state()

    def _cmd_proposals(self, _arg: str) -> str:
        return _format_proposals()

    def _cmd_evolve(self, arg: str) -> str:
        err = run_self_evolve(arg, self.overrides, self.system_prompts)
        return err if err else "self-evolve dispatched"

    def _cmd_quit(self, _arg: str) -> str:
        app = self._build_application()
        if app.is_running:
            app.exit()
        return ""

    _cmd_exit = _cmd_quit

    # ------------------------------------------------------------------ run loop

    async def _poller(self) -> None:
        """Periodically drain hub events and refresh the screen."""
        while True:
            await asyncio.sleep(0.1)
            self._drain()
            if self._application is not None:
                self._application.invalidate()

    def run(self) -> int:
        """Enter the full-screen loop (real console I/O)."""
        from prompt_toolkit.input import create_input
        from prompt_toolkit.output import create_output

        self.console_lines.append(("master", "ZOVA terminal ready — F1..F7 select agent tabs, F8 MASTER, type /help for commands."))
        app = self._build_application(input=create_input(), output=create_output())

        def _start_poller() -> None:
            # ``create_background_task`` needs the app's event loop; ``pre_run``
            # fires after the loop is set up (calling it earlier in ``run()``
            # raises ``RuntimeError: no running event loop``).
            app.create_background_task(self._poller())

        app.run(pre_run=_start_poller)
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZOVA — MultiAgentCoding Retro Terminal")
    parser.add_argument("--workspace", default=None, help="working directory for the agents")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="headless build check: construct the app and exit (no TTY required)",
    )
    args = parser.parse_args(argv)

    app = RetroTerminalApp(workspace=Path(args.workspace) if args.workspace else None)
    if args.smoke:
        print("SMOKE-OK: retro terminal app constructed (banner rows=%d)" % len(BANNER))
        return 0
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
