"""Base specification for a single control-plane agent.

Every specialized agent (M1..M7) and the master coordinator is described by an
``AgentSpec`` instance living in its own module under ``scripts/core/agents/``.
This keeps each agent independently configurable, testable, and modifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentSpec:
    """Declarative definition of one agent (or the master coordinator).

    Attributes:
        tag: Unique short tab tag, e.g. ``"m1"``.
        name: Human display name, e.g. ``"Matthew"``.
        agent: OpenCode agent key, e.g. ``"matthew"`` (``None`` for master).
        persona: Persona display name used for tab identity badges.
        role: Short role badge, e.g. ``"Architect"``.
        modes: Operational modes routed to this agent (shown in pickers).
        extra_modes: Routing-only modes (in ``MODE_TO_AGENT`` but not offered
            as operational picker options), e.g. Chloe's audit/compact modes.
        description: Long-form role description for Obsidian agent logs.
        model: The agent's configured default model (mirrors ``opencode.json``;
            used by the launcher workers and the terminal). ``None`` for the
            master coordinator, which has no OpenCode agent.
        immutable: When true the model/mode are locked (``pinned_model``/``pinned_mode``).
        pinned_model: Locked model for immutable agents (e.g. Chloe).
        pinned_mode: Locked mode for immutable agents (e.g. Chloe's audit mode).
    """

    tag: str
    name: str
    agent: str | None
    persona: str
    role: str
    modes: tuple[str, ...] = field(default_factory=tuple)
    extra_modes: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    model: str | None = None
    immutable: bool = False
    pinned_model: str | None = None
    pinned_mode: str | None = None

    @property
    def all_modes(self) -> tuple[str, ...]:
        """Every mode this agent accepts (operational + routing-only)."""
        return self.modes + self.extra_modes
