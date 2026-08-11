"""Base specification for a single control-plane agent.

Every agent (M1..M7) and the master coordinator is described by an
``AgentSpec`` instance living in its own module under ``scripts/core/agents/``.
This keeps each agent independently configurable, testable, and modifiable.

Baseline-zero contract: agents are **plain** — an identity (tag/name/agent key)
plus a configured model. No roles, operational modes, system prompts, or other
specialized behavior wrappers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    """Declarative definition of one agent (or the master coordinator).

    Attributes:
        tag: Unique short tab tag, e.g. ``"m1"``.
        name: Human display name, e.g. ``"Matthew"``.
        agent: OpenCode agent key, e.g. ``"matthew"`` (``None`` for master).
        model: The agent's configured default model (mirrors ``opencode.json``;
            used by the launcher workers and the terminal). ``None`` for the
            master coordinator, which has no OpenCode agent.
    """

    tag: str
    name: str
    agent: str | None
    model: str | None = None
