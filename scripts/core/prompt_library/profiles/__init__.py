"""Built-in prompt profile modules — one module per prompt role.

Each module exposes a ``PROFILES`` list of plain dicts; ``builtin.py``
validates and turns them into immutable :class:`PromptProfile` objects.
"""

from __future__ import annotations

from . import (
    ai_engineer,
    cloud_engineer,
    code_reviewer,
    data_engineer,
    debugger,
    devops_engineer,
    external,
    orchestrator,
    project_manager,
    qa_engineer,
    researcher,
    security_engineer,
    software_architect,
    software_engineer,
    technical_writer,
)

# Deterministic module order (mirrors PROMPT_ROLES) so registry ordering is stable.
MODULES = (
    software_engineer,
    software_architect,
    code_reviewer,
    debugger,
    qa_engineer,
    security_engineer,
    devops_engineer,
    cloud_engineer,
    data_engineer,
    ai_engineer,
    researcher,
    technical_writer,
    project_manager,
    orchestrator,
    external,  # cross-role: adapted from external research sources (provenance-tracked)
)


def all_profile_dicts() -> list[dict]:
    """Concatenate every module's raw profile dicts, in deterministic order."""
    out: list[dict] = []
    for module in MODULES:
        out.extend(module.PROFILES)
    return out


__all__ = ["MODULES", "all_profile_dicts"]
