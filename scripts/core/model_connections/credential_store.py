"""Credential store — the ONLY secret backend (Phase 4).

Secrets live in the **same OpenCode auth store** the Settings/BYOK layer
already uses (``~/.local/share/opencode/auth.json``), keyed by
``connection_id`` so the project keeps a single secret store instead of a
second one. This module is a thin, strictly-bounded wrapper:

* ``has_credential``  — masked status only (``configured: true|false``).
* ``store_credential`` — write a secret (atomic tmp+replace write).
* ``remove_credential`` — delete a secret.
* ``_resolve_credential`` — INTERNAL backend helper (validation/dispatch
  only). It must never be called from an API/UI path and never be logged,
  echoed, or returned to a caller outside the execution layer.

Security rules enforced here (and tested):
* no secret value is ever returned by the public surface
* no secret value is ever written to workflow JSON (workflows never touch
  this module)
* errors/logs go through :func:`redact` so secrets cannot leak into messages
* the store file format matches the OpenCode auth store, so the existing
  ``opencode auth`` tooling remains compatible

Known limitation (documented): the auth store is a plain JSON file protected
by OS user permissions. It is not encrypted at rest. A stronger backend
(OS keychain) can replace ``_store_path``/``_read``/``_write`` behind this
same interface later.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from scripts.core.model_connections.errors import CredentialError

# Auth-store override for tests / alternate installs; mirrors the project's
# ZOVA_* env-var convention. When unset, the OpenCode default is used so the
# existing Settings/BYOK layer and this store stay one and the same file.
_AUTH_STORE_ENV = "ZOVA_AUTH_STORE"

_URL_QUERY_RE = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")


def auth_store_path() -> Path:
    env = os.environ.get(_AUTH_STORE_ENV)
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _read_store(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _write_store(path: Path, data: dict) -> None:
    """Atomic write (tmp + os.replace) so a crash never truncates the store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def has_credential(connection_id: str) -> bool:
    """Masked status: does this connection have a stored secret? (never the value)"""
    data = _read_store(auth_store_path())
    entry = data.get(connection_id or "")
    return bool(isinstance(entry, dict) and entry.get("type") == "api"
                and entry.get("key"))


def store_credential(connection_id: str, secret: str) -> bool:
    """Persist a secret for a connection. Returns True when stored.

    The secret is written in the OpenCode auth-store format so existing
    tooling remains compatible. Never returns or logs the value.
    """
    connection_id = (connection_id or "").strip()
    secret = (secret or "").strip()
    if not connection_id:
        raise CredentialError("cannot store a credential without a connection id")
    if not secret:
        raise CredentialError("cannot store an empty credential")
    path = auth_store_path()
    data = _read_store(path)
    data[connection_id] = {"type": "api", "key": secret}
    _write_store(path, data)
    return has_credential(connection_id)


def remove_credential(connection_id: str) -> bool:
    path = auth_store_path()
    data = _read_store(path)
    if connection_id not in data:
        return False
    del data[connection_id]
    _write_store(path, data)
    return True


def _resolve_credential(connection_id: str) -> str | None:
    """INTERNAL: read the secret for backend execution/validation.

    Never call from an API/UI path; never log, echo, or serialize the result.
    """
    data = _read_store(auth_store_path())
    entry = data.get(connection_id or "")
    if isinstance(entry, dict) and entry.get("type") == "api":
        return entry.get("key") or None
    return None


def redact(text: str, *secrets: str | None) -> str:
    """Remove secret material from a message before it leaves the backend.

    Replaces known secret values, then drops the query string of any URL
    (query strings commonly carry API keys). Safe to apply to exceptions.
    """
    text = str(text or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "***")
    return _URL_QUERY_RE.sub(r"\1", text)


def safe_error(exc: BaseException, *secrets: str | None) -> str:
    """A redacted, human-safe error string (never contains secret values)."""
    return redact(str(exc), *secrets)


__all__ = [
    "CredentialError",
    "_resolve_credential",
    "auth_store_path",
    "has_credential",
    "redact",
    "remove_credential",
    "safe_error",
    "store_credential",
]
