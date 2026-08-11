"""M6 — Max: DevOps, automation, and environment stability."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m6",
    name="Max",
    agent="max",
    persona="Max",
    role="DevOps",
    modes=("devops", "automation", "max"),
    model="opencode/deepseek-v4-flash-free",
    description=(
        "Max — systematic DevOps and automation specialist owning launchers, "
        "workers, execution paths, configuration plumbing, and build stability."
    ),
)
