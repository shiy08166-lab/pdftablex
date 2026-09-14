# Methodology

The full method, end to end. Read this once before using the tool on a document
that matters.

---

## The one idea

**A PDF is not a table. It is a bag of text fragments that carry coordinates.**

There is no grid, no rows, no columns, and the order in which fragments appear
in the content stream is unrelated to the order a human reads them. A single
cell may be split across a dozen objects; a single object may hold two cells.

Everything below follows from that.

Two consequences become rules:

1. **Rebuild by geometry, never by reading order.**
2. **The render layer is the final truth.** A PDF has a text layer (what a
   program can extract) and a render layer (what a human sees). When they
   disagree, **the render wins** — the text layer can be reordered, can hold
   fragments that were never painted, and can map a symbol to a space.

---

## The loop

Extraction is not a one-shot process. It is a loop, and the loop terminates
when the differences are zero *or* every remaining difference has a written
verdict.

```
  extract
     |
     v
  compare against a reference
     |
     v
  classify each difference  ----------> all explained?  -- yes --> deliver
     |                                        ^
     v                                        |
  render forensics for the ambiguous ones ----+
     |
     v
  add or tighten a rule, re-run  ----------------+
```

Single-pass extraction is never correct. Plan for several rounds.

---

## Decision tree

```
Is there a reference file (CSV/XLSX/previous export)?
├─ YES → use it to resolve geometric ambiguity (sliding-window reassignment),
│         and classify every surviving difference.
│         The reference resolves *ambiguity*. It does not get to overrule the
│         PDF on content — see the caution below.
└─ NO  → rely on geometric self-consistency, value patterns, a dictionary, and
          character conservation.

Is the text layer trustworthy?
├─ NO  → render forensics decides. Reordering, invisible fragments, symbol
│         mapping failures are all invisible to text-only tools.
└─ YES → compare directly.

Either way, finish with: character conservation + sampled render review.
```

**The caution.** A reference is a second opinion, not an oracle. In real
cross-checks, roughly half of the apparent "differences" turned out to be
defects of the *reference*: jumbled text layers, invisible fragments, damaged
prefix marks. Every verdict of "the reference is wrong" needs render evidence.

---

## Step 1 — Reconnaissance

Look before you extract. Dump the text objects and their coordinates.

```bash
pdftablex recon document.pdf --pages 0 1 -1
```

Establish:

| Question | Where to look |
|---|---|
| Page size and orientation | `page.rect` |
| Column edges | the header row's object x positions |
| Where data starts | the first row below the header |
| **Which column identifies a row?** | a sequence number — ideally unique and consecutive |
| Page header / footer | the first anchor's y on later pages; the footer's y |
| Watermarks | very wide tracking, repeated at the same y on every page |
| Grid lines | `page.get_drawings()` — horizontal rules give you row bounds for free |

If there are real grid lines, stop here and use `find_tables()`.

---

## Step 2 — Extract

Three moves.

**2.1 Row anchors, character by character.**
Take the run of leading digits at the start of each text object whose centre
sits left of the anchor column's right edge. Object-level tests miss the common
case where the sequence number and the adjacent cell share one object.

**2.2 Bands at anchor midpoints.**
The boundary between row *i* and row *i+1* is the midpoint of their anchor y
values. A row's own wrapped lines may sit a few points *above* its anchor —
that is normal stacking, not a page-spanning continuation.

**2.3 Column assignment by character centre.**
`bisect` the character's centre x against the boundary table. Never assign by
object — objects cross column boundaries.

> **The most common mistake in this whole method:** the boundary table needs
> N+1 entries (N left edges plus the right outer edge). Supply only N and every
> column shifts by one.

---

## Step 3 — Stitch cells

Group a cell's fragments into sub-lines by baseline proximity, then join the
sub-lines. **The join rule depends on what the column contains**, and getting
it wrong is the largest source of "right row count, wrong cells".

| Column kind | Rule | Example |
|---|---|---|
| `code` | concatenate | `PZ.10.10.` + `03` |
| `cjk` | concatenate | `山地植物志` + `图鉴汇编` |
| `en` | space, unless the previous line ends with `-` | `FIELD-` + `GUIDE TO THE COASTAL ZONE` |
| `digit` | decide per seam from the neighbouring characters | `PZ10A+` + `Z` |

---

## Step 4 — Compare

Grade at three levels, because they answer different questions:

| Level | Question |
|---|---|
| `exact` | byte-for-byte identical? |
| `soft` | same words? |
| `hard` | same datum, however written? |

`hard` ignores notation (whitespace, hyphens, slashes, brackets, punctuation,
degree marks) and upper-cases. It is the right level for "is this the same
value?" — and it deliberately hides wrap artefacts, which is why the other two
exist.

**Alignment.** Pair by unique key where one exists. Where the key column has
gaps (a `####` block, say), pair positionally inside a known anchor range.
**Report unpaired rows** — they are usually where the real problem is.

---

## Step 5 — Resolve geometric ambiguity

When adjacent rows' wrapped lines interleave, geometry alone cannot separate
them. With a reference, use sliding-window reassignment:

> Take a window of 2–5 rows around a failure. Pool **all** of that column's
> sub-lines across the window, sorted by y. Enumerate every contiguous
> partition of the pool into `window` parts. Keep the partition that reproduces
> the reference exactly; break ties toward the partition that moves the fewest
> sub-lines.

This is the single highest-yield operator. In one real project it fixed 96 cells
in a 2,000-row BOM and **15,910** cells in a 35,000-row catalogue.

**The principle that keeps it honest:** the reference resolves *extraction
ambiguity* only. Anything still mismatching afterwards goes on the difference
list as a real difference — it is never quietly attributed to the reference.

---

## Step 6 — Classify, then repair

Every remaining difference gets a category from
[`defect-taxonomy.md`](defect-taxonomy.md). Repair operators are applied only
where justified:

- **reference-guided** operators commit only when both affected cells then match
- **dictionary-guided** operators commit only when the rejoined text is a real word
- **mechanical** operators (whitespace collapsing) are safe but must not touch
  semantically meaningful spacing

Anything else is **reported, not guessed**. "Unrecoverable" is a legitimate and
important finding.

---

## Step 7 — Verify independently

Do not re-run the same logic and call it verification. Use evidence that does
not depend on your own stitching:

**Character conservation.** Compare each row's *character multiset* — not its
content — against the PDF's own band. Catches dropped, duplicated and
bled-across characters with **no reference at all**. Upper-case both sides, or
you will drown in false `m`/`M` alarms.

**Document-wide conservation.** The strong invariant. Repair may move characters
between bands, but it must never create or destroy one.

**Value patterns.** Identifier formats, date formats, numeric ranges,
enumerator sets.

**Render sampling.** Pick 1–2 examples per defect category and *look at them*.
For symbol defects, cover different character variants and different columns.

**Read the output back.** Re-open the generated file and compare. Writing can
fail on its own.

---

## What "correct" means

You cannot honestly say "I guarantee this is right". You can say:

> **Under every independent line of evidence I could construct, this is
> self-consistent: character conservation balances document-wide, every
> difference against the reference has a written verdict backed by render
> evidence, and the output reads back identically.**

And you should add what you could *not* establish: which values were
unrecoverable, which cells were completed from the reference, and where the
evidence ran out.

That is a stronger claim than a guarantee, because it can be checked.
