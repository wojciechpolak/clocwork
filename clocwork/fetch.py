# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Clone remote projects into a cache and keep them in step with their remotes.

A `repo` in projects.toml is either a local directory or something git can
clone. This module owns the second case. `config` asks it where a clone belongs
so that `ProjectSpec.path` is a real local directory either way, and `collect`
asks it to sync just before counting. Nothing else in the program needs to know
a project came off the network.

Clones are shallow (`--depth 1`) and single branch, and they stay on disk
between runs, so a rerun costs one fetch instead of one clone.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ProjectSpec

GIT = "git"
CACHE_DIR_NAME = "clocwork"
DEFAULT_TIMEOUT = 300

# A slug longer than this buys no more recognition, and the digest after it is
# what actually keeps two projects apart.
SLUG_MAX = 40

# Schemes git can clone over. Deliberately short: every one of them names a
# host to talk to, and none of them can name a program to run.
_SCHEMES = ("https://", "http://", "ssh://", "git://")

_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")

# `ext::sh -c ...` hands git a command line to run, and other helpers can do
# the same, so the form is refused by shape rather than by name.
_HELPER = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*::")

# git's scp-like spelling, user@host:path. The user part is required, so a
# relative directory with a colon in it stays a directory.
_SCP = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9_.-]+:(?!/)")

# https://user:token@host/... A clone URL in CI usually carries a token, and it
# must not reach an error message, a progress line, or a directory name.
_USERINFO = re.compile(r"(?<=://)[^/@]*@")

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def default_cache() -> Path:
    """Where clones go when neither --cache nor the config says otherwise."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / CACHE_DIR_NAME


def is_remote(value: str) -> bool:
    """True for anything git would clone, false for a directory on this machine.

    A transport helper counts as remote so that `rejection` gets to refuse it
    by name, rather than it falling through and being read as a directory.
    """
    return bool(_SCHEME.match(value) or _HELPER.match(value) or _SCP.match(value))


def rejection(value: str) -> str | None:
    """Why git must not be handed this value, or None if it is safe.

    The caller turns the string into a ConfigError. Returning a reason rather
    than raising one keeps this module free of an import back into config.
    """
    if value.startswith("-"):
        return f"repo must not start with '-', got {value!r}"
    if _HELPER.match(value) and not _SCHEME.match(value):
        # ext::, and anything shaped like it, runs a command of the URL's
        # choosing. No report is worth that.
        return f"repo transport helpers are not allowed, got {value!r}"
    match = _SCHEME.match(value)
    if match and not value.lower().startswith(_SCHEMES):
        allowed = ", ".join(_SCHEMES)
        return f"repo scheme {match.group(1)!r} is not one of: {allowed}"
    return None


def redact(url: str) -> str:
    """The URL with any username or password taken out."""
    return _USERINFO.sub("", url)


def canonical(url: str) -> str:
    """The spelling two configs naming the same repo agree on.

    Credentials go first, so rotating a token keeps the clone. The trailing
    slash and `.git` go too, because a project written both ways is one repo
    and deserves one clone.
    """
    bare = redact(url).rstrip("/")
    return bare[:-4] if bare.endswith(".git") else bare


def repo_name(url: str) -> str:
    """The project name a clone URL implies, which is its last path segment."""
    tail = canonical(url).rsplit("/", 1)[-1]
    # An scp-form URL has no slash before the repo, so split the colon too.
    return tail.rsplit(":", 1)[-1] or "repo"


def slug(name: str) -> str:
    """A directory name that says which repo this is at a glance."""
    cleaned = _UNSAFE.sub("-", name).strip("-._")
    return cleaned[:SLUG_MAX] or "repo"


def cache_path(cache: Path, url: str, branch: str | None = None) -> Path:
    """Where one repo on one branch is kept.

    The digest covers the URL and the branch, so the same repo on two branches
    gets two clones, and repointing a project in the config cannot leave it
    counting the old remote: it asks for a directory that does not exist yet.
    """
    key = f"{canonical(url)}\n{branch or ''}".encode()
    digest = hashlib.blake2s(key, digest_size=6).hexdigest()
    return cache / f"{slug(repo_name(url))}-{digest}"


def _env() -> dict[str, str]:
    """git, with the two prompts that can hang a run turned off.

    A repo needing credentials nobody supplied should fail in a second, not
    stop a CI job forever on a password prompt with no terminal to answer it.
    """
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def _git(argv: list[str], cwd: Path | None, timeout: int) -> str | None:
    """Run one git command. None means it worked, a string says what went wrong.

    git echoes the URL it was given, so every message goes through redact on
    the way out.
    """
    try:
        proc = subprocess.run(
            [GIT, *argv],
            cwd=None if cwd is None else str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env(),
        )
    except subprocess.TimeoutExpired:
        return f"git {argv[0]} timed out after {timeout}s"
    except OSError as exc:
        return redact(str(exc))
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        message = lines[-1] if lines else f"git {argv[0]} exit code {proc.returncode}"
        return redact(message)
    return None


def clone_argv(url: str, dest: Path, branch: str | None) -> list[str]:
    """One commit of one branch, and no tags. That is all cloc ever reads."""
    argv = ["clone", "--depth", "1", "--single-branch", "--no-tags"]
    if branch:
        argv += ["--branch", branch]
    # `--` keeps a URL that survived `rejection` from being read as an option
    # anyway, whatever a future git adds.
    argv += ["--", url, str(dest)]
    return argv


def fetch_argv(branch: str | None) -> list[str]:
    """HEAD asks the remote for whatever it calls its default branch."""
    return ["fetch", "--depth", "1", "--no-tags", "origin", branch or "HEAD"]


def _clone(url: str, dest: Path, branch: str | None, timeout: int) -> str | None:
    """Clone beside the target, then rename onto it.

    A clone interrupted halfway would otherwise leave a directory that looks
    cached and counts wrong. The rename is what makes the cache entry appear
    all at once or not at all.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)

    error = _git(clone_argv(url, tmp, branch), None, timeout)
    if error is None:
        try:
            os.replace(tmp, dest)
        except OSError as exc:
            error = str(exc)
    if error is not None:
        shutil.rmtree(tmp, ignore_errors=True)
    return error


def _update(dest: Path, branch: str | None, timeout: int) -> str | None:
    """Move the clone to the remote's current tip.

    reset keeps whatever branch the clone is on, so git_metadata still has a
    branch name to report.
    """
    error = _git(fetch_argv(branch), dest, timeout)
    if error is not None:
        return error
    return _git(["reset", "--hard", "FETCH_HEAD"], dest, timeout)


def sync(
    spec: ProjectSpec, timeout: int = DEFAULT_TIMEOUT, fetch: bool = True
) -> str | None:
    """Make sure a remote project is on disk and current.

    Returns None when the directory is ready to count, or one line saying why
    it is not. Nothing here raises: a repo that will not clone is one skipped
    row, the same as a directory that is not there.

    With fetch off, an existing clone is used as it stands. A missing one is
    still cloned, because there is nothing else to count.
    """
    if spec.repo is None:
        return None

    dest = spec.path
    if dest.is_dir() and not (dest / ".git").is_dir():
        # Something that is not a clone is sitting where one belongs. The name
        # came from cache_path, so it is ours and nobody else's to lose.
        shutil.rmtree(dest, ignore_errors=True)

    if not dest.is_dir():
        return _clone(spec.repo, dest, spec.branch, timeout)
    if not fetch:
        return None
    return _update(dest, spec.branch, timeout)
