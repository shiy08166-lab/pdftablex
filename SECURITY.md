# Security policy

`pdftablex` parses **untrusted input**. A PDF is an attacker-controlled
program for a renderer, and this library walks its text objects, its geometry
and its fonts. Treat a hostile document as in scope.

## Supported versions

Only the latest release gets fixes.

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

**Do not open a public issue.** Use GitHub's private reporting: go to the
**Security** tab of this repository and click **Report a vulnerability**. That
opens a draft advisory only the maintainers can see.

Please include what you did, what happened, and — if you can — a **minimal
reproducing document**. It must be one you generated, never a real export; see
the data-safety note in [`README.md`](README.md).

## What counts

- A crafted PDF that makes the parser hang, blow up memory, or crash the
  process instead of raising.
- A repair operator that writes outside the bounds it declares, or that
  fabricates a value where the contract says it must report instead.
- Anything that turns a malformed document into code execution, file writes,
  or network access. (The library does none of these today; a path to one is a
  vulnerability.)

Decompression bombs and absurdly large documents count as **robustness**
issues. Report them and a guard will be added — but they will be handled in
the open, not as an advisory.

## What does not count

- **A wrong value in the output.** Extraction quality is a correctness bug.
  Open a normal issue. Note that `####` sequence numbers and ASCII-to-ASCII
  overflow are *documented, unrecoverable* limits — see the limits section of
  the README before filing.
- Anything that requires the attacker to already control the machine, or to
  have write access to the repository.
- The example fixtures being wrong. They are synthetic and generated on demand.
