# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""The default layout. A summary card sized for a GitHub profile README.

A big grand total, one proportion bar over everything counted, and a labelled
row for each of the top few. Languages by default, projects with `by`.
"""

from __future__ import annotations

from ...model import Report
from .. import (
    DEFAULT_ROWS,
    DEFAULT_SUBJECT,
    group_digits,
    humanize,
    palette,
    percent,
)
from . import (
    footer_line,
    frame,
    header,
    legend_row,
    open_svg,
    proportion_bar,
    series,
    text,
    top_rows,
)

WIDTH = 480
PAD = 20

# Vertical layout, each value derived from the one above it so nothing can drift
# out of agreement when a row is added or the type sizes change.
TITLE_BASELINE = PAD + 14
FIGURE_BASELINE = TITLE_BASELINE + 36
SUBTITLE_BASELINE = FIGURE_BASELINE + 20
BAR_TOP = SUBTITLE_BASELINE + 12
BAR_HEIGHT = 10
ROWS_TOP = BAR_TOP + BAR_HEIGHT + 16
ROW_HEIGHT = 24
ROW_BASELINE_OFFSET = 12
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
    # The bar covers everything, the rows only the top few, and both paint from
    # the same numbered classes.
    names = palette(label for label, _ in everything)

    rows_bottom = ROWS_TOP + len(shown) * ROW_HEIGHT
    footer_baseline = rows_bottom + FOOTER_GAP
    height = footer_baseline + PAD - 6
    inner = width - 2 * PAD

    out = open_svg(
        width,
        height,
        f"Lines of code by {by}: {group_digits(total.code)} across "
        f"{len(report.counted)} projects",
        names,
    )
    out.append(frame(width, height))
    out.extend(
        header(report, PAD, TITLE_BASELINE, FIGURE_BASELINE, SUBTITLE_BASELINE)
    )
    out.extend(
        proportion_bar(
            PAD, BAR_TOP, inner, BAR_HEIGHT, everything, total.code, names
        )
    )

    for index, (label, code) in enumerate(shown):
        baseline = ROWS_TOP + index * ROW_HEIGHT + ROW_BASELINE_OFFSET
        out.extend(
            legend_row(
                PAD,
                width - PAD,
                baseline,
                label,
                names[label],
                f"{humanize(code)}  {percent(code, total.code):.1f}%",
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
