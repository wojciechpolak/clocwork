# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clocwork import config, fetch
from tests.helpers import sample_report  # noqa: F401  (sets sys.path)


def write_config(body: str) -> Path:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "projects.toml"
    path.write_text(body)
    return path


class TestLoad(unittest.TestCase):
    def test_defaults_are_inherited_and_overridden(self):
        path = write_config(
            """
[defaults]
root = "projects"
exclude_langs = ["JSON"]
cloc_args = ["--no3"]

[[project]]
repo = "alpha"
name = "Alpha One"

[[project]]
repo = "beta"
exclude_langs = ["Markdown"]
"""
        )
        cfg = config.load(path)
        alpha, beta = cfg.projects

        self.assertEqual(alpha.name, "Alpha One")
        self.assertEqual(alpha.exclude_langs, ["JSON"])
        self.assertEqual(alpha.cloc_args, ["--no3"])
        # A per-project value replaces the default outright.
        self.assertEqual(beta.exclude_langs, ["Markdown"])
        self.assertEqual(beta.cloc_args, ["--no3"])

    def test_name_defaults_to_directory_name(self):
        path = write_config('[[project]]\nrepo = "some/nested/thing"\n')
        self.assertEqual(config.load(path).projects[0].name, "thing")

    def test_relative_paths_resolve_against_root_next_to_config(self):
        path = write_config(
            '[defaults]\nroot = ".."\n\n[[project]]\nrepo = "dotfiles"\n'
        )
        resolved = config.load(path).projects[0].path
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved.name, "dotfiles")
        self.assertEqual(resolved.parent, path.parent.parent.resolve())

    def test_absolute_path_is_left_alone(self):
        path = write_config('[[project]]\nrepo = "/opt/thing"\n')
        self.assertEqual(str(config.load(path).projects[0].path), "/opt/thing")

    def test_missing_repo_key(self):
        path = write_config('[[project]]\nname = "no repo"\n')
        with self.assertRaisesRegex(config.ConfigError, "repo"):
            config.load(path)

    def test_the_old_path_key_says_what_it_became(self):
        path = write_config('[[project]]\npath = "alpha"\n')
        with self.assertRaisesRegex(config.ConfigError, "'path' is now 'repo'"):
            config.load(path)

    def test_no_projects(self):
        path = write_config('[defaults]\nroot = ".."\n')
        with self.assertRaisesRegex(config.ConfigError, "no \\[\\[project\\]\\]"):
            config.load(path)

    def test_unknown_key_is_rejected(self):
        path = write_config('[[project]]\nrepo = "a"\nexclude = ["x"]\n')
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            config.load(path)

    def test_duplicate_names_are_rejected(self):
        path = write_config(
            '[[project]]\nrepo = "a/dotfiles"\n\n[[project]]\nrepo = "b/dotfiles"\n'
        )
        with self.assertRaisesRegex(config.ConfigError, "duplicate"):
            config.load(path)

    def test_private_defaults_to_false(self):
        path = write_config('[[project]]\nrepo = "a"\n')
        self.assertFalse(config.load(path).projects[0].private)

    def test_private_is_inherited_and_overridden(self):
        path = write_config(
            """
[defaults]
private = true

[[project]]
repo = "alpha"

[[project]]
repo = "beta"
private = false
"""
        )
        alpha, beta = config.load(path).projects
        self.assertTrue(alpha.private)
        self.assertFalse(beta.private)

    def test_bad_private_value(self):
        path = write_config('[[project]]\nrepo = "a"\nprivate = "yes"\n')
        with self.assertRaisesRegex(config.ConfigError, "private must be"):
            config.load(path)

    def test_url_is_optional_and_trimmed(self):
        path = write_config('[[project]]\nrepo = "a"\n')
        self.assertIsNone(config.load(path).projects[0].url)
        path = write_config(
            '[[project]]\nrepo = "a"\nurl = "  https://example.com/a  "\n'
        )
        self.assertEqual(config.load(path).projects[0].url, "https://example.com/a")

    def test_bad_url_value(self):
        for value in ('url = 7', 'url = "  "', 'url = "javascript:alert(1)"',
                      'url = "example.com/a"'):
            path = write_config(f'[[project]]\nrepo = "a"\n{value}\n')
            with self.assertRaisesRegex(config.ConfigError, "url"):
                config.load(path)

    def test_url_is_not_a_defaults_key(self):
        path = write_config(
            '[defaults]\nurl = "https://example.com"\n\n[[project]]\nrepo = "a"\n'
        )
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            config.load(path)

    def test_bad_vcs_value(self):
        path = write_config('[[project]]\nrepo = "a"\nvcs = "svn"\n')
        with self.assertRaisesRegex(config.ConfigError, "vcs"):
            config.load(path)

    def test_mask_label_defaults_and_can_be_set(self):
        path = write_config('[[project]]\nrepo = "a"\n')
        self.assertEqual(config.load(path).mask_label, "UNDISCLOSED")
        path = write_config(
            '[defaults]\nmask_label = "STEALTH"\n\n[[project]]\nrepo = "a"\n'
        )
        self.assertEqual(config.load(path).mask_label, "STEALTH")

    def test_bad_mask_label(self):
        for value in ('mask_label = 7', 'mask_label = "  "'):
            path = write_config(f'[defaults]\n{value}\n\n[[project]]\nrepo = "a"\n')
            with self.assertRaisesRegex(config.ConfigError, "mask_label"):
                config.load(path)

    def test_mask_label_is_not_a_per_project_key(self):
        path = write_config('[[project]]\nrepo = "a"\nmask_label = "X"\n')
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            config.load(path)

    def test_missing_file(self):
        with self.assertRaisesRegex(config.ConfigError, "not found"):
            config.load("/nonexistent/projects.toml")

    def test_missing_file_points_at_the_example_when_there_is_one(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "projects.example.toml").write_text('[[project]]\nrepo = "a"\n')
        with self.assertRaisesRegex(
            config.ConfigError, "copy projects.example.toml to projects.toml"
        ):
            config.load(tmp / "projects.toml")

    def test_invalid_toml(self):
        path = write_config("this is not toml =\n")
        with self.assertRaisesRegex(config.ConfigError, "invalid TOML"):
            config.load(path)


class TestRemoteRepo(unittest.TestCase):
    """A repo that is a URL resolves to the directory its clone will occupy."""

    REPO = "https://example.com/acme/hello-world.git"

    def one(self, body: str, **kwargs):
        return config.load(write_config(body), **kwargs).projects[0]

    def test_a_url_becomes_a_clone_under_the_cache(self):
        spec = self.one(f'[[project]]\nrepo = "{self.REPO}"\n', cache="/c")
        self.assertEqual(spec.repo, self.REPO)
        self.assertTrue(spec.is_remote)
        self.assertEqual(spec.path.parent, Path("/c"))
        self.assertEqual(spec.path, fetch.cache_path(Path("/c"), self.REPO))

    def test_a_directory_stays_a_directory(self):
        spec = self.one('[defaults]\nroot = "/code"\n\n[[project]]\nrepo = "a"\n')
        self.assertIsNone(spec.repo)
        self.assertFalse(spec.is_remote)
        self.assertEqual(spec.path, Path("/code/a"))

    def test_the_name_comes_off_the_url(self):
        # A segment other than "repo", which is what repo_name falls back to.
        self.assertEqual(
            self.one(f'[[project]]\nrepo = "{self.REPO}"\n', cache="/c").name,
            "hello-world",
        )

    def test_a_given_name_still_wins(self):
        spec = self.one(
            f'[[project]]\nrepo = "{self.REPO}"\nname = "VCStreak"\n', cache="/c"
        )
        self.assertEqual(spec.name, "VCStreak")

    def test_a_branch_moves_the_clone(self):
        body = f'[[project]]\nrepo = "{self.REPO}"\nbranch = "  next  "\n'
        spec = self.one(body, cache="/c")
        self.assertEqual(spec.branch, "next")
        self.assertNotEqual(spec.path, fetch.cache_path(Path("/c"), self.REPO))

    def test_a_branch_needs_a_remote_to_check_out(self):
        # Checking out a branch in somebody's own working tree is not this
        # program's business.
        path = write_config('[[project]]\nrepo = "a"\nbranch = "next"\n')
        with self.assertRaisesRegex(config.ConfigError, "local directory"):
            config.load(path)

    def test_a_bad_branch_is_rejected(self):
        for value in ('branch = 7', 'branch = "  "', 'branch = "--upload-pack=x"'):
            with self.subTest(value=value):
                path = write_config(
                    f'[[project]]\nrepo = "{self.REPO}"\n{value}\n'
                )
                with self.assertRaisesRegex(config.ConfigError, "branch"):
                    config.load(path)

    def test_a_dangerous_repo_is_rejected(self):
        for value in ("ext::sh -c whoami", "ftp://h/a", "file:///opt/a", "-x"):
            with self.subTest(value=value):
                path = write_config(f'[[project]]\nrepo = "{value}"\n')
                with self.assertRaisesRegex(config.ConfigError, "repo"):
                    config.load(path)

    def test_branch_is_not_a_defaults_key(self):
        path = write_config(
            '[defaults]\nbranch = "main"\n\n[[project]]\nrepo = "a"\n'
        )
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            config.load(path)

    def test_the_home_page_is_never_taken_from_the_clone_url(self):
        # The two differ by a ".git" on GitHub and by everything elsewhere.
        self.assertIsNone(
            self.one(f'[[project]]\nrepo = "{self.REPO}"\n', cache="/c").url
        )


class TestCacheRoot(unittest.TestCase):
    def test_the_flag_beats_the_config(self):
        path = write_config('[defaults]\ncache = "/from-config"\n\n'
                            '[[project]]\nrepo = "a"\n')
        self.assertEqual(config.load(path, cache="/from-flag").cache,
                         Path("/from-flag"))

    def test_the_config_beats_the_default(self):
        path = write_config('[defaults]\ncache = "/from-config"\n\n'
                            '[[project]]\nrepo = "a"\n')
        self.assertEqual(config.load(path).cache, Path("/from-config"))

    def test_a_relative_cache_follows_the_config_file(self):
        path = write_config('[defaults]\ncache = "clones"\n\n'
                            '[[project]]\nrepo = "a"\n')
        self.assertEqual(config.load(path).cache, path.parent.resolve() / "clones")

    def test_the_default_is_the_xdg_one(self):
        path = write_config('[[project]]\nrepo = "a"\n')
        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/x"}):
            self.assertEqual(config.load(path).cache, Path("/x/clocwork"))

    def test_a_bad_cache_value(self):
        path = write_config('[defaults]\ncache = 7\n\n[[project]]\nrepo = "a"\n')
        with self.assertRaisesRegex(config.ConfigError, "cache must be"):
            config.load(path)


class TestProjectSpec(unittest.TestCase):
    def test_use_git_requires_both_opt_in_and_a_repo(self):
        tmp = Path(tempfile.mkdtemp())
        spec = config.ProjectSpec(name="x", path=tmp, vcs="git")
        self.assertFalse(spec.use_git)  # no .git directory
        (tmp / ".git").mkdir()
        self.assertTrue(spec.use_git)
        self.assertFalse(config.ProjectSpec(name="x", path=tmp, vcs="none").use_git)


class TestCliTable(unittest.TestCase):
    """[cli] holds default values for command-line flags."""

    BODY = '\n[[project]]\nrepo = "alpha"\n'

    def load(self, cli_body: str):
        return config.load(write_config(cli_body + self.BODY))

    def test_absent_table_is_empty(self):
        self.assertEqual(self.load("").cli, {})

    def test_values_come_through_by_argparse_destination(self):
        cfg = self.load(
            '[cli]\nlayout = "all"\nsvg_rows = 8\ndetail = true\ntimeout = 60\n'
        )
        self.assertEqual(
            cfg.cli, {"layout": "all", "svg_rows": 8, "detail": True, "timeout": 60}
        )

    def test_visibility_keys_are_refused_and_the_error_says_why(self):
        for key, value in (
            ("all", "true"),
            ("private", "true"),
            ("mask", "true"),
            ("mask_each", "true"),
            ("only", '"alpha"'),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(
                config.ConfigError, "not settable here.*command line"
            ):
                self.load(f"[cli]\n{key} = {value}\n")

    def test_config_and_stdout_are_refused_too(self):
        with self.assertRaisesRegex(config.ConfigError, "which config file"):
            self.load('[cli]\nconfig = "other.toml"\n')
        with self.assertRaisesRegex(config.ConfigError, "not a preference"):
            self.load('[cli]\nstdout = "md"\n')

    def test_unknown_key(self):
        with self.assertRaisesRegex(config.ConfigError, "unknown key"):
            self.load('[cli]\nlayouts = "all"\n')

    def test_wrong_types(self):
        with self.assertRaisesRegex(config.ConfigError, "svg_rows must be int"):
            self.load('[cli]\nsvg_rows = "eight"\n')
        with self.assertRaisesRegex(config.ConfigError, "layout must be str"):
            self.load("[cli]\nlayout = 3\n")

    def test_a_bool_key_does_not_take_an_int(self):
        # True is an int in Python, so the int branch would swallow this one.
        with self.assertRaisesRegex(config.ConfigError, "detail must be bool"):
            self.load("[cli]\ndetail = 1\n")

    def test_an_int_key_does_not_take_a_bool(self):
        with self.assertRaisesRegex(config.ConfigError, "timeout must be int"):
            self.load("[cli]\ntimeout = true\n")

    def test_a_relative_out_follows_the_config_file(self):
        cfg = self.load('[cli]\nout = "reports"\n')
        self.assertEqual(cfg.cli["out"], str(cfg.source.parent / "reports"))

    def test_an_absolute_out_is_left_alone(self):
        cfg = self.load('[cli]\nout = "/tmp/somewhere"\n')
        self.assertEqual(cfg.cli["out"], "/tmp/somewhere")

    def test_not_a_table(self):
        with self.assertRaisesRegex(config.ConfigError, r"\[cli\] must be a table"):
            self.load('cli = "all"\n')

    def test_fetch_is_a_bool(self):
        self.assertIs(self.load("[cli]\nfetch = false\n").cli["fetch"], False)
        with self.assertRaisesRegex(config.ConfigError, "fetch must be bool"):
            self.load('[cli]\nfetch = "no"\n')

    def test_cache_is_refused_because_it_is_read_first(self):
        with self.assertRaisesRegex(config.ConfigError, "read before"):
            self.load('[cli]\ncache = "/c"\n')


if __name__ == "__main__":
    unittest.main()
