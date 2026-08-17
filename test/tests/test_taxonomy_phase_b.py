import json
from pathlib import Path

import pytest

from scripts.core.taxonomy.build import build_taxonomy
from scripts.core.taxonomy.effective import resolve_effective
from scripts.core.taxonomy.overrides import OverrideError


def test_taxonomy_has_schema_edges_categories_and_provenance():
    taxonomy = build_taxonomy()
    assert taxonomy["schema_version"] == 1
    assert taxonomy["repositories"] and taxonomy["evidence"] and taxonomy["capabilities"]
    assert taxonomy["categories"]
    assert taxonomy["role_skill_edges"]
    assert taxonomy["role_prompt_edges"]
    assert all(item["source_repos"] and item["license"] for item in taxonomy["capabilities"])


def test_build_is_byte_stable(tmp_path: Path):
    first = json.dumps(build_taxonomy(), indent=2) + "\n"
    second = json.dumps(build_taxonomy(), indent=2) + "\n"
    assert first == second


def test_override_precedence():
    taxonomy = build_taxonomy()
    capability_id = taxonomy["capabilities"][0]["id"]
    role_id = next(iter(taxonomy["role_edges"]))
    overrides = {"schema_version": 1, "capability_overrides": {capability_id: {"name": "Curated Name"}}, "role_overrides": {role_id: {"category": "curated"}}, "skill_order_overrides": {}, "agent_assignment_overrides": {}, "category_overrides": {}, "curated_presets": []}
    effective = resolve_effective(taxonomy, overrides)
    assert next(item for item in effective["capabilities"] if item["id"] == capability_id)["name"] == "Curated Name"
    assert effective["role_edges"][role_id]["category"] == "curated"


def test_orphaned_override_fails_loudly():
    taxonomy = build_taxonomy()
    overrides = {"schema_version": 1, "capability_overrides": {"missing": {"name": "bad"}}}
    with pytest.raises(OverrideError, match="orphaned"):
        resolve_effective(taxonomy, overrides)
