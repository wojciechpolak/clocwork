# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Renderer registry and helpers shared by every output format.

Each renderer is `render(report, detail=False, sections=SECTION_NAMES) -> str`,
plus whatever extra keywords it declares in `Format.options`. Adding a format
means one module plus one entry in `_registry`.
"""

from __future__ import annotations

import colorsys
import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import cache

from ..model import Report

# cloc counted the lines; the Markdown and HTML meta lines say so and link
# it, next to clocwork's own `__url__`.
CLOC_URL = "https://github.com/AlDanial/cloc"

# A fixed palette so a language keeps its colour between HTML and SVG, and
# between runs. Anything unlisted falls back to a hue derived from its name.
#
# These are the *light* colours. Linguist picks them to sit on a white page, and
# several of them all but vanish on the dark card: Lua at 1.18:1, Less at 1.56,
# Ruby at 1.63. `_fit` derives the dark palette from this table rather than a
# second one typed out beside it. Two tables drift, and a second table could not
# cover the hue hash below.
LANGUAGE_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Python": "#3572a5",
    "Go": "#00add8",
    "Rust": "#dea584",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Java": "#b07219",
    "Kotlin": "#a97bff",
    "Swift": "#f05138",
    "Ruby": "#701516",
    "PHP": "#4f5d95",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Sass": "#a53b70",
    "Less": "#1d365d",
    "Vuejs Component": "#41b883",
    "Svelte": "#ff3e00",
    "JSON": "#8a8a8a",
    "YAML": "#cb171e",
    "TOML": "#9c4221",
    "XML": "#0060ac",
    "Markdown": "#083fa1",
    "Bourne Shell": "#89e051",
    "Bourne Again Shell": "#89e051",
    "SQL": "#e38c00",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "make": "#427819",
    "CMake": "#da3434",
    "Lua": "#000080",
    "Perl": "#0298c3",
    "Elixir": "#6e4a7e",
    "Haskell": "#5e5086",
    "Dart": "#00b4ab",
    "Text": "#9e9e9e",
    "INI": "#d1dbe0",
}


# The two backgrounds a colour has to survive. They must stay equal to `--bg` in
# `html.STYLE` and to the `.bg` fill in `svg.STYLE`, in both themes. A test
# asserts it, because a palette fitted to the wrong background is worse than one
# that was never fitted at all.
LIGHT_BG = "#ffffff"
DARK_BG = "#0f1115"

# WCAG 1.4.11. Dots and bar segments are graphics rather than text, so 3:1 is
# the bar to clear, not 4.5:1. At 4.5 Ruby and CMake collapse into the same
# red.
CONTRAST_FLOOR = 3.0


def _rgb(color: str) -> tuple[float, float, float]:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return r, g, b


def _hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (round(c * 255) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _luminance(color: str) -> float:
    r, g, b = (
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(color)
    )
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    """WCAG contrast between two #rrggbb colours: 1.0 identical, 21.0 at most."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _fit(color: str, background: str) -> str:
    """Walk a colour's lightness away from `background` until it clears the floor.

    It leaves hue and saturation alone, so a language stays recognisably
    itself; only how much light it carries changes. A colour that already clears the
    floor comes back untouched, which in dark mode is 27 of the 39 above.
    """
    hue, lightness, saturation = colorsys.rgb_to_hls(*_rgb(color))
    step = 0.01 if _luminance(background) < 0.5 else -0.01
    while contrast_ratio(color, background) < CONTRAST_FLOOR:
        nudged = min(0.95, max(0.05, lightness + step))
        if nudged == lightness:  # as pale (or as deep) as it goes
            break
        lightness = nudged
        color = _hex(colorsys.hls_to_rgb(hue, lightness, saturation))
    return color


def _fit_both(color: str) -> str:
    """Fit a colour to clear the floor against *both* backgrounds.

    A layout that draws no background of its own cannot know what it will sit
    on, so its colours have to work either way. Lighten until it clears the
    dark page, then darken until it clears the white one. The two constraints
    leave a band of lightness wide enough that the second pass never undoes
    what the first did.
    """
    return _fit(_fit(color, DARK_BG), LIGHT_BG)


def _hue(name: str) -> int:
    """A hue from a name, spread across the wheel and the same on every machine.

    A digest rather than a sum of character codes. The sum sent names of
    similar length and spelling to neighbouring hues. Nobody noticed while it
    only coloured the odd unlisted language, and then `--by project` hashed a
    whole chart and six of fourteen projects came out green. blake2s is
    standard library, it is stable across processes where `hash()` is not, and
    four bytes are enough.
    """
    digest = hashlib.blake2s(name.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % 360


@cache
def color_for(language: str, dark: bool = False, any_bg: bool = False) -> str:
    """Stable colour per language, from the table above or else a hue from its
    name, fitted to the theme background where it would otherwise disappear.

    The table's light colours go through untouched. Ten of them sit
    below the floor on white, JavaScript yellow at 1.35:1 being the worst. But
    they are linguist's, they are what GitHub itself shows on a white page, and
    every dot here is labelled with its language anyway. Recognisability wins.
    Dark mode has no such palette to be faithful to, and there the failures are
    not "low contrast" but invisible. Lua at 1.18:1 on the card is the
    background. The hue hash has no identity to protect either, so it is fitted
    in both directions. Its fixed 48% lightness fails on white for the
    yellow-greens just as it fails on the card for the reds and blues.

    `any_bg` is the third case, and it outranks `dark`. The frameless layouts
    sit on a page whose colour nothing here knows, so their fills are fitted to
    both backgrounds at once. Identity loses to visibility there. A navy dot on
    a dark README is not a subtler blue, it is nothing.
    """
    known = LANGUAGE_COLORS.get(language)
    if known:
        if any_bg:
            return _fit_both(known)
        return _fit(known, DARK_BG) if dark else known
    hue = _hue(language)
    # The same hsl(hue, 45%, 48%) as always, spelled in hex, because `_fit`
    # needs channels to measure and an SVG fill is safer as a plain colour.
    hashed = _hex(colorsys.hls_to_rgb(hue / 360, 0.48, 0.45))
    if any_bg:
        return _fit_both(hashed)
    return _fit(hashed, DARK_BG if dark else LIGHT_BG)


def palette(languages: Iterable[str]) -> dict[str, str]:
    """Language -> CSS identifier, `l0` upward, shared by the HTML and the SVG.

    Named by index rather than by language, because slugging the name collides
    (`C` and `C#` both give `c`) and would put report text inside a `<style>`
    block.
    """
    return {language: f"l{index}" for index, language in enumerate(languages)}


# Digit grouping uses a plain ASCII space on purpose. The TXT report stays
# copy-pasteable everywhere, and the HTML/SVG tables already set nowrap.
DIGIT_SEPARATOR = " "


def group_digits(n: int) -> str:
    """12345 -> '12 345', readable in every output format."""
    return f"{n:,}".replace(",", DIGIT_SEPARATOR)


def humanize(n: int) -> str:
    """Compact form for the SVG card, where horizontal space is scarce."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        value = n / 1000
        return f"{value:.1f}k" if value < 100 else f"{value:.0f}k"
    return f"{n / 1_000_000:.1f}M"


def percent(part: int, whole: int) -> float:
    return (part / whole * 100) if whole else 0.0


@dataclass(frozen=True)
class Format:
    name: str
    extension: str
    render: Callable[..., str]
    # The SVG is a summary card, not a full report, so it gets its own basename.
    filename_stem: str | None = None
    # Extra keywords this format's `render` accepts beyond detail and sections.
    # `render` below forwards only what the format declares, which is how the
    # SVG takes a layout and a width without the other three growing arguments
    # they would ignore.
    options: frozenset[str] = frozenset()


def _registry() -> dict[str, Format]:
    from . import html, markdown, svg, txt

    return {
        "txt": Format("txt", ".txt", txt.render),
        "md": Format("md", ".md", markdown.render),
        "html": Format("html", ".html", html.render),
        "svg": Format(
            "svg",
            ".svg",
            svg.render,
            filename_stem="card",
            options=frozenset(
                {"layout", "width", "by", "rows", "title", "subtitle"}
            ),
        ),
    }


FORMAT_NAMES = ("txt", "md", "html", "svg")

# The summary tables a standard run emits, and the order `resolve_sections`
# returns them in. Picking a subset is presentation only. Every surviving table
# holds the numbers it would have held in a full run.
SECTION_NAMES = ("project", "language")

# The shapes the SVG can be drawn in, and the order `cli.resolve_layouts`
# returns them in. A layout is a picture over the same numbers, not a filter.
# Each one writes its own file, named after itself.
LAYOUT_NAMES = ("card", "strip", "bar", "bars", "donut", "banner")
# The two that draw no background rect. They sit under other content, so the
# page supplies their background and they never learn what colour it is. Both
# take their fills from `color_for(any_bg=True)` and ask for no theme at all.
FRAMELESS_LAYOUTS = ("strip", "bar")
DEFAULT_LAYOUT = "card"

# What an SVG layout is drawn over. The same five shapes either way. The
# subject decides where the rows come from, nothing else. Only the SVG has the
# option. TXT, Markdown and HTML print both tables already, and `--sections`
# picks between them.
SUBJECT_NAMES = ("language", "project")
DEFAULT_SUBJECT = "language"

# How many rows the layouts that keep a labelled list will name: `card`, `bars`
# and `donut`. A shape argument like the two above, not a filter. The proportion
# bar and the donut ring still cover everything counted, and only the labelled
# list is cut. 0 means every row. `strip` and `bar` keep no such list and ignore
# it, since their own caps count wrapped lines rather than entries.
DEFAULT_ROWS = 6


def get(name: str) -> Format:
    formats = _registry()
    try:
        return formats[name]
    except KeyError:
        raise KeyError(
            f"unknown format {name!r}; choose from {', '.join(FORMAT_NAMES)}"
        ) from None


def render(
    name: str,
    report: Report,
    detail: bool = False,
    sections: Sequence[str] = SECTION_NAMES,
    **options,
) -> str:
    """Passes extra keywords on to the formats that declare them and to no
    others, so a caller can hand the same arguments to every format."""
    fmt = get(name)
    extra = {k: v for k, v in options.items() if k in fmt.options and v is not None}
    return fmt.render(report, detail=detail, sections=sections, **extra)
