"""End-to-end demo on a real, public-domain dataset.

    python examples/fetch_public.py     # download once
    python examples/demo_public.py

Where ``demo.py`` uses an invented catalogue, this one uses real records from
OurAirports — 16 columns, prose-like names and place names that wrap, quoted
fields containing commas, mixed numeric precision. None of it is confidential:
the dataset is public domain.

The point of having both fixtures is that they fail differently. Invented data
is tidy. Real data has 108-character airport names, values that overflow their
column, and text with enough English words in it that a hard-wrapped word can
actually be detected and rejoined.

Expected outcome: every recoverable defect is repaired, and the two ``####``
cells are reported as unrecoverable rather than invented.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pymupdf
from export_sim import (
    is_representable,
    plan_defects,
    plan_layout,
    render_export,
    spec_for,
    write_ground_truth,
)

from pdftablex import (
    char_conservation,
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
PUBLIC = HERE / "public"

#: Columns taken from the OurAirports dataset, in order. ``name``,
#: ``municipality`` and ``keywords`` hold prose; the rest are codes and numbers.
COLUMNS = [
    "id",
    "ident",
    "type",
    "name",
    "latitude_deg",
    "longitude_deg",
    "elevation_ft",
    "continent",
    "iso_country",
    "iso_region",
    "municipality",
    "scheduled_service",
    "iata_code",
    "gps_code",
    "keywords",
]

#: ``en`` columns get a space inserted at a wrap seam; everything else
#: concatenates. Getting this wrong is the largest source of "right rows, wrong
#: cells", so it is stated explicitly rather than guessed.
JOINS = {
    "name": "en",
    "municipality": "en",
    "keywords": "en",
    **{name: "code" for name in COLUMNS if name not in ("name", "municipality", "keywords")},
}

#: The defects planted here are the recoverable ones. ``overflow`` and
#: ``placeholder`` are inherently lossy — one destroys a neighbour's value, the
#: other destroys its own — so they live in the synthetic fixture, which can
#: arrange an empty neighbour and an explicit expected loss.
COUNTS = {
    "split_word": 3,
    "swallow_space": 3,
    "double_space": 3,
    "hyphen_wrap": 2,
    "interleave": 2,
    "overflow": 0,
    "placeholder": 2,
}


def bar(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def load_dataset(
    path: Path, limit: int, stride: int
) -> tuple[list[str], list[list[str]], int]:
    """Stream a spread of rows out of the file, then prepend a sequence column.

    Streamed rather than loaded: the source is ~86,000 rows and 12 MB, and
    materialising all of it costs far more memory than sampling 400 rows does.

    A stride rather than the first N rows, because consecutive rows in this file
    are near-duplicates (same country, same region), which would make the
    fixture artificially easy.

    Rows containing characters outside Latin-1 are skipped — the simulator
    renders with a Base-14 font, which cannot represent them. Roughly 5% of
    rows are affected. The count is returned so the report can say so.
    """
    sampled: list[list[str]] = []
    skipped = 0
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        source_header = next(reader)
        wanted = [source_header.index(name) for name in COLUMNS]
        for i, row in enumerate(reader):
            if i % stride:
                continue
            values = [row[j].strip() for j in wanted]
            if not is_representable(values):
                skipped += 1
                continue
            sampled.append(values)
            if len(sampled) >= limit:
                break

    header = ["no", *COLUMNS]
    rows = [[str(i + 1), *row] for i, row in enumerate(sampled)]
    return header, rows, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(PUBLIC / "airports.csv"))
    parser.add_argument("--outdir", default=str(PUBLIC))
    parser.add_argument("--rows", type=int, default=400)
    parser.add_argument("--stride", type=int, default=193)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)

    source = Path(args.csv)
    if not source.exists():
        print(f"missing {source}\nrun: python examples/fetch_public.py", file=sys.stderr)
        return 2

    outdir = Path(args.outdir)
    header, rows, skipped = load_dataset(source, args.rows, args.stride)

    # --- 1. build a realistic export of it ------------------------------
    bar("1. simulate a print-to-PDF export of real data")
    # A4 landscape, seventeen columns: the tight layout a data dump actually
    # gets, which is what forces long values to wrap.
    layout = plan_layout(
        header,
        rows,
        page_width=842.0,
        page_height=595.0,
        font_size=6.0,
        margin=26.0,
        rows_per_page=42,
        joins=JOINS,
    )
    defects = plan_defects(rows, layout, seed=args.seed, counts=COUNTS)
    pdf_path = outdir / "airports.pdf"
    result = render_export(header, rows, layout, defects, pdf_path)
    truth_path = write_ground_truth(header, rows, outdir / "airports_ground_truth.csv")
    spec = spec_for(layout)

    print(f"   source    : {source.name} (OurAirports, public domain)")
    print(f"   table     : {len(rows)} rows x {spec.n_columns} columns")
    if skipped:
        print(f"   skipped   : {skipped} row(s) outside Latin-1 (Base-14 font limit)")
    print(
        f"   page      : {layout.page_width:.0f} x {layout.page_height:.0f} pt, "
        f"{layout.font_size} pt type"
    )
    print(f"   planted   : {len(result.applied)} defect(s) {result.summary()}")
    for defect in result.applied:
        print(f"     · {defect}")
    if result.skipped:
        print(f"   skipped   : {len(result.skipped)} (not physically applicable)")

    with open(truth_path, encoding="utf-8-sig", newline="") as fh:
        truth = list(csv.reader(fh))[1:]

    # The ``####`` cells are destroyed by design; they must be reported, not fixed.
    placeholder_cells = {
        (d.row, spec.names.index(d.column))
        for d in result.applied
        if d.kind == "placeholder"
    }

    doc = pymupdf.open(pdf_path)

    # --- 2. strategy -----------------------------------------------------
    bar("2. choose an extraction strategy")
    probe = probe_strategy(doc)
    print(f"   strategy  : {probe.strategy}")
    print(f"   because   : {probe.reason}")

    # --- 3. naive --------------------------------------------------------
    bar("3. naive extraction (geometry only)")
    extracted = extract_rows(doc, spec)
    print(f"   rows      : {len(extracted)}  (truth: {len(truth)})")
    naive = compare_all_modes(extracted, spec, truth)
    _report_modes(naive)

    # --- 4. repair -------------------------------------------------------
    bar("4. repair")
    repaired = repair(extracted, spec, targets=truth, dictionary=load_dictionary())
    for line in repaired.log[:18]:
        print(f"   · {line}")
    if len(repaired.log) > 18:
        print(f"   · ... and {len(repaired.log) - 18} more")
    after = compare_all_modes(extracted, spec, truth)
    _report_modes(after)

    remaining = {(d.row - 1, d.col) for d in after["hard"]}
    unexpected = remaining - placeholder_cells
    if placeholder_cells:
        print(f"   unrecoverable: {len(placeholder_cells)} cell(s) rendered as ####")
        for row, col in sorted(placeholder_cells):
            print(f"     row {row + 1} {spec.names[col]}: the PDF lost the value")
    print(f"   unexpected differences: {len(unexpected)}")
    for row, col in sorted(unexpected)[:6]:
        print(f"     row {row + 1} {spec.names[col]}: {extracted[row].value(col, spec)!r}"
              f" != {truth[row][col]!r}")

    # --- 5. independent evidence -----------------------------------------
    bar("5. independent verification (no reference used)")
    counters = pdf_band_counters(doc, spec)
    expected = repaired.expected_conservation_failures
    problems = char_conservation(
        extracted, spec, counters, allow_extra_in=expected, allow_missing_in=expected
    )
    print(f"   per-row conservation  : {len(problems)} unexplained row(s)")
    for anchor, extra, missing in problems[:5]:
        print(f"     anchor {anchor}: extra={dict(extra)} missing={dict(missing)}")
    extra, missing = global_char_conservation(extracted, spec, counters)
    print(
        "   document-wide         : OK -- no character created or lost"
        if not extra and not missing
        else f"   document-wide         : extra={dict(extra)} missing={dict(missing)}"
    )

    # --- 6. write and read back ------------------------------------------
    bar("6. write XLSX and read it back")
    xlsx = to_xlsx(extracted, spec, outdir / "airports_extracted.xlsx", header=spec.names)
    mismatches = verify_written_xlsx(xlsx, extracted, spec)
    print(f"   wrote {xlsx.name}")
    print(f"   read-back : {'OK' if not mismatches else f'{len(mismatches)} mismatch(es)'}")

    doc.close()

    # --- 7. verdict ------------------------------------------------------
    bar("7. verdict")
    ok = (
        not unexpected
        and not problems
        and not mismatches
        and not extra
        and not missing
        and len(extracted) == len(truth)
    )
    print(f"   rows recovered           : {len(extracted)} / {len(truth)}")
    print(
        f"   content differences      : {len(after['hard'])}"
        f"  ({len(placeholder_cells)} unrecoverable, {len(unexpected)} unexpected)"
    )
    print(f"   whitespace differences   : {len(after['soft'])}")
    print(f"   byte differences         : {len(after['exact'])}")
    print(f"   characters created/lost  : {sum(extra.values()) + sum(missing.values())}")
    print(f"   {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _report_modes(results: dict) -> None:
    counts = {mode: len(diffs) for mode, diffs in results.items()}
    print(
        f"   wrong cells: exact {counts['exact']}, "
        f"whitespace {counts['soft']}, content {counts['hard']}"
    )


if __name__ == "__main__":
    sys.exit(main())
