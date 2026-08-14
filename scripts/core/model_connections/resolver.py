"""Connection resolver — deterministic node → runtime configuration.

Resolution order (never guesses, never switches providers silently)::

    explicit connection (node.connection_id)
        ↓
    explicit model's provider → its connection
        ↓
    provider default connection
        ↓
    local / default runtime (no credential needed)
        ↓
    clear, secret-free error

The result is metadata + a masked credential flag — the raw secret is never
returned here. Backend execution can call :func:`resolve_credential`
separately (internal only).
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.core.model_connections import credential_store
from scripts.core.model_connections.errors import (
    ResolutionError,
    UnknownConnectionError,
)
from scripts.core.model_connections.providers import (
    is_local_provider,
    provider_for_model,
    requires_api_key,
)
from scripts.core.model_connections.registry import (
    get_connection,
    list_connections_by_provider,
)
from scripts.core.model_connections.schema import ModelConnection


@dataclass(frozen=True)
class Resolution:
    """Resolved runtime configuration for a node (never contains a secret)."""

    connection_id: str | None
    provider: str | None
    display_name: str
    endpoint: str | None
    deployment: str | None
    credential_configured: bool
    needs_credential: bool
    local: bool
    source: str            # explicit | model-provider | provider-default | local | none

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "credential_configured": self.credential_configured,
            "needs_credential": self.needs_credential,
            "local": self.local,
            "source": self.source,
        }


def _from_connection(connection: ModelConnection, source: str) -> Resolution:
    needs = connection.credential_type == "api_key"
    return Resolution(
        connection_id=connection.connection_id,
        provider=connection.provider,
        display_name=connection.display_name or connection.connection_id,
        endpoint=connection.endpoint or None,
        deployment=connection.deployment or None,
        credential_configured=credential_store.has_credential(connection.connection_id),
        needs_credential=needs,
        local=is_local_provider(connection.provider),
        source=source,
    )


def _local_resolution(source: str = "local") -> Resolution:
    return Resolution(
        connection_id=None, provider=None, display_name="Local / runtime default",
        endpoint=None, deployment=None, credential_configured=False,
        needs_credential=False, local=True, source=source)


def _default_connection_for(provider: str) -> ModelConnection | None:
    """The default (or sole) connection for a provider; None when ambiguous."""
    matches = list_connections_by_provider(provider)
    if not matches:
        return None
    defaults = [c for c in matches if c.default]
    if len(defaults) == 1:
        return defaults[0]
    if len(defaults) > 1:
        return None  # ambiguous — require an explicit choice
    if len(matches) == 1:
        return matches[0]
    return None  # multiple non-default connections — require an explicit choice


def resolve(node: ModelConnection | dict | None = None,
            *,
            model: str | None = None,
            connection_id: str | None = None) -> Resolution:
    """Resolve a workflow node (or explicit model/connection) to a runtime
    configuration. Raises :class:`ResolutionError` with a secret-free message
    when a required connection or credential is missing.

    ``node`` may be a ``ModelConnection`` (already chosen), a dict carrying
    ``model``/``connection_id``, or None — in which case ``model`` and
    ``connection_id`` keyword args are used.
    """
    if isinstance(node, ModelConnection):
        return _from_connection(node, "explicit")
    if isinstance(node, dict):
        connection_id = connection_id or str(node.get("connection_id") or "")
        model = model if model is not None else str(node.get("model") or "")

    connection_id = (connection_id or "").strip()
    model = (model or "").strip()

    # 1. explicit connection wins.
    if connection_id:
        try:
            return _from_connection(get_connection(connection_id), "explicit")
        except UnknownConnectionError as exc:
            raise ResolutionError(str(exc)) from exc

    # 2/3. model → provider → provider default connection.
    provider = provider_for_model(model) if model else None
    if provider:
        if is_local_provider(provider):
            return _local_resolution("local")
        connection = _default_connection_for(provider)
        if connection is not None:
            return _from_connection(connection, "provider-default")
        if requires_api_key(provider):
            matches = list_connections_by_provider(provider)
            if matches:
                raise ResolutionError(
                    f"model {model!r} needs a {provider} connection, but multiple "
                    "exist — select one explicitly on the node")
            raise ResolutionError(
                f"model {model!r} needs a {provider} connection — create one "
                "first (Manage Connections)")

    # 4. local / default runtime (no model, or a model with no credential
    #    requirement that has no connection — e.g. unconfigured local).
    return _local_resolution("none" if not model else "local")


def resolve_credential(connection_id: str) -> str | None:
    """INTERNAL: the stored secret for backend execution.

    Never call from an API/UI path; never log, echo, or serialize the result.
    """
    if not connection_id:
        return None
    try:
        get_connection(connection_id)  # existence check
    except UnknownConnectionError:
        return None
    return credential_store._resolve_credential(connection_id)


__all__ = ["Resolution", "resolve", "resolve_credential"]
