"""Model capability matrix — which modes each model may run.

Data-only module: the per-agent operational mode groups, the model -> modes
capability matrix, and the inverse ``MODELS_BY_AGENT`` live here (not in the
registry) so model capabilities can be edited in one place without touching
roster-derivation logic. The registry imports and re-exports these constants
unchanged, keeping the legacy import surface intact.

``MODE_OPTIONS_BY_MODEL`` maps each model selector to the operational modes it
may run (the options shown in the UI model pickers). ``MODELS_BY_AGENT`` is the
inverse — every model that offers at least one of an agent's modes — used by
the launcher CLI (``scripts/core/agents/__main__.py``) and by tests to prove
each agent can run on its configured model.
"""

from __future__ import annotations

from .alex import SPEC as ALEX
from .chloe import COMPACT_MODES, M7_AUDIT_MODE, SPEC as CHLOE
from .constants import AUTO_MODE, AUTO_MODEL
from .david import SPEC as DAVID
from .elena import SPEC as ELENA
from .matthew import SPEC as MATTHEW
from .max import SPEC as MAX
from .sarah import SPEC as SARAH

# Per-agent operational mode groups (kept as public tuples for callers that
# referenced the old ``_*_MODES`` lists).
ARCHITECT_MODES: tuple[str, ...] = MATTHEW.modes
BACKEND_MODES: tuple[str, ...] = ALEX.modes
FRONTEND_MODES: tuple[str, ...] = SARAH.modes
QA_MODES: tuple[str, ...] = DAVID.modes
SECURITY_MODES: tuple[str, ...] = ELENA.modes
DEVOPS_MODES: tuple[str, ...] = MAX.modes
DOCS_MODES: tuple[str, ...] = CHLOE.modes

ALL_OPERATIONAL_MODES: list[str] = [
    *ARCHITECT_MODES, *BACKEND_MODES, *FRONTEND_MODES, *QA_MODES,
    *SECURITY_MODES, *DEVOPS_MODES, *DOCS_MODES,
]

# Which modes each model may run (model capability matrix).
MODE_OPTIONS_BY_MODEL: dict[str, list[str]] = {
    AUTO_MODEL: [AUTO_MODE, *ALL_OPERATIONAL_MODES],
    "opencode/deepseek-v4-flash-free": [
        *ARCHITECT_MODES, *BACKEND_MODES, *FRONTEND_MODES,
        *QA_MODES, *SECURITY_MODES, *DEVOPS_MODES,
    ],
    "opencode/big-pickle": [
        *QA_MODES, *ARCHITECT_MODES, *BACKEND_MODES, *FRONTEND_MODES,
        *DEVOPS_MODES, *SECURITY_MODES, *DOCS_MODES,
    ],
    "opencode/ling-3.0-tiny-free": [
        M7_AUDIT_MODE, *SECURITY_MODES, *DOCS_MODES, *COMPACT_MODES,
    ],
    "ollama/qwen2.5-coder:7b": [*ALL_OPERATIONAL_MODES],
    "mulerouter/gpt-5.5": [*ALL_OPERATIONAL_MODES],
    "mulerouter/gpt-5.4-mini": [*ALL_OPERATIONAL_MODES, *COMPACT_MODES],
    "mulerouter/qwen3-max": [*ALL_OPERATIONAL_MODES],
    "mulerouter/qwen3.7-max": [*ALL_OPERATIONAL_MODES],
}

# Inverse capability map: agent key -> models offering at least one of its
# modes (operational or routing-only, e.g. Chloe's audit/compact modes).
_SPECS = (MATTHEW, ALEX, SARAH, DAVID, ELENA, MAX, CHLOE)
MODELS_BY_AGENT: dict[str, tuple[str, ...]] = {}
for _spec in _SPECS:
    MODELS_BY_AGENT[_spec.agent] = tuple(
        model
        for model, modes in MODE_OPTIONS_BY_MODEL.items()
        if any(mode in modes for mode in _spec.all_modes)
    )
