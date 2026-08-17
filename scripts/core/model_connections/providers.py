"""Provider metadata table (Phase 4) — configuration only, no SDKs.

Providers are described by what they need and what they support so the UI and
resolver can behave correctly *before* any provider integration exists. No
vendor SDK is imported anywhere in this package; ``provider`` is metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.core.model_connections.errors import UnknownProviderError


@dataclass(frozen=True)
class ProviderMeta:
    provider: str
    display_name: str
    auth_type: str                # api_key | bearer | x-api-key | none
    requires_api_key: bool
    supports_base_url: bool
    supports_deployment: bool
    supports_model_discovery: bool
    credential_type: str = "api_key"


PROVIDERS: tuple[ProviderMeta, ...] = (
    ProviderMeta("openai", "OpenAI", "bearer", True, True, False, True),
    ProviderMeta("anthropic", "Anthropic", "x-api-key", True, False, False, True),
    ProviderMeta("google", "Gemini", "api_key", True, False, False, True),
    ProviderMeta("azure_openai", "Azure OpenAI", "api_key", True, True, True, True),
    ProviderMeta("openrouter", "OpenRouter", "bearer", True, True, False, True),
    ProviderMeta("ollama", "Ollama (local)", "none", False, True, False, True,
                 credential_type="none"),
    ProviderMeta("custom_openai_compatible", "Custom OpenAI-compatible",
                 "bearer", False, True, False, True),
)

_PROVIDER_BY_ID = {p.provider: p for p in PROVIDERS}

# Providers whose models run locally and never need an external credential.
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "local"})


def get_provider(provider: str) -> ProviderMeta:
    meta = _PROVIDER_BY_ID.get(provider or "")
    if meta is None:
        raise UnknownProviderError(
            f"unknown provider {provider!r}; known providers: "
            + ", ".join(sorted(_PROVIDER_BY_ID)))
    return meta


def provider_known(provider: str) -> bool:
    return (provider or "") in _PROVIDER_BY_ID


def provider_meta() -> list[dict]:
    """Metadata for the UI — no secrets, no SDKs."""
    return [{
        "provider": p.provider,
        "display_name": p.display_name,
        "auth_type": p.auth_type,
        "requires_api_key": p.requires_api_key,
        "supports_base_url": p.supports_base_url,
        "supports_deployment": p.supports_deployment,
        "supports_model_discovery": p.supports_model_discovery,
        "credential_type": p.credential_type,
    } for p in PROVIDERS]


def provider_for_model(model_id: str) -> str | None:
    """Derive the provider from a model id (``provider/bare`` prefix).

    ``local/...`` and ``ollama/...`` are treated as local providers. Returns
    None for ids without a provider prefix (e.g. bare "Auto" is not a model).
    """
    model_id = (model_id or "").strip()
    if "/" in model_id:
        prefix = model_id.split("/", 1)[0]
        if prefix in LOCAL_PROVIDERS or prefix in _PROVIDER_BY_ID:
            return prefix
    return None


def is_local_provider(provider: str | None) -> bool:
    return (provider or "") in LOCAL_PROVIDERS


def requires_api_key(provider: str) -> bool:
    try:
        return get_provider(provider).requires_api_key
    except UnknownProviderError:
        return False


__all__ = [
    "LOCAL_PROVIDERS",
    "PROVIDERS",
    "ProviderMeta",
    "get_provider",
    "is_local_provider",
    "provider_for_model",
    "provider_known",
    "provider_meta",
    "requires_api_key",
]
