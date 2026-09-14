# pdftablex

**High-fidelity recovery of tabular data from print-to-PDF exports — with evidence, not assurances.**

Print-to-PDF is where structured data goes to die. An engineering BOM, a parts
catalogue, a ledger, a report — export it to PDF and you get a bag of text
fragments with coordinates. Columns are gone, rows bleed into each other,
wrapped words get sliced in half, and the text layer sometimes disagrees with
what you can actually see on the page.

`pdftablex` recovers the table, and — more importantly — gives you a
reproducible reason to believe the recovery is correct.

```
naive extraction     rows 60,  wrong cells: exact 6, whitespace 6, content 3
after repair         rows 60,  wrong cells: exact 0, whitespace 0, content 0
character conservation:  OK — no character created or lost
```

---

## Why the obvious approach fails

`pdfplumber`, `camelot` and `find_tables()` all work well on PDFs that contain
**real vector grid lines**. If your document has those, use `find_tables()` —
this project does, via `pdftablex probe` (see [Choosing a strategy](#choosing-a-strategy)).

Borderless tables are the hard case, and there the failure modes are specific:

| What you see | What actually happened |
|---|---|
| A row's text appears in the next row | A wrapped line sits *below* the next row's first line. Row gaps and wrap gaps are often 3.14pt vs 3.17pt — not separable by geometry. |
| Chinese and English text merged into one column | One text object spans two logical cells. |
| `ALPINE ECOLOGY` extracts as `PEAELNLIGOYOC` | The text layer stores characters out of order. The page renders fine. |
| A cell is short by a few characters | The exporter clipped the tail when painting. The data is in the layer; the ink is not. |
| `°` became a space | The font has no `ToUnicode` mapping for the glyph. |
| Hundreds of phantom differences | A wide-tracked watermark drops one letter into each column. |
| Sequence numbers are all `####` | The source system exported a too-narrow numeric column. **Unrecoverable** — the real values are gone from the PDF. |

## The method

Four principles do the work.

**1. Rebuild by geometry, never by reading order.**
Rows come from anchors (the sequence column). Bands are cut at the midpoints
between consecutive anchors. Every *character* is assigned to a column by its
own centre x — never a whole text object, because objects cross column
boundaries.

**2. The rendered page is ground truth.**
A PDF has two layers: the text layer (what a program extracts) and the render
layer (what a human sees). When they disagree, **the render wins**. `pdftablex`
ships render-forensics helpers so you can turn "is row 931 correct?" into a PNG
and look at it.

**3. Repair only what you can justify.**
Every operator either reproduces a reference file exactly, or is backed by an
independent dictionary. Anything else is *reported*, never guessed.

**4. Prove it, don't claim it.**
Comparison happens at three levels, and a document-wide character-conservation
check runs with no reference at all.

## Install

```bash
pip install pymupdf openpyxl english-words
pip install -e .
```

Python 3.10+. The only heavy dependency is PyMuPDF.

## Quickstart

### Two demos

**1. A synthetic catalogue** — invented, tiny, and hermetic. Six columns.

```bash
python examples/make_synthetic_pdf.py --outdir examples/synthetic
python examples/demo.py
```

The generator injects nine real-world export defects (word split, slash-hidden
split, swallowed space, double space, CJK wrap, column overflow, interleaved
wrap, watermark, footer). The demo shows the naive extraction failing at all
three comparison levels, then the repair pass driving every count to zero.

**2. Real public data** — OurAirports, public domain, sixteen columns.

```bash
python examples/fetch_public.py
python examples/demo_public.py
```

```
naive extraction     rows 400,  wrong cells: exact 18, whitespace 15, content 9
after repair         rows 400,  wrong cells: exact 2,  whitespace 2,  content 2
                     (the 2 are #### cells the PDF destroyed — reported, not invented)
character conservation: OK — no character created or lost
unexpected differences: 0
PASS
```

Two fixtures because they fail differently. Invented data is tidy; real data has
108-character airport names, values that overflow their column, and text with
enough English words in it that a hard-wrapped word can actually be detected and
rejoined. If the pipeline only works on the tidy one, it does not work.

Neither fixture is committed: `examples/public/` is git-ignored, and the
synthetic one is generated on demand.

### Writing your own fixture

`examples/export_sim.py` turns any CSV into a print-to-PDF export with chosen
defects — useful for testing against your own data without shipping it.

```python
from export_sim import plan_layout, plan_defects, render_export, spec_for

layout = plan_layout(header, rows, page_width=842, page_height=595)
defects = plan_defects(rows, layout, seed=7)      # only plants what the data can host
result = render_export(header, rows, layout, defects, "export.pdf")
spec = spec_for(layout)                            # the matching TableSpec

print(result.applied)   # what was actually planted
print(result.skipped)   # what was not physically possible
```

### Command line

```bash
# Is this a bordered or a borderless table?
pdftablex probe catalogue.pdf

# Dump text objects and coordinates so you can measure the column edges.
pdftablex recon catalogue.pdf --pages 0 -1

# Extract, repair, write XLSX, and print the evidence.
pdftablex extract catalogue.pdf \
    --spec spec.json \
    --reference known_good.csv \
    --out catalogue.xlsx \
    --report report.md \
    --verbose

# Re-check an existing output.
pdftablex verify catalogue.pdf --spec spec.json --xlsx catalogue.xlsx --reference known_good.csv
```

### Python API

```python
import pymupdf
from pdftablex import (
    Column, AnchorSpec, PageSpec, TableSpec,
    extract_rows, repair, load_dictionary,
    pdf_band_counters, char_conservation, compare_rows,
)

spec = TableSpec(
    columns=[
        Column("no",       45.0, "code"),
        Column("title_cn", 68.0, "cjk"),
        Column("title_en", 150.0, "en"),
        Column("call_code", 440.0, "code"),
    ],
    right_edge=545.0,
    anchor=AnchorSpec(column=0, max_x=66.0),
    page=PageSpec(data_top=60.0, footer_bottom=800.0, watermarks=frozenset({"SAMPLEDATA"})),
)

doc = pymupdf.open("catalogue.pdf")
rows = extract_rows(doc, spec)

# Reference-guided repair: resolves ambiguity, never invents data.
result = repair(rows, spec, targets=known_good_rows, dictionary=load_dictionary())
print(result.log)                     # every change, with a reason
print(result.completions)             # cells the PDF had lost — verify these by hand

# Independent evidence, no reference needed.
counters = pdf_band_counters(doc, spec)
print(char_conservation(rows, spec, counters))
```

## Choosing a strategy

```bash
$ pdftablex probe catalogue.pdf
strategy        : bordered
why             : 3/3 probed pages expose a table; use find_tables()
find_tables()   : 460 table(s), 35424 row(s), up to 19 column(s)
```

- **Bordered** → `find_tables()`. Faster and more accurate than anything
  geometric. A 460-page export resolves in minutes.
- **Borderless** → this library. `find_tables()` returns nothing useful.

## The repair operators

| Operator | Defect |
|---|---|
| `move_overflow_back` | Long text overflowed past a column boundary. Refuses to act when both sides of the boundary are ASCII — that case is genuinely ambiguous and gets reported instead. |
| `reassign_subline_window` | Adjacent rows' wrapped lines interleave. Pools the window's sub-lines, enumerates every contiguous partition, keeps the one that reproduces the reference. |
| `repair_split_words` | Hard wrap split a word (`ENCYCLOPE` + `DIA`). Uses the leading/trailing *letter run* of a token, so `INDEX/CATALO` + `GUE` is caught too. |
| `repair_swallowed_space` | The wrap also ate the space (`MANUSCRIP` + `TCOLLECTION`). Both halves must be dictionary words. |
| `collapse_cjk_spaces` | Wrap artefacts inside CJK columns (`图 -鉴` → `图-鉴`). |
| `collapse_double_spaces` | Exporter emitted double spaces. |
| `complete_from_reference` | The PDF itself lost characters. **Reported separately** — these are not evidence that the PDF agreed. |

## Verification model

Three comparison levels, because they answer different questions:

| Level | Question | Catches |
|---|---|---|
| `exact` | Byte-for-byte identical? | double spaces, casing |
| `soft` | Same words? | split words, swallowed spaces |
| `hard` | Same datum, however written? | missing/extra characters |

`hard` deliberately ignores notation (whitespace, hyphens, slashes, brackets,
punctuation, degree marks). That is why `soft` and `exact` exist: a cell can be
*content*-correct and still be *presented* wrongly, and only the stricter levels
see it.

Then two conservation checks that need **no reference**:

- **Per-row**: each row's character multiset versus the PDF's own. Catches
  dropped, duplicated and bled-across characters. Rows touched by cross-band
  reassignment are expected to fail this — the characters moved, they were not
  created or destroyed — so the API takes an explicit allowance list.
- **Document-wide**: the whole-document multiset. Repair may *move* characters
  between bands, but it must never create or destroy one. This invariant
  survives every operator.

Finally: **read the output back**. `verify_written_xlsx` re-opens the file and
compares. A pipeline that only checks its in-memory state has checked nothing.

## Layout spec

Everything document-specific lives in a `TableSpec`, so the algorithm never
contains a hard-coded coordinate. Measure the edges with `recon`, write them
down, reuse the algorithm on a completely different table.

```json
{
  "right_edge": 545.0,
  "columns": [
    { "name": "no",        "left": 45.0,  "kind": "code" },
    { "name": "title_cn",  "left": 68.0,  "kind": "cjk"  },
    { "name": "title_en",  "left": 150.0, "kind": "en"   }
  ],
  "anchor": { "column": 0, "max_x": 66.0, "placeholder": "####" },
  "page":   { "data_top": 60.0, "footer_bottom": 800.0,
              "watermarks": ["SAMPLEDATA"], "subline_gap": 1.2 }
}
```

`kind` controls how wrapped sub-lines are stitched: `code` and `cjk`
concatenate directly, `en` inserts a space (unless a trailing `-` is present),
`digit` decides per seam from the characters on both sides.

> **The most common mistake:** `left_edges` must have N+1 entries (N column
> left edges plus the right outer edge). Supplying only N silently shifts every
> column by one.

## Use it as an agent skill

The same method is packaged as an agent skill under
[`skills/pdf-table-extraction/`](skills/pdf-table-extraction/SKILL.md), so an
assistant can pick up both the approach and the working tool without being
briefed.

```bash
cp -r skills/pdf-table-extraction ~/.workbuddy/skills/   # or your agent's skill dir
pip install -e .
```

The skill is a thin layer over this library: it says *when* to use the method,
*which* defects to expect, and *how* to prove the result. Computation stays here.

It is written to be host-agnostic — no assumed tool names, no network access,
no hard-coded paths — and every optional dependency declares how it degrades.
Render forensics is recommended; if the host cannot view images, the skill
requires the agent to **say that adjudication was not performed** rather than
present a weaker verification as a full one.

To validate it on a new agent, ask for something that forces the whole loop:

> Here is a PDF with a borderless table and a CSV that should match it. Recover
> the table, tell me every difference you find and what caused it, and show me
> what you could not recover.

A healthy run reports a strategy decision, a row count, differences at three
levels, at least one inspected render, conservation counts, and an explicit list
of unrecoverable items. A run that reports only "extracted successfully" has not
used the skill.

## Limits — read this before trusting the output

- **`####` sequence numbers are unrecoverable.** The source system exported a
  too-narrow column; the real values are absent from the PDF *and* from any
  derivative. Do not guess them.
- **ASCII-to-ASCII overflow is ambiguous.** When text spills from one
  ASCII column into another ASCII column, the spill point cannot be recovered
  from geometry. `move_overflow_back` declines to act and the cell surfaces as
  a difference.
- **A reference file is not automatically right.** Roughly half the "differences"
  in a real cross-check turn out to be defects of the *reference*, not the PDF —
  jumbled text layers, invisible fragments, damaged markers. Every such verdict
  needs render forensics before it is believed.
- **Never trust a first "zero differences" result.** It usually means the rules
  have a hole. Budget at least one round of external challenge.
- **Two identical-looking rows may be genuinely different.** Positional
  alignment breaks down when the anchor column is missing values; align by
  value where you can, and report unpaired rows rather than forcing a match.

## Data safety

This repository ships **method, code and synthetic samples only**.

Real exports leak. A parts BOM carries supplier names and part numbers; a
ledger carries account identities; a catalogue carries customer data. The
`.gitignore` blocks `*.pdf`, `*.xlsx`, `*.csv`, `*.json`, `*.png`, `*.sql` and
`*.db` by default, and re-admits only `examples/synthetic/`.

Even the public-domain fixture is not committed: `examples/public/` is ignored
too, because "this one is safe" is exactly the judgement that stops being made
carefully after the tenth time. The repository ships code, not data.

Before you push, confirm:

```bash
git status --ignored --short | head
```

If a real document ever reaches a commit, treat it as disclosed — rewriting
history does not un-share it.

## Further reading

| Document | What it covers |
|---|---|
| [`docs/methodology.md`](docs/methodology.md) | The full method, step by step, with the decision tree |
| [`docs/defect-taxonomy.md`](docs/defect-taxonomy.md) | Every export defect, with recognition recipes |
| [`docs/verification-protocol.md`](docs/verification-protocol.md) | The checklist, and the anti-pattern list |
| [`docs/design-notes.md`](docs/design-notes.md) | Why the method is shaped this way — including the approach that failed |
| [`skills/README.md`](skills/README.md) | Installing and validating the agent skill |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch model, branch protection, and the house rules |

## Project layout

```
src/pdftablex/
  config.py     TableSpec — the layout description, so no coordinate is hard-coded
  geometry.py   anchor banding + character-level column assignment
  join.py       stitching wrapped sub-lines, per column kind
  repair.py     the repair operators, each with a justification rule
  verify.py     three comparison levels + character conservation
  detect.py     bordered/borderless probe and the find_tables() fast path
  render.py     render forensics — turn "is row 931 right?" into a PNG
  export.py     XLSX/CSV writers + read-back verification
  specfile.py   layout JSON serialisation
  cli.py        probe / recon / extract / verify
examples/
  make_synthetic_pdf.py  an invented catalogue with nine injected defects
  export_sim.py          CSV → simulated export PDF, with chosen defects
  fetch_public.py        downloads the OurAirports fixture (public domain)
  demo.py                end-to-end on the synthetic catalogue
  demo_public.py         end-to-end on real data, sixteen columns
tests/                   36 tests, including byte-equality round trips
skills/                  the agent skill wrapping this library, plus its sync
docs/                    methodology, defect taxonomy, verification protocol
```

## Development

| Branch | Purpose |
|---|---|
| `main` | Releases only — never committed to directly |
| `dev` | Integration branch and repository default — never committed to directly |
| anything else | Your work; branch off `dev`, PR back into `dev` |

Neither long-lived branch takes direct pushes: a direct push skips the CI run
and the review at the same time, which is how a working tree quietly regresses
after a force-push or a stale-clone commit. Branch protection is expected to
enforce this rather than merely document it — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

```bash
pip install -e ".[dev]"

ruff check src examples tests skills
pytest tests -q
python skills/sync_references.py --check      # skill references match docs/
python examples/demo.py                       # must print PASS
python examples/fetch_public.py && python examples/demo_public.py
```

CI runs all of it, on Python 3.10 / 3.12 / 3.13, plus a job that **fails the
build if a document or spreadsheet outside `examples/synthetic/` is ever
tracked**. It triggers on any branch, deliberately: a workflow that silently
does not run because the branch is named something else is worse than one that
runs too often.

## License

MIT. See [LICENSE](LICENSE).
