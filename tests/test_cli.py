# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import chdir, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from clocwork import cli, collect
from clocwork import render as render_pkg
from clocwork.config import ProjectSpec
from clocwork.model import LangCount, ProjectReport
from clocwork.render.svg import strip as strip_layout
from tests.helpers import FIXTURES

SAMPLE = (FIXTURES / "cloc_sample.json").read_text()


class TestHelpWidth(unittest.TestCase):
    """--help stays readable on a terminal of any width."""

    @staticmethod
    def help_at(columns):
        with mock.patch.dict(os.environ, {"COLUMNS": str(columns)}):
            return cli.build_parser().format_help()

    def test_wide_terminal_is_capped(self):
        for line in self.help_at(200).splitlines():
            self.assertLessEqual(len(line), cli.HELP_WIDTH, line)

    def test_narrow_terminal_wraps_narrower_still(self):
        # The cap is a ceiling, not a target: 50 columns must not be padded
        # back out to 80. The epilog is raw and sets its own width, so it
        # is cut off the end and only the option help is measured.
        options = self.help_at(50).split("options:", 1)[1].split("examples:")[0]
        self.assertLessEqual(max(len(x) for x in options.splitlines()), 50)

    def test_description_fits_unwrapped(self):
        # RawDescriptionHelpFormatter never folds the description, so its
        # length is the author's problem rather than the formatter's.
        first = self.help_at(200).split("\n\n")[1]
        self.assertNotIn("\n", first)
        self.assertLessEqual(len(first), cli.HELP_WIDTH)


class TestFormatSelection(unittest.TestCase):
    def test_all(self):
        self.assertEqual(cli.resolve_formats("all"), list(render_pkg.FORMAT_NAMES))

    def test_subset_keeps_order_given(self):
        self.assertEqual(cli.resolve_formats("md, svg"), ["md", "svg"])

    def test_unknown(self):
        with self.assertRaisesRegex(ValueError, "unknown format"):
            cli.resolve_formats("txt,pdf")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "no formats"):
            cli.resolve_formats(" , ")


class TestSectionSelection(unittest.TestCase):
    def test_all(self):
        self.assertEqual(cli.resolve_sections("all"), list(render_pkg.SECTION_NAMES))

    def test_subset(self):
        self.assertEqual(cli.resolve_sections("language"), ["language"])

    def test_order_given_does_not_reorder_the_report(self):
        self.assertEqual(
            cli.resolve_sections("language, project"), list(render_pkg.SECTION_NAMES)
        )

    def test_unknown(self):
        with self.assertRaisesRegex(ValueError, "unknown section"):
            cli.resolve_sections("project,files")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "no sections"):
            cli.resolve_sections(" , ")


class TestLayoutSelection(unittest.TestCase):
    def test_all(self):
        self.assertEqual(cli.resolve_layouts("all"), list(render_pkg.LAYOUT_NAMES))

    def test_default_is_the_card_alone(self):
        self.assertEqual(cli.resolve_layouts(render_pkg.DEFAULT_LAYOUT), ["card"])

    def test_order_given_does_not_change_the_files_written(self):
        self.assertEqual(cli.resolve_layouts("strip, card"), ["card", "strip"])

    def test_unknown(self):
        with self.assertRaisesRegex(ValueError, "unknown layout"):
            cli.resolve_layouts("card,pie")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "no layouts"):
            cli.resolve_layouts(" , ")


class TestSubjectSelection(unittest.TestCase):
    def test_all(self):
        self.assertEqual(cli.resolve_subjects("all"), list(render_pkg.SUBJECT_NAMES))

    def test_default_is_languages(self):
        self.assertEqual(
            cli.resolve_subjects(render_pkg.DEFAULT_SUBJECT), ["language"]
        )

    def test_order_given_does_not_change_the_files_written(self):
        self.assertEqual(
            cli.resolve_subjects("project, language"), ["language", "project"]
        )

    def test_unknown(self):
        with self.assertRaisesRegex(ValueError, "unknown subject"):
            cli.resolve_subjects("files")

    def test_empty(self):
        with self.assertRaisesRegex(ValueError, "no subjects"):
            cli.resolve_subjects(" , ")


class TestWidthOption(unittest.TestCase):
    def test_unset_leaves_each_layout_its_own_default(self):
        self.assertIsNone(cli.resolve_width(None))

    def test_a_usable_width_passes_through(self):
        self.assertEqual(cli.resolve_width(900), 900)

    def test_too_narrow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least"):
            cli.resolve_width(80)


class TestRowsOption(unittest.TestCase):
    def test_unset_leaves_each_layout_its_own_default(self):
        self.assertIsNone(cli.resolve_rows(None))

    def test_a_count_passes_through(self):
        self.assertEqual(cli.resolve_rows(12), 12)

    def test_zero_means_every_row(self):
        self.assertEqual(cli.resolve_rows(0), 0)

    def test_a_negative_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 or more"):
            cli.resolve_rows(-1)


class TestOnlyFilter(unittest.TestCase):
    def setUp(self):
        self.specs = [
            ProjectSpec(name="Advent of Code", path=Path("/code/aoc")),
            ProjectSpec(name="dotfiles", path=Path("/code/dotfiles")),
        ]

    def test_matches_display_name_case_insensitively(self):
        kept, missing = cli.filter_projects(self.specs, ["advent of code"])
        self.assertEqual([s.name for s in kept], ["Advent of Code"])
        self.assertEqual(missing, [])

    def test_matches_directory_name(self):
        kept, _ = cli.filter_projects(self.specs, ["aoc"])
        self.assertEqual([s.name for s in kept], ["Advent of Code"])

    def test_reports_values_that_matched_nothing(self):
        kept, missing = cli.filter_projects(self.specs, ["dotfiles", "nope"])
        self.assertEqual([s.name for s in kept], ["dotfiles"])
        self.assertEqual(missing, ["nope"])

    def test_no_filter_keeps_everything(self):
        kept, missing = cli.filter_projects(self.specs, None)
        self.assertEqual(kept, self.specs)
        self.assertEqual(missing, [])


class TestVisibilityFilter(unittest.TestCase):
    def setUp(self):
        self.specs = [
            ProjectSpec(name="Public One", path=Path("/code/public-one")),
            ProjectSpec(name="Secret", path=Path("/code/secret"), private=True),
        ]

    def test_public_is_the_default(self):
        kept, _ = cli.filter_projects(self.specs, None)
        self.assertEqual([s.name for s in kept], ["Public One"])

    def test_private_keeps_only_private(self):
        kept, _ = cli.filter_projects(self.specs, None, "private")
        self.assertEqual([s.name for s in kept], ["Secret"])

    def test_all_keeps_everything(self):
        kept, _ = cli.filter_projects(self.specs, None, "all")
        self.assertEqual(kept, self.specs)

    def test_only_reaches_a_private_project_without_the_flag(self):
        kept, missing = cli.filter_projects(self.specs, ["secret"], "public")
        self.assertEqual([s.name for s in kept], ["Secret"])
        self.assertEqual(missing, [])


class TestResolveVisibility(unittest.TestCase):
    def resolve(self, *argv):
        return cli.resolve_visibility(cli.build_parser().parse_args(list(argv)))

    def test_default_is_public(self):
        self.assertEqual(self.resolve(), "public")

    def test_mask_alone_means_all(self):
        self.assertEqual(self.resolve("--mask"), "all")
        self.assertEqual(self.resolve("--mask", "STEALTH"), "all")

    def test_mask_each_alone_also_means_all(self):
        self.assertEqual(self.resolve("--mask-each"), "all")

    def test_mask_narrows_to_private_when_asked(self):
        self.assertEqual(self.resolve("--private", "--mask"), "private")

    def test_explicit_switches_still_win(self):
        self.assertEqual(self.resolve("--all"), "all")
        self.assertEqual(self.resolve("--private"), "private")


class TestMaskPrivate(unittest.TestCase):
    def setUp(self):
        self.specs = [
            ProjectSpec(name="Public", path=Path("/code/public")),
            ProjectSpec(name="One", path=Path("/code/one"), private=True),
            ProjectSpec(name="Two", path=Path("/code/two"), private=True),
        ]
        self.reports = [
            ProjectReport("Public", "/code/public", {"Go": LangCount(code=10)}),
            ProjectReport(
                "One", "/code/one", {"Go": LangCount(code=20)}, branch="main"
            ),
            ProjectReport("Two", "/code/two", {"Rust": LangCount(code=30)}),
        ]

    def test_private_projects_become_one_nameless_entry(self):
        masked = cli.mask_private(self.specs, self.reports, "UNDISCLOSED")
        self.assertEqual([r.name for r in masked], ["Public", "UNDISCLOSED"])
        merged = masked[-1]
        self.assertEqual(merged.total.code, 50)
        self.assertIsNone(merged.branch)
        self.assertNotIn("one", str(merged.path))

    def test_mask_each_keeps_one_numbered_row_per_project(self):
        masked = cli.mask_private(
            self.specs, self.reports, "UNDISCLOSED", each=True
        )
        self.assertEqual(
            [r.name for r in masked], ["Public", "UNDISCLOSED-1", "UNDISCLOSED-2"]
        )
        # Largest first: Two has 30 lines, One has 20.
        self.assertEqual([r.total.code for r in masked], [10, 30, 20])
        self.assertTrue(all(r.branch is None for r in masked[1:]))
        self.assertNotIn("one", " ".join(str(r.path) for r in masked[1:]))

    def test_mask_each_still_adds_up_to_the_merged_total(self):
        merged = cli.mask_private(self.specs, self.reports, "X")
        separate = cli.mask_private(self.specs, self.reports, "X", each=True)
        self.assertEqual(
            sum(r.total.code for r in merged), sum(r.total.code for r in separate)
        )

    def test_mask_each_numbers_past_nine_line_up(self):
        specs = [
            ProjectSpec(name=f"P{i}", path=Path(f"/code/p{i}"), private=True)
            for i in range(10)
        ]
        reports = [
            ProjectReport(f"P{i}", f"/code/p{i}", {"Go": LangCount(code=100 - i)})
            for i in range(10)
        ]
        masked = cli.mask_private(specs, reports, "UNDISCLOSED", each=True)
        self.assertEqual(masked[0].name, "UNDISCLOSED-01")
        self.assertEqual(masked[-1].name, "UNDISCLOSED-10")
        # Zero padding is what keeps --sort name in step with --sort code.
        self.assertEqual(
            [r.name for r in masked], sorted(r.name for r in masked)
        )

    def test_mask_each_keeps_failures_apart_and_unnamed(self):
        reports = list(self.reports)
        reports[2] = ProjectReport("Two", "/code/two", error="/code/two not found")
        masked = cli.mask_private(self.specs, reports, "UNDISCLOSED", each=True)
        self.assertEqual(
            [r.name for r in masked], ["Public", "UNDISCLOSED-1", "UNDISCLOSED-2"]
        )
        failure = masked[-1]
        self.assertFalse(failure.ok)
        self.assertNotIn("/code/two", failure.error or "")

    def test_nothing_private_leaves_the_list_alone(self):
        specs = [self.specs[0]]
        self.assertEqual(
            cli.mask_private(specs, [self.reports[0]], "UNDISCLOSED"), [self.reports[0]]
        )

    def test_failures_stay_visible_but_unnamed(self):
        reports = list(self.reports)
        reports[2] = ProjectReport("Two", "/code/two", error="directory not found")
        masked = cli.mask_private(self.specs, reports, "UNDISCLOSED")
        failures = [r for r in masked if not r.ok]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].name, "UNDISCLOSED")
        self.assertIn("1 private project", failures[0].error or "")
        # The one that did count is still counted.
        self.assertEqual([r for r in masked if r.ok][-1].total.code, 20)

    def test_every_private_project_failing_leaves_no_counted_entry(self):
        specs = self.specs[1:]
        reports = [
            ProjectReport("One", "/code/one", error="boom"),
            ProjectReport("Two", "/code/two", error="boom"),
        ]
        masked = cli.mask_private(specs, reports, "UNDISCLOSED")
        self.assertEqual(len(masked), 1)
        self.assertFalse(masked[0].ok)
        self.assertIn("2 private project", masked[0].error or "")


class TestOutputPath(unittest.TestCase):
    def test_report_formats_share_the_basename(self):
        path = cli.output_path(Path("/out"), "report", render_pkg.get("md"))
        self.assertEqual(path, Path("/out/cw-report.md"))

    def test_card_keeps_its_own_stem(self):
        path = cli.output_path(
            Path("/out"), "report", render_pkg.get("svg"), None, "language"
        )
        self.assertEqual(path, Path("/out/cw-card-languages.svg"))

    def test_a_layout_names_its_own_file(self):
        path = cli.output_path(Path("/out"), "report", render_pkg.get("svg"), "strip")
        self.assertEqual(path, Path("/out/cw-strip.svg"))

    def test_the_project_subject_suffixes_the_stem(self):
        path = cli.output_path(
            Path("/out"), "report", render_pkg.get("svg"), "strip", "project"
        )
        self.assertEqual(path, Path("/out/cw-strip-projects.svg"))

    def test_the_language_subject_suffixes_the_stem_too(self):
        """Neither subject is the unmarked one, so both are in the filename."""
        path = cli.output_path(
            Path("/out"), "report", render_pkg.get("svg"), "strip", "language"
        )
        self.assertEqual(path, Path("/out/cw-strip-languages.svg"))

    def test_every_subject_has_a_suffix(self):
        """A new subject that nobody named here would silently collide with
        whichever one it was added beside."""
        self.assertEqual(
            sorted(cli.SUBJECT_SUFFIX), sorted(render_pkg.SUBJECT_NAMES)
        )

    def test_the_prefix_survives_a_custom_basename(self):
        path = cli.output_path(Path("/out"), "all", render_pkg.get("txt"))
        self.assertEqual(path, Path("/out/cw-all.txt"))


class TestDefaultPaths(unittest.TestCase):
    """Where --config and --out point when neither is typed.

    PACKAGE_ROOT is the repository in a checkout and site-packages in an
    installed clocwork. Anchored to it alone, the defaults sent a Homebrew or
    pip install looking for a project list it can never have, and wrote the
    report inside the install prefix.
    """

    def setUp(self):
        # Resolved, because default_config_path() reads Path.cwd(), which on
        # macOS returns /private/var where the temp directory says /var.
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (self.tmp / "alpha").mkdir()
        self.config = self.tmp / "projects.toml"
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n[[project]]\nrepo = "alpha"\n'
        )

    def run_main(self, *argv):
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with mock.patch.object(collect.subprocess, "run", return_value=completed), \
             mock.patch.object(collect.shutil, "which", return_value="/bin/cloc"), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cli.main(["--quiet", "--format", "txt", *argv])

    def test_a_project_list_here_is_the_default_config(self):
        self.enterContext(chdir(self.tmp))
        self.assertEqual(cli.default_config_path(), self.config)

    def test_without_one_the_default_sits_beside_the_tool(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(chdir(empty))
        self.assertEqual(
            cli.default_config_path(),
            cli.PACKAGE_ROOT / "projects.toml",
        )

    def test_a_directory_named_projects_toml_is_not_a_config(self):
        empty = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        (empty / "projects.toml").mkdir()
        self.enterContext(chdir(empty))
        self.assertEqual(
            cli.default_config_path(),
            cli.PACKAGE_ROOT / "projects.toml",
        )

    def test_the_report_lands_beside_the_config(self):
        self.assertEqual(self.run_main("--config", str(self.config)), 0)
        self.assertTrue((self.tmp / "out" / "cw-report.txt").is_file())

    def test_running_here_needs_no_flags_at_all(self):
        # An installed clocwork, in a directory holding a project list,
        # writes its report there.
        self.enterContext(chdir(self.tmp))
        self.assertEqual(self.run_main(), 0)
        self.assertTrue((self.tmp / "out" / "cw-report.txt").is_file())

    def test_a_typed_out_wins(self):
        elsewhere = self.tmp / "somewhere"
        self.run_main("--config", str(self.config), "--out", str(elsewhere))
        self.assertTrue((elsewhere / "cw-report.txt").is_file())
        self.assertFalse((self.tmp / "out").exists())

    def test_a_cli_table_out_wins(self):
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n'
            '[cli]\nout = "configured"\n\n'
            '[[project]]\nrepo = "alpha"\n'
        )
        self.run_main("--config", str(self.config))
        self.assertTrue((self.tmp / "configured" / "cw-report.txt").is_file())
        self.assertFalse((self.tmp / "out").exists())


class TestMain(unittest.TestCase):
    """End-to-end through main(), with cloc mocked out."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.project = self.tmp / "alpha"
        self.project.mkdir()
        self.config = self.tmp / "projects.toml"
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n[[project]]\nrepo = "alpha"\n'
        )
        self.out = self.tmp / "out"

    def run_main(self, *argv, stdout=SAMPLE, returncode=0):
        completed = subprocess.CompletedProcess(["cloc"], returncode, stdout, "")
        with mock.patch.object(collect.subprocess, "run", return_value=completed), \
             mock.patch.object(collect.shutil, "which", return_value="/bin/cloc"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(
                    ["--config", str(self.config), "--out", str(self.out), *argv]
                )
        return code, out.getvalue(), err.getvalue()

    def totals(self, text: str) -> str:
        """The 'Projects: N  Files: N  Code: N' line, minus the project count."""
        line = next(ln for ln in text.splitlines() if ln.startswith("Projects:"))
        return line.split("Files:", 1)[1]

    def test_writes_every_format(self):
        code, _, _ = self.run_main("--quiet")
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            [
                "cw-card-languages.svg",
                "cw-report.html",
                "cw-report.md",
                "cw-report.txt",
            ],
        )

    def test_format_subset(self):
        self.run_main("--quiet", "--format", "md")
        self.assertEqual([p.name for p in self.out.iterdir()], ["cw-report.md"])

    def test_stdout_writes_nothing_to_disk(self):
        code, out, _ = self.run_main("--stdout", "md")
        self.assertEqual(code, 0)
        self.assertFalse(self.out.exists())
        self.assertIn("# Lines of code", out)

    def test_progress_stays_off_stdout_so_output_can_be_piped(self):
        _, out, err = self.run_main("--stdout", "md")
        self.assertIn("counting alpha", err)
        self.assertNotIn("counting alpha", out)

    def test_failed_project_exits_one_but_still_reports(self):
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n'
            '[[project]]\nrepo = "alpha"\n\n[[project]]\nrepo = "ghost"\n'
        )
        code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 1)
        self.assertIn("skipped ghost", err)
        self.assertIn("ghost", (self.out / "cw-report.txt").read_text())

    def test_total_failure_exits_two(self):
        code, _, _ = self.run_main("--quiet", returncode=1, stdout="")
        self.assertEqual(code, 2)

    def test_bad_config_exits_two(self):
        self.config.write_text("[defaults]\n")
        code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 2)
        self.assertIn("no [[project]]", err)

    def test_only_matching_nothing_exits_two(self):
        code, _, err = self.run_main("--quiet", "--only", "nope")
        self.assertEqual(code, 2)
        self.assertIn("nothing to count", err)

    def write_public_and_private(self):
        (self.tmp / "beta").mkdir()
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n'
            '[[project]]\nrepo = "alpha"\n\n'
            '[[project]]\nrepo = "beta"\nprivate = true\n'
        )

    def test_private_projects_are_left_out_by_default(self):
        self.write_public_and_private()
        code, out, _ = self.run_main("--quiet", "--stdout", "txt")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertNotIn("beta", out)

    def test_private_counts_only_private_projects(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--private", "--stdout", "txt")
        self.assertIn("beta", out)
        self.assertNotIn("alpha", out)

    def test_all_counts_both(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--all", "--stdout", "txt")
        self.assertIn("alpha", out)
        self.assertIn("beta", out)

    def test_only_reaches_a_private_project(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--only", "beta", "--stdout", "txt")
        self.assertIn("beta", out)
        self.assertNotIn("alpha", out)

    def test_all_public_hidden_suggests_the_flags(self):
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\nprivate = true\n\n'
            '[[project]]\nrepo = "alpha"\n'
        )
        code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 2)
        self.assertIn("no public projects", err)

    def test_mask_counts_private_code_without_naming_it(self):
        self.write_public_and_private()
        _, masked, _ = self.run_main("--quiet", "--mask", "--stdout", "txt")
        _, shown, _ = self.run_main("--quiet", "--all", "--stdout", "txt")
        self.assertIn("UNDISCLOSED", masked)
        self.assertNotIn("beta", masked)
        self.assertIn("alpha", masked)
        # Only the name went away. The totals must survive the merge.
        self.assertEqual(self.totals(masked), self.totals(shown))

    def test_mask_hides_a_private_projects_url_too(self):
        (self.tmp / "beta").mkdir()
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n'
            '[[project]]\nrepo = "alpha"\n\n'
            '[[project]]\nrepo = "beta"\nprivate = true\n'
            'url = "https://example.com/beta"\n'
        )
        for flag in ("--mask", "--mask-each"):
            with self.subTest(flag=flag):
                _, out, _ = self.run_main("--quiet", flag, "--stdout", "md")
                self.assertIn("UNDISCLOSED", out)
                self.assertNotIn("example.com", out)

    def test_a_url_makes_the_project_name_a_link(self):
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n'
            '[[project]]\nrepo = "alpha"\nurl = "https://example.com/alpha"\n'
        )
        _, out, _ = self.run_main("--quiet", "--stdout", "md")
        self.assertIn("[alpha](https://example.com/alpha)", out)

    def test_mask_hides_the_name_in_the_detail_breakdown_too(self):
        self.write_public_and_private()
        for flag in ("--mask", "--mask-each"):
            with self.subTest(flag=flag):
                _, out, _ = self.run_main(
                    "--quiet", flag, "--detail", "--stdout", "txt"
                )
                self.assertNotIn("beta", out)

    def test_mask_each_gives_every_private_project_its_own_row(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--mask-each", "--stdout", "txt")
        _, shown, _ = self.run_main("--quiet", "--all", "--stdout", "txt")
        self.assertIn("UNDISCLOSED-1", out)
        self.assertNotIn("beta", out)
        self.assertIn("alpha", out)
        self.assertEqual(self.totals(out), self.totals(shown))

    def test_mask_each_and_mask_agree_on_the_grand_total(self):
        self.write_public_and_private()
        _, merged, _ = self.run_main("--quiet", "--mask", "--stdout", "txt")
        _, separate, _ = self.run_main("--quiet", "--mask-each", "--stdout", "txt")
        self.assertEqual(self.totals(merged), self.totals(separate))

    def test_mask_each_takes_the_label_from_mask(self):
        self.write_public_and_private()
        _, out, _ = self.run_main(
            "--quiet", "--mask", "STEALTH", "--mask-each", "--stdout", "txt"
        )
        self.assertIn("STEALTH-1", out)
        self.assertNotIn("UNDISCLOSED", out)

    def test_mask_takes_a_literal(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--mask", "STEALTH", "--stdout", "txt")
        self.assertIn("STEALTH", out)
        self.assertNotIn("UNDISCLOSED", out)

    def test_mask_label_from_the_config_is_used_and_overridable(self):
        (self.tmp / "beta").mkdir()
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\nmask_label = "HUSH"\n\n'
            '[[project]]\nrepo = "alpha"\n\n'
            '[[project]]\nrepo = "beta"\nprivate = true\n'
        )
        _, out, _ = self.run_main("--quiet", "--mask", "--stdout", "txt")
        self.assertIn("HUSH", out)
        _, out, _ = self.run_main("--quiet", "--mask", "LOUD", "--stdout", "txt")
        self.assertIn("LOUD", out)
        self.assertNotIn("HUSH", out)

    def test_mask_with_private_counts_only_the_masked_ones(self):
        self.write_public_and_private()
        _, out, _ = self.run_main("--quiet", "--private", "--mask", "--stdout", "txt")
        self.assertIn("UNDISCLOSED", out)
        self.assertNotIn("alpha", out)
        self.assertNotIn("beta", out)

    def test_private_and_all_together_are_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            cli.main(["--config", str(self.config), "--private", "--all"])
        self.assertEqual(raised.exception.code, 2)

    def test_missing_cloc_exits_two(self):
        with mock.patch.object(collect.shutil, "which", return_value=None):
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                code = cli.main(["--config", str(self.config)])
        self.assertEqual(code, 2)
        self.assertIn("brew install cloc", err.getvalue())

    def test_sections_picks_one_summary_table(self):
        code, out, _ = self.run_main(
            "--quiet", "--sections", "language", "--stdout", "txt"
        )
        self.assertEqual(code, 0)
        self.assertIn("By language", out)
        self.assertNotIn("By project", out)

    def test_an_unknown_section_exits_two(self):
        code, _, err = self.run_main("--quiet", "--sections", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("unknown section(s): bogus", err)
        self.assertFalse(self.out.exists())

    def test_dropping_a_section_leaves_the_totals_alone(self):
        _, full, _ = self.run_main("--quiet", "--stdout", "txt")
        _, partial, _ = self.run_main(
            "--quiet", "--sections", "project", "--stdout", "txt"
        )
        self.assertEqual(self.totals(full), self.totals(partial))

    def test_reruns_are_identical_apart_from_the_timestamp(self):
        for layout in render_pkg.LAYOUT_NAMES:
            with self.subTest(layout=layout):
                self.run_main("--quiet", "--format", "svg", "--layout", layout)
                first = (self.out / f"cw-{layout}-languages.svg").read_text()
                self.run_main("--quiet", "--format", "svg", "--layout", layout)
                second = (self.out / f"cw-{layout}-languages.svg").read_text()
                self.assertEqual(first, second)

    def test_date_none_makes_every_format_reproducible(self):
        # The stamp is the only thing a rerun over unchanged code changes by
        # itself, cloc's own timings having been dropped by --hide-rate. With
        # no stamp the whole output directory is a function of the counts, so
        # a scheduled run only commits when the code moved.
        second = self.tmp / "again"
        common = ("--quiet", "--format", "all", "--layout", "all", "--by", "all")
        self.run_main(*common, "--date", "none")
        self.run_main(*common, "--date", "none", "--out", str(second))
        written = sorted(p.name for p in self.out.iterdir())
        self.assertEqual(written, sorted(p.name for p in second.iterdir()))
        for name in written:
            with self.subTest(file=name):
                self.assertEqual(
                    (self.out / name).read_bytes(),
                    (second / name).read_bytes(),
                )

    def test_the_precision_reaches_the_report(self):
        for precision, pattern in (
            ("minute", r"Generated: \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC by"),
            ("day", r"Generated: \d{4}-\d{2}-\d{2} by"),
            ("month", r"Generated: \d{4}-\d{2} by"),
            ("none", r"Generated by clocwork"),
        ):
            with self.subTest(precision=precision):
                _, out, _ = self.run_main(
                    "--quiet", "--stdout", "txt", "--date", precision
                )
                self.assertRegex(out, pattern)

    def test_every_layout_writes_its_own_file(self):
        code, _, _ = self.run_main("--quiet", "--format", "svg", "--layout", "all")
        self.assertEqual(code, 0)
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            sorted(f"cw-{name}-languages.svg" for name in render_pkg.LAYOUT_NAMES),
        )

    def test_two_layouts_live_side_by_side(self):
        self.run_main("--quiet", "--format", "svg", "--layout", "card,strip")
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            ["cw-card-languages.svg", "cw-strip-languages.svg"],
        )

    def test_both_subjects_live_side_by_side(self):
        self.run_main("--quiet", "--format", "svg", "--layout", "card", "--by", "all")
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            ["cw-card-languages.svg", "cw-card-projects.svg"],
        )

    def test_only_the_project_subject_names_the_projects(self):
        self.run_main("--quiet", "--format", "svg", "--layout", "bars", "--by", "all")
        self.assertIn("alpha", (self.out / "cw-bars-projects.svg").read_text())
        self.assertNotIn("alpha", (self.out / "cw-bars-languages.svg").read_text())

    def test_an_unknown_subject_exits_two(self):
        code, _, err = self.run_main("--quiet", "--by", "files")
        self.assertEqual(code, 2)
        self.assertIn("unknown subject(s): files", err)
        self.assertFalse(self.out.exists())

    def test_the_subject_reaches_stdout_too(self):
        _, out, _ = self.run_main("--quiet", "--stdout", "svg", "--layout", "bars",
                                  "--by", "project")
        self.assertIn("alpha", out)

    def test_an_unknown_layout_exits_two(self):
        code, _, err = self.run_main("--quiet", "--layout", "bogus")
        self.assertEqual(code, 2)
        self.assertIn("unknown layout(s): bogus", err)
        self.assertFalse(self.out.exists())

    def test_the_layout_reaches_stdout_too(self):
        _, out, _ = self.run_main("--quiet", "--stdout", "svg", "--layout", "strip")
        self.assertIn(f'width="{strip_layout.WIDTH}"', out)
        self.assertFalse(self.out.exists())

    def test_svg_width_reaches_every_layout(self):
        self.run_main("--quiet", "--format", "svg", "--layout", "all",
                      "--svg-width", "900")
        for name in render_pkg.LAYOUT_NAMES:
            with self.subTest(layout=name):
                self.assertIn(
                    'width="900"',
                    (self.out / f"cw-{name}-languages.svg").read_text(),
                )

    def test_too_narrow_an_svg_width_exits_two(self):
        code, _, err = self.run_main("--quiet", "--svg-width", "10")
        self.assertEqual(code, 2)
        self.assertIn("--svg-width must be at least", err)
        self.assertFalse(self.out.exists())

    def test_svg_rows_caps_the_labelled_rows(self):
        # The fixture counts three languages, so a cap of two drops the last.
        self.run_main("--quiet", "--format", "svg", "--svg-rows", "2")
        self.assertNotIn(
            "Markdown", (self.out / "cw-card-languages.svg").read_text()
        )
        self.run_main("--quiet", "--format", "svg")
        self.assertIn("Markdown", (self.out / "cw-card-languages.svg").read_text())

    def test_svg_rows_reaches_stdout_too(self):
        _, out, _ = self.run_main("--quiet", "--stdout", "svg", "--svg-rows", "1")
        self.assertIn("Go", out)
        self.assertNotIn("JSON", out)

    def test_zero_svg_rows_labels_everything(self):
        _, out, _ = self.run_main("--quiet", "--stdout", "svg", "--svg-rows", "0")
        for language in ("Go", "JSON", "Markdown"):
            self.assertIn(language, out)

    def test_a_negative_svg_rows_exits_two(self):
        code, _, err = self.run_main("--quiet", "--svg-rows", "-1")
        self.assertEqual(code, 2)
        self.assertIn("--svg-rows must be 0 or more", err)
        self.assertFalse(self.out.exists())

    def test_svg_headings_reach_the_banner(self):
        self.run_main("--quiet", "--format", "svg", "--layout", "banner",
                      "--svg-title", "Everything", "--svg-subtitle", "so far")
        drawn = (self.out / "cw-banner-languages.svg").read_text()
        self.assertIn("Everything", drawn)
        self.assertIn("so far", drawn)

    def test_svg_headings_leave_the_other_layouts_alone(self):
        # They take the argument so the CLI can hand every layout the same
        # keywords. Only the banner has anywhere to draw it.
        self.run_main("--quiet", "--format", "svg", "--layout", "card,donut",
                      "--svg-title", "Everything")
        for layout in ("card", "donut"):
            with self.subTest(layout=layout):
                self.assertNotIn(
                    "Everything",
                    (self.out / f"cw-{layout}-languages.svg").read_text(),
                )

    def test_svg_headings_reach_stdout_too(self):
        _, out, _ = self.run_main("--quiet", "--stdout", "svg", "--layout",
                                  "banner", "--svg-title", "Everything")
        self.assertIn("Everything", out)
        self.assertFalse(self.out.exists())


class TestRemoteProjects(unittest.TestCase):
    """Remote projects through main(), with git and cloc both mocked out."""

    REPO = "https://example.com/acme/hello-world.git"

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cache = self.tmp / "cache"
        self.config = self.tmp / "projects.toml"
        self.config.write_text(f'[[project]]\nrepo = "{self.REPO}"\n')
        self.out = self.tmp / "out"

    def run_main(self, *argv):
        """cloc is mocked; each test patches collect.sync for itself."""
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with (
            mock.patch.object(collect.subprocess, "run", return_value=completed),
            mock.patch.object(collect.shutil, "which", return_value="/bin/cloc"),
        ):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(
                    [
                        "--config", str(self.config),
                        "--out", str(self.out),
                        "--cache", str(self.cache),
                        *argv,
                    ]
                )
        return code, out.getvalue(), err.getvalue()

    def test_the_cache_flag_decides_where_the_clone_goes(self):
        seen = []
        with mock.patch.object(
            collect, "sync", side_effect=lambda spec, **kw: seen.append(spec) or None
        ):
            self.run_main("--quiet")
        self.assertEqual(seen[0].path.parent, self.cache)
        self.assertEqual(seen[0].repo, self.REPO)

    def test_a_clone_that_fails_is_a_skipped_row_not_a_dead_run(self):
        with mock.patch.object(
            collect, "sync", return_value="fatal: repository not found"
        ):
            code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 2)  # it was the only project, so nothing counted
        self.assertIn("fatal: repository not found", err)

    def test_no_fetch_reaches_the_sync(self):
        with mock.patch.object(collect, "sync", return_value=None) as sync:
            self.run_main("--quiet", "--no-fetch")
        self.assertIs(sync.call_args.kwargs["fetch"], False)

    def test_fetch_is_on_by_default(self):
        with mock.patch.object(collect, "sync", return_value=None) as sync:
            self.run_main("--quiet")
        self.assertIs(sync.call_args.kwargs["fetch"], True)

    def test_the_config_can_turn_fetching_off(self):
        self.config.write_text(
            f'[cli]\nfetch = false\n\n[[project]]\nrepo = "{self.REPO}"\n'
        )
        with mock.patch.object(collect, "sync", return_value=None) as sync:
            self.run_main("--quiet")
        self.assertIs(sync.call_args.kwargs["fetch"], False)

    def test_the_flag_turns_it_back_on_for_one_run(self):
        self.config.write_text(
            f'[cli]\nfetch = false\n\n[[project]]\nrepo = "{self.REPO}"\n'
        )
        with mock.patch.object(collect, "sync", return_value=None) as sync:
            self.run_main("--quiet", "--fetch")
        self.assertIs(sync.call_args.kwargs["fetch"], True)

    def test_progress_says_syncing_for_a_remote_project(self):
        with mock.patch.object(collect, "sync", return_value=None):
            _, _, err = self.run_main("--stdout", "txt")
        self.assertIn("syncing hello-world", err)
        self.assertNotIn("counting hello-world", err)


class TestConfigCliTable(unittest.TestCase):
    """[cli] supplies defaults through main(); anything typed still wins."""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.tmp / "alpha").mkdir()
        (self.tmp / "hush").mkdir()
        self.config = self.tmp / "projects.toml"
        self.out = self.tmp / "out"
        self.write()

    def write(self, cli_body: str = "", private: bool = False):
        extra = '\n[[project]]\nrepo = "hush"\nprivate = true\n' if private else ""
        self.config.write_text(
            f'[defaults]\nroot = "{self.tmp}"\n\n{cli_body}\n'
            f'[[project]]\nrepo = "alpha"\n{extra}'
        )

    def run_main(self, *argv, use_config_cli=True):
        completed = subprocess.CompletedProcess(["cloc"], 0, SAMPLE, "")
        with mock.patch.object(collect.subprocess, "run", return_value=completed), \
             mock.patch.object(collect.shutil, "which", return_value="/bin/cloc"):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(
                    ["--config", str(self.config), "--out", str(self.out), *argv],
                    use_config_cli=use_config_cli,
                )
        return code, out.getvalue(), err.getvalue()

    def written(self) -> list[str]:
        return sorted(p.name for p in self.out.iterdir())

    def test_a_value_applies_when_the_flag_is_absent(self):
        self.write('[cli]\nformat = "md"\n')
        self.run_main("--quiet")
        self.assertEqual(self.written(), ["cw-report.md"])

    def test_a_typed_flag_beats_the_config(self):
        self.write('[cli]\nformat = "md"\n')
        self.run_main("--quiet", "--format", "txt")
        self.assertEqual(self.written(), ["cw-report.txt"])

    def test_svg_rows_and_layout_reach_the_svg(self):
        self.write('[cli]\nformat = "svg"\nlayout = "all"\nby = "all"\n')
        self.run_main("--quiet")
        self.assertEqual(
            len(self.written()),
            len(render_pkg.LAYOUT_NAMES) * len(render_pkg.SUBJECT_NAMES),
        )

    def test_svg_headings_can_be_configured(self):
        self.write(
            '[cli]\nformat = "svg"\nlayout = "banner"\n'
            'svg_title = "Everything"\nsvg_subtitle = "so far"\n'
        )
        self.run_main("--quiet")
        drawn = (self.out / "cw-banner-languages.svg").read_text()
        self.assertIn("Everything", drawn)
        self.assertIn("so far", drawn)
        # Typed still wins over configured.
        self.run_main("--quiet", "--svg-title", "Only this")
        drawn = (self.out / "cw-banner-languages.svg").read_text()
        self.assertIn("Only this", drawn)
        self.assertNotIn("Everything", drawn)

    def test_a_configured_date_reaches_the_stamp(self):
        # The key a scheduled run sets once and forgets.
        self.write('[cli]\nformat = "txt"\ndate = "none"\n')
        self.run_main("--quiet")
        self.assertIn(
            "Generated by clocwork", (self.out / "cw-report.txt").read_text()
        )
        self.run_main("--quiet", "--date", "day")
        self.assertRegex(
            (self.out / "cw-report.txt").read_text(), r"Generated: \d{4}-\d{2}-\d{2}"
        )

    def test_a_configured_date_that_is_not_a_precision_is_an_error(self):
        # argparse checks `choices` for a typed flag but not for a default, so
        # the [cli] value is caught where the stamp is built.
        self.write('[cli]\ndate = "monthly"\n')
        code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 2)
        self.assertIn("monthly", err)
        self.assertIn("month", err)

    def test_no_detail_turns_off_a_configured_detail(self):
        self.write('[cli]\nformat = "md"\ndetail = true\n')
        self.run_main("--quiet")
        self.assertIn("<details>", (self.out / "cw-report.md").read_text())
        self.run_main("--quiet", "--no-detail")
        self.assertNotIn("<details>", (self.out / "cw-report.md").read_text())

    def test_no_quiet_turns_off_a_configured_quiet(self):
        self.write("[cli]\nquiet = true\n")
        _, _, err = self.run_main()
        self.assertNotIn("counting alpha", err)
        _, _, err = self.run_main("--no-quiet")
        self.assertIn("counting alpha", err)

    def test_the_table_cannot_make_a_bare_run_disclose(self):
        # The guarantee the exclusion exists for. A [cli] table is settings,
        # never permission. Private projects stay out until --mask, --all or
        # --private says otherwise on the line you type.
        self.write('[cli]\nformat = "txt"\nlayout = "all"\n', private=True)
        self.run_main("--quiet")
        report = (self.out / "cw-report.txt").read_text()
        self.assertIn("alpha", report)
        self.assertNotIn("hush", report)

    def test_a_refused_key_exits_two(self):
        self.write("[cli]\nmask = true\n", private=True)
        code, _, err = self.run_main("--quiet")
        self.assertEqual(code, 2)
        self.assertIn("not settable here", err)
        self.assertFalse(self.out.exists())

    def test_use_config_cli_false_ignores_the_table(self):
        # scripts/gallery commits its output, so it runs this way. The reader's
        # preferences must not decide what lands in docs/gallery.
        self.write('[cli]\nformat = "md"\n')
        self.run_main("--quiet", use_config_cli=False)
        self.assertEqual(len(self.written()), 4)


if __name__ == "__main__":
    unittest.main()
