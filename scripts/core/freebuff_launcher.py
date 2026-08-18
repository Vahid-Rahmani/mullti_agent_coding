"""Minimal Windows-only FreeBuff CMD launcher.

This deliberately does not participate in Agent prompt/runtime execution.  It
only opens one real Command Prompt per Agent when FreeBuff is selected.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from threading import Lock

_LOCK = Lock()
from scripts.core.providers.terminal import TerminalProcess

_PROCESSES: dict[str, TerminalProcess] = {}
_OUTPUT_LOCK = threading.Condition(Lock())
_OUTPUT_COUNTS: dict[str, tuple[TerminalProcess, int]] = {}
# FreeBuff enters the alternate screen while it is still showing its
# onboarding/model-selection view.  That sequence is therefore not an input
# readiness signal: sending Enter there races the first TUI frame.  The first
# stable view that accepts the bootstrap confirmation has a deterministic
# title instead.
# FreeBuff has used both onboarding labels across releases/screen sizes.  Both
# are emitted by the TUI only after the alternate screen is mounted and the
# input surface exists; CMD output alone contains neither phrase.
_READY_MARKERS = ("Start coding for free", "Enter a coding task")
_READY_MARKER = _READY_MARKERS[0]  # compatibility for focused tests/callers
_READY_TAIL = max(len(marker) for marker in _READY_MARKERS) - 1


def _freebuff_executable() -> str | None:
    for name in ("freebuff", "freebuff.cmd", "freebuff.exe", "freebuff.ps1"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _observe_tui_bootstrap(proc: TerminalProcess, text: str, tail: str,
                           bootstrap_done: bool) -> tuple[str, bool]:
    """Observe one decoded PTY chunk without changing the delivered bytes.

    FreeBuff emits ``ESC[?1049h`` before its onboarding screen is ready.  Wait
    for the actual deterministic onboarding/input view instead.  The marker
    may be split at any PTY read boundary, so retain a bounded rolling tail.
    The caller owns the per-process ``bootstrap_done`` flag; once set, later
    redraws and resize output cannot trigger another automatic Enter.
    """
    probe = tail + text
    if not bootstrap_done and any(marker in probe for marker in _READY_MARKERS):
        proc.write("\r")
        bootstrap_done = True
    return probe[-_READY_TAIL:], bootstrap_done


def launch_freebuff_cmd(agent: str, workspace: Path, on_output=None,
                        cols: int | None = None, rows: int | None = None) -> dict:
    """Open/reuse ``cmd.exe`` with FreeBuff inside the Agent's ConPTY."""
    if os.name != "nt":
        raise RuntimeError("FreeBuff CMD launcher is Windows-only")
    key = str(agent).strip()
    if not key:
        raise ValueError("agent is required")
    if cols is None or rows is None:
        raise ValueError("initial terminal dimensions are required before FreeBuff launch")
    cols = max(2, min(int(cols), 512))
    rows = max(2, min(int(rows), 256))
    exe = _freebuff_executable()
    if not exe:
        raise FileNotFoundError("FreeBuff executable was not found on PATH")
    root = workspace.resolve()
    with _LOCK:
        current = _PROCESSES.get(key)
        if current is not None and current.poll() is None:
            current.resize(cols, rows)
            return {"state": "reused", "agent": key, "pid": current.pid,
                    "cwd": str(root), "executable": exe,
                    "cols": cols, "rows": rows}
        # The browser has already measured the terminal.  Pass that grid into
        # ConPTY creation so FreeBuff cannot enter alternate-screen mode at
        # pywinpty's 80x24 default.
        proc = TerminalProcess("cmd.exe", root, cols=cols, rows=rows)
        _PROCESSES[key] = proc
        with _OUTPUT_LOCK:
            _OUTPUT_COUNTS[key] = (proc, 0)
        proc.write(f'cd /d "{root}"\r')
        proc.write("freebuff\r")
        def pump():
            bootstrap_done = False
            bootstrap_tail = ""
            try:
                while proc.poll() is None:
                    data = proc.read_available(0.1)
                    if not data:
                        continue
                    text = data.decode("utf-8", "replace")
                    with _OUTPUT_LOCK:
                        current = _OUTPUT_COUNTS.get(key)
                        if current is not None and current[0] is proc:
                            _OUTPUT_COUNTS[key] = (proc, current[1] + 1)
                            _OUTPUT_LOCK.notify_all()
                    # Forward every original chunk immediately and verbatim;
                    # bootstrap detection is observational side-effect only.
                    if on_output:
                        on_output(text)
                    bootstrap_tail, bootstrap_done = _observe_tui_bootstrap(
                        proc, text, bootstrap_tail, bootstrap_done,
                    )
            finally:
                with _LOCK:
                    if _PROCESSES.get(key) is proc:
                        _PROCESSES.pop(key, None)
                    with _OUTPUT_LOCK:
                        current = _OUTPUT_COUNTS.get(key)
                        if current is not None and current[0] is proc:
                            _OUTPUT_COUNTS.pop(key, None)
                            _OUTPUT_LOCK.notify_all()
        threading.Thread(target=pump, name=f"freebuff-cmd-{key}", daemon=True).start()
        return {"state": "started", "agent": key, "pid": proc.pid,
                "cwd": str(root), "executable": exe,
                "command": f'cmd.exe /K cd /d "{root}" && freebuff',
                "cols": cols, "rows": rows,
                "embedded": True}


def process_for(agent: str):
    with _LOCK:
        return _PROCESSES.get(str(agent).strip())


def write_input(agent: str, text: str) -> bool:
    proc = process_for(agent)
    if proc is None or proc.poll() is not None:
        return False
    proc.write(text)
    return True


def output_checkpoint(agent: str, proc: TerminalProcess | None = None) -> int:
    """Return the live PTY output count before a prompt write."""
    with _OUTPUT_LOCK:
        current = _OUTPUT_COUNTS.get(str(agent).strip())
        if current is None or (proc is not None and current[0] is not proc):
            return -1
        return current[1]


def wait_for_output(agent: str, proc: TerminalProcess, checkpoint: int,
                    timeout: float = 1.0) -> bool:
    """Wait for a post-write PTY redraw before sending prompt Enter."""
    if checkpoint < 0:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    key = str(agent).strip()
    with _OUTPUT_LOCK:
        while True:
            current = _OUTPUT_COUNTS.get(key)
            if current is None or current[0] is not proc:
                return False
            if current[1] > checkpoint:
                return True
            if proc.poll() is not None:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _OUTPUT_LOCK.wait(remaining)


def resize_input(agent: str, cols: int, rows: int) -> bool:
    proc = process_for(agent)
    if proc is None or proc.poll() is not None:
        return False
    try:
        proc.resize(cols, rows)
        return True
    except (OSError, ValueError, AttributeError):
        return False


def stop_freebuff_cmd(agent: str) -> bool:
    with _LOCK:
        proc = _PROCESSES.pop(str(agent).strip(), None)
    if proc is None or proc.poll() is not None:
        return False
    proc.terminate()
    return True


__all__ = ["launch_freebuff_cmd", "output_checkpoint", "process_for",
           "resize_input", "stop_freebuff_cmd", "wait_for_output", "write_input"]
