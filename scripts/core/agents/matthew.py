"""M1 — Matthew (plain agent)."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m1",
    name="Matthew",
    agent="matthew",
    model="google/gemini-3.1-flash-lite",
)
