---
name: Bug report
about: Something is wrong — a crash, a hang, or a value recovered incorrectly
title: ""
labels: bug
---

<!--
  Before filing, read the limits section of the README. `####` sequence
  numbers and ASCII-to-ASCII overflow are documented, unrecoverable cases —
  they are not bugs.
-->

## What happened

<!-- The value you got. -->

## What you expected

<!-- The value you expected, and how you know. -->

## How you know which one is right

<!--
  This project's whole claim is "prove it, don't claim it". "The output looks
  wrong" is hard to act on; "the render shows X and the text layer shows Y" is
  immediately actionable.

  If you have a reference file, say so. If you looked at a rendered page, say
  so. If you have neither, say that too — it changes what can be concluded.
-->

## Which comparison level fails

- [ ] `exact` (byte-for-byte)
- [ ] `soft` (same words)
- [ ] `hard` (same datum, however written)
- [ ] character conservation (per-row or document-wide)
- [ ] it crashes or hangs instead

## Reproducing document

<!--
  Do NOT attach a real document. Real exports leak supplier names, part
  numbers and customer data, and this repository will not accept one.

  Instead, reproduce the *shape*: `examples/export_sim.py` turns any CSV into a
  simulated print-to-PDF export with chosen defects. Or describe the layout and
  the defect and attach nothing at all — that is still useful.
-->

- [ ] I have not attached a real document.

## Environment

- `pdftablex` version:
- Python version:
- OS:
- `pdftablex probe` says the table is: bordered / borderless

## What you already ruled out

<!--
  What did you try? Which assumptions did you test? Knowing where you stopped
  saves a round trip.
-->
