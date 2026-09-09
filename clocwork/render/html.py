# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Standalone HTML report.

One file, inline CSS, no external requests. Drop it straight onto a static
site, or open it from disk.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from .. import __url__
from ..model import ProjectReport, Report, sort_languages
from . import CLOC_URL, SECTION_NAMES, color_for, group_digits, palette, percent

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #ffffff;
  --surface: #f7f8fa;
  --border: #e3e6ea;
  --text: #1c1e21;
  --muted: #6b7280;
  --accent: #2563eb;
  --track: #eceff3;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115;
    --surface: #171a20;
    --border: #262b33;
    --text: #e6e8eb;
    --muted: #9aa3af;
    --accent: #60a5fa;
    --track: #22262e;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2.5rem 1.25rem 4rem;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        Helvetica, Arial, sans-serif;
}
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.75rem; margin: 0 0 .35rem; letter-spacing: -.02em; }
h2 { font-size: 1.1rem; margin: 2.5rem 0 .85rem; letter-spacing: -.01em; }
.meta { color: var(--muted); font-size: .85rem; margin: 0 0 2rem; }
/* Two-up when narrow, four-up when there is room, and never a lone stretched
   card on its own row, which is what plain flex-wrap would give. */
.stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: .75rem;
  margin: 0 0 .5rem;
}
@media (min-width: 40rem) {
  .stats { grid-template-columns: repeat(4, 1fr); }
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: .85rem 1rem;
}
.stat .value {
  display: block;
  font-size: 1.6rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.02em;
}
.stat .label {
  display: block;
  color: var(--muted);
  font-size: .75rem;
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-top: .2rem;
}
.bar {
  display: flex;
  height: 10px;
  border-radius: 999px;
  overflow: hidden;
  background: var(--track);
  margin: 1.25rem 0 .75rem;
}
.bar span { display: block; height: 100%; }
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: .4rem 1.1rem;
  color: var(--muted);
  font-size: .82rem;
  margin-bottom: .5rem;
}
.legend span { display: inline-flex; align-items: center; gap: .4rem; }
.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td {
  padding: .5rem .7rem;
  border-bottom: 1px solid var(--border);
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
th { color: var(--muted); font-weight: 600; font-size: .75rem;
     text-transform: uppercase; letter-spacing: .05em; }
th:first-child, td:first-child { text-align: left; }
tbody tr:hover { background: var(--surface); }
/* Tables still scroll inside .scroll if they must, but tightening the cells on
   narrow screens keeps the six-column layout out of that most of the time. */
@media (max-width: 34rem) {
  table { font-size: .82rem; }
  th, td { padding: .45rem .4rem; }
}
tfoot td { font-weight: 700; border-top: 2px solid var(--border);
           border-bottom: none; }
details { border-top: 1px solid var(--border); padding: .35rem 0; }
summary { cursor: pointer; padding: .5rem 0; font-weight: 600; }
summary::marker { color: var(--muted); }
.name { display: inline-flex; align-items: center; gap: .5rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.sub { color: var(--muted); font-weight: 400; font-size: .82rem; }
.skipped { color: var(--muted); font-size: .875rem; }
.skipped code { color: var(--text); }
"""


def _language_vars(names: dict[str, str]) -> str:
    """Custom properties for the language palette, light on `:root` and dark
    inside the media query, so one declaration on a dot serves both themes.

    Built by concatenation rather than an f-string, because CSS is nothing but
    braces.
    """
    light = "".join(f"--{cls}:{color_for(lang)};" for lang, cls in names.items())
    dark = "".join(
        f"--{cls}:{color_for(lang, dark=True)};" for lang, cls in names.items()
    )
    return (
        ":root{" + light + "}\n"
        "@media (prefers-color-scheme: dark){:root{" + dark + "}}\n"
    )


def _swatch(lang: str, names: dict[str, str]) -> str:
    """The theme-aware colour for one language, with the light hex as the
    `var()` fallback so a fragment copied out of the page keeps its colour."""
    cls = names.get(lang)
    if cls is None:
        return color_for(lang)
    return f"var(--{cls},{color_for(lang)})"


def _linked(project: ProjectReport) -> str:
    """A project with a `url` shows its name as a link; the rest stay plain."""
    name = escape(project.name)
    if not project.url:
        return name
    return f'<a href="{escape(project.url)}">{name}</a>'


def _stat(value: str, label: str) -> str:
    return (
        f'<div class="stat"><span class="value">{escape(value)}</span>'
        f'<span class="label">{escape(label)}</span></div>'
    )


def _table(headers, rows, footer) -> list[str]:
    out = ['<div class="scroll"><table>', "<thead><tr>"]
    out.extend(f"<th>{escape(h)}</th>" for h in headers)
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    out.append("</tbody>")
    if footer:
        out.append(
            "<tfoot><tr>" + "".join(f"<td>{c}</td>" for c in footer) + "</tr></tfoot>"
        )
    out.append("</table></div>")
    return out


def _counts(count) -> list[str]:
    return [
        group_digits(count.files),
        group_digits(count.code),
        group_digits(count.comment),
        group_digits(count.blank),
    ]


def render(
    report: Report,
    detail: bool = False,
    sections: Sequence[str] = SECTION_NAMES,
) -> str:
    total = report.grand_total
    languages = report.languages_sorted()
    # Every language in the report, so the per-project tables below draw from
    # the same variables as the summary.
    names = palette(lang for lang, _ in languages)

    out = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">']
    out.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    out.append("<title>Lines of code</title>")
    out.append(f"<style>{STYLE}{_language_vars(names)}</style>")
    out.append("</head>")
    out.append("<body><main>")
    out.append("<h1>Lines of code</h1>")

    meta = (
        f"Generated {escape(report.generated_at)} &middot; "
        f'<a href="{__url__}">clocwork</a> {escape(report.clocwork_version)}'
    )
    if report.cloc_version:
        meta += (
            f' &middot; <a href="{CLOC_URL}">cloc</a> '
            f"{escape(report.cloc_version)}"
        )
    out.append(f'<p class="meta">{meta}</p>')

    out.append('<div class="stats">')
    out.append(_stat(group_digits(total.code), "lines of code"))
    out.append(_stat(str(len(report.counted)), "projects"))
    out.append(_stat(group_digits(total.files), "files"))
    out.append(_stat(str(len(languages)), "languages"))
    out.append("</div>")

    # Proportion bar: a whole-corpus view before any of the numbers.
    out.append('<div class="bar">')
    for lang, count in languages:
        share = percent(count.code, total.code)
        if share < 0.1:
            continue
        out.append(
            f'<span style="width:{share:.3f}%;background:{_swatch(lang, names)}"'
            f' title="{escape(lang)} — {group_digits(count.code)}"></span>'
        )
    out.append("</div>")

    out.append('<div class="legend">')
    for lang, count in languages[:8]:
        out.append(
            f'<span><i class="dot" style="background:{_swatch(lang, names)}"></i>'
            f"{escape(lang)} {percent(count.code, total.code):.1f}%</span>"
        )
    out.append("</div>")

    if "project" in sections:
        out.append("<h2>By project</h2>")
        rows = []
        for project in report.projects_sorted():
            label = _linked(project)
            if project.branch:
                label += f' <span class="sub">{escape(project.branch)}</span>'
            rows.append(
                [
                    label,
                    *_counts(project.total),
                    f"{percent(project.total.code, total.code):.1f}%",
                ]
            )
        out.extend(
            _table(
                ["Project", "Files", "Code", "Comment", "Blank", "Share"],
                rows,
                ["Total", *_counts(total), "100.0%"],
            )
        )

    if "language" in sections:
        out.append("<h2>By language</h2>")
        rows = [
            [
                f'<span class="name"><i class="dot" '
                f'style="background:{_swatch(lang, names)}"></i>'
                f"{escape(lang)}</span>",
                *_counts(count),
                f"{percent(count.code, total.code):.1f}%",
            ]
            for lang, count in languages
        ]
        out.extend(
            _table(
                ["Language", "Files", "Code", "Comment", "Blank", "Share"],
                rows,
                ["Total", *_counts(total), "100.0%"],
            )
        )

    if detail:
        out.append("<h2>Per project, per language</h2>")
        for project in report.projects_sorted():
            out.append("<details>")
            out.append(
                f"<summary>{_linked(project)} "
                f'<span class="sub">{group_digits(project.total.code)} lines</span>'
                "</summary>"
            )
            rows = [
                [
                    f'<span class="name"><i class="dot" '
                    f'style="background:{_swatch(lang, names)}"></i>'
                    f"{escape(lang)}</span>",
                    *_counts(count),
                ]
                for lang, count in sort_languages(project.languages, report.sort_key)
            ]
            out.extend(
                _table(
                    ["Language", "Files", "Code", "Comment", "Blank"],
                    rows,
                    ["Total", *_counts(project.total)],
                )
            )
            out.append("</details>")

    if report.failures:
        out.append("<h2>Skipped</h2>")
        out.append('<ul class="skipped">')
        for project in report.failures:
            out.append(
                f"<li><code>{escape(project.name)}</code> — "
                f"{escape(project.error or '')}</li>"
            )
        out.append("</ul>")

    out.append("</main></body></html>")
    return "\n".join(out)
