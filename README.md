# Evidence-constrained clinical coding

This is an offline-first Python 3.12+ coding assistant. It reads the supplied
404-entry catalogue and 45 guideline snippets, extracts asserted patient facts,
retrieves relevant records for audit, and applies evidence-constrained
predicates. Every input record produces one JSONL result. A result can be an
accepted assignment, a provisional/review assignment, or an explicit
unresolved refusal; unsupported findings are never force-fit to the nearest
code.

## Run it from a clean clone

Run the commands below from the repository root, the folder containing
`BRIEF.md`. The project has no runtime Python dependencies and does not need a
model key, database, or network connection. Install Python 3.12 or newer; the
implementation uses only the Python standard library. Docker Desktop is
optional and is needed only for the container commands below.

Check the Python installation with this single command:

```powershell
python --version
```

If `python` is not recognised on Windows, install Python 3.12+ with the
official installer and enable its PATH option. There is no `pip install`
step for this repository.

### Run the included smoke example

This runs three readable example notes and prints one compact JSON result per
input record to the terminal:

```powershell
python -m app.cli examples/smoke_notes.jsonl
```

The first two examples receive evidence-backed assignments and the third is
an intentional unresolved/refusal case. The same command works through the
shorter module entry point:

```powershell
python -m app examples/smoke_notes.jsonl
```

To save the smoke results instead, use this single command:

```powershell
python -m app.cli examples/smoke_notes.jsonl --output smoke_results.jsonl
```

`smoke_results.jsonl` is written to the current directory (normally the
repository root). The output file is JSONL: each line is one complete result,
not one combined JSON array. Read the saved lines in PowerShell with:

```powershell
Get-Content .\smoke_results.jsonl
```

To display the most useful fields from every saved line in PowerShell, run:

```powershell
Get-Content .\smoke_results.jsonl | ForEach-Object { $_ | ConvertFrom-Json | Select-Object note_id,status,confidence,assignments,missing_information }
```

If `--output` is omitted, results go to standard output and no result file is
created. If `--output path` is supplied, the parent folder must already exist.

### Run all automated tests

This is the one-command local test suite:

```powershell
python -m unittest discover -s tests -v
```

It runs `tests/test_system.py`, `tests/test_edge_cases.py`, and
`tests/test_brief_requirements.py`. The tests cover normal assignments,
negation and history scope, missing catalogue entries, unsafe corpus content,
thresholds, input accounting, provenance, lifecycle filtering, paraphrases,
and refusal/safety behavior.

### Run the main benchmark

Run the 33-note development benchmark with:

```powershell
python -m app.evaluate
```

This reads `benchmark/notes.jsonl` and grades it against
`benchmark/expected.json`. The command prints a JSON report in the terminal.
The important fields are:

- `exact_code_accuracy`: the proportion of notes whose sorted assigned code
  list exactly equals the expected code list. An expected empty list means the
  correct behavior is an explicit unresolved result.
- `accounted_rate`: the proportion of input notes that produced one of the
  allowed statuses: `accepted`, `provisional`, `review`, or `unresolved`.
- `rows`: note-by-note expected codes, actual codes, match status, and result
  status for diagnosing failures.

The benchmark data is local development data, not training data. It is not
used to alter the system at runtime.

To save the benchmark report as a JSON file in the repository root instead of
printing it only in the terminal, run:

```powershell
python -m app.evaluate | Out-File -FilePath benchmark_report.json -Encoding utf8
```

Read that report with:

```powershell
Get-Content .\benchmark_report.json
```

### Run the paraphrase and adversarial holdout

Run the separate 35-note holdout-style suite with:

```powershell
python -m app.evaluate --notes benchmark/unseen_notes.jsonl --expected benchmark/unseen_expected.json
```

Its notes and expected answers are stored in the two `benchmark/unseen_*`
files. It is a local regression check for paraphrases, incomplete evidence,
catalogue gaps, and competing diagnoses; the private evaluator described in
`BRIEF.md` remains the real unseen-note evaluation.

### Run your own input file

Point the positional input argument at any JSON, JSONL, or plain-text file:

```powershell
python -m app.cli path\to\your_notes.jsonl --output results.jsonl
```

The input path is never hard-coded. Supported forms are:

- JSONL: one object per line, normally `{"note_id":"case-1","text":"..."}`.
- JSON array: a file containing several note objects.
- JSON object containing a `notes` array.
- Plain text: one note per line.

For JSON objects, the text can be in `text`, `note`, `note_text`,
`consult_note`, or `body`. `note_id` is preferred; `id` and `encounter_id`
are also accepted. Missing IDs receive a stable line-based fallback. Blank,
malformed, or unsupported records are emitted as unresolved results with an
`input_quality` explanation rather than being dropped.

### Run with the separately sourced data additions

The default run uses exactly the supplied 404-entry catalogue and 45 supplied
guideline snippets. The separately sourced WHO additions are opt-in. Enable
both for a run with the necrotising-fasciitis catalogue entry and the malaria
diagnostic guideline:

```powershell
python -m app.cli path\to\your_notes.jsonl --extra-catalogue data\additions\icd_catalog_additions.json --extra-guidelines data\additions\guideline_additions.json --output enriched_results.jsonl
```

The addition files, provenance, sources, and reasons for keeping them separate
are documented in `data/additions/README.md`.

### Run the container

Docker Desktop is optional. From the repository root, this builds the image
and runs the default smoke input:

```powershell
docker compose up --build
```

To run a host input file in the container and save results back to the
repository root, use this single PowerShell command:

```powershell
docker compose run --rm -v "${PWD}:/input" coder /input/your_notes.jsonl --output /input/docker_results.jsonl
```

The container uses the same CLI and output contract as the native command.

### Read a result

Every output line preserves the original `note_text` and contains the same
top-level fields:

- `status`: `accepted`, `provisional`, `review`, or `unresolved`.
- `confidence`: `high`, `moderate`, or `low`.
- `assignments`: selected code(s), title, catalogue metadata, guideline ID,
  confidence, support, and note/catalogue/guideline evidence.
- `candidates`: plausible but unselected alternatives shown for review.
- `missing_information` and `unresolved_reasons`: what prevented a stronger
  decision. An unresolved result is deliberate when the catalogue is missing
  the condition or the note lacks required evidence.
- `safety_flags`: urgent review, confirmation, or do-not-force-fit warnings.
- `trace`: corpus hashes and lifecycle decisions, retrieval hits, extracted
  facts, and policy branches used to reach the result.

The versioned output contract is in `schema/result.schema.json`. The local
evaluator grades assigned code sets and input accounting; it does not replace
human review of the evidence, confidence, refusal reason, or safety flags.
The private grader runs the system unmodified against notes not included in
this repository, so benchmark files are only regression checks. No model key
is required; an LLM adapter would be an optional future proposer whose output
must pass the same policy and evidence checks.

For a successful run the CLI exits with status `0`. An unreadable input or
invalid corpus is a fatal command error; an individual blank, malformed, or
unsupported note is intentionally non-fatal and becomes an unresolved output
line so record accounting is preserved.

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
  deprecated/untrusted guidance and honours explicit replacement relationships
  expressed in trusted corpus prose; the trace explains each
  inclusion/exclusion decision.
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
  thresholds, provenance and malformed input. `tests/test_brief_requirements.py`
  directly exercises non-obvious restrictions, renamed corpus identifiers,
  gap refusal, sourced extensions and trust downgrades. Run all three with
  `python -m unittest discover -s tests -v`.
- `schema/result.schema.json` documents the versioned JSON output contract.
- `Dockerfile` and `compose.yaml` provide the clean-clone container workflow;
  `examples/smoke_notes.jsonl` is the default input for `docker compose up`.
- `reasoning.md` is the candidate's private design record. It is intentionally
  ignored by Git at the user's request and is not required at runtime.

## Data decisions

The data audit found 404 unique catalogue codes and 45 dated snippets, with no
provided guideline-to-code map. A newer trusted revision supersedes an older
rule only when the corpus itself explicitly establishes that relationship;
deprecated and unsigned/imported guidance is excluded from decision retrieval,
while every exclusion is explained in the trace. The imported chest-pain
snippet contains a prompt-injection directive and is treated as untrusted data,
not executable instruction. Definitions, negatives,
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
