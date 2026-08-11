"""M2 — Alex: core backend, APIs, and data handling."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m2",
    name="Alex",
    agent="alex",
    persona="Alex",
    role="Builder",
    modes=("backend", "api", "build", "alex"),
    model="opencode/deepseek-v4-flash-free",
    description=(
        "Alex — pragmatic core backend and API specialist owning robust Python "
        "logic, data handling, filesystem operations, background processes, and "
        "integrations."
    ),
)
