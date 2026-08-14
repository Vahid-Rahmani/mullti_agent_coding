"""Execution layer — provider-neutral request/response, planner, executor, runtime (Phase 5).

Only the leaf modules (``errors``, ``schema``) are imported eagerly here:
``providers.base`` imports ``execution.schema`` while ``execution.planner``
imports ``providers.base``, so the package init must stay lean to avoid an
import cycle. The heavier modules are imported directly as submodules::

    from scripts.core.execution.planner import plan_node
    from scripts.core.execution.executor import default_dispatch_for
    from scripts.core.execution.runtime import start_run
"""

from __future__ import annotations

from scripts.core.execution import errors, schema
from scripts.core.execution.schema import (
    ExecutionEvent,
    ExecutionResult,
    ModelRequest,
    ModelResponse,
)

__all__ = [
    "errors",
    "schema",
    "ExecutionEvent",
    "ExecutionResult",
    "ModelRequest",
    "ModelResponse",
]
