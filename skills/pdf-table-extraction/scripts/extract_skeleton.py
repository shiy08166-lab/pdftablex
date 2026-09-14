#!/usr/bin/env python3
"""Single-file reference implementation of the extraction core.

This is a **fallback**, for when the ``pdftablex`` package cannot be installed.
It implements the two moves that matter — anchor banding and character-level
column assignment — in one file with no package structure. It does *not*
implement the repair operators, the verification checks or the exporters. For
those, install the real thing:

    pip install pymupdf openpyxl english-words
    pip install -e .

Usage
-----
    python extract_skeleton.py recon   document.pdf
    python extract_skeleton.py extract document.pdf

Edit the CONFIG block first. Run ``recon`` and read the printed coordinates to
measure your column edges; guessing them is the most common cause of a
one-column shift.

Dependency: ``pip install pymupdf``
"""

from __future__ import annotations

import bisect
import json
import sys

import pymupdf

# ============================== CONFIG ==============================
PDF = "document.pdf"
OUT = "extracted.json"

# Column left edges: the x a character's *centre* must reach to belong to that
# column. MUST have N+1 entries — N column edges plus the right outer edge.
# Supplying only N silently shifts every column by one.
LEFT_EDGES = [45.0, 68.0, 150.0, 350.0, 440.0, 505.0, 545.0]
COLUMNS = ["no", "title_cn", "title_en", "subject_cn", "call_code", "year"]

# How wrapped sub-lines inside one cell are rejoined.
#   code  -> concatenate          cjk  -> concatenate
#   en    -> space (or none after a trailing '-')
#   digit -> decide per seam from the neighbouring characters
JOIN_KINDS = {
    "no": "code",
    "title_cn": "cjk",
    "title_en": "en",
    "subject_cn": "cjk",
    "call_code": "code",
    "year": "digit",
}

ANCHOR_COLUMN = 0
ANCHOR_MAX_X = 66.0  # a digit only counts as part of the anchor left of this
ANCHOR_MAX_DIGITS = 5
ANCHOR_PLACEHOLDER = "####"  # Excel prints this when a numeric column is narrow

DATA_TOP = 60.0  # text above this y is the repeated page header
FOOTER_BOTTOM = 800.0  # text below this y is the page footer
WATERMARKS = {"SAMPLEDATA"}  # compared with whitespace removed
SUBLINE_GAP = 1.2  # baseline gap at or below which fragments share a sub-line
# ====================================================================

N_COLUMNS = len(COLUMNS)


def is_cjk(ch: str) -> bool:
    if not ch:
        return False
    return (
        "\u4e00" <= ch <= "\u9fff"
        or "\u3000" <= ch <= "\u303f"
        or "\uff00" <= ch <= "\uffef"
    )


def collect(page):
    """Text objects of one page, sorted by y, with furniture removed."""
    objects = []
    for block in page.get_text("rawdict").get("blocks", ()):
        for line in block.get("lines", ()):
            chars = []
            for span in line.get("spans", ()):
                for ch in span.get("chars", ()):
                    x0, y0, x1, _y1 = ch["bbox"]
                    if y0 <= DATA_TOP:
                        continue
                    chars.append(((x0 + x1) / 2.0, x0, x1, ch["c"]))
            if not chars:
                continue
            y = line["bbox"][1]
            if y > FOOTER_BOTTOM:
                continue
            squeezed = "".join(c for _, _, _, c in chars).replace(" ", "")
            if squeezed in WATERMARKS:
                continue
            objects.append((y, chars))
    objects.sort(key=lambda o: o[0])
    return objects


def detect_anchor(chars):
    """Character-level anchor detection.

    Object-level tests miss the common case where the sequence number and the
    adjacent cell share one object ('1093 Bracket').
    """
    run, kind = [], None
    for cx, _x0, _x1, c in sorted(chars, key=lambda t: t[1]):
        if c.isdigit() and cx < ANCHOR_MAX_X and kind in (None, "d"):
            run.append(c)
            kind = "d"
        elif c == "#" and cx < ANCHOR_MAX_X and kind in (None, "#"):
            run.append(c)
            kind = "#"
        elif c == " ":
            continue
        else:
            break
    if kind == "d" and 1 <= len(run) <= ANCHOR_MAX_DIGITS:
        return int("".join(run))
    return ANCHOR_PLACEHOLDER if kind == "#" else None


def join_cell(kind: str, texts) -> str:
    pieces = [t for t in texts if t]
    if not pieces:
        return ""
    out = pieces[0]
    for nxt in pieces[1:]:
        if kind == "code":
            out += nxt
        elif kind == "cjk":
            out += nxt if (is_cjk(out[-1]) and is_cjk(nxt[0])) else " " + nxt
        elif kind == "digit":
            if is_cjk(out[-1]) or is_cjk(nxt[0]) or (out[-1].isdigit() and nxt[0].isdigit()):
                out += nxt
            else:
                out += " " + nxt
        else:  # "en"
            out += nxt if out.endswith("-") else " " + nxt
    return out


def band_index(y: float, anchors) -> int:
    last = len(anchors) - 1
    for k, (_oi, ay) in enumerate(anchors):
        top = (anchors[k - 1][1] + ay) / 2.0 if k > 0 else float("-inf")
        bot = (anchors[k + 1][1] + ay) / 2.0 if k < last else float("inf")
        if top <= y < bot:
            return k
    return last


def recon(pdf_path: str, pages=(0, 1, -1)) -> None:
    doc = pymupdf.open(pdf_path)
    for p in pages:
        index = p if p >= 0 else doc.page_count + p
        page = doc[index]
        print(f"=== page {index + 1}  rect={page.rect} ===")
        for y, chars in collect(page)[:30]:
            x0 = min(c[1] for c in chars)
            x1 = max(c[2] for c in chars)
            text = "".join(c[3] for c in chars)
            print(f"  y={y:7.2f} x={x0:6.1f}-{x1:6.1f}  {text[:70]!r}")
        rules = sorted(
            {
                round(d["rect"].y0, 1)
                for d in page.get_drawings()
                if d["rect"].width > 100 and d["rect"].height < 1.5
            }
        )
        print(f"  horizontal rules at y: {rules[:12]}")
    doc.close()


def extract(pdf_path: str, out_path: str) -> list[dict]:
    doc = pymupdf.open(pdf_path)
    rows: list[dict] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        objects = collect(page)
        if not objects:
            continue

        anchors = [
            (i, obj[0]) for i, obj in enumerate(objects) if detect_anchor(obj[1]) is not None
        ]
        if not anchors:
            continue
        values = [detect_anchor(objects[i][1]) for i, _ in anchors]
        anchor_objects = {i for i, _ in anchors}

        page_rows = [
            {
                "page": page_index + 1,
                "anchor": v,
                "frags": {c: [] for c in range(N_COLUMNS)},
            }
            for v in values
        ]

        for i, (y, chars) in enumerate(objects):
            row = page_rows[band_index(y, anchors)]
            runs: list[tuple[int, list]] = []
            for cx, x0, _x1, c in chars:
                col = bisect.bisect_right(LEFT_EDGES, cx) - 1
                if not (0 <= col < N_COLUMNS):
                    continue
                if runs and runs[-1][0] == col:
                    runs[-1][1].append((cx, x0, c))
                else:
                    runs.append((col, [(cx, x0, c)]))
            for col, group in runs:
                text = "".join(c for _, _, c in sorted(group)).strip()
                if not text:
                    continue
                if col == ANCHOR_COLUMN and i not in anchor_objects:
                    continue  # a stray fragment in the anchor column
                row["frags"][col].append((y, min(g[1] for g in group), text))

        for row in page_rows:
            cells = []
            for col in range(N_COLUMNS):
                if col == ANCHOR_COLUMN:
                    cells.append(str(row["anchor"]))
                    continue
                frags = sorted(row["frags"][col], key=lambda t: (t[0], t[1]))
                if not frags:
                    cells.append("")
                    continue
                lines, last_y = [[frags[0][2]]], frags[0][0]
                for fy, _fx, ft in frags[1:]:
                    if fy - last_y > SUBLINE_GAP:
                        lines.append([ft])
                    else:
                        lines[-1].append(ft)
                    last_y = fy
                texts = ["".join(ln).strip() for ln in lines]
                cells.append(join_cell(JOIN_KINDS[COLUMNS[col]], texts))
            rows.append(
                {"page": row["page"], "anchor": row["anchor"], "cells": cells}
            )

    doc.close()
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f"extracted {len(rows)} row(s) -> {out_path}")
    print("NOTE: no repair, no verification. Use the real library for those.")
    return rows


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "recon"
    target = sys.argv[2] if len(sys.argv) > 2 else PDF
    if mode == "recon":
        recon(target)
    elif mode == "extract":
        extract(target, OUT)
    else:
        print(__doc__)
        raise SystemExit(2)
