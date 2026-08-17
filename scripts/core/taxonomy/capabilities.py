"""First-class capability records and provenance validation."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .evidence import Evidence, Repository


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    description: str
    domains: tuple[str, ...]
    evidence: tuple[str, ...]
    source_repos: tuple[str, ...]
    origin: str
    license: str


def stable_capability_id(value: str) -> str:
    """Return the canonical, deterministic capability slug."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def validate_capabilities(capabilities: tuple[Capability, ...] | list[Capability]) -> None:
    ids: set[str] = set()
    for capability in capabilities:
        if not capability.id or capability.id != stable_capability_id(capability.id):
            raise ValueError(f"invalid capability id: {capability.id!r}")
        if capability.id in ids:
            raise ValueError(f"duplicate capability id: {capability.id}")
        ids.add(capability.id)
        if capability.origin != "original" and (not capability.source_repos or not capability.license):
            raise ValueError(f"non-original capability lacks provenance: {capability.id}")


def capabilities_from_repositories(repositories: tuple[Repository, ...] | list[Repository]) -> tuple[Capability, ...]:
    records: dict[str, dict[str, object]] = {}
    for repo in repositories:
        for evidence in repo.evidence:
            for raw_id in evidence.supports:
                capability_id = stable_capability_id(raw_id)
                record = records.setdefault(capability_id, {"evidence": set(), "repos": set(), "domains": set(), "inspection": False})
                record["evidence"].add(evidence.id)  # type: ignore[union-attr]
                record["repos"].add(repo.id)  # type: ignore[union-attr]
                record["domains"].update(repo.domains)  # type: ignore[union-attr]
                record["inspection"] = bool(record["inspection"]) or evidence.requires_inspection
    result = []
    for capability_id, record in sorted(records.items()):
        name = capability_id.replace("-", " ").title()
        result.append(Capability(capability_id, name, f"Capability evidenced by repository research: {name.lower()}.", tuple(sorted(record["domains"])), tuple(sorted(record["evidence"])), tuple(sorted(record["repos"])), "source-derived", "aggregated"))
    validate_capabilities(result)
    return tuple(result)


def load_internal_capabilities(root: Path) -> tuple[Capability, ...]:
    """Load original/internal capability evidence without external provenance."""
    data = json.loads((root / "knowledge" / "taxonomy" / "internal_capabilities.json").read_text(encoding="utf-8"))
    capabilities = tuple(Capability(item["id"], item["name"], item["description"], tuple(item["domains"]), tuple(item["evidence"]), tuple(item["source_repos"]), item["origin"], item["license"]) for item in data)
    validate_capabilities(capabilities)
    return capabilities


def internal_evidence_from_capabilities(
        capabilities: tuple[Capability, ...]) -> tuple[Evidence, ...]:
    """Materialize original/internal evidence records referenced by capabilities."""
    grouped: dict[str, list[str]] = {}
    for capability in capabilities:
        for evidence_id in capability.evidence:
            grouped.setdefault(evidence_id, []).append(capability.id)
    return tuple(
        Evidence(
            id=evidence_id,
            repository="internal",
            kind="architecture",
            summary="Original MultiAgentCoding capability declaration.",
            supports=tuple(sorted(capability_ids)),
            confidence="direct",
        )
        for evidence_id, capability_ids in sorted(grouped.items())
    )
