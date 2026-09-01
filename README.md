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
contains the catalogue code, guideline ID, quoted note evidence and confidence
factors. `trace` records corpus hashes, retrieval hits, extracted facts and
policy branches. No model key is required; an LLM adapter would be an optional
future proposer whose output must pass the same policy and evidence checks.

`docker compose up` builds and runs the included smoke file. To run a supplied
file in the container from PowerShell, use
`docker compose run --rm -v "${PWD}:/input:ro" coder /input/notes.jsonl`.

## Data decisions

The data audit found 404 unique catalogue codes and 45 dated snippets, with no
provided guideline-to-code map. The active pneumonia revision supersedes the
older clinical-only rule; deprecated and unsigned/imported guidance is excluded
from decision retrieval, while its exclusion is visible in the trace. The
imported chest-pain snippet contains a prompt-injection directive and is
treated as untrusted data, not executable instruction. Definitions, negatives,
age bands, time windows, confirmation requirements and competing candidates are
implemented as predicates. Missing catalogue coverage (for example giant-cell
arteritis, acute chest syndrome and necrotising soft-tissue infection) produces
a coded refusal and safety flag.

I reviewed public WHO ICD-11/API material and clinical safety/evaluation
guidance, but did not copy external codes into the exercise catalogue: without
the exercise's release/version and a validated local mapping, doing so could
create a plausible but wrong payer assignment. The additive-loader and corpus
hashes are ready for separately sourced, licensed additions; any addition
should carry its own source, version and review record.

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
