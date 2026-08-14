"""Execution runtime — the in-memory run registry (Phase 5).

Centralizes the run registry that previously lived in ``workflow_engine._RUNS``
so the execution layer owns run lifecycle (start/get/cancel/snapshot) while the
workflow engine stays focused on graph scheduling. In-memory only — no database
in this phase; runs live for the server's lifetime exactly as before.

``workflow_engine`` re-exports the same function names for API compatibility,
so existing callers (routes, tests) keep working unchanged.
"""

from __future__ import annotations

import threading

from scripts.core.workflows import Workflow

_RUNS: dict[str, object] = {}       # run_id -> WorkflowRunner
_RUNS_LOCK = threading.Lock()


def start_run(workflow: Workflow, initial_state: dict | None = None,
              dispatch_fn=None, repo_root=None) -> str:
    """Register and start a run; returns the run id."""
    from scripts.core.workflow_engine import WorkflowRunner

    runner = WorkflowRunner(workflow, dispatch_fn=dispatch_fn, repo_root=repo_root)
    with _RUNS_LOCK:
        _RUNS[runner.run_id] = runner
    runner.start(initial_state)
    return runner.run_id


def get_run(run_id: str):
    with _RUNS_LOCK:
        return _RUNS.get(run_id)


def cancel_run(run_id: str) -> bool:
    runner = get_run(run_id)
    if runner is None:
        return False
    runner.cancel()
    return True


def list_runs() -> list[dict]:
    with _RUNS_LOCK:
        return [runner.snapshot() for runner in _RUNS.values()]


def snapshot(run_id: str) -> dict | None:
    """Full execution snapshot for a run (includes events + per-node records)."""
    runner = get_run(run_id)
    return runner.snapshot() if runner is not None else None


def clear_runs() -> None:
    """Drop the registry (test helper / teardown)."""
    with _RUNS_LOCK:
        _RUNS.clear()
