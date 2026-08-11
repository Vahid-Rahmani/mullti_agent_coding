"""Progress telemetry — token estimation and weighted progress aggregation.

No UI/rendering dependencies. These are pure math/telemetry functions.
"""

from __future__ import annotations

from .agents import AGENTS, STATUS_IDLE, STATUS_THINKING, STATUS_ACTIVE

TOKEN_CONTEXT_WINDOW = 8192
_TOKEN_CHARS_PER_TOKEN = 4
WORKING_LABEL = "working..."
_PROGRESS_BAR_WIDTH = 24


def _estimate_token_percent(prompt: str, output: list[str] | tuple[str, ...]) -> int:
    """Estimate prompt+stream token usage as a bounded percentage."""
    chars = len(prompt) + sum(len(line) for line in output)
    tokens = chars / _TOKEN_CHARS_PER_TOKEN
    return max(0, min(100, round(tokens / TOKEN_CONTEXT_WINDOW * 100)))


DEFAULT_PROGRESS_WEIGHTS: dict[str, float] = {tag: 1.0 for tag, _name, _agent in AGENTS}


def _weighted_progress(
    statuses: dict[str, str],
    progress: dict[str, int],
    tags: set[str] | list[str] | tuple[str, ...] | None = None,
    weights: dict[str, float] | None = None,
    terminal_value: int | None = None,
) -> int:
    """Return a bounded weighted progress average for the supplied tasks."""
    task_tags = list(tags) if tags is not None else [
        tag for tag, _name, _agent in AGENTS
        if statuses.get(tag, STATUS_IDLE) in (STATUS_THINKING, STATUS_ACTIVE)
    ]
    if not task_tags:
        return 0
    weights = weights or DEFAULT_PROGRESS_WEIGHTS
    total_weight = 0.0
    weighted_total = 0.0
    for tag in task_tags:
        weight = max(0.0, float(weights.get(tag, 1.0)))
        if not weight:
            continue
        value = (
            terminal_value
            if statuses.get(tag) == STATUS_IDLE and tags is not None and terminal_value is not None
            else (100 if statuses.get(tag) == STATUS_IDLE and tags is not None else progress.get(tag, 0))
        )
        weighted_total += weight * max(0, min(100, int(value)))
        total_weight += weight
    if not total_weight:
        return 0
    return max(0, min(100, int(weighted_total / total_weight + 0.5)))
