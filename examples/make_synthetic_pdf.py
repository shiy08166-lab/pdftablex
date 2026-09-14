"""Generate a synthetic, entirely fictional PDF that reproduces real export defects.

Nothing here comes from any real document. The subject matter is deliberately
unrelated to the kind of data this toolkit was first built for: it is a
fictional library catalogue, invented in code, so the whole example can be
committed and shared without a second thought.

What it reproduces -- these are the defects that actually show up in
print-to-PDF exports, and each one is here on purpose:

===================  ==========================================================
Defect               Where
===================  ==========================================================
word split by a      row 4:  ``ENCYCLOPE`` + ``DIA``
hard wrap
slash-hidden split   row 8:  ``INDEX/CATALO`` + ``GUE``
swallowed space      row 21: ``MANUSCRIP`` + ``TCOLLECTION``
double space         row 25: ``ATLAS  OF`` (rendered with two spaces)
hyphen wrap          row 16: ``FIELD-`` + ``GUIDE``
CJK wrap             row 13: ``山地`` + ``植物志``
column overflow      row 19: an over-long English title bleeds into the
                     next (empty) column
interleaved wrap     rows 31/32: a wrap line sits *below* the next row's
                     first line, so midpoint banding mis-assigns it
watermark            every page: wide-tracked ``S A M P L E   D A T A``
footer               every page
===================  ==========================================================

Run it::

    python examples/make_synthetic_pdf.py --outdir examples/synthetic

It writes ``catalogue.pdf``, ``catalogue_ground_truth.csv`` and ``spec.json``.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pymupdf

from pdftablex import AnchorSpec, Column, PageSpec, TableSpec, save_spec

# --------------------------------------------------------------------------
# Layout constants (PDF points). These are what the spec below describes.
# --------------------------------------------------------------------------

PAGE_W, PAGE_H = 595.0, 842.0
FS = 7.5
ROW_PITCH = 12.0
WRAP_GAP = 5.0  # normal leading inside a wrapped cell
INTERLEAVED_GAP = 7.5  # deliberately too large: pushes the wrap line into the next band
EN_WRAP_WIDTH = 32  # characters before the exporter wraps
ROWS_PER_PAGE = 40

HEADER_Y = 52.0
FIRST_ROW_Y = 76.0
WATERMARK_Y = 300.0
FOOTER_Y = 820.0

RENDER_X = {
    "no": 45.0,
    "title_cn": 72.0,
    "title_en": 154.0,
    "subject_cn": 354.0,
    "call_code": 444.0,
    "year": 509.0,
}


def build_spec() -> TableSpec:
    """The layout description for the synthetic catalogue."""
    return TableSpec(
        columns=[
            Column("no", 45.0, "code"),
            Column("title_cn", 68.0, "cjk"),
            Column("title_en", 150.0, "en"),
            Column("subject_cn", 350.0, "cjk"),
            Column("call_code", 440.0, "code"),
            Column("year", 505.0, "digit"),
        ],
        right_edge=545.0,
        anchor=AnchorSpec(column=0, max_x=66.0, spill_column=None),
        page=PageSpec(
            # The header baseline sits at 52 (bbox top ~44) and the first data
            # row at 76 (bbox top ~68), so 60 separates them on every page.
            data_top=60.0,
            footer_bottom=800.0,
            watermarks=frozenset({"SAMPLEDATA"}),
            subline_gap=1.2,
        ),
    )


# --------------------------------------------------------------------------
# Fictional content
# --------------------------------------------------------------------------

_SUBJECTS = [
    "MOUNTAIN", "COASTAL", "DESERT", "BOREAL", "URBAN", "RIVER",
    "ALPINE", "TROPICAL", "ESTUARINE", "GRASSLAND",
]
_TOPICS = [
    "FLORA", "FAUNA", "GEOLOGY", "CLIMATE", "HYDROLOGY",
    "SOILS", "MIGRATION", "ECOLOGY",
]
_REGIONS = ["NORTHERN", "SOUTHERN", "EASTERN", "WESTERN", "CENTRAL", "DELTAIC"]

_TITLES_CN = [
    "山地植物志", "海岸鸟类图鉴", "沙漠地质概论", "北方森林生态",
    "城市水文研究", "河流沉积分析", "高山土壤调查", "热带雨林笔记",
    "河口湿地手册", "草原昆虫图谱", "岩层构造导论", "湖泊富营养化",
]
_SUBJECTS_CN = [
    "植物学", "动物学", "地质学", "气象学", "水文学", "土壤学", "生态学", "地理学",
]
_AUTHORS = [
    "ELLISON M", "HARUKA T", "OKONKWO A", "MARCHETTI L", "SORENSEN K",
    "BAUER R", "NAKAMURA S", "DUBOIS C",
]


def _title_en(i: int) -> str:
    return (
        f"{_SUBJECTS[i % len(_SUBJECTS)]} {_TOPICS[(i * 3) % len(_TOPICS)]} "
        f"OF THE {_REGIONS[(i * 5) % len(_REGIONS)]} REGION"
    )


def _call_code(i: int) -> str:
    return f"PZ.{i % 90 + 10:02d}.{(i * 7) % 90 + 10:02d}"


def build_dataset(n_rows: int = 60) -> list[dict[str, str]]:
    """The logical (correct) values, i.e. the ground truth."""
    rows: list[dict[str, str]] = []
    for i in range(n_rows):
        rows.append(
            {
                "no": str(i + 1),
                "title_cn": _TITLES_CN[i % len(_TITLES_CN)],
                "title_en": _title_en(i),
                "subject_cn": _SUBJECTS_CN[(i * 3) % len(_SUBJECTS_CN)],
                "call_code": _call_code(i),
                "year": str(1970 + (i * 7) % 51),
            }
        )

    # --- the deliberately defective rows (0-based indices) -----------------
    rows[3]["title_en"] = "ENCYCLOPEDIA OF ALPINE ECOLOGY"
    rows[7]["title_en"] = "INDEX/CATALOGUE OF NORTHERN FLORA"
    rows[12]["title_cn"] = "山地植物志图鉴汇编"
    rows[15]["title_en"] = "FIELD-GUIDE TO THE COASTAL ZONE"
    rows[18]["title_en"] = "COMPREHENSIVE SURVEY OF ESTUARINE HYDROLOGY"
    rows[18]["subject_cn"] = ""  # left blank so the overflow has somewhere to go
    rows[20]["title_en"] = "MANUSCRIPT COLLECTION OF THE DELTAIC PLAIN"
    rows[24]["title_en"] = "ATLAS OF THE RIVER BASIN"
    rows[30]["title_en"] = "BIBLIOGRAPHY OF BOREAL MIGRATION PATTERNS"
    rows[31]["title_en"] = "CHRONICLE OF URBAN ECOLOGY SURVEYS"
    return rows


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def wrap_at_words(text: str, width: int) -> list[str]:
    """Greedy word wrapping -- what a spreadsheet exporter would do."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _insert(page, x: float, y: float, text: str, cjk: bool = False) -> None:
    if not text:
        return
    page.insert_text(
        (x, y),
        text,
        fontsize=FS,
        fontname="china-s" if cjk else "helv",
        color=(0, 0, 0),
    )


def _emit_row(page, y: float, row: dict[str, str], index: int) -> None:
    """Render one logical row, injecting the defect that belongs to it."""
    _insert(page, RENDER_X["no"], y, row["no"])

    # --- CJK title: row 13 is wrapped across two lines ---------------------
    if index == 12:
        _insert(page, RENDER_X["title_cn"], y, "山地", cjk=True)
        _insert(page, RENDER_X["title_cn"], y + WRAP_GAP, "植物志图鉴汇编", cjk=True)
    else:
        _insert(page, RENDER_X["title_cn"], y, row["title_cn"], cjk=True)

    # --- English title ----------------------------------------------------
    text = row["title_en"]

    if index == 3:  # hard wrap splits ENCYCLOPEDIA
        _insert(page, RENDER_X["title_en"], y, "ENCYCLOPE")
        _insert(page, RENDER_X["title_en"], y + WRAP_GAP, "DIA OF ALPINE ECOLOGY")
    elif index == 7:  # split hidden behind a slash
        _insert(page, RENDER_X["title_en"], y, "INDEX/CATALO")
        _insert(page, RENDER_X["title_en"], y + WRAP_GAP, "GUE OF NORTHERN FLORA")
    elif index == 15:  # wrap after a hyphen
        _insert(page, RENDER_X["title_en"], y, "FIELD-")
        _insert(page, RENDER_X["title_en"], y + WRAP_GAP, "GUIDE TO THE COASTAL ZONE")
    elif index == 18:  # never wrapped: overflows into the next column
        _insert(page, RENDER_X["title_en"], y, text)
    elif index == 20:  # the wrap ate the space
        _insert(page, RENDER_X["title_en"], y, "MANUSCRIP")
        _insert(page, RENDER_X["title_en"], y + WRAP_GAP, "TCOLLECTION OF THE DELTAIC PLAIN")
    elif index == 24:  # double space inside one line
        _insert(page, RENDER_X["title_en"], y, text.replace(" OF ", "  OF "))
    elif index == 30:  # wrap line placed too low -> lands in the next row's band
        lines = wrap_at_words(text, EN_WRAP_WIDTH)
        _insert(page, RENDER_X["title_en"], y, lines[0])
        _insert(page, RENDER_X["title_en"], y + INTERLEAVED_GAP, " ".join(lines[1:]))
    else:
        lines = wrap_at_words(text, EN_WRAP_WIDTH)
        _insert(page, RENDER_X["title_en"], y, lines[0])
        for k, line in enumerate(lines[1:], start=1):
            _insert(page, RENDER_X["title_en"], y + k * WRAP_GAP, line)

    _insert(page, RENDER_X["subject_cn"], y, row["subject_cn"], cjk=True)
    _insert(page, RENDER_X["call_code"], y, row["call_code"])
    _insert(page, RENDER_X["year"], y, row["year"])


def _emit_furniture(page) -> None:
    """Watermark and footer -- both must be filtered out, not extracted."""
    page.insert_text(
        (90.0, WATERMARK_Y),
        "S A M P L E   D A T A",
        fontsize=30,
        fontname="helv",
        color=(0.85, 0.85, 0.85),
    )
    page.insert_text(
        (150.0, FOOTER_Y),
        "DEMO LIBRARY / SYNTHETIC DATA / NOT REAL",
        fontsize=7,
        fontname="helv",
        color=(0.4, 0.4, 0.4),
    )


def build_pdf(path: str | Path, rows: list[dict[str, str]]) -> Path:
    doc = pymupdf.open()
    for start in range(0, len(rows), ROWS_PER_PAGE):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for name, x in RENDER_X.items():
            page.insert_text((x, HEADER_Y), name, fontsize=7.5, fontname="helv", color=(0, 0, 0))
        for offset, row in enumerate(rows[start : start + ROWS_PER_PAGE]):
            index = start + offset
            _emit_row(page, FIRST_ROW_Y + offset * ROW_PITCH, row, index)
        _emit_furniture(page)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    doc.close()
    return out


def write_ground_truth(path: str | Path, rows: list[dict[str, str]]) -> Path:
    columns = list(rows[0].keys())
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([row[c] for c in columns])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", default="examples/synthetic")
    parser.add_argument("--rows", type=int, default=60)
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    rows = build_dataset(args.rows)

    pdf = build_pdf(outdir / "catalogue.pdf", rows)
    truth = write_ground_truth(outdir / "catalogue_ground_truth.csv", rows)
    spec = save_spec(build_spec(), outdir / "spec.json") or outdir / "spec.json"

    print(f"wrote {pdf}")
    print(f"wrote {truth}")
    print(f"wrote {spec}")
    print(f"{len(rows)} fictional rows, {len(rows[0])} columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
