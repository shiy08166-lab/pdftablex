# Design notes — why this method is shaped the way it is

This library did not start as a library. It started as two independent
attempts at the same problem, and the difference between them is the most
useful thing in this repository.

---

## Two approaches

**Attempt A — architecture first.**

The plan was sound on paper: define a unified intermediate representation
(`Cell` with row/col/span/bbox, `Table` with an engine tag), implement an engine
interface, add three engines (PyMuPDF, Camelot, pdfplumber), route between them,
validate with a capability matrix, and export. Eight phases, a RAM budget per
phase, ~4,700 lines of Python.

It did not produce correct data. On the borderless table it reached ~31% column
accuracy, because the architecture answered *"how do we organise engines?"* and
never answered *"why is this cell's value wrong?"*

**Attempt B — evidence first.**

No architecture. Pick one document, extract it, compare it against something
known-good, classify every difference, look at the ambiguous ones, tighten a
rule, repeat. The row count converged first; the column assignment took several
more rounds. Only once the differences reached zero was the method written down.

It shipped.

---

## What actually separated them

**A believed the text layer was the truth. B discovered the render layer is.**

That is the whole difference, and it is not a matter of effort or code volume.
Attempt A's design principle was "PDF is the single ground truth" — meaning the
*extracted text*. Under that assumption, a jumbled text layer, an invisible
fragment, or a symbol that maps to a space are all invisible failures. You
cannot design your way out of a wrong premise.

Attempt B only found this by rendering regions of the page and *looking at
them*. The finding — "the text layer says `PEAELNLIGOYOC`, the page says
`ALPINE ECOLOGY`" — invalidated the premise and rewrote the
method.

**A optimised for generality. B optimised for being able to tell whether it was
right.**

Attempt A's `find_tables()` path was genuinely excellent — for bordered tables,
it solved a 460-page export in minutes at 100% column accuracy, and that result
is kept in this library as the `probe` fast path. But the same framework had no
answer for the borderless case, because "route to another engine" is not a
strategy when the problem is that no engine can see the truth.

**A stopped at "it runs". B stopped at "I can show it is right".**

Attempt A's deliverable was a pipeline that executed. Attempt B's deliverable
was a set of numbers: row counts, differences per category, characters
conserved, and a list of items it could *not* recover. The second is checkable.
The first is not.

---

## What carried over from the failed attempt

Not nothing — the useful parts are all here:

- **The `find_tables()` fast path.** `pdftablex probe` and
  `pdftablex.detect.extract_bordered` are the direct descendant. For bordered
  exports it beats anything geometric.
- **The two-modes framing.** "Extract and validate" versus "validate an external
  file" is the right decomposition, and it survives in the CLI's
  `extract` / `verify` split.
- **The IR idea, simplified.** A `Cell` with a bbox and a source page is useful.
  Row/col spans and per-cell confidence scores were not — they were never
  populated with anything meaningful, and the real work happened in geometry
  and stitching, not in the data structure.
- **The RAM discipline.** Sequential engines, release before the next one.
  Still good advice.

## What was thrown away

- Multi-engine routing as a *strategy*. It is a fallback, not a plan. If you
  cannot tell whether an engine's output is right, having three of them just
  gives you three unverifiable answers.
- Confidence scores that were never calibrated.
- Any notion that "the pipeline ran" constitutes evidence.

---

## The transferable lesson

> **Build the instrument that tells you whether you are right, before you build
> the thing you want to be right.**

In this project the instrument was: compare against a reference, classify every
difference, render the ambiguous ones, and check character conservation without
a reference at all. Every one of those was cheap to build and each one
immediately falsified an assumption.

The architecture, by contrast, was expensive and falsified nothing.

A second, smaller lesson, which cost a round trip:

> **A clean "zero differences" result is what a blind spot looks like from the
> inside.**

The tool reported zero. The user then found a split word hiding behind a slash
— `INDEX/CATALO` + `GUE` — which the rule's all-letters test could not see.
That fix is now `repair_split_words`, and the anti-pattern is written down in
[`verification-protocol.md`](verification-protocol.md). Budget a round of
external challenge for every clean result you produce.
