from scripts.core.agents.registry import AGENT_SPECS
from scripts.core.taxonomy.build import build_taxonomy
from scripts.core.taxonomy.coverage import runtime_agent_keys
from scripts.core.taxonomy.effective import resolve_effective


def test_every_registered_agent_has_complete_matrix_coverage():
    taxonomy = build_taxonomy()
    assert runtime_agent_keys() == tuple(spec.agent for spec in AGENT_SPECS if spec.agent)
    assert taxonomy["coverage"]["uncovered_agents"] == []
    assert taxonomy["coverage"]["uncovered_capabilities"] == []
    for agent in runtime_agent_keys():
        assignment = taxonomy["agent_assignments"][agent]
        assert assignment["capability_ids"] and assignment["role_ids"] and assignment["skill_ids"]


def test_capabilities_and_agents_are_many_to_many():
    assignments = build_taxonomy()["agent_assignments"]
    assert any(len(value["capability_ids"]) > 1 for value in assignments.values())
    owners = {}
    for agent, assignment in assignments.items():
        for capability in assignment["capability_ids"]:
            owners.setdefault(capability, set()).add(agent)
    assert any(len(agent_ids) > 1 for agent_ids in owners.values())


def test_fallback_is_deterministic_and_distinguished():
    taxonomy = build_taxonomy()
    assert build_taxonomy()["agent_assignments"] == taxonomy["agent_assignments"]
    assert taxonomy["coverage"]["fallback_assignments"]
    assert set(taxonomy["coverage"]["fallback_assignments"]).isdisjoint(taxonomy["coverage"]["explicit_assignments"])


def test_agent_override_beats_fallback():
    taxonomy = build_taxonomy()
    agent = taxonomy["coverage"]["fallback_assignments"][0]
    effective = resolve_effective(taxonomy, {"schema_version": 1, "agent_assignment_overrides": {agent: {"capability_ids": ["citation"]}}})
    assert effective["agent_assignments"][agent]["capability_ids"] == ["citation"]
    assert effective["coverage"]["assignment_sources"][agent] == "override"
