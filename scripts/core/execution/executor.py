"""Executor — the adapter-backed dispatch boundary (Phase 5).

The workflow engine's wave scheduler is untouched. This module replaces the
old inline subprocess dispatch with a clean pipeline:

    WorkflowRunner → plan_node → ProviderAdapter.execute → ExecutionResult

``execute_node`` runs one planned node through its adapter with:

* a per-node **timeout** (default 300s; adapter kills the child on expiry),
* **cancellation** (the runner's event propagates to the adapter, which
  terminates the in-flight subprocess — no orphans),
* bounded, opt-in **retries** (default 0 — existing behavior unchanged unless
  the workflow sets ``settings.node_max_retries``).

Every attempt produces a full :class:`ExecutionResult` and ordered
:class:`ExecutionEvent` records; the final result is what the runner stores
per node id. Credentials never appear in results, events, or exceptions.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from scripts.core.execution.errors import (
    AdapterCancelledError,
    AdapterError,
    AdapterTimeoutError,
    PlanError,
)
from scripts.core.execution.planner import NodePlan, plan_node
from scripts.core.execution.schema import ExecutionResult, iso_now
from scripts.core.model_connections.credential_store import redact
from scripts.core.providers.base import adapter_for
from scripts.core.workflows import WorkflowNode

DEFAULT_NODE_TIMEOUT = 300      # seconds; conservative, backward compatible
DEFAULT_MAX_RETRIES = 0         # opt-in: existing behavior unchanged
_RETRY_DELAY = 0.0              # deterministic retries (no random backoff)


def execute_node(
    plan: NodePlan,
    adapter,
    connection,
    *,
    timeout: float | None = None,
    max_retries: int = 0,
    cancel_event=None,
    execution_id: str = "",
    on_event=None,
) -> ExecutionResult:
    """Execute one planned node with timeout + bounded retry.

    ``on_event(event_type, result, attempt)`` is called for every emitted node
    event (node_started per attempt, node_completed/node_failed per attempt)
    so the caller can persist ordered events. Returns the **final**
    ``ExecutionResult`` (last attempt).
    """
    timeout = timeout if timeout is not None else DEFAULT_NODE_TIMEOUT
    max_attempts = max(0, int(max_retries or 0)) + 1
    last: ExecutionResult | None = None

    request = (
        dataclasses.replace(
            plan.request,
            metadata={**plan.request.metadata, "execution_id": execution_id or ""},
        )
        if plan.request is not None
        else None
    )

    for attempt in range(1, max_attempts + 1):
        node_execution_id = f"{execution_id or 'run'}-{plan.node_id}-{attempt}"
        started_at = iso_now()
        started = time.monotonic()
        status = "completed"
        response = ""
        error = ""
        error_code = ""
        usage: dict = {}
        provider = plan.provider

        if on_event:
            on_event("node_started", None, attempt)

        try:
            resp = adapter.execute(
                request, connection,
                timeout=timeout,
                cancel_event=cancel_event,
                execution_id=node_execution_id,
            )
            response = resp.text or ""
            usage = dict(resp.usage or {})
            if resp.provider:
                provider = resp.provider
        except AdapterCancelledError as exc:
            status = "failed"
            error = str(exc)
            error_code = exc.error_code
        except AdapterTimeoutError as exc:
            status = "failed"
            error = str(exc)
            error_code = exc.error_code
        except AdapterError as exc:
            status = "failed"
            error = str(exc)
            error_code = getattr(exc, "error_code", "adapter_error")
        except Exception as exc:  # noqa: BLE001 — never leak raw internals
            status = "failed"
            error = redact(str(exc)) or "execution failed"
            error_code = "execution_error"

        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        result = ExecutionResult(
            execution_id=execution_id or "",
            node_execution_id=node_execution_id,
            status=status,
            started_at=started_at,
            finished_at=iso_now(),
            latency_ms=latency_ms,
            response=response,
            error=error,
            usage=usage,
            model=plan.model,
            provider=provider,
            error_code=error_code,
        )
        last = result
        if on_event:
            on_event("node_completed" if status == "completed" else "node_failed",
                     result, attempt)
        if status == "completed":
            break

    assert last is not None
    return last


def default_dispatch_for(runner, *, timeout=None, max_retries=None):
    """Build the runner's default ``dispatch_fn`` (adapter-backed).

    ``timeout``/``max_retries`` default to the workflow's
    ``settings.node_timeout`` / ``settings.node_max_retries`` (or the module
    defaults) — so existing workflows behave exactly as before unless they
    opt in. The returned callable matches the engine's dispatch contract::

        dispatch_fn(node, prompt, state, repo_root) -> DispatchResult
    """
    return _AdapterDispatch(
        runner,
        timeout=_resolve_setting(runner, timeout, "node_timeout", DEFAULT_NODE_TIMEOUT),
        max_retries=_resolve_setting(runner, max_retries, "node_max_retries", DEFAULT_MAX_RETRIES),
    )


def _resolve_setting(runner, explicit, key: str, default):
    if explicit is not None:
        return explicit
    try:
        return int((runner.workflow.settings or {}).get(key, default))
    except (TypeError, ValueError):
        return default


class _AdapterDispatch:
    """Dispatch callable that plans + executes a node through the adapter.

    Stateless across calls (the runner may invoke it concurrently for nodes in
    the same wave): every per-call value is captured in a closure.
    """

    def __init__(self, runner, *, timeout: float, max_retries: int) -> None:
        self.runner = runner
        self.timeout = timeout
        self.max_retries = max_retries

    def __call__(self, node: WorkflowNode, prompt: str, state: dict,
                 repo_root: Path | None = None):
        runner = self.runner

        try:
            plan = plan_node(node, state, repo_root, execution_id=runner.run_id)
        except PlanError as exc:
            model = node.model or ""
            provider = "opencode"
            runner.record_event("node_started", node_id=node.id, status="running",
                                model=model, provider=provider)
            failed = ExecutionResult(
                execution_id=runner.run_id,
                node_execution_id=f"{runner.run_id}-{node.id}",
                status="failed",
                started_at=iso_now(), finished_at=iso_now(), latency_ms=0.0,
                error=str(exc), error_code="plan_error",
                model=model, provider=provider,
            )
            runner.record_execution(node.id, failed)
            runner.record_event("node_failed", node_id=node.id, status="failed",
                                model=model, provider=provider, error_code="plan_error")
            return _failure(str(exc))

        model, provider = plan.model, plan.provider

        def on_event(event_type, result, attempt):
            if event_type == "node_started":
                runner.record_event("node_started", node_id=node.id,
                                    status="running", model=model, provider=provider)
            else:
                runner.record_event(
                    event_type, node_id=node.id, status=result.status,
                    model=result.model, provider=result.provider,
                    latency_ms=result.latency_ms, usage=result.usage,
                    error_code=result.error_code)

        result = execute_node(
            plan, adapter_for(plan.resolution), plan.connection,
            timeout=self.timeout, max_retries=self.max_retries,
            cancel_event=runner.cancelled, execution_id=runner.run_id,
            on_event=on_event,
        )
        runner.record_execution(node.id, result)
        if result.status == "completed":
            return _success(result.response)
        return _failure(result.error or "execution failed")


def _success(output: str):
    from scripts.core.workflow_engine import DispatchResult

    return DispatchResult("success", output)


def _failure(output: str):
    from scripts.core.workflow_engine import DispatchResult

    return DispatchResult("failure", output)
