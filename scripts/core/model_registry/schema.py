"""ModelSpec — provider-neutral model registry schema (Phase 3).

The Model Registry describes *what each model can do* without any provider
SDK, API key or network call. ``ModelSpec`` reuses the Phase 2
``ModelCapabilityProfile`` for capability data (no duplicated fields) and adds
only registry metadata: provider, family, modalities, status.

Deliberately NOT here (later phases): credentials, endpoints, deployments,
provider client classes. The future boundary is::

    Model Registry → Provider Adapter → FreeBuff / BYOK → Credentials → API call
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.core.prompt_library.model_capabilities import (
    ModelCapabilityProfile,
)

# Provider identifiers are metadata only — no SDK is imported or required.
PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "google",
    "azure_openai",
    "local",
    "opencode",
)

# Model lifecycle statuses.
STATUSES: tuple[str, ...] = ("available", "preview", "deprecated")


@dataclass(frozen=True)
class ModelSpec:
    """One catalog entry. Capabilities reuse ``ModelCapabilityProfile``."""

    id: str                       # stable id, e.g. "google/gemini-3.6-flash"
    display_name: str = ""
    provider: str = ""            # one of PROVIDERS (metadata only)
    family: str = ""              # e.g. "gemini", "claude", "deepseek"
    capabilities: ModelCapabilityProfile = field(
        default_factory=ModelCapabilityProfile)
    modalities: tuple[str, ...] = ()   # e.g. ("text", "image")
    status: str = "available"     # available | preview | deprecated

    @classmethod
    def from_dict(cls, data: dict) -> ModelSpec:
        caps_data = data.get("capabilities")
        if not isinstance(caps_data, dict):
            # flat capability keys may live at the top level
            caps_data = {
                k: data.get(k)
                for k in ("reasoning", "coding", "context_window", "tool_use",
                          "vision", "latency", "cost", "structured_output")
                if data.get(k) is not None
            }
        caps = (ModelCapabilityProfile.from_dict(caps_data)
                if caps_data else ModelCapabilityProfile())
        return cls(
            id=str(data.get("id") or data.get("model_id") or ""),
            display_name=str(data.get("display_name") or data.get("name") or ""),
            provider=str(data.get("provider") or ""),
            family=str(data.get("family") or ""),
            capabilities=caps,
            modalities=tuple(str(m) for m in (data.get("modalities") or ())),
            status=str(data.get("status") or "available"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "provider": self.provider,
            "family": self.family,
            "capabilities": self.capabilities.to_dict(),
            "context_window": self.capabilities.context_window,
            "modalities": list(self.modalities),
            "status": self.status,
        }


def validate_spec(spec: ModelSpec) -> None:
    """Raise ValueError for a structurally invalid ModelSpec."""
    if not spec.id or "/" not in spec.id:
        raise ValueError(f"model id {spec.id!r} must be provider/model shaped")
    if spec.provider and spec.provider not in PROVIDERS:
        raise ValueError(
            f"model {spec.id!r}: unknown provider {spec.provider!r}; "
            f"allowed: {', '.join(PROVIDERS)}")
    if spec.status not in STATUSES:
        raise ValueError(
            f"model {spec.id!r}: unknown status {spec.status!r}; "
            f"allowed: {', '.join(STATUSES)}")


__all__ = ["PROVIDERS", "STATUSES", "ModelSpec", "validate_spec"]
