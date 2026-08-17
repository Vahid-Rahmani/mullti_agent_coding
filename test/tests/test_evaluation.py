"""Evaluation abstraction tests — schema, criteria, scoring, provenance.

Covers the new ``scripts.core.evaluation`` module: definition/criterion
validation, unique ids, deterministic weighted scoring, the pass/review/fail
decision, generated findings, invalid-input handling, and provenance rules for
adapted definitions. No model, provider, or external dependency is involved.
"""

import os
import sys
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

from scripts.core import evaluation as E


def _good_definition(**overrides):
    data = {
        "id": "test-rubric",
        "name": "Test Rubric",
        "criteria": [
            {"id": "correctness", "name": "Correctness",
             "dimension": "correctness", "weight": 1.0},
            {"id": "completeness", "name": "Completeness",
             "dimension": "completeness", "weight": 1.0},
        ],
        "version": "1.0.0",
    }
    data.update(overrides)
    return E.EvaluationDefinition.from_dict(data)


class TestSchema(unittest.TestCase):
    def test_definition_requires_id(self):
        d = _good_definition(id="")
        self.assertTrue(any("id is required" in m for m in E.validate_definition(d)))

    def test_definition_requires_name(self):
        d = _good_definition(name=" ")
        self.assertTrue(any("name is required" in m for m in E.validate_definition(d)))

    def test_definition_requires_at_least_one_criterion(self):
        d = _good_definition(criteria=[])
        self.assertTrue(any("criterion" in m for m in E.validate_definition(d)))

    def test_criterion_requires_known_dimension(self):
        d = _good_definition(criteria=[
            {"id": "c1", "name": "C", "dimension": "banana"}])
        self.assertTrue(any("unknown dimension" in m for m in E.validate_definition(d)))

    def test_duplicate_criterion_ids_rejected(self):
        d = _good_definition(criteria=[
            {"id": "c1", "name": "A", "dimension": "quality"},
            {"id": "c1", "name": "B", "dimension": "quality"},
        ])
        self.assertTrue(any("duplicate criterion id" in m
                            for m in E.validate_definition(d)))

    def test_non_positive_weight_rejected(self):
        d = _good_definition(criteria=[
            {"id": "c1", "name": "A", "dimension": "quality", "weight": 0.0}])
        self.assertTrue(any("weight must be positive" in m
                            for m in E.validate_definition(d)))

    def test_invalid_thresholds_rejected(self):
        d = _good_definition(pass_threshold=0.5, review_threshold=0.9)
        self.assertTrue(any("thresholds" in m for m in E.validate_definition(d)))

    def test_valid_definition_passes(self):
        self.assertEqual(E.validate_definition(_good_definition()), [])

    def test_roundtrip(self):
        d = E.get_evaluation("agent-output-quality")
        back = E.EvaluationDefinition.from_dict(d.to_dict())
        self.assertEqual(back.id, d.id)
        self.assertEqual([c.id for c in back.criteria],
                         [c.id for c in d.criteria])


class TestProvenance(unittest.TestCase):
    def test_adapted_evaluations_carry_source(self):
        for eid in ("security-findings-quality", "research-output-quality"):
            d = E.get_evaluation(eid)
            self.assertEqual(E.validate_definition(d), [], eid)
            self.assertEqual(d.origin, "adapted", eid)
            self.assertTrue(d.source.strip(), eid)
            self.assertTrue(d.source_url.startswith("https://"), eid)
            self.assertTrue(d.license.strip(), eid)
            self.assertTrue(d.adaptation_note.strip(), eid)

    def test_original_defaults_to_original(self):
        d = E.get_evaluation("agent-output-quality")
        self.assertEqual(d.origin, "original")
        self.assertEqual(d.source, "")

    def test_non_original_requires_source(self):
        d = _good_definition(origin="adapted")
        self.assertTrue(any("requires a source reference" in m
                            for m in E.validate_definition(d)))


class TestRegistry(unittest.TestCase):
    def test_all_ids_unique_and_known(self):
        defs = E.list_evaluations()
        self.assertEqual(len(defs), 3, "3 built-in evaluation definitions expected")
        self.assertEqual(len({d.id for d in defs}), len(defs))

    def test_get_evaluation_and_unknown_raises(self):
        d = E.get_evaluation("security-findings-quality")
        self.assertIn("evidence", [c.id for c in d.criteria])
        with self.assertRaises(E.EvaluationError):
            E.get_evaluation("does-not-exist")

    def test_deterministic_ordering(self):
        ids = [d.id for d in E.list_evaluations()]
        self.assertEqual(ids, sorted(ids))


class TestScoring(unittest.TestCase):
    def _scores(self, definition, value):
        return {c.id: value for c in definition.criteria}

    def test_all_max_passes(self):
        d = E.get_evaluation("agent-output-quality")
        r = E.evaluate(d, self._scores(d, 4))
        self.assertEqual(r.decision, "pass")
        self.assertEqual(r.overall, 4.0)
        self.assertEqual(r.overall_normalized, 1.0)
        self.assertEqual(r.findings, ())

    def test_all_min_fails(self):
        d = E.get_evaluation("agent-output-quality")
        r = E.evaluate(d, self._scores(d, 0))
        self.assertEqual(r.decision, "fail")
        self.assertEqual(r.overall, 0.0)
        self.assertEqual(len(r.findings), len(d.criteria))

    def test_weights_affect_overall(self):
        # correctness weighs 2.0; quality weighs 1.0 — a perfect correctness
        # with zero quality yields a higher total than the reverse.
        d = E.get_evaluation("agent-output-quality")
        perfect_correctness = {c.id: (4 if c.id == "correctness" else 0)
                               for c in d.criteria}
        r1 = E.evaluate(d, perfect_correctness)
        perfect_quality = {c.id: (4 if c.id == "quality" else 0)
                           for c in d.criteria}
        r2 = E.evaluate(d, perfect_quality)
        self.assertGreater(r1.overall, r2.overall)

    def test_midpoint_reviews(self):
        d = _good_definition()
        r = E.evaluate(d, {"correctness": 2, "completeness": 2})
        self.assertEqual(r.decision, "review")

    def test_threshold_boundaries(self):
        d = E.get_evaluation("agent-output-quality")
        # 3/4 = 0.75 exactly → pass (>= pass_threshold)
        r = E.evaluate(d, self._scores(d, 3))
        self.assertEqual(r.decision, "pass")
        self.assertEqual(r.overall_normalized, 0.75)

    def test_decision_and_score_structure(self):
        d = E.get_evaluation("security-findings-quality")
        r = E.evaluate(d, {c.id: 4 for c in d.criteria}, notes={"evidence": "has PoC"})
        payload = r.to_dict()
        self.assertEqual(payload["definition_id"], "security-findings-quality")
        self.assertIn("scores", payload)
        self.assertIn("overall", payload)
        self.assertIn("decision", payload)
        self.assertIn("findings", payload)
        by_id = {s["criterion_id"]: s for s in payload["scores"]}
        self.assertEqual(by_id["evidence"]["note"], "has PoC")

    def test_scores_out_of_range_rejected(self):
        d = E.get_evaluation("agent-output-quality")
        with self.assertRaises(E.EvaluationError):
            E.evaluate(d, {"correctness": 5})
        with self.assertRaises(E.EvaluationError):
            E.evaluate(d, {"correctness": -1})

    def test_missing_criterion_rejected(self):
        d = E.get_evaluation("agent-output-quality")
        with self.assertRaises(E.EvaluationError):
            E.evaluate(d, {"correctness": 4})

    def test_unknown_criterion_rejected(self):
        d = E.get_evaluation("agent-output-quality")
        with self.assertRaises(E.EvaluationError):
            E.evaluate(d, {"correctness": 4, "ghost": 4})

    def test_clamping_keeps_score_in_range(self):
        # validate_scores rejects out-of-range, but evaluate clamps defensively
        d = _good_definition()
        problems = E.validate_scores(d, {"correctness": 99, "completeness": 4})
        self.assertTrue(any("out of range" in m for m in problems))

    def test_deterministic_result(self):
        d = E.get_evaluation("agent-output-quality")
        scores = {c.id: 3 for c in d.criteria}
        self.assertEqual(E.evaluate(d, scores).to_dict(),
                         E.evaluate(d, scores).to_dict())


if __name__ == "__main__":
    unittest.main()
