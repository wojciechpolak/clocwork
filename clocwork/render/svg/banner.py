# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""A wide 2:1 card. A heading block, a ring of shares, a bar across the foot.

The only layout that takes text of its own. It draws `title` and `subtitle`
above the usual header, and leaving them out shortens the block rather than
moving anything, because the whole stack is centred on the ring rather than
pinned to the top.

The only layout with a locked aspect ratio, too. The others take their height
from how many rows they list. This one takes it from its width, so
`--svg-width 640` gives 640x320 and the same picture. Every constant below is
written at the design size and scaled by `k`.

The ring copies how `donut` builds its own, from filled annular sectors split
at half a circle. Both reasons carry over. `language_rules` only ever writes
`fill`, so a stroked arc would lose its dark override, and a sector under 180
degrees keeps the large-arc flag at 0. It is spelled out again here rather than
imported because `donut` binds its helpers to its own centre and radii.
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
from . import (
    LABEL_GAP,
    dot,
    ellipsize,
    footer_line,
    frame,
    open_svg,
    proportion_bar,
    series,
    summary_line,
    text,
    text_width,
    top_rows,
)

WIDTH = 1280
HEIGHT = 640
PAD = 72

TITLE_SIZE = 104
SUBTITLE_SIZE = 27
LABEL_SIZE = 18
FIGURE_SIZE = 68
SUMMARY_SIZE = 20
FOOTER_SIZE = 18

# Space above each block in the heading stack. The top block takes none, so an
# absent heading costs the stack its own height and nothing more.
BLOCK_GAP = {
    "title": 0,
    "subtitle": 16,
    "label": 40,
    "figure": 12,
    "summary": 14,
}

OUTER_R = 150
RING_WIDTH = 42
INNER_R = OUTER_R - RING_WIDTH
CENTER_X = 985
CENTER_Y = PAD + 40 + OUTER_R
MIN_SWEEP = 0.5

BAR_TOP = 470
BAR_HEIGHT = 20
CHIP_SIZE = 20
CHIP_DOT_R = 6
CHIP_GAP = 26
CHIPS_BASELINE = BAR_TOP + BAR_HEIGHT + 30
FOOTER_BASELINE = HEIGHT - PAD + 22


def _point(radius: float, angle: float, k: float) -> tuple[float, float]:
    """Polar to Cartesian at the design size, then scaled. 0 degrees is twelve
    o'clock, and scaling about the origin takes the centre along with it."""
    radians = math.radians(angle - 90)
    return (
        (CENTER_X + radius * math.cos(radians)) * k,
        (CENTER_Y + radius * math.sin(radians)) * k,
    )


def _sector(start: float, end: float, k: float) -> str:
    outer, inner = OUTER_R * k, INNER_R * k
    x1, y1 = _point(OUTER_R, start, k)
    x2, y2 = _point(OUTER_R, end, k)
    x3, y3 = _point(INNER_R, end, k)
    x4, y4 = _point(INNER_R, start, k)
    return (
        f"M{x1:.2f} {y1:.2f}"
        f"A{outer:.2f} {outer:.2f} 0 0 1 {x2:.2f} {y2:.2f}"
        f"L{x3:.2f} {y3:.2f}"
        f"A{inner:.2f} {inner:.2f} 0 0 0 {x4:.2f} {y4:.2f}Z"
    )


def _spans(start: float, sweep: float) -> list[tuple[float, float]]:
    """At most half a circle each, so the large-arc flag stays 0."""
    pieces = max(1, math.ceil(sweep / 180))
    step = sweep / pieces
    return [(start + i * step, start + (i + 1) * step) for i in range(pieces)]


def _heading(report: Report, title: str | None, subtitle: str | None,
             k: float) -> list[str]:
    """The text column, centred on the ring, holding whichever blocks are there.

    A block is (kind, content, size, class, weight), and its height is its type
    size, so an absent heading shortens the stack by exactly that block.
    """
    room = (CENTER_X - OUTER_R - LABEL_GAP - PAD) * k
    blocks = []
    if title:
        blocks.append(("title", title, TITLE_SIZE, "figure", 700))
    if subtitle:
        blocks.append(("subtitle", subtitle, SUBTITLE_SIZE, "muted", 400))
    blocks += [
        ("label", "LINES OF CODE", LABEL_SIZE, "title", 600),
        ("figure", group_digits(report.grand_total.code), FIGURE_SIZE, "figure", 700),
        ("summary", summary_line(report), SUMMARY_SIZE, "muted", 400),
    ]

    gaps = [0.0] + [BLOCK_GAP[kind] * k for kind, *_ in blocks[1:]]
    sizes = [size * k for _, _, size, _, _ in blocks]
    total = sum(gaps) + sum(sizes)

    out = []
    baseline = CENTER_Y * k - total / 2
    laid = zip(blocks, gaps, sizes, strict=True)
    for (_, content, _, cls, weight), gap, size in laid:
        baseline += gap + size
        out.append(
            text(PAD * k, baseline, ellipsize(content, size, weight, room), cls,
                 round(size, 2), weight)
        )
    return out


def _chips(everything: list[tuple[str, int]], shown: list[tuple[str, int]],
           total: int, names: dict[str, str], k: float, room: float) -> list[str]:
    """One line of dot-name-percent chips, the overflow collapsed into +N more.

    `rows` has already cut `shown`. This cuts again to whatever one line
    holds, which is why the cap is a ceiling rather than a count.
    """
    size = CHIP_SIZE * k
    gap = CHIP_GAP * k
    lead = CHIP_DOT_R * 2 * k + 6 * k

    def width(label: str, value: str) -> float:
        return lead + text_width(label, size, 500) + 6 * k + text_width(value, size)

    labelled = [(label, f"{percent(code, total):.1f}%") for label, code in shown]
    fits = list(labelled)
    while fits:
        used = sum(width(*chip) for chip in fits) + gap * (len(fits) - 1)
        rest = len(everything) - len(fits)
        if rest:
            used += gap + text_width(f"+{rest} more", size)
        if used <= room:
            break
        fits.pop()

    out = []
    x = PAD * k
    baseline = CHIPS_BASELINE * k
    for label, value in fits:
        out.append(dot(names[label], x + CHIP_DOT_R * k, baseline - 6 * k, label,
                       max(1, round(CHIP_DOT_R * k))))
        x += lead
        out.append(text(x, baseline, label, "label", round(size, 2), 500))
        x += text_width(label, size, 500) + 6 * k
        out.append(text(x, baseline, value, "muted", round(size, 2)))
        x += text_width(value, size) + gap
    rest = len(everything) - len(fits)
    if rest:
        out.append(text(x, baseline, f"+{rest} more", "muted", round(size, 2)))
    return out


def render(
    report: Report,
    width: int | None = None,
    by: str = DEFAULT_SUBJECT,
    rows: int = DEFAULT_ROWS,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    width = width or WIDTH
    k = width / WIDTH
    height = round(HEIGHT * k)
    total = report.grand_total
    everything = series(report, by)
    shown = top_rows(everything, rows)
    names = palette(label for label, _ in everything)
    inner = round((WIDTH - 2 * PAD) * k)

    out = open_svg(
        width,
        height,
        f"{title + ': ' if title else ''}"
        f"Lines of code by {by}: {group_digits(total.code)} across "
        f"{len(report.counted)} projects",
        names,
    )
    out.append(frame(width, height))
    out.extend(_heading(report, title, subtitle, k))

    angle = 0.0
    for label, code in everything:
        sweep = 360 * percent(code, total.code) / 100
        if sweep < MIN_SWEEP:
            continue
        for start, end in _spans(angle, sweep):
            out.append(
                f'<path class="{names[label]}" d="{_sector(start, end, k)}" '
                f'fill="{color_for(label)}"/>'
            )
        angle += sweep

    out.append(text(CENTER_X * k, (CENTER_Y + 8) * k, humanize(total.code),
                    "figure", round(46 * k, 2), 700, "middle"))
    out.append(text(CENTER_X * k, (CENTER_Y + 40) * k, "lines", "muted",
                    round(20 * k, 2), 400, "middle"))

    out.extend(
        proportion_bar(round(PAD * k), round(BAR_TOP * k), inner,
                       max(1, round(BAR_HEIGHT * k)), everything, total.code, names)
    )
    out.extend(_chips(everything, shown, total.code, names, k, inner))
    out.append(text(PAD * k, FOOTER_BASELINE * k, footer_line(report), "muted",
                    round(FOOTER_SIZE * k, 2)))

    out.append("</svg>")
    return "\n".join(out) + "\n"
