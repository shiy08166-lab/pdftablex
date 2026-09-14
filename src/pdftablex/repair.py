"""Repair operators.

Each operator targets one named export defect and is applied only when it can
be *justified* -- either by a reference file or by an independent dictionary.
Nothing is "fixed" speculatively; a candidate that cannot be justified is left
alone and reported instead.

===========================================  ==========================================
Operator                                     Defect it addresses
===========================================  ==========================================
``complete_from_reference``                  PDF clipped or truncated the cell
``move_overflow_back``                       long text overflowed into the next column
``reassign_subline_window``                  adjacent rows' wrapped lines interleave
``repair_split_words``                       hard wrap split a word (``MANUSCRIP`` + ``T``)
``repair_swallowed_space``                   hard wrap ate the space after the split
``collapse_cjk_spaces``                      wrap artefacts inside CJK columns
``collapse_double_spaces``                   exporter emitted double spaces
===========================================  ==========================================

Every operator accepts an optional ``log`` list and appends a human-readable
line for each change it makes. Keep that log: it is the audit trail that lets a
reviewer check the machine's work instead of trusting it.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from .config import TableSpec
from .geometry import Row
from .join import is_cjk, join_sublines
from .verify import hard

Log = list[str] | None

#: A window bigger than this is not worth brute-forcing; the ambiguity is
#: almost certainly a data problem rather than a stitching problem.
_MAX_POOL = 24


def load_dictionary() -> frozenset[str]:
    """The English word list used to detect hard-wrapped words.

    Returns an empty set if ``english-words`` is unavailable, which disables
    the dictionary-based operators rather than failing.
    """
    try:
        from english_words import get_english_words_set

        return frozenset(get_english_words_set(["web2"], lower=True))
    except Exception:  # pragma: no cover - optional dependency
        return frozenset()


def _note(log: Log, message: str) -> None:
    if log is not None:
        log.append(message)


# --------------------------------------------------------------------------
# Reference-guided operators
# --------------------------------------------------------------------------


def complete_from_reference(
    rows: Sequence[Row],
    spec: TableSpec,
    targets: Sequence[Sequence[str]],
    log: Log = None,
) -> list[dict]:
    """Fill cells the PDF itself lost, using the reference as the source.

    Only applies where the extracted value is a genuine prefix/substring of the
    reference -- i.e. where the PDF demonstrably dropped trailing characters.
    Returns the list of completions so the caller can report them as
    "recovered, please confirm against the authoritative source".
    """
    completions: list[dict] = []
    for i, row in enumerate(rows):
        if i >= len(targets):
            break
        for col in range(spec.n_columns):
            if col == spec.anchor.column or col >= len(targets[i]):
                continue
            ref = targets[i][col]
            got = row.value(col, spec)
            if not ref or hard(got) == hard(ref):
                continue
            h_got, h_ref = hard(got), hard(ref)
            if not h_got:
                continue
            # Recover only when the PDF's value is contained in the reference
            # and the gap is small enough to be a clipped tail, not new data.
            if h_got in h_ref and 0 < len(h_ref) - len(h_got) <= 14:
                row.set_subline_texts(col, [ref])
                completions.append(
                    {"row": i + 1, "col": col, "pdf": got, "reference": ref}
                )
                _note(log, f"complete row {i + 1} col {col}: {got!r} -> {ref!r}")
    return completions


def move_overflow_back(
    rows: Sequence[Row],
    spec: TableSpec,
    targets: Sequence[Sequence[str]],
    touched: set[int] | None = None,
    log: Log = None,
) -> int:
    """Move characters that overflowed past a column boundary back into their cell.

    Triggered by the ``boundary`` flag: extraction records every column
    boundary that a character straddles, which is the reliable signature of
    overflow (a ``clip`` test on the left cell alone misses it whenever the
    last character happens to stop just short of the edge).

    The move is committed only when *both* affected cells then match the
    reference, and only when the boundary separates ASCII from something else.
    When **both** sides are ASCII the spill point cannot be recovered from
    geometry at all -- the cell is deliberately left alone so that it surfaces
    as a difference instead of being guessed at.
    """
    moved = 0
    for i, row in enumerate(rows):
        if i >= len(targets):
            break
        boundaries = row.flags.get("boundary", set())
        for col in range(1, spec.n_columns - 1):
            # Boundary index col + 1 separates column col from column col + 1.
            if (col + 1) not in boundaries:
                continue
            left = row.sublines.get(col, [])
            right = row.sublines.get(col + 1, [])
            if not left or not right:
                continue

            match = re.match(r"^[A-Za-z][A-Za-z0-9]*", right[0][1])
            if not match:
                continue
            prefix = match.group(0)
            rest = right[0][1][match.end() :]
            # Ambiguous boundary: ASCII running into ASCII. Do not guess.
            if rest and rest[0].isascii() and not rest[0].isspace():
                continue

            trial_left = [*left[:-1], (left[-1][0], left[-1][1] + prefix)]
            trial_right = (
                [(right[0][0], rest.strip())] if rest.strip() else []
            ) + right[1:]

            if hard(
                join_sublines(col, [t for _, t in trial_left], spec.columns[col].kind)
            ) != hard(targets[i][col]):
                continue
            if hard(
                join_sublines(
                    col + 1, [t for _, t in trial_right], spec.columns[col + 1].kind
                )
            ) != hard(targets[i][col + 1]):
                continue

            row.sublines[col] = trial_left
            row.sublines[col + 1] = trial_right
            if touched is not None:
                touched.add(i + 1)
            moved += 1
            _note(log, f"move-overflow row {i + 1} col {col + 1}: {prefix!r} moved left")
    return moved


def reassign_subline_window(
    rows: Sequence[Row],
    spec: TableSpec,
    targets: Sequence[Sequence[str]],
    max_window: int = 5,
    touched: set[int] | None = None,
    log: Log = None,
) -> int:
    """Re-cut the wrapped sub-lines of neighbouring rows.

    Adjacent rows' wrapped lines interleave on the y axis -- a row gap of
    3.14pt against a wrap gap of 3.17pt is not separable by geometry alone. So
    the window's sub-lines are pooled, every contiguous partition of the pool
    into ``window`` parts is enumerated, and the partition that reproduces the
    reference exactly wins. Ties break toward the partition that moves the
    fewest sub-lines.

    The reference is used only to resolve *ambiguity in the extraction*. Any
    mismatch that survives this step is reported as a real difference, never
    silently attributed to the reference.
    """
    if len(targets) != len(rows):
        raise ValueError("reassign_subline_window needs a 1:1 row alignment")
    total = 0

    for col in range(spec.n_columns):
        if col == spec.anchor.column:
            continue
        kind = spec.columns[col].kind
        i = 0
        n = len(rows)
        while i < n:
            if hard(rows[i].value(col, spec)) == hard(targets[i][col]):
                i += 1
                continue

            matched = False
            for w in range(2, max_window + 1):
                for lo in range(max(0, i - w + 1), min(n - w, i) + 1):
                    hi = lo + w
                    if all(
                        hard(rows[j].value(col, spec)) == hard(targets[j][col])
                        for j in range(lo, hi)
                    ):
                        continue
                    pool = sorted(
                        (y, j, t)
                        for j in range(lo, hi)
                        for y, t in rows[j].sublines.get(col, [])
                    )
                    if not pool or len(pool) > _MAX_POOL:
                        continue

                    best: tuple[int, list] | None = None
                    for cuts in itertools.combinations_with_replacement(
                        range(len(pool) + 1), w - 1
                    ):
                        bounds = (0, *cuts, len(pool))
                        segments = [pool[bounds[k] : bounds[k + 1]] for k in range(w)]
                        if any(
                            hard(
                                join_sublines(
                                    col, [t for _, _, t in seg], kind
                                )
                            )
                            != hard(targets[lo + k][col])
                            for k, seg in enumerate(segments)
                        ):
                            continue
                        moved = sum(
                            1
                            for k, seg in enumerate(segments)
                            for _, origin, _ in seg
                            if origin != lo + k
                        )
                        if best is None or moved < best[0]:
                            best = (moved, segments)
                            if moved == 0:
                                break
                        # A tie on cost is still a valid partition; keep going
                        # only while a cheaper one might exist.
                        if best[0] == 0:
                            break

                    if best is None:
                        continue
                    for k, seg in enumerate(best[1]):
                        rows[lo + k].sublines[col] = [(y, t) for y, _, t in seg]
                        if touched is not None:
                            touched.add(lo + k + 1)
                    total += 1
                    matched = True
                    _note(log, f"reassign window rows {lo + 1}-{hi} col {col}: re-cut (w={w})")
                    break
                if matched:
                    break
            i += 1

    return total


# --------------------------------------------------------------------------
# Dictionary-guided operators (need no reference)
# --------------------------------------------------------------------------


def _tail_word(token: str) -> str:
    m = re.search(r"[A-Za-z]+$", token)
    return m.group(0) if m else ""


def _head_word(token: str) -> str:
    m = re.search(r"^[A-Za-z]+", token)
    return m.group(0) if m else ""


def repair_split_words(
    rows: Sequence[Row],
    spec: TableSpec,
    dictionary: frozenset[str],
    log: Log = None,
) -> int:
    """Join a word the exporter hard-wrapped without a hyphen.

    ``MANUSCRIP`` + ``T`` -> ``MANUSCRIPT``.

    Note the token-level rule: look at the *leading/trailing letter run* of a
    token, not the whole token. ``INDEX/CATALO`` + ``GUE`` hides the split
    behind a slash and defeats a naive "is this token all letters" test -- a
    real defect this project shipped a fix for only after a user found it.
    """
    if not dictionary:
        return 0
    fixed = 0

    for row in rows:
        for col in range(spec.n_columns):
            if col == spec.anchor.column or spec.columns[col].kind != "en":
                continue
            for k in range(len(row.sublines.get(col, [])) - 1):
                sublines = row.sublines[col]
                left_tokens = sublines[k][1].split()
                right_tokens = sublines[k + 1][1].split()
                if not left_tokens or not right_tokens:
                    continue
                a, b = left_tokens[-1], right_tokens[0]
                sa, sb = _tail_word(a), _head_word(b)
                if not sa or not sb or len(sa) < 3:
                    continue
                if sa.lower() not in dictionary and (sa + sb).lower() in dictionary:
                    sublines[k] = (sublines[k][0], sublines[k][1] + b)
                    sublines[k + 1] = (
                        sublines[k + 1][0],
                        " ".join(right_tokens[1:]),
                    )
                    fixed += 1
                    _note(log, f"join-split-word: {sa}+{sb} -> {sa}{sb}")
    return fixed


def repair_swallowed_space(
    rows: Sequence[Row],
    spec: TableSpec,
    dictionary: frozenset[str],
    log: Log = None,
) -> int:
    """Restore a space the hard wrap swallowed.

    ``MANUSCRIP`` + ``TCOLLECTION`` -> ``MANUSCRIPT COLLECTION``. Both sides
    must themselves be dictionary words for the split point to be accepted.
    """
    if not dictionary:
        return 0
    fixed = 0

    for row in rows:
        for col in range(spec.n_columns):
            if col == spec.anchor.column or spec.columns[col].kind != "en":
                continue
            for k in range(len(row.sublines.get(col, [])) - 1):
                sublines = row.sublines[col]
                left_tokens = sublines[k][1].split()
                right_tokens = sublines[k + 1][1].split()
                if not left_tokens or not right_tokens:
                    continue
                a, b = left_tokens[-1], right_tokens[0]
                sa, sb = _tail_word(a), _head_word(b)
                if not sa or not sb or len(sa) < 3 or len(sb) < 5:
                    continue
                if sa.lower() in dictionary or sb.lower() in dictionary:
                    continue
                for j in range(1, len(sb)):
                    w1, w2 = (sa + sb[:j]).lower(), sb[j:].lower()
                    if w1 in dictionary and w2 in dictionary and len(w2) >= 3:
                        sublines[k] = (sublines[k][0], sublines[k][1] + sb[:j])
                        sublines[k + 1] = (
                            sublines[k + 1][0],
                            " ".join([sb[j:], *right_tokens[1:]]),
                        )
                        fixed += 1
                        _note(log, f"restore-space: {sa}+{sb} -> {sa}{sb[:j]} {sb[j:]}")
                        break
    return fixed


# --------------------------------------------------------------------------
# Purely mechanical normalisations (need no reference, no dictionary)
# --------------------------------------------------------------------------


def collapse_cjk_spaces(rows: Sequence[Row], spec: TableSpec, log: Log = None) -> int:
    """Remove spaces introduced by wrapping inside CJK columns.

    A wrap seam inside a Chinese name is not a word boundary:
    ``图 -鉴`` should be ``图-鉴``.
    """
    touched = 0
    for row in rows:
        for col in range(spec.n_columns):
            if spec.columns[col].kind != "cjk":
                continue
            for k, (y, text) in enumerate(row.sublines.get(col, [])):
                if " " not in text:
                    continue
                tokens = text.split(" ")
                out = [tokens[0]]
                for token in tokens[1:]:
                    prev = out[-1][-1:]
                    nxt = token[:1]
                    if prev and nxt and (is_cjk(prev) or prev in "-") and (
                        is_cjk(nxt) or nxt in "-"
                    ):
                        out[-1] += token
                    else:
                        out.append(token)
                joined = " ".join(out)
                if joined != text:
                    row.sublines[col][k] = (y, joined)
                    touched += 1
    if touched:
        _note(log, f"collapse-cjk-spaces: {touched} sub-line(s)")
    return touched


def collapse_double_spaces(rows: Sequence[Row], spec: TableSpec, log: Log = None) -> int:
    """Collapse runs of spaces inside every cell."""
    touched = 0
    for row in rows:
        for col in range(spec.n_columns):
            for k, (y, text) in enumerate(row.sublines.get(col, [])):
                collapsed = " ".join(text.split())
                if collapsed != text:
                    row.sublines[col][k] = (y, collapsed)
                    touched += 1
    if touched:
        _note(log, f"collapse-double-spaces: {touched} sub-line(s)")
    return touched


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


@dataclass
class RepairResult:
    """What the repair pass did -- and, just as importantly, what it did not."""

    log: list[str] = field(default_factory=list)
    #: Cells filled from the reference because the PDF had lost the characters.
    #: These are *not* evidence that the PDF agreed; report them separately.
    completions: list[dict] = field(default_factory=list)
    #: 1-based indices of rows whose characters were moved between bands.
    #: Row-level character conservation legitimately fails for these, because
    #: the characters now sit in a different band from the one the PDF paints.
    reassigned_rows: set[int] = field(default_factory=set)

    @property
    def recovered_rows(self) -> set[int]:
        return {c["row"] for c in self.completions}

    @property
    def expected_conservation_failures(self) -> set[int]:
        """Rows whose per-row conservation is expected to be off."""
        return self.reassigned_rows | self.recovered_rows


def repair(
    rows: Sequence[Row],
    spec: TableSpec,
    targets: Sequence[Sequence[str]] | None = None,
    dictionary: frozenset[str] | None = None,
    max_window: int = 5,
) -> RepairResult:
    """Run every applicable operator, cheapest first.

    Reference-guided operators run first so that ambiguity is resolved before
    anything else touches the text; dictionary-guided operators next, since a
    split word must be rejoined before the dictionary can see the whole word;
    purely mechanical normalisations last, so they see the final text.
    """
    result = RepairResult()

    if dictionary is None:
        dictionary = load_dictionary()

    if targets is not None:
        moved = move_overflow_back(
            rows, spec, targets, result.reassigned_rows, result.log
        )
        if moved:
            result.log.append(f"-- move-overflow-back applied {moved} time(s)")
        reassigned = reassign_subline_window(
            rows, spec, targets, max_window, result.reassigned_rows, result.log
        )
        if reassigned:
            result.log.append(
                f"-- subline-window reassignment applied {reassigned} time(s)"
            )

    repair_split_words(rows, spec, dictionary, result.log)
    repair_swallowed_space(rows, spec, dictionary, result.log)
    collapse_cjk_spaces(rows, spec, result.log)
    collapse_double_spaces(rows, spec, result.log)

    if targets is not None:
        result.completions = complete_from_reference(rows, spec, targets, result.log)

    return result
