"""Self-evolve bridge — checkpoint + dispatch + verify for self-evolution cycles."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from .agents import PROJECT_ROOT
from .run_hub import HUB
from . import state_tracker as _state_tracker

_SCRIPT_DIR = str(Path(__file__).resolve().parent.parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from self_evolve import SelfEvolveEngine, detect_optimization_loops  # noqa: E402

SELF_EVOLVE_ENGINE = SelfEvolveEngine(
    project_root=PROJECT_ROOT,
    record_decision=lambda text: _state_tracker.STATE.record_decision(text),
)


def _after_self_evolve_run(prompt: str, overrides: dict) -> None:
    """Wait for the dispatched swarm run, then verify and write the marker."""
    try:
        while HUB.running > 0:
            if HUB._abort_event.is_set():
                return
            time.sleep(0.2)
        if HUB._abort_event.is_set():
            return
        result = SELF_EVOLVE_ENGINE.verify()
        if result["ok"]:
            SELF_EVOLVE_ENGINE.write_restart_marker(
                payload={"source": "self-evolve", "prompt": prompt, "ok": True, "verified": True}
            )
        else:
            _state_tracker.STATE.record_restart("verify", "failed: " + "; ".join(result.get("errors") or []))
    except Exception as exc:  # noqa: BLE001
        if not HUB._abort_event.is_set():
            _state_tracker.STATE.record_restart("verify", "exception: " + str(exc))


def _spawn_self_evolve_watcher(prompt: str, overrides: dict) -> None:
    """Start the verify+marker watcher on a daemon thread."""
    t = threading.Thread(
        target=_after_self_evolve_run,
        args=(prompt, overrides),
        name="self-evolve-watcher",
        daemon=True,
    )
    HUB._evolve_thread = t
    t.start()


def run_self_evolve(
    prompt: str,
    overrides: dict,
    system_prompts: dict[str, str] | None = None,
    enabled_agents: set[str] | list[str] | tuple[str, ...] | None = None,
) -> str | None:
    """Checkpoint + dispatch a self-evolve cycle (terminal '/evolve' command)."""
    if not prompt.strip():
        return "Usage: /evolve <prompt>"
    checkpoint = SELF_EVOLVE_ENGINE.checkpoint(prompt)
    err = HUB.run(
        prompt, overrides, system_prompts=system_prompts, enabled_agents=enabled_agents,
    )
    if err:
        return err
    _spawn_self_evolve_watcher(prompt, overrides)
    return f"self-evolve checkpointed @ {checkpoint['git_head'] or 'no-git'}: {prompt}"
