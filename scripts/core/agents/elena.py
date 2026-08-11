"""M5 — Elena: code quality and security audit (read-only)."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m5",
    name="Elena",
    agent="elena",
    persona="Elena",
    role="Security",
    modes=("security", "review", "reviewer", "elena"),
    model="opencode/ling-3.0-tiny-free",
    description=(
        "Elena — strict code quality and security auditor reviewing correctness, "
        "maintainability, secure patterns, and release readiness. Read-only."
    ),
)
