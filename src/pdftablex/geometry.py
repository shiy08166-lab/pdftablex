"""Reconstruct logical rows from a PDF character layer.

The central idea: **a PDF is not a table, it is a bag of text fragments that
happen to carry coordinates.** There is no grid, no notion of rows or columns,
and the order in which fragments appear in the content stream is unrelated to
the order a human reads them.

So rows are recovered by *geometry*:

1. find the row anchors (normally the sequence-number column),
2. cut the page into bands at the midpoints between consecutive anchors,
3. assign every character to a column by its own centre x,
4. stitch the fragments inside a cell into sub-lines, then into one value.

Steps 1 and 3 must operate on **characters**, never on whole text objects.
Exporters routinely merge two logical cells into one object (``'1093 Bracket'``)
or split one logical cell across a dozen objects.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import NamedTuple

from .config import TableSpec
from .join import join_sublines


class Char(NamedTuple):
    """A single character with its bounding box."""

    cx: float  # centre x
    x0: float
    x1: float
    c: str


class Obj(NamedTuple):
    """One text object (a PDF ``line``), kept in content-stream order."""

    y: float
    chars: list[Char]
    text: str


@dataclass
class Frag:
    """A run of characters that belong to one column of one row."""

    y: float
    x0: float
    x1: float
    text: str


@dataclass
class Row:
    """One logical table row, assembled from fragments."""

    page: int  # 1-based
    anchor: int | str
    frags: dict[int, list[Frag]] = field(default_factory=dict)
    #: Working state: column -> [(y, text)] sub-lines. Repair operators mutate this.
    sublines: dict[int, list[tuple[float, str]]] = field(default_factory=dict)
    flags: dict[str, set[int]] = field(default_factory=dict)

    def value(self, col: int, spec: TableSpec) -> str:
        """The stitched text of one cell."""
        if col == spec.anchor.column:
            return str(self.anchor)
        texts = [t for _, t in self.sublines.get(col, [])]
        return join_sublines(col, texts, spec.columns[col].kind)

    def values(self, spec: TableSpec) -> list[str]:
        return [self.value(c, spec) for c in range(spec.n_columns)]

    def subline_texts(self, col: int) -> list[str]:
        return [t for _, t in self.sublines.get(col, [])]

    def set_subline_texts(self, col: int, texts: Sequence[str]) -> None:
        """Replace sub-lines with bare text, keeping existing y where possible."""
        old = self.sublines.get(col, [])
        self.sublines[col] = [
            (old[i][0] if i < len(old) else 0.0, t) for i, t in enumerate(texts)
        ]


def iter_objects(page, page_index: int, spec: TableSpec) -> list[Obj]:
    """Yield the text objects of one page, sorted by y, with furniture removed.

    Drops page-1 header, page footer and known watermark objects. Watermarks
    matter more than they look: a wide-tracked string like ``I N T E R N A L``
    drops single characters into arbitrary columns and manufactures hundreds of
    phantom differences.
    """
    ps = spec.page
    top_cutoff = ps.top_for(page_index)
    raw = page.get_text("rawdict")
    objects: list[Obj] = []

    for block in raw.get("blocks", ()):
        for line in block.get("lines", ()):
            chars: list[Char] = []
            for span in line.get("spans", ()):
                for ch in span.get("chars", ()):
                    x0, y0, x1, _y1 = ch["bbox"]
                    if top_cutoff is not None and y0 <= top_cutoff:
                        continue
                    chars.append(Char((x0 + x1) / 2.0, x0, x1, ch["c"]))
            if not chars:
                continue
            y = line["bbox"][1]
            if ps.footer_bottom is not None and y > ps.footer_bottom:
                continue
            if ps.watermarks:
                squeezed = "".join(c.c for c in chars).replace(" ", "")
                if squeezed in ps.watermarks:
                    continue
            objects.append(Obj(y, chars, "".join(c.c for c in chars)))

    objects.sort(key=lambda o: o.y)
    return objects


def detect_anchor(chars: Sequence[Char], spec: TableSpec) -> int | str | None:
    """Read the row anchor off a text object.

    Character-level on purpose: ``'1093 MCU cover'`` is a single object in most
    exports, so object-level tests would miss the row entirely.

    Returns the integer sequence number, the placeholder string (``'####'``)
    when the exporter truncated a too-narrow numeric column, or ``None`` if
    this object does not start a row.
    """
    a = spec.anchor
    run: list[str] = []
    kind: str | None = None

    for ch in sorted(chars, key=lambda c: c.x0):
        if ch.c.isdigit() and ch.cx < a.max_x and kind in (None, "d"):
            run.append(ch.c)
            kind = "d"
        elif ch.c == "#" and ch.cx < a.max_x and kind in (None, "#"):
            run.append(ch.c)
            kind = "#"
        elif ch.c == " ":
            continue
        else:
            break

    if kind == "d" and a.min_digits <= len(run) <= a.max_digits:
        return int("".join(run))
    if kind == "#":
        return a.placeholder
    return None


def _band_index(y: float, anchors: Sequence[tuple[int, float]]) -> int:
    """Which band does ``y`` fall into? Bands are cut at anchor midpoints.

    A row's own sub-lines may sit a few points *above* its anchor -- that is
    normal stacking, not a page-spanning continuation.
    """
    last = len(anchors) - 1
    for k, (_oi, ay) in enumerate(anchors):
        top = (anchors[k - 1][1] + ay) / 2.0 if k > 0 else float("-inf")
        bot = (anchors[k + 1][1] + ay) / 2.0 if k < last else float("inf")
        if top <= y < bot:
            return k
    return last


def build_sublines(frags: Sequence[Frag], gap: float) -> list[tuple[float, str]]:
    """Group fragments of one cell into sub-lines by baseline proximity."""
    if not frags:
        return []
    ordered = sorted(frags, key=lambda f: (f.y, f.x0))
    groups: list[list[Frag]] = [[ordered[0]]]
    for frag in ordered[1:]:
        if frag.y - groups[-1][-1].y <= gap:
            groups[-1].append(frag)
        else:
            groups.append([frag])
    return [
        (g[0].y, "".join(f.text for f in sorted(g, key=lambda f: f.x0)).strip())
        for g in groups
    ]


def extract_rows(doc, spec: TableSpec, pages: Sequence[int] | None = None) -> list[Row]:
    """Extract every logical row of ``doc`` according to ``spec``.

    ``pages`` is an optional 0-based page selection; ``None`` means all pages.
    """
    rows: list[Row] = []
    page_range = range(doc.page_count) if pages is None else pages

    for page_index in page_range:
        page = doc[page_index]
        objects = iter_objects(page, page_index, spec)
        if not objects:
            continue

        # --- 1. anchors -------------------------------------------------
        anchors: list[tuple[int, float]] = []  # (object index, anchor y)
        for oi, obj in enumerate(objects):
            value = detect_anchor(obj.chars, spec)
            if value is not None:
                anchors.append((oi, obj.y))
        if not anchors:
            continue

        anchor_values: list[int | str] = [
            detect_anchor(objects[oi].chars, spec) for oi, _ in anchors
        ]
        anchor_objects = {oi for oi, _ in anchors}

        page_rows = [
            Row(page=page_index + 1, anchor=value)  # type: ignore[arg-type]
            for value in anchor_values
        ]

        # --- 2 & 3. banding + character-level column assignment ----------
        spill_col = spec.anchor.spill_column
        for oi, obj in enumerate(objects):
            row = page_rows[_band_index(obj.y, anchors)]
            row.flags.setdefault("boundary", set())
            row.flags.setdefault("clip", set())
            row.flags.setdefault("overlap", set())

            runs: list[tuple[int, list[Char]]] = []
            for ch in obj.chars:
                col = spec.column_of(ch.cx)
                if col < 0:
                    continue
                # Record which *boundaries* a character straddles. This is the
                # reliable signal that a cell's text overflowed into its
                # neighbour: the overflow character sits in the right column but
                # its ink starts left of the boundary.
                for b, boundary in enumerate(spec.left_edges):
                    if b == 0 or b == len(spec.left_edges) - 1:
                        continue
                    if ch.x0 < boundary - 0.05 and ch.x1 > boundary + 0.05:
                        row.flags["boundary"].add(b)
                if runs and runs[-1][0] == col:
                    runs[-1][1].append(ch)
                else:
                    runs.append((col, [ch]))

            for col, chars in runs:
                ordered = sorted(chars, key=lambda c: c.cx)
                text = "".join(c.c for c in ordered).strip()
                if not text:
                    continue
                for a, b in pairwise(ordered):
                    if b.x0 < a.x1 - 0.3:
                        row.flags["overlap"].add(col)
                if col < spec.n_columns - 1:
                    right = spec.left_edges[col + 1]
                    if max(c.x1 for c in ordered) >= right - 0.45:
                        row.flags["clip"].add(col)

                target = col
                if col == spec.anchor.column and oi not in anchor_objects:
                    # A stray fragment sitting in the anchor column is a
                    # degenerate left-shift, not a sequence number.
                    if spill_col is None:
                        continue
                    target = spill_col
                row.frags.setdefault(target, []).append(
                    Frag(obj.y, min(c.x0 for c in ordered), max(c.x1 for c in ordered), text)
                )

        # --- 4. sub-lines ------------------------------------------------
        for row in page_rows:
            for col in range(spec.n_columns):
                row.sublines[col] = build_sublines(
                    row.frags.get(col, []), spec.page.subline_gap
                )

        rows.extend(page_rows)

    return rows
