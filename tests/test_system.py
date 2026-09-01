from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.corpus import CorpusError, load_corpus
from app.engine import CodingEngine
from app.evaluate import evaluate
from app.io import read_notes
from app.text import extract_facts


ROOT = Path(__file__).resolve().parents[1]


def engine() -> CodingEngine:
    return CodingEngine(load_corpus(ROOT / "data/icd_catalog.json", ROOT / "data/guideline_snippets.json"))


class CorpusTests(unittest.TestCase):
    def test_catalogue_and_active_guideline_lifecycle(self) -> None:
        corpus = engine().corpus
        self.assertEqual(len(corpus.catalogue), 404)
        self.assertEqual(len(corpus.guidelines), 45)
        active = {item.id for item in corpus.active_guidelines()}
        self.assertNotIn("GDL-041", active)
        self.assertNotIn("GDL-045", active)
        self.assertNotIn("GDL-017", active)
        self.assertIn("GDL-016", active)

    def test_external_collision_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extra.json"
            path.write_text(json.dumps([{"code": "FA31", "title": "Wrong", "chapter": "x", "synonyms": []}]), encoding="utf-8")
            with self.assertRaises(CorpusError):
                load_corpus(ROOT / "data/icd_catalog.json", ROOT / "data/guideline_snippets.json", extra_catalogue_paths=(path,))


class FactTests(unittest.TestCase):
    def test_assertion_and_numeric_thresholds(self) -> None:
        store = extract_facts("No fever. Possible pneumonia. BP 98/60, RR 24. History of asthma.")
        self.assertTrue(store.absent("fever"))
        self.assertTrue(store.matching("pneumonia", assertion="possible"))
        self.assertEqual(store.value("systolic_bp")["value"], 98)
        self.assertEqual(store.value("respiratory_rate")["value"], 24)
        self.assertTrue(store.matching("asthma", assertion="historical"))

    def test_overlapping_concepts_are_retained(self) -> None:
        store = extract_facts("The patient has wheeze and respiratory compromise.")
        self.assertTrue(store.positive("wheeze"))
        self.assertTrue(store.positive("respiratory_compromise"))


class DecisionTests(unittest.TestCase):
    def test_smoke_assignments_and_refusals(self) -> None:
        coding = engine()
        notes = read_notes(ROOT / "tests/fixtures/smoke_notes.jsonl")
        output = {item.note.note_id: item.as_dict() for item in (coding.process(note) for note in notes)}
        self.assertEqual(output["costochondritis-1"]["assignments"][0]["code"], "FA31")
        self.assertEqual(output["pneumonia-1"]["assignments"][0]["code"], "CA22")
        self.assertEqual(output["pneumonia-old-rule"]["status"], "provisional")
        self.assertNotEqual(output["injection-trap"]["assignments"][0]["code"] if output["injection-trap"]["assignments"] else None, "BA41")
        self.assertEqual(output["unknown-1"]["status"], "unresolved")
        self.assertEqual(output["blank-1"]["status"], "unresolved")

    def test_every_input_record_is_emitted(self) -> None:
        notes = read_notes(ROOT / "tests/fixtures/smoke_notes.jsonl")
        outputs = [engine().process(note).as_dict() for note in notes]
        self.assertEqual([record["input_position"] for record in outputs], list(range(1, len(notes) + 1)))

    def test_unseen_holdout_regression(self) -> None:
        report = evaluate(ROOT / "benchmark/unseen_notes.jsonl", ROOT / "benchmark/unseen_expected.json")
        self.assertEqual(report["notes"], 35)
        self.assertEqual(report["exact_code_accuracy"], 1.0)
        self.assertEqual(report["accounted_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

