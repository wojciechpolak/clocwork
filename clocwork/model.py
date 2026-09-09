# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Data model shared by the collector and every renderer.

Renderers never touch cloc's raw JSON; they only read these objects, which is
what keeps the TXT/Markdown/HTML/SVG outputs from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import __version__


@dataclass(frozen=True)
class LangCount:
    """Line counts for one language, in one project or summed across many."""

    files: int = 0
    blank: int = 0
    comment: int = 0
    code: int = 0

    def __add__(self, other: LangCount) -> LangCount:
        return LangCount(
            files=self.files + other.files,
            blank=self.blank + other.blank,
            comment=self.comment + other.comment,
            code=self.code + other.code,
        )

    @property
    def total_lines(self) -> int:
        return self.blank + self.comment + self.code

    @classmethod
    def from_cloc(cls, blob: dict) -> LangCount:
        return cls(
            files=int(blob.get("nFiles", 0)),
            blank=int(blob.get("blank", 0)),
            comment=int(blob.get("comment", 0)),
            code=int(blob.get("code", 0)),
        )


@dataclass(frozen=True)
class ProjectReport:
    """One project's result. A failed project carries `error` and empty counts."""

    name: str
    path: str
    languages: dict[str, LangCount] = field(default_factory=dict)
    url: str | None = None
    branch: str | None = None
    commit: str | None = None
    error: str | None = None

    @property
    def total(self) -> LangCount:
        return sum(self.languages.values(), LangCount())

    @property
    def ok(self) -> bool:
        return self.error is None

    def without_languages(self, excluded: set[str]) -> ProjectReport:
        """Drop excluded languages. Totals are derived, so they follow along."""
        if not excluded:
            return self
        kept = {k: v for k, v in self.languages.items() if k not in excluded}
        return replace(self, languages=kept)


def sort_languages(
    languages: dict[str, LangCount], key: str = "code"
) -> list[tuple[str, LangCount]]:
    """Sort language entries. Ties break on name so output stays deterministic."""
    items = list(languages.items())
    if key == "name":
        return sorted(items, key=lambda kv: kv[0].lower())
    if key == "files":
        return sorted(items, key=lambda kv: (-kv[1].files, kv[0].lower()))
    return sorted(items, key=lambda kv: (-kv[1].code, kv[0].lower()))


def merge_projects(reports: list[ProjectReport], name: str) -> ProjectReport:
    """Fold several projects into one entry carrying their summed counts.

    The url, branch and commit stay unset on purpose. They identify a project
    as surely as its name does.
    """
    languages: dict[str, LangCount] = {}
    for report in reports:
        for lang, count in report.languages.items():
            languages[lang] = languages.get(lang, LangCount()) + count
    return ProjectReport(name=name, path=name, languages=languages)


@dataclass(frozen=True)
class Report:
    """Everything one run produced: per project, per language, and the total."""

    generated_at: str
    projects: list[ProjectReport]
    clocwork_version: str = __version__
    cloc_version: str | None = None
    sort_key: str = "code"

    @property
    def counted(self) -> list[ProjectReport]:
        return [p for p in self.projects if p.ok]

    @property
    def failures(self) -> list[ProjectReport]:
        return [p for p in self.projects if not p.ok]

    @property
    def by_language(self) -> dict[str, LangCount]:
        """Language totals summed across every successfully counted project."""
        totals: dict[str, LangCount] = {}
        for project in self.counted:
            for lang, count in project.languages.items():
                totals[lang] = totals.get(lang, LangCount()) + count
        return totals

    @property
    def grand_total(self) -> LangCount:
        return sum((p.total for p in self.counted), LangCount())

    def languages_sorted(self) -> list[tuple[str, LangCount]]:
        return sort_languages(self.by_language, self.sort_key)

    def projects_sorted(self) -> list[ProjectReport]:
        if self.sort_key == "name":
            return sorted(self.counted, key=lambda p: p.name.lower())
        if self.sort_key == "files":
            return sorted(self.counted, key=lambda p: (-p.total.files, p.name.lower()))
        return sorted(self.counted, key=lambda p: (-p.total.code, p.name.lower()))
