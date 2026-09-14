<!--
Generated from docs/verification-protocol.md by skills/sync_references.py — do not edit here.
Edit the file in docs/ and re-run: python skills/sync_references.py
-->

# Verification protocol

Run this after every extraction. **Every item gets a number, not a "passed".**
An unquantified "looks good" is not a verification.

The purpose is not to produce a comfortable answer. It is to produce an answer
that survives someone else checking it.

---

## 0. Before you start

- [ ] **Name the ground truth.** Is the PDF the baseline, or is the reference
      file? The two roles are not interchangeable, and mixing them up is how
      you end up "fixing" correct data.
- [ ] **List the unrecoverable items** (source-level `####`, values clipped
      before the layer was written) and say so in the deliverable.

## 1. Structural integrity

- [ ] **Row count** — extracted versus expected. A difference of 1 must be
      explained, not waved through.
- [ ] **Column count** — matches the header.
- [ ] **Anchor continuity** — the sequence runs without gaps or repeats, or
      every gap is explained (deleted records? a source-system defect?).
- [ ] **No empty data rows, no shifted rows.**

## 2. Cell comparison, with a reference

- [ ] **Alignment** — pair by unique key where one exists; pair positionally
      only inside a known anchor range; **report the number of unpaired rows**.
- [ ] **Grade at all three levels** — `exact`, `soft`, `hard`. A cell that
      passes `hard` while failing `soft` is content-correct and
      presentation-wrong; that is still a defect worth fixing.
- [ ] **Real differences reach zero, or every one has a verdict.**

## 3. Cell comparison, without a reference

- [ ] **Per-row character conservation** — each row's character multiset
      against the PDF's own band. Upper-case both sides.
- [ ] **Document-wide conservation** — the strong invariant. Repair may move
      characters between bands; it must never create or destroy one.
- [ ] **Value patterns** — identifier format compliance, date formats, numeric
      ranges, enumerator sets.
- [ ] **Cross-consistency** — same code implies same name; report the count of
      violations.

## 4. Classifying every difference

- [ ] Every difference is assigned a category from
      [`defect-taxonomy.md`](defect-taxonomy.md).
- [ ] **Every "the reference is wrong" verdict has render evidence.** No
      exceptions — this is the verdict most likely to be wrong and most
      damaging when it is.
- [ ] **Sampled render review** — at least 1–2 examples per category; for
      symbol defects, cover different character variants *and* different columns.
- [ ] The conclusion distinguishes clearly between: **candidate wrong**,
      **reference wrong**, and **both incomplete**.

## 5. Write-back verification

- [ ] **Re-open the generated file and compare.** Writing is a step that can
      fail on its own.
- [ ] **Every cell forced to text format.** Excel will otherwise turn `10.10`
      into a date and a long identifier into scientific notation.
- [ ] **Spot-check the samples that matter** — anything a user reported, plus
      one representative of each defect class.

## 6. Deliverable

- [ ] Repair operations counted **by operator**.
- [ ] Unrecoverable items stated explicitly.
- [ ] A reproducible script chain: extract → compare → repair → generate.
- [ ] The difference list attached, with before/after values, for human review.
- [ ] Cells completed from the reference listed **separately** — they are not
      evidence that the PDF agreed.

---

## Anti-patterns

Collected from things that actually went wrong. Each one cost a re-run.

| Anti-pattern | Why it bites |
|---|---|
| Scanning for split words with an all-letters test | Misses `INDEX/CATALO` + `GUE`; the split hides behind a slash |
| Different case conventions on the two sides | Flood of false `m`/`M`, `x`/`X`, `φ`/`Φ` alarms |
| Keying a repair dictionary by row instead of row+column | A second repair in the same row overwrites the first |
| Writing with `index + 1` instead of the original row number | The whole file shifts by one row |
| Reversing a slice bound (`[:1]` vs `[1:]`) | Repairs silently produce empty strings |
| Declaring "zero differences" too early | It means the rules have a hole. A user will find it. |
| Treating source-system losses as conversion bugs | You cannot repair data that was never exported |
| Splitting a trailing block by pure geometry | Wrap gaps and row gaps overlap; names get merged |
| Editing one script from several places at once | Parallel edits overwrite each other — serialise them |

## The uncomfortable rule

**Every "zero differences" conclusion deserves one external challenge.** Not
because the work is bad, but because a clean result is exactly what a blind
spot looks like from the inside.

The most valuable finding in this project's history — a split word hiding
behind a slash — was reported by the *user*, not by the tool. The tool's rule
had a hole and reported zero.
