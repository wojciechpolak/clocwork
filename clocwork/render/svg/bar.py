# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""The smallest layout. One proportion bar and one line of labels.

Frameless like `strip`, and always the same height, however many languages or
projects it draws. The caption sums whatever does not fit into a trailing
"other". The colours come from the same `any_bg` palette `strip` uses, fitted
to read on either background, because nothing here knows what the page behind
it looks like.

`rows` is here for the layout contract and does nothing. There is no list of
rows to cut, and the caption already draws every label it has room for.
"""

from __future__ import annotations

from ...model import Report
from .. import DEFAULT_ROWS, DEFAULT_SUBJECT, palette, percent
from . import open_svg, proportion_bar, series, text, text_width

WIDTH = 840
PAD = 2

BAR_TOP = PAD
BAR_HEIGHT = 8
CAPTION_SIZE = 11
CAPTION_GAP = 7
CAPTION_BASELINE = BAR_TOP + BAR_HEIGHT + CAPTION_GAP + CAPTION_SIZE
HEIGHT = CAPTION_BASELINE + 4

SEPARATOR = "  ·  "


def _caption(items: list[tuple[str, int]], total: int, avail: float) -> str:
    """As many labels as fit, then everything left over as one share."""
    shown: list[str] = []
    for index, (label, code) in enumerate(items):
        piece = f"{label} {percent(code, total):.0f}%"
        rest = sum(c for _, c in items[index + 1:])
        tail = (
            SEPARATOR + f"other {percent(rest, total):.0f}%"
            if index + 1 < len(items)
            else ""
        )
        candidate = SEPARATOR.join([*shown, piece]) + tail
        if shown and text_width(candidate, CAPTION_SIZE) > avail:
            break
        shown.append(piece)
    else:
        return SEPARATOR.join(shown)

    rest = sum(c for _, c in items[len(shown):])
    return SEPARATOR.join([*shown, f"other {percent(rest, total):.0f}%"])


def render(
    report: Report,
    width: int | None = None,
    by: str = DEFAULT_SUBJECT,
    rows: int = DEFAULT_ROWS,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    width = width or WIDTH
    total = report.grand_total.code
    items = series(report, by)
    names = palette(label for label, _ in items)
    inner = width - 2 * PAD

    out = open_svg(
        width,
        HEIGHT,
        f"{by.capitalize()} mix across {len(report.counted)} projects",
        names,
        any_bg=True,
    )
    out.extend(
        proportion_bar(
            PAD, BAR_TOP, inner, BAR_HEIGHT, items, total, names, any_bg=True
        )
    )
    out.append(
        text(
            PAD,
            CAPTION_BASELINE,
            _caption(items, total, inner),
            "neutral",
            CAPTION_SIZE,
        )
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"
