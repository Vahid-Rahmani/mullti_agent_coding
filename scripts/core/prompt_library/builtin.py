"""Built-in prompt library — the authoritative list of shipped profiles.

Every profile is validated through :func:`scripts.core.prompt_library.schema.validate_profile`
on first import, so a malformed or duplicate built-in can never silently ship.
The result is an immutable, deterministic list consumed by ``registry.py``.
"""

from __future__ import annotations

from . import profiles
from .schema import PromptProfile, validate_profile


class PromptLibraryError(ValueError):
    """Raised for a malformed or duplicate built-in profile (a programming error)."""


def _build() -> list[PromptProfile]:
    """Validate and freeze the built-in profiles into immutable PromptProfile objects."""
    built: list[PromptProfile] = []
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    for raw in profiles.all_profile_dicts():
        profile = PromptProfile.from_dict(raw)
        problems = validate_profile(profile)
        if problems:
            raise PromptLibraryError(
                f"invalid built-in prompt profile: {'; '.join(problems)}"
            )
        if profile.id in seen_ids:
            raise PromptLibraryError(f"duplicate prompt profile id {profile.id!r}")
        if profile.role not in seen_roles:
            seen_roles.add(profile.role)
        seen_ids.add(profile.id)
        built.append(profile)
    return built


BUILTIN_PROFILES: tuple[PromptProfile, ...] = tuple(_build())


__all__ = ["BUILTIN_PROFILES", "PromptLibraryError"]
