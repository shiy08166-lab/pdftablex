# Agent skill

`pdf-table-extraction/` packages this project as an agent skill, so an assistant
can pick up the method — and the working tool — without being told about it.

The skill is a thin layer over the library: it states *when* to use the method,
*which* defects to expect, and *how* to prove the result. All the computation
lives in `src/pdftablex`.

## Layout

```
skills/
  sync_references.py           keeps references/ in step with docs/
  pdf-table-extraction/
    SKILL.md                   the skill: when to use it, what to expect, how to prove it
    references/                generated copies of the three core docs
    scripts/extract_skeleton.py  single-file fallback, no package install needed
```

The skill has to work when copied somewhere on its own, so it carries its own
copies of the core documents. Those copies are **generated, never hand-edited** —
`docs/` is the source of truth:

```bash
python skills/sync_references.py           # regenerate
python skills/sync_references.py --check   # fail if stale (CI runs this)
```

## Install

Copy the skill directory into your agent's user-level skill folder:

```bash
# typical locations
cp -r skills/pdf-table-extraction ~/.workbuddy/skills/     # WorkBuddy
cp -r skills/pdf-table-extraction ~/.claude/skills/        # Claude-style layouts
```

Then install the library the skill calls:

```bash
pip install pymupdf openpyxl english-words
pip install -e .        # from the repository root
```

The skill degrades safely if the library is missing — it falls back to
`scripts/extract_skeleton.py`, which implements anchor banding and
character-level column assignment in one file — and if `english-words` is
missing, the two dictionary-guided operators become no-ops and the
corresponding defects surface as differences instead of being repaired.

## What changed from a methodology-only skill

An earlier version of this skill was prose plus a skeleton script — correct, but
it asked the agent to re-implement the algorithm each time. This version is
backed by a tested implementation, so the agent spends its effort on the
document rather than on the plumbing.

It is also written to be **host-agnostic**:

- no assumption that a particular image-viewing tool exists — render forensics
  is recommended, and if it is unavailable the skill requires the agent to
  *state that adjudication was not performed* rather than present a weaker
  verification as a full one
- no hard-coded paths, no host-specific tool names, no network access
- every optional dependency is listed with its degradation behaviour

## Validating it on a new agent

The method has been exercised end to end on real documents, but the skill
wrapper has not been run on every host. To check it on a new agent, ask for
something that forces the whole loop:

> Here is a PDF with a borderless table and a CSV that should match it. Recover
> the table, tell me every difference you find and what caused it, and show me
> what you could not recover.

A healthy run reports: a strategy decision, a row count, differences graded at
three levels, at least one rendered region inspected, character conservation
counts, and an explicit list of unrecoverable items. A run that reports only
"extracted successfully" has not used the skill.

## Roadmap

Ideas that would extend the skill, not yet implemented:

- **Bordered-table path as a first-class skill branch.** `find_tables()` is
  wired into the CLI but the skill treats it as a side note.
- **Layout auto-detection.** Measuring column edges by hand with `recon` is the
  slowest part of onboarding a new document; clustering header object x
  positions would automate most of it.
- **Merged-cell semantics.** `row_span` / `col_span` are absent by design — no
  real document in this project needed them. A document that does would need
  the extraction step to emit them.
- **A confidence signal that means something.** Per-cell confidence scores were
  tried and dropped because they were never calibrated. A useful version would
  key off the defect flags (`boundary`, `clip`, `overlap`) rather than a
  synthetic score.
