# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Plain-text report: fixed-width tables, no dependencies."""

from __future__ import annotations

from collections.abc import Sequence

from ..model import Report, sort_languages
from . import SECTION_NAMES, group_digits, percent

RIGHT = "r"
LEFT = "l"


def table(headers: list[str], rows: list[list[str]], aligns: str) -> list[str]:
    """Render a bordered table. `aligns` is one 'l'/'r' character per column."""
    columns = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(columns):
            widths[i] = max(widths[i], len(row[i]))

    def rule(left: str, mid: str, right: str) -> str:
        return left + mid.join("-" * (w + 2) for w in widths) + right

    def line(cells: list[str]) -> str:
        out = []
        for i, cell in enumerate(cells):
            out.append(
                cell.rjust(widths[i]) if aligns[i] == RIGHT else cell.ljust(widths[i])
            )
        return "| " + " | ".join(out) + " |"

    lines = [rule("+", "+", "+"), line(headers), rule("+", "+", "+")]
    lines.extend(line(row) for row in rows)
    lines.append(rule("+", "+", "+"))
    return lines


def _heading(text: str) -> list[str]:
    return ["", text, "=" * len(text), ""]


def render(
    report: Report,
    detail: bool = False,
    sections: Sequence[str] = SECTION_NAMES,
) -> str:
    total = report.grand_total
    lines: list[str] = []

    title = "Lines of code"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(
        f"Generated: {report.generated_at} by clocwork {report.clocwork_version}"
    )
    if report.cloc_version:
        lines.append(f"Counted with: cloc {report.cloc_version}")
    lines.append(
        f"Projects: {len(report.counted)}   "
        f"Files: {group_digits(total.files)}   "
        f"Code: {group_digits(total.code)}"
    )

    if "project" in sections:
        lines.extend(_heading("By project"))
        rows = [
            [
                project.name,
                group_digits(project.total.files),
                group_digits(project.total.code),
                group_digits(project.total.comment),
                group_digits(project.total.blank),
                f"{percent(project.total.code, total.code):.1f}%",
            ]
            for project in report.projects_sorted()
        ]
        rows.append(
            [
                "TOTAL",
                group_digits(total.files),
                group_digits(total.code),
                group_digits(total.comment),
                group_digits(total.blank),
                "100.0%",
            ]
        )
        lines.extend(
            table(
                ["Project", "Files", "Code", "Comment", "Blank", "Share"],
                rows,
                "lrrrrr",
            )
        )

    if "language" in sections:
        lines.extend(_heading("By language"))
        rows = [
            [
                lang,
                group_digits(count.files),
                group_digits(count.code),
                group_digits(count.comment),
                group_digits(count.blank),
                f"{percent(count.code, total.code):.1f}%",
            ]
            for lang, count in report.languages_sorted()
        ]
        rows.append(
            [
                "TOTAL",
                group_digits(total.files),
                group_digits(total.code),
                group_digits(total.comment),
                group_digits(total.blank),
                "100.0%",
            ]
        )
        lines.extend(
            table(
                ["Language", "Files", "Code", "Comment", "Blank", "Share"],
                rows,
                "lrrrrr",
            )
        )

    if detail:
        for project in report.projects_sorted():
            label = project.name
            if project.branch:
                label += f"  ({project.branch}"
                label += f" @ {project.commit})" if project.commit else ")"
            lines.extend(_heading(label))
            rows = [
                [
                    lang,
                    group_digits(count.files),
                    group_digits(count.code),
                    group_digits(count.comment),
                    group_digits(count.blank),
                ]
                for lang, count in sort_languages(project.languages, report.sort_key)
            ]
            rows.append(
                [
                    "TOTAL",
                    group_digits(project.total.files),
                    group_digits(project.total.code),
                    group_digits(project.total.comment),
                    group_digits(project.total.blank),
                ]
            )
            lines.extend(
                table(["Language", "Files", "Code", "Comment", "Blank"], rows, "lrrrr")
            )

    if report.failures:
        lines.extend(_heading("Skipped"))
        for project in report.failures:
            lines.append(f"  {project.name} ({project.path}): {project.error}")

    lines.append("")
    return "\n".join(lines)
