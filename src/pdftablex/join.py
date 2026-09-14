"""Stitching wrapped sub-lines back into one cell value.

When a cell is too narrow, the exporter wraps its text onto several physical
lines. Rejoining them is not a matter of "add a space": the correct separator
depends on what the column contains.

======================  ==========================  ==================================
Column kind             Rule                        Example
======================  ==========================  ==================================
``code``                direct concatenation        ``PZ.10.10.`` + ``03``
``cjk``                 direct concatenation        ``山地植物志`` + ``图鉴汇编``
``en``                  space, unless a trailing    ``FIELD-`` + ``GUIDE TO THE COASTAL ZONE``
                        ``-`` is present
``digit``               chosen per seam from the    ``PZ10A+`` + ``Z`` -> ``PZ10A+Z``
                        characters on both sides
======================  ==========================  ==================================

Getting this wrong is the single largest source of "the row count is right but
the cells are wrong" failures.
"""

from __future__ import annotations

from collections.abc import Sequence

from .config import JoinKind


def is_cjk(ch: str) -> bool:
    """True for Han characters and CJK/full-width punctuation."""
    if not ch:
        return False
    return (
        "\u4e00" <= ch <= "\u9fff"
        or "\u3000" <= ch <= "\u303f"
        or "\uff00" <= ch <= "\uffef"
    )


def _join_digit(out: str, nxt: str) -> str:
    """Decide the seam for a mixed column (e.g. material grades)."""
    if is_cjk(out[-1]) or is_cjk(nxt[0]):
        return out + nxt
    if out[-1].isdigit() and nxt[0].isdigit():
        return out + nxt
    return out + " " + nxt


def join_sublines(col: int, texts: Sequence[str], kind: JoinKind) -> str:
    """Join the sub-lines of one cell into its final value."""
    pieces = [t for t in texts if t]
    if not pieces:
        return ""

    out = pieces[0]
    for nxt in pieces[1:]:
        if kind == "code":
            out += nxt
        elif kind == "cjk":
            out += nxt if (is_cjk(out[-1]) and is_cjk(nxt[0])) else " " + nxt
        elif kind == "digit":
            out = _join_digit(out, nxt)
        else:  # "en"
            out += nxt if out.endswith("-") else " " + nxt
    return out


def collapse_spaces(text: str) -> str:
    """Collapse runs of spaces. Exporters emit double spaces at wrap seams."""
    return " ".join(text.split())
