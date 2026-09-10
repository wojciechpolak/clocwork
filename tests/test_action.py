# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""action.yml stays in step with the command it wraps.

The file is read as text rather than parsed. A YAML library would be the first
third-party import in this suite, and the suite has to run under a bare
`python -m unittest` with nothing installed. tests/test_homebrew.py takes the
same line with the formula: the artefact is not importable, so scan it.

Two conventions inside the file are what make a scan enough. Every flag reaches
the command through `argv+=`, so those lines are the complete list of what the
action can pass; and no `${{ }}` appears in a `run:` body, so nothing a caller
writes is ever pasted into the script.
"""

import re
import unittest
from pathlib import Path

from clocwork import cli
from tests.helpers import FIXTURES  # noqa: F401  (sets sys.path)

ROOT = Path(__file__).resolve().parent.parent
TEXT = (ROOT / "action.yml").read_text()

# Inputs the CLI has no flag for, because they are the action's own plumbing
# or because one input becomes several arguments.
PLUMBING = {"repos", "config", "args", "install-cloc", "fail-on-skipped"}

# GitHub takes these eight and nothing else.
BRANDING_COLORS = (
    "white",
    "yellow",
    "blue",
    "green",
    "orange",
    "red",
    "purple",
    "gray-dark",
)


def block(name: str) -> str:
    """The lines under one top-level key, up to the next one."""
    keeping, out = False, []
    for line in TEXT.splitlines():
        if re.match(r"^[a-z]", line):
            keeping = line.startswith(f"{name}:")
            continue
        if keeping:
            out.append(line)
    return "\n".join(out)


RUNS = block("runs")
INPUTS = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", block("inputs"))
OUTPUTS = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", block("outputs"))
# Both the initial `argv=(...)` and every `argv+=(...)` after it.
ARGV = re.findall(r"argv\+?=\(([^)]*)\)", RUNS)
BODIES = re.findall(r"(?ms)^      run: \|\n(.*?)(?=\n {4}- name:|\Z)", RUNS)


def flags(fragment: str) -> list[str]:
    return re.findall(r"--[a-z][a-z0-9-]*", fragment)


class TestArguments(unittest.TestCase):
    """Nothing is passed that the command would not recognise."""

    def setUp(self):
        self.options = {
            option
            for action in cli.build_parser()._actions
            for option in action.option_strings
        }

    def test_the_file_is_there_and_declares_inputs(self):
        self.assertTrue(INPUTS, "no inputs found; the scan is reading nothing")
        self.assertTrue(ARGV, "no argv+= lines found; the scan is reading nothing")

    def test_every_flag_the_action_passes_exists(self):
        for fragment in ARGV:
            for flag in flags(fragment):
                with self.subTest(flag=flag):
                    self.assertIn(flag, self.options)

    def test_every_input_that_is_a_flag_is_spelled_like_it(self):
        # The assertion that catches a renamed CLI flag: an input whose name no
        # longer matches a flag is one that quietly reaches nothing.
        for name in INPUTS:
            if name in PLUMBING:
                continue
            with self.subTest(input=name):
                self.assertIn(f"--{name}", self.options)

    def test_the_two_that_are_not_named_alike(self):
        self.assertIn("--repo", self.options)
        self.assertIn("--config", self.options)
        self.assertIn("--repo", flags(" ".join(ARGV)))
        self.assertIn("--config", flags(" ".join(ARGV)))

    def test_visibility_never_reaches_the_command(self):
        # --all, --private, --mask and --mask-each decide what leaves the
        # machine, and that decision belongs on the line the caller wrote. It
        # goes through `args`, typed, or not at all. Reversing this means
        # changing CLAUDE.md and this test together.
        passed = flags(" ".join(ARGV))
        for flag in ("--all", "--private", "--mask", "--mask-each"):
            with self.subTest(flag=flag):
                self.assertNotIn(flag, passed)

    def test_the_command_is_the_wrapper_and_the_wrapper_is_there(self):
        self.assertIn('"$GITHUB_ACTION_PATH/bin/clocwork"', RUNS)
        self.assertTrue((ROOT / "bin" / "clocwork").is_file())


class TestInputsAndOutputs(unittest.TestCase):
    """Every input is declared, described and used."""

    def test_every_declared_input_is_used(self):
        for name in INPUTS:
            with self.subTest(input=name):
                self.assertIn(f"inputs.{name}", RUNS)

    def test_every_used_input_is_declared(self):
        for name in set(re.findall(r"inputs\.([a-z0-9-]+)", RUNS)):
            with self.subTest(input=name):
                self.assertIn(name, INPUTS)

    def test_every_input_is_described(self):
        declared = block("inputs")
        for name in INPUTS:
            with self.subTest(input=name):
                one = re.search(
                    rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z]|\Z)", declared
                )
                self.assertIsNotNone(one)
                assert one is not None  # for the type checker
                self.assertIn("description:", one.group(1))

    def test_every_output_names_a_step(self):
        self.assertEqual(sorted(OUTPUTS), ["files", "out-dir", "skipped"])
        for name in OUTPUTS:
            with self.subTest(output=name):
                self.assertIn(f"steps.run.outputs.{name}", block("outputs"))


class TestShell(unittest.TestCase):
    """The rules that keep a caller's input out of the script."""

    def test_no_expression_reaches_a_run_body(self):
        # Inputs arrive through env:. This is the quoting fix and the
        # script-injection fix at once.
        self.assertTrue(BODIES)
        for index, body in enumerate(BODIES):
            with self.subTest(body=index):
                self.assertNotIn("${{", body)

    def test_every_body_starts_the_same_way(self):
        self.assertEqual(len(BODIES), RUNS.count("run: |"))
        for index, body in enumerate(BODIES):
            with self.subTest(body=index):
                self.assertTrue(body.lstrip().startswith("set -euo pipefail"))

    def test_every_step_declares_its_shell(self):
        self.assertEqual(RUNS.count("- name:"), RUNS.count("shell: bash"))

    def test_it_is_a_composite_action(self):
        self.assertIn("using: composite", RUNS)


class TestExampleWorkflow(unittest.TestCase):
    """examples/clocwork.yml is documentation, and documentation rots.

    It is the file the README tells people to copy, so a `with:` key that no
    longer names an input is a broken workflow in somebody else's repository.
    """

    EXAMPLE = ROOT / "examples" / "clocwork.yml"

    def setUp(self):
        self.text = self.EXAMPLE.read_text()
        # Only the steps that call this action. The file also uses
        # actions/cache, whose `with:` keys sit at the same indent and are
        # nothing to do with us. Commented-out alternatives start with a #, so
        # the pattern skips them: they are prose about inputs, not inputs.
        steps = re.split(r"(?m)^      - name:", self.text)
        ours = [s for s in steps if "uses: wojciechpolak/clocwork@" in s]
        self.assertTrue(ours, "no clocwork step found; the scan is reading nothing")
        self.used = [
            name
            for step in ours
            for name in re.findall(r"(?m)^          ([a-z][a-z0-9-]*):", step)
        ]

    def test_it_is_not_a_workflow_of_ours(self):
        # Under .github/workflows/ GitHub would try to run it, and it counts
        # repositories that are not this one.
        self.assertTrue(self.EXAMPLE.is_file())
        self.assertFalse((ROOT / ".github" / "workflows" / "clocwork.yml").exists())

    def test_it_calls_the_action(self):
        self.assertIn("uses: wojciechpolak/clocwork@", self.text)

    def test_every_input_it_passes_is_declared(self):
        self.assertTrue(self.used, "no with: keys found; the scan is reading nothing")
        for name in self.used:
            with self.subTest(input=name):
                self.assertIn(name, INPUTS)

    def test_the_readme_points_at_it(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("examples/clocwork.yml", readme)


class TestBranding(unittest.TestCase):
    """Inert until there is a Marketplace listing, and required the day there is."""

    def test_an_icon_and_an_allowed_colour(self):
        branding = block("branding")
        icon = re.search(r"icon:\s*(\S+)", branding)
        color = re.search(r"color:\s*(\S+)", branding)
        self.assertIsNotNone(icon)
        self.assertIsNotNone(color)
        assert color is not None  # for the type checker
        self.assertIn(color.group(1), BRANDING_COLORS)


if __name__ == "__main__":
    unittest.main()
