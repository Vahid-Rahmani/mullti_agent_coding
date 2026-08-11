"""M1 — Matthew: lead architect and master coordinator (read-only)."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m1",
    name="Matthew",
    agent="matthew",
    persona="Matthew",
    role="Architect",
    modes=("architect", "analyze", "plan", "matthew"),
    model="opencode/deepseek-v4-flash-free",
    description=(
        "Matthew — analytical, approachable lead system architect and master "
        "coordinator guiding structure, routing, and design decisions. Read-only."
    ),
)
