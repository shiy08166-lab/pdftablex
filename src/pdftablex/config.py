"""Layout description for a printed table.

Everything document-specific lives here, so the extraction algorithm itself
never contains a hard-coded coordinate. A ``TableSpec`` is the single object
you hand to :func:`pdftablex.geometry.extract_rows`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

#: How wrapped sub-lines inside one cell are stitched back together.
#:
#: ``code``  -- no separator (``PZ.10.10.`` + ``03``)
#: ``cjk``   -- no separator (``山地植物志`` + ``图鉴汇编``)
#: ``en``    -- space, unless the previous line ends with ``-``
#: ``digit`` -- decide from the characters on both sides of the seam
JoinKind = Literal["code", "cjk", "en", "digit"]

_JOIN_KINDS = ("code", "cjk", "en", "digit")


@dataclass(frozen=True)
class Column:
    """One column of the table.

    ``left`` is the x coordinate that a character's *centre* must reach to be
    assigned to this column. It is measured from the header row of the real
    document -- run ``pdftablex recon`` to read those numbers off.
    """

    name: str
    left: float
    kind: JoinKind = "en"

    def __post_init__(self) -> None:
        if self.kind not in _JOIN_KINDS:
            raise ValueError(f"unknown join kind {self.kind!r}; expected one of {_JOIN_KINDS}")


@dataclass
class AnchorSpec:
    """How to recognise the column that identifies a logical row.

    The anchor is normally a sequential number, but exporters often merge it
    into the same text object as the neighbouring cell (``'1093 Alpine'``),
    so the anchor is detected **character by character**, not per object.
    """

    column: int = 0
    #: A character only counts as part of the anchor if its centre is left of this.
    max_x: float = 60.0
    min_digits: int = 1
    max_digits: int = 5
    #: Excel prints ``####`` when a numeric column is too narrow. Those rows are
    #: still valid rows, and the real value is unrecoverable from the PDF.
    placeholder: str = "####"
    #: Fragments that land in the anchor column but are *not* the anchor are a
    #: degenerate left-shift caused by the exporter; move them here. ``None``
    #: discards them instead.
    spill_column: int | None = 1


@dataclass
class PageSpec:
    """Per-page furniture that must not be mistaken for data."""

    #: Text above this y is a repeated page header. Applied to **every** page,
    #: which is what exporters usually do.
    data_top: float | None = None
    #: Overrides ``data_top`` on page 1 only, for documents whose first page
    #: carries an extra title block that later pages do not.
    first_page_data_top: float | None = None
    #: Text below this y is the page footer.
    footer_bottom: float | None = None
    #: Repeated watermark strings, compared with whitespace removed.
    watermarks: frozenset[str] = frozenset()
    #: Two fragments belong to the same sub-line when their baseline gap is
    #: at most this. Tune it against ``recon`` output.
    subline_gap: float = 1.2

    def top_for(self, page_index: int) -> float | None:
        """The header cutoff that applies to ``page_index`` (0-based)."""
        if page_index == 0 and self.first_page_data_top is not None:
            return self.first_page_data_top
        return self.data_top


@dataclass
class TableSpec:
    """Complete layout description."""

    columns: Sequence[Column]
    #: Right-hand outer edge of the data area. With N columns this makes
    #: N + 1 boundaries -- supplying only N silently shifts every column.
    right_edge: float
    anchor: AnchorSpec = field(default_factory=AnchorSpec)
    page: PageSpec = field(default_factory=PageSpec)

    def __post_init__(self) -> None:
        if len(self.columns) < 1:
            raise ValueError("at least one column is required")
        lefts = [c.left for c in self.columns]
        if lefts != sorted(lefts):
            raise ValueError("column left edges must be ascending")
        if self.right_edge <= lefts[-1]:
            raise ValueError("right_edge must be greater than the last column's left edge")
        if not 0 <= self.anchor.column < len(self.columns):
            raise ValueError("anchor.column is out of range")

    @property
    def n_columns(self) -> int:
        return len(self.columns)

    @property
    def left_edges(self) -> list[float]:
        """N + 1 boundaries used for :func:`bisect.bisect_right`."""
        return [c.left for c in self.columns] + [self.right_edge]

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column_of(self, cx: float) -> int:
        """Column index for a character whose centre is at ``cx``, or -1."""
        import bisect

        idx = bisect.bisect_right(self.left_edges, cx) - 1
        if 0 <= idx < self.n_columns:
            return idx
        return -1
