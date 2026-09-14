"""Choose the extraction strategy for a PDF.

There are two kinds of printable table and they want opposite approaches:

**Bordered tables** -- the exporter drew real vector grid lines. PyMuPDF's
``find_tables()`` reads those lines directly and is both faster and more
accurate than any geometric reconstruction. Use it. A 460-page bordered export
resolves in minutes with perfect column counts.

**Borderless tables** -- alignment is done with whitespace only. There are no
lines to find, so ``find_tables()`` returns nothing useful and you must
reconstruct the grid from character coordinates (see :mod:`pdftablex.geometry`).

Deciding this up front saves a lot of wasted effort. The probe is deliberately
cheap: look at a handful of pages, count how many expose at least one table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Strategy = Literal["bordered", "borderless", "unknown"]


@dataclass
class ProbeResult:
    strategy: Strategy
    pages_probed: int
    pages_with_tables: int
    rows_seen: int

    @property
    def reason(self) -> str:
        if self.strategy == "bordered":
            return (
                f"{self.pages_with_tables}/{self.pages_probed} probed pages expose a table; "
                "use find_tables()"
            )
        if self.strategy == "borderless":
            return (
                f"only {self.pages_with_tables}/{self.pages_probed} probed pages expose a table; "
                "reconstruct the grid from character coordinates"
            )
        return "not enough pages to decide"


def probe_strategy(
    doc,
    probe_pages: int = 3,
    min_hit_ratio: float = 0.6,
) -> ProbeResult:
    """Decide whether ``doc`` is a bordered or borderless table export."""
    total = doc.page_count
    if total == 0:
        return ProbeResult("unknown", 0, 0, 0)

    indices = list(range(min(probe_pages, total)))
    if total > probe_pages:
        # Sample the tail too: first pages can differ from the body.
        indices += [total - 1]

    hits = 0
    rows = 0
    for i in indices:
        page = doc[i]
        try:
            finder = page.find_tables()
        except Exception:  # pragma: no cover - older PyMuPDF builds
            continue
        tables = getattr(finder, "tables", None) or []
        if tables:
            hits += 1
            biggest = max(tables, key=lambda t: t.row_count)
            rows += biggest.row_count

    ratio = hits / len(indices) if indices else 0.0
    if ratio >= min_hit_ratio:
        strategy: Strategy = "bordered"
    elif hits == 0:
        strategy = "borderless"
    else:
        # A partial hit usually means decorative lines rather than a real grid.
        strategy = "borderless"
    return ProbeResult(strategy, len(indices), hits, rows)


def extract_bordered(doc, pages=None) -> list[dict]:
    """Extract bordered tables with ``find_tables()``.

    Returns one entry per page that contained a table::

        {"page": 1, "table_index": 0, "rows": [[...], ...]}

    The largest table on each page wins -- smaller ones are usually header or
    footer boxes.
    """
    out: list[dict] = []
    indices = range(doc.page_count) if pages is None else pages

    for i in indices:
        page = doc[i]
        try:
            finder = page.find_tables()
        except Exception:  # pragma: no cover
            continue
        tables = getattr(finder, "tables", None) or []
        for ti, table in enumerate(tables):
            data = table.extract()
            if not data:
                continue
            out.append(
                {
                    "page": i + 1,
                    "table_index": ti,
                    "n_rows": len(data),
                    "n_cols": max((len(r) for r in data), default=0),
                    "rows": data,
                }
            )
    return out
