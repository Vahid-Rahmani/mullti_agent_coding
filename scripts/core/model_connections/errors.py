"""Connection-layer errors (Phase 4 / FreeBuff · BYOK).

Every error message here is intentionally secret-free: it may name a
connection id, provider, or model, but never a credential value, endpoint
query string, or authorization header.
"""

from __future__ import annotations


class ConnectionError(RuntimeError):
    """Base class for all model-connection failures (safe to surface)."""


class UnknownProviderError(ConnectionError):
    """Provider id is not in the provider metadata table."""


class UnknownConnectionError(ConnectionError):
    """No connection with this connection_id exists."""


class DuplicateConnectionError(ConnectionError):
    """A connection with this connection_id already exists."""


class CredentialError(ConnectionError):
    """A required credential is missing or unusable (never includes the secret)."""


class ResolutionError(ConnectionError):
    """A workflow node's model/connection could not be resolved to a usable
    runtime configuration. The message explains *what* is missing (provider,
    connection, credential) without exposing any secret."""


__all__ = [
    "ConnectionError",
    "CredentialError",
    "DuplicateConnectionError",
    "ResolutionError",
    "UnknownConnectionError",
    "UnknownProviderError",
]
