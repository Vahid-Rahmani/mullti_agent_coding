"""Read-only taxonomy drift and integrity checks."""

import json
from pathlib import Path

from .build import build_taxonomy, validate_taxonomy
from .effective import load_effective
from .overrides import load_overrides, validate_overrides


def taxonomy_integrity(root: Path) -> dict:
    artifact = root / "knowledge" / "taxonomy" / "taxonomy.json"
    generated = build_taxonomy(root)
    validate_taxonomy(generated)
    stale = not artifact.is_file() or json.loads(artifact.read_text(encoding="utf-8")) != generated
    overrides = load_overrides(root)
    validate_overrides(generated, overrides)
    effective = load_effective(root)
    return {
        "stale": stale,
        "coverage_complete": not effective["coverage"]["uncovered_agents"]
        and not effective["coverage"]["uncovered_capabilities"],
        "override_valid": True,
        "effective_consistent": True,
    }
