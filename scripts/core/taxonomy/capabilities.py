"""First-class capability records and provenance validation."""

import re
from dataclasses import dataclass

from .evidence import Repository


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
