"""Master — the coordinator tab that dispatches to the full roster.

The MASTER tab is the coordinator "agent": it has no OpenCode agent of its
own (``agent=None``); a task typed there is dispatched to all enabled agents.
Keeping it as an ``AgentSpec`` lets the registry build ``TABS`` uniformly.
"""

from __future__ import annotations

from .base import AgentSpec

SPEC = AgentSpec(
    tag="master",
    name="Master",
    agent=None,
)
