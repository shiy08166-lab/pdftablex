"""Render-based forensics.

The text layer and the rendered page are two different things, and when they
disagree **the rendered page wins**. Real exports contain all of:

* characters stored in the wrong order (``PEAELNLIGOYOC`` renders as
  ``ALPINE ECOLOGY``),
* invisible leftover fragments that are in the data but were never painted,
* symbols that have a glyph but map to a space because the font's ``ToUnicode``
  table is incomplete (the degree sign is the classic offender).

None of those are visible to a text-only tool. Rendering the region and looking
at it is the only way to adjudicate, which is why this module exists: it turns
"where is row 931?" into a PNG you can inspect.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

#: 5-7x is the sweet spot: glyph shapes and marks are legible without the image
#: becoming unwieldy.
DEFAULT_ZOOM = 6.0


def render_region(
    doc,
    page_index: int,
    rect: pymupdf.Rect | tuple[float, float, float, float],
    out_path: str | Path,
    zoom: float = DEFAULT_ZOOM,
    padding: tuple[float, float] = (6.0, 10.0),
) -> Path:
    """Render a rectangle of a page to a PNG and return its path.

    ``padding`` is ``(above, below)`` in PDF points; a little vertical slack
    keeps ascenders and descenders inside the frame.
    """
    if not isinstance(rect, pymupdf.Rect):
        rect = pymupdf.Rect(*rect)
    above, below = padding
    clip = pymupdf.Rect(rect.x0, rect.y0 - above, rect.x1, rect.y1 + below)

    page = doc[page_index]
    matrix = pymupdf.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, clip=clip)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(out))
    return out


def render_row(
    doc,
    page_index: int,
    y_top: float,
    y_bottom: float,
    out_path: str | Path,
    x_range: tuple[float, float] | None = None,
    zoom: float = DEFAULT_ZOOM,
) -> Path:
    """Render one horizontal slice of a page -- typically a single table row.

    Locating the slice from the *extracted* sub-line y coordinates is far more
    reliable than re-searching for anchors, especially on pages where every
    anchor is a ``####`` placeholder.
    """
    page = doc[page_index]
    x0, x1 = x_range if x_range else (0.0, page.rect.width)
    return render_region(doc, page_index, (x0, y_top, x1, y_bottom), out_path, zoom=zoom)


def render_page(doc, page_index: int, out_path: str | Path, zoom: float = 2.0) -> Path:
    """Render a whole page at a modest zoom -- useful for eyeballing layout."""
    page = doc[page_index]
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(str(out))
    return out
