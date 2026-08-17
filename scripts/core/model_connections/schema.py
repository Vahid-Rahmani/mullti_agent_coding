"""ModelConnection — provider-neutral connection metadata (Phase 4).

A ``ModelConnection`` is **metadata only**. It never carries a secret: the raw
API key lives behind ``credential_store`` (the OpenCode auth store), keyed by
``connection_id``. ``to_dict()`` therefore can never leak a credential.

The workflow only ever references a connection by id::

    {"model": "openai/gpt-5", "connection_id": "conn_openai_primary"}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from scripts.core.model_connections.errors import (
    ConnectionError,
)

# status values mirror ui_settings.CONNECTION_STATUS.
CONNECTION_STATUSES: tuple[str, ...] = (
    "not_configured", "configured", "tested", "validation_failed",
)

# credential_type values.
CREDENTIAL_TYPES: tuple[str, ...] = ("api_key", "none")

# connection_id shape: letters/digits/underscore/hyphen, starting conn_ is
# conventional but not required.
_CONNECTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def validate_connection_id(connection_id: str) -> str:
    connection_id = (connection_id or "").strip()
    if not _CONNECTION_ID_RE.match(connection_id):
        raise ConnectionError(
            f"invalid connection id {connection_id!r} "
            "(expected 1-96 chars of letters, digits, '-' or '_')")
    return connection_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ModelConnection:
    """Immutable connection metadata. Never holds a secret."""

    connection_id: str
    provider: str
    display_name: str = ""
    credential_type: str = "api_key"   # api_key | none
    endpoint: str = ""                 # optional base URL (custom providers)
    deployment: str = ""               # optional deployment name (azure_openai)
    status: str = "not_configured"     # see CONNECTION_STATUSES
    default: bool = False              # provider default (used by the resolver)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> ModelConnection:
        now = _now_iso()
        created = str(data.get("created_at") or now)
        return cls(
            connection_id=validate_connection_id(
                str(data.get("connection_id") or data.get("id") or "")),
            provider=str(data.get("provider") or ""),
            display_name=str(data.get("display_name") or ""),
            credential_type=str(data.get("credential_type") or "api_key"),
            endpoint=str(data.get("endpoint") or ""),
            deployment=str(data.get("deployment") or ""),
            status=str(data.get("status") or "not_configured"),
            default=bool(data.get("default", False)),
            created_at=created,
            updated_at=str(data.get("updated_at") or created),
        )

    def to_dict(self) -> dict:
        """Serializable metadata — by construction never contains a secret."""
        return {
            "id": self.connection_id,
            "connection_id": self.connection_id,
            "provider": self.provider,
            "display_name": self.display_name,
            "credential_type": self.credential_type,
            "endpoint": self.endpoint,
            "deployment": self.deployment,
            "status": self.status,
            "default": self.default,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def with_updates(self, **changes: object) -> ModelConnection:
        """Return a copy with metadata changes applied (no secret fields)."""
        allowed = {"display_name", "endpoint", "deployment", "status",
                   "default", "updated_at", "credential_type"}
        unknown = set(changes) - allowed
        if unknown:
            raise ConnectionError(f"unsupported connection field(s): {sorted(unknown)}")
        credential_type = str(changes.get("credential_type", self.credential_type))
        if credential_type not in CREDENTIAL_TYPES:
            raise ConnectionError(f"invalid credential_type {credential_type!r}")
        return ModelConnection(
            connection_id=self.connection_id,
            provider=self.provider,
            display_name=str(changes.get("display_name", self.display_name)),
            credential_type=credential_type,
            endpoint=str(changes.get("endpoint", self.endpoint)),
            deployment=str(changes.get("deployment", self.deployment)),
            status=str(changes.get("status", self.status)),
            default=bool(changes.get("default", self.default)),
            created_at=self.created_at,
            updated_at=str(changes.get("updated_at", _now_iso())),
        )


__all__ = [
    "CONNECTION_STATUSES",
    "CREDENTIAL_TYPES",
    "ModelConnection",
    "validate_connection_id",
]
