from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Assertion = Literal[
    "present", "absent", "possible", "conditional", "historical", "family_history"
]


@dataclass(frozen=True)
class CodeEntry:
    code: str
    title: str
    chapter: str
    synonyms: tuple[str, ...] = ()
    code_system: str = "local-exercise-catalogue"
    version: str = "provided"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code_system": self.code_system,
            "catalogue_version": self.version,
            "code": self.code,
            "title": self.title,
            "chapter": self.chapter,
            "synonyms": list(self.synonyms),
        }


@dataclass(frozen=True)
class Guideline:
    id: str
    title: str
    source: str
    effective: str
    text: str
    status: str = "active"
    trust: str = "normal"

    @property
    def effective_key(self) -> int:
        year, month = self.effective.split("-", 1)
        return int(year) * 100 + int(month)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "effective": self.effective,
            "text": self.text,
            "status": self.status,
            "trust": self.trust,
        }


@dataclass(frozen=True)
class NoteRecord:
    note_id: str
    text: str
    position: int
    encounter_date: str | None = None
    raw: dict[str, Any] | None = None
    input_quality: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    kind: Literal["note", "catalogue", "guideline", "system"]
    reference: str | None = None
    quote: str | None = None
    span: tuple[int, int] | None = None
    role: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        if self.reference is not None:
            result["reference"] = self.reference
        if self.quote is not None:
            result["quote"] = self.quote
        if self.span is not None:
            result["span"] = list(self.span)
        if self.role is not None:
            result["role"] = self.role
        return result


@dataclass(frozen=True)
class Fact:
    concept: str
    value: Any = True
    assertion: Assertion = "present"
    temporality: str = "current"
    experiencer: str = "patient"
    start: int = 0
    end: int = 0
    quote: str = ""
    source: str = "deterministic"
    confidence: str = "moderate"
    problem_hint: str | None = None

    @property
    def is_current_patient(self) -> bool:
        return self.experiencer == "patient" and self.temporality == "current"

    @property
    def is_positive(self) -> bool:
        return self.assertion == "present" and self.is_current_patient

    def as_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "value": self.value,
            "assertion": self.assertion,
            "temporality": self.temporality,
            "experiencer": self.experiencer,
            "span": [self.start, self.end],
            "quote": self.quote,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class FactStore:
    text: str
    normalized: str
    facts: list[Fact] = field(default_factory=list)
    material_spans: list[tuple[int, int, str, str]] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, fact: Fact) -> None:
        # Repeated copy-forward facts are retained in the list for audit, while
        # query helpers deduplicate them by concept/value/assertion.
        self.facts.append(fact)

    def matching(self, concept: str, *, assertion: Assertion | None = None) -> list[Fact]:
        return [
            fact
            for fact in self.facts
            if fact.concept == concept and (assertion is None or fact.assertion == assertion)
        ]

    def positive(self, concept: str) -> list[Fact]:
        return [fact for fact in self.matching(concept) if fact.is_positive]

    def absent(self, concept: str) -> list[Fact]:
        return [
            fact
            for fact in self.matching(concept, assertion="absent")
            if fact.experiencer == "patient" and fact.temporality == "current"
        ]

    def any_positive(self, *concepts: str) -> bool:
        return any(self.positive(concept) for concept in concepts)

    def first_positive(self, *concepts: str) -> Fact | None:
        for concept in concepts:
            values = self.positive(concept)
            if values:
                return values[0]
        return None

    def value(self, concept: str) -> Any | None:
        values = [fact.value for fact in self.positive(concept) if fact.value is not True]
        return values[0] if values else None

    def has_contradiction(self, concept: str) -> bool:
        return bool(self.positive(concept) and self.absent(concept))


@dataclass(frozen=True)
class Candidate:
    code: CodeEntry
    guideline: Guideline
    score: float
    support: str
    confidence: str
    evidence: tuple[Evidence, ...] = ()
    missing: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    safety_flags: tuple[str, ...] = ()
    role: str = "primary"
    problem: str = "encounter"
    provisional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.code,
            "title": self.code.title,
            "guideline_id": self.guideline.id,
            "role": self.role,
            "provisional": self.provisional,
            "score": round(self.score, 3),
            "confidence": self.confidence,
            "support": self.support,
            "missing_information": list(self.missing),
            "blockers": list(self.blockers),
            "evidence": [item.as_dict() for item in self.evidence],
        }


@dataclass
class ProblemResult:
    problem_id: str
    span: tuple[int, int] | None
    status: str
    assignments: list[Candidate] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    unresolved_reasons: list[str] = field(default_factory=list)
    safety_flags: list[str] = field(default_factory=list)
    evidence_ledger: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "span": list(self.span) if self.span else None,
            "status": self.status,
            "assignments": [candidate.as_dict() for candidate in self.assignments],
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "missing_information": self.missing_information,
            "unresolved_reasons": self.unresolved_reasons,
            "safety_flags": self.safety_flags,
            "evidence_ledger": self.evidence_ledger,
        }


@dataclass
class CodingResult:
    note: NoteRecord
    status: str
    confidence: str
    confidence_factors: dict[str, list[str]]
    problems: list[ProblemResult]
    missing_information: list[str]
    unresolved_reasons: list[str]
    safety_flags: list[str]
    trace: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        assignments = [
            candidate.as_dict()
            for problem in self.problems
            for candidate in problem.assignments
        ]
        candidates = [
            candidate.as_dict()
            for problem in self.problems
            for candidate in problem.candidates
        ]
        return {
            "schema_version": "1.0",
            "note_id": self.note.note_id,
            "input_position": self.note.position,
            "input_quality": list(self.note.input_quality),
            "status": self.status,
            "confidence": self.confidence,
            "confidence_factors": self.confidence_factors,
            "assignments": assignments,
            "candidates": candidates,
            "problems": [problem.as_dict() for problem in self.problems],
            "missing_information": self.missing_information,
            "unresolved_reasons": self.unresolved_reasons,
            "safety_flags": self.safety_flags,
            "trace": self.trace,
        }
