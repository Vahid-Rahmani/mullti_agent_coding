"""Phase G–H normalization, migration, and integrity tests."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

from scripts.core.agents import PROJECT_ROOT
from scripts.core.taxonomy import build
from scripts.core.taxonomy.build import build_taxonomy, write_taxonomy
from scripts.core.taxonomy.capabilities import load_internal_capabilities
from scripts.core.taxonomy.integrity import taxonomy_integrity
from scripts.core.taxonomy.overrides import load_overrides, migrate_agent_context


def test_build_has_no_legacy_role_or_prompt_seed_dependency():
    source = inspect.getsource(build)
    assert "_role_skill_map" not in source
    assert "suggest_prompts_for_role" not in source
    assert "relations.json" in source


def test_internal_capabilities_are_original_and_preserve_internal_provenance():
    capabilities = load_internal_capabilities(PROJECT_ROOT)
    assert capabilities
    assert {"repository-analysis", "code-review"} <= {item.id for item in capabilities}
    assert all(item.origin == "original" for item in capabilities)
    assert all(item.source_repos == ("internal",) for item in capabilities)
    assert all(item.license == "internal" for item in capabilities)


def test_agent_context_migrates_without_deleting_the_legacy_file(tmp_path: Path):
    legacy = {
        "skill_assignments": {"matthew": ["structured-research"]},
        "prompt_assignments": {"matthew": ["researcher-analyst"]},
    }
    source = tmp_path / "agent_context.json"
    source.write_text(json.dumps(legacy), encoding="utf-8")

    assert migrate_agent_context(tmp_path) == {"matthew": ["skills", "prompts"]}
    assignment = load_overrides(tmp_path)["agent_assignment_overrides"]["matthew"]
    assert assignment == {
        "skill_ids": ["structured-research"],
        "prompt_profile_ids": ["researcher-analyst"],
    }
    assert json.loads(source.read_text(encoding="utf-8")) == legacy
    assert migrate_agent_context(tmp_path) == {}


def test_integrity_reports_staleness_when_a_structured_source_changes(tmp_path: Path):
    shutil.copytree(PROJECT_ROOT / "knowledge", tmp_path / "knowledge")
    shutil.copy2(PROJECT_ROOT / "roles.json", tmp_path / "roles.json")
    write_taxonomy(tmp_path)
    assert taxonomy_integrity(tmp_path)["stale"] is False

    relations = tmp_path / "knowledge" / "taxonomy" / "relations.json"
    relation_data = json.loads(relations.read_text(encoding="utf-8"))
    relation_data["role_prompt_edges"]["researcher"] = []
    relations.write_text(json.dumps(relation_data, indent=2) + "\n", encoding="utf-8")
    assert taxonomy_integrity(tmp_path)["stale"] is True


def test_normalized_build_remains_deterministic_and_covered():
    first = build_taxonomy()
    second = build_taxonomy()
    assert first == second
    assert first["coverage"]["uncovered_agents"] == []
