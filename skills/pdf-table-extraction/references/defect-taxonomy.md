<!--
Generated from docs/defect-taxonomy.md by skills/sync_references.py — do not edit here.
Edit the file in docs/ and re-run: python skills/sync_references.py
-->

# Export defect taxonomy

Signatures and countermeasures for the defects that show up in
print-to-PDF tables. Each entry says how to *recognise* the defect and what to
do about it, so you can classify a difference instead of staring at it.

The names are stable identifiers — use them in reports.

---

## A. Text layer reordered

**Signature.** The extracted string is wrong but not random: its character
multiset matches the correct value exactly.
`PEAELNLIGOYOC` ↔ `ALPINE ECOLOGY`.

**Recognise.** `sorted(hard(candidate)) == sorted(hard(reference))`. If the
multisets match, it is a reorder, not a content error.

**Action.** **The render is authoritative; the candidate is correct.** Do not
try to repair the extraction — the data is intact and only its storage order is
scrambled. Reading such a region in content-stream order rather than by x often
recovers the right sequence, but do not rely on it.

---

## B. Text layer holds invisible characters

**Signature.** The layer contains characters that are not painted on the page.

Two distinct cases with opposite conclusions:

1. **Clipped at export** — the tail was never drawn. The layer holds
   `PZ.10.10` but only `PZ.10.1` is painted. The ink is missing, so the
   *visible* value is the truncated one. This is a real data loss.
2. **Invisible residue** — the layer holds extra fragments that were never
   meant to be seen (`PLATE RH` in the layer, absent from the page). The
   reference that omits them is *correct*.

**Recognise.** Render the region. Whatever you can see is the truth.

---

## C. Symbol mapped to a space

**Signature.** A character is a space (or `\x00`) in the layer but renders as a
symbol. Classically `°`, `①②`, bullet marks — fonts with an incomplete
`ToUnicode` table.

**Recognise.** Consecutive spaces in the layer where the render shows a glyph.

**Action.** Strip the symbol on **both** sides before comparing. Do not treat it
as "the data contains a space".

---

## D. Cell content overflows its column

**Signature.** A long value's tail crosses the column boundary and lands in the
neighbour (`BOREAL STRUCTU` with `RE` in the next column).

**Recognise.** `pdftablex` flags the *boundary index* any character straddles.
A `clip` test on the left cell alone is unreliable — the last character often
stops a fraction of a point short of the edge.

**Action.** `move_overflow_back`, committed only when both cells then match the
reference. **Declines to act when both sides are ASCII**, because the spill
point is then genuinely ambiguous; the cell is reported instead.

---

## E. Hard wrap splits a word

**Signature.** An English word is broken at a wrap point with **no hyphen**:
`MANUSCRIP` + `T`.

**Recognise.** The trailing segment is not a word, and the concatenation is.

**Variants — all of these occur:**

- **with a hyphen**: `MANUSCRIP` + `T-FLORA` — the tail is still not a word
- **punctuation-embedded**: `INDEX/CATALO` + `GUE`. A naive "is this token all
  letters?" test misses it. **Take the leading/trailing letter run of the
  token**, not the token.
- **swallowed space**: `MANUSCRIP` + `TCOLLECTION` — see F.

**Action.** `repair_split_words`, dictionary-backed.

---

## F. Wrap swallowed the following space

**Signature.** `MANUSCRIP` + `TCOLLECTION` should be
`MANUSCRIPT COLLECTION`. The split point is *inside* the second fragment.

**Recognise.** Neither fragment is a word, but some split `a + b[:j]` / `b[j:]`
makes both halves words.

**Action.** `repair_swallowed_space`. Both halves must be dictionary words.

> Dictionary coverage is a real constraint. Plurals and inflections are often
> absent from word lists; pick your test vocabulary accordingly, and treat a
> failed lookup as "no opinion", never as "wrong".

---

## G. Double or stray spaces

**Signature.** `MANUSCRIPT  COLLECTION`.

**Action.** Collapse runs of whitespace — but distinguish legitimate semantic
spacing. `BOREAL ECOLOGY` must not be touched.

---

## H. Sequence numbers displayed as `####`

**Signature.** A numeric column too narrow for its content.

**The decision that matters:** check whether the *source* PDF also shows
`####`. If it does, the source system exported it that way and the value is
**gone**. It is not a conversion artefact and it is **not recoverable**. Infer
from position if you must, but never fabricate a value.

---

## I. Watermark pollution

**Signature.** Repeated text at a fixed position on every page, with unusually
wide tracking (`I N T E R N A L`). Individual letters land in different columns
and manufacture hundreds of phantom differences.

**Recognise.** The same text at the same y across pages; or an x-span far wider
than its character count implies.

**Action.** Detect it during reconnaissance and discard the whole object during
extraction. **Skipping this step alone can introduce a thousand false
differences.**

---

## J. Adjacent rows interleave on the y axis

**Signature.** A row's last wrapped line sits within a fraction of a point of
the next row's first line. Row pitch and wrap pitch overlap numerically
(3.14pt vs 3.17pt), so midpoint banding mis-assigns by construction.

**Recognise.** After banding, differences concentrate in long-text columns
while short columns are clean.

**Action.** `reassign_subline_window`. **Requires a reference** — this is a
genuine geometric ambiguity, not something more geometry can solve.

---

## K. Trailing signature / pending-registration block

**Signature.** At the end of a document, a block of rows with only a name and no
identifier, often with a background highlight.

**Recognise.** The row count is short by one or a few; the last row's cell is
suspiciously long (several names concatenated).

**Action.** Handle the block separately. **Do not split it by y-gap** — the
gaps overlap. Read the names off the render, one row at a time, and verify by
checking that the split pieces concatenate back to the original blob.

---

## L. Page-spanning rows

**Signature.** A logical row's content appears at the top of the next page.

**Caution.** Many apparent continuations are simply **the page's own first row
wrapping upward** — a row's wrapped lines normally sit 5–8pt above its anchor.
**Confirm on the render before merging anything across a page break.**

---

## M. Text object spans two columns

**Signature.** One object holds two logical cells:
`'河口湿地手册  MANUSCRIPT COLLECTION O'`.

**Action.** Assign by **character** x, never by object.

---

## N. Sequence number merged with the neighbouring cell

**Signature.** `'1093 Alpine'` — the anchor and the adjacent cell share one
object.

**Action.** Detect anchors at the **character** level: take the run of leading
digits at the start of the object, rather than testing the object as a whole.
