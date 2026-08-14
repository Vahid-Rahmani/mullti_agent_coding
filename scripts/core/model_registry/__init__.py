"""Model Registry (Phase 3) — provider-neutral model catalog + selection.

    Prompt Library decides WHAT the agent needs.
    Model Registry describes WHAT each model can do.
    Model Selector decides WHICH available model best matches.

Provider integration (FreeBuff / BYOK, credentials, actual API calls) is a
later phase and is intentionally absent here.
"""

from scripts.core.model_registry.registry import (
    ModelError,
    get_model,
    list_models,
    list_models_by_capability,
    list_models_by_provider,
    model_providers,
)
from scripts.core.model_registry.schema import (
    PROVIDERS,
    STATUSES,
    ModelSpec,
    validate_spec,
)
from scripts.core.model_registry.selection import (
    ModelSelection,
    select_models,
)

__all__ = [
    "ModelSpec",
    "ModelError",
    "ModelSelection",
    "PROVIDERS",
    "STATUSES",
    "get_model",
    "list_models",
    "list_models_by_capability",
    "list_models_by_provider",
    "model_providers",
    "select_models",
    "validate_spec",
]
