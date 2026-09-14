"""End-to-end demo on the synthetic catalogue.

    python examples/demo.py

It prints the naive extraction's error rate, then the same numbers after the
repair pass, then the independent character-conservation check. The point of
the demo is the *shape* of the result, not the specific numbers:

    naive      -> rows are right, cells are wrong
    repaired   -> differences go to zero
    conservation -> every row balances, with no reference involved

Everything it touches is generated fiction.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pymupdf
from make_synthetic_pdf import build_dataset, build_pdf, build_spec, write_ground_truth

from pdftablex import (
    char_conservation,
    classify_all,
    compare_all_modes,
    extract_rows,
    global_char_conservation,
    pdf_band_counters,
    probe_strategy,
    repair,
    to_xlsx,
    verify_written_xlsx,
)
from pdftablex.repair import load_dictionary

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "synthetic"


def read_truth(path: Path, names: list[str]) -> list[list[str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if rows and rows[0] == names:
        rows = rows[1:]
    return rows


def bar(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def _print_modes(results: dict, indent: str = "") -> None:
    """Report all three comparison levels side by side."""
    counts = {mode: len(diffs) for mode, diffs in results.items()}
    print(
        f"{indent}wrong cells    : exact {counts['exact']}, "
        f"whitespace {counts['soft']}, content {counts['hard']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default=str(DEFAULT_OUT))
    parser.add_argument("--rows", type=int, default=60)
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # --- 1. build the fixture ------------------------------------------
    bar("1. build a synthetic PDF (fictional library catalogue)")
    rows_data = build_dataset(args.rows)
    pdf_path = build_pdf(outdir / "catalogue.pdf", rows_data)
    truth_path = write_ground_truth(outdir / "catalogue_ground_truth.csv", rows_data)
    spec = build_spec()
    print(f"   {pdf_path.name}: {len(rows_data)} rows, {spec.n_columns} columns")
    print("   deliberately injected: word splits, slash-hidden split, swallowed")
    print("   space, double space, CJK wrap, column overflow, interleaved wrap,")
    print("   watermark, footer")

    targets = read_truth(truth_path, spec.names)
    doc = pymupdf.open(pdf_path)

    # --- 2. pick a strategy --------------------------------------------
    bar("2. choose an extraction strategy")
    probe = probe_strategy(doc)
    print(f"   strategy: {probe.strategy}")
    print(f"   because : {probe.reason}")

    # --- 3. naive extraction -------------------------------------------
    bar("3. naive extraction (geometry only)")
    rows = extract_rows(doc, spec)
    print(f"   rows extracted : {len(rows)}  (truth: {len(targets)})")
    naive = compare_all_modes(rows, spec, targets)
    _print_modes(naive, indent="   ")
    print("   (content = same datum however written; whitespace = same words;")
    print("    exact = byte-for-byte. Naive stitching fails all three.)")

    # --- 4. repair ------------------------------------------------------
    bar("4. repair")
    dictionary = load_dictionary()
    print(f"   dictionary     : {len(dictionary):,} words")
    result = repair(rows, spec, targets=targets, dictionary=dictionary)
    for line in result.log[:14]:
        print(f"   · {line}")
    if len(result.log) > 14:
        print(f"   · ... and {len(result.log) - 14} more operation(s)")
    print(f"   total operations: {len(result.log)}")
    print(f"   recovered from reference: {len(result.completions)}")

    after = compare_all_modes(rows, spec, targets)
    _print_modes(after, indent="   ")
    content_diffs = classify_all(after["hard"])
    if content_diffs:
        for d in content_diffs[:6]:
            print(f"     row {d.row} {spec.names[d.col]}: {d.candidate!r} != {d.reference!r}")

    # --- 5. independent evidence ---------------------------------------
    bar("5. independent verification (no reference used)")
    counters = pdf_band_counters(doc, spec)
    expected = result.expected_conservation_failures
    problems = char_conservation(
        rows, spec, counters, allow_extra_in=expected, allow_missing_in=expected
    )
    if problems:
        print(f"   per-row conservation : {len(problems)} row(s) unbalanced")
        for anchor, extra, missing in problems[:6]:
            print(f"     anchor {anchor}: extra={dict(extra)} missing={dict(missing)}")
    else:
        print(f"   per-row conservation : all {len(rows)} rows balance")
    if expected:
        print(f"   (expected exceptions : rows {sorted(expected)} -- the repair pass moved")
        print("    characters between bands, so they now sit in a different row)")

    extra, missing = global_char_conservation(rows, spec, counters)
    if extra or missing:
        print(f"   document-wide        : extra={dict(extra)} missing={dict(missing)}")
    else:
        print("   document-wide        : OK -- no character created or lost")

    # --- 6. write and read back ----------------------------------------
    bar("6. write XLSX and read it back")
    xlsx = to_xlsx(rows, spec, outdir / "catalogue_extracted.xlsx", header=spec.names)
    mismatches = verify_written_xlsx(xlsx, rows, spec)
    print(f"   wrote {xlsx.name}")
    print(f"   read-back check: {'OK' if not mismatches else f'{len(mismatches)} mismatch(es)'}")

    doc.close()

    # --- 7. verdict -----------------------------------------------------
    bar("7. verdict")
    ok = (
        not after["hard"]
        and not after["soft"]
        and not after["exact"]
        and not problems
        and not mismatches
        and not (extra or missing)
    )
    print(f"   content differences      : {len(after['hard'])}")
    print(f"   whitespace differences   : {len(after['soft'])}")
    print(f"   byte differences         : {len(after['exact'])}")
    print(f"   unexplained imbalances   : {len(problems)}")
    print(f"   characters created/lost  : {sum(extra.values()) + sum(missing.values())}")
    print(f"   write read-back errors   : {len(mismatches)}")
    print(f"   {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
