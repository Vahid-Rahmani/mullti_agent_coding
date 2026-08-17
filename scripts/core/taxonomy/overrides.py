"""Curated override storage and reference validation for the taxonomy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.core.agents import PROJECT_ROOT

DEFAULT_OVERRIDES: dict[str, Any] = {
    "schema_version": 1,
    "category_overrides": {},
    "capability_overrides": {},
    "role_overrides": {},
    "skill_order_overrides": {},
    "agent_assignment_overrides": {},
    "curated_presets": [],
}


class OverrideError(ValueError):
    """Raised when an override points at a missing generated entity."""


def overrides_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else PROJECT_ROOT) / "knowledge" / "taxonomy" / "overrides.json"


def load_overrides(root: Path | None = None) -> dict[str, Any]:
    path = overrides_path(root)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_OVERRIDES))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise OverrideError("overrides.json must be a schema version 1 object")
    merged = json.loads(json.dumps(DEFAULT_OVERRIDES))
    merged.update(data)
    return merged


def ensure_overrides(root: Path | None = None) -> Path:
    path = overrides_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_OVERRIDES, indent=2) + "\n", encoding="utf-8")
    return path


def save_overrides(data: dict[str, Any], root: Path | None = None) -> Path:
    """Persist curated overrides only; generated taxonomy is never rewritten."""
    path = overrides_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def validate_overrides(taxonomy: dict[str, Any], overrides: dict[str, Any]) -> None:
    capabilities = {item["id"] for item in taxonomy["capabilities"]}
    roles = set(taxonomy["role_edges"])
    skills = set(taxonomy["skill_edges"])
    agents = set(taxonomy["agent_assignments"])
    categories = {item["id"] for item in taxonomy["categories"]}
    for key, values, valid in (("capability_overrides", overrides.get("capability_overrides", {}), capabilities), ("role_overrides", overrides.get("role_overrides", {}), roles), ("skill_order_overrides", overrides.get("skill_order_overrides", {}), roles), ("agent_assignment_overrides", overrides.get("agent_assignment_overrides", {}), agents)):
        for reference in values:
            if reference not in valid:
                raise OverrideError(f"orphaned {key} reference: {reference}")
    for category in overrides.get("category_overrides", {}).get("rename", {}):
        if category not in categories:
            raise OverrideError(f"orphaned category override: {category}")
    for skill_ids in overrides.get("skill_order_overrides", {}).values():
        for skill_id in skill_ids:
            if skill_id not in skills:
                raise OverrideError(f"orphaned skill reference: {skill_id}")
    for values in overrides.get("role_overrides", {}).values():
        for capability in values.get("capabilities", []):
            if capability not in capabilities:
                raise OverrideError(f"orphaned capability reference: {capability}")
