"""Provider adapter protocol, resolved connection, and adapter registry (Phase 5).

The adapter seam is the execution boundary:

    WorkflowNode → connection_id only
    Planner      → ResolvedConnection (metadata only)
    Adapter      → consumes the secret internally, immediately before the call

:class:`ResolvedConnection` is the controlled object handed to adapters. It
may carry an internal credential value (``_credential``) — set **only** at the
adapter execution boundary via :func:`resolve_credential_for` — but that value
is excluded from ``to_public_dict()``/``to_dict()`` and is never serialized,
logged, compared, or echoed.

Only one adapter ships today: :class:`OpenCodeAdapter` (the default runtime).
Future direct-provider adapters register themselves via
:func:`register_adapter` and are selected per resolved provider; until then
any unknown provider resolves to OpenCode, preserving current behavior.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Protocol

from scripts.core.execution.schema import ModelRequest, ModelResponse


@dataclass(frozen=True)
class ResolvedConnection:
    """Safe runtime configuration handed to a provider adapter.

    ``_credential`` is the internal secret slot — never serialized, never in
    logs/exceptions/events/snapshots. It is populated only inside the adapter
    execution boundary (:func:`resolve_credential_for`).
    """

    connection_id: str = ""
    provider: str = ""
    endpoint: str | None = None
    deployment: str | None = None
    local: bool = True
    source: str = "local"
    _credential: str | None = field(default=None, repr=False, compare=False)

    def with_credential(self, secret: str | None) -> ResolvedConnection:
        """Return a copy carrying the secret — execution boundary only."""
        return replace(self, _credential=secret)

    def has_credential(self) -> bool:
        return bool(self._credential)

    def to_dict(self) -> dict:
        """Public metadata — deliberately excludes any credential."""
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "local": self.local,
            "source": self.source,
        }

    def to_public_dict(self) -> dict:
        return self.to_dict()


class ProviderAdapter(Protocol):
    """Contract every execution adapter must satisfy.

    ``execute`` receives the provider-neutral request plus the resolved
    connection; it returns a :class:`ModelResponse` or raises an
    ``AdapterError`` subclass (typed timeout/cancelled/failure). ``timeout``
    and ``cancel_event`` let the executor bound each node execution; adapters
    must terminate their work (killing any child process) and must never leave
    orphans.
    """

    provider_id: str

    def execute(
        self,
        request: ModelRequest,
        connection: ResolvedConnection,
        *,
        timeout: float | None = None,
        cancel_event: threading.Event | None = None,
        execution_id: str = "",
    ) -> ModelResponse:
        ...


# ---------------------------------------------------------------- registry


def adapter_for(resolution) -> ProviderAdapter:
    """Map a resolved connection (or ``None``) to a provider adapter.

    Default: :class:`OpenCodeAdapter` — unknown providers and the local
    runtime keep executing through opencode exactly as before. Direct adapters
    will be registered per provider in a later phase.
    """
    from scripts.core.providers.opencode import OpenCodeAdapter

    provider = getattr(resolution, "provider", None) if resolution is not None else None
    cls = _ADAPTERS.get(provider) or OpenCodeAdapter
    return cls()


def register_adapter(provider_id: str, adapter_cls: type) -> None:
    """Register an adapter for a provider id (future direct adapters)."""
    _ADAPTERS[provider_id] = adapter_cls


def resolve_credential_for(connection: ResolvedConnection) -> str | None:
    """INTERNAL execution-boundary helper: fetch the secret for a connection.

    Only adapters call this, immediately before making the provider call. The
    value must never be logged, echoed, serialized, or returned outside the
    adapter boundary. OpenCode does not need it (opencode reads its own auth
    store) — this exists for future direct-provider adapters.
    """
    if not connection.connection_id:
        return None
    from scripts.core import model_connections

    return model_connections.resolve_credential(connection.connection_id)


_ADAPTERS: dict[str, type] = {}


def _prime_default_adapter() -> None:
    """Register the built-in OpenCode adapter (import-time side effect)."""
    from scripts.core.providers.opencode import OpenCodeAdapter

    if "opencode" not in _ADAPTERS:
        _ADAPTERS["opencode"] = OpenCodeAdapter


_prime_default_adapter()
