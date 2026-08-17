"""Pure generated-taxonomy plus curated-overrides resolver."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .overrides import load_overrides, validate_overrides


def resolve_effective(taxonomy: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    validate_overrides(taxonomy, overrides)
    result = deepcopy(taxonomy)
    for capability_id, changes in overrides.get("capability_overrides", {}).items():
        target = next(item for item in result["capabilities"] if item["id"] == capability_id)
        target.update({key: deepcopy(value) for key, value in changes.items() if key in {"name", "description", "domains"}})
    role_edges = result["role_edges"]
    for role_id, changes in overrides.get("role_overrides", {}).items():
        role_edges[role_id].update({key: deepcopy(value) for key, value in changes.items() if key in {"capabilities", "category"}})
    for role_id, ordered in overrides.get("skill_order_overrides", {}).items():
        result["role_skill_edges"][role_id] = list(ordered)
    for agent, changes in overrides.get("agent_assignment_overrides", {}).items():
        result["agent_assignments"][agent].update(deepcopy(changes))
        result["coverage"]["assignment_sources"][agent] = "override"
    explicit = set(result["coverage"].get("explicit_assignments", []))
    explicit.update(overrides.get("agent_assignment_overrides", {}))
    result["coverage"]["explicit_assignments"] = sorted(explicit)
    for category in result["categories"]:
        category_id = category["id"]
        category["id"] = overrides.get("category_overrides", {}).get("rename", {}).get(category_id, category_id)
    return result


def load_effective(root: Path | None = None) -> dict[str, Any]:
    import json

    base = Path(root) if root is not None else Path.cwd()
    taxonomy = json.loads((base / "knowledge" / "taxonomy" / "taxonomy.json").read_text(encoding="utf-8"))
    return resolve_effective(taxonomy, load_overrides(base))
