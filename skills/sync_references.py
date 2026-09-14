"""Copy the canonical documents in ``docs/`` into the skill's ``references/``.

The skill has to be installable on its own — copy it into an agent's skill
folder and the relative links to ``docs/`` are gone. So the skill carries its
own copies.

Those copies must not drift, so they are generated, never hand-edited:

    python skills/sync_references.py          # regenerate
    python skills/sync_references.py --check  # fail if out of date (CI)

``docs/`` is the single source of truth. Edit there, then re-run this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REFS = ROOT / "skills" / "pdf-table-extraction" / "references"

#: Human-facing docs that the skill needs to carry with it.
SYNCED = ("methodology.md", "defect-taxonomy.md", "verification-protocol.md")

BANNER = """<!--
Generated from docs/{name} by skills/sync_references.py — do not edit here.
Edit the file in docs/ and re-run: python skills/sync_references.py
-->

"""


def render(name: str, text: str) -> str:
    return BANNER.format(name=name) + text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the copies are out of date instead of writing them",
    )
    args = parser.parse_args(argv)

    REFS.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []

    for name in SYNCED:
        source = DOCS / name
        if not source.exists():
            print(f"missing source: {source}", file=sys.stderr)
            return 2
        wanted = render(name, source.read_text(encoding="utf-8"))
        target = REFS / name
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == wanted:
            print(f"up to date: references/{name}")
            continue
        stale.append(name)
        if args.check:
            print(f"OUT OF DATE: references/{name}", file=sys.stderr)
        else:
            target.write_text(wanted, encoding="utf-8")
            print(f"wrote references/{name}")

    if args.check and stale:
        print(
            f"\n{len(stale)} reference file(s) are stale. "
            "Run: python skills/sync_references.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
