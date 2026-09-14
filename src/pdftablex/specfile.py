"""Serialise a :class:`~pdftablex.config.TableSpec` to and from JSON.

Keeping the layout in a data file rather than in code is what makes the
extractor reusable across documents: you re-measure the column edges, write
them down, and the same algorithm runs on a completely different table.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import AnchorSpec, Column, PageSpec, TableSpec


def spec_to_dict(spec: TableSpec) -> dict:
    return {
        "right_edge": spec.right_edge,
        "columns": [
            {"name": c.name, "left": c.left, "kind": c.kind} for c in spec.columns
        ],
        "anchor": {
            "column": spec.anchor.column,
            "max_x": spec.anchor.max_x,
            "min_digits": spec.anchor.min_digits,
            "max_digits": spec.anchor.max_digits,
            "placeholder": spec.anchor.placeholder,
            "spill_column": spec.anchor.spill_column,
        },
        "page": {
            "data_top": spec.page.data_top,
            "first_page_data_top": spec.page.first_page_data_top,
            "footer_bottom": spec.page.footer_bottom,
            "watermarks": sorted(spec.page.watermarks),
            "subline_gap": spec.page.subline_gap,
        },
    }


def spec_from_dict(data: dict) -> TableSpec:
    anchor = data.get("anchor", {})
    page = data.get("page", {})
    return TableSpec(
        columns=[Column(c["name"], c["left"], c.get("kind", "en")) for c in data["columns"]],
        right_edge=data["right_edge"],
        anchor=AnchorSpec(
            column=anchor.get("column", 0),
            max_x=anchor.get("max_x", 60.0),
            min_digits=anchor.get("min_digits", 1),
            max_digits=anchor.get("max_digits", 5),
            placeholder=anchor.get("placeholder", "####"),
            spill_column=anchor.get("spill_column", 1),
        ),
        page=PageSpec(
            data_top=page.get("data_top"),
            first_page_data_top=page.get("first_page_data_top"),
            footer_bottom=page.get("footer_bottom"),
            watermarks=frozenset(page.get("watermarks", ())),
            subline_gap=page.get("subline_gap", 1.2),
        ),
    )


def load_spec(path: str | Path) -> TableSpec:
    with open(path, encoding="utf-8") as fh:
        return spec_from_dict(json.load(fh))


def save_spec(spec: TableSpec, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec_to_dict(spec), fh, indent=2, ensure_ascii=False)
