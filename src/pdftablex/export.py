"""Write extracted rows out as CSV or XLSX.

Two details matter more than they look:

1. **Everything is text.** Excel will happily turn ``10.10`` into a date and
   a long numeric id into scientific notation. Setting the number format to
   ``@`` on every cell is not cosmetic, it is correctness.
2. **Read back after writing.** Writing is a step that can fail on its own, so
   :func:`verify_written_xlsx` re-reads the file and compares. A pipeline that
   only checks its in-memory state has not checked anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font

from .config import TableSpec
from .geometry import Row
from .verify import hard


def rows_as_lists(rows: Sequence[Row], spec: TableSpec) -> list[list[str]]:
    return [row.values(spec) for row in rows]


def to_csv(
    rows: Sequence[Row],
    spec: TableSpec,
    path: str | Path,
    header: Sequence[str] | None = None,
) -> Path:
    """Write rows to CSV (UTF-8 with BOM, so Excel opens it correctly)."""
    import csv

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        if header:
            writer.writerow(list(header))
        writer.writerows(rows_as_lists(rows, spec))
    return out


def to_xlsx(
    rows: Sequence[Row],
    spec: TableSpec,
    path: str | Path,
    sheet_name: str = "data",
    header: Sequence[str] | None = None,
    freeze_header: bool = True,
) -> Path:
    """Write rows to XLSX with every cell forced to text format."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    start = 1
    if header:
        ws.append(list(header))
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(vertical="center")
        start = 2

    for values in rows_as_lists(rows, spec):
        ws.append(values)

    for row in ws.iter_rows(
        min_row=start, max_row=ws.max_row, min_col=1, max_col=ws.max_column
    ):
        for cell in row:
            cell.number_format = "@"
            cell.alignment = Alignment(vertical="center", wrap_text=False)

    if freeze_header and header:
        ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    wb.close()
    return out


def verify_written_xlsx(
    path: str | Path,
    rows: Sequence[Row],
    spec: TableSpec,
    header_rows: int = 1,
) -> list[tuple[int, int, str, str]]:
    """Read the file back and compare it against the rows we meant to write.

    Returns ``(row, col, expected, found)`` for every cell that differs.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    mismatches: list[tuple[int, int, str, str]] = []

    expected = rows_as_lists(rows, spec)
    for i, want in enumerate(expected):
        excel_row = i + 1 + header_rows
        for col, want_value in enumerate(want, start=1):
            got = ws.cell(excel_row, col).value
            got_text = "" if got is None else str(got)
            if hard(got_text) != hard(want_value):
                mismatches.append((excel_row, col, want_value, got_text))

    wb.close()
    return mismatches
