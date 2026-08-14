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
registry (``scripts.core.execution.runtime``) — never in ``AgentSpec``,
``roles.json``, or ``opencode.json``.

Phase 5: the default node dispatch is adapter-backed
(``scripts.core.execution.executor`` → ``ProviderAdapter`` → OpenCode CLI),
and every run emits ordered execution events plus per-node records
(``ExecutionResult``) that appear in the run snapshot. The wave scheduler
itself is unchanged.
"""

from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.core.execution.planner import build_node_prompt  # canonical builder
from scripts.core.execution.schema import utc_now_iso
from scripts.core.workflows import Workflow, WorkflowNode, effective_entry

@dataclass
class DispatchResult:
    """Outcome of one node's dispatch. ``outcome`` is success | failure."""

    outcome: str
    output: str = ""


def _dry_dispatch(node: WorkflowNode, prompt: str, state: dict,
                  repo_root: Path | None = None) -> DispatchResult:
    """Dry-run dispatch: report success without launching any agent process.

    Used only by :func:`simulate_workflow` so a dry-run previews the execution
    plan (waves, branches, fan-in, conditions, retry bounds) without side
    effects — nothing is written and no agent ever runs.
    """
    return DispatchResult("success", "")


class WorkflowRunner:
    """Executes one workflow run with isolated state and wave scheduling."""

    def __init__(self, workflow: Workflow, dispatch_fn=None,
                 repo_root: Path | None = None) -> None:
        self.workflow = workflow
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
        # Phase 5: ordered execution events + per-node execution records.
        self.events: list[dict] = []
        self.executions: dict[str, dict] = {}
        # The default dispatch is the adapter-backed execution pipeline
        # (planner → ProviderAdapter → OpenCode). Custom dispatch fns (tests,
        # dry-run) bypass it exactly as before.
        if dispatch_fn is None:
            from scripts.core.execution.executor import default_dispatch_for

            dispatch_fn = default_dispatch_for(self)
        self.dispatch_fn = dispatch_fn

    # ------------------------------------------------- execution records

    def record_event(self, event_type: str, *, node_id: str = "",
                     status: str = "", model: str = "", provider: str = "",
                     latency_ms: float | None = None, usage: dict | None = None,
                     error_code: str = "") -> None:
        """Append one ordered execution event (never contains secrets)."""
        from scripts.core.execution.schema import ExecutionEvent

        ev = ExecutionEvent(
            execution_id=self.run_id,
            workflow_id=self.workflow.id,
            timestamp=utc_now_iso(),
            event_type=event_type,
            node_id=node_id,
            status=status,
            model=model,
            provider=provider,
            latency_ms=latency_ms,
            usage=usage or {},
            error_code=error_code,
        )
        with self.lock:
            self.events.append(ev.to_dict())

    def record_execution(self, node_id: str, result) -> None:
        """Store the final ExecutionResult for a node (per run)."""
        with self.lock:
            self.executions[node_id] = result.to_dict()

    # ------------------------------------------------------------ public

    def start(self, initial_state: dict | None = None) -> str:
        """Begin execution on a background thread; return the run id."""
        self.record_event("workflow_started", status="running",
                          model="", provider="")
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
        plan_rows = self._plan_preview()
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
            # Phase 5: per-node resolved plan metadata (model/connection/
            # adapter/prompt_profile/task) — resolved WITHOUT executing.
            "plan": plan_rows,
        }

    def _plan_preview(self) -> list[dict]:
        """Resolve safe execution-plan metadata per enabled agent node.

        Reuses the planner so a dry run answers "what would execute, with which
        model / connection / adapter, in what order" — but never resolves
        credentials and never executes anything.
        """
        from scripts.core.execution.errors import PlanError
        from scripts.core.execution.planner import plan_node

        rows: list[dict] = []
        for n in self.workflow.nodes:
            if n.kind != "agent" or not n.enabled:
                continue
            try:
                rows.append(plan_node(n, dict(self.state), self.repo_root).to_dict())
            except PlanError as exc:
                rows.append({"node_id": n.id, "error": str(exc)})
        return rows

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
                # Phase 5: ordered execution events + per-node execution records
                "events": [dict(e) for e in self.events],
                "executions": {k: dict(v) for k, v in self.executions.items()},
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
            cancelled = self.cancelled.is_set()
            failed = any(s == "failed" for s in self.statuses.values())
            if cancelled or failed:
                self.record_event(
                    "workflow_failed", status="failed",
                    error_code="cancelled" if cancelled else "node_failed")
            else:
                self.record_event("workflow_completed", status="completed")
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


# ---------------------------------------------------------------- dry run


def simulate_workflow(workflow: Workflow, initial_state: dict | None = None,
                      repo_root: Path | None = None) -> dict:
    """Dry-run a workflow without dispatching any agent; return the plan."""
    runner = WorkflowRunner(workflow, dispatch_fn=_dry_dispatch, repo_root=repo_root)
    return runner.simulate(initial_state)


# ---------------------------------------------------------------- run registry
#
# The in-memory run registry now lives in scripts.core.execution.runtime;
# these thin delegators keep the previous public API (and any module-level
# patching of ``workflow_engine.start_run`` in tests/routes) working unchanged.

from scripts.core.execution import runtime as _execution_runtime  # noqa: E402


def start_run(workflow: Workflow, initial_state: dict | None = None,
              dispatch_fn=None, repo_root: Path | None = None) -> str:
    """Register and start a run via the execution runtime; returns the run id."""
    return _execution_runtime.start_run(
        workflow, initial_state=initial_state, dispatch_fn=dispatch_fn,
        repo_root=repo_root)


def get_run(run_id: str):
    """Return the runner for a run id (or None)."""
    return _execution_runtime.get_run(run_id)


def cancel_run(run_id: str) -> bool:
    """Cancel a run (also terminates in-flight adapter subprocesses)."""
    return _execution_runtime.cancel_run(run_id)


def list_runs() -> list[dict]:
    """Snapshots of every registered run."""
    return _execution_runtime.list_runs()


if __name__ == "__main__":  # pragma: no cover — manual smoke only
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("workflow_engine module (no standalone CLI)")
