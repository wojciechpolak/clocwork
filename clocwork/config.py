# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Load and validate projects.toml.

`[defaults]` supplies values that each `[[project]]` may override, so the common
case stays a bare `repo = "..."` line. `[cli]` is a different thing under a
similar name: default values for command-line flags, which anything typed on the
line overrides.

`repo` is either a directory on this machine or a URL git can clone. A URL is
resolved here to the directory its clone will occupy, so `ProjectSpec.path` is a
local path either way and nothing downstream has to ask which kind it was.

`from_repos` builds the same Config from `--repo` values with no file involved,
so a run needs a project list but not necessarily a place to keep one.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import fetch

DEFAULT_CONFIG_NAME = "projects.toml"

_PROJECT_KEYS = {
    "repo",
    "branch",
    "name",
    "url",
    "vcs",
    "private",
    "exclude_dirs",
    "exclude_langs",
    "cloc_args",
}
# mask_label stays out of _PROJECT_KEYS. One label per run, not per project.
# url joins repo and name as a per-project identity, and branch belongs to one
# remote, so none of them is worth inheriting.
_DEFAULTS_KEYS = _PROJECT_KEYS - {"repo", "branch", "name", "url"} | {
    "root",
    "cache",
    "mask_label",
}

# Renamed rather than dropped, so the old spelling gets an answer instead of
# reading like a typo in a list of keys nobody misspelled.
_PROJECT_RENAMED = {
    "path": "'path' is now 'repo', which takes a local directory or a clone URL",
}

# [cli] keys are argparse destinations, so svg_rows rather than svg-rows.
# Checking the type here makes a wrong one fail at load, rather than crash
# argparse or Path() three stages later.
_CLI_TYPES: dict[str, type] = {
    "format": str,
    "layout": str,
    "by": str,
    "sections": str,
    "sort": str,
    "date": str,
    "basename": str,
    "out": str,
    "detail": bool,
    "quiet": bool,
    "fetch": bool,
    "svg_rows": int,
    "svg_width": int,
    "svg_title": str,
    "svg_subtitle": str,
    "timeout": int,
}
_CLI_KEYS = set(_CLI_TYPES)

# Refused by name rather than merely left out of _CLI_KEYS, so the error can
# say why instead of reading like a typo.
_CLI_REFUSED = {
    "all": "visibility stays on the command line",
    "private": "visibility stays on the command line",
    "mask": "visibility stays on the command line",
    "mask_each": "visibility stays on the command line",
    "only": "visibility stays on the command line",
    "config": "the config file cannot choose which config file to read",
    "cache": "the cache directory is read before [cli] is",
    "repo": "--repo is the mode that reads no config file, and this is one; "
    "a config file lists its projects in [[project]]",
    "stdout": "printing one format instead of writing files is a mode, "
    "not a preference",
}

# Only these reach an href, so a "javascript:" URL cannot get as far as the
# HTML or SVG output.
_URL_SCHEMES = ("http://", "https://")


class ConfigError(Exception):
    """Raised for anything wrong with the config file; the CLI prints it bare."""


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    path: Path
    repo: str | None = None
    branch: str | None = None
    url: str | None = None
    vcs: str = "git"
    private: bool = False
    exclude_dirs: list[str] = field(default_factory=list)
    exclude_langs: list[str] = field(default_factory=list)
    cloc_args: list[str] = field(default_factory=list)

    @property
    def is_remote(self) -> bool:
        """A clone URL to fetch, rather than a directory already here."""
        return self.repo is not None

    @property
    def use_git(self) -> bool:
        """Git listing needs both the opt-in and an actual repo to ask."""
        return self.vcs == "git" and (self.path / ".git").exists()


@dataclass(frozen=True)
class Config:
    source: Path
    projects: list[ProjectSpec]
    mask_label: str = "UNDISCLOSED"
    cli: dict[str, object] = field(default_factory=dict)
    cache: Path = field(default_factory=fetch.default_cache)


def _as_str_list(value, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of strings, got {value!r}")
    return list(value)


def load(path: str | Path, cache: str | None = None) -> Config:
    """Read the config file. `cache` is --cache, which outranks the file."""
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        # A fresh checkout has only the example, so say so rather than just
        # "gone".
        example = config_path.with_name(
            f"{config_path.stem}.example{config_path.suffix}"
        )
        hint = ""
        if example.is_file():
            hint = f"; copy {example.name} to {config_path.name}"
        raise ConfigError(f"config file not found: {config_path}{hint}")

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid TOML: {exc}") from exc

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("[defaults] must be a table")
    unknown = set(defaults) - _DEFAULTS_KEYS
    if unknown:
        raise ConfigError(f"[defaults]: unknown key(s): {', '.join(sorted(unknown))}")

    # Relative paths resolve against `root`, itself relative to the config file,
    # so the tool works from any working directory.
    root = (config_path.parent / str(defaults.get("root", ".."))).resolve()

    cache_root = _cache_root(cache, defaults.get("cache"), config_path.parent)

    mask_label = defaults.get("mask_label", "UNDISCLOSED")
    if not isinstance(mask_label, str) or not mask_label.strip():
        raise ConfigError(
            f"[defaults]: mask_label must be a non-empty string, got {mask_label!r}"
        )

    cli = _cli_table(raw, config_path.parent)

    entries = raw.get("project", [])
    if not isinstance(entries, list):
        raise ConfigError("[[project]] must be an array of tables")
    if not entries:
        raise ConfigError(f"{config_path}: no [[project]] entries defined")

    projects = [
        _build_project(e, i, defaults, root, cache_root)
        for i, e in enumerate(entries, 1)
    ]

    _reject_duplicate_names(projects)

    return Config(
        source=config_path,
        projects=projects,
        mask_label=mask_label,
        cli=cli,
        cache=cache_root,
    )


def from_repos(
    values: list[str], cache: str | None = None, root: Path | None = None
) -> Config:
    """A Config with no file behind it: one project per --repo value.

    --repo holds what a [[project]] repo key holds, so each value goes through
    _build_project like any other. fetch.rejection refuses the same values,
    fetch.cache_path picks the same clone directory, and two values naming one
    project collide the same way. Nothing here counts as a second reading of
    the schema.

    No file is read, so there are no [defaults] to inherit and no [cli] table
    to take flag defaults from, and the shipped defaults stand. `source` names
    the file that would have been read, because its one reader is the --out
    default and `out/` beside the config is the rule worth keeping.
    """
    base = Path.cwd() if root is None else Path(root)
    cache_root = _cache_root(cache, None, base)

    projects = []
    for index, value in enumerate(values, 1):
        text = value.strip()
        if not text:
            raise ConfigError("--repo: expected a directory or a clone URL, got ''")
        projects.append(
            _build_project(
                {"repo": text},
                index,
                {},
                base,
                cache_root,
                where=f"--repo {text!r}",
            )
        )

    _reject_duplicate_names(projects)

    return Config(
        source=base / DEFAULT_CONFIG_NAME,
        projects=projects,
        cache=cache_root,
    )


def _reject_duplicate_names(projects: list[ProjectSpec]) -> None:
    """Two projects under one name make a report nobody can read back."""
    seen: dict[str, str] = {}
    for project in projects:
        if project.name in seen:
            raise ConfigError(
                f"duplicate project name {project.name!r} "
                f"({seen[project.name]} and {project.path})"
            )
        seen[project.name] = str(project.path)


def _cache_root(override: str | None, configured, config_dir: Path) -> Path:
    """Where clones are kept: --cache, then [defaults] cache, then the default.

    A relative --cache follows the working directory, because that is where you
    typed it. A relative one in the config follows the config file, the way root
    does, so the cache does not move when you run the tool from elsewhere.
    """
    if configured is not None and (
        not isinstance(configured, str) or not configured.strip()
    ):
        raise ConfigError(
            f"[defaults]: cache must be a non-empty string, got {configured!r}"
        )
    for value, base in ((override, Path.cwd()), (configured, config_dir)):
        if isinstance(value, str) and value.strip():
            path = Path(value.strip()).expanduser()
            return path if path.is_absolute() else (base / path).resolve()
    return fetch.default_cache()


def _cli_table(raw: dict, config_dir: Path) -> dict[str, object]:
    """Read [cli], the default values for command-line flags.

    Visibility is missing from _CLI_KEYS on purpose. --all, --private, --mask,
    --mask-each and --only decide what leaves this machine, so they have to be
    readable on the line you type rather than sitting in a file you cannot see
    while typing it.
    """
    table = raw.get("cli", {})
    if not isinstance(table, dict):
        raise ConfigError("[cli] must be a table")

    refused = sorted(set(table) & set(_CLI_REFUSED))
    if refused:
        raise ConfigError(
            "[cli]: "
            + "; ".join(
                f"{key!r} is not settable here, {_CLI_REFUSED[key]}"
                for key in refused
            )
        )
    unknown = set(table) - _CLI_KEYS
    if unknown:
        raise ConfigError(f"[cli]: unknown key(s): {', '.join(sorted(unknown))}")

    values: dict[str, object] = {}
    for key, value in table.items():
        want = _CLI_TYPES[key]
        # bool first: True is an int in Python, so the int branch would take it.
        if want is bool:
            ok = isinstance(value, bool)
        elif want is int:
            ok = isinstance(value, int) and not isinstance(value, bool)
        else:
            ok = isinstance(value, str)
        if not ok:
            raise ConfigError(
                f"[cli]: {key} must be {want.__name__}, got {value!r}"
            )
        values[key] = value

    # A relative out follows the config file, the way root does, so the target
    # does not move with the working directory.
    out = values.get("out")
    if isinstance(out, str):
        path = Path(out).expanduser()
        values["out"] = str(path if path.is_absolute() else config_dir / path)

    return values


def _directory_name(path: Path) -> str:
    """The directory's own name, even when the value written ends in '..'.

    Path('/code/x/..').name is '..', which would put a project called '..' in
    the report. normpath is lexical, so it drops the segment without following
    symlinks and without touching the path cloc is handed. The fallback is the
    one fetch.repo_name already uses, so both halves of default_name agree.
    """
    return Path(os.path.normpath(path)).name or "repo"


def _build_project(
    entry,
    index: int,
    defaults: dict,
    root: Path,
    cache: Path,
    where: str | None = None,
) -> ProjectSpec:
    # `where` names --repo when the value was typed rather than written down.
    # Left unset it is the table it came from, and every message reads as it
    # always did.
    where = where or f"[[project]] #{index}"
    if not isinstance(entry, dict):
        raise ConfigError(f"{where}: must be a table")
    renamed = sorted(set(entry) & set(_PROJECT_RENAMED))
    if renamed:
        raise ConfigError(
            f"{where}: " + "; ".join(_PROJECT_RENAMED[key] for key in renamed)
        )
    unknown = set(entry) - _PROJECT_KEYS
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(sorted(unknown))}")

    raw_repo = entry.get("repo")
    if not isinstance(raw_repo, str) or not raw_repo.strip():
        raise ConfigError(f"{where}: missing required string key 'repo'")
    raw_repo = raw_repo.strip()
    refusal = fetch.rejection(raw_repo)
    if refusal:
        raise ConfigError(f"{where}: {refusal}")

    branch = entry.get("branch")
    if branch is not None:
        if not isinstance(branch, str) or not branch.strip():
            raise ConfigError(
                f"{where}: branch must be a non-empty string, got {branch!r}"
            )
        branch = branch.strip()
        if branch.startswith("-"):
            raise ConfigError(
                f"{where}: branch must not start with '-', got {branch!r}"
            )

    if fetch.is_remote(raw_repo):
        repo = raw_repo
        # The clone lands under the cache, so path stays a real local directory
        # and use_git, git_metadata and the renderers never learn the
        # difference.
        path = fetch.cache_path(cache, repo, branch)
        default_name = fetch.repo_name(repo)
    else:
        if branch:
            raise ConfigError(
                f"{where}: branch applies only to a repo clocwork clones itself, "
                f"and {raw_repo!r} is a local directory"
            )
        repo = None
        path = Path(raw_repo).expanduser()
        if not path.is_absolute():
            path = root / path
        default_name = _directory_name(path)

    def setting(key: str) -> list[str]:
        value = entry.get(key, defaults.get(key, []))
        return _as_str_list(value, f"{where}: {key}")

    vcs = str(entry.get("vcs", defaults.get("vcs", "git")))
    if vcs not in ("git", "none"):
        raise ConfigError(f"{where}: vcs must be 'git' or 'none', got {vcs!r}")

    name = entry.get("name")
    if name is not None and not isinstance(name, str):
        raise ConfigError(f"{where}: name must be a string")

    # The home page, which is not the clone URL. On GitHub they differ by a
    # ".git" and elsewhere they need not resemble each other at all, so neither
    # one is ever derived from the other.
    url = entry.get("url")
    if url is not None:
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{where}: url must be a non-empty string, got {url!r}")
        url = url.strip()
        if not url.lower().startswith(_URL_SCHEMES):
            raise ConfigError(
                f"{where}: url must start with http:// or https://, got {url!r}"
            )

    private = entry.get("private", defaults.get("private", False))
    if not isinstance(private, bool):
        raise ConfigError(f"{where}: private must be true or false, got {private!r}")

    return ProjectSpec(
        name=name or default_name,
        path=path,
        repo=repo,
        branch=branch,
        url=url,
        vcs=vcs,
        private=private,
        exclude_dirs=setting("exclude_dirs"),
        exclude_langs=setting("exclude_langs"),
        cloc_args=setting("cloc_args"),
    )
