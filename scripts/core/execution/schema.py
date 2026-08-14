"""Execution schemas — provider-neutral request/response + per-node records (Phase 5).

These dataclasses are the boundary between the workflow engine and provider
adapters. They are deliberately **free of credential fields**: nothing in this
module can serialize a secret, and the security tests assert that a secret
string never appears in ``to_dict()`` output, events, or run snapshots.

The provider that consumes a :class:`ModelRequest` is chosen by the planner;
the request itself carries only what every provider needs: a model id, the
final prompt, optional sampling knobs, and opaque metadata (workflow id, node
id, execution id, and — for the OpenCode adapter — the OpenCode agent key).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Ordered execution event types (observability model).
EVENT_TYPES: tuple[str, ...] = (
    "workflow_started",
    "node_started",
    "node_completed",
    "node_failed",
    "workflow_completed",
    "workflow_failed",
)

# ExecutionResult statuses (kept aligned with the workflow engine's node
# statuses so existing snapshot consumers keep working).
RESULT_STATUSES: tuple[str, ...] = ("completed", "failed")

# Stable error codes surfaced in ExecutionResult.error_code / events.
ERROR_CODES: tuple[str, ...] = (
    "",
    "timeout",
    "cancelled",
    "nonzero_exit",
    "opencode_missing",
    "empty_prompt",
    "plan_error",
    "adapter_error",
    "execution_error",
)

# Metadata keys a request may carry (adapter-specific values live here).
METADATA_KEYS: tuple[str, ...] = (
    "workflow_id",
    "node_id",
    "execution_id",
    "agent",       # OpenCode agent key (opencode adapter)
)


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (event/record timestamps)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValueError(message)


@dataclass(frozen=True)
class ModelRequest:
    """A provider-neutral model call. Never carries credentials."""

    model: str
    prompt: str
    stream: bool = False
    metadata: dict = field(default_factory=dict)
    temperature: float | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        _require(bool((self.model or "").strip()), "ModelRequest.model is required")
        _require(isinstance(self.prompt, str), "ModelRequest.prompt must be a string")
        _require(bool((self.prompt or "").strip()), "ModelRequest.prompt is required")
        if self.temperature is not None:
            _require(0.0 <= self.temperature <= 2.0,
                     "temperature must be within [0, 2]")
        if self.max_tokens is not None:
            _require(self.max_tokens > 0, "max_tokens must be positive")

    @property
    def workflow_id(self) -> str:
        return str(self.metadata.get("workflow_id") or "")

    @property
    def node_id(self) -> str:
        return str(self.metadata.get("node_id") or "")

    @property
    def execution_id(self) -> str:
        return str(self.metadata.get("execution_id") or "")

    @property
    def agent(self) -> str:
        return str(self.metadata.get("agent") or "")

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt": self.prompt,
            "stream": self.stream,
            "metadata": dict(self.metadata),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


@dataclass(frozen=True)
class ModelResponse:
    """A provider-neutral model result. Usage is best-effort."""

    text: str = ""
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)      # e.g. {prompt_tokens, completion_tokens}
    model: str = ""
    provider: str = ""
    raw_metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(isinstance(self.text, str), "ModelResponse.text must be a string")

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "finish_reason": self.finish_reason,
            "usage": dict(self.usage),
            "model": self.model,
            "provider": self.provider,
            "raw_metadata": dict(self.raw_metadata),
        }


@dataclass(frozen=True)
class ExecutionResult:
    """The complete record of one node execution (per attempt)."""

    execution_id: str
    node_execution_id: str
    status: str                       # completed | failed
    started_at: str
    finished_at: str
    latency_ms: float
    response: str = ""
    error: str = ""
    usage: dict = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    error_code: str = ""              # timeout | cancelled | nonzero_exit | ...

    def __post_init__(self) -> None:
        _require(self.status in RESULT_STATUSES,
                 f"invalid ExecutionResult.status {self.status!r}")

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "node_execution_id": self.node_execution_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "latency_ms": self.latency_ms,
            "response": self.response,
            "error": self.error,
            "usage": dict(self.usage),
            "model": self.model,
            "provider": self.provider,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class ExecutionEvent:
    """One ordered execution event. Never contains secrets."""

    execution_id: str
    workflow_id: str
    timestamp: str
    event_type: str                   # one of EVENT_TYPES
    node_id: str = ""
    status: str = ""
    model: str = ""
    provider: str = ""
    latency_ms: float | None = None
    usage: dict = field(default_factory=dict)
    error_code: str = ""

    def __post_init__(self) -> None:
        _require(self.event_type in EVENT_TYPES,
                 f"invalid ExecutionEvent.event_type {self.event_type!r}")

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "status": self.status,
            "model": self.model,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "usage": dict(self.usage),
            "error_code": self.error_code,
        }


def iso_now() -> str:
    """Alias for :func:`utc_now_iso` (convenience for execution timestamps)."""
    return utc_now_iso()


def monotonic_ms() -> float:
    """Monotonic clock in milliseconds (latency measurements)."""
    return time.monotonic() * 1000.0
