"""M7 — Chloe: Architectural Obsidian Archivist (fully configurable).

Chloe's audit/archivist roles dispatch to the ``chloe`` OpenCode agent. Her
operational modes (docs, documentation, chloe, archivist) plus the routing-only
audit and compaction modes all resolve to the ``chloe`` OpenCode agent. Like
every other agent (M1 Matthew … M7), her model and operation mode can be
configured individually from the settings screen — there are no hardcoded
model locks anymore.
"""

from __future__ import annotations

from .base import AgentSpec

# Chloe-specific mode labels (exported so the registry and UI can reference
# the audit mode and the archivist mode by name).
M7_AUDIT_MODE = "documentation-audit"
ARCHIVIST_MODE = "archivist"

# Routing-only modes: they dispatch to chloe but are not offered as generic
# operational picker options (they live in ``extra_modes`` for that reason).
COMPACT_MODES = ("compact", "compaction")

SPEC = AgentSpec(
    tag="m7",
    name="Chloe",
    agent="chloe",
    persona="Chloe",
    role="Archivist",
    modes=("docs", "documentation", "chloe", ARCHIVIST_MODE),
    extra_modes=(M7_AUDIT_MODE, *COMPACT_MODES),
    model="opencode/ling-3.0-tiny-free",
    description=(
        "Chloe — Architectural Obsidian Archivist: filters conversation from "
        "architectural decisions, stores notes under the task project's "
        "docs/architecture/ with embedded Mermaid maps, and keeps a lean "
        "per-project Evolution file. Read-only."
    ),
)
