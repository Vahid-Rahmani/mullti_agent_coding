"""M3 — Sarah: terminal interface, frontend, and UX."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m3",
    name="Sarah",
    agent="sarah",
    persona="Sarah",
    role="Frontend",
    modes=("frontend", "tui", "sarah"),
    model="opencode/deepseek-v4-flash-free",
    description=(
        "Sarah — detail-oriented terminal interface and UX engineer owning "
        "layout, rendering, interactions, modals, themes, and user-facing "
        "presentation."
    ),
)
