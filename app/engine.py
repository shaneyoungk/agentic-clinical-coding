from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .corpus import Corpus
from .models import CodingResult, NoteRecord
from .policy import CodingPolicy
from .retrieval import retrieve_codes, retrieve_guidelines
from .text import extract_facts


@dataclass
class CodingEngine:
    corpus: Corpus

    def process(self, note: NoteRecord) -> CodingResult:
        facts = extract_facts(note.text)
        decision = CodingPolicy(self.corpus).run(facts)
        assignments = [candidate for problem in decision.problems for candidate in problem.assignments]
        unresolved = [reason for problem in decision.problems for reason in problem.unresolved_reasons]
        missing = sorted({item for problem in decision.problems for item in problem.missing_information})
        safety = sorted({item for problem in decision.problems for item in problem.safety_flags})
        if not assignments:
            status = "unresolved"
            confidence = "low"
        elif any(problem.status == "review" for problem in decision.problems):
            status = "review"
            confidence = "moderate"
        elif any(problem.status == "provisional" for problem in decision.problems):
            status = "provisional"
            confidence = "moderate"
        else:
            status = "accepted"
            confidence = "high" if all(candidate.confidence == "high" for candidate in assignments) else "moderate"
        raising = [candidate.support for candidate in assignments]
        lowering = list(missing) + list(unresolved) + list(note.input_quality) + list(facts.warnings)
        if not assignments:
            lowering.append("no safe assignment satisfied the evidence-constrained policy")
        trace: dict[str, Any] = {
            "corpus": {
                "catalogue_records": len(self.corpus.catalogue),
                "guideline_records": len(self.corpus.guidelines),
                "active_guideline_ids": [item.id for item in self.corpus.active_guidelines()],
                "guideline_lifecycle": self.corpus.guideline_lifecycle(),
                "sha256": self.corpus.hashes,
            },
            "retrieval": {
                "codes": [
                    {"code": hit.item.code, "score": round(hit.score, 4), "matched_terms": list(hit.matched_terms)}
                    for hit in retrieve_codes(self.corpus, note.text)
                ],
                "guidelines": [
                    {"id": hit.item.id, "score": round(hit.score, 4), "matched_terms": list(hit.matched_terms)}
                    for hit in retrieve_guidelines(self.corpus, note.text)
                ],
            },
            "facts": [fact.as_dict() for fact in facts.facts],
            "policy": decision.trace,
        }
        return CodingResult(
            note=note,
            status=status,
            confidence=confidence,
            confidence_factors={"raises": raising, "lowers": lowering},
            problems=list(decision.problems),
            missing_information=missing,
            unresolved_reasons=sorted(set(unresolved)),
            safety_flags=safety,
            trace=trace,
        )

