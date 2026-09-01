# Evidence-constrained clinical coding

This is an offline-first Python 3.12+ coding assistant. It reads the supplied
404-entry catalogue and 45 guideline snippets, extracts asserted patient facts,
retrieves relevant records for audit, and applies evidence-constrained
predicates. Every input record produces one JSONL result. A result can be an
accepted assignment, a provisional/review assignment, or an explicit
unresolved refusal; unsupported findings are never force-fit to the nearest
code.

Run locally:

```text
python -m app.cli path/to/notes.jsonl --output results.jsonl
python -m app.evaluate
```

Input can be JSON, JSONL, or one plain-text note per line. Each assignment
contains the catalogue code, code-system/version, guideline ID, quoted note
evidence and confidence factors. The original `note_text` is retained in every
result, so malformed, unsupported or only-partially-understood input is still
auditable. `trace` records corpus hashes, retrieval hits, extracted facts,
guideline lifecycle decisions and policy branches. No model key is required;
an LLM adapter would be an optional future proposer whose output must pass the
same policy and evidence checks.
The output contract is documented in `schema/result.schema.json`.

## Repository map and execution flow

If you are new to the project, start with `app/cli.py`. The program follows
this path:

`CLI -> input parser -> corpus loader -> fact extraction -> retrieval -> policy
rules -> JSONL result`

The important files are:

- `app/cli.py` is the command-line entry point. It accepts the input path,
  optional corpus paths and output path, loads the engine, and writes one JSON
  result per input note.
- `app/__main__.py` makes `python -m app ...` an equivalent shorter entry
  point. `python -m app.cli ...` is also supported.
- `app/io.py` reads JSON, JSONL and plain-text input. It accepts common text
  field names (`text`, `note`, `note_text`, `consult_note`, `body`), assigns a
  stable fallback ID, and preserves malformed or blank records as explicit
  unresolved records so they cannot disappear silently.
- `app/corpus.py` validates the catalogue and guideline JSON, preserves
  code-system/version metadata, rejects duplicate or conflicting additions,
  computes SHA-256 provenance hashes, and applies lifecycle rules. It excludes
  deprecated/untrusted guidance and applies the newer pneumonia supersession
  relationship; the trace explains each inclusion/exclusion decision.
- `app/models.py` contains the typed data objects shared by every layer:
  catalogue codes, guidelines, notes, extracted facts, evidence, candidates,
  problems and final coding results.
- `app/text.py` is the deterministic clinical fact extractor. It normalizes
  spelling and punctuation, recognizes clinical aliases, numbers and units,
  and marks facts as present, absent, possible, conditional, historical or
  family history. It is deliberately a fact layer, not a code lookup table.
- `app/retrieval.py` provides a small dependency-free lexical retriever over
  catalogue titles/synonyms and active guidelines. Its hits are for relevance
  and audit traceability; retrieval alone never assigns a diagnosis.
- `app/policy.py` is the safety-critical decision layer. It checks definitions,
  exclusions, age/time/measurement thresholds, confirmation requirements,
  competing candidates and catalogue gaps. It creates evidence-backed
  candidates or a refusal. It uses semantic catalogue titles and guideline
  content rather than executing note text or trusting a guideline ID.
- `app/engine.py` orchestrates one note through extraction, policy and
  retrieval, then calculates overall status/confidence and assembles the full
  trace (facts, evidence, corpus hashes and policy branches).
- `app/evaluate.py` runs the local benchmark in `benchmark/` and reports exact
  code-set accuracy and record-accounting rate. It is a lightweight tbench-like
  regression command with no third-party dependencies.
- `data/icd_catalog.json` and `data/guideline_snippets.json` are the supplied
  source inputs. `data/additions/` contains the separately sourced WHO
  necrotising-fasciitis code and malaria diagnostic guidance, with provenance
  notes. They are opt-in and can be passed with `--extra-catalogue` or
  `--extra-guidelines`, so the supplied-corpus benchmark remains unchanged.
- `benchmark/notes.jsonl` contains readable local benchmark notes and
  `benchmark/expected.json` contains their expected code sets. These are
  development checks, not training data.
- `benchmark/unseen_notes.jsonl` and `benchmark/unseen_expected.json` are a
  separate 35-note holdout-style suite with paraphrases and adversarial edge
  cases. Run it with:

  `python -m app.evaluate --notes benchmark/unseen_notes.jsonl --expected benchmark/unseen_expected.json`
- `tests/test_system.py` covers corpus loading, lifecycle, input accounting
  and smoke assignments. `tests/test_edge_cases.py` covers negation/history
  scope, prompt injection, missing catalogue conditions, incomplete
  thresholds, provenance and malformed input. Run both with the command below.
- `schema/result.schema.json` documents the versioned JSON output contract.
- `Dockerfile` and `compose.yaml` provide the clean-clone container workflow;
  `examples/smoke_notes.jsonl` is the default input for `docker compose up`.
- `reasoning.md` is the candidate's private design record. It is intentionally
  ignored by Git at the user's request and is not required at runtime.

For a quick beginner walkthrough, run `python -m app.cli examples/smoke_notes.jsonl`.
The first two records receive evidence-backed
assignments; the third demonstrates an unresolved result. Open one JSON line
and inspect `assignments` for proposed codes, `problems` for candidates and
missing information, and `trace` for how the decision was made. Then run
`python -m unittest discover -s tests -v` and `python -m app.evaluate` to
verify the installation.

`docker compose up` builds and runs the included smoke file. To run a supplied
file in the container from PowerShell, use
`docker compose run --rm -v "${PWD}:/input:ro" coder /input/notes.jsonl`.

## Data decisions

The data audit found 404 unique catalogue codes and 45 dated snippets, with no
provided guideline-to-code map. The active pneumonia revision supersedes the
older clinical-only rule; deprecated and unsigned/imported guidance is excluded
from decision retrieval, while every exclusion is explained in the trace. The
imported chest-pain snippet contains a prompt-injection directive and is
treated as untrusted data, not executable instruction. Definitions, negatives,
age bands, time windows, confirmation requirements and competing candidates are
implemented as predicates. Missing catalogue coverage (for example giant-cell
arteritis and acute chest syndrome) produces a coded refusal and safety flag.

I added `1B71 Necrotising fasciitis` as an opt-in catalogue extension after
verifying the code/title in the WHO ICD-11 Reference Guide; the gap matters
because the supplied cellulitis entry must not absorb a necrotising emergency.
I also added a short, separately sourced paraphrase of WHO malaria diagnostic
testing guidance. Both additions are documented in `data/additions/`, carry
source/version metadata, are hashed at runtime and remain subject to the same
policy checks. The default run intentionally preserves the supplied ontology;
the additions are enabled explicitly with the CLI flags.

The deterministic rules should generalise to paraphrased notes when the same
clinical facts are documented. They are not a replacement for clinician/coder
review, cannot infer absent tests, and do not attempt all 50,000 ICD-11
entities. At that scale the linear catalogue scan should become an indexed
terminology service with versioned embeddings/synonyms, while policy validation,
provenance, calibration and refusal behavior remain unchanged.

The local benchmark in `benchmark/` covers 33 positive, provisional, complication,
threshold, conflict and refusal cases; the tests also check malformed/blank
records, assertion scope, catalogue collisions and guideline lifecycle. With
another day I would add adjudicated unseen-note evaluation, a terminology
server adapter, calibrated selective-risk curves, richer section/temporal
parsing, and a clinician review queue.

Tooling: Codex was used to inspect the corpus, implement the system and drive
the tests. One generated implementation initially selected `Whooping cough`
for the generic symptom `cough` because of substring matching; that regression
was caught by the smoke benchmark and fixed with exact-title/shortest-match
ranking plus tests.
