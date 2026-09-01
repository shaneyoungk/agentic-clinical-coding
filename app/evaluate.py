from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .corpus import load_corpus
from .engine import CodingEngine
from .io import read_notes


def evaluate(notes_path: str | Path, expected_path: str | Path) -> dict[str, Any]:
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))
    expected = expected.get("notes", expected)
    notes = read_notes(notes_path)
    root = Path(__file__).resolve().parents[1]
    engine = CodingEngine(load_corpus(root / "data/icd_catalog.json", root / "data/guideline_snippets.json"))
    rows: list[dict[str, Any]] = []
    exact = 0
    accounted = 0
    for note in notes:
        result = engine.process(note).as_dict()
        actual_codes = sorted(item["code"] for item in result["assignments"])
        target = expected.get(note.note_id, {})
        target_codes = sorted(target.get("codes", []))
        code_match = actual_codes == target_codes
        if code_match:
            exact += 1
        if result["status"] in {"accepted", "provisional", "review", "unresolved"}:
            accounted += 1
        rows.append({"note_id": note.note_id, "expected_codes": target_codes, "actual_codes": actual_codes, "code_match": code_match, "status": result["status"]})
    total = len(notes)
    return {
        "notes": total,
        "exact_code_accuracy": round(exact / total, 4) if total else 1.0,
        "accounted_rate": round(accounted / total, 4) if total else 1.0,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local deterministic coding benchmark")
    parser.add_argument("--notes", default="benchmark/notes.jsonl")
    parser.add_argument("--expected", default="benchmark/expected.json")
    args = parser.parse_args(argv)
    print(json.dumps(evaluate(args.notes, args.expected), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

