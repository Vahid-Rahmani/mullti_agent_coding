"""Execution-layer errors (Phase 5).

All messages are secret-free by construction: they are produced from typed
error codes and static text — never from request/response bodies or raw
exceptions that could embed credentials. The executor additionally routes
unexpected exceptions through :func:`scripts.core.model_connections.
credential_store.redact` as defense-in-depth.
"""

from __future__ import annotations


class ExecutionError(RuntimeError):
    """Base error for the execution layer."""


class PlanError(ExecutionError):
    """A node could not be planned (e.g. an explicit connection is invalid).

    Raised for *explicit* connection resolution failures so execution fails
    loudly (an explicit connection selection is authoritative — never silently
    replaced). Implicit (auto) resolution degrades to the local OpenCode
    default and is reported as safe plan metadata instead.
    """


class AdapterError(ExecutionError):
    """A provider adapter failed to execute a request.

    ``error_code`` is a stable machine-readable code (e.g. ``timeout``,
    ``cancelled``, ``nonzero_exit``, ``opencode_missing``) surfaced in
    ``ExecutionResult.error_code`` and execution events.
    """

    def __init__(self, message: str, *, error_code: str = "adapter_error") -> None:
        super().__init__(message)
        self.error_code = error_code


class AdapterTimeoutError(AdapterError):
    """A node execution exceeded its per-node timeout and was terminated."""

    def __init__(self, message: str = "execution timed out") -> None:
        super().__init__(message, error_code="timeout")


class AdapterCancelledError(AdapterError):
    """The run was cancelled while the node was executing."""

    def __init__(self, message: str = "execution cancelled") -> None:
        super().__init__(message, error_code="cancelled")
