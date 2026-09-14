"""The evidence layer.

Extraction is easy to *claim* correct and hard to *prove* correct. This module
supplies the proof machinery:

``hard``
    A normalisation that strips pure notation (whitespace, hyphens, slashes,
    brackets, punctuation, degree marks) and upper-cases the rest. Two strings
    that differ only in *how* they are written compare equal.

``compare_rows``
    Cell-by-cell comparison against a reference, with every mismatch graded.

``classify``
    Names the reason a pair differs. The distinction that matters most is
    between "the candidate is wrong" and "the reference's text layer is
    lying" -- telling those apart is what stops you from "fixing" correct data.

``char_conservation``
    Compares the *multiset* of characters per row, ignoring order. Catches
    dropped, duplicated and bled-across characters and needs **no reference at
    all**, which makes it genuinely independent evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .config import TableSpec
from .geometry import _band_index, detect_anchor, iter_objects

#: Notation, never data. ``°`` is included because fonts frequently lose its
#: ToUnicode mapping and render it as a space.
_NOISE = re.compile(r"[\s\-_/\\()（）\[\]【】{},，.。:：;；°º′″'\"·•|]+")

#: Leading marks that get corrupted into look-alike characters.
_MARK_PREFIX = re.compile(r"^\s*[0Oo。º°·]+")


def hard(text: str | None) -> str:
    """Content-level normalisation: strip notation, upper-case.

    Use this to ask "is this the same datum, however it is written?".
    """
    return _NOISE.sub("", (text or "").upper())


def soft(text: str | None) -> str:
    """Whitespace-normalised comparison.

    Collapses runs of whitespace and trims. Catches the wrap artefacts that
    :func:`hard` deliberately hides -- ``MANUSCRIP T`` and ``MANUSCRIPT``
    are content-identical but *not* presentation-identical, and that difference
    is exactly what the dictionary-guided repairs are there to remove.
    """
    return " ".join((text or "").split())


def exact(text: str | None) -> str:
    """No normalisation at all."""
    return text or ""


#: Available comparison levels, weakest first.
MODES = {"hard": hard, "soft": soft, "exact": exact}


def hard_key(text: str | None) -> tuple[str, ...]:
    """Order-insensitive key: the sorted characters of ``hard(text)``."""
    return tuple(sorted(hard(text)))


@dataclass
class Diff:
    """One mismatching cell."""

    row: int  # 1-based index into the extracted rows
    col: int  # 0-based column index
    candidate: str  # value produced from the PDF
    reference: str  # value from the reference file
    kind: str = "unclassified"
    note: str = ""


def compare_rows(
    rows: Sequence,
    spec: TableSpec,
    targets: Sequence[Sequence[str]],
    start: int = 0,
    mode: str = "hard",
) -> list[Diff]:
    """Grade every cell of ``rows`` against ``targets``.

    ``targets[i][j]`` is the expected value of row ``i + start``, column ``j``.
    Rows are compared positionally; align them by anchor beforehand.

    ``mode`` selects how strictly the two strings must match:

    ``exact``
        byte-for-byte. The right level for "will this pass a diff tool?".
    ``soft``
        whitespace-normalised. The right level for "did the wrap stitching
        produce the same words?".
    ``hard``
        notation-insensitive (default). The right level for "is this the same
        datum?". A cell can pass here while still being wrong in presentation,
        which is why the other two levels exist.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {sorted(MODES)}")
    normalise = MODES[mode]

    diffs: list[Diff] = []
    for i, row in enumerate(rows):
        if i + start >= len(targets):
            break
        expected = targets[i + start]
        for col in range(spec.n_columns):
            if col >= len(expected):
                break
            ref = expected[col]
            if not ref:
                continue
            got = row.value(col, spec)
            if normalise(got) != normalise(ref):
                diffs.append(Diff(i + start + 1, col, got, ref))
    return diffs


def compare_all_modes(
    rows: Sequence,
    spec: TableSpec,
    targets: Sequence[Sequence[str]],
) -> dict[str, list[Diff]]:
    """Run all three comparison levels. Returns ``{mode: diffs}``."""
    return {mode: compare_rows(rows, spec, targets, mode=mode) for mode in MODES}


def classify(diff: Diff) -> Diff:
    """Name the most likely cause of a mismatch, in priority order."""
    got, ref = diff.candidate, diff.reference

    # A damaged leading mark: "。 PART" / "0 PART" / "o PART" instead of "° PART".
    stripped = _MARK_PREFIX.sub("", got)
    if stripped != got and hard(stripped) == hard(ref):
        diff.kind = "marker-corruption"
        diff.note = "leading mark damaged; candidate is wrong"
        return diff

    # Same characters, different order -> the reference's text layer is jumbled
    # (a real defect of the PDF export, not of the data).
    if hard_key(got) == hard_key(ref):
        diff.kind = "text-layer-reordered"
        diff.note = "identical character multiset; reference extraction is jumbled"
        return diff

    h_got, h_ref = hard(got), hard(ref)

    # The candidate is a prefix/suffix of the reference: the PDF clipped the
    # cell (text was not painted) or the exporter truncated it.
    if h_got and h_ref.startswith(h_got):
        diff.kind = "candidate-truncated"
        diff.note = f"candidate is missing {len(h_ref) - len(h_got)} trailing char(s)"
        return diff
    if h_got and h_got.startswith(h_ref):
        diff.kind = "reference-truncated"
        diff.note = f"candidate carries {len(h_got) - len(h_ref)} extra char(s)"
        return diff

    # Repeated leading characters are the classic signature of overprinting.
    deduped = re.sub(r"^(.)\1+", r"\1", h_got)
    if deduped and deduped == h_ref:
        diff.kind = "overprint"
        diff.note = "leading character duplicated by overprint"
        return diff

    diff.kind = "content-difference"
    diff.note = "needs human adjudication"
    return diff


def classify_all(diffs: Iterable[Diff]) -> list[Diff]:
    return [classify(d) for d in diffs]


def summarize(diffs: Sequence[Diff]) -> dict[str, int]:
    """Count diffs by kind, plus a ``total``."""
    counts = Counter(d.kind for d in diffs)
    return {"total": len(diffs), **dict(sorted(counts.items()))}


# --------------------------------------------------------------------------
# Independent verification: character conservation
# --------------------------------------------------------------------------


def pdf_band_counters(doc, spec: TableSpec) -> dict[object, Counter]:
    """Character multiset per row band, read straight from the PDF.

    Uses the same *geometry* helpers as extraction but none of the stitching or
    repair logic, so a bug in the join rules cannot hide here.
    """
    counters: dict[object, Counter] = {}

    for page_index in range(doc.page_count):
        page = doc[page_index]
        objects = iter_objects(page, page_index, spec)
        if not objects:
            continue

        anchors: list[tuple[int, float]] = []
        values: list[object] = []
        for oi, obj in enumerate(objects):
            value = detect_anchor(obj.chars, spec)
            if value is not None:
                anchors.append((oi, obj.y))
                values.append(value)
        if not anchors:
            continue

        for obj in objects:
            value = values[_band_index(obj.y, anchors)]
            counter = counters.setdefault(value, Counter())
            for ch in obj.chars:
                # The anchor column is compared by value, not by character.
                if spec.column_of(ch.cx) == spec.anchor.column:
                    continue
                # Apply exactly the same normalisation as the row side, or the
                # two counters are measuring different alphabets.
                kept = hard(ch.c)
                if kept:
                    counter[kept] += 1

    return counters


def char_conservation(
    rows: Sequence,
    spec: TableSpec,
    band_counters: dict[object, Counter],
    allow_extra_in: set[int] | None = None,
    allow_missing_in: set[int] | None = None,
) -> list[tuple[object, Counter, Counter]]:
    """Compare each row's character multiset against the PDF's own.

    Returns ``(anchor, extra_in_row, missing_from_row)`` for every row that
    does not balance.

    ``allow_extra_in`` / ``allow_missing_in`` take 1-based row indices where an
    imbalance is *expected*, and the corresponding component is dropped from
    the result:

    * rows completed from a reference carry more characters than the PDF holds,
    * rows touched by cross-band sub-line reassignment carry characters the PDF
      paints in a neighbouring band -- and the neighbour is short by exactly
      the same characters.

    Use :func:`global_char_conservation` for an invariant that survives both.

    Both sides are upper-cased and stripped of notation. Mixing case
    conventions produces a flood of false ``m``/``M``, ``x``/``X`` alarms.
    """
    allow_extra = allow_extra_in or set()
    allow_missing = allow_missing_in or set()
    problems: list[tuple[object, Counter, Counter]] = []

    for i, row in enumerate(rows):
        anchor = row.anchor
        pdf_chars = +band_counters.get(anchor, Counter())
        row_chars: Counter = Counter()
        for col in range(spec.n_columns):
            if col == spec.anchor.column:
                continue
            row_chars.update(hard(row.value(col, spec)))

        extra = Counter() if (i + 1) in allow_extra else row_chars - pdf_chars
        missing = Counter() if (i + 1) in allow_missing else pdf_chars - row_chars
        if extra or missing:
            problems.append((anchor, extra, missing))

    return problems


def global_char_conservation(
    rows: Sequence,
    spec: TableSpec,
    band_counters: dict[object, Counter],
) -> tuple[Counter, Counter]:
    """Document-wide character conservation.

    The strong invariant: repair may *move* characters between bands, but it
    must never create or destroy one. Summing over the whole document makes the
    check immune to band reassignment, so it stays meaningful even after the
    aggressive repairs have run.

    Returns ``(extra_in_output, missing_from_output)``.
    """
    pdf_total: Counter = Counter()
    for counter in band_counters.values():
        pdf_total.update(counter)

    row_total: Counter = Counter()
    for row in rows:
        for col in range(spec.n_columns):
            if col == spec.anchor.column:
                continue
            row_total.update(hard(row.value(col, spec)))

    return row_total - pdf_total, pdf_total - row_total


def format_conservation(problems: Sequence[tuple[object, Counter, Counter]], limit: int = 10) -> str:
    if not problems:
        return "character conservation: OK (every row balances)"
    lines = [f"character conservation: {len(problems)} row(s) do not balance"]
    for anchor, extra, missing in problems[:limit]:
        lines.append(f"  anchor {anchor!r}: extra={dict(extra)} missing={dict(missing)}")
    if len(problems) > limit:
        lines.append(f"  ... and {len(problems) - limit} more")
    return "\n".join(lines)


@dataclass
class VerificationReport:
    """Aggregated outcome of a verification run."""

    row_count: int = 0
    expected_row_count: int | None = None
    diffs: list[Diff] = field(default_factory=list)
    conservation_problems: list[tuple[object, Counter, Counter]] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return not self.conservation_problems

    def render(self) -> str:
        out = [f"rows: {self.row_count}"]
        if self.expected_row_count is not None:
            delta = self.row_count - self.expected_row_count
            out.append(f"expected rows: {self.expected_row_count} (delta {delta:+d})")
        out.append(f"cell differences: {summarize(self.diffs)}")
        out.append(format_conservation(self.conservation_problems))
        return "\n".join(out)
