"""Model Connections (Phase 4) — FreeBuff / BYOK provider integration layer.

Provider-neutral BYOK connections: named connections reference a provider, an
optional endpoint/deployment, and a credential stored **only** in the OpenCode
auth store (``credential_store``). Workflows carry just ``connection_id`` —
never a secret.

    workflow node
        ↓ connection_id
    connection registry (metadata)
        ↓
    credential store (secret)
        ↓
    resolver → runtime configuration (metadata + masked credential flag)
"""

from scripts.core.model_connections import (  # noqa: F401
    credential_store,
    providers,
    registry,
    resolver,
)
from scripts.core.model_connections.errors import (
    ConnectionError,
    CredentialError,
    DuplicateConnectionError,
    ResolutionError,
    UnknownConnectionError,
    UnknownProviderError,
)
from scripts.core.model_connections.registry import (
    connection_metadata,
    connections_path,
    create_connection,
    delete_connection,
    get_connection,
    list_connections,
    list_connections_by_provider,
    update_connection,
    validate_connection,
)
from scripts.core.model_connections.resolver import (
    Resolution,
    resolve,
    resolve_credential,
)
from scripts.core.model_connections.schema import (
    ModelConnection,
    validate_connection_id,
)

__all__ = [
    "ConnectionError",
    "CredentialError",
    "DuplicateConnectionError",
    "ModelConnection",
    "Resolution",
    "ResolutionError",
    "UnknownConnectionError",
    "UnknownProviderError",
    "connection_metadata",
    "connections_path",
    "create_connection",
    "delete_connection",
    "get_connection",
    "list_connections",
    "list_connections_by_provider",
    "resolve",
    "resolve_credential",
    "update_connection",
    "validate_connection",
    "validate_connection_id",
]
