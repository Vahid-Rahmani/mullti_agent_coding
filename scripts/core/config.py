"""Session configuration model — decoupled state for the multi-agent UI.

Provides a clean, serializable data structure for agent toggles, model/mode
overrides, specialized system prompts, and typography preferences. The UI
reads and writes this model; the core uses it for dispatch filtering.

No UI or rendering dependencies.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field

from .agents import (
    AGENTS, AUTO_MODE, AUTO_MODEL, DEFAULT_ENABLED_AGENTS,
)


@dataclass
class TypographyConfig:
    """User-facing typography and layout preferences."""

    input_min_lines: int = 3
    input_max_lines: int = 12
    console_min_lines: int = 5
    console_preferred_lines: int = 12
    font_scale: float = 1.0

    def to_dict(self) -> dict:
        return {
            "input_min_lines": self.input_min_lines,
            "input_max_lines": self.input_max_lines,
            "console_min_lines": self.console_min_lines,
            "console_preferred_lines": self.console_preferred_lines,
            "font_scale": self.font_scale,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TypographyConfig":
        return cls(
            input_min_lines=int(data.get("input_min_lines", 3)),
            input_max_lines=int(data.get("input_max_lines", 12)),
            console_min_lines=int(data.get("console_min_lines", 5)),
            console_preferred_lines=int(data.get("console_preferred_lines", 12)),
            font_scale=float(data.get("font_scale", 1.0)),
        )


@dataclass
class SessionConfig:
    """Complete user-facing session configuration.

    Holds all mutable settings that the UI layer manages: which agents are
    active, model/mode overrides per tab, specialized system prompts, and
    typography/layout preferences.
    """

    enabled_agents: set[str] = field(default_factory=lambda: set(DEFAULT_ENABLED_AGENTS))
    overrides: dict[str, dict[str, str]] = field(default_factory=lambda: {
        "master": {"model": AUTO_MODEL, "mode": AUTO_MODE},
    })
    system_prompts: dict[str, str] = field(default_factory=dict)
    typography: TypographyConfig = field(default_factory=TypographyConfig)
    roster_version: str = "2026-08-humanified-v1"

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for persistence (e.g. state.md)."""
        return {
            "enabled_agents": sorted(self.enabled_agents),
            "overrides": {k: dict(v) for k, v in self.overrides.items()},
            "system_prompts": dict(self.system_prompts),
            "typography": self.typography.to_dict(),
            "roster_version": self.roster_version,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "SessionConfig":
        """Load from a persisted dict, with safe defaults for missing keys."""
        if not data:
            return cls()
        enabled = set(data.get("enabled_agents", []))
        if not enabled:
            enabled = set(DEFAULT_ENABLED_AGENTS)
        overrides_raw = data.get("overrides", {})
        overrides: dict[str, dict[str, str]] = {}
        for key, val in overrides_raw.items():
            if isinstance(val, dict):
                overrides[key] = dict(val)
        if "master" not in overrides:
            overrides["master"] = {"model": AUTO_MODEL, "mode": AUTO_MODE}
        typo = TypographyConfig.from_dict(data.get("typography", {}))
        return cls(
            enabled_agents=enabled,
            overrides=overrides,
            system_prompts=data.get("system_prompts", {}),
            typography=typo,
            roster_version=data.get("roster_version", "2026-08-humanified-v1"),
        )

    def clone(self) -> "SessionConfig":
        """Return a deep copy for draft/rollback workflows."""
        return deepcopy(self)

    def is_agent_enabled(self, tag: str) -> bool:
        """Check whether an agent tag is currently enabled for dispatch."""
        return tag in self.enabled_agents

    def enable_agent(self, tag: str) -> None:
        """Add an agent tag to the enabled set."""
        valid = {t for t, _, _ in AGENTS}
        if tag in valid:
            self.enabled_agents.add(tag)

    def disable_agent(self, tag: str) -> None:
        """Remove an agent tag from the enabled set (at least one must remain)."""
        if len(self.enabled_agents) > 1:
            self.enabled_agents.discard(tag)

    def set_override(self, target: str, key: str, value: str) -> None:
        """Write a per-tab model/mode override.

        Every agent (M1..M7) is individually configurable — there are no
        locked agents, so ``all`` fans out to the entire roster.
        """
        if target == "all":
            for tag, _, _ in AGENTS:
                self.overrides.setdefault(tag, {})[key] = value
        else:
            self.overrides.setdefault(target, {})[key] = value

    def resolve(self, tag: str, hub=None) -> tuple[str | None, str]:
        """Resolve effective (model, mode) for a tag using the hub."""
        if hub is None:
            from .run_hub import HUB as _hub
            hub = _hub
        return hub.resolve(tag, self.overrides)
