# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""A thin band of chips that wraps, with no card around it.

Meant to sit under something else, a table in a profile README say, so it
carries no frame and no grand total. Just what was counted, how much, and in
what proportion. Languages by default, projects with `by`. Height is one line
per wrapped row, and `text_width` decides where a row wraps. That is an
estimate, so the gaps are generous enough to absorb its error.

Frameless decides the colours too. The page supplies the background and this
layout never learns what colour it is, so every fill comes from the `any_bg`
palette, which reads on white and on a dark README alike. There is no theme
override to get wrong. `svg.NEUTRAL` carries the reasoning.

`rows` is here for the layout contract and does nothing. `MAX_ROWS` below counts
wrapped *lines* rather than entries, and this layout draws every entry already,
so `--svg-rows` has nothing to lift.
"""

from __future__ import annotations

from ...model import Report
from .. import DEFAULT_ROWS, DEFAULT_SUBJECT, humanize, palette, percent
from . import dot, ellipsize, open_svg, series, text, text_width

WIDTH = 840
PAD = 2  # frameless, so this is only enough that the first dot is not clipped

DOT_R = 4
DOT_GAP = 6  # dot to name
VALUE_GAP = 6  # name to value
CHIP_GAP = 18  # chip to chip
NAME_SIZE = 12
VALUE_SIZE = 11

LINE_HEIGHT = 22
BASELINE_OFFSET = 15
# A run with a hundred languages must not produce a hundred-line image; past
# this many rows the rest collapse into one "+N more" chip.
MAX_ROWS = 4


def _chip_width(label: str, value: str) -> float:
    return (
        DOT_R * 2
        + DOT_GAP
        + text_width(label, NAME_SIZE, 500)
        + VALUE_GAP
        + text_width(value, VALUE_SIZE)
    )


def _fit(label: str, value: str, avail: float) -> str:
    """A chip wider than a whole row would never fit anywhere, so its label is
    cut down. Long project names are the reason this exists."""
    room = avail - (_chip_width(label, value) - text_width(label, NAME_SIZE, 500))
    return ellipsize(label, NAME_SIZE, 500, room)


def _wrap(chips: list[tuple[str, str, str, float]], avail: float):
    """Greedy left-to-right fill, one list of chips per row."""
    rows: list[list[tuple[str, str, str, float]]] = [[]]
    used: list[float] = [0.0]
    for chip in chips:
        if used[-1] and used[-1] + CHIP_GAP + chip[3] > avail:
            rows.append([])
            used.append(0.0)
        used[-1] += (CHIP_GAP if rows[-1] else 0) + chip[3]
        rows[-1].append(chip)
    return rows, used


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
    avail = width - 2 * PAD

    chips = []
    for label, code in items:
        value = f"{humanize(code)}  {percent(code, total):.1f}%"
        shown = _fit(label, value, avail)
        chips.append((label, shown, value, _chip_width(shown, value)))

    lines, used = _wrap(chips, avail)
    hidden = 0
    if len(lines) > MAX_ROWS:
        hidden = sum(len(row) for row in lines[MAX_ROWS:])
        lines, used = lines[:MAX_ROWS], used[:MAX_ROWS]
    # The overflow chip has to fit too, so it evicts chips until it does.
    more = ""
    if hidden:
        more = f"+{hidden} more"
        while lines[-1] and used[-1] + CHIP_GAP + text_width(more, VALUE_SIZE) > avail:
            dropped = lines[-1].pop()
            used[-1] = max(0.0, used[-1] - dropped[3] - CHIP_GAP)
            hidden += 1
            more = f"+{hidden} more"

    height = 2 * PAD + len(lines) * LINE_HEIGHT

    out = open_svg(
        width,
        height,
        f"Lines of code by {by}: "
        f"{', '.join(label for label, _ in items[:6])}"
        if items
        else f"Lines of code by {by}",
        names,
        any_bg=True,
    )
    for index, row in enumerate(lines):
        baseline = PAD + index * LINE_HEIGHT + BASELINE_OFFSET
        x = float(PAD)
        for label, shown, value, chip_width in row:
            out.append(
                dot(names[label], x + DOT_R, baseline - 4, label, DOT_R, any_bg=True)
            )
            name_x = x + DOT_R * 2 + DOT_GAP
            out.append(text(name_x, baseline, shown, "neutral", NAME_SIZE, 500))
            out.append(
                text(
                    name_x + text_width(shown, NAME_SIZE, 500) + VALUE_GAP,
                    baseline,
                    value,
                    "neutral",
                    VALUE_SIZE,
                )
            )
            x += chip_width + CHIP_GAP
        if more and index == len(lines) - 1:
            out.append(text(x, baseline, more, "neutral", VALUE_SIZE))
    out.append("</svg>")
    return "\n".join(out) + "\n"
