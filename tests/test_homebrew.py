# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tap formula is generated, so the generator is what gets tested.

scripts/render-homebrew-formula is run as a command rather than imported. It
has no .py extension, like every other script in that directory, and it should
not grow one only so a test can reach it. Running it is also what CI does.
"""

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "scripts" / "render-homebrew-formula"
SHA256 = "a" * 64
VERSION = "0.9.0"


def render(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDERER), *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def formula(version: str = VERSION, sha256: str = SHA256) -> str:
    done = render(version, sha256)
    assert done.returncode == 0, done.stderr
    return done.stdout


class TestVersions(unittest.TestCase):
    def test_a_git_tag_and_a_bare_version_mean_the_same_thing(self):
        for given in ("0.9.0", "v0.9.0", "v10.20.30", "v0.0.0"):
            with self.subTest(version=given):
                self.assertEqual(render(given, SHA256).returncode, 0)

    def test_a_pre_release_never_reaches_the_tap(self):
        # brew install resolves to whatever the tap holds, and a candidate for
        # a version must not be published under the name of that version.
        for given in ("0.9.0-rc.1", "v0.9.0-rc.1", "0.9.0-beta", "0.9.0+1"):
            with self.subTest(version=given):
                done = render(given, SHA256)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not a stable release version", done.stderr)

    def test_anything_that_is_not_three_numbers_is_refused(self):
        for given in ("0.9", "0.9.0.1", "v", "latest", "", "0.9.x", "00.9.0"):
            with self.subTest(version=given):
                self.assertEqual(render(given, SHA256).returncode, 2)


class TestChecksums(unittest.TestCase):
    def test_only_a_64_character_lowercase_digest_is_one(self):
        for given in (
            "a" * 63,
            "a" * 65,
            "A" * 64,
            f"sha256:{'a' * 64}",
            "g" * 64,
            "",
        ):
            with self.subTest(sha256=given):
                done = render(VERSION, given)
                self.assertEqual(done.returncode, 2)
                self.assertIn("not a 64-character", done.stderr)


class TestFormula(unittest.TestCase):
    def test_it_pins_the_release_it_was_handed(self):
        text = formula("v1.2.3", "b" * 64)
        self.assertRegex(text, r"(?m)^class Clocwork < Formula$")
        self.assertRegex(
            text,
            r'(?m)^  url "https://github\.com/wojciechpolak/clocwork/releases/'
            r'download/v1\.2\.3/clocwork-1\.2\.3-py3-none-any\.whl", '
            r"using: :nounzip$",
        )
        self.assertRegex(text, rf'(?m)^  sha256 "{"b" * 64}"$')
        self.assertRegex(text, r'(?m)^  license "GPL-3\.0-or-later"$')

    def test_the_version_appears_nowhere_it_could_go_stale(self):
        # Homebrew reads the version out of the url. Every other mention comes
        # from the wheel's own filename, so there is one number in the file.
        self.assertEqual(formula("1.2.3").count("1.2.3"), 2)

    def test_it_installs_the_wheel_rather_than_building_the_sdist(self):
        text = formula()
        self.assertIn("using: :nounzip", text)
        self.assertIn('venv.pip_install_and_link buildpath/"clocwork-', text)
        # A resource block would mean a build backend, which would mean pip
        # reaching PyPI during brew install.
        self.assertNotIn("resource ", text)

    def test_cloc_and_git_are_runtime_dependencies(self):
        text = formula()
        for name in ("cloc", "git"):
            self.assertRegex(text, rf'(?m)^  depends_on "{name}"$')
        self.assertNotIn("=> :build", text)

    def test_the_python_it_depends_on_is_the_one_the_venv_uses(self):
        text = formula()
        wanted = re.findall(r'(?m)^  depends_on "(python@[\d.]+)"$', text)
        self.assertEqual(len(wanted), 1, text)
        venv_python = wanted[0].replace("@", "")
        self.assertIn(f'virtualenv_create(libexec, "{venv_python}")', text)

    def test_the_test_block_counts_something_real(self):
        # A virtualenv that installed but cannot import still prints a version
        # perfectly well, so --version alone proves nothing.
        text = formula()
        self.assertIn("--stdout txt", text)
        self.assertIn('assert_match "Python", output', text)


class TestDescription(unittest.TestCase):
    """What brew audit wants of a description, checked without running it."""

    def setUp(self):
        found = re.findall(r'(?m)^  desc "([^"]+)"$', formula())
        self.assertEqual(len(found), 1)
        self.desc = found[0]

    def test_it_starts_with_a_capital(self):
        self.assertTrue(self.desc[:1].isupper(), self.desc)

    def test_it_does_not_end_in_a_full_stop(self):
        self.assertFalse(self.desc.endswith("."), self.desc)

    def test_it_is_not_the_formula_name_again(self):
        self.assertFalse(self.desc.lower().startswith("clocwork"), self.desc)

    def test_it_fits_the_length_homebrew_allows(self):
        self.assertLess(len(self.desc), 80, self.desc)


class TestFileModes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.target = self.tmp / "Formula" / "clocwork.rb"

    def test_out_writes_the_formula_and_makes_the_directory(self):
        done = render(VERSION, SHA256, "--out", str(self.target))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.target.read_text(), formula())

    def test_check_passes_against_what_out_wrote(self):
        render(VERSION, SHA256, "--out", str(self.target))
        self.assertEqual(
            render(VERSION, SHA256, "--check", str(self.target)).returncode, 0
        )

    def test_check_fails_on_a_changed_or_missing_file(self):
        self.assertEqual(
            render(VERSION, SHA256, "--check", str(self.target)).returncode, 1
        )
        render(VERSION, SHA256, "--out", str(self.target))
        self.target.write_text(self.target.read_text() + "\n# edited in the tap\n")
        self.assertEqual(
            render(VERSION, SHA256, "--check", str(self.target)).returncode, 1
        )

    def test_out_and_check_cannot_both_be_given(self):
        done = render(VERSION, SHA256, "--out", "a", "--check", "b")
        self.assertEqual(done.returncode, 2)

    def test_two_runs_over_one_release_write_the_same_bytes(self):
        self.assertEqual(formula(), formula())


if __name__ == "__main__":
    unittest.main()
