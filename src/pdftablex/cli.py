"""Command line interface.

    pdftablex probe   catalogue.pdf              # bordered or borderless?
    pdftablex recon   catalogue.pdf --spec s.json # dump coordinates
    pdftablex extract catalogue.pdf --spec s.json --out out.xlsx
    pdftablex verify  catalogue.pdf --spec s.json --xlsx out.xlsx
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pymupdf

from . import __version__
from .detect import extract_bordered, probe_strategy
from .export import to_xlsx, verify_written_xlsx
from .geometry import extract_rows, iter_objects
from .repair import load_dictionary, repair
from .specfile import load_spec
from .verify import (
    VerificationReport,
    char_conservation,
    classify_all,
    compare_rows,
    format_conservation,
    global_char_conservation,
    pdf_band_counters,
    summarize,
)


def _read_reference(path: str, names: list[str] | None = None) -> list[list[str]]:
    """Read a reference CSV, dropping a header row if it names the columns."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if rows and names and [c.strip() for c in rows[0]] == names:
        rows = rows[1:]
    return rows


def cmd_probe(args: argparse.Namespace) -> int:
    doc = pymupdf.open(args.pdf)
    result = probe_strategy(doc)
    print(f"pages           : {doc.page_count}")
    print(f"pages probed    : {result.pages_probed}")
    print(f"pages w/ tables : {result.pages_with_tables}")
    print(f"strategy        : {result.strategy}")
    print(f"why             : {result.reason}")
    if result.strategy == "bordered":
        tables = extract_bordered(doc)
        total = sum(t["n_rows"] for t in tables)
        cols = max((t["n_cols"] for t in tables), default=0)
        print(f"find_tables()   : {len(tables)} table(s), {total} row(s), up to {cols} column(s)")
    doc.close()
    return 0


def cmd_recon(args: argparse.Namespace) -> int:
    """Dump objects and coordinates so column edges can be measured."""
    spec = load_spec(args.spec) if args.spec else None
    doc = pymupdf.open(args.pdf)
    pages = args.pages or [0, 1, doc.page_count - 1]
    pages = [p if p >= 0 else doc.page_count + p for p in pages]

    for page_index in sorted(set(pages)):
        page = doc[page_index]
        print(f"=== page {page_index + 1}  rect={page.rect} ===")
        if spec is not None:
            objects = iter_objects(page, page_index, spec)
        else:
            # No spec yet: show the raw text objects so edges can be measured.
            from .geometry import Char, Obj

            objects = []
            raw = page.get_text("rawdict")
            for block in raw.get("blocks", ()):
                for line in block.get("lines", ()):
                    chars = [
                        Char((c["bbox"][0] + c["bbox"][2]) / 2, c["bbox"][0], c["bbox"][2], c["c"])
                        for span in line.get("spans", ())
                        for c in span.get("chars", ())
                    ]
                    if chars:
                        objects.append(Obj(line["bbox"][1], chars, "".join(c.c for c in chars)))
            objects.sort(key=lambda o: o.y)

        for obj in objects[: args.limit]:
            x0 = min(c.x0 for c in obj.chars)
            x1 = max(c.x1 for c in obj.chars)
            print(f"  y={obj.y:7.2f} x={x0:6.1f}-{x1:6.1f}  {obj.text[:70]!r}")

        lines = sorted(
            {
                round(d["rect"].y0, 1)
                for d in page.get_drawings()
                if d["rect"].width > 100 and d["rect"].height < 1.5
            }
        )
        print(f"  horizontal rules at y: {lines[:12]}")
    doc.close()
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    doc = pymupdf.open(args.pdf)

    strategy = probe_strategy(doc)
    if strategy.strategy == "bordered" and not args.force_geometry:
        print(
            f"note: {strategy.reason}. find_tables() is likely better; "
            "pass --force-geometry to reconstruct anyway."
        )

    rows = extract_rows(doc, spec)
    print(f"extracted {len(rows)} row(s) from {doc.page_count} page(s)")

    targets = _read_reference(args.reference, spec.names) if args.reference else None
    if targets is not None and len(targets) != len(rows):
        print(
            f"warning: reference has {len(targets)} row(s) but {len(rows)} were extracted; "
            "reference-guided repair is skipped"
        )
        targets = None

    result = repair(
        rows,
        spec,
        targets=targets,
        dictionary=load_dictionary(),
        max_window=args.window,
    )
    if result.log:
        print(f"repair: {len(result.log)} change(s)")
        if args.verbose:
            for line in result.log:
                print(f"  {line}")
    else:
        print("repair: nothing to do")

    header = spec.names
    out = to_xlsx(rows, spec, args.out, header=header)
    print(f"wrote {out}")

    mismatches = verify_written_xlsx(out, rows, spec)
    print(f"read-back check: {'OK' if not mismatches else f'{len(mismatches)} mismatch(es)'}")

    if result.completions:
        print(f"cells recovered from the reference: {len(result.completions)}")
        print("  these are NOT confirmed by the PDF -- review them explicitly")

    # Independent evidence, needs no reference.
    counters = pdf_band_counters(doc, spec)
    expected = result.expected_conservation_failures
    problems = char_conservation(
        rows, spec, counters, allow_extra_in=expected, allow_missing_in=expected
    )
    print(format_conservation(problems))

    extra, missing = global_char_conservation(rows, spec, counters)
    if extra or missing:
        print(f"document-wide conservation: extra={dict(extra)} missing={dict(missing)}")
    else:
        print("document-wide conservation: OK (no character created or lost)")

    if targets is not None:
        diffs = classify_all(compare_rows(rows, spec, targets))
        print(f"cell differences vs reference: {summarize(diffs)}")
        if args.report:
            _write_report(
                args.report, rows, spec, diffs, problems, result.log, result.completions
            )
            print(f"wrote {args.report}")

    doc.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    spec = load_spec(args.spec)
    doc = pymupdf.open(args.pdf)

    rows = extract_rows(doc, spec)
    report = VerificationReport(row_count=len(rows))

    targets = _read_reference(args.reference, spec.names) if args.reference else None
    if targets is not None:
        if len(targets) != len(rows):
            print(
                f"warning: reference has {len(targets)} row(s) but {len(rows)} were "
                "extracted; comparison is skipped"
            )
            targets = None
        else:
            report.expected_row_count = len(targets)
            result = repair(rows, spec, targets=targets, dictionary=load_dictionary())
            print(f"repair: {len(result.log)} change(s)")
            diffs = classify_all(compare_rows(rows, spec, targets))
            report.diffs = diffs
            print(f"cell differences: {summarize(diffs)}")
            for diff in diffs[: args.limit]:
                print(
                    f"  row {diff.row} col {spec.names[diff.col]}: "
                    f"{diff.candidate!r} != {diff.reference!r}  [{diff.kind}]"
                )
            counters = pdf_band_counters(doc, spec)
            expected = result.expected_conservation_failures
            report.conservation_problems = char_conservation(
                rows, spec, counters, allow_extra_in=expected, allow_missing_in=expected
            )
    else:
        counters = pdf_band_counters(doc, spec)
        report.conservation_problems = char_conservation(rows, spec, counters)

    print(report.render())

    if args.xlsx:
        mismatches = verify_written_xlsx(args.xlsx, rows, spec)
        print(
            f"file vs fresh extraction: "
            f"{'identical' if not mismatches else f'{len(mismatches)} difference(s)'}"
        )
        for row, col, want, got in mismatches[: args.limit]:
            print(f"  row {row} col {col}: expected {want!r}, found {got!r}")

    doc.close()
    return 0


def _write_report(path, rows, spec, diffs, problems, log, completions) -> None:
    lines = [
        "# Extraction report",
        "",
        f"- rows extracted: {len(rows)}",
        f"- cell differences: {summarize(diffs)}",
        f"- repair operations: {len(log)}",
        f"- cells recovered from reference: {len(completions)}",
        "",
        "## Character conservation",
        "",
        "```",
        format_conservation(problems),
        "```",
        "",
        "## Cell differences",
        "",
        "| row | column | candidate (PDF) | reference | kind |",
        "|---|---|---|---|---|",
    ]
    for diff in diffs:
        lines.append(
            f"| {diff.row} | {spec.names[diff.col]} | {diff.candidate} | "
            f"{diff.reference} | {diff.kind} |"
        )
    if completions:
        lines += [
            "",
            "## Cells recovered from the reference",
            "",
            "> The PDF itself had lost these characters. They are filled from the",
            "> reference and must be confirmed against the authoritative source.",
            "",
            "| row | column | value in PDF | value written |",
            "|---|---|---|---|",
        ]
        for item in completions:
            lines.append(
                f"| {item['row']} | {spec.names[item['col']]} | {item['pdf']} | "
                f"{item['reference']} |"
            )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdftablex",
        description="Recover tabular data from print-to-PDF exports, with evidence.",
    )
    parser.add_argument("--version", action="version", version=f"pdftablex {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("probe", help="decide between find_tables() and geometry")
    p.add_argument("pdf")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("recon", help="dump text objects and coordinates")
    p.add_argument("pdf")
    p.add_argument("--spec", help="layout JSON; optional, improves filtering")
    p.add_argument("--pages", type=int, nargs="*", help="0-based page indices")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_recon)

    p = sub.add_parser("extract", help="extract, repair and write XLSX")
    p.add_argument("pdf")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True, help="output .xlsx path")
    p.add_argument("--reference", help="reference CSV used to resolve ambiguity")
    p.add_argument("--report", help="write a markdown report here")
    p.add_argument("--window", type=int, default=5, help="max window for sub-line reassignment")
    p.add_argument("--force-geometry", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("verify", help="verify an existing output")
    p.add_argument("pdf")
    p.add_argument("--spec", required=True)
    p.add_argument("--xlsx", help="verify this file instead of a fresh extraction")
    p.add_argument("--reference")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
