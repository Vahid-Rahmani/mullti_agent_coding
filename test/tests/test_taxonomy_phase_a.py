from pathlib import Path

import pytest

from scripts.core.taxonomy.capabilities import (
    Capability,
    capabilities_from_repositories,
    stable_capability_id,
    validate_capabilities,
)
from scripts.core.taxonomy.evidence import (
    EvidenceSchemaError,
    load_source_records,
    parse_source_text,
)

SOURCES = Path("knowledge/sources")


def test_reference_sources_parse_with_provenance():
    records = load_source_records(SOURCES)
    assert {r.id for r in records} >= {"open-notebook", "no-ai-slop", "i-have-adhd", "open-seo", "book-to-skill", "strix", "open-generative-ai"}
    assert all(r.url and r.license and r.extraction_mode for r in records)
    assert all(e.repository == r.id and ":" in e.id for r in records for e in r.evidence)


def test_capabilities_have_stable_ids_and_provenance():
    capabilities = capabilities_from_repositories(load_source_records(SOURCES))
    assert capabilities
    assert all(c.id == stable_capability_id(c.id) for c in capabilities)
    assert all(c.source_repos and c.evidence and c.license for c in capabilities)
    validate_capabilities(capabilities)


def test_malformed_frontmatter_is_rejected():
    with pytest.raises(EvidenceSchemaError):
        parse_source_text("# no frontmatter")


def test_duplicate_evidence_ids_are_rejected():
    text = """---\nid: example\nurl: https://example.test\nlicense: MIT\nsource_type: test\nextraction_mode: ideas\ncode_reuse: "no"\nevidence:\n  - id: same\n    kind: pattern\n    summary: one\n    supports: [one]\n    confidence: direct\n  - id: same\n    kind: pattern\n    summary: two\n    supports: [two]\n    confidence: direct\n---\n# Example\n"""
    with pytest.raises(EvidenceSchemaError, match="duplicate evidence"):
        parse_source_text(text)


def test_requires_inspection_is_preserved():
    record = parse_source_text("""---\nid: example\nurl: https://example.test\nlicense: MIT\nsource_type: test\nextraction_mode: ideas\ncode_reuse: "no"\nevidence:\n  - id: provisional\n    kind: pattern\n    summary: inspect me\n    supports: [provisional-capability]\n    confidence: inferred\n    requires_inspection: true\n---\n# Example\n""")
    assert record.evidence[0].requires_inspection is True


def test_duplicate_capability_ids_are_rejected():
    capability = Capability("same", "Same", "desc", (), (), ("repo",), "source-derived", "MIT")
    with pytest.raises(ValueError, match="duplicate capability"):
        validate_capabilities([capability, capability])

