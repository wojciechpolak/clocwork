# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run cloc over each configured project and normalise its JSON output.

cloc's own `--sum-reports` ("combine reports") collapses everything into a single
grand total, which loses the per-project breakdown this tool exists to produce.
So clocwork counts each project on its own and aggregates in `model`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .config import ProjectSpec
from .fetch import sync
from .model import LangCount, ProjectReport

CLOC = "cloc"
DEFAULT_TIMEOUT = 300

# cloc puts these alongside the language entries in its JSON object.
_NON_LANGUAGE_KEYS = {"header", "SUM"}


class ClocMissing(Exception):
    """cloc is not on PATH."""


def ensure_cloc() -> str:
    found = shutil.which(CLOC)
    if not found:
        raise ClocMissing(
            "cloc not found on PATH. Install it with:  brew install cloc\n"
            "(see https://github.com/AlDanial/cloc)"
        )
    return found


def cloc_version() -> str | None:
    try:
        proc = subprocess.run(
            [CLOC, "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None


def build_argv(spec: ProjectSpec) -> list[str]:
    # --quiet drops the progress preamble that would otherwise precede the JSON.
    #
    # --hide-rate is missing on purpose. It strips elapsed_seconds and
    # lines_per_second from the header, which parse_cloc_json drops along with
    # the rest of the header anyway, and cloc 1.98 closes that shortened header
    # with a trailing comma, which no JSON parser accepts. 1.98 is what apt
    # installs on Ubuntu, so the flag bought nothing and cost every run there.
    argv = [CLOC, "--json", "--quiet"]
    if spec.use_git:
        # Ask git for the file list, so untracked and .gitignore'd paths
        # (node_modules, dist, build output) never reach cloc.
        argv.append("--vcs=git")
    if spec.exclude_dirs:
        argv.append("--exclude-dir=" + ",".join(spec.exclude_dirs))
    argv.extend(spec.cloc_args)
    argv.append(".")
    return argv


def _git(path: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=path, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_metadata(spec: ProjectSpec) -> tuple[str | None, str | None]:
    """Branch and short commit, best effort. A bare checkout reports None."""
    if not (spec.path / ".git").exists():
        return None, None
    branch = _git(spec.path, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git(spec.path, "log", "-1", "--format=%h")
    return branch, commit


def parse_cloc_json(payload: str) -> dict[str, LangCount]:
    """Turn cloc's JSON object into language -> counts, dropping header and SUM."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("cloc did not return a JSON object")
    return {
        lang: LangCount.from_cloc(blob)
        for lang, blob in data.items()
        if lang not in _NON_LANGUAGE_KEYS and isinstance(blob, dict)
    }


def _failed(spec: ProjectSpec, message: str) -> ProjectReport:
    return ProjectReport(
        name=spec.name, path=str(spec.path), url=spec.url, error=message
    )


def collect_project(
    spec: ProjectSpec, timeout: int = DEFAULT_TIMEOUT, fetch: bool = True
) -> ProjectReport:
    """Count one project. This returns failures rather than raising them, so
    one broken path cannot take down a whole run."""
    if spec.is_remote:
        # A remote project has to be on disk before there is anything to count,
        # and a clone that fails is one skipped row like any other.
        error = sync(spec, timeout=timeout, fetch=fetch)
        if error:
            return _failed(spec, error)

    if not spec.path.is_dir():
        return _failed(spec, "directory not found")

    try:
        proc = subprocess.run(
            build_argv(spec),
            cwd=spec.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _failed(spec, f"cloc timed out after {timeout}s")
    except OSError as exc:
        return _failed(spec, str(exc))

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit code {proc.returncode}"
        return _failed(spec, message)

    # cloc emits an empty body (not `{}`) for a repo with nothing countable.
    if not proc.stdout.strip():
        return _failed(spec, "no countable files")

    try:
        languages = parse_cloc_json(proc.stdout)
    except (ValueError, json.JSONDecodeError) as exc:
        return _failed(spec, f"unreadable cloc output: {exc}")

    branch, commit = git_metadata(spec)
    report = ProjectReport(
        name=spec.name,
        path=str(spec.path),
        languages=languages,
        url=spec.url,
        branch=branch,
        commit=commit,
    )
    # Excluding after the count keeps the filter cheap to change. Nothing
    # rescans, and the config stays the only place that decides what is hidden.
    return report.without_languages(set(spec.exclude_langs))


def collect_all(
    specs: list[ProjectSpec],
    timeout: int = DEFAULT_TIMEOUT,
    on_progress=None,
    fetch: bool = True,
) -> list[ProjectReport]:
    reports = []
    for spec in specs:
        if on_progress:
            on_progress(spec)
        reports.append(collect_project(spec, timeout=timeout, fetch=fetch))
    return reports
