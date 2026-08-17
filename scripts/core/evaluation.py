"""Evaluation — a native, reusable abstraction for judging agent outputs.

The evaluation layer turns a task's *output* into a structured, deterministic
``score / findings / decision`` without any model, provider, credential, or
external dependency:

    Task → Agent / Workflow → Output → Evaluation → Score / Findings / Decision

An :class:`EvaluationDefinition` declares *what to look for* (ordered criteria
across a fixed dimension vocabulary); :func:`evaluate` turns per-criterion
numeric scores into a weighted total, a pass/review/fail decision, and generated
findings. Everything is deterministic and pure: the same criteria scores always
produce the same result. This is a foundation for workflows/agents to adopt, not
a full ML evaluation platform.

Definitions are structured data with the same provenance style as
:class:`~scripts.core.prompt_library.schema.PromptProfile`, so evaluation
patterns adapted from external research stay traceable to their source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.core.prompt_library.schema import ORIGINS

# The evaluation dimensions a criterion may belong to. Kept to the useful
# subset the system needs — correctness, completeness, quality, consistency,
# security, relevance, adherence — not an unbounded taxonomy.
EVALUATION_DIMENSIONS: tuple[str, ...] = (
    "correctness",
    "completeness",
    "quality",
    "consistency",
    "security",
    "relevance",
    "adherence",
)

# The decision a completed evaluation can reach.
DECISIONS: tuple[str, ...] = ("pass", "review", "fail")

# Per-criterion numeric scale: 0 (absent/wrong) .. 4 (excellent). Kept as a
# small integer scale so scores stay human-explainable and deterministic.
SCORE_MIN = 0
SCORE_MAX = 4

# Overall decision thresholds, as fractions of SCORE_MAX.
PASS_THRESHOLD = 0.75      # overall >= 75% of max → pass
REVIEW_THRESHOLD = 0.50    # overall >= 50% of max → review (needs attention)
# A criterion scoring at or below this fraction generates a finding.
FINDING_THRESHOLD = 0.50

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class EvaluationError(ValueError):
    """Raised for an unknown evaluation definition or invalid input."""


@dataclass(frozen=True)
class EvaluationCriterion:
    """One scored dimension of an evaluation.

    ``weight`` is a relative multiplier (default 1.0) so critical criteria can
    dominate the total without changing the per-criterion 0..4 scale.
    """

    id: str
    name: str
    description: str = ""
    dimension: str = ""          # one of EVALUATION_DIMENSIONS
    weight: float = 1.0

    @classmethod
    def from_dict(cls, data: dict) -> EvaluationCriterion:
        raw_weight = data.get("weight")
        weight = float(raw_weight) if raw_weight not in (None, "") else 1.0
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            dimension=str(data.get("dimension") or ""),
            weight=weight,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "dimension": self.dimension,
            "weight": self.weight,
        }


@dataclass(frozen=True)
class EvaluationDefinition:
    """A reusable set of criteria for judging one class of output."""

    id: str
    name: str
    description: str = ""
    criteria: tuple[EvaluationCriterion, ...] = ()
    pass_threshold: float = PASS_THRESHOLD
    review_threshold: float = REVIEW_THRESHOLD
    version: str = "1.0.0"
    # Provenance — same style as PromptProfile / Skill.
    source: str = ""
    source_url: str = ""
    license: str = ""
    origin: str = "original"
    adaptation_note: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> EvaluationDefinition:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            criteria=tuple(
                EvaluationCriterion.from_dict(c)
                for c in (data.get("criteria") or [])
            ),
            pass_threshold=float(data.get("pass_threshold") or PASS_THRESHOLD),
            review_threshold=float(data.get("review_threshold") or REVIEW_THRESHOLD),
            version=str(data.get("version") or "1.0.0"),
            source=str(data.get("source") or ""),
            source_url=str(data.get("source_url") or ""),
            license=str(data.get("license") or ""),
            origin=str(data.get("origin") or "original"),
            adaptation_note=str(data.get("adaptation_note") or ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "criteria": [c.to_dict() for c in self.criteria],
            "pass_threshold": self.pass_threshold,
            "review_threshold": self.review_threshold,
            "version": self.version,
            "source": self.source,
            "source_url": self.source_url,
            "license": self.license,
            "origin": self.origin,
            "adaptation_note": self.adaptation_note,
        }


def validate_definition(definition: EvaluationDefinition) -> list[str]:
    """Return human-readable validation problems (empty == valid).

    Enforces: slug id, non-empty name, at least one criterion, well-formed
    criteria (slug id, name, known dimension, positive weight), unique criterion
    ids, sane thresholds, a semver version, and provenance rules identical to
    ``validate_profile``.
    """
    problems: list[str] = []
    if not definition.id:
        problems.append("id is required")
    elif not _SLUG_RE.match(definition.id):
        problems.append(f"invalid id {definition.id!r} (use [a-z0-9._-])")
    if not definition.name.strip():
        problems.append(f"{definition.id or '?'}: name is required")
    if not definition.criteria:
        problems.append(f"{definition.id or '?'}: at least one criterion is required")

    seen: set[str] = set()
    for crit in definition.criteria:
        if not crit.id:
            problems.append(f"{definition.id or '?'}: a criterion has an empty id")
        elif not _SLUG_RE.match(crit.id):
            problems.append(f"{definition.id or '?'}: invalid criterion id "
                            f"{crit.id!r} (use [a-z0-9._-])")
        elif crit.id in seen:
            problems.append(f"{definition.id or '?'}: duplicate criterion id {crit.id!r}")
        seen.add(crit.id)
        if not crit.name.strip():
            problems.append(f"{definition.id or '?'}: criterion {crit.id!r} "
                            "has no name")
        if crit.dimension not in EVALUATION_DIMENSIONS:
            problems.append(f"{definition.id or '?'}: criterion {crit.id!r} has "
                            f"unknown dimension {crit.dimension!r}")
        if crit.weight <= 0:
            problems.append(f"{definition.id or '?'}: criterion {crit.id!r} "
                            "weight must be positive")

    if not (0.0 < definition.review_threshold < definition.pass_threshold <= 1.0):
        problems.append(f"{definition.id or '?'}: thresholds must satisfy "
                        "0 < review < pass <= 1")
    if not definition.version or not _VERSION_RE.match(definition.version):
        problems.append(f"{definition.id or '?'}: invalid version "
                        f"{definition.version!r} (use semver like 1.0.0)")
    if definition.origin not in ORIGINS:
        problems.append(f"{definition.id or '?'}: unknown origin {definition.origin!r}")
    if definition.origin != "original" and not definition.source.strip():
        problems.append(f"{definition.id or '?'}: origin {definition.origin!r} "
                        "requires a source reference")
    return problems


@dataclass(frozen=True)
class CriterionScore:
    """One criterion's numeric score (0..4) plus an optional note."""

    criterion_id: str
    score: float
    note: str = ""

    def to_dict(self) -> dict:
        return {"criterion_id": self.criterion_id, "score": self.score,
                "note": self.note}


@dataclass(frozen=True)
class EvaluationResult:
    """The structured outcome of evaluating one output."""

    definition_id: str
    scores: tuple[CriterionScore, ...] = ()
    overall: float = 0.0            # weighted mean, 0..4
    overall_normalized: float = 0.0  # 0..1 (overall / SCORE_MAX)
    decision: str = "fail"          # pass | review | fail
    findings: tuple[str, ...] = ()
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "definition_id": self.definition_id,
            "scores": [s.to_dict() for s in self.scores],
            "overall": self.overall,
            "overall_normalized": self.overall_normalized,
            "decision": self.decision,
            "findings": list(self.findings),
            "notes": dict(self.notes),
        }


def validate_scores(definition: EvaluationDefinition,
                    scores: dict[str, float]) -> list[str]:
    """Validate a raw ``{criterion_id: score}`` mapping against a definition.

    Every criterion must be present and within ``[SCORE_MIN, SCORE_MAX]``;
    unknown criterion ids are rejected so a typo can never silently pass.
    """
    problems: list[str] = []
    known = {c.id for c in definition.criteria}
    for cid in known:
        if cid not in scores:
            problems.append(f"missing score for criterion {cid!r}")
    for cid, score in scores.items():
        if cid not in known:
            problems.append(f"unknown criterion {cid!r}")
            continue
        if not (SCORE_MIN <= float(score) <= SCORE_MAX):
            problems.append(f"criterion {cid!r} score {score!r} out of range "
                            f"[{SCORE_MIN}, {SCORE_MAX}]")
    return problems


def evaluate(definition: EvaluationDefinition,
             scores: dict[str, float],
             notes: dict[str, str] | None = None) -> EvaluationResult:
    """Deterministically score an output against a definition.

    Computes a weighted mean over the criteria (a criterion's ``weight`` is
    applied relative to the sum of weights), clamps it to the 0..4 scale,
    derives a pass/review/fail decision from the definition's thresholds, and
    generates a finding for every criterion at or below the finding threshold.
    Raises :class:`EvaluationError` when the input is invalid (so callers get a
    clear failure rather than a silently wrong result).
    """
    definition_problems = validate_definition(definition)
    if definition_problems:
        raise EvaluationError(
            f"invalid evaluation definition {definition.id!r}: "
            f"{'; '.join(definition_problems)}"
        )
    score_problems = validate_scores(definition, scores)
    if score_problems:
        raise EvaluationError(f"invalid scores for {definition.id!r}: "
                              f"{'; '.join(score_problems)}")

    notes = notes or {}
    total_weight = sum(c.weight for c in definition.criteria) or 1.0
    weighted_sum = 0.0
    ordered: list[CriterionScore] = []
    findings: list[str] = []
    for crit in definition.criteria:
        raw = float(scores[crit.id])
        clamped = max(SCORE_MIN, min(SCORE_MAX, raw))
        weighted_sum += clamped * crit.weight
        ordered.append(CriterionScore(
            criterion_id=crit.id, score=clamped, note=notes.get(crit.id, "")))
        if clamped <= (SCORE_MAX * FINDING_THRESHOLD):
            findings.append(f"{crit.name}: {clamped}/{SCORE_MAX} "
                            f"({crit.dimension})")

    overall = round(weighted_sum / total_weight, 4)
    normalized = round(overall / SCORE_MAX, 4)
    if normalized >= definition.pass_threshold:
        decision = "pass"
    elif normalized >= definition.review_threshold:
        decision = "review"
    else:
        decision = "fail"

    return EvaluationResult(
        definition_id=definition.id,
        scores=tuple(ordered),
        overall=overall,
        overall_normalized=normalized,
        decision=decision,
        findings=tuple(findings),
        notes={"thresholds": {"pass": definition.pass_threshold,
                              "review": definition.review_threshold}},
    )


# ---------------------------------------------------------------- built-in defs


class EvaluationLibraryError(ValueError):
    """Raised for a malformed or duplicate built-in evaluation (a programming error)."""


def _build() -> tuple[EvaluationDefinition, ...]:
    built: list[EvaluationDefinition] = []
    seen: set[str] = set()
    for raw in BUILTIN_EVALUATION_DICTS:
        definition = EvaluationDefinition.from_dict(raw)
        problems = validate_definition(definition)
        if problems:
            raise EvaluationLibraryError(
                f"invalid built-in evaluation: {'; '.join(problems)}"
            )
        if definition.id in seen:
            raise EvaluationLibraryError(f"duplicate evaluation id {definition.id!r}")
        seen.add(definition.id)
        built.append(definition)
    return tuple(built)


BUILTIN_EVALUATIONS: tuple[EvaluationDefinition, ...] = ()
_EVALUATIONS: dict[str, EvaluationDefinition] = {}


def list_evaluations() -> list[EvaluationDefinition]:
    """All built-in evaluation definitions, deterministically ordered by id."""
    return sorted(_EVALUATIONS.values(), key=lambda d: d.id)


def get_evaluation(evaluation_id: str) -> EvaluationDefinition:
    """Return one definition by id, or raise :class:`EvaluationError`."""
    definition = _EVALUATIONS.get((evaluation_id or "").strip())
    if definition is None:
        raise EvaluationError(f"unknown evaluation definition {evaluation_id!r}")
    return definition


# The general agent-output rubric (original). Covers the core dimensions:
# correctness, completeness, quality, consistency, relevance, adherence.
_GENERAL_CRITERIA = (
    EvaluationCriterion(
        id="correctness", name="Correctness", dimension="correctness",
        description="The output is factually and logically correct.",
        weight=2.0),
    EvaluationCriterion(
        id="completeness", name="Completeness", dimension="completeness",
        description="The output addresses every part of the request.", weight=1.5),
    EvaluationCriterion(
        id="quality", name="Quality", dimension="quality",
        description="The output is well-formed, clear, and idiomatic.", weight=1.0),
    EvaluationCriterion(
        id="consistency", name="Consistency", dimension="consistency",
        description="The output is internally consistent and consistent with prior context."),
    EvaluationCriterion(
        id="relevance", name="Relevance", dimension="relevance",
        description="The output stays on task without tangents."),
    EvaluationCriterion(
        id="adherence", name="Adherence", dimension="adherence",
        description="The output follows the stated requirements and constraints.",
        weight=1.5),
)

# Security-findings rubric (adapted from the Strix find→validate→fix→re-scan
# model): evidence-grounded findings, validated fixes, honest reporting.
_SECURITY_CRITERIA = (
    EvaluationCriterion(
        id="correctness", name="Finding Correctness", dimension="correctness",
        description="Each finding is a real, reachable issue, not static-analysis noise.",
        weight=2.0),
    EvaluationCriterion(
        id="evidence", name="Evidence", dimension="adherence",
        description="Each finding carries a reproduction / proof-of-concept with concrete steps.",
        weight=2.0),
    EvaluationCriterion(
        id="completeness", name="Completeness", dimension="completeness",
        description="The surface was covered within the authorized scope."),
    EvaluationCriterion(
        id="severity", name="Severity Calibration", dimension="quality",
        description="Severity reflects realistic exploitability, not theoretical worst case.",
        weight=1.5),
    EvaluationCriterion(
        id="verification", name="Fix Verification", dimension="adherence",
        description="Fixes were re-tested and findings marked closed/unverified honestly.",
        weight=1.5),
    EvaluationCriterion(
        id="safety", name="Safety & Scope", dimension="security",
        description="The work stayed within authorized scope and trust boundaries."),
)

# Research-output rubric (adapted from the open-notebook source/citation model):
# every claim traces to a source; provenance and gaps are explicit.
_RESEARCH_CRITERIA = (
    EvaluationCriterion(
        id="correctness", name="Claim Accuracy", dimension="correctness",
        description="Claims faithfully reflect their sources without distortion.",
        weight=2.0),
    EvaluationCriterion(
        id="citation", name="Citation Coverage", dimension="adherence",
        description="Every claim carries a traceable source reference.",
        weight=2.0),
    EvaluationCriterion(
        id="completeness", name="Completeness", dimension="completeness",
        description="The question is covered, with gaps and open questions called out."),
    EvaluationCriterion(
        id="separation", name="Claim / Interpretation Separation", dimension="quality",
        description="The source's claim is kept distinct from the AI's interpretation."),
    EvaluationCriterion(
        id="relevance", name="Relevance", dimension="relevance",
        description="Findings stay relevant to the research question."),
)


def _to_dict(criteria: tuple[EvaluationCriterion, ...]) -> list[dict]:
    return [c.to_dict() for c in criteria]


BUILTIN_EVALUATION_DICTS: tuple[dict, ...] = (
    {
        "id": "agent-output-quality",
        "name": "Agent Output Quality",
        "description": "General rubric for judging any agent or workflow output.",
        "criteria": _to_dict(_GENERAL_CRITERIA),
        "pass_threshold": PASS_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "version": "1.0.0",
    },
    {
        "id": "security-findings-quality",
        "name": "Security Findings Quality",
        "description": "Rubric for pentest / security-audit findings: evidence over assertion.",
        "criteria": _to_dict(_SECURITY_CRITERIA),
        "pass_threshold": PASS_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "version": "1.0.0",
        "source": "usestrix/strix",
        "source_url": "https://github.com/usestrix/strix",
        "license": "Apache-2.0",
        "origin": "adapted",
        "adaptation_note": "Evidence-grounded, validated-fix, honest-reporting rubric distilled from the Strix pentesting model; no code copied.",
    },
    {
        "id": "research-output-quality",
        "name": "Research Output Quality",
        "description": "Rubric for cited research output: every claim traces to a source.",
        "criteria": _to_dict(_RESEARCH_CRITERIA),
        "pass_threshold": PASS_THRESHOLD,
        "review_threshold": REVIEW_THRESHOLD,
        "version": "1.0.0",
        "source": "lfnovo/open-notebook",
        "source_url": "https://github.com/lfnovo/open-notebook",
        "license": "MIT",
        "origin": "adapted",
        "adaptation_note": "Citation/provenance quality rubric adapted from the open-notebook source model; no code copied.",
    },
)


# Build the validated registry once the built-in data is defined above.
_BUILT = _build()
BUILTIN_EVALUATIONS = _BUILT
_EVALUATIONS = {d.id: d for d in _BUILT}


__all__ = [
    "BUILTIN_EVALUATIONS",
    "DECISIONS",
    "EVALUATION_DIMENSIONS",
    "FINDING_THRESHOLD",
    "PASS_THRESHOLD",
    "REVIEW_THRESHOLD",
    "SCORE_MAX",
    "SCORE_MIN",
    "CriterionScore",
    "EvaluationCriterion",
    "EvaluationDefinition",
    "EvaluationError",
    "EvaluationResult",
    "evaluate",
    "get_evaluation",
    "list_evaluations",
    "validate_definition",
    "validate_scores",
]
