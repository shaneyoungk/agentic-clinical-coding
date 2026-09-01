# Separately sourced additions

These files are intentionally separate from the 404-entry exercise catalogue
and the supplied guideline corpus. They are opt-in at runtime:

```text
python -m app.cli notes.jsonl \
  --extra-catalogue data/additions/icd_catalog_additions.json \
  --extra-guidelines data/additions/guideline_additions.json
```

## Catalogue addition

`icd_catalog_additions.json` adds `1B71`, Necrotising fasciitis. The supplied
catalogue contains cellulitis but no dedicated necrotising soft-tissue entry;
using cellulitis for pain out of proportion, rapid progression, anaesthesia or
crepitus would be an unsafe force-fit. The code/title appears in the WHO ICD-11
Reference Guide, February 2023, page 349 (Spanish edition):

https://icd.who.int/es/docs/GuiaReferencia_CIE_11_Feb2023.pdf

The record identifies the WHO ICD-11 MMS code system and the `2025-01`
linearization release. It is not merged into the supplied default corpus, so
the default benchmark remains reproducible against the exercise data.

## Guideline addition

`guideline_additions.json` contains a short paraphrase of the WHO Global
Malaria Programme's diagnostic-testing guidance. It closes a provenance gap
for the local malaria confirmation rule by making the microscopy/RDT-before-
treatment principle available as a separately sourced, versioned guideline.
The text is a concise adaptation rather than a bulk copy of the source page:

https://www.who.int/teams/global-malaria-programme/case-management/diagnosis

The WHO page describes this as a living resource, so the addition must be
reviewed when the source changes. External records are validated for collisions,
hashed in the output trace, and remain subject to the same deterministic policy
and refusal checks as supplied records.
