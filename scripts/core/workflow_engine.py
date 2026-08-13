"""Workflow execution engine — LangGraph-style graph semantics.

Each workflow node runs an agent (or is a terminal ``end`` no-op); edges carry
``""`` (unconditional flow), ``"success"`` or ``"failure"`` conditions. The
scheduler is a **wave** scheduler:

    * A node is *ready* when every incoming edge's source has settled and at
      least one incoming edge is active. (Fan-in waits for all branches;
      conditional routing activates exactly the matching branch.)
    * Ready nodes in the same wave run **concurrently** (parallel fan-out).
    * ``"success"``/``""`` edges flow when the source **completes**;
      ``"failure"`` edges flow when the source **fails** (a failed node stops
      the unconditional path — its downstream is skipped unless reached
      another way). A **disabled** node is never executed and never fires its
      edges, so a downstream node reachable only through it is skipped.
    * Loops are bounded by ``settings.max_iterations`` (default 3): a
      ``Reviewer --failure--> Developer`` retry cycle re-runs the target and
      can never spin forever.

Execution state is **isolated per run** and lives only in the in-memory run
registry — never in ``AgentSpec``, ``roles.json``, or ``opencode.json``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.core import opencode_cfg
from scripts.core import roles
from scripts.core.workflows import Workflow, WorkflowNode, effective_entry

@dataclass
class DispatchResult:
    """Outcome of one node's dispatch. ``outcome`` is success | failure."""

    outcome: str
    output: str = ""


def build_node_prompt(node: WorkflowNode, state: dict, repo_root: Path | None = None) -> str:
    """Compose a node's runtime prompt: roles + instructions + workflow state.

    A node's own ``roles`` override the agent's persistent assignments for this
    run only (never mutating ``roles.json``). Role context comes from the
    existing role store; the agent identity and model stay untouched.
    """
    parts: list[str] = []
    if node.roles:
        role_ctx = roles.render_role_context(
            node.agent, role_ids=list(node.roles), repo_root=repo_root)
    else:
        role_ctx = roles.agent_context(node.agent, repo_root=repo_root)
    if role_ctx:
        parts.append(role_ctx.strip())
    if node.instructions.strip():
        parts.append(node.instructions.strip())
    if state:
        parts.append("## Workflow state\n```json\n" + json.dumps(state, indent=2) + "\n```")
    return "\n\n".join(parts)


def _dry_dispatch(node: WorkflowNode, prompt: str, state: dict,
                  repo_root: Path | None = None) -> DispatchResult:
    """Dry-run dispatch: report success without launching any agent process.

    Used only by :func:`simulate_workflow` so a dry-run previews the execution
    plan (waves, branches, fan-in, conditions, retry bounds) without side
    effects — nothing is written and no agent ever runs.
    """
    return DispatchResult("success", "")


def _default_dispatch(node: WorkflowNode, prompt: str, state: dict,
                      repo_root: Path | None = None) -> DispatchResult:
    """Run one node through ``opencode run`` (the same plain dispatch as the hub)."""
    from scripts.core.run_hub import (  # local import keeps engine import-light
        _build_run_command, _insecure_tls_env, _opencode_command, _strip_ansi,
    )

    exe = _opencode_command()
    if not exe:
        return DispatchResult(
            "failure",
            "opencode executable not found on PATH. Install opencode or add it to PATH.",
        )
    model = node.model or opencode_cfg.resolve_model(node.agent, repo_root)
    if not prompt.strip():
        return DispatchResult("failure", "node produced an empty prompt")
    cmd = _build_run_command(exe, node.agent, prompt, model)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(repo_root) if repo_root is not None else Path.cwd()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            env=_insecure_tls_env(),
        )
    except OSError as exc:
        return DispatchResult("failure", f"failed to launch opencode: {exc}")
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = _strip_ansi(raw.rstrip("\r\n"))
            if line:
                lines.append(line)
    except (OSError, ValueError):
        pass
    returncode = proc.wait()
    return DispatchResult(
        "success" if returncode == 0 else "failure",
        "\n".join(lines),
    )


class WorkflowRunner:
    """Executes one workflow run with isolated state and wave scheduling."""

    def __init__(self, workflow: Workflow, dispatch_fn=None,
                 repo_root: Path | None = None) -> None:
        self.workflow = workflow
        self.dispatch_fn = dispatch_fn or _default_dispatch
        self.repo_root = repo_root
        self.run_id = uuid.uuid4().hex[:12]
        self.lock = threading.Lock()

        self.statuses: dict[str, str] = {}
        self.outputs: dict[str, str] = {}
        self.state: dict = dict(workflow.state)
        self.reason: dict[str, str] = {}
        self.visits: dict[str, int] = {}
        self.waves: list[list[str]] = []   # ordered execution waves (parallel groups)
        self.finished = False
        self.cancelled = threading.Event()
        self.nodes = {n.id: n for n in workflow.nodes}

    # ------------------------------------------------------------ public

    def start(self, initial_state: dict | None = None) -> str:
        """Begin execution on a background thread; return the run id."""
        thread = threading.Thread(
            target=self._run, args=(initial_state,), name=f"wf-{self.run_id}", daemon=True,
        )
        thread.start()
        return self.run_id

    def cancel(self) -> None:
        self.cancelled.set()

    def simulate(self, initial_state: dict | None = None) -> dict:
        """Preview the execution plan synchronously with a no-op dispatch.

        Runs the same wave scheduler (so sequential / parallel / fan-in /
        conditional routing / bounded retry are all honored) but never launches
        an agent. Returns the ordered waves, final statuses, reasons, start
        nodes, conditional edges and the loop bound — everything the UI needs
        to draw the planned path without touching a real run.
        """
        self.dispatch_fn = _dry_dispatch
        self._run_inner(initial_state)
        return {
            "waves": self.waves,
            "start_nodes": list(effective_entry(self.workflow)),
            "statuses": dict(self.statuses),
            "reasons": dict(self.reason),
            "conditional_edges": [
                {"source": e.source, "target": e.target, "condition": e.condition}
                for e in self.workflow.edges if e.condition
            ],
            "max_iterations": int(self.workflow.settings.get("max_iterations", 3)),
        }

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "run_id": self.run_id,
                "workflow_id": self.workflow.id,
                "workflow_name": self.workflow.name,
                "finished": self.finished,
                "statuses": dict(self.statuses),
                "outputs": {k: v[-2000:] for k, v in self.outputs.items()},
                "state": dict(self.state),
                "reason": dict(self.reason),
                "labels": {n.id: n.label for n in self.workflow.nodes},
            }

    # ------------------------------------------------------------ scheduler

    # Edge/flow semantics:
    #   * unconditional ("") edges fire when the source completes; each firing
    #     decrements the target's pending counter (fan-in AND semantics).
    #   * conditional ("success"/"failure") edges fire only when the source's
    #     outcome matches; they do not decrement pending (OR semantics).
    #   * a failed node stops its unconditional path (only its "failure" edges
    #     fire); a disabled node never runs and never fires, so a strictly
    #     downstream node is skipped.
    #   * loop re-entry: when an edge fires into a finished node, that node is
    #     reset to "waiting" and re-armed (pending = its unconditional in-degree)
    #     so a `Reviewer --failure--> Developer` retry loop re-runs the target
    #     instead of spinning. The loop is bounded by settings.max_iterations.

    def _activate(self, target: str, condition: str, pending: dict[str, int],
                  uncond_in: dict[str, int], enabled: set[str]) -> str | None:
        """Apply one edge firing to its target; return the id to enqueue (or None)."""
        if target not in enabled:
            return None
        status = self.statuses.get(target)
        if status in ("completed", "failed", "skipped"):
            # loop re-entry: re-arm and reset to waiting
            self.statuses[target] = "waiting"
            pending[target] = uncond_in[target]
            status = "waiting"
        if status != "waiting":
            return None  # already running / disabled
        if condition == "":
            pending[target] = max(0, pending[target] - 1)
        if pending[target] == 0 and self.statuses[target] == "waiting":
            return target
        return None

    def _run(self, initial_state: dict | None) -> None:
        try:
            self._run_inner(initial_state)
        finally:
            with self.lock:
                self.finished = True

    def _run_inner(self, initial_state: dict | None) -> None:
        self.state = dict(self.workflow.state)
        if initial_state:
            self.state.update(initial_state)

        enabled = {n.id for n in self.workflow.nodes if n.enabled}
        incoming: dict[str, list] = {}
        outgoing: dict[str, list] = {}
        uncond_in: dict[str, int] = {nid: 0 for nid in self.nodes}
        for edge in self.workflow.edges:
            incoming.setdefault(edge.target, []).append(edge)
            outgoing.setdefault(edge.source, []).append(edge)
            if edge.condition == "":
                uncond_in[edge.target] += 1

        for nid, node in self.nodes.items():
            self.statuses[nid] = "disabled" if not node.enabled else "waiting"
            self.visits[nid] = 0

        pending: dict[str, int] = dict(uncond_in)
        max_iters = int(self.workflow.settings.get("max_iterations", 3))

        # Seed the first wave from the explicit/inferred entry nodes. A cyclic
        # workflow's first node may have a conditional edge back into it, so it
        # is not reachable purely via zero-in-degree inference — hence entry.
        seed = set(effective_entry(self.workflow))
        seed.update(nid for nid in enabled if not incoming.get(nid))
        queue = sorted(seed & enabled)

        while queue:
            if self.cancelled.is_set():
                for nid in queue:
                    self.statuses[nid] = "failed"
                    self.reason[nid] = "cancelled"
                break
            wave = sorted(set(queue))
            queue = []
            wave = [nid for nid in wave if self.statuses.get(nid) == "waiting"]
            if not wave:
                break
            self.waves.append(list(wave))
            for nid in wave:
                self.statuses[nid] = "running"
            results = self._run_wave(wave)
            for nid in wave:
                self.visits[nid] += 1
                if self.visits[nid] > max_iters:
                    self.statuses[nid] = "failed"
                    self.reason[nid] = "loop limit exceeded"
                    continue
                res = results.get(nid)
                if res is None:
                    self.statuses[nid] = "failed"
                    self.reason[nid] = "dispatch returned no result"
                    continue
                outcome = res.outcome if res.outcome in ("success", "failure") else "success"
                self.outputs[nid] = res.output
                self.state[nid] = res.output
                self.statuses[nid] = "completed" if outcome == "success" else "failed"
                for edge in outgoing.get(nid, []):
                    fired = (edge.condition == "") or (edge.condition == outcome)
                    if not fired:
                        continue
                    nxt = self._activate(edge.target, edge.condition, pending, uncond_in, enabled)
                    if nxt:
                        queue.append(nxt)

        for nid in enabled:
            if self.statuses.get(nid) == "waiting":
                self.statuses[nid] = "skipped"
                self.reason[nid] = "unreachable"

    def _run_wave(self, wave: list[str]) -> dict[str, DispatchResult]:
        results: dict[str, DispatchResult] = {}
        threads: list[threading.Thread] = []

        def run_one(nid: str) -> None:
            node = self.nodes[nid]
            if self.cancelled.is_set():
                results[nid] = DispatchResult("failure", "cancelled")
                return
            if node.kind == "end":
                results[nid] = DispatchResult("success", "")
                return
            prompt = build_node_prompt(node, dict(self.state), self.repo_root)
            try:
                results[nid] = self.dispatch_fn(
                    node, prompt, dict(self.state), self.repo_root)
            except Exception as exc:  # noqa: BLE001
                results[nid] = DispatchResult("failure", str(exc))

        for nid in wave:
            thread = threading.Thread(target=run_one, args=(nid,), daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        return results


# ---------------------------------------------------------------- run registry

_RUNS: dict[str, WorkflowRunner] = {}
_RUNS_LOCK = threading.Lock()


def simulate_workflow(workflow: Workflow, initial_state: dict | None = None,
                      repo_root: Path | None = None) -> dict:
    """Dry-run a workflow without dispatching any agent; return the plan."""
    runner = WorkflowRunner(workflow, dispatch_fn=_dry_dispatch, repo_root=repo_root)
    return runner.simulate(initial_state)


def start_run(workflow: Workflow, initial_state: dict | None = None,
              dispatch_fn=None, repo_root: Path | None = None) -> str:
    """Register and start a run; returns the run id."""
    runner = WorkflowRunner(workflow, dispatch_fn=dispatch_fn, repo_root=repo_root)
    with _RUNS_LOCK:
        _RUNS[runner.run_id] = runner
    runner.start(initial_state)
    return runner.run_id


def get_run(run_id: str) -> WorkflowRunner | None:
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


if __name__ == "__main__":  # pragma: no cover — manual smoke only
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("workflow_engine module (no standalone CLI)")
