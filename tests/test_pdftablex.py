"""Test suite.

Run with ``pytest`` from the repository root. The end-to-end test builds the
synthetic catalogue PDF on the fly, so the suite needs no fixture files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

import pymupdf
from make_synthetic_pdf import (
    build_dataset,
    build_pdf,
    build_spec,
    write_ground_truth,
)

from pdftablex import (
    Column,
    PageSpec,
    TableSpec,
    char_conservation,
    classify,
    compare_rows,
    extract_rows,
    global_char_conservation,
    hard,
    join_sublines,
    pdf_band_counters,
    probe_strategy,
    repair,
    soft,
    to_xlsx,
    verify_written_xlsx,
)
from pdftablex.repair import load_dictionary
from pdftablex.verify import Diff

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------


def test_spec_rejects_descending_columns():
    with pytest.raises(ValueError, match="ascending"):
        TableSpec(columns=[Column("b", 200.0), Column("a", 100.0)], right_edge=300.0)


def test_spec_requires_right_edge_past_last_column():
    with pytest.raises(ValueError, match="right_edge"):
        TableSpec(columns=[Column("a", 100.0)], right_edge=90.0)


def test_column_of_uses_half_open_intervals():
    spec = TableSpec(
        columns=[Column("a", 10.0), Column("b", 20.0)], right_edge=30.0
    )
    assert spec.column_of(9.9) == -1
    assert spec.column_of(10.0) == 0
    assert spec.column_of(19.99) == 0
    assert spec.column_of(20.0) == 1
    assert spec.column_of(30.0) == -1


def test_page_top_prefers_first_page_override():
    page = PageSpec(data_top=60.0, first_page_data_top=80.0)
    assert page.top_for(0) == 80.0
    assert page.top_for(1) == 60.0


# --------------------------------------------------------------------------
# join rules
# --------------------------------------------------------------------------


def test_join_code_concatenates():
    assert join_sublines(0, ["PZ.10.10.", "03"], "code") == "PZ.10.10.03"


def test_join_cjk_concatenates_without_a_space():
    assert join_sublines(0, ["山地植物志", "图鉴汇编"], "cjk") == (
        "山地植物志图鉴汇编"
    )


def test_join_english_inserts_a_space():
    assert join_sublines(0, ["BOREAL", "ECOLOGY"], "en") == "BOREAL ECOLOGY"


def test_join_english_does_not_double_a_trailing_hyphen():
    assert join_sublines(0, ["FIELD-", "GUIDE TO THE COASTAL ZONE"], "en") == "FIELD-GUIDE TO THE COASTAL ZONE"


def test_join_english_still_inserts_a_space_at_a_cjk_seam():
    # An English column keeps its space rule even when the wrap lands on a CJK
    # fragment; only the CJK and code kinds concatenate blindly.
    assert join_sublines(0, ["ALPINE", "生态学"], "en") == "ALPINE 生态学"


# --------------------------------------------------------------------------
# normalisation and classification
# --------------------------------------------------------------------------


def test_hard_ignores_notation_and_case():
    assert hard("PZ.10.10") == hard("PZ1010")
    assert hard("fi eld-guide") == hard("FIELDGUIDE")


def test_hard_hides_word_splits_that_soft_catches():
    # This is why three comparison levels exist.
    assert hard("MANUSCRIP T") == hard("MANUSCRIPT")
    assert soft("MANUSCRIP T") != soft("MANUSCRIPT")
    assert soft("ATLAS  OF") == soft("ATLAS OF")


def test_classify_marker_corruption():
    d = classify(Diff(1, 0, "。 植物志", "° 植物志"))
    assert d.kind == "marker-corruption"


def test_classify_reordered_text_layer():
    target = "ALPINE ECOLOGY"
    # Same characters, different order: the classic "text layer is jumbled but
    # the page looks fine" signature.
    scrambled = "".join(sorted(hard(target)))
    d = classify(Diff(1, 0, scrambled, target))
    assert d.kind == "text-layer-reordered"


def test_classify_truncation():
    assert classify(Diff(1, 0, "ATTACH/COM", "ATTACH/COMP")).kind == "candidate-truncated"
    assert classify(Diff(1, 0, "ATTACH/COMPX", "ATTACH/COMP")).kind == "reference-truncated"


def test_classify_overprint():
    d = classify(Diff(1, 0, "WW204815", "W204815"))
    assert d.kind == "overprint"


def test_classify_real_difference_is_not_excused():
    d = classify(Diff(1, 0, "ALPHA", "OMEGA"))
    assert d.kind == "content-difference"


# --------------------------------------------------------------------------
# end to end on the synthetic catalogue
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def catalogue(tmp_path_factory):
    outdir = tmp_path_factory.mktemp("catalogue")
    data = build_dataset(60)
    pdf = build_pdf(outdir / "catalogue.pdf", data)
    truth = write_ground_truth(outdir / "catalogue_ground_truth.csv", data)
    spec = build_spec()
    targets = [[r[c] for c in spec.names] for r in data]
    return {"pdf": pdf, "truth": truth, "spec": spec, "targets": targets}


def test_probe_detects_borderless(catalogue):
    doc = pymupdf.open(catalogue["pdf"])
    assert probe_strategy(doc).strategy == "borderless"
    doc.close()


def test_row_count_matches(catalogue):
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, catalogue["spec"])
    doc.close()
    assert len(rows) == len(catalogue["targets"])


def test_naive_extraction_is_wrong_but_repairable(catalogue):
    spec = catalogue["spec"]
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, spec)
    naive = compare_rows(rows, spec, catalogue["targets"])
    assert naive, "the fixture is supposed to contain defects"

    repair(rows, spec, targets=catalogue["targets"], dictionary=load_dictionary())
    assert compare_rows(rows, spec, catalogue["targets"]) == []
    doc.close()


def test_repair_reaches_byte_equality(catalogue):
    spec = catalogue["spec"]
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, spec)
    repair(rows, spec, targets=catalogue["targets"], dictionary=load_dictionary())
    assert compare_rows(rows, spec, catalogue["targets"], mode="soft") == []
    assert compare_rows(rows, spec, catalogue["targets"], mode="exact") == []
    doc.close()


def test_character_conservation_balances(catalogue):
    spec = catalogue["spec"]
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, spec)
    result = repair(rows, spec, targets=catalogue["targets"], dictionary=load_dictionary())
    counters = pdf_band_counters(doc, spec)
    expected = result.expected_conservation_failures
    problems = char_conservation(
        rows, spec, counters, allow_extra_in=expected, allow_missing_in=expected
    )
    assert problems == []
    extra, missing = global_char_conservation(rows, spec, counters)
    assert not extra and not missing
    doc.close()


def test_xlsx_round_trip_is_lossless(catalogue, tmp_path):
    spec = catalogue["spec"]
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, spec)
    repair(rows, spec, targets=catalogue["targets"], dictionary=load_dictionary())
    out = to_xlsx(rows, spec, tmp_path / "out.xlsx", header=spec.names)
    assert verify_written_xlsx(out, rows, spec) == []
    doc.close()


def test_reference_free_extraction_still_balances(catalogue):
    """Without a reference, only the dictionary and mechanical operators run."""
    spec = catalogue["spec"]
    doc = pymupdf.open(catalogue["pdf"])
    rows = extract_rows(doc, spec)
    repair(rows, spec, targets=None, dictionary=load_dictionary())
    counters = pdf_band_counters(doc, spec)
    extra, missing = global_char_conservation(rows, spec, counters)
    assert not extra and not missing, "repair must never create or destroy characters"
    doc.close()
