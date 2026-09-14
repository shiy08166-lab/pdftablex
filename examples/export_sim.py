"""Simulate a print-to-PDF export of a CSV, with controllable defects.

Real exports are hard to obtain and often confidential, which makes them hard to
practise on. This module builds one: give it a CSV, get back a PDF that behaves
like a spreadsheet printed to PDF — plus the ground truth, so the pipeline has
something to be graded against.

The defects are not random noise. Each reproduces a failure mode from
[`docs/defect-taxonomy.md`](../docs/defect-taxonomy.md), and the planner only
plants splits it can justify: a mid-word break is placed where the prefix is
*not* itself a dictionary word and the rejoined word *is*. That keeps the
fixture fair — it tests whether the pipeline can recover, not whether it can
guess.

A defect is applied only where it is physically possible (a cell that wraps to
two lines, a value that actually overflows). :func:`render_export` reports which
defects were applied and which were skipped, so a test can assert on reality
rather than on intention.

Usage::

    from export_sim import plan_layout, plan_defects, render_export, spec_for

    layout = plan_layout(header, rows)
    defects = plan_defects(rows, layout, seed=7)
    result = render_export(header, rows, layout, defects, "out.pdf")
    print(result.applied)

The generated PDF is a *simulation*. It reproduces the geometry and the defect
signatures of a real export; it does not reproduce a real exporter's font
handling, kerning or pagination quirks.
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# --------------------------------------------------------------------------
# Font
# --------------------------------------------------------------------------
#
# PyMuPDF's Base-14 fonts cover Latin-1 and extract back exactly as written.
# Anything beyond that (Czech, Turkish, CJK, combining marks) is either dropped
# or replaced with a look-alike, which would make the *simulator* the source of
# the differences rather than the defects.
#
# So the simulator uses a Base-14 font and the caller filters out rows it cannot
# represent — see :func:`latin1_clean_rows`. A real export has no such
# restriction, and a real pipeline must handle what such an export contains.

BODY_FONT = "helv"


def text_width(text: str, font_size: float) -> float:
    """Width of ``text`` in points, in the font that will render it."""
    return pymupdf.get_text_length(text, fontname=BODY_FONT, fontsize=font_size)


def latin1_clean_rows(rows: list[list[str]]) -> list[list[str]]:
    """Drop rows containing characters the Base-14 font cannot represent."""
    return [row for row in rows if is_representable(row)]


def is_representable(row: list[str]) -> bool:
    """Can every cell of this row be rendered and extracted back unchanged?"""
    for cell in row:
        try:
            cell.encode("latin-1")
        except UnicodeEncodeError:
            return False
    return True


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SimColumn:
    """One rendered column.

    ``join`` must match the ``kind`` given to the corresponding
    ``pdftablex.Column`` — it is the contract for how a wrapped cell is
    reassembled.
    """

    name: str
    width: float
    join: str = "en"


@dataclass
class ExportLayout:
    page_width: float = 1191.0  # A3 landscape
    page_height: float = 842.0
    font_size: float = 6.5
    margin: float = 34.0
    header_y: float = 44.0
    first_row_y: float = 66.0
    row_pitch: float = 11.0
    wrap_gap: float = 4.6  # normal leading inside a wrapped cell
    interleave_gap: float = 7.4  # deliberately too large: lands in the next band
    rows_per_page: int = 62
    columns: list[SimColumn] = field(default_factory=list)
    watermark: str | None = "S P E C I M E N"
    footer: str | None = "PUBLIC DATA / GENERATED SAMPLE / NOT AN OFFICIAL EXPORT"

    @property
    def data_top(self) -> float:
        return self.header_y + 8.0

    @property
    def footer_bottom(self) -> float:
        return self.page_height - 40.0

    def x_of(self, index: int) -> float:
        return self.margin + sum(c.width for c in self.columns[:index])

    def right_edge(self) -> float:
        return self.margin + sum(c.width for c in self.columns)

    def names(self) -> list[str]:
        return [c.name for c in self.columns]


def plan_layout(
    header: list[str],
    rows: list[list[str]],
    *,
    page_width: float = 1191.0,
    page_height: float = 842.0,
    font_size: float = 6.5,
    margin: float = 34.0,
    rows_per_page: int = 62,
    joins: dict[str, str] | None = None,
) -> ExportLayout:
    """Size each column in proportion to the text it actually holds.

    Widths come from each column's 95th-percentile content length, so a column
    of ISO timestamps does not get the same space as a column of place names.
    Roughly what a spreadsheet does before you print it.
    """
    joins = joins or {}
    weights: list[float] = []
    for i, name in enumerate(header):
        lengths = sorted(len(r[i]) for r in rows)
        p95 = lengths[min(len(lengths) - 1, int(len(lengths) * 0.95))] if lengths else 1
        weights.append(max(float(p95), float(len(name))) + 2.0)

    available = page_width - 2 * margin
    total = sum(weights)
    widths = [available * w / total for w in weights]

    return ExportLayout(
        page_width=page_width,
        page_height=page_height,
        font_size=font_size,
        margin=margin,
        rows_per_page=rows_per_page,
        columns=[
            SimColumn(name, widths[i], joins.get(name, guess_join(rows, i)))
            for i, name in enumerate(header)
        ],
    )


def guess_join(rows: list[list[str]], index: int) -> str:
    """Pick a join kind from the data, erring toward concatenation.

    Pure numerics map to ``code``, not ``digit``: ``digit`` decides per seam
    from the neighbouring characters and would insert a space into ``35.`` +
    ``371``. Concatenation is the correct rule for numbers.
    """
    values = [r[index] for r in rows if r[index]]
    if not values:
        return "en"
    if all(" " not in v for v in values):
        return "code"
    return "en"


def wrap_text(text: str, width: float, font_size: float) -> list[str]:
    """Word-wrap, then hard-break any token still too wide.

    The hard break is what a spreadsheet does to a long identifier in a narrow
    column — and it is why ``code`` columns must concatenate rather than insert
    a space when rejoining.
    """
    if not text:
        return [""]

    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if not current or text_width(candidate, font_size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    broken: list[str] = []
    for line in lines:
        while len(line) > 1 and text_width(line, font_size) > width:
            cut = len(line)
            while cut > 1 and text_width(line[:cut], font_size) > width:
                cut -= 1
            broken.append(line[:cut])
            line = line[cut:]
        broken.append(line)
    return [b for b in broken if b] or [""]


# --------------------------------------------------------------------------
# Defects
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Defect:
    row: int  # 0-based
    column: str
    kind: str

    def __str__(self) -> str:
        return f"row {self.row + 1} {self.column}: {self.kind}"


DEFECT_KINDS = (
    "split_word",
    "swallow_space",
    "double_space",
    "hyphen_wrap",
    "interleave",
    "overflow",
    "placeholder",
)

DEFAULT_COUNTS = {
    "split_word": 3,
    "swallow_space": 3,
    "double_space": 3,
    "hyphen_wrap": 2,
    "interleave": 2,
    "overflow": 2,
    "placeholder": 2,
}


def load_dictionary() -> frozenset[str]:
    """The English word list, loaded once per process.

    Building the 234k-word set is not free, and the simulator asks for it on
    every dictionary-guided defect.
    """
    global _DICTIONARY
    if _DICTIONARY is None:
        try:
            from english_words import get_english_words_set

            _DICTIONARY = frozenset(get_english_words_set(["web2"], lower=True))
        except Exception:  # pragma: no cover - optional dependency
            _DICTIONARY = frozenset()
    return _DICTIONARY


_DICTIONARY: frozenset[str] | None = None


def _applies(
    kind: str,
    row: list[str],
    column: str,
    index_of: dict[str, int],
    layout: ExportLayout,
    dictionary: frozenset[str],
) -> bool:
    """Can this defect actually be planted in this cell?

    Checking before choosing is the difference between a fixture that tests the
    pipeline and a fixture that mostly tests the planner. The first version of
    this module picked rows at random and then discovered the defect was
    physically impossible — nine of fifteen defects silently did nothing.
    """
    ci = index_of[column]
    value = row[ci]
    if not value:
        return False
    width = layout.columns[ci].width - 2.0

    if kind == "placeholder":
        return True
    if kind == "overflow":
        return (
            text_width(value, layout.font_size) > width and ci + 1 < len(layout.columns)
        )
    if kind == "hyphen_wrap":
        return force_hyphen_break(value, width, layout.font_size) is not None

    lines = wrap_text(value, width, layout.font_size)
    if kind == "split_word":
        return force_word_split(lines, dictionary, width, layout.font_size) is not None
    if kind == "swallow_space":
        return force_swallow_space(lines, dictionary, width, layout.font_size) is not None
    if kind == "double_space":
        return " " in lines[0]
    if kind == "interleave":
        # Three lines would spill into the row after next, which the
        # window-based repair is not built for.
        return len(lines) == 2
    return False


def plan_defects(
    rows: list[list[str]],
    layout: ExportLayout,
    *,
    seed: int = 7,
    counts: dict[str, int] | None = None,
    anchor_column: int = 0,
    dictionary: frozenset[str] | None = None,
) -> list[Defect]:
    """Choose a spread of defects that the data can actually host.

    At most one per row, and the row after each is left clean so that
    ``interleave`` has an undisturbed neighbour to be reassigned against.
    """
    rng = random.Random(seed)
    counts = dict(counts or DEFAULT_COUNTS)
    dictionary = load_dictionary() if dictionary is None else dictionary

    index_of = {c.name: i for i, c in enumerate(layout.columns)}
    en_columns = [c.name for c in layout.columns if c.join == "en"]
    code_columns = [c.name for c in layout.columns if c.join == "code"]
    # A placeholder in the anchor column would destroy the row identity itself.
    placeholder_columns = [
        c.name
        for c in layout.columns
        if c.join in ("code", "digit") and index_of[c.name] != anchor_column
    ]

    eligible = {
        "split_word": en_columns,
        "swallow_space": en_columns,
        "double_space": en_columns,
        "hyphen_wrap": en_columns + code_columns,
        "interleave": en_columns,
        "overflow": en_columns,
        "placeholder": placeholder_columns,
    }

    order = list(range(len(rows) - 1))
    rng.shuffle(order)
    used: set[int] = set()
    defects: list[Defect] = []

    for kind in DEFECT_KINDS:
        need = counts.get(kind, 0)
        columns = eligible.get(kind, [])
        if not need or not columns:
            continue
        shuffled = list(columns)
        rng.shuffle(shuffled)

        placed = 0
        for row in order:
            if placed >= need:
                break
            if row in used or row + 1 in used:
                continue
            for column in shuffled:
                if _applies(kind, rows[row], column, index_of, layout, dictionary):
                    defects.append(Defect(row, column, kind))
                    used.update({row, row + 1})
                    placed += 1
                    break

    return sorted(defects, key=lambda d: (d.row, d.column))


# --------------------------------------------------------------------------
# Defect transforms
# --------------------------------------------------------------------------


def force_word_split(
    lines: list[str],
    dictionary: frozenset[str],
    width: float | None = None,
    font_size: float = 0.0,
) -> list[str] | None:
    """Move a few characters of the next line's first word up, mid-word.

    Only accepted when the moved prefix is *not* a word and the whole word
    *is* — otherwise the repair has no justification and the fixture would be
    testing guesswork.

    The moved characters must also still fit the column. Appending to an
    already-full line pushes the tail past the boundary, where it is reassigned
    to the next column — which plants a *different* defect than the one
    intended, and one that is not recoverable.
    """
    if len(lines) < 2 or not lines[-1]:
        return None
    word = lines[-1].split()[0]
    rest = lines[-1].split()[1:]
    if len(word) < 5 or word.lower() not in dictionary:
        return None

    for take in range(3, len(word) - 1):
        prefix = word[:take]
        if prefix.lower() in dictionary:
            continue
        merged = f"{lines[-2]} {prefix}".strip()
        if width is not None and text_width(merged, font_size) > width:
            continue
        moved = list(lines)
        moved[-2] = merged
        moved[-1] = " ".join([word[take:], *rest]).strip()
        return [line for line in moved if line] or None
    return None


def force_swallow_space(
    lines: list[str],
    dictionary: frozenset[str],
    width: float | None = None,
    font_size: float = 0.0,
) -> list[str] | None:
    """Break inside a word *and* drop the space after it.

    ``MANUSCRIPT COLLECTION`` becomes ``MANUSCRIP`` + ``TCOLLECTION``. Requires
    both words to be in the dictionary, so the repair's split point is provable
    rather than plausible.
    """
    if len(lines) < 2 or not lines[-2] or not lines[-1]:
        return None
    left_words = lines[-2].split()
    right_words = lines[-1].split()
    if not left_words or not right_words:
        return None
    w1, w2 = left_words[-1], right_words[0]
    if len(w1) < 5 or len(w2) < 4:
        return None
    if w1.lower() not in dictionary or w2.lower() not in dictionary:
        return None
    if w1[:-1].lower() in dictionary:
        return None

    merged = " ".join([f"{w1[-1]}{w2}", *right_words[1:]])
    if width is not None and text_width(merged, font_size) > width:
        return None

    moved = list(lines)
    moved[-2] = " ".join([*left_words[:-1], w1[:-1]])
    moved[-1] = merged
    return moved


def force_hyphen_break(text: str, width: float, font_size: float) -> list[str] | None:
    """Break the line immediately after an existing hyphen."""
    position = text.find("-")
    while position != -1:
        head, tail = text[: position + 1], text[position + 1 :].lstrip()
        if head and tail and text_width(head, font_size) <= width:
            return [head, *wrap_text(tail, width, font_size)]
        position = text.find("-", position + 1)
    return None


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


@dataclass
class RenderResult:
    path: Path
    applied: list[Defect] = field(default_factory=list)
    skipped: list[Defect] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        from collections import Counter

        return dict(Counter(d.kind for d in self.applied))


def _insert(page, x: float, y: float, text: str, font_size: float) -> None:
    if text:
        page.insert_text((x, y), text, fontsize=font_size, fontname=BODY_FONT, color=(0, 0, 0))


def render_export(
    header: list[str],
    rows: list[list[str]],
    layout: ExportLayout,
    defects: list[Defect],
    out_path: str | Path,
) -> RenderResult:
    """Render the CSV as a print-to-PDF export, injecting the planned defects."""
    needs_dictionary = any(d.kind in ("split_word", "swallow_space") for d in defects)
    dictionary = load_dictionary() if needs_dictionary else frozenset()

    by_row: dict[int, dict[str, str]] = {}
    for defect in defects:
        by_row.setdefault(defect.row, {})[defect.column] = defect.kind

    result = RenderResult(path=Path(out_path))

    doc = pymupdf.open()
    for start in range(0, len(rows), layout.rows_per_page):
        page = doc.new_page(width=layout.page_width, height=layout.page_height)
        for i, col in enumerate(layout.columns):
            _insert(page, layout.x_of(i), layout.header_y, col.name, layout.font_size)

        for offset, row in enumerate(rows[start : start + layout.rows_per_page]):
            index = start + offset
            y = layout.first_row_y + offset * layout.row_pitch
            kinds = by_row.get(index, {})
            blanked: set[str] = set()

            for i, col in enumerate(layout.columns):
                if col.name in blanked:
                    continue
                value = row[i]
                kind = kinds.get(col.name)
                x = layout.x_of(i)
                usable = col.width - 2.0
                lines = wrap_text(value, usable, layout.font_size)
                applied = True

                if kind == "placeholder":
                    _insert(page, x, y, "#" * 4, layout.font_size)
                    result.applied.append(Defect(index, col.name, kind))
                    continue

                if kind == "overflow":
                    if text_width(value, layout.font_size) <= usable:
                        applied = False
                    else:
                        _insert(page, x, y, value, layout.font_size)
                        if i + 1 < len(layout.columns):
                            blanked.add(layout.columns[i + 1].name)
                        result.applied.append(Defect(index, col.name, kind))
                        continue

                elif kind == "split_word":
                    forced = force_word_split(lines, dictionary, usable, layout.font_size)
                    if forced is None:
                        applied = False
                    else:
                        lines = forced
                elif kind == "swallow_space":
                    forced = force_swallow_space(
                        lines, dictionary, usable, layout.font_size
                    )
                    if forced is None:
                        applied = False
                    else:
                        lines = forced
                elif kind == "double_space":
                    if " " not in lines[0]:
                        applied = False
                    else:
                        lines = [lines[0].replace(" ", "  ", 1), *lines[1:]]
                elif kind == "hyphen_wrap":
                    forced = force_hyphen_break(value, usable, layout.font_size)
                    if forced is None:
                        applied = False
                    else:
                        lines = forced
                elif kind == "interleave" and len(lines) != 2:
                    # Only meaningful when the cell wraps to exactly two lines;
                    # three would spill into the row after next.
                    applied = False

                if kind and applied:
                    result.applied.append(Defect(index, col.name, kind))
                elif kind:
                    result.skipped.append(Defect(index, col.name, kind))

                gap = (
                    layout.interleave_gap
                    if kind == "interleave" and applied
                    else layout.wrap_gap
                )
                for k, line in enumerate(lines):
                    _insert(page, x, y + k * gap, line, layout.font_size)

        if layout.watermark:
            page.insert_text(
                (layout.page_width * 0.22, layout.page_height * 0.45),
                layout.watermark,
                fontsize=26,
                fontname=BODY_FONT,
                color=(0.86, 0.86, 0.86),
            )
        if layout.footer:
            page.insert_text(
                (layout.page_width * 0.3, layout.page_height - 22),
                layout.footer,
                fontsize=6,
                fontname=BODY_FONT,
                color=(0.45, 0.45, 0.45),
            )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    doc.close()
    return result


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def ground_truth(rows: list[list[str]]) -> list[list[str]]:
    """The values a correct extraction must reproduce.

    Whitespace is collapsed: the PDF cannot represent a run of spaces inside a
    wrapped cell distinctly from a single one, so the fixture does not pretend
    otherwise. Everything else is preserved exactly.
    """
    return [[" ".join(cell.split()) for cell in row] for row in rows]


def write_ground_truth(header: list[str], rows: list[list[str]], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(ground_truth(rows))
    return out


def spec_for(layout: ExportLayout, *, anchor_column: int = 0):
    """Build the matching ``pdftablex.TableSpec``."""
    from pdftablex import AnchorSpec, Column, PageSpec, TableSpec

    left_edges = [layout.x_of(i) for i in range(len(layout.columns))]
    return TableSpec(
        columns=[
            Column(col.name, left_edges[i], col.join) for i, col in enumerate(layout.columns)
        ],
        right_edge=layout.right_edge(),
        anchor=AnchorSpec(
            column=anchor_column,
            max_x=left_edges[1] if len(left_edges) > 1 else left_edges[0] + 20.0,
            spill_column=None,
        ),
        page=PageSpec(
            data_top=layout.data_top,
            footer_bottom=layout.footer_bottom,
            watermarks=frozenset(
                {(layout.watermark or "").replace(" ", "")} if layout.watermark else set()
            ),
            subline_gap=1.2,
        ),
    )
