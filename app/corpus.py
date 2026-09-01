from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import CodeEntry, Guideline


class CorpusError(ValueError):
    """Raised when the coding corpus cannot be safely loaded."""


@dataclass(frozen=True)
class Corpus:
    catalogue: tuple[CodeEntry, ...]
    guidelines: tuple[Guideline, ...]
    hashes: dict[str, str]
    catalogue_version: str = "provided"

    @property
    def code_by_code(self) -> dict[str, CodeEntry]:
        return {entry.code: entry for entry in self.catalogue}

    @property
    def guideline_by_id(self) -> dict[str, Guideline]:
        return {guideline.id: guideline for guideline in self.guidelines}

    def active_guidelines(self, as_of: str | None = None) -> tuple[Guideline, ...]:
        """Return current trusted guidance, applying explicit lifecycle signals.

        The supplied snippets do not carry a formal supersession field. We
        therefore derive an explainable replacement relationship from prose:
        a newer trusted record that explicitly says it replaces or supersedes
        an older record with the same source/topic signature makes the older
        record historical. This is deliberately corpus-generic; no guideline
        identifier, diagnosis code or disease name is special-cased here.
        """
        eligible, replacements = self._guideline_lifecycle(as_of)
        return tuple(item for item in eligible if item.id not in replacements)

    def guideline_lifecycle(self, as_of: str | None = None) -> list[dict[str, object]]:
        """Explain why every guideline is or is not decision-active."""
        as_of_key = _date_key(as_of) if as_of else None
        _, replacements = self._guideline_lifecycle(as_of)
        decisions: list[dict[str, object]] = []
        for item in self.guidelines:
            reasons: list[str] = []
            if item.status != "active":
                reasons.append(f"status={item.status}")
            if item.trust != "normal":
                reasons.append(f"trust={item.trust}")
            if as_of_key is not None and item.effective_key > as_of_key:
                reasons.append(f"effective_after_as_of={as_of}")
            if item.id in replacements:
                reasons.append("superseded_by_newer_guidance")
            decisions.append({
                "id": item.id,
                "effective": item.effective,
                "status": item.status,
                "trust": item.trust,
                "included": not reasons,
                "reasons": reasons or ["active_trusted_current"],
            })
        return decisions

    def _guideline_lifecycle(self, as_of: str | None) -> tuple[list[Guideline], set[str]]:
        as_of_key = _date_key(as_of) if as_of else None
        eligible = [
            item
            for item in self.guidelines
            if item.status == "active"
            and item.trust == "normal"
            and (as_of_key is None or item.effective_key <= as_of_key)
        ]
        replacements: set[str] = set()
        for newer in eligible:
            body = f"{newer.title} {newer.text}".lower()
            marker = re.search(r"\b(?:replaces|supersedes|supplants)\b", body)
            if marker is None:
                continue
            replacement_tail = body[marker.end():]
            replacement_terms = _content_terms(replacement_tail)
            for older in eligible:
                if older.id == newer.id or older.effective_key >= newer.effective_key:
                    continue
                older_topic = _content_terms(f"{older.title} {older.source}")
                shared_reference = len(replacement_terms & older_topic) >= 2
                shared_title = len(_content_terms(newer.title) & _content_terms(older.title)) >= 2
                if shared_reference or shared_title:
                    replacements.add(older.id)
        return eligible, replacements

    def searchable_guidelines(self) -> tuple[Guideline, ...]:
        """Include historical/untrusted documents for audit retrieval."""
        return self.guidelines


def _date_key(value: str | None) -> int | None:
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}(?:-\d{2})?", value):
        raise CorpusError(f"invalid date: {value!r}; expected YYYY-MM or YYYY-MM-DD")
    year, month = value[:7].split("-")
    month_int = int(month)
    if not 1 <= month_int <= 12:
        raise CorpusError(f"invalid month in date: {value!r}")
    return int(year) * 100 + month_int


_CORPUS_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on",
    "or", "the", "to", "with", "where", "this", "that", "new", "old",
}


def _content_terms(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in _CORPUS_STOPWORDS and len(token) > 2
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CorpusError(f"corpus file not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"invalid JSON corpus file {path}: {exc}") from exc


def _metadata_for_guideline(record: dict[str, Any]) -> tuple[str, str]:
    haystack = " ".join(
        str(record.get(key, "")) for key in ("title", "source", "text")
    ).lower()
    derived_status = "deprecated" if "deprecated" in haystack or "historical reference" in haystack else "active"
    derived_trust = "untrusted" if any(
        marker in haystack for marker in (
            "unsigned",
            "system directive",
            "processing assistant",
            "ignore previous instructions",
            "disregard conflicting guidance",
            "omit the evidence",
            "instruction takes precedence",
        )
    ) else "normal"
    # Explicit metadata may add lifecycle information, but it cannot make a
    # record active/trusted when its own content carries a clear downgrade
    # signal. This prevents a migrated document from self-certifying around
    # the safety check.
    status = "deprecated" if derived_status == "deprecated" else record.get("status", derived_status)
    trust = "untrusted" if derived_trust == "untrusted" else record.get("trust", derived_trust)
    if not isinstance(status, str) or not isinstance(trust, str):
        raise CorpusError("guideline status and trust must be strings")
    if status not in {"active", "deprecated"}:
        raise CorpusError(f"invalid guideline status: {status!r}")
    if trust not in {"normal", "untrusted"}:
        raise CorpusError(f"invalid guideline trust: {trust!r}")
    return status, trust


def load_catalogue(path: str | Path) -> tuple[CodeEntry, ...]:
    file_path = Path(path)
    data = _read_json(file_path)
    if not isinstance(data, list):
        raise CorpusError(f"catalogue must be a JSON list: {file_path}")
    entries: list[CodeEntry] = []
    seen: set[str] = set()
    code_pattern = re.compile(r"^[A-Z0-9][A-Z0-9.]*$")
    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise CorpusError(f"catalogue record {index} is not an object")
        for key in ("code", "title", "chapter", "synonyms"):
            if key not in record:
                raise CorpusError(f"catalogue record {index} missing {key!r}")
        code = record["code"]
        title = record["title"]
        chapter = record["chapter"]
        synonyms = record["synonyms"]
        if not isinstance(code, str) or not code_pattern.fullmatch(code):
            raise CorpusError(f"invalid catalogue code at record {index}: {code!r}")
        if code in seen:
            raise CorpusError(f"duplicate catalogue code: {code}")
        if not isinstance(title, str) or not title.strip() or not isinstance(chapter, str):
            raise CorpusError(f"invalid title/chapter at catalogue record {index}")
        if not isinstance(synonyms, list) or any(not isinstance(item, str) for item in synonyms):
            raise CorpusError(f"invalid synonyms at catalogue record {index}")
        code_system = record.get("code_system", "local-exercise-catalogue")
        version = record.get("version", "provided")
        if not isinstance(code_system, str) or not code_system.strip():
            raise CorpusError(f"invalid code_system at catalogue record {index}")
        if not isinstance(version, str) or not version.strip():
            raise CorpusError(f"invalid version at catalogue record {index}")
        seen.add(code)
        entries.append(CodeEntry(
            code,
            title.strip(),
            chapter.strip(),
            tuple(s.strip() for s in synonyms if s.strip()),
            code_system.strip(),
            version.strip(),
        ))
    return tuple(entries)


def load_guidelines(path: str | Path) -> tuple[Guideline, ...]:
    file_path = Path(path)
    data = _read_json(file_path)
    if not isinstance(data, list):
        raise CorpusError(f"guidelines must be a JSON list: {file_path}")
    guidelines: list[Guideline] = []
    seen: set[str] = set()
    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise CorpusError(f"guideline record {index} is not an object")
        for key in ("id", "title", "source", "effective", "text"):
            if key not in record:
                raise CorpusError(f"guideline record {index} missing {key!r}")
        identifier = record["id"]
        if not isinstance(identifier, str) or not identifier.strip():
            raise CorpusError(f"invalid or duplicate guideline ID: {identifier!r}")
        identifier = identifier.strip()
        if identifier in seen:
            raise CorpusError(f"invalid or duplicate guideline ID: {identifier!r}")
        if not all(isinstance(record[key], str) and record[key].strip() for key in ("title", "source", "text")):
            raise CorpusError(f"invalid guideline text metadata at record {index}")
        effective = record["effective"]
        _date_key(effective)
        status, trust = _metadata_for_guideline(record)
        seen.add(identifier)
        guidelines.append(Guideline(
            id=identifier,
            title=record["title"].strip(),
            source=record["source"].strip(),
            effective=effective,
            text=record["text"].strip(),
            status=status,
            trust=trust,
        ))
    return tuple(guidelines)


def load_corpus(
    catalogue_path: str | Path,
    guideline_path: str | Path,
    *,
    extra_catalogue_paths: tuple[str | Path, ...] = (),
    extra_guideline_paths: tuple[str | Path, ...] = (),
) -> Corpus:
    catalogue = list(load_catalogue(catalogue_path))
    guidelines = list(load_guidelines(guideline_path))
    seen_codes = {item.code for item in catalogue}
    for extra_path in extra_catalogue_paths:
        for item in load_catalogue(extra_path):
            if item.code in seen_codes:
                existing = next(entry for entry in catalogue if entry.code == item.code)
                if (existing.title, existing.chapter) != (item.title, item.chapter):
                    raise CorpusError(f"external code collision for {item.code}")
                continue
            catalogue.append(item)
            seen_codes.add(item.code)
    seen_ids = {item.id for item in guidelines}
    for extra_path in extra_guideline_paths:
        for item in load_guidelines(extra_path):
            if item.id in seen_ids:
                raise CorpusError(f"external guideline collision for {item.id}")
            guidelines.append(item)
            seen_ids.add(item.id)
    paths = [Path(catalogue_path), Path(guideline_path)] + [Path(p) for p in extra_catalogue_paths + extra_guideline_paths]
    return Corpus(
        catalogue=tuple(catalogue),
        guidelines=tuple(guidelines),
        hashes={str(path): _sha256(path) for path in paths},
    )
