# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clocwork import collect
from clocwork.config import ProjectSpec
from tests.helpers import FIXTURES

SAMPLE = (FIXTURES / "cloc_sample.json").read_text()


def spec(tmp: Path, **kwargs) -> ProjectSpec:
    return ProjectSpec(name=kwargs.pop("name", "alpha"), path=tmp, **kwargs)


class TestParse(unittest.TestCase):
    def test_header_and_sum_are_not_languages(self):
        languages = collect.parse_cloc_json(SAMPLE)
        self.assertEqual(set(languages), {"Go", "JSON", "Markdown"})

    def test_counts_match_the_fixture(self):
        languages = collect.parse_cloc_json(SAMPLE)
        self.assertEqual(languages["Go"].code, 1000)
        self.assertEqual(languages["Go"].files, 10)

    def test_parsed_total_matches_cloc_sum(self):
        languages = collect.parse_cloc_json(SAMPLE)
        total = sum(c.code for c in languages.values())
        self.assertEqual(total, json.loads(SAMPLE)["SUM"]["code"])

    def test_non_object_payload(self):
        with self.assertRaises(ValueError):
            collect.parse_cloc_json("[1, 2]")


class TestArgv(unittest.TestCase):
    def test_git_repo_uses_vcs_listing(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (tmp / ".git").mkdir()
        argv = collect.build_argv(spec(tmp))
        self.assertIn("--vcs=git", argv)
        self.assertEqual(argv[-1], ".")

    def test_hide_rate_is_never_passed(self):
        # cloc 1.98, which is what apt installs on Ubuntu, closes the header
        # with a trailing comma when it is shortened by --hide-rate, and no
        # JSON parser accepts that. parse_cloc_json drops the header anyway,
        # so there is nothing to gain by asking.
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertNotIn("--hide-rate", collect.build_argv(spec(tmp)))

    def test_plain_directory_skips_vcs(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.assertNotIn("--vcs=git", collect.build_argv(spec(tmp)))

    def test_excludes_and_passthrough_args(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        argv = collect.build_argv(
            spec(tmp, exclude_dirs=["vendor", "fixtures"], cloc_args=["--no3"])
        )
        self.assertIn("--exclude-dir=vendor,fixtures", argv)
        self.assertIn("--no3", argv)


class TestCollectProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def run_with(self, **proc):
        completed = subprocess.CompletedProcess(
            args=["cloc"],
            returncode=proc.get("returncode", 0),
            stdout=proc.get("stdout", SAMPLE),
            stderr=proc.get("stderr", ""),
        )
        with mock.patch.object(collect.subprocess, "run", return_value=completed):
            return collect.collect_project(spec(self.tmp, **proc.get("spec", {})))

    def test_success(self):
        report = self.run_with()
        self.assertIsNone(report.error)
        self.assertEqual(report.total.code, 1490)

    def test_exclude_langs_applied_after_counting(self):
        report = self.run_with(spec={"exclude_langs": ["JSON", "Markdown"]})
        self.assertEqual(set(report.languages), {"Go"})
        self.assertEqual(report.total.code, 1000)

    def test_url_reaches_the_report(self):
        report = self.run_with(spec={"url": "https://example.com/alpha"})
        self.assertEqual(report.url, "https://example.com/alpha")

    def test_a_failed_project_keeps_its_url(self):
        missing = ProjectSpec(
            name="gone", path=self.tmp / "nope", url="https://example.com/gone"
        )
        self.assertEqual(collect.collect_project(missing).url,
                         "https://example.com/gone")

    def test_missing_directory(self):
        missing = ProjectSpec(name="gone", path=self.tmp / "nope")
        report = collect.collect_project(missing)
        self.assertEqual(report.error, "directory not found")
        self.assertEqual(report.total.code, 0)

    def test_nonzero_exit_reports_last_stderr_line(self):
        report = self.run_with(returncode=1, stderr="warning\nfatal: bad repo\n")
        self.assertEqual(report.error, "fatal: bad repo")

    def test_empty_output(self):
        self.assertEqual(self.run_with(stdout="  \n").error, "no countable files")

    def test_unparseable_output(self):
        self.assertIn("unreadable", self.run_with(stdout="not json").error)

    def test_timeout(self):
        with mock.patch.object(
            collect.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="cloc", timeout=5),
        ):
            report = collect.collect_project(spec(self.tmp), timeout=5)
        self.assertIn("timed out", report.error or "")

    def test_collect_all_continues_past_a_failure(self):
        specs = [
            ProjectSpec(name="gone", path=self.tmp / "nope"),
            ProjectSpec(name="ok", path=self.tmp),
        ]
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with mock.patch.object(collect.subprocess, "run", return_value=completed):
            reports = collect.collect_all(specs)
        self.assertEqual([r.ok for r in reports], [False, True])


class TestRemoteProject(unittest.TestCase):
    """A remote project is synced first, and a sync that fails is a skipped row."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def remote(self) -> ProjectSpec:
        return ProjectSpec(
            name="hello-world",
            path=self.tmp,
            repo="https://example.com/acme/hello-world.git",
            branch="main",
        )

    def test_the_clone_happens_before_the_count(self):
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with (
            mock.patch.object(collect, "sync", return_value=None) as sync,
            mock.patch.object(collect.subprocess, "run", return_value=completed),
        ):
            report = collect.collect_project(self.remote(), timeout=7)
        sync.assert_called_once()
        self.assertEqual(sync.call_args.kwargs, {"timeout": 7, "fetch": True})
        self.assertTrue(report.ok)

    def test_a_clone_that_fails_never_reaches_cloc(self):
        with (
            mock.patch.object(collect, "sync", return_value="fatal: not found"),
            mock.patch.object(collect.subprocess, "run") as run,
        ):
            report = collect.collect_project(self.remote())
        run.assert_not_called()
        self.assertEqual(report.error, "fatal: not found")

    def test_no_fetch_travels_all_the_way_down(self):
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with (
            mock.patch.object(collect, "sync", return_value=None) as sync,
            mock.patch.object(collect.subprocess, "run", return_value=completed),
        ):
            collect.collect_all([self.remote()], fetch=False)
        self.assertIs(sync.call_args.kwargs["fetch"], False)

    def test_a_local_project_is_never_synced(self):
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with (
            mock.patch.object(collect, "sync") as sync,
            mock.patch.object(collect.subprocess, "run", return_value=completed),
        ):
            collect.collect_project(spec(self.tmp))
        sync.assert_not_called()


class TestEnsureCloc(unittest.TestCase):
    def test_missing_binary_explains_how_to_install(self):
        with (
            mock.patch.object(collect.shutil, "which", return_value=None),
            self.assertRaisesRegex(collect.ClocMissing, "brew install cloc"),
        ):
            collect.ensure_cloc()


if __name__ == "__main__":
    unittest.main()
