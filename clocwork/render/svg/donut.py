# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""A ring of language or project shares, the total in the middle, a legend
beside it.

The ring is built from *filled* annular sectors rather than stroked arcs, so
every coloured element keeps its `fill` presentation attribute and the shared
`language_rules`, which only ever writes `fill`, covers the dark theme too.
No sector spans more than half the circle, so the arcs stay small, the
large-arc flag stays 0, and a single language at 100% draws as two halves
instead of a degenerate zero-length arc.
"""

from __future__ import annotations

import math

from ...model import Report
from .. import (
    DEFAULT_ROWS,
    DEFAULT_SUBJECT,
    color_for,
    group_digits,
    humanize,
    palette,
    percent,
)
from . import footer_line, frame, legend_row, open_svg, series, text, top_rows

WIDTH = 480
PAD = 20

TITLE_BASELINE = PAD + 14
RING_TOP = TITLE_BASELINE + 14
OUTER_R = 62
RING_WIDTH = 18
INNER_R = OUTER_R - RING_WIDTH
CENTER_X = PAD + OUTER_R
CENTER_Y = RING_TOP + OUTER_R
RING_BOTTOM = CENTER_Y + OUTER_R
LEGEND_GAP = 22
LEGEND_ROW_HEIGHT = 20
# The legend is centred on the ring, which holds while it is shorter than the
# ring is tall. A longer one would grow off the top of the card, so it stops at
# the ring's top edge and runs downwards from there.
LEGEND_TOP_MIN = RING_TOP
FOOTER_GAP = 20
FOOTER_SIZE = 10

# Anything thinner than this reads as a hairline rather than a slice.
MIN_SWEEP = 0.5


def _point(radius: float, angle: float) -> tuple[float, float]:
    """Polar to Cartesian, with 0 degrees at twelve o'clock."""
    radians = math.radians(angle - 90)
    return CENTER_X + radius * math.cos(radians), CENTER_Y + radius * math.sin(radians)


def _sector(start: float, end: float) -> str:
    x1, y1 = _point(OUTER_R, start)
    x2, y2 = _point(OUTER_R, end)
    x3, y3 = _point(INNER_R, end)
    x4, y4 = _point(INNER_R, start)
    return (
        f"M{x1:.2f} {y1:.2f}"
        f"A{OUTER_R} {OUTER_R} 0 0 1 {x2:.2f} {y2:.2f}"
        f"L{x3:.2f} {y3:.2f}"
        f"A{INNER_R} {INNER_R} 0 0 0 {x4:.2f} {y4:.2f}Z"
    )


def _spans(start: float, sweep: float) -> list[tuple[float, float]]:
    """The sector split into pieces of at most half a circle."""
    pieces = max(1, math.ceil(sweep / 180))
    step = sweep / pieces
    return [(start + i * step, start + (i + 1) * step) for i in range(pieces)]


def render(
    report: Report,
    width: int | None = None,
    by: str = DEFAULT_SUBJECT,
    rows: int = DEFAULT_ROWS,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    width = width or WIDTH
    total = report.grand_total
    everything = series(report, by)
    shown = top_rows(everything, rows)
    names = palette(label for label, _ in everything)

    legend_height = len(shown) * LEGEND_ROW_HEIGHT
    legend_top = max(LEGEND_TOP_MIN, CENTER_Y - legend_height / 2)
    footer_baseline = max(RING_BOTTOM, legend_top + legend_height) + FOOTER_GAP
    height = int(footer_baseline + PAD - 6)

    out = open_svg(
        width,
        height,
        f"Lines of code by {by}: {group_digits(total.code)} in total",
        names,
    )
    out.append(frame(width, height))
    out.append(text(PAD, TITLE_BASELINE, "LINES OF CODE", "title", 11, 600))

    angle = 0.0
    for label, code in everything:
        sweep = 360 * percent(code, total.code) / 100
        if sweep < MIN_SWEEP:
            continue
        for start, end in _spans(angle, sweep):
            out.append(
                f'<path class="{names[label]}" d="{_sector(start, end)}" '
                f'fill="{color_for(label)}"/>'
            )
        angle += sweep

    out.append(
        text(CENTER_X, CENTER_Y + 2, humanize(total.code), "figure", 20, 700, "middle")
    )
    out.append(text(CENTER_X, CENTER_Y + 18, "lines", "muted", 10, 400, "middle"))

    legend_left = CENTER_X + OUTER_R + LEGEND_GAP
    for index, (label, code) in enumerate(shown):
        baseline = legend_top + index * LEGEND_ROW_HEIGHT + 14
        out.extend(
            legend_row(
                legend_left,
                width - PAD,
                baseline,
                label,
                names[label],
                f"{percent(code, total.code):.1f}%",
                11,
            )
        )

    out.append(
        text(
            PAD,
            footer_baseline,
            footer_line(report),
            "muted",
            FOOTER_SIZE,
        )
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"
