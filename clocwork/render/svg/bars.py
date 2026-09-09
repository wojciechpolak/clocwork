# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""The card's header over a ranked list, one bar per language or project.

Bar length is relative to the biggest entry rather than to the grand total, so
the top bar always fills its row and the small ones stay visible. The
percentage beside it is the share of the total, which is what the number means.
"""

from __future__ import annotations

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
    ellipsize,
    footer_line,
    frame,
    header,
    open_svg,
    series,
    text,
    text_width,
    top_rows,
)

WIDTH = 480
PAD = 20

# Each value derived from the one above it, as in `card`.
TITLE_BASELINE = PAD + 14
FIGURE_BASELINE = TITLE_BASELINE + 36
SUBTITLE_BASELINE = FIGURE_BASELINE + 20
ROWS_TOP = SUBTITLE_BASELINE + 14
ROW_HEIGHT = 30
ROW_LABEL_OFFSET = 12  # label baseline within the row
ROW_BAR_OFFSET = ROW_LABEL_OFFSET + 6  # top of the bar within the row
BAR_HEIGHT = 6
FOOTER_GAP = 20
FOOTER_SIZE = 10


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

    rows_bottom = ROWS_TOP + len(shown) * ROW_HEIGHT
    footer_baseline = rows_bottom + FOOTER_GAP
    height = footer_baseline + PAD - 6
    inner = width - 2 * PAD
    widest = max((code for _, code in shown), default=0)

    out = open_svg(
        width,
        height,
        f"Lines of code by {by}: {group_digits(total.code)} in total",
        names,
    )
    out.append(frame(width, height))
    out.extend(
        header(report, PAD, TITLE_BASELINE, FIGURE_BASELINE, SUBTITLE_BASELINE)
    )

    radius = BAR_HEIGHT / 2
    for index, (label, code) in enumerate(shown):
        top = ROWS_TOP + index * ROW_HEIGHT
        baseline = top + ROW_LABEL_OFFSET
        value = f"{humanize(code)}  {percent(code, total.code):.1f}%"
        room = inner - text_width(value, 12) - LABEL_GAP
        out.append(
            text(PAD, baseline, ellipsize(label, 12, 500, room), "label", 12, 500)
        )
        out.append(
            text(
                width - PAD,
                baseline,
                value,
                "muted",
                12,
                anchor="end",
            )
        )
        bar_top = top + ROW_BAR_OFFSET
        out.append(
            f'<rect class="track" fill="#eceff3" x="{PAD}" y="{bar_top}" '
            f'width="{inner}" height="{BAR_HEIGHT}" rx="{radius}"/>'
        )
        filled = inner * (code / widest) if widest else 0.0
        if filled >= 0.5:
            out.append(
                f'<rect class="{names[label]}" x="{PAD}" y="{bar_top}" '
                f'width="{filled:.2f}" height="{BAR_HEIGHT}" rx="{radius}" '
                f'fill="{color_for(label)}"/>'
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
