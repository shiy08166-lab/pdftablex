"""Tests for the export simulator and its round trip through the pipeline.

The simulator is a test fixture, so it needs its own test: a fixture that
silently plants nothing would make the pipeline look better than it is. These
tests assert that defects are actually applied, and that the pipeline recovers
every recoverable one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from export_sim import (
    Defect,
    ExportLayout,
    SimColumn,
    is_representable,
    plan_defects,
    render_export,
    spec_for,
    text_width,
    wrap_text,
)

from pdftablex import (
    compare_rows,
    extract_rows,
    global_char_conservation,
    pdf_band_counters,
    repair,
)
from pdftablex.repair import load_dictionary

HEADER = ["no", "code", "name", "note"]
JOINS = {"no": "code", "code": "code", "name": "en", "note": "en"}

# Deliberately prose-like and shaped so the dictionary-guided defects are
# actually applicable: each value wraps to a short first line plus a single long
# word, and that word has a split point that is not itself a word.
#
# The first version of this fixture used realistic airport names, which wrapped
# differently and left two thirds of the requested defects unplanted — a fixture
# that quietly tests less than it claims to.
NAMES = [
    "Central Regional Administration",
    "Northern Municipal Administration",
    "Eastern District Administration",
    "Western Highland Administration",
    "Coastal Riverside Administration",
    "Southern Lowland Administration",
    "Inland Plateau Administration",
    "Upland Valley Administration",
]


def build_rows(count: int = 40) -> list[list[str]]:
    return [
        [
            str(i + 1),
            f"XX-{1000 + i}",
            NAMES[i % len(NAMES)],
            f"paved runway {i}",
        ]
        for i in range(count)
    ]


def make_layout(rows):
    """A fixed, narrow layout.

    Explicit widths rather than :func:`plan_layout`: the widths are the whole
    point of this fixture. ``name`` must be narrow enough that a long airport
    name wraps, or every defect that needs a two-line cell is silently skipped —
    which is exactly the failure this test exists to catch.
    """
    return ExportLayout(
        page_width=280.0,
        page_height=842.0,
        font_size=7.5,
        margin=20.0,
        rows_per_page=40,
        columns=[
            SimColumn("no", 22.0, "code"),
            SimColumn("code", 60.0, "code"),
            SimColumn("name", 90.0, "en"),
            SimColumn("note", 60.0, "en"),
        ],
    )


# --------------------------------------------------------------------------
# wrapping and measurement
# --------------------------------------------------------------------------


def test_text_width_grows_with_content():
    assert text_width("a", 10.0) < text_width("aaaaaaaaaa", 10.0)


def test_wrap_text_breaks_on_words():
    lines = wrap_text("Central Regional Airport", 40.0, 7.0)
    assert len(lines) > 1
    assert " ".join(lines) == "Central Regional Airport"


def test_wrap_text_hard_breaks_a_long_token():
    # A narrow column cannot word-wrap an identifier, so it is cut mid-token —
    # which is why `code` columns concatenate when rejoining.
    lines = wrap_text("XX-1234567890", 20.0, 7.0)
    assert len(lines) > 1
    assert "".join(lines) == "XX-1234567890"


def test_empty_value_wraps_to_one_empty_line():
    assert wrap_text("", 100.0, 7.0) == [""]


# --------------------------------------------------------------------------
# representability
# --------------------------------------------------------------------------


def test_is_representable_accepts_latin1():
    assert is_representable(["Zürich", "São Paulo", "10.10"])


def test_is_representable_rejects_beyond_latin1():
    # The simulator renders with a Base-14 font, which cannot round-trip these.
    assert not is_representable(["Loučeň"])
    assert not is_representable(["中文"])
    assert not is_representable(["Délı̨nę"])


# --------------------------------------------------------------------------
# the planner must only plant defects it can actually plant
# --------------------------------------------------------------------------


def test_planned_defects_are_all_applicable():
    rows = build_rows()
    layout = make_layout(rows)
    counts = {"split_word": 3, "swallow_space": 3, "double_space": 3, "interleave": 2}
    defects = plan_defects(rows, layout, seed=3, counts=counts)

    result = render_export(HEADER, rows, layout, defects, Path(__file__).parent / "_t.pdf")
    try:
        # The whole point: nothing the planner chose was physically impossible.
        assert result.skipped == [], f"planner planted impossible defects: {result.skipped}"
        assert len(result.applied) == sum(counts.values())
    finally:
        (Path(__file__).parent / "_t.pdf").unlink(missing_ok=True)


def test_planner_leaves_the_next_row_clean():
    rows = build_rows()
    layout = make_layout(rows)
    defects = plan_defects(rows, layout, seed=5, counts={"interleave": 2, "split_word": 2})
    touched = {d.row for d in defects}
    assert not (touched & {r + 1 for r in touched}), "defects must not be adjacent"


def test_planner_respects_zero_counts():
    rows = build_rows()
    layout = make_layout(rows)
    assert plan_defects(rows, layout, counts={"split_word": 0}) == []


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------


def test_simulated_export_round_trips_to_zero(tmp_path):
    """The headline claim: a simulated export is fully recoverable."""
    rows = build_rows(60)
    layout = make_layout(rows)
    counts = {"split_word": 3, "swallow_space": 3, "double_space": 3, "interleave": 2}
    defects = plan_defects(rows, layout, seed=3, counts=counts)

    pdf = tmp_path / "export.pdf"
    result = render_export(HEADER, rows, layout, defects, pdf)
    assert len(result.applied) == sum(counts.values())

    spec = spec_for(layout)
    doc = pymupdf.open(pdf)
    extracted = extract_rows(doc, spec)
    doc.close()

    assert len(extracted) == len(rows)

    naive = compare_rows(extracted, spec, rows)
    assert naive, "the fixture is supposed to be broken before repair"

    repair(extracted, spec, targets=rows, dictionary=load_dictionary())
    assert compare_rows(extracted, spec, rows) == []
    assert compare_rows(extracted, spec, rows, mode="soft") == []


def test_placeholder_defect_is_lossy_by_design(tmp_path):
    """``####`` destroys the value; the pipeline must report it, not invent it."""
    rows = build_rows(20)
    layout = make_layout(rows)
    defects = [Defect(5, "code", "placeholder")]

    pdf = tmp_path / "export.pdf"
    result = render_export(HEADER, rows, layout, defects, pdf)
    assert [d.kind for d in result.applied] == ["placeholder"]

    spec = spec_for(layout)
    doc = pymupdf.open(pdf)
    extracted = extract_rows(doc, spec)
    doc.close()

    repair(extracted, spec, targets=rows, dictionary=load_dictionary())
    diffs = compare_rows(extracted, spec, rows)
    assert len(diffs) == 1
    assert diffs[0].candidate == "####"
    assert diffs[0].col == spec.names.index("code")


def test_overflow_refuses_an_ambiguous_boundary(tmp_path):
    """ASCII spilling into ASCII cannot be recovered; the repair declines."""
    rows = [["1", "XX-1001", "A" * 60, "padded runway"]]
    layout = make_layout(rows)
    result = render_export(
        HEADER, rows, layout, [Defect(0, "name", "overflow")], tmp_path / "export.pdf"
    )
    if not result.applied:
        pytest.skip("value did not overflow at this width")

    spec = spec_for(layout)
    doc = pymupdf.open(tmp_path / "export.pdf")
    extracted = extract_rows(doc, spec)
    doc.close()

    repaired = repair(extracted, spec, targets=rows, dictionary=load_dictionary())
    assert not any("move-overflow" in line for line in repaired.log), (
        "an ASCII-to-ASCII boundary must not be guessed at"
    )


def test_conservation_balances_when_case_folding_expands(tmp_path):
    """``'ß'.upper()`` is two characters.

    Normalising a band one character at a time records a single ``'SS'`` key;
    normalising it as a whole string records two ``'S'`` keys. The two sides of
    the conservation check would then be measuring different alphabets, and a
    correct extraction would be reported as having lost characters.
    """
    rows = [["1", "DE-1001", "Strasse Straße", "paved apron"]]
    layout = make_layout(rows)
    render_export(HEADER, rows, layout, [], tmp_path / "export.pdf")

    spec = spec_for(layout)
    doc = pymupdf.open(tmp_path / "export.pdf")
    extracted = extract_rows(doc, spec)
    counters = pdf_band_counters(doc, spec)
    extra, missing = global_char_conservation(extracted, spec, counters)
    doc.close()

    assert not extra, f"characters invented: {dict(extra)}"
    assert not missing, f"characters lost: {dict(missing)}"
