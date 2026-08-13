"""Base specification for a single control-plane agent.

Every agent (M1..M7) and the master coordinator is described by an
``AgentSpec`` instance living in its own module under ``scripts/core/agents/``.
This keeps each agent independently configurable, testable, and modifiable.

Agent contract: an ``AgentSpec`` is **model-agnostic** — it carries only
identity (tag/name/agent key). The runtime model (and mode / fallback chain)
is selected through the Settings / BYOK system and lives **only** in
``opencode.json``, resolved via ``scripts.core.opencode_cfg.resolve_model``.
The same agent can therefore run on any provider/model without editing its
spec module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    """Declarative identity of one agent (or the master coordinator).

    Attributes:
        tag: Unique short tab tag, e.g. ``"m1"``.
        name: Human display name, e.g. ``"Matthew"``.
        agent: OpenCode agent key, e.g. ``"matthew"`` (``None`` for master).

    There is intentionally no ``model`` field: the model is a runtime concern
    owned by ``opencode.json`` and the Settings/BYOK layer, never by the
    agent's static identity.
    """

    tag: str
    name: str
    agent: str | None
