## What this changes

<!-- One or two sentences. What was wrong, or what is new. -->

## Which defect does it address?

<!--
Name it from docs/defect-taxonomy.md, or say "none — infrastructure".
If this adds or changes a repair operator, say which defect it handles and
which it does NOT. A heuristic that "usually works" is a defect category to
document, not a rule to add.
-->

## Verification

- [ ] `pytest tests -q` passes
- [ ] `ruff check src examples tests skills` passes
- [ ] `python skills/sync_references.py --check` passes (if `docs/` changed)
- [ ] A demo reaches `PASS` — `examples/demo.py` and/or `examples/demo_public.py`
- [ ] No real document is added: `git ls-files | grep -v '^examples/synthetic/' | grep -Ei '\.(pdf|xlsx?|csv|png|sql|db)$'` returns nothing

## Honesty check

<!--
Answer both, even if briefly. They are the two ways this project most often
fools itself.
-->

- **What is NOT covered by this change?** (Which defect classes, which inputs,
  which comparison levels?)
- **What would make you distrust the result?** (Which assumption, if wrong,
  invalidates it?)
