# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clocwork import fetch
from clocwork.config import ProjectSpec
from tests.helpers import FIXTURES  # noqa: F401  (sets sys.path)

REPO = "https://example.com/acme/hello-world.git"


def ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=0, stdout=stdout,
                                       stderr="")


def bad(stderr: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["git"], returncode=128, stdout="",
                                       stderr=stderr)


class TestClassify(unittest.TestCase):
    def test_urls_are_remote(self):
        for value in (
            "https://github.com/example/repo.git",
            "http://example.com/repo",
            "ssh://git@example.com/repo.git",
            "git://example.com/repo.git",
            "git@example.com:acme/hello-world.git",
        ):
            with self.subTest(value=value):
                self.assertTrue(fetch.is_remote(value))

    def test_directories_are_not_remote(self):
        for value in ("feed-reader", "~/code/thing", "/opt/thing",
                      "python/legacy-app", "C:/src/repo"):
            with self.subTest(value=value):
                self.assertFalse(fetch.is_remote(value))

    def test_a_transport_helper_is_refused(self):
        # ext:: runs a command of the URL's choosing, so it must not be read as
        # a directory either.
        self.assertTrue(fetch.is_remote("ext::sh -c whoami"))
        self.assertIn("transport helpers", fetch.rejection("ext::sh -c whoami") or "")

    def test_an_unknown_scheme_is_refused_rather_than_read_as_a_directory(self):
        self.assertIsNotNone(fetch.rejection("ftp://example.com/repo"))
        self.assertIsNotNone(fetch.rejection("file:///opt/thing"))

    def test_a_leading_dash_is_refused(self):
        self.assertIn("'-'", fetch.rejection("--upload-pack=touch /tmp/x") or "")

    def test_ordinary_values_pass(self):
        for value in (REPO, "git@example.com:acme/hello-world.git", "feed-reader"):
            with self.subTest(value=value):
                self.assertIsNone(fetch.rejection(value))


class TestNaming(unittest.TestCase):
    def test_credentials_never_survive(self):
        url = "https://user:t0ken@github.com/example/repo.git"
        self.assertEqual(fetch.redact(url), "https://github.com/example/repo.git")
        self.assertNotIn("t0ken", str(fetch.cache_path(Path("/c"), url)))

    def test_one_repo_written_two_ways_is_one_clone(self):
        self.assertEqual(
            fetch.cache_path(Path("/c"), "https://h/a/repo.git"),
            fetch.cache_path(Path("/c"), "https://h/a/repo/"),
        )

    def test_a_branch_gets_its_own_clone(self):
        self.assertNotEqual(
            fetch.cache_path(Path("/c"), REPO, "main"),
            fetch.cache_path(Path("/c"), REPO, "next"),
        )

    def test_two_repos_do_not_collide(self):
        self.assertNotEqual(
            fetch.cache_path(Path("/c"), "https://h/a/repo"),
            fetch.cache_path(Path("/c"), "https://h/b/repo"),
        )

    def test_the_directory_says_which_repo_it_is(self):
        self.assertTrue(
            fetch.cache_path(Path("/c"), REPO).name.startswith("hello-world-")
        )

    def test_the_same_url_gives_the_same_path_every_run(self):
        self.assertEqual(
            fetch.cache_path(Path("/c"), REPO, "main"),
            fetch.cache_path(Path("/c"), REPO, "main"),
        )

    def test_name_comes_off_the_url(self):
        # Never assert on the segment "repo" here. repo_name falls back to that
        # string, so the test would pass on a derivation that did nothing.
        self.assertEqual(fetch.repo_name(REPO), "hello-world")
        self.assertEqual(
            fetch.repo_name("git@example.com:acme/hello-world.git"), "hello-world"
        )
        self.assertEqual(fetch.repo_name("https://h/deep/nest/thing/"), "thing")

    def test_a_url_with_no_path_falls_back_to_the_host(self):
        self.assertEqual(fetch.repo_name("https://example.com/"), "example.com")

    def test_a_url_with_nothing_to_name_still_names_something(self):
        self.assertEqual(fetch.repo_name("https://"), "repo")

    def test_a_slug_cannot_escape_the_cache(self):
        self.assertEqual(fetch.slug("../../etc"), "etc")
        self.assertNotIn("/", fetch.cache_path(Path("/c"), "https://h/a/..").name)

    def test_default_cache_follows_xdg(self):
        with mock.patch.dict("os.environ", {"XDG_CACHE_HOME": "/x"}):
            self.assertEqual(fetch.default_cache(), Path("/x/clocwork"))


class TestArgv(unittest.TestCase):
    def test_a_clone_is_shallow_and_single_branch(self):
        argv = fetch.clone_argv(REPO, Path("/c/dest"), None)
        self.assertEqual(argv[:5],
                         ["clone", "--depth", "1", "--single-branch", "--no-tags"])
        self.assertNotIn("--branch", argv)
        self.assertEqual(argv[-3:], ["--", REPO, "/c/dest"])

    def test_a_branch_reaches_the_clone(self):
        self.assertIn("--branch", fetch.clone_argv(REPO, Path("/c/d"), "next"))

    def test_no_branch_fetches_whatever_the_remote_calls_default(self):
        self.assertEqual(fetch.fetch_argv(None)[-1], "HEAD")
        self.assertEqual(fetch.fetch_argv("next")[-1], "next")

    def test_git_cannot_be_asked_for_a_password(self):
        env = fetch._env()
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertIn("BatchMode=yes", env["GIT_SSH_COMMAND"])


class TestSync(unittest.TestCase):
    def setUp(self):
        self.cache = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.dest = self.cache / "hello-world-abc123"

    def spec(self, **kwargs) -> ProjectSpec:
        return ProjectSpec(name="hello-world", path=self.dest, repo=REPO, **kwargs)

    def run_sync(self, results, **kwargs):
        """Run sync with one CompletedProcess per git call, in order."""
        self.calls = []

        def record(argv, **run_kwargs):
            self.calls.append(argv)
            if argv[1] == "clone":
                # The real clone leaves a directory behind; the mock has to too,
                # or the rename onto the cache entry has nothing to move.
                Path(argv[-1]).mkdir(parents=True, exist_ok=True)
                (Path(argv[-1]) / ".git").mkdir()
            return results.pop(0)

        with mock.patch.object(fetch.subprocess, "run", side_effect=record):
            return fetch.sync(self.spec(**kwargs.pop("spec", {})), **kwargs)

    def test_a_local_project_is_left_alone(self):
        plain = ProjectSpec(name="alpha", path=self.dest)
        with mock.patch.object(fetch.subprocess, "run") as run:
            self.assertIsNone(fetch.sync(plain))
        run.assert_not_called()

    def test_a_missing_clone_is_cloned(self):
        self.assertIsNone(self.run_sync([ok()]))
        self.assertEqual(self.calls[0][1], "clone")
        self.assertTrue((self.dest / ".git").is_dir())

    def test_the_clone_lands_all_at_once(self):
        # git writes into a temporary name, so an interrupted clone cannot be
        # mistaken for a cached one.
        self.run_sync([ok()])
        self.assertNotEqual(self.calls[0][-1], str(self.dest))
        self.assertTrue(self.calls[0][-1].startswith(str(self.dest)))

    def test_a_failed_clone_leaves_nothing_behind(self):
        error = self.run_sync([bad("fatal: repository not found")])
        self.assertEqual(error, "fatal: repository not found")
        self.assertFalse(self.dest.exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_an_existing_clone_is_fetched_not_recloned(self):
        (self.dest / ".git").mkdir(parents=True)
        self.assertIsNone(self.run_sync([ok(), ok()]))
        self.assertEqual([c[1] for c in self.calls], ["fetch", "reset"])

    def test_no_fetch_uses_the_clone_as_it_stands(self):
        (self.dest / ".git").mkdir(parents=True)
        with mock.patch.object(fetch.subprocess, "run") as run:
            self.assertIsNone(fetch.sync(self.spec(), fetch=False))
        run.assert_not_called()

    def test_no_fetch_still_clones_what_is_not_there(self):
        self.assertIsNone(self.run_sync([ok()], fetch=False))
        self.assertEqual(self.calls[0][1], "clone")

    def test_a_directory_that_is_not_a_clone_is_replaced(self):
        self.dest.mkdir(parents=True)
        (self.dest / "leftover").write_text("half a clone")
        self.assertIsNone(self.run_sync([ok()]))
        self.assertEqual(self.calls[0][1], "clone")
        self.assertFalse((self.dest / "leftover").exists())

    def test_a_failed_fetch_stops_before_the_reset(self):
        (self.dest / ".git").mkdir(parents=True)
        self.assertEqual(self.run_sync([bad("fatal: could not read")]),
                         "fatal: could not read")
        self.assertEqual([c[1] for c in self.calls], ["fetch"])

    def test_a_token_in_the_url_never_reaches_the_error(self):
        with mock.patch.object(
            fetch.subprocess,
            "run",
            return_value=bad("fatal: https://user:t0ken@h/a/b not found"),
        ):
            error = fetch.sync(self.spec())
        self.assertNotIn("t0ken", error or "")

    def test_a_timeout_says_so(self):
        with mock.patch.object(
            fetch.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            self.assertIn("timed out", fetch.sync(self.spec(), timeout=5) or "")


if __name__ == "__main__":
    unittest.main()
