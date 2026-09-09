# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from clocwork.model import (
    LangCount,
    ProjectReport,
    Report,
    merge_projects,
    sort_languages,
)
from tests.helpers import sample_report


class TestLangCount(unittest.TestCase):
    def test_addition(self):
        total = LangCount(1, 2, 3, 4) + LangCount(10, 20, 30, 40)
        self.assertEqual(total, LangCount(11, 22, 33, 44))

    def test_sum_starts_from_zero(self):
        counts = [LangCount(1, 1, 1, 1), LangCount(2, 2, 2, 2)]
        self.assertEqual(sum(counts, LangCount()), LangCount(3, 3, 3, 3))

    def test_total_lines_excludes_file_count(self):
        self.assertEqual(LangCount(files=9, blank=1, comment=2, code=3).total_lines, 6)

    def test_from_cloc(self):
        blob = {"nFiles": 3, "blank": 4, "comment": 5, "code": 6}
        self.assertEqual(LangCount.from_cloc(blob), LangCount(3, 4, 5, 6))


class TestProjectReport(unittest.TestCase):
    def test_total_is_derived_from_languages(self):
        project = ProjectReport(
            name="p",
            path="/p",
            languages={
                "Go": LangCount(1, 1, 1, 10),
                "C": LangCount(2, 2, 2, 20),
            },
        )
        self.assertEqual(project.total, LangCount(3, 3, 3, 30))

    def test_without_languages_updates_the_total(self):
        project = ProjectReport(
            name="p",
            path="/p",
            languages={"Go": LangCount(1, 1, 1, 10), "JSON": LangCount(5, 0, 0, 999)},
        )
        trimmed = project.without_languages({"JSON"})
        self.assertEqual(list(trimmed.languages), ["Go"])
        self.assertEqual(trimmed.total.code, 10)
        # The original is untouched.
        self.assertEqual(project.total.code, 1009)

    def test_without_languages_is_a_noop_when_empty(self):
        project = ProjectReport(name="p", path="/p", languages={"Go": LangCount()})
        self.assertIs(project.without_languages(set()), project)

    def test_ok_reflects_error(self):
        self.assertTrue(ProjectReport(name="p", path="/p").ok)
        self.assertFalse(ProjectReport(name="p", path="/p", error="boom").ok)


class TestReport(unittest.TestCase):
    def test_by_language_sums_across_projects(self):
        report = sample_report()
        self.assertEqual(report.by_language["Go"], LangCount(11, 105, 52, 1050))
        self.assertEqual(report.by_language["TypeScript"].code, 600)

    def test_grand_total(self):
        self.assertEqual(sample_report().grand_total.code, 2050)

    def test_failures_are_excluded_from_totals(self):
        report = sample_report(with_failure=True)
        self.assertEqual(len(report.counted), 2)
        self.assertEqual([p.name for p in report.failures], ["gamma"])
        self.assertEqual(report.grand_total.code, 2050)

    def test_empty_report_totals_to_zero(self):
        report = Report(generated_at="now", projects=[])
        self.assertEqual(report.grand_total, LangCount())
        self.assertEqual(report.by_language, {})

    def test_sort_keys(self):
        report = sample_report()
        self.assertEqual(next(n for n, _ in report.languages_sorted()), "Go")
        by_name = Report(
            generated_at="now", projects=report.projects, sort_key="name"
        )
        self.assertEqual(next(n for n, _ in by_name.languages_sorted()), "Go")
        self.assertEqual([p.name for p in by_name.projects_sorted()], ["alpha", "beta"])

    def test_sort_languages_breaks_ties_by_name(self):
        languages = {
            "Zig": LangCount(code=100),
            "Ada": LangCount(code=100),
        }
        self.assertEqual([n for n, _ in sort_languages(languages)], ["Ada", "Zig"])


class TestMergeProjects(unittest.TestCase):
    def test_sums_languages_across_projects(self):
        merged = merge_projects(sample_report().counted, "UNDISCLOSED")
        self.assertEqual(merged.name, "UNDISCLOSED")
        self.assertEqual(merged.total.code, 2050)
        self.assertEqual(
            merged.languages["Go"],
            LangCount(files=11, blank=105, comment=52, code=1050),
        )

    def test_drops_everything_that_identifies_a_project(self):
        merged = merge_projects(sample_report().counted, "UNDISCLOSED")
        self.assertIsNone(merged.url)
        self.assertIsNone(merged.branch)
        self.assertIsNone(merged.commit)
        self.assertEqual(merged.path, "UNDISCLOSED")
        self.assertTrue(merged.ok)

    def test_empty_input_is_an_empty_entry(self):
        merged = merge_projects([], "UNDISCLOSED")
        self.assertEqual(merged.languages, {})
        self.assertEqual(merged.total, LangCount())


if __name__ == "__main__":
    unittest.main()
