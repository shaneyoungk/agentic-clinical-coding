from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .corpus import Corpus
from .models import CodeEntry, Guideline
from .text import normalize_for_search


@dataclass(frozen=True)
class RetrievalHit:
    item: CodeEntry | Guideline
    score: float
    matched_terms: tuple[str, ...]


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize_for_search(value))


def _idf(documents: list[list[str]]) -> dict[str, float]:
    count = Counter(token for document in documents for token in set(document))
    total = len(documents)
    return {term: math.log((total + 1) / (frequency + 1)) + 1.0 for term, frequency in count.items()}


def _score(query: list[str], document: list[str], idf: dict[str, float]) -> tuple[float, tuple[str, ...]]:
    if not query or not document:
        return 0.0, ()
    counts = Counter(document)
    length_norm = 0.5 + 0.5 * len(document) / max(len(document), 80)
    matched = sorted(set(query) & set(document))
    score = sum(idf.get(term, 1.0) * (1.0 + math.log(counts[term])) for term in matched) / length_norm
    return score, tuple(matched)


def retrieve_codes(corpus: Corpus, note_text: str, limit: int = 12) -> tuple[RetrievalHit, ...]:
    query = _tokens(note_text)
    documents = [_tokens(f"{entry.title} {' '.join(entry.synonyms)} {entry.chapter}") for entry in corpus.catalogue]
    idf = _idf(documents)
    hits: list[RetrievalHit] = []
    for entry, document in zip(corpus.catalogue, documents):
        score, terms = _score(query, document, idf)
        if score:
            hits.append(RetrievalHit(entry, score, terms))
    return tuple(sorted(hits, key=lambda hit: (-hit.score, getattr(hit.item, "code", "")))[:limit])


def retrieve_guidelines(corpus: Corpus, note_text: str, limit: int = 8) -> tuple[RetrievalHit, ...]:
    query = _tokens(note_text)
    active = corpus.active_guidelines()
    documents = [_tokens(f"{item.title} {item.text}") for item in active]
    idf = _idf(documents)
    hits: list[RetrievalHit] = []
    for guideline, document in zip(active, documents):
        score, terms = _score(query, document, idf)
        if score:
            hits.append(RetrievalHit(guideline, score, terms))
    return tuple(sorted(hits, key=lambda hit: (-hit.score, getattr(hit.item, "id", "")))[:limit])

