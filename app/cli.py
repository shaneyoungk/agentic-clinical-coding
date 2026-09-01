from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .corpus import CorpusError, load_corpus
from .engine import CodingEngine
from .io import InputError, read_notes, write_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline-first evidence-constrained ICD coding")
    parser.add_argument("input", help="JSON, JSONL, or plain-text note file")
    parser.add_argument("--output", default="-", help="JSONL output path, or - for stdout")
    parser.add_argument("--catalogue", default="data/icd_catalog.json")
    parser.add_argument("--guidelines", default="data/guideline_snippets.json")
    parser.add_argument("--extra-catalogue", action="append", default=[], help="separate additive catalogue JSON file")
    parser.add_argument("--extra-guidelines", action="append", default=[], help="separate additive guideline JSON file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        corpus = load_corpus(
            args.catalogue,
            args.guidelines,
            extra_catalogue_paths=tuple(args.extra_catalogue),
            extra_guideline_paths=tuple(args.extra_guidelines),
        )
        notes = read_notes(args.input)
    except (CorpusError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    engine = CodingEngine(corpus)
    write_jsonl((engine.process(note).as_dict() for note in notes), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

