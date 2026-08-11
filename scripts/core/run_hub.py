"""Run hub — thread-safe execution engine for the multi-agent system.

RunHub spawns one worker thread per target agent; each thread streams
``opencode run`` output into per-tag buffers via subprocess management.

Baseline-zero: dispatch is plain. Every agent runs its configured model from
the specs; there are no operational modes, no analyzer pre-dispatch, and no
external integrations (no Obsidian vault logging, no self-evolve).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .agents import (
    AGENTS, _AGENT_TAGS, AGENT_SPEC_BY_AGENT, PROJECT_ROOT,
    STATUS_ACTIVE, STATUS_ERROR, STATUS_IDLE, STATUS_THINKING,
)
from .progress import (
    DEFAULT_PROGRESS_WEIGHTS, _estimate_token_percent, _weighted_progress,
)
from . import state_tracker as _state_tracker

# Ensure scripts/ directory is on path for optional imports from sibling modules.
_SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a log string."""
    return _ANSI_RE.sub("", text)


_TRUNCATE_MARKER = "… [truncated] …"


def prune_prompt(prompt: str, max_chars: int = 12000) -> str:
    """Reduce a prompt to a compact, dispatch-safe size."""
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
    """Resolve the opencode executable path (PATHEXT-aware, Windows-safe)."""
    return shutil.which("opencode") or shutil.which("opencode.cmd")


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_prompt(prompt: str) -> str:
    """Strip control characters and leading whitespace from a raw prompt."""
    return _CONTROL_CHARS_RE.sub("", prompt).lstrip()


def _insecure_tls_env() -> dict[str, str] | None:
    """Env override for opencode subprocesses when the TLS bypass is on.

    ``ZOVA_ALLOW_INSECURE_TLS=1`` (or ``true``/``yes``) sets
    ``NODE_TLS_REJECT_UNAUTHORIZED=0`` so the opencode CLI skips certificate
    verification. Strictly opt-in for environments with self-signed or
    intercepting certificates (antivirus/EDR web filters, corporate proxies):
    default (unset or 0) leaves Node's TLS verification fully enabled.
    Returns ``None`` when disabled, so subprocesses inherit the environment
    unchanged.
    """
    raw = os.environ.get("ZOVA_ALLOW_INSECURE_TLS", "").strip().lower()
    if raw not in ("1", "true", "yes"):
        return None
    return {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "0"}


def _build_run_command(
    exe: str, agent: str, prompt: str, model: str | None = None
) -> list[str]:
    """Build the ``opencode run`` argv for one agent (plain dispatch)."""
    cmd = [exe, "run", "--agent", agent, "--auto"]
    if model:
        cmd += ["-m", model]
    prompt = _sanitize_prompt(prompt)
    if prompt.startswith("-"):
        cmd.append("--")
    cmd.append(prompt)
    return cmd


class RunHub:
    """Thread-safe shared state for live agent runs.

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
        self._cancelled_tags: set[str] = set()
        self.running = 0
        self.session_tags: set[str] = set()
        self.progress_weights: dict[str, float] = dict(DEFAULT_PROGRESS_WEIGHTS)
        self.workspace: Path = PROJECT_ROOT
        self._abort_event = threading.Event()

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
                self.progress[tag] = 100
        self._emit(tag, "status", status)

    def append_line(self, tag: str, text: str) -> None:
        with self.lock:
            self.buffers[tag].append(text)
            output_lines = len(self.buffers[tag])
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

    def resolve(self, tag: str, overrides: dict[str, dict[str, str]] | None = None) -> tuple[str | None, str]:
        """Resolve (model, mode) for a tag.

        Baseline-zero: every agent uses its configured spec model; the mode is
        always plain ``"auto"`` (no operational modes exist). ``overrides`` is
        accepted for backward compatibility but ignored.
        """
        spec = AGENT_SPEC_BY_AGENT.get(tag)
        if spec is None and tag != "master":
            spec = next(
                (s for s in (AGENT_SPEC_BY_AGENT.get(a) for _, _, a in AGENTS) if s and s.tag == tag),
                None,
            )
        model = spec.model if spec is not None else None
        return model, "auto"

    def run(
        self,
        prompt: str,
        overrides: dict[str, dict[str, str]] | None = None,
        agents: list[str] | None = None,
        system_prompts: dict[str, str] | None = None,
        enabled_agents: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> str | None:
        """Spawn one worker thread per target agent (plain dispatch).

        ``overrides`` and ``system_prompts`` are accepted for backward
        compatibility but ignored: agents always run their configured spec
        model with the raw prompt.
        """
        if not prompt.strip():
            return "Prompt must not be empty."
        enabled = set(enabled_agents) if enabled_agents is not None else set(_AGENT_TAGS)
        targets = [
            a for a in AGENTS
            if a[0] in enabled and (not agents or a[0] in agents)
        ]
        if not targets:
            return "No agents matched the /agents filter."
        self.append_line("master", f"▶ {prompt}")
        pruned = prune_prompt(prompt)
        _state_tracker.STATE.record_run(pruned, time.strftime("%Y-%m-%dT%H:%M:%S"))
        with self.lock:
            if self.running == 0:
                self.session_tags.clear()
                self._abort_event.clear()
            self._cancelled_tags.difference_update(tag for tag, _name, _agent in targets)
            self.session_tags.update(tag for tag, _name, _agent in targets)
            self.running += len(targets)
            for tag, _name, _agent in targets:
                dispatch_prompt = pruned
                self.progress[tag] = 5
                self.token_usage[tag] = _estimate_token_percent(dispatch_prompt, [])
                self.prompts[tag] = dispatch_prompt
        for tag, _name, agent in targets:
            self._emit(tag, "run", f"{tag.upper()}::{_sanitize_prompt(prompt)[:60]}")
            model, _mode = self.resolve(tag)
            self.set_status(tag, STATUS_THINKING)
            threading.Thread(
                target=self._run_agent,
                args=(tag, agent, pruned, model),
                name=f"term-{tag}",
                daemon=True,
            ).start()
        return None

    def _run_agent(self, tag: str, agent: str, prompt: str, model: str | None) -> None:
        ok = False
        _killed = False
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. Install opencode or "
                    "add it to PATH before using the terminal."
                )
            cmd = _build_run_command(exe, agent, prompt, model)
            with self.lock:
                if tag in self._cancelled_tags:
                    self._cancelled_tags.discard(tag)
                    _killed = True
                    return
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
                    env=_insecure_tls_env(),
                )
                self.procs[tag] = proc
            try:
                for raw in proc.stdout:
                    with self.lock:
                        if tag in self._cancelled_tags:
                            break
                    line = raw.rstrip("\r\n")
                    if line:
                        self.append_line(tag, line)
                        self.set_status(tag, STATUS_ACTIVE)
            except (BrokenPipeError, OSError, ValueError):
                pass
            returncode = proc.wait()
            with self.lock:
                _already_popped = self.procs.pop(tag, None) is None
            if _already_popped:
                _killed = True
                ok = True
            elif returncode != 0:
                cmd_str = " ".join(cmd)
                if len(cmd_str) > 200:
                    cmd_str = cmd_str[:197] + "…"
                self.append_error(tag, f"exit code {returncode}: {cmd_str}")
                self.set_status(tag, STATUS_ERROR)
            else:
                ok = True
                self.set_status(tag, STATUS_IDLE)
        except Exception as exc:  # noqa: BLE001
            self.append_error(tag, str(exc))
            self.set_status(tag, STATUS_ERROR)
        finally:
            with self.lock:
                self.running = max(0, self.running - 1)
                if self.running == 0:
                    self.session_tags.clear()
            if not _killed:
                _state_tracker.STATE.record_finish(tag, ok)

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
                self.statuses, self.progress, tags or None, self.progress_weights,
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

    def _tag_cancelled(self, tag: str) -> bool:
        with self.lock:
            return tag in self._cancelled_tags

    def clear_tag_cancellation(self, tag: str) -> None:
        with self.lock:
            self._cancelled_tags.discard(tag)

    def terminate_agent(self, tag: str) -> bool:
        """Terminate a single agent's subprocess and reset its state."""
        proc = None
        with self.lock:
            self._cancelled_tags.add(tag)
            proc = self.procs.pop(tag, None)
            if self.statuses.get(tag) in (STATUS_THINKING, STATUS_ACTIVE):
                self.statuses[tag] = STATUS_IDLE
                self.token_usage[tag] = 0
                self.session_tags.discard(tag)
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            name = next((n for t, n, _ in AGENTS if t == tag), tag.upper())
            self.append_line(tag, f"── {name} terminated ──")
            self.append_line("master", f"── {tag.upper()} terminated ──")
            _state_tracker.STATE.record_restart("interrupted", f"{tag} terminated by user")
        with self.lock:
            self.progress[tag] = 0
        return proc is not None

    def terminate_all(self) -> None:
        """Kill every active subprocess and force-reset all UI telemetry."""
        with self.lock:
            procs = list(self.procs.values())
            self.procs.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        self.force_ui_idle()
        self.append_line("master", "── terminated ──")
        _state_tracker.STATE.record_restart("interrupted", "terminated by user")

    def force_ui_idle(self) -> None:
        """Reset every UI telemetry field to idle."""
        self._abort_event.set()
        with self.lock:
            self.running = 0
            self.session_tags.clear()
            for tag, _name, _agent in AGENTS:
                self.statuses[tag] = STATUS_IDLE
                self.progress[tag] = 0
                self.token_usage[tag] = 0


HUB = RunHub()
