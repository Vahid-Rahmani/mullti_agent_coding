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

from scripts.core.model_connections import credential_store, providers, registry, resolver  # noqa: F401
from scripts.core.model_connections.errors import (  # noqa: F401
    ConnectionError,
    CredentialError,
    DuplicateConnectionError,
    ResolutionError,
    UnknownConnectionError,
    UnknownProviderError,
)
from scripts.core.model_connections.registry import (  # noqa: F401
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
from scripts.core.model_connections.resolver import (  # noqa: F401
    Resolution,
    resolve,
    resolve_credential,
)
from scripts.core.model_connections.schema import (  # noqa: F401
    ModelConnection,
    validate_connection_id,
)

__all__ = [
    "ModelConnection",
    "Resolution",
    "ConnectionError",
    "CredentialError",
    "DuplicateConnectionError",
    "ResolutionError",
    "UnknownConnectionError",
    "UnknownProviderError",
    "connections_path",
    "list_connections",
    "list_connections_by_provider",
    "get_connection",
    "connection_metadata",
    "create_connection",
    "update_connection",
    "delete_connection",
    "validate_connection",
    "resolve",
    "resolve_credential",
    "validate_connection_id",
]
