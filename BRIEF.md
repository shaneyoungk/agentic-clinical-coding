# Take-home: agentic clinical coding

**Sugen Technologies, founding engineer track**

Timebox: about 4 hours of work, inside a 48-hour window from the moment we send
this.

You must build it with your AI tooling (Claude Code, Cursor, Codex, whatever you
actually use). No screen recording. Your commit history is what we read instead,
so commit as you go.

## The situation

A district hospital codes its outpatient encounters by hand. A clinical officer
writes a free-text consult note; a records clerk reads it at the end of the week
and assigns an ICD-11 code from a printed booklet. The codes drive the insurance
claim, so a wrong code is a rejected claim, and a confidently wrong code on a
missed emergency is worse than a rejected claim.

Your job is the assignment: note in, code out, with the evidence that justifies
it.

## Read this part twice

**We do not grade the notes we are giving you, because we are not giving you
any.**

We grade by running your system, unmodified, against a private set of consult
notes written for this exercise. You will never see them. Same hospital, same
clinicians, same catalogue, same guideline corpus. Different patients, different
presentations, and the people writing the notes are no more consistent from one
week to the next than they are inside a single week.

So anything you special-case to what you can see will fail. A keyword table
mapping "chest pain" to a code will fail. A regex that finds restrictions by
looking for the phrase "should not" will fail, because the restrictions that
matter are not written that way. A rule keyed to a specific guideline ID, a
specific code, or a specific phrasing will fail, and it will not be obvious to
you that it has.

Write things that reason, not things that match.

## What you get

`data/icd_catalog.json` — 404 diagnosis entries, each with a code, title,
chapter and synonym list.

`data/guideline_snippets.json` — 45 clinical guideline snippets, each with an
id, title, source, effective date and body text.

We have not documented either one. There is no mapping from guideline to code,
no list of which guidelines matter, and no guarantee the corpus is internally
consistent, complete, or entirely trustworthy. It came out of a real document
library and it looks like one.

**Read the data before you write the retrieval.**

## What to build

A system that takes a free-text consult note and returns an assignment.

**Must work:**

1. `docker compose up` (or one documented command) brings your system up from a
   clean clone with no manual steps in between.
2. One command runs a note, or a file of notes, through the system. The input
   path is an argument, not a constant: we will point it at our own file.
3. For each note, output:
   - the proposed code or codes, **or an explicit refusal**,
   - the retrieved evidence the decision rests on, cited by catalogue code and
     guideline id,
   - a confidence level, and what would raise or lower it,
   - anything you could not resolve, and why.
4. Nothing a note contains disappears silently. A note your system cannot place
   is a note it says it cannot place.

**Language, framework, libraries, model: your choice.** Use what you are fastest
in. An LLM at inference time is allowed and reasonable; so is deterministic
logic. We grade both paths identically. Deterministic logic that generalises is
worth exactly as much as a model call that generalises.

If you call a model, read the key from the environment, commit no keys, and make
the pipeline run end to end with no key set — without a key, anything you cannot
classify goes to the unresolved output rather than crashing the run or being
dropped.

## Four things worth saying plainly

**The restrictions do not announce themselves.** The corpus contains guidance
that narrows, qualifies or overrides other guidance. Some of it is signposted.
Most of it is a definition, a scope statement, a prerequisite, an age band, a
temporal window, or a subordinate clause in the middle of a paragraph about
something else. A system that finds restrictions by looking for restriction
words will find the easy half and confidently walk into the rest.

**The catalogue is incomplete, and saying so is the right answer.** Real
presentations exist that have no entry in the 404 we gave you. Where a note
describes a condition the catalogue does not carry, a system that says "no
confident match, here is why, here is what it looks like" is correct. A system
that force-fits to the nearest available code is wrong, and in a hospital it is
dangerous. **We score the refusal above the guess.**

**Expand the data.** The catalogue and the corpus are a starting set, not the
finished article, and part of this exercise is what you do about that. Source
and add real ICD-11 codes and real guideline material where you find gaps that
matter. Cite what you add and where it came from, keep it separate from what we
supplied so the diff is legible, and say in your README what you added and why
that gap was worth closing. A system that only ever answers out of the 404
entries we handed you has accepted our data as ground truth, and our data is not
ground truth. We are specifically interested in whether you go looking.

**Not everything in the corpus is trustworthy.** It is a document library that
has been migrated, appended to, and edited by people over several years. Treat
what you retrieve accordingly.

## The README is part of the deliverable

Half a page to a page, and we read it before we read the code. Cover:

- What the data made you decide, and what you decided against.
- What you did about guidance that disagrees with other guidance, or with
  itself. There is some. Name it.
- What you added to the catalogue or corpus, why, and where you sourced it.
- Which of your decisions you expect to survive a different set of notes, and
  which you know will not.
- What you did not build, and what you would do next with another day.
- Where this breaks at 50,000 codes instead of 404.

We are more interested in a short honest README attached to a partly finished
system than a long one attached to a complete-sounding claim.

## Ground rules

- **AI tooling is required, not tolerated.** We want to see how you drive it.
  There is no credit for typing it all by hand.
- **Commit as you go, in small commits.** The history is our only view of how
  you worked, including the parts you backed out of. One squashed commit at the
  end tells us nothing and counts against you. So does a history whose timestamps
  say the work happened in a way it did not.
- **Two lines in the README on your tooling:** which tool you used, and the one
  place it produced something wrong that you caught. That second line is the one
  we actually read.
- Do not spend more than about four hours. Nobody finishes this. Where you
  choose to stop is information we want.

## How we judge it

In this order:

1. **It runs on notes you have never seen.** Clean clone, one command up, our
   note file in, structured output out. This is most of the score.
2. **Judgment on hard notes.** The interesting parts of this exercise are the
   notes where the obvious answer is the wrong one, and the notes where the right
   answer is that there is no answer. What you do there, and whether you noticed
   at all, is the rest of it.
3. **Nothing silently disappears.** Every note is accounted for in the output.
   A note you admit you could not code costs less than a note that quietly
   receives a plausible wrong code.
4. **What you did about the data we gave you**, including what you added.
5. **How you drove the tooling**, from the commit history and those two README
   lines.
6. Polish, tests, and code style, last. Not unimportant, just last.

## Submitting

Reply to this email inside the 48-hour window with:

1. A link to a private GitHub repo, with `devin.y0411@gmail.com` invited as a
   collaborator. Push the real history, not a squash.
2. One line on how long it actually took you.

Questions during the window are fine, and asking a good one costs you nothing.
Email is the fastest way to reach us.
