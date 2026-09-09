# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""The parts every SVG layout shares, plus one module per layout.

GitHub renders an SVG through an <img> tag, which rules out an external
stylesheet, <foreignObject> and web fonts. Every colour goes on the element as
a presentation attribute, which survives anywhere, and the inline <style> only
*overrides* it for dark mode, so a stripped style block still leaves a readable
light picture.

Every layout is `render(report, width=None, by=DEFAULT_SUBJECT,
rows=DEFAULT_ROWS) -> str` over the same language summary, drawn at a different
shape. This module holds what they share: the stylesheet, the text helper, the
proportion bar, the legend row. A layout module holds its own geometry, and
nothing else imports it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from html import escape

from ...model import Report
from .. import (
    DEFAULT_LAYOUT,
    DEFAULT_ROWS,
    DEFAULT_SUBJECT,
    LAYOUT_NAMES,
    SECTION_NAMES,
    SUBJECT_NAMES,
    color_for,
    group_digits,
    percent,
)

STYLE = """
    .bg { fill: #ffffff; stroke: #e3e6ea; }
    .title { fill: #6b7280; }
    .figure { fill: #1c1e21; }
    .label { fill: #1c1e21; }
    .muted { fill: #6b7280; }
    .track { fill: #eceff3; }
    @media (prefers-color-scheme: dark) {
      .bg { fill: #0f1115; stroke: #262b33; }
      .title { fill: #9aa3af; }
      .figure { fill: #e6e8eb; }
      .label { fill: #e6e8eb; }
      .muted { fill: #9aa3af; }
      .track { fill: #22262e; }
    }
"""

# What `strip` and `bar` paint with. They draw no background, so the page
# supplies one, and `prefers-color-scheme` cannot answer for it. It describes
# the viewer, not the page behind the image. On GitHub the two agree. In a
# JetBrains Markdown preview they do not, and the near-black `.label` landed on
# a dark page at 1.13:1, which is to say it vanished. So these are one colour
# each, clearing 4.3:1 on white and on the dark card alike, and NEUTRAL_STYLE
# carries no media query. Inside a chip, weight and size do the work that a
# second tone would have done.
NEUTRAL = "#737a87"
NEUTRAL_TRACK = "#8b929e"

NEUTRAL_STYLE = f"""
    .neutral {{ fill: {NEUTRAL}; }}
    .neutral-track {{ fill: {NEUTRAL_TRACK}; }}
"""

# Every class in STYLE that `text` may be asked for, with its light colour. A
# new text class belongs in both halves of STYLE *and* here, or `text` raises.
# `.neutral` is the one entry with no second half, because the layouts that
# paint with it have no dark mode to switch into.
TEXT_FILLS = {
    "title": "#6b7280",
    "figure": "#1c1e21",
    "label": "#1c1e21",
    "muted": "#6b7280",
    "neutral": NEUTRAL,
}

FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def language_rules(names: dict[str, str], any_bg: bool = False) -> str:
    """One fill rule per language, light first and dark as an override, matching
    how `.bg` and the rest are written above.

    No language *name* reaches the stylesheet, since the classes are numbered,
    so there is nothing here to escape.

    With `any_bg` there is no override and no media query. Each language gets
    one colour that clears the floor on either background, which is all a
    layout can use when it does not know which background it is on.
    """
    if any_bg:
        return "".join(f"    .{cls} {{ fill: {color_for(lang, any_bg=True)}; }}\n"
                       for lang, cls in names.items())
    light = "".join(f"    .{cls} {{ fill: {color_for(lang)}; }}\n"
                    for lang, cls in names.items())
    dark = "".join(f"      .{cls} {{ fill: {color_for(lang, dark=True)}; }}\n"
                   for lang, cls in names.items())
    return light + "    @media (prefers-color-scheme: dark) {\n" + dark + "    }\n"


def num(value: float) -> str:
    """Coordinates as short decimals, so two runs never differ by float noise."""
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def text(x, y, content, cls, size, weight=400, anchor="start") -> str:
    return (
        f'<text x="{num(x)}" y="{num(y)}" class="{cls}" fill="{TEXT_FILLS[cls]}" '
        f'font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}">{escape(content)}</text>'
    )


# Advance widths for the font stack above, as a fraction of the type size,
# rounded off Helvetica's. There is no font metrics library here and there is
# not going to be one (see the zero-dependency rule), so any layout that has to
# wrap or to place one string after another measures with these buckets. They
# err a little wide on purpose. A chip measured too big wraps one chip early;
# one measured too small collides with whatever follows it.
_NARROW = set(".,:;'`|iljI1!ft()[]{}-")
_WIDE = set("MWmw@%")


def text_width(content: str, size: float, weight: int = 400) -> float:
    total = 0.0
    for char in content:
        if char == " ":
            total += 0.28
        elif char in _NARROW:
            total += 0.34
        elif char in _WIDE:
            total += 0.95
        elif char.isdigit():
            total += 0.57
        elif char.isupper():
            total += 0.70
        else:
            total += 0.56
    return total * size * (1.06 if weight >= 600 else 1.0)


ELLIPSIS = "\u2026"


def ellipsize(label: str, size: float, weight: int, max_width: float) -> str:
    """Shorten a label until it fits, measuring it the way the layout places it.

    Language names are short enough that this never triggers. Project names are
    not, and they sit left of a right-aligned number.
    """
    if max_width <= 0 or text_width(label, size, weight) <= max_width:
        return label
    trimmed = label
    while trimmed and text_width(trimmed + ELLIPSIS, size, weight) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ELLIPSIS) if trimmed else ELLIPSIS


def series(report: Report, by: str = DEFAULT_SUBJECT) -> list[tuple[str, int]]:
    """One (label, code lines) pair per row, in the order `--sort` asked for.

    `languages_sorted` and `projects_sorted` both drop the failures and sort
    themselves, so this is the only place in the package that knows a layout
    can be drawn over projects rather than languages. Every layout works off
    the pairs.
    """
    if by == "project":
        return [(project.name, project.total.code) for project in
                report.projects_sorted()]
    return [(name, count.code) for name, count in report.languages_sorted()]


def top_rows(items: list[tuple[str, int]], rows: int) -> list[tuple[str, int]]:
    """The first `rows` entries, or every entry when `rows` is 0.

    The three layouts that keep a labelled list share this, so `--svg-rows 0`
    means the same thing in each of them.
    """
    return items[:rows] if rows > 0 else items


def open_svg(
    width: int,
    height: int,
    label: str,
    names: dict[str, str],
    any_bg: bool = False,
) -> list[str]:
    """The root element, and one of the two stylesheets.

    A framed layout gets STYLE and its dark override. A frameless one gets
    NEUTRAL_STYLE, which names only the classes it paints with, so the file it
    writes contains no `prefers-color-scheme` at all.
    """
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{escape(label)}">',
        f"<style>{NEUTRAL_STYLE if any_bg else STYLE}"
        f"{language_rules(names, any_bg)}</style>",
    ]


def frame(width: int, height: int) -> str:
    """The card background, inset half a pixel so the 1px stroke lands on the
    pixel grid rather than straddling it."""
    return (
        f'<rect class="bg" fill="#ffffff" stroke="#e3e6ea" x="0.5" y="0.5" '
        f'width="{width - 1}" height="{height - 1}" rx="10"/>'
    )


def summary_line(report: Report) -> str:
    return (
        f"{len(report.counted)} projects  ·  "
        f"{group_digits(report.grand_total.files)} files  ·  "
        f"{len(report.by_language)} languages"
    )


def footer_line(report: Report) -> str:
    """The signature every framed layout carries: clocwork drew the card, cloc
    counted the lines, and the date it happened.

    No version numbers. The card is a badge, and TXT, Markdown and HTML have
    the room to say which cloc and which clocwork produced the numbers. The
    frameless layouts (`strip`, `bar`) carry no footer at all; they sit under
    other content, and the README that embeds them is where the credit goes.
    """
    return f"clocwork · cloc · {report.generated_at.split(' ')[0]}"


def header(
    report: Report,
    x: int,
    title_baseline: int,
    figure_baseline: int,
    subtitle_baseline: int,
) -> list[str]:
    """Title, grand total, and the one-line summary under it."""
    return [
        text(x, title_baseline, "LINES OF CODE", "title", 11, 600),
        text(x, figure_baseline, group_digits(report.grand_total.code), "figure",
             32, 700),
        text(x, subtitle_baseline, summary_line(report), "muted", 11),
    ]


def dot(cls: str, cx: float, cy: float, label: str, r: int = 4,
        any_bg: bool = False) -> str:
    return (
        f'<circle class="{cls}" cx="{num(cx)}" cy="{num(cy)}" r="{r}" '
        f'fill="{color_for(label, any_bg=any_bg)}"/>'
    )


LABEL_GAP = 12  # the least space left between a row label and its value


def legend_row(
    left: float,
    right: float,
    baseline: float,
    label: str,
    cls: str,
    value: str,
    size: int = 12,
) -> list[str]:
    """Dot, label, right-aligned value. The value keeps its width and the label
    gives way, which only happens with long project names."""
    room = right - (left + 16) - text_width(value, size) - LABEL_GAP
    return [
        dot(cls, left + 4, baseline - 4, label),
        text(left + 16, baseline, ellipsize(label, size, 500, room), "label",
             size, 500),
        text(right, baseline, value, "muted", size, anchor="end"),
    ]


def proportion_bar(
    x: int,
    y: int,
    width: int,
    height: int,
    items: Sequence[tuple[str, int]],
    total: int,
    names: dict[str, str],
    clip_id: str = "barclip",
    any_bg: bool = False,
) -> list[str]:
    """Track, clip, and one segment per item, widest first.

    The group carries `id="bar"` so a test can find its segments without
    sweeping every <g> in the document.
    """
    radius = height / 2
    track_cls, track_fill = (
        ("neutral-track", NEUTRAL_TRACK) if any_bg else ("track", "#eceff3")
    )
    out = [
        f'<rect class="{track_cls}" fill="{track_fill}" x="{x}" y="{y}" '
        f'width="{width}" height="{height}" rx="{radius}"/>',
        f'<clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="{width}" '
        f'height="{height}" rx="{radius}"/></clipPath>',
        f'<g id="bar" clip-path="url(#{clip_id})">',
    ]
    offset = 0.0
    for label, code in items:
        segment = width * percent(code, total) / 100
        # A segment thinner than half a pixel would only muddy the edge of the
        # one before it.
        if segment < 0.5:
            continue
        out.append(
            f'<rect class="{names[label]}" x="{x + offset:.2f}" y="{y}" '
            f'width="{segment:.2f}" height="{height}" '
            f'fill="{color_for(label, any_bg=any_bg)}"/>'
        )
        offset += segment
    out.append("</g>")
    return out


def _layouts() -> dict[str, Callable[..., str]]:
    # Imported here rather than at module scope, because the layout modules
    # import the helpers above, the way `render._registry` defers its own
    # imports.
    from . import banner, bar, bars, card, donut, strip

    return {
        "card": card.render,
        "strip": strip.render,
        "bar": bar.render,
        "bars": bars.render,
        "donut": donut.render,
        "banner": banner.render,
    }


def render(
    report: Report,
    detail: bool = False,
    sections: Sequence[str] = SECTION_NAMES,
    layout: str = DEFAULT_LAYOUT,
    width: int | None = None,
    by: str = DEFAULT_SUBJECT,
    rows: int = DEFAULT_ROWS,
    title: str | None = None,
    subtitle: str | None = None,
) -> str:
    """`layout` picks the shape, `by` picks what it is drawn over, and `rows`
    caps how many of them get a label. The summary tables are the report's
    business, so this signature takes `detail` and `sections` for the registry
    contract and ignores them."""
    try:
        draw = _layouts()[layout]
    except KeyError:
        raise KeyError(
            f"unknown layout {layout!r}; choose from {', '.join(LAYOUT_NAMES)}"
        ) from None
    if by not in SUBJECT_NAMES:
        raise KeyError(
            f"unknown subject {by!r}; choose from {', '.join(SUBJECT_NAMES)}"
        )
    return draw(report, width=width, by=by, rows=rows, title=title,
                subtitle=subtitle)
