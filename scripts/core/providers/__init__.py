"""Provider adapters — the execution seam (Phase 5).

Only the OpenCode adapter ships today (the default runtime). Direct-provider
adapters are a later phase; the registry seam (:func:`adapter_for`) already
supports them without touching the workflow engine.
"""

from __future__ import annotations

from scripts.core.providers.base import (
    ProviderAdapter,
    ResolvedConnection,
    adapter_for,
    register_adapter,
    resolve_credential_for,
)
from scripts.core.providers.opencode import (
    OpenCodeAdapter,
    build_run_command,
    insecure_tls_env,
    opencode_command,
    sanitize_prompt,
    strip_ansi,
)

__all__ = [
    "ProviderAdapter",
    "ResolvedConnection",
    "adapter_for",
    "register_adapter",
    "resolve_credential_for",
    "OpenCodeAdapter",
    "build_run_command",
    "insecure_tls_env",
    "opencode_command",
    "sanitize_prompt",
    "strip_ansi",
]
