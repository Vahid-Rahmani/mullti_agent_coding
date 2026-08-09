#!/usr/bin/env python3
"""ZOVA — MultiAgentCoding Retro Terminal.

A full-screen, retro-CRT style terminal UI for the control-plane agents. It
replaces the browser workspace (``web_app.py``) and the desktop GUI
(``unified_app.py``) as the single interactive way to talk to the agent swarm.

Look & feel (strict palette, per spec — these four colors are the only ones
used anywhere in the UI):
  * white       standard code, active highlights, and primary text
  * orange      important details & keywords (tag prefixes, errors)
  * light neutral grey  framing, muted states, and panel borders on black


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
    /model [t] [n]   show/set a tab's model override (t = active tab,
                     m1..m7, master, all; n = model or 'auto')
    /mode [t] [n]    show/set a tab's mode override (same target syntax)
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
import threading
import time
from pathlib import Path

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
MODE_OPTIONS_BY_MODEL: dict[str, list[str]] = {
    AUTO_MODEL: [AUTO_MODE],
    "opencode/deepseek-v4-flash-free": ["architect", "build", "analyze"],
    "opencode/big-pickle": ["plan", "build", "analyze"],
    "opencode/ling-3.0-tiny-free": ["review", "compact"],
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


def _agent_progress_fragments(
    statuses: dict[str, str],
    progress: dict[str, int] | None = None,
    token_usage: dict[str, int] | None = None,
    current_tab: str = "master",
) -> list[tuple[str, str]]:
    """Render active-agent progress rows and token lines for all tabs."""
    progress = progress or {}
    token_usage = token_usage or {}
    fragments: list[tuple[str, str]] = []
    for tag, name, _agent in AGENTS:
        if statuses.get(tag, STATUS_IDLE) not in (STATUS_THINKING, STATUS_ACTIVE):
            continue
        label_style = f"bold {NEON}" if tag == current_tab else "class:retro.muted"
        fragments.append((label_style, f"{tag.upper()} {name}  "))
        fragments.extend(_progress_bar_fragments(progress.get(tag, 0)))
        fragments.append(("class:retro.console", "  "))
        fragments.extend(_working_fragments())
        fragments.append(("class:retro.console", "\n"))
        fragments.append(("class:retro.muted", f"    Token: {token_usage.get(tag, 0)}% Used (approx.)\n"))
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
                self.progress[tag] = 0
                self.token_usage[tag] = 0
                self.prompts[tag] = ""
        self._emit("master", "line", "── logs cleared ──")

    # ------------------------------------------------------------ running

    def resolve(self, tag: str, overrides: dict[str, dict[str, str]]) -> tuple[str | None, str]:
        """Resolve (model, mode) for a tag: tag override > master override > auto."""
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
        self.append_line("master", f"▶ {prompt}")
        pruned = prune_prompt(prompt)
        STATE.record_run(pruned, time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            self.running += len(targets)
            for tag, _name, _agent in targets:
                self.progress[tag] = 5
                self.token_usage[tag] = _estimate_token_percent(prompt, [])
                self.prompts[tag] = pruned
        for tag, _name, agent in targets:
            # A run separator resets the visible block context for this agent
            # and makes consecutive runs easy to scan in every tab.
            self._emit(tag, "run", _run_header(prompt, tag.upper()))
            model, mode = self.resolve(tag, overrides)
            self.set_status(tag, STATUS_THINKING)
            threading.Thread(
                target=self._run_agent,
                args=(tag, agent, pruned, model, mode),
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
    ) -> None:
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
            STATE.record_finish(tag, ok)

    def terminate_all(self) -> None:
        with self.lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        self.append_line("master", "── terminated ──")
        STATE.record_restart("interrupted", "terminated by user")


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


def run_self_evolve(prompt: str, overrides: dict) -> str | None:
    """Checkpoint + dispatch a self-evolve cycle (terminal '/evolve' command)."""
    if not prompt.strip():
        return "Usage: /evolve <prompt>"
    checkpoint = SELF_EVOLVE_ENGINE.checkpoint(prompt)
    err = HUB.run(prompt, overrides)
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

# ZOVA neutral palette — white is the primary highlight and grey frames the UI.
WHITE = "#ffffff"      # primary text and active highlights
ORANGE = "#ff8c00"     # errors and secondary warning keywords
GREY = "#c4c8cc"       # light neutral borders and muted text
GREY_BG = "#333333"    # background highlight (input box)
# Kept as a compatibility alias for existing helper names; no green is used.
NEON = WHITE
BLACK = "#000000"      # solid background

STATUS_SYMBOL = {
    STATUS_IDLE: ("●", GREY),
    STATUS_THINKING: ("◐", ORANGE),
    STATUS_ACTIVE: ("●", NEON),
    STATUS_ERROR: ("✕", ORANGE),
}


def _tag_style(tag: str) -> str:
    """prompt_toolkit style fragment for a tag prefix (orange keyword)."""
    return f"bold {ORANGE}"


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
    """Model status bar text (embedded in the rounded box's top border).

    Shows the active tab, that tab's *resolved* model/mode (tab override >
    master override > auto), dispatch target (the active agent tab or the
    ``/agents`` filter on MASTER), and the running count.
    """
    model, mode = HUB.resolve(current_tab, overrides)
    if current_tab != "master":
        target = current_tab
    else:
        target = ",".join(agents_filter) if agents_filter else "all"
    running = HUB.running
    return (
        f" ▍TAB {current_tab.upper()} ▍MODEL {model or AUTO_MODEL} "
        f"▍MODE {mode or AUTO_MODE} "
        f"▍TARGET {target} ▍RUN {running}/{len(AGENTS)} "
    )


def _dashboard_fragments(
    statuses: dict[str, str], current_tab: str = "master"
) -> list[tuple[str, str]]:
    """Tab bar row: MASTER + M1..M7 with live status (strict ZOVA palette).

    Each tab shows its status symbol (grey idle / orange busy-or-error /
    white active) and label. The active tab is highlighted: bracket-wrapped
    and bold white. Other tabs render grey-ish labels with status-colored
    symbols.
    """
    fragments: list[tuple[str, str]] = []
    for tag, name, _agent in TABS:
        status = statuses.get(tag, STATUS_IDLE)
        symbol, color = STATUS_SYMBOL.get(status, STATUS_SYMBOL[STATUS_IDLE])
        active = tag == current_tab
        label = "MASTER" if tag == "master" else f"{tag.upper()} {name}"
        if active:
            # keep the status symbol's own color inside the bracket; the
            # label is the white highlight
            fragments.append((f"bold {NEON}", " ["))
            fragments.append((color, f"{symbol} "))
            fragments.append((f"bold {NEON}", f"{label}] "))
        else:
            fragments.append((color, f" {symbol} "))
            fragments.append(("class:retro.muted", f"{label} "))
    return fragments


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
    BLOCK_THINKING: f"bold {GREY}",
    BLOCK_TODO: f"bold {GREY}",
    BLOCK_EXECUTION: f"bold {GREY}",
}
_BLOCK_PANEL_WIDTH = 64


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


def _panel_border(kind: str, opening: bool) -> tuple[str, str]:
    """Return a uniformly sized light-grey border for a categorized panel."""
    style = f"bold {GREY}"
    if opening:
        prefix = f"╭─ {_BLOCK_LABELS[kind]} "
        dashes = max(1, _BLOCK_PANEL_WIDTH - len(prefix) - 1)
        return style, prefix + "─" * dashes + "╮\n"
    return style, "╰" + "─" * (_BLOCK_PANEL_WIDTH - 2) + "╯\n"


def _content_style(kind: str, text: str) -> str:
    """Style panel content, emphasizing completed/pending todo states."""
    if text.startswith("ERROR"):
        return f"bold {ORANGE}"
    if kind == BLOCK_TODO:
        marker = re.match(r"^(?:[-*+]\s+)?\[([ X✓✗~-])\]", text.strip(), re.IGNORECASE)
        if marker:
            state = marker.group(1).lower()
            if state in {"x", "✓"}:
                return f"bold {NEON}"
            if state in {"~", "-"}:
                return f"bold {GREY}"
            return f"bold {ORANGE}"
        return f"bold {ORANGE}"
    return "class:retro.console"


def _console_fragments(
    lines: list[tuple[str, str]],
    prefix: bool = True,
    initial_states: dict[str, str] | None = None,
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
            for line_tag, text in group:
                fragments.append((_content_style(kind, text), text + "\n"))
            continue

        style, border = _panel_border(kind, True)
        fragments.append((style, border))
        for line_tag, text in group:
            content: list[tuple[str, str]] = []
            if prefix and line_tag and line_tag != "master":
                content.append((_tag_style(line_tag), f"[{line_tag}] "))
            content.append((_content_style(kind, text), text))
            fragments.append((style, "│ "))
            fragments.extend(content)
            fragments.append((style, " │\n"))
        style, border = _panel_border(kind, False)
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

    def resolve_title() -> list[tuple[str, str]]:
        return title_fragments() if callable(title_fragments) else (title_fragments or [])

    def top_content() -> list[tuple[str, str]]:
        w = resolve_width()
        middle = "".join(t for _, t in resolve_title())
        base = "╭─" + middle + "─"
        tail = "─" * max(1, w - len(base) - 2) if w else ""
        return [("class:retro.box", base + tail + "╮")]

    def bottom_content() -> list[tuple[str, str]]:
        w = resolve_width()
        return [("class:retro.box", "╰" + "─" * max(2, w - 2) + "╯")] if w else []

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
        if workspace is not None:
            self.hub.workspace = Path(workspace).expanduser().resolve()
        self.overrides: dict[str, dict[str, str]] = {
            "master": {"model": AUTO_MODEL, "mode": AUTO_MODE}
        }
        self.agents_filter: list[str] | None = None
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
            Dimension,
            FormattedTextControl,
            HSplit,
            Layout,
            Window,
        )
        from prompt_toolkit.styles import Style

        commands = [
            "tab", "help", "cd", "model", "mode", "agents", "status",
            "overrides", "clear", "stop", "swarm", "proposals", "evolve",
            "quit", "exit",
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
            content=FormattedTextControl(lambda: _dashboard_fragments(self.hub.statuses, self.current_tab)),
            height=Dimension(min=1, max=2),
            wrap_lines=True,
            style="class:retro.dash",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        self.progress_window = Window(
            content=FormattedTextControl(
                lambda: _agent_progress_fragments(
                    self.hub.statuses,
                    self.hub.progress,
                    self.hub.token_usage,
                    self.current_tab,
                )
            ),
            height=Dimension(min=0, max=max(1, len(AGENTS) * 2)),
            wrap_lines=True,
            style="class:retro.progress",
            always_hide_cursor=True,
            dont_extend_height=True,
        )
        self.console_window = Window(
            content=FormattedTextControl(lambda: self._console_fragments()),
            style="class:retro.console",
            always_hide_cursor=True,
            wrap_lines=True,
        )
        input_window = Window(
            content=BufferControl(buffer=self.buffer, focusable=True),
            height=Dimension(min=1, max=8),
            wrap_lines=True,
            style="class:retro.input",
        )

        def _box_width() -> int:
            try:
                return max(40, os.get_terminal_size().columns - 2)
            except OSError:
                return 100

        box = build_rounded_box(
            input_window,
            title_fragments=lambda: [(
                "class:retro.model",
                _model_bar(self.overrides, self.agents_filter, self.current_tab),
            )],
            width=lambda: _box_width(),
        )

        root = HSplit(
            [
                banner_window,
                dir_window,
                self.tab_window,
                self.progress_window,
                self.console_window,
                box,
            ]
        )
        self.layout_root = root
        self.key_bindings = kb
        self._style_dict = {
            "retro": f"bg:{BLACK} fg:{WHITE}",
            "retro.banner": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.dir": f"bold bg:{BLACK} fg:{GREY}",
            "retro.dash": f"bg:{BLACK} fg:{WHITE}",
            "retro.progress": f"bg:{BLACK} fg:{WHITE}",
            "retro.muted": f"bg:{BLACK} fg:{GREY}",
            "retro.console": f"bg:{BLACK} fg:{WHITE}",
            "retro.model": f"bold bg:{BLACK} fg:{WHITE}",
            "retro.box": f"bg:{BLACK} fg:{GREY}",
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
                mouse_support=False,
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
            err = self.hub.run(stripped, self.overrides, targets)
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
        """Write a per-tab override; 'all' writes every tab (incl. master)."""
        if target == "all":
            for tag, _, _ in TABS:
                self.overrides.setdefault(tag, {})[key] = value
        else:
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
            return self._model_status_line(target)
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
            return self._mode_status_line(target)
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
        err = run_self_evolve(arg, self.overrides)
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
