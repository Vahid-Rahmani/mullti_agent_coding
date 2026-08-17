"""Taxonomy-driven Agent Catalog tests."""

import tempfile
from pathlib import Path

from scripts.core import agent_catalog as catalog
from scripts.core import runtime_context
from scripts.core.agents.registry import AGENT_SPECS
from scripts.core.taxonomy.build import build_taxonomy
from scripts.core.taxonomy.overrides import load_overrides


def test_catalog_is_derived_from_effective_taxonomy():
    taxonomy = build_taxonomy()
    assert {item.id for item in catalog.list_categories()} == {item["id"] for item in taxonomy["categories"]}
    assert {item.agent_key for item in catalog.list_presets()} == {spec.agent for spec in AGENT_SPECS if spec.agent}


def test_empty_agent_is_zero_configuration():
    empty = catalog.empty_agent()
    assert empty.agent_key == empty.role == empty.model == empty.agent_mode == ""
    assert empty.capabilities == empty.role_ids == empty.skills == empty.prompt_profiles == empty.knowledge == ()
    assert catalog.build_preset_runtime_prompt(empty, "raw request") == "raw request"


def test_catalog_is_deterministic_unique_and_valid():
    first = [preset.to_dict() for preset in catalog.list_presets()]
    assert first == [preset.to_dict() for preset in catalog.list_presets()]
    assert len({item["id"] for item in first}) == len(first)
    assert catalog.validate_catalog() == []


def test_derived_preset_includes_matrix_configuration_and_runtime_model():
    config = catalog.resolve_preset_config(catalog.get_preset("agent-matthew"))
    assert config["capabilities"] and config["role_ids"] and config["skills"]
    assert config["model"] and config["agent_mode"] == "all"


def test_preset_application_persists_as_override_and_survives_rebuild():
    source_root = Path.cwd()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "knowledge" / "taxonomy"
        target.mkdir(parents=True)
        (target / "taxonomy.json").write_text((source_root / "knowledge" / "taxonomy" / "taxonomy.json").read_text(encoding="utf-8"), encoding="utf-8")
        preset = catalog.get_preset("agent-sarah", root)
        catalog.apply_preset(preset, root)
        saved = load_overrides(root)
        assert saved["agent_assignment_overrides"]["sarah"]["role_ids"] == list(preset.role_ids)
        prompt = runtime_context.build_runtime_prompt("sarah", user_request="persisted", repo_root=root)
        assert "## Skills" in prompt and "persisted" in prompt
        assert load_overrides(root) == saved


def test_category_api_compatibility():
    for category in catalog.list_categories():
        assert all(preset.category == category.id for preset in catalog.presets_for_category(category.id))
