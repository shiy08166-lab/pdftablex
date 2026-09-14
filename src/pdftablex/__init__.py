"""pdftablex -- high-fidelity recovery of tabular data from PDF exports.

The short version of the method:

1. A PDF is a bag of coordinate-carrying text fragments, not a table. Rebuild
   rows by geometry -- anchors for rows, character centres for columns.
2. The rendered page is ground truth. The text layer can be jumbled, hold
   invisible fragments, or map symbols to spaces.
3. Never assert correctness; demonstrate it. Compare against a reference where
   one exists, and prove character conservation where one does not.
4. Repair only what you can justify. Anything else is reported, not guessed.
"""

from .config import AnchorSpec, Column, PageSpec, TableSpec
from .detect import ProbeResult, extract_bordered, probe_strategy
from .export import rows_as_lists, to_csv, to_xlsx, verify_written_xlsx
from .geometry import Char, Frag, Obj, Row, extract_rows
from .join import collapse_spaces, is_cjk, join_sublines
from .render import render_page, render_region, render_row
from .repair import RepairResult, load_dictionary, repair
from .specfile import load_spec, save_spec, spec_from_dict, spec_to_dict
from .verify import (
    Diff,
    VerificationReport,
    char_conservation,
    classify,
    classify_all,
    compare_all_modes,
    compare_rows,
    exact,
    global_char_conservation,
    hard,
    hard_key,
    pdf_band_counters,
    soft,
    summarize,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # config
    "Column",
    "AnchorSpec",
    "PageSpec",
    "TableSpec",
    # geometry
    "Char",
    "Obj",
    "Frag",
    "Row",
    "extract_rows",
    # join
    "join_sublines",
    "collapse_spaces",
    "is_cjk",
    # repair
    "repair",
    "RepairResult",
    "load_dictionary",
    # verify
    "hard",
    "soft",
    "exact",
    "hard_key",
    "Diff",
    "compare_rows",
    "compare_all_modes",
    "classify",
    "classify_all",
    "summarize",
    "char_conservation",
    "global_char_conservation",
    "pdf_band_counters",
    "VerificationReport",
    # detect
    "probe_strategy",
    "ProbeResult",
    "extract_bordered",
    # render
    "render_region",
    "render_row",
    "render_page",
    # export
    "to_xlsx",
    "to_csv",
    "rows_as_lists",
    "verify_written_xlsx",
    # specfile
    "load_spec",
    "save_spec",
    "spec_to_dict",
    "spec_from_dict",
]
