---
name: pdf-table-extraction
description: Recover tabular data from print-to-PDF exports (BOMs, catalogues, ledgers, statements, reports) with high fidelity, and prove the result is correct. Use when a PDF contains table data that must be recovered faithfully — especially when naive extraction is garbled, rows bleed into each other, cells wrap across columns, watermarks pollute cells, sequence numbers show as ####, or a reference file (CSV/XLSX) exists to cross-check against. Covers the extraction algorithm, the repair operators, the export-defect taxonomy and the verification protocol.
agent_created: true
---

# PDF table extraction

## The one idea

**A PDF is not a table. It is a bag of text fragments that carry coordinates.**

There is no grid, no rows, no columns, and content-stream order is unrelated to
reading order. One cell may be split across a dozen objects; one object may hold
two cells. Two rules follow:

1. **Rebuild by geometry, never by reading order.** Rows from anchors, columns
   from each character's own centre x.
2. **The render layer is the final truth.** A PDF has a text layer (what a
   program extracts) and a render layer (what a human sees). When they disagree,
   **the render wins** — the text layer can be reordered, can hold fragments that
   were never painted, and can map a symbol to a space.

## Before anything: which kind of table is it?

```bash
pdftablex probe document.pdf
```

- **Bordered** (real vector grid lines) → `find_tables()`. Faster and more
  accurate than anything geometric; a 460-page export resolves in minutes.
  `pdftablex.detect.extract_bordered` wraps it.
- **Borderless** → this skill. `find_tables()` returns nothing useful.

Do not skip this step. Most wasted effort on these tasks is geometry applied to
a document that had grid lines all along.

## Toolbelt

The method is implemented and tested in the `pdftablex` package. Prefer calling
it over re-implementing the algorithm.

```bash
pip install pymupdf openpyxl english-words
pip install -e .            # from the repository root

pdftablex probe   doc.pdf                              # strategy
pdftablex recon   doc.pdf --pages 0 1 -1               # dump coordinates
pdftablex extract doc.pdf --spec s.json --reference known_good.csv \
                          --out doc.xlsx --report report.md --verbose
pdftablex verify  doc.pdf --spec s.json --xlsx doc.xlsx --reference known_good.csv
```

Python:

```python
from pdftablex import (
    Column, AnchorSpec, PageSpec, TableSpec,
    extract_rows, repair, load_dictionary,
    pdf_band_counters, char_conservation, global_char_conservation,
    compare_all_modes, render_region, to_xlsx, verify_written_xlsx,
)
```

If the package is unavailable, `pdftablex/geometry.py` and `pdftablex/join.py`
are the two files worth porting by hand — the rest is convenience.

## Workflow

```
1. PROBE      bordered or borderless?
2. RECON      measure column edges, find the anchor column, find watermarks
3. EXTRACT    anchor banding + character-level column assignment
4. STITCH     join sub-lines per column kind
5. COMPARE    against a reference, at three levels
6. CLASSIFY   give every difference a name (see defect table below)
7. REPAIR     only what can be justified
8. VERIFY     character conservation + render sampling + read-back
```

Steps 5–8 repeat. **Single-pass extraction is never correct.** Plan for rounds.

## Column kinds

`TableSpec` assigns each column a `kind`, which controls how wrapped sub-lines
are rejoined. Getting this wrong is the largest source of "right row count,
wrong cells".

| kind | Rule | Example |
|---|---|---|
| `code` | concatenate | `PZ.10.10.` + `03` |
| `cjk` | concatenate | `山地植物志` + `图鉴汇编` |
| `en` | space, unless the previous line ends with `-` | `FIELD-` + `GUIDE TO THE COASTAL ZONE` |
| `digit` | decide per seam from the neighbouring characters | `PZ10A+` + `Z` |

> **The most common mistake in this whole method:** the boundary table needs
> N+1 entries (N left edges plus the right outer edge). Supply only N and every
> column shifts by one.

## Defect quick reference

| Signature | Defect | Action |
|---|---|---|
| Character multiset matches, order differs | text layer reordered | **Reference is right.** Do not "fix" the extraction. |
| Layer has text the render does not show | invisible fragment | Render decides. Either the tail was clipped (data lost) or the residue is meaningless. |
| A space in the layer renders as a glyph | symbol mapping missing (`°`) | Strip the symbol on **both** sides before comparing. |
| A cell's tail appears in the next column | overflow | `move_overflow_back`. **Declines when both sides are ASCII** — genuinely ambiguous. |
| Word split with no hyphen (`MANUSCRIP` + `T`) | hard wrap | `repair_split_words`. Use the token's **leading/trailing letter run**, so `INDEX/CATALO` + `GUE` is caught too. |
| Neither fragment is a word | wrap swallowed the space | `repair_swallowed_space`. Both halves must be dictionary words. |
| Double spaces | exporter artefact | `collapse_double_spaces`. Do not touch semantic spacing. |
| Sequence numbers are `####` | source system exported a narrow column | **Unrecoverable.** Never fabricate. |
| Same text at the same y on every page, wide tracking | watermark | Discard the whole object at extraction. **Skipping this manufactures hundreds of false differences.** |
| Adjacent rows' wrapped lines interleave | row/wrap pitch overlap | `reassign_subline_window`. **Requires a reference.** |
| Trailing block of nameless rows | pending-registration rows | Handle separately. **Never split by y-gap** — the gaps overlap; read the render. |
| One object holds two cells | object spans columns | Assign by character x, never by object. |
| `'1093 Alpine'` as one object | anchor merged with neighbour | Detect anchors at the **character** level. |

Full taxonomy with recognition recipes:
`docs/defect-taxonomy.md`.

## Three comparison levels

They answer different questions. Report all three.

| Level | Question | Catches |
|---|---|---|
| `exact` | byte-for-byte identical? | double spaces, casing |
| `soft` | same words? | split words, swallowed spaces |
| `hard` | same datum, however written? | missing/extra characters |

`hard` strips notation (whitespace, hyphens, slashes, brackets, punctuation,
degree marks) and upper-cases. A cell can be *content*-correct and still
*presented* wrongly — only `soft` and `exact` see that.

## Verification — do this, do not skip it

Full checklist: `docs/verification-protocol.md`. The non-negotiables:

- **Per-row character conservation** — each row's character multiset against
  the PDF's own band. Needs **no reference**. Upper-case both sides or drown in
  false `m`/`M` alarms. Rows touched by cross-band reassignment are *expected*
  to fail this; pass them as explicit allowances.
- **Document-wide conservation** — the strong invariant. Repair may *move*
  characters between bands; it must never create or destroy one.
- **Read the output back** — re-open the generated file and compare. Writing can
  fail on its own. Force every cell to text format or Excel turns `10.10` into a
  date.
- **Render sampling** — 1–2 examples per defect category. Every verdict of "the
  reference is wrong" needs render evidence; that verdict is the most likely to
  be wrong and the most damaging when it is.

## Iron rules

1. **Render > text layer.** Any claim resting on "the text layer says so" gets
   rendered when challenged.
2. **Never declare "zero differences" as final.** A clean result is what a blind
   spot looks like from the inside. Budget one external challenge.
3. **Scanning rules must cover punctuation-embedded cases.** A split word hiding
   behind a slash defeats an all-letters test.
4. **Unrecoverable is a finding.** Say so; do not guess a value.
5. **A row count off by one is a real bug.** Usually a trailing structural
   problem — a block of nameless rows collapsed into one cell.
6. **The reference is a second opinion, not an oracle.** Roughly half of the
   apparent "differences" in a real cross-check turn out to be defects of the
   *reference*.
7. **Serialise edits to your own scripts.** Parallel edits overwrite each other.

## Portability notes

This skill deliberately avoids host-specific assumptions.

- **Required**: Python 3.10+, `pymupdf`, `openpyxl`, `english-words`, and a way
  to run shell commands.
- **Image inspection is strongly recommended but optional.** Render forensics
  (`pdftablex.render_region`) is how ambiguous differences get adjudicated. If
  you have no way to view a PNG, fall back to character conservation, the
  dictionary operators and value-pattern checks, and **say explicitly in your
  report that render adjudication was not performed** — do not present a
  weaker verification as a full one.
- **`english-words` is optional.** Without it, `repair_split_words` and
  `repair_swallowed_space` become no-ops and the corresponding defects surface
  as `soft`-level differences instead of being repaired. That is a safe
  degradation.
- **No network access is needed or used.** Everything runs on local files.

## Further reading

The skill carries its own copies so it works standalone:

- `references/methodology.md` — the full method, step by step
- `references/defect-taxonomy.md` — every defect, with recognition recipes
- `references/verification-protocol.md` — the checklist and the anti-pattern list
- `scripts/extract_skeleton.py` — a single-file reference implementation, for
  when the `pdftablex` package cannot be installed

The single most valuable habit in those documents: **budget one round of
external challenge for every clean result.** The tool once reported zero
differences on a 2,000-row export; a user then found a split word hiding behind
a slash that the rule could not see.

## Definition of done

Before reporting a result, confirm all of these. If any is missing, say which
one and why — a partial verification stated honestly is worth more than a
complete-looking one that was not performed.

- [ ] Strategy decided (`probe`), and the reason recorded
- [ ] Row count compared against an independent count, delta explained
- [ ] Differences graded at all three levels (exact / soft / hard)
- [ ] Every difference given a category from the defect table
- [ ] Character conservation run, per-row **and** document-wide
- [ ] At least one region rendered and inspected — or an explicit statement that
      render adjudication was not possible
- [ ] Output read back and compared
- [ ] Unrecoverable items and reference-completed cells listed separately
