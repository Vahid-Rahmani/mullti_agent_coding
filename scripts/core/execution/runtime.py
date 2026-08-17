"""Server-owned workflow registry with durable snapshots.

The browser only observes runs through APIs; worker threads and provider
subprocesses belong to the dashboard server. Snapshots are atomically journaled
under ``_logs/`` so reconnects and post-restart history remain available.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from scripts.core.agents import PROJECT_ROOT
from scripts.core.workflows import Workflow

_RUNS: dict[str, object] = {}
_ARCHIVED: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()
_STORE_PATH: Path | None = PROJECT_ROOT / "_logs" / "workflow_runs.json"
_POLL_SECONDS = 0.08


def configure_store(path: Path | None) -> None:
    """Set the runtime journal location (a focused test seam)."""
    global _STORE_PATH
    _STORE_PATH = path
    _load_archive()


def _load_archive() -> None:
    global _ARCHIVED
    if _STORE_PATH is None:
        _ARCHIVED = {}
        return
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        rows = raw.get("runs", {}) if isinstance(raw, dict) else {}
        _ARCHIVED = {str(key): value for key, value in rows.items()
                     if isinstance(value, dict)}
    except (OSError, ValueError, TypeError):
        _ARCHIVED = {}


def _persist() -> None:
    """Persist snapshot copies without allowing I/O failure to stop a run."""
    if _STORE_PATH is None:
        return
    with _RUNS_LOCK:
        rows = dict(_ARCHIVED)
        rows.update({run_id: runner.snapshot() for run_id, runner in _RUNS.items()})
    try:
        _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _STORE_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "runs": rows}, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, _STORE_PATH)
    except OSError:
        pass


def _journal_runner(runner) -> None:
    """Journal independently from SSE/API clients until a run settles."""
    while True:
        _persist()
        if runner.finished:
            _persist()
            return
        time.sleep(_POLL_SECONDS)


def start_run(workflow: Workflow, initial_state: dict | None = None,
              dispatch_fn=None, repo_root=None) -> str:
    """Register and start a server-owned background run; return its id."""
    from scripts.core.workflow_engine import WorkflowRunner

    runner = WorkflowRunner(workflow, dispatch_fn=dispatch_fn, repo_root=repo_root)
    # Completion is journaled synchronously as well as by the background
    # watcher, closing the small window between a finished worker and a server
    # restart.
    runner.on_finished = _persist
    with _RUNS_LOCK:
        _RUNS[runner.run_id] = runner
        _ARCHIVED.pop(runner.run_id, None)
    runner.start(initial_state)
    threading.Thread(target=_journal_runner, args=(runner,),
                     name=f"wf-journal-{runner.run_id}", daemon=True).start()
    _persist()
    return runner.run_id


def get_run(run_id: str):
    with _RUNS_LOCK:
        return _RUNS.get(run_id)


def cancel_run(run_id: str) -> bool:
    runner = get_run(run_id)
    if runner is None:
        return False
    runner.cancel()
    _persist()
    return True


def snapshot(run_id: str) -> dict | None:
    """Return a live snapshot when possible, otherwise durable history."""
    runner = get_run(run_id)
    if runner is not None:
        return runner.snapshot()
    with _RUNS_LOCK:
        saved = _ARCHIVED.get(run_id)
        return dict(saved) if saved is not None else None


def list_runs() -> list[dict]:
    with _RUNS_LOCK:
        rows = {run_id: dict(item) for run_id, item in _ARCHIVED.items()}
        rows.update({run_id: runner.snapshot() for run_id, runner in _RUNS.items()})
    return [rows[run_id] for run_id in sorted(rows)]


def clear_runs() -> None:
    """Drop runtime state (test helper / teardown)."""
    with _RUNS_LOCK:
        _RUNS.clear()
        _ARCHIVED.clear()


_load_archive()
