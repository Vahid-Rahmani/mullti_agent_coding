"""Run hub — thread-safe execution engine for the multi-agent swarm.

RunHub spawns one worker thread per target agent; each thread streams
``opencode run`` output into per-tag buffers via subprocess management.
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
    AGENTS, _AGENT_TAGS, AGENT_SPEC_BY_TAG, AUTO_MODE, AUTO_MODEL,
    IMMUTABLE_TAGS, M7_AUDIT_MODE, MODE_TO_AGENT, PROJECT_ROOT,
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


def _build_run_command(
    exe: str, agent: str, prompt: str, model: str | None, mode: str | None = None
) -> list[str]:
    """Build the ``opencode run`` argv for one agent."""
    chosen_agent = mode if mode and mode != AUTO_MODE else agent
    chosen_agent = MODE_TO_AGENT.get(chosen_agent, chosen_agent)
    cmd = [exe, "run", "--agent", chosen_agent, "--auto"]
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
        self._audit_thread: threading.Thread | None = None
        self._evolve_thread: threading.Thread | None = None
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

    def resolve(self, tag: str, overrides: dict[str, dict[str, str]]) -> tuple[str | None, str]:
        """Resolve (model, mode) for a tag: tag override > master override > auto."""
        if tag in IMMUTABLE_TAGS:
            spec = AGENT_SPEC_BY_TAG[tag]
            return (spec.pinned_model or "opencode/ling-3.0-tiny-free", spec.pinned_mode or M7_AUDIT_MODE)
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
        enabled_agents: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> str | None:
        """Spawn one worker thread per target agent."""
        if not prompt.strip():
            return "Prompt must not be empty."
        enabled = set(enabled_agents) if enabled_agents is not None else set(_AGENT_TAGS)
        targets = [
            a for a in AGENTS
            if a[0] in enabled and (not agents or a[0] in agents)
        ]
        if not targets:
            return "No agents matched the /agents filter."
        # Log the prompt into the Obsidian vault (best-effort).
        try:
            import prompt_logger

            _log_tab = agents[0] if agents and len(agents) == 1 else "master"
            _target_tags = [t[0] for t in targets] if agents else None
            _prompt_path = prompt_logger.log_prompt(
                prompt, target_agents=_target_tags, active_tab=_log_tab,
            )
            _prompt_log_id = _prompt_path.stem
            import agent_logger

            agent_logger.ensure_agent_logs([t[0] for t in targets])
        except Exception:
            _prompt_log_id = None
        self.append_line("master", f"▶ {prompt}")
        pruned = prune_prompt(prompt)
        _state_tracker.STATE.record_run(pruned, time.strftime("%Y-%m-%dT%H:%M:%S"))
        system_prompts = system_prompts or {}
        dispatch_prompts: dict[str, str] = {}
        with self.lock:
            if self.running == 0:
                self.session_tags.clear()
                self._abort_event.clear()
            self._cancelled_tags.difference_update(tag for tag, _name, _agent in targets)
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
            self._emit(tag, "run", f"{tag.upper()}::{_sanitize_prompt(prompt)[:60]}")
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
        _killed = False
        try:
            exe = _opencode_command()
            if not exe:
                raise FileNotFoundError(
                    "opencode executable not found on PATH. Install opencode or "
                    "add it to PATH before using the terminal."
                )
            cmd = _build_run_command(exe, agent, prompt, model, mode)
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
            try:
                if prompt_log_id:
                    import agent_logger

                    agent_logger.append_agent_run(
                        tag, prompt, prompt_log_id,
                        status="ok" if ok else "failed",
                        duration_s=time.time() - _start,
                    )
            except Exception:
                pass
            if tag == "m7" and ok and not _killed:
                self._run_m7_audit(prompt)

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
        if self._audit_thread is not None and self._audit_thread.is_alive():
            self._audit_thread.join(timeout=2.0)
        self._audit_thread = None
        self._evolve_thread = None
        with self.lock:
            self.running = 0
            self.session_tags.clear()
            for tag, _name, _agent in AGENTS:
                self.statuses[tag] = STATUS_IDLE
                self.progress[tag] = 0
                self.token_usage[tag] = 0

    def _run_m7_audit(self, prompt: str = "") -> None:
        """Run the M7 vault audit + archivist sync (best-effort; never blocks)."""
        def _audit() -> None:
            try:
                import obsidian_auditor

                result = obsidian_auditor.audit_run()
                if self._abort_event.is_set() or self._tag_cancelled("m7"):
                    return
                self.append_line("master", result["summary"])
                if not result["ok"]:
                    for issue in result.get("integrity", {}).get("issues", []):
                        self.append_line("m7", f"AUDIT: {issue}")
                    for orphan in result.get("cross_ref", {}).get("orphaned_prompts", []):
                        self.append_line("m7", f"AUDIT: orphaned prompt {orphan}")
            except Exception as exc:  # noqa: BLE001
                if not self._abort_event.is_set() and not self._tag_cancelled("m7"):
                    self.append_line("m7", f"AUDIT ERROR: {exc}")
            # Architectural Obsidian Archivist — rules 1-5 (filter, store,
            # mermaid map, maintenance, lean evolution).
            if self._abort_event.is_set() or self._tag_cancelled("m7"):
                return
            try:
                from .archivist import archivist_run

                arch = archivist_run(prompt, workspace=self.workspace)
                if self._abort_event.is_set() or self._tag_cancelled("m7"):
                    return
                for line in arch["summary"].splitlines():
                    self.append_line("m7", f"ARCHIVIST: {line}")
            except Exception as exc:  # noqa: BLE001
                if not self._abort_event.is_set() and not self._tag_cancelled("m7"):
                    self.append_line("m7", f"ARCHIVIST ERROR: {exc}")

        t = threading.Thread(target=_audit, name="m7-audit", daemon=True)
        self._audit_thread = t
        t.start()


HUB = RunHub()


def build_overrides_table(
    overrides: dict[str, dict[str, str]], hub: RunHub | None = None
) -> str:
    """Render every tab's effective model/mode as an aligned table."""
    if hub is None:
        hub = HUB
    from .agents import TABS

    rows: list[tuple[str, str, str, str]] = []
    for tag, _name, _agent in TABS:
        model, mode = hub.resolve(tag, overrides)
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


def _agent_tab_identity(
    tag: str,
    overrides: dict[str, dict[str, str]] | None = None,
    hub: RunHub | None = None,
) -> tuple[str, str]:
    """Return the effective display name and role badge for an agent tab."""
    from .agents import AGENTS, _AGENT_PERSONAS, MODE_TO_AGENT, AUTO_MODE

    base = next(((name, agent) for item, name, agent in AGENTS if item == tag), (tag.upper(), tag))
    persona_key = base[1]
    mode = None
    if overrides is not None:
        if hub is None:
            hub = HUB
        _model, mode = hub.resolve(tag, overrides)
    if mode and mode != AUTO_MODE:
        persona_key = MODE_TO_AGENT.get(mode, persona_key)
    return _AGENT_PERSONAS.get(persona_key, (base[0], mode or tag.upper()))
