# Contributing

## Branches

| Branch | Purpose |
|---|---|
| `main` | Releases only. Never committed to directly. |
| `dev` | Integration branch, and the repository's default. Never committed to directly either. |
| anything else | Your work. Branch off `dev`, open a PR back into `dev`. |

```bash
git switch dev
git pull
git switch -c fix/word-split-behind-a-slash
# ... work ...
git push -u origin fix/word-split-behind-a-slash
gh pr create --base dev
```

## Why no direct commits

A direct push to `dev` or `main` skips two things at once: the CI run and the
review. That combination is how a working tree quietly regresses — a force-push
after a rebase, an accidental `git reset --hard`, a commit made from a stale
clone. There is no record that anything was lost, because the branch simply
moved.

Through a PR, CI runs on the merge result and the diff is reviewable before it
lands. Both branches should have this enforced, not merely agreed:

```bash
# once the repository exists
gh api -X PUT "repos/shiy08166-lab/pdftablex/branches/dev/protection" \
  -H "Accept: application/vnd.github+json" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=test (3.10)" \
  -f "required_status_checks[contexts][]=test (3.12)" \
  -f "required_status_checks[contexts][]=test (3.13)" \
  -f "required_status_checks[contexts][]=no-data-leak" \
  -f "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=0" \
  -f "restrictions=" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false"
```

`required_approving_review_count=0` still requires a PR — it just does not
require a second person, which matters on a single-maintainer repository.
Repeat with `branches/main` for the release branch.

> Classic branch protection is not available on private repositories for every
> plan. If the call is rejected, use **Settings → Rules → Rulesets**, which
> offers the same controls.

## Before opening a PR

```bash
pip install -e ".[dev]"

ruff check src examples tests skills
pytest tests -q
python skills/sync_references.py --check
python examples/demo.py
```

All four must pass. CI runs them, so this is mostly about not waiting for the
round trip.

## House rules

**Never commit a real document.** This is the one rule with no exceptions and no
judgement call. The `.gitignore` blocks `*.pdf`, `*.xlsx`, `*.csv`, `*.json`,
`*.png`, `*.sql` and `*.db` and re-admits only `examples/synthetic/`; CI fails
the build if anything else is tracked. If you need a fixture, generate it:

```bash
python examples/make_synthetic_pdf.py --outdir examples/synthetic   # invented
python examples/fetch_public.py                                     # public domain
```

`examples/public/` is ignored too, on purpose. "This one is safe" is exactly the
judgement that stops being made carefully after the tenth time.

**Never assert correctness you have not demonstrated.** If you add or change an
operator, add a test that shows the difference count going to zero — and say in
the PR which defects it does *not* cover. A clean result is what a blind spot
looks like from the inside; see
[`docs/verification-protocol.md`](docs/verification-protocol.md).

**Repairs must be justified.** An operator commits a change only when a
reference reproduces it exactly or a dictionary backs it. Anything else is
reported, not guessed. If you find yourself adding a heuristic that "usually
works", that is a defect category to document instead.

**Keep `docs/` and the skill in step.** The skill carries generated copies of
the core documents:

```bash
python skills/sync_references.py           # after editing docs/
python skills/sync_references.py --check   # CI runs this
```
