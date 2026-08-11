"""M4 — David: QA, TDD, tests, and debugging."""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="m4",
    name="David",
    agent="david",
    persona="David",
    role="QA",
    modes=("qa", "test", "tester", "david"),
    model="opencode/big-pickle",
    description=(
        "David — rigorous QA and TDD lead owning unit/integration coverage, "
        "debugging, edge cases, and assertion quality."
    ),
)
