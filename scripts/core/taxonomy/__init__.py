"""Repository-driven taxonomy primitives.

Phase A deliberately exposes data models and parsing only; runtime taxonomy
resolution remains unchanged until a later phase.
"""

from .capabilities import (
    Capability,
    capabilities_from_repositories,
    validate_capabilities,
)
from .evidence import (
    Evidence,
    Repository,
    load_source_records,
    parse_source_file,
    parse_source_text,
)

__all__ = [
    "Capability",
    "Evidence",
    "Repository",
    "capabilities_from_repositories",
    "load_source_records",
    "parse_source_file",
    "parse_source_text",
    "validate_capabilities",
]
