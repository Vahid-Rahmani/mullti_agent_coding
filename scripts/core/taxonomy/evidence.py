"""Parse machine-readable repository evidence from source Markdown files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class EvidenceSchemaError(ValueError):
    """Raised when a source record has invalid or incomplete frontmatter."""


@dataclass(frozen=True)
class Evidence:
    id: str
    repository: str
    kind: str
    summary: str
    supports: tuple[str, ...]
    confidence: str
    requires_inspection: bool = False


@dataclass(frozen=True)
class Repository:
    id: str
    source_url: str
    license: str
    source_type: str
    extraction_mode: str
    code_reuse: str
    domains: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    path: str | None = None

    @property
    def url(self) -> str:
        """Compatibility alias for the design document's shorter field name."""
        return self.source_url


def _frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise EvidenceSchemaError("source record must start with YAML frontmatter")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise EvidenceSchemaError("unterminated YAML frontmatter") from exc
    data = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(data, dict):
        raise EvidenceSchemaError("frontmatter must be a YAML mapping")
    return data


def _required(data: dict[str, Any], key: str, expected: type) -> Any:
    value = data.get(key)
    if not isinstance(value, expected) or (isinstance(value, str) and not value.strip()):
        raise EvidenceSchemaError(f"frontmatter field {key!r} must be a non-empty {expected.__name__}")
    return value


def parse_source_text(text: str, *, path: str | None = None) -> Repository:
    data = _frontmatter(text)
    repo_id = _required(data, "id", str)
    evidence_data = data.get("evidence")
    if not isinstance(evidence_data, list):
        raise EvidenceSchemaError("frontmatter field 'evidence' must be a list")
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for item in evidence_data:
        if not isinstance(item, dict):
            raise EvidenceSchemaError("each evidence entry must be a mapping")
        local_id = _required(item, "id", str)
        evidence_id = f"{repo_id}:{local_id}"
        if evidence_id in seen:
            raise EvidenceSchemaError(f"duplicate evidence id: {evidence_id}")
        seen.add(evidence_id)
        supports = item.get("supports")
        if not isinstance(supports, list) or not supports or not all(isinstance(v, str) and v for v in supports):
            raise EvidenceSchemaError(f"{evidence_id}: supports must be a non-empty list of strings")
        confidence = item.get("confidence")
        if confidence not in {"direct", "inferred"}:
            raise EvidenceSchemaError(f"{evidence_id}: confidence must be direct or inferred")
        kind = item.get("kind")
        if kind not in {"pattern", "workflow", "output-policy", "methodology", "architecture"}:
            raise EvidenceSchemaError(f"{evidence_id}: invalid evidence kind")
        evidence.append(Evidence(evidence_id, repo_id, kind, _required(item, "summary", str), tuple(supports), confidence, bool(item.get("requires_inspection", False))))
    domains = data.get("domains", [])
    if not isinstance(domains, list) or not all(isinstance(v, str) for v in domains):
        raise EvidenceSchemaError("domains must be a list of strings")
    source_url = data.get("source_url", data.get("url"))
    if not isinstance(source_url, str) or not source_url.strip():
        raise EvidenceSchemaError("frontmatter field 'source_url' must be a non-empty string")
    return Repository(repo_id, source_url, _required(data, "license", str), _required(data, "source_type", str), _required(data, "extraction_mode", str), _required(data, "code_reuse", str), tuple(domains), tuple(evidence), path)


def parse_source_file(path: str | Path) -> Repository:
    source = Path(path)
    return parse_source_text(source.read_text(encoding="utf-8"), path=str(source))


def load_source_records(directory: str | Path) -> tuple[Repository, ...]:
    records = []
    for path in sorted(Path(directory).glob("*.md")):
        if path.name.lower() == "readme.md" or not path.read_text(encoding="utf-8").lstrip().startswith("---"):
            continue
        records.append(parse_source_file(path))
    return tuple(records)
