from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import NoteRecord


class InputError(ValueError):
    """Raised only for an unreadable input path, not for an individual note."""


def _text_from_record(record: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    for key in ("text", "note", "note_text", "consult_note", "body"):
        value = record.get(key)
        if isinstance(value, str):
            return value, ()
    return None, ("missing_note_text",)


def _record_from_json(record: Any, position: int) -> NoteRecord:
    if not isinstance(record, dict):
        return NoteRecord(f"line-{position}", str(record) if record is not None else "", position, input_quality=("json_record_not_object",))
    text, quality = _text_from_record(record)
    note_id = record.get("note_id", record.get("id", record.get("encounter_id", f"line-{position}")))
    if not isinstance(note_id, str) or not note_id.strip():
        note_id = f"line-{position}"
        quality = quality + ("invalid_note_id",)
    encounter_date = record.get("encounter_date", record.get("date"))
    if encounter_date is not None and not isinstance(encounter_date, str):
        encounter_date = str(encounter_date)
        quality = quality + ("coerced_encounter_date",)
    return NoteRecord(
        note_id.strip(),
        text or "",
        position,
        encounter_date,
        record,
        quality,
    )


def read_notes(path: str | Path) -> tuple[NoteRecord, ...]:
    file_path = Path(path)
    try:
        content = file_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise InputError(f"input file not found: {file_path}") from exc
    except OSError as exc:
        raise InputError(f"cannot read input file {file_path}: {exc}") from exc

    stripped = content.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # A file that looks like JSON but is not valid is handled line by
            # line below, preserving every line for an explicit refusal.
            pass
        else:
            if isinstance(parsed, dict) and isinstance(parsed.get("notes"), list):
                parsed = parsed["notes"]
            if isinstance(parsed, list):
                return tuple(_record_from_json(item, index) for index, item in enumerate(parsed, 1))
            return (_record_from_json(parsed, 1),)

    records: list[NoteRecord] = []
    for position, line in enumerate(content.splitlines(), 1):
        if not line.strip():
            records.append(NoteRecord(f"line-{position}", "", position, input_quality=("blank_line",)))
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            records.append(NoteRecord(f"line-{position}", line, position, input_quality=("plain_text",)))
        else:
            records.append(_record_from_json(parsed, position))
    if not records and content == "":
        records.append(NoteRecord("line-1", "", 1, input_quality=("empty_file",)))
    return tuple(records)


def write_jsonl(records: Iterable[dict[str, Any]], output: str | Path | None = None) -> None:
    lines = [json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records]
    rendered = "\n".join(lines) + ("\n" if lines else "")
    if output is None or str(output) == "-":
        print(rendered, end="")
        return
    Path(output).write_text(rendered, encoding="utf-8")
