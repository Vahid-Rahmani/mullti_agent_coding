"""Connection registry — named BYOK connections (Phase 4).

The registry persists **metadata only** (``connection_id``, provider, display
name, endpoint, deployment, status, timestamps). Secrets stay behind
:mod:`credential_store`; the registry never reads, writes, or returns them.

Metadata file: ``~/.local/share/multicoding/connections.json`` by default
(override with ``ZOVA_CONNECTIONS``, following the project's ZOVA_* test
convention). Atomic writes only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts.core.model_connections import credential_store
from scripts.core.model_connections.errors import (
    ConnectionError,
    CredentialError,
    DuplicateConnectionError,
    UnknownConnectionError,
    UnknownProviderError,
)
from scripts.core.model_connections.providers import (
    get_provider,
)
from scripts.core.model_connections.schema import (
    CONNECTION_STATUSES,
    ModelConnection,
    validate_connection_id,
)

_CONNECTIONS_ENV = "ZOVA_CONNECTIONS"


def connections_path() -> Path:
    env = os.environ.get(_CONNECTIONS_ENV)
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "multicoding" / "connections.json"


# ------------------------------------------------------------------ io


def _load() -> dict[str, dict]:
    path = connections_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _save(data: dict[str, dict]) -> None:
    path = connections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _stored() -> dict[str, ModelConnection]:
    out: dict[str, ModelConnection] = {}
    for cid, raw in _load().items():
        try:
            out[cid] = ModelConnection.from_dict(raw)
        except ConnectionError:
            continue  # corrupt entry: skip rather than fail the whole registry
    return out


# ------------------------------------------------------------------ status


def _status_for(connection: ModelConnection) -> str:
    """Derive status: tested/validation_failed override; otherwise whether the
    credential is present (configured) or absent (not_configured)."""
    if connection.status in ("tested", "validation_failed"):
        return connection.status
    if connection.credential_type == "api_key":
        return "configured" if credential_store.has_credential(
            connection.connection_id) else "not_configured"
    return "configured"  # credential_type "none" needs no secret


# ------------------------------------------------------------------ registry API


def list_connections() -> list[ModelConnection]:
    """All connections sorted by connection_id (deterministic)."""
    return sorted(_stored().values(), key=lambda c: c.connection_id)


def list_connections_by_provider(provider: str) -> list[ModelConnection]:
    return [c for c in list_connections() if c.provider == (provider or "")]


def get_connection(connection_id: str) -> ModelConnection:
    connection_id = validate_connection_id(connection_id)
    stored = _stored()
    connection = stored.get(connection_id)
    if connection is None:
        raise UnknownConnectionError(f"unknown connection {connection_id!r}")
    return connection.with_updates(status=_status_for(connection))


def connection_metadata(connection_id: str) -> dict:
    """Metadata dict for API responses — never contains a secret."""
    return get_connection(connection_id).to_dict()


def create_connection(
    provider: str,
    display_name: str = "",
    *,
    api_key: str | None = None,
    endpoint: str = "",
    deployment: str = "",
    default: bool = False,
    credential_type: str = "api_key",
    connection_id: str | None = None,
) -> ModelConnection:
    """Create a connection: validate, persist metadata, store the secret
    (if any) through credential_store. Returns metadata only."""
    meta = get_provider(provider)  # raises UnknownProviderError
    # When the caller did not explicitly choose a credential type, mirror the
    # provider's own type (e.g. ollama is "none" — no secret needed).
    if credential_type == "api_key" and meta.credential_type == "none":
        credential_type = "none"
    if credential_type == "api_key" and meta.requires_api_key and not api_key:
        raise CredentialError(
            f"provider {provider!r} requires an API key — supply one to create "
            "a working connection")

    if not connection_id:
        base = "conn_" + provider.replace("_", "-")
        existing = {c.connection_id for c in list_connections()}
        n = 1
        while f"{base}_{n}" in existing:
            n += 1
        connection_id = f"{base}_{n}"
    connection_id = validate_connection_id(connection_id)

    stored = _load()
    if connection_id in stored:
        raise DuplicateConnectionError(
            f"connection {connection_id!r} already exists")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = ModelConnection(
        connection_id=connection_id,
        provider=provider,
        display_name=display_name or meta.display_name,
        credential_type=credential_type,
        endpoint=(endpoint or "").strip(),
        deployment=(deployment or "").strip(),
        status="not_configured",
        default=bool(default),
        created_at=now,
        updated_at=now,
    )

    if credential_type == "api_key" and api_key:
        credential_store.store_credential(connection_id, api_key)

    if default:
        _clear_provider_default(provider)

    raw = dict(connection.to_dict())
    raw.pop("id", None)
    stored[connection_id] = raw
    _save(stored)
    return get_connection(connection_id)


def update_connection(
    connection_id: str,
    *,
    display_name: str | None = None,
    endpoint: str | None = None,
    deployment: str | None = None,
    api_key: str | None = None,
    default: bool | None = None,
    credential_type: str | None = None,
    status: str | None = None,
) -> ModelConnection:
    """Update metadata and/or replace the stored secret. Never returns a key."""
    connection_id = validate_connection_id(connection_id)
    stored = _load()
    if connection_id not in stored:
        raise UnknownConnectionError(f"unknown connection {connection_id!r}")

    changes: dict[str, object] = {}
    if display_name is not None:
        changes["display_name"] = display_name
    if endpoint is not None:
        changes["endpoint"] = endpoint
    if deployment is not None:
        changes["deployment"] = deployment
    if default is not None:
        changes["default"] = default
    if credential_type is not None:
        changes["credential_type"] = credential_type
    if status is not None:
        if status not in CONNECTION_STATUSES:
            raise ConnectionError(f"invalid connection status {status!r}")
        changes["status"] = status

    if api_key is not None:
        api_key = api_key.strip()
        if not api_key:
            raise CredentialError("cannot store an empty credential")
        credential_store.store_credential(connection_id, api_key)
        changes["status"] = "configured"

    if changes.get("default"):
        _clear_provider_default(stored[connection_id].get("provider", ""))

    connection = ModelConnection.from_dict(stored[connection_id]).with_updates(**changes)
    raw = dict(connection.to_dict())
    raw.pop("id", None)
    stored[connection_id] = raw
    _save(stored)
    return get_connection(connection_id)


def delete_connection(connection_id: str) -> bool:
    connection_id = validate_connection_id(connection_id)
    stored = _load()
    if connection_id not in stored:
        raise UnknownConnectionError(f"unknown connection {connection_id!r}")
    del stored[connection_id]
    _save(stored)
    credential_store.remove_credential(connection_id)
    return True


def _clear_provider_default(provider: str) -> None:
    """Ensure only one connection per provider is marked default."""
    stored = _load()
    changed = False
    for raw in stored.values():
        if raw.get("provider") == provider and raw.get("default"):
            raw["default"] = False
            changed = True
    if changed:
        _save(stored)


# ------------------------------------------------------------------ validation


def validate_connection(connection_id: str) -> dict:
    """Configuration-based validation (no network call).

    Checks, in order: the connection exists; its provider is known; required
    fields (endpoint for custom providers, deployment for azure_openai) are
    present; and the credential exists when the provider requires one.
    Returns ``{ok, detail, connection}`` — never a secret.
    """
    connection = get_connection(connection_id)  # raises UnknownConnectionError
    if connection.status == "validation_failed":
        return {"ok": False, "detail": "previous validation failed — re-test the connection",
                "connection": connection.to_dict()}
    try:
        meta = get_provider(connection.provider)
    except UnknownProviderError as exc:
        return {"ok": False, "detail": str(exc), "connection": connection.to_dict()}

    if (connection.credential_type == "api_key" and meta.requires_api_key
            and not credential_store.has_credential(connection_id)):
        return {"ok": False,
                "detail": f"no API key stored for {connection_id!r} — add one",
                "connection": connection.to_dict()}

    if meta.supports_base_url and meta.provider != "openai" and not connection.endpoint:
        return {"ok": False,
                "detail": f"provider {connection.provider!r} needs an endpoint (base URL)",
                "connection": connection.to_dict()}
    if meta.supports_deployment and not connection.deployment:
        return {"ok": False,
                "detail": f"provider {connection.provider!r} needs a deployment name",
                "connection": connection.to_dict()}

    update_connection(connection_id, status="tested")
    return {"ok": True, "detail": "connection configured correctly",
            "connection": get_connection(connection_id).to_dict()}


__all__ = [
    "connection_metadata",
    "connections_path",
    "create_connection",
    "delete_connection",
    "get_connection",
    "list_connections",
    "list_connections_by_provider",
    "update_connection",
    "validate_connection",
]
