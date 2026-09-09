# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""GitHub-flavoured Markdown report.

Summary tables lead; per-project detail hides inside <details> so the file can
be dropped into a profile README without burying everything else.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from .. import __url__
from ..model import ProjectReport, Report, sort_languages
from . import CLOC_URL, SECTION_NAMES, group_digits, percent

_HEADERS = ["Files", "Code", "Comment", "Blank"]


def _linked(project: ProjectReport) -> str:
    """A project with a `url` shows its name as a link; the rest stay plain."""
    if not project.url:
        return project.name
    return f"[{project.name}]({project.url})"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _separator(count: int, first_left: bool = True) -> str:
    cells = ["---" if first_left and i == 0 else "---:" for i in range(count)]
    return _row(cells)


def render(
    report: Report,
    detail: bool = False,
    sections: Sequence[str] = SECTION_NAMES,
) -> str:
    total = report.grand_total
    out: list[str] = ["# Lines of code", ""]
    out.append(
        f"**{group_digits(total.code)}** lines of code across "
        f"**{len(report.counted)}** projects "
        f"and **{group_digits(total.files)}** files."
    )
    out.append("")
    when = f"{report.generated_at} " if report.generated_at else ""
    out.append(
        f"<sub>Generated {when}"
        f"by [clocwork]({__url__}) {report.clocwork_version}"
    )
    if report.cloc_version:
        out[-1] += f" with [cloc]({CLOC_URL}) {report.cloc_version}"
    out[-1] += "</sub>"
    out.append("")

    if "project" in sections:
        out.append("## By project")
        out.append("")
        out.append(_row(["Project", *_HEADERS, "Share"]))
        out.append(_separator(6))
        for project in report.projects_sorted():
            out.append(
                _row(
                    [
                        _linked(project),
                        group_digits(project.total.files),
                        group_digits(project.total.code),
                        group_digits(project.total.comment),
                        group_digits(project.total.blank),
                        f"{percent(project.total.code, total.code):.1f}%",
                    ]
                )
            )
        out.append(
            _row(
                [
                    "**Total**",
                    f"**{group_digits(total.files)}**",
                    f"**{group_digits(total.code)}**",
                    f"**{group_digits(total.comment)}**",
                    f"**{group_digits(total.blank)}**",
                    "**100.0%**",
                ]
            )
        )
        out.append("")

    if "language" in sections:
        out.append("## By language")
        out.append("")
        out.append(_row(["Language", *_HEADERS, "Share"]))
        out.append(_separator(6))
        for lang, count in report.languages_sorted():
            out.append(
                _row(
                    [
                        lang,
                        group_digits(count.files),
                        group_digits(count.code),
                        group_digits(count.comment),
                        group_digits(count.blank),
                        f"{percent(count.code, total.code):.1f}%",
                    ]
                )
            )
        out.append(
            _row(
                [
                    "**Total**",
                    f"**{group_digits(total.files)}**",
                    f"**{group_digits(total.code)}**",
                    f"**{group_digits(total.comment)}**",
                    f"**{group_digits(total.blank)}**",
                    "**100.0%**",
                ]
            )
        )
        out.append("")

    if detail:
        out.append("## Per project, per language")
        out.append("")
        for project in report.projects_sorted():
            name = escape(project.name)
            if project.url:
                # <summary> is HTML, not Markdown, so the link is an anchor.
                name = f'<a href="{escape(project.url)}">{name}</a>'
            summary = f"{name} — {group_digits(project.total.code)} lines"
            out.append("<details>")
            out.append(f"<summary>{summary}</summary>")
            out.append("")
            out.append(_row(["Language", *_HEADERS]))
            out.append(_separator(5))
            for lang, count in sort_languages(project.languages, report.sort_key):
                out.append(
                    _row(
                        [
                            lang,
                            group_digits(count.files),
                            group_digits(count.code),
                            group_digits(count.comment),
                            group_digits(count.blank),
                        ]
                    )
                )
            out.append("")
            out.append("</details>")
            out.append("")

    if report.failures:
        out.append("## Skipped")
        out.append("")
        for project in report.failures:
            out.append(f"- `{project.name}` — {project.error}")
        out.append("")

    return "\n".join(out)
