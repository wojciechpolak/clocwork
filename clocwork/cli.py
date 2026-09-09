# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Command line entry point: config -> collect -> report -> rendered files."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from . import render as render_pkg
from .collect import ClocMissing, cloc_version, collect_all, ensure_cloc
from .config import DEFAULT_CONFIG_NAME, ConfigError, ProjectSpec
from .config import load as load_config
from .model import ProjectReport, Report, merge_projects

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = "out"
SORT_KEYS = ("code", "name", "files")
HELP_WIDTH = 80


def default_config_path() -> Path:
    """projects.toml in the working directory, else the one beside the tool.

    PACKAGE_ROOT is the repository in a checkout and site-packages anywhere
    else, so the second half of that answer is only useful to someone running
    from the source tree. An installed clocwork, from Homebrew or a plain pip,
    has no project list next to it and never will, and the working directory
    is the only place it can look. In a checkout the two agree: the working
    directory is the repository root, and both name the same file.
    """
    local = Path.cwd() / DEFAULT_CONFIG_NAME
    return local if local.is_file() else PACKAGE_ROOT / DEFAULT_CONFIG_NAME


class HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Wrap help at HELP_WIDTH, or at the terminal when it is narrower.

    argparse follows the terminal alone, which on a wide one sets option help
    in 190-column paragraphs the eye cannot track back from. The ceiling only
    ever narrows the text, so a small terminal still wraps to its own width.
    Two columns of slack come off either figure, which is argparse's own
    convention and keeps a line off the right edge.

    Raw is inherited for the epilog, whose examples are aligned by hand. It
    covers the description too, so that string has to arrive short enough to
    print as one line: this formatter will not fold it.
    """

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 24,
        width: int | None = None,
    ) -> None:
        given = width or shutil.get_terminal_size().columns
        capped = min(given, HELP_WIDTH) - 2
        super().__init__(prog, indent_increment, max_help_position, capped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clocwork",
        description="Count lines of code across several projects with cloc "
        "and render one report.",
        formatter_class=HelpFormatter,
        epilog="examples:\n"
        "  clocwork                        # all formats into out/\n"
        "  clocwork --stdout md            # Markdown to stdout, write nothing\n"
        "  clocwork --only aoc --detail    # one project, per-language breakdown\n"
        "  clocwork --sections language    # the language table on its own\n"
        "  clocwork --layout strip         # a thin wrapping band of languages\n"
        "  clocwork --layout strip --by project   # ...of projects instead\n"
        "  clocwork --svg-rows 12          # label twelve rows, not six\n"
        "  clocwork --layout banner --svg-title clocwork\n"
        "  clocwork --all                  # public and private projects together\n"
        "  clocwork --mask                 # ...with the private ones anonymous\n"
        "  clocwork --mask-each            # ...anonymous but not merged together\n",
    )
    parser.add_argument(
        "-c",
        "--config",
        default=str(default_config_path()),
        help=f"project list (default: {DEFAULT_CONFIG_NAME} here, "
        "else next to this tool)",
    )
    parser.add_argument(
        "-o",
        "--out",
        # Left unset so main can put it beside whichever config file won.
        default=None,
        help=f"output directory (default: {DEFAULT_OUT}/ beside the config)",
    )
    parser.add_argument(
        "--cache",
        metavar="DIR",
        help="where clones of remote projects are kept (default: cache from "
        "the config, else $XDG_CACHE_HOME/clocwork, else ~/.cache/clocwork)",
    )
    parser.add_argument(
        "-f",
        "--format",
        default="all",
        help=(
            f"comma separated: {', '.join(render_pkg.FORMAT_NAMES)}, "
            "or 'all' (default: all)"
        ),
    )
    parser.add_argument(
        "--stdout",
        metavar="FORMAT",
        choices=render_pkg.FORMAT_NAMES,
        help="print one format to stdout and write no files",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="NAME",
        help="count only this project (name or directory); repeatable",
    )
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument(
        "--private",
        action="store_true",
        help="count only projects marked private in the config",
    )
    visibility.add_argument(
        "--all",
        action="store_true",
        help="count private projects as well as public ones",
    )
    parser.add_argument(
        "--mask",
        nargs="?",
        const="",
        metavar="LABEL",
        help="count private projects, but merge them into one anonymous row "
        "(label: LABEL, else mask_label from the config, else UNDISCLOSED)",
    )
    parser.add_argument(
        "--mask-each",
        action="store_true",
        help="mask private projects without merging them: each keeps its own "
        "row, numbered LABEL-1, LABEL-2, ... (implies --mask)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="include the per-project, per-language breakdown",
    )
    # store_true has no off switch, so without this nothing typed could turn a
    # [cli] detail = true back off for one run.
    parser.add_argument(
        "--no-detail",
        dest="detail",
        action="store_false",
        help="drop the breakdown, overriding detail in the config's [cli] table",
    )
    parser.add_argument(
        "--sections",
        default="all",
        help=(
            f"summary tables to include, comma separated: "
            f"{', '.join(render_pkg.SECTION_NAMES)}, or 'all' (default: all)"
        ),
    )
    parser.add_argument(
        "--layout",
        default=render_pkg.DEFAULT_LAYOUT,
        help=(
            f"SVG shapes to draw, comma separated: "
            f"{', '.join(render_pkg.LAYOUT_NAMES)}, or 'all' "
            f"(default: {render_pkg.DEFAULT_LAYOUT}); each one writes its own "
            "file, named after the layout. Other formats ignore it"
        ),
    )
    parser.add_argument(
        "--by",
        default=render_pkg.DEFAULT_SUBJECT,
        help=(
            f"what the SVG layouts are drawn over, comma separated: "
            f"{', '.join(render_pkg.SUBJECT_NAMES)}, or 'all' "
            f"(default: {render_pkg.DEFAULT_SUBJECT}); each is written to "
            "<layout>-<subject>s.svg. Other formats ignore it"
        ),
    )
    parser.add_argument(
        "--svg-width",
        type=int,
        metavar="PX",
        help="override the SVG width; each layout has its own default",
    )
    parser.add_argument(
        "--svg-rows",
        type=int,
        metavar="N",
        help=(
            f"how many rows an SVG layout labels (default: "
            f"{render_pkg.DEFAULT_ROWS}, or 0 for every row). Only card, bars "
            "and donut keep a list. strip and bar label every row already, and "
            "other formats ignore it"
        ),
    )
    parser.add_argument(
        "--svg-title",
        metavar="TEXT",
        help=(
            "headline for the banner layout, above the total. No other layout "
            "has anywhere to put one, and they ignore it"
        ),
    )
    parser.add_argument(
        "--svg-subtitle",
        metavar="TEXT",
        help="second line under --svg-title, on the banner layout only",
    )
    parser.add_argument(
        "--sort",
        default="code",
        choices=SORT_KEYS,
        help="order rows by (default: code)",
    )
    parser.add_argument(
        "--basename",
        default="report",
        help="stem for generated files (default: report)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="seconds to allow each cloc run, clone and fetch (default: 300)",
    )
    # Both carry the same default, so which one is declared first does not
    # decide what a bare run does.
    parser.add_argument(
        "--no-fetch",
        dest="fetch",
        action="store_false",
        default=True,
        help="do not contact the remotes; count the clones already cached. "
        "A project with no clone yet is still cloned, since there is nothing "
        "else to count",
    )
    parser.add_argument(
        "--fetch",
        dest="fetch",
        action="store_true",
        default=True,
        help="update the clones before counting, overriding fetch in the "
        "config's [cli] table (default)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress")
    parser.add_argument(
        "--no-quiet",
        dest="quiet",
        action="store_false",
        help="show progress, overriding quiet in the config's [cli] table",
    )
    parser.add_argument(
        "--version", action="version", version=f"clocwork {__version__}"
    )
    return parser


def resolve_formats(value: str) -> list[str]:
    if value.strip() == "all":
        return list(render_pkg.FORMAT_NAMES)
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in render_pkg.FORMAT_NAMES]
    if unknown:
        raise ValueError(
            f"unknown format(s): {', '.join(unknown)}; "
            f"choose from {', '.join(render_pkg.FORMAT_NAMES)}"
        )
    if not names:
        raise ValueError("no formats selected")
    return names


def resolve_sections(value: str) -> list[str]:
    """Which summary tables to render. The order given does not matter, because
    each format keeps its own section order, so the result comes back
    canonical."""
    if value.strip() == "all":
        return list(render_pkg.SECTION_NAMES)
    names = {n.strip() for n in value.split(",") if n.strip()}
    unknown = sorted(n for n in names if n not in render_pkg.SECTION_NAMES)
    if unknown:
        raise ValueError(
            f"unknown section(s): {', '.join(unknown)}; "
            f"choose from {', '.join(render_pkg.SECTION_NAMES)}"
        )
    if not names:
        raise ValueError("no sections selected")
    return [n for n in render_pkg.SECTION_NAMES if n in names]


def masking(args: argparse.Namespace) -> bool:
    """--mask-each is a way of masking, so it turns masking on by itself."""
    return args.mask is not None or args.mask_each


def resolve_visibility(args: argparse.Namespace) -> str:
    """--mask asks for private counts, so on its own it means --all."""
    if args.all:
        return "all"
    if args.private:
        return "private"
    return "all" if masking(args) else "public"


def _visible(spec: ProjectSpec, visibility: str) -> bool:
    return visibility == "all" or spec.private == (visibility == "private")


def filter_projects(
    specs: list[ProjectSpec], only: list[str] | None, visibility: str = "public"
):
    """Match --only against project name or directory name, case-insensitively.

    An explicit --only names the project outright, so it overrides the
    visibility filter; otherwise private projects stay out unless asked for.
    """
    if not only:
        return [s for s in specs if _visible(s, visibility)], []
    wanted = {value.lower() for value in only}
    kept = [
        s for s in specs if s.name.lower() in wanted or s.path.name.lower() in wanted
    ]
    matched = {s.name.lower() for s in kept} | {s.path.name.lower() for s in kept}
    return kept, sorted(wanted - matched)


def mask_private(
    specs: list[ProjectSpec],
    reports: list[ProjectReport],
    label: str,
    each: bool = False,
) -> list[ProjectReport]:
    """Replace every private project with an anonymous entry.

    By default they all fold into one merged row. With `each`, every private
    project keeps its own row under a numbered label instead.

    Renderers stay unaware of any of this. They receive projects called
    `label`, with no path, branch, or commit to give them away.
    """
    # One report per spec, in order; strict= turns any future drift into an error
    # rather than a silently truncated list.
    public = [r for s, r in zip(specs, reports, strict=True) if not s.private]
    hidden = [r for s, r in zip(specs, reports, strict=True) if s.private]
    if not hidden:
        return public

    counted = [r for r in hidden if r.ok]
    failed = [r for r in hidden if not r.ok]
    if each:
        return public + number_masked(counted, failed, label)

    masked = [merge_projects(counted, label)] if counted else []
    if failed:
        # Folding a failure into the counted row would swallow it and quietly
        # under-report the totals, so it stays a separate, still nameless entry.
        masked.append(
            ProjectReport(
                name=label,
                path=label,
                error=f"{len(failed)} private project(s) could not be counted",
            )
        )
    return public + masked


def number_masked(
    counted: list[ProjectReport], failed: list[ProjectReport], label: str
) -> list[ProjectReport]:
    """One anonymous row per private project, labelled LABEL-1, LABEL-2, ...

    Numbers run largest first so the rows read in order under the default
    --sort code, and are zero padded past nine so --sort name agrees. Merging
    a project with itself is what strips its url, branch and commit, exactly
    as the single merged row does.
    """
    ordered = sorted(counted, key=lambda r: -r.total.code) + failed
    width = len(str(len(ordered)))
    masked = []
    for i, report in enumerate(ordered, start=1):
        name = f"{label}-{i:0{width}d}"
        if report.ok:
            masked.append(merge_projects([report], name))
        else:
            # The error text can name a path, so it does not survive either.
            masked.append(
                ProjectReport(
                    name=name, path=name, error="private project could not be counted"
                )
            )
    return masked


def resolve_layouts(value: str) -> list[str]:
    """Same shape as resolve_sections. Validated, and returned in LAYOUT_NAMES
    order rather than the order typed, so `--layout donut,card` and
    `--layout card,donut` write the same two files in the same sequence."""
    if value.strip() == "all":
        return list(render_pkg.LAYOUT_NAMES)
    names = {n.strip() for n in value.split(",") if n.strip()}
    unknown = sorted(n for n in names if n not in render_pkg.LAYOUT_NAMES)
    if unknown:
        raise ValueError(
            f"unknown layout(s): {', '.join(unknown)}; "
            f"choose from {', '.join(render_pkg.LAYOUT_NAMES)}"
        )
    if not names:
        raise ValueError("no layouts selected")
    return [n for n in render_pkg.LAYOUT_NAMES if n in names]


def resolve_subjects(value: str) -> list[str]:
    """What the layouts are drawn over. Same shape as `resolve_layouts`.
    Validated, and returned in SUBJECT_NAMES order rather than the order typed,
    so the language file is always written before the project one."""
    if value.strip() == "all":
        return list(render_pkg.SUBJECT_NAMES)
    names = {n.strip() for n in value.split(",") if n.strip()}
    unknown = sorted(n for n in names if n not in render_pkg.SUBJECT_NAMES)
    if unknown:
        raise ValueError(
            f"unknown subject(s): {', '.join(unknown)}; "
            f"choose from {', '.join(render_pkg.SUBJECT_NAMES)}"
        )
    if not names:
        raise ValueError("no subjects selected")
    return [n for n in render_pkg.SUBJECT_NAMES if n in names]


MIN_SVG_WIDTH = 200


def resolve_width(value: int | None) -> int | None:
    if value is not None and value < MIN_SVG_WIDTH:
        raise ValueError(f"--svg-width must be at least {MIN_SVG_WIDTH}")
    return value


def resolve_rows(value: int | None) -> int | None:
    """0 means every row, so only a negative is wrong. None leaves each layout
    its own default, as an unset --svg-width does."""
    if value is not None and value < 0:
        raise ValueError("--svg-rows must be 0 or more (0 for every row)")
    return value


# Every file this tool writes carries the prefix, whatever the basename, so
# `rm cw-*` clears the output directory and leaves everything else alone. It
# lives here and not in the default `--basename`. A basename is the user's to
# change, and the SVG layouts never read one anyway.
FILENAME_PREFIX = "cw-"

# Both subjects are named in the file. Language is only the default of `--by`,
# not a lesser variant of it, and an unmarked stem beside a marked one reads as
# the default only to someone who already knows there is an axis. Formats with
# no subject at all pass `by=None` and keep their plain stem.
SUBJECT_SUFFIX = {"language": "-languages", "project": "-projects"}


def output_path(
    out_dir: Path,
    basename: str,
    fmt: render_pkg.Format,
    layout: str | None = None,
    by: str | None = None,
) -> Path:
    """The layout is the stem and the subject suffixes it, so every
    combination gets its own file."""
    stem = layout or fmt.filename_stem or basename
    stem += SUBJECT_SUFFIX.get(by or "", "")
    return out_dir / f"{FILENAME_PREFIX}{stem}{fmt.extension}"


def main(argv: list[str] | None = None, use_config_cli: bool = True) -> int:
    """Run one pass and return the exit status.

    `use_config_cli=False` ignores the config's [cli] table, so a caller that
    must write the same output on every machine gets the shipped defaults
    whatever the reader prefers. scripts/gallery is the only such caller.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        ensure_cloc()
        config = load_config(args.config, cache=args.cache)
        if use_config_cli and config.cli:
            # The first pass was only ever for --config. Re-parse with the
            # config's values as defaults. Argparse skips a default whenever
            # the flag appears on the line, so the precedence rule needs no
            # merge of its own.
            parser.set_defaults(**config.cli)
            args = parser.parse_args(argv)
        formats = resolve_formats(args.format)
        sections = resolve_sections(args.sections)
        layouts = resolve_layouts(args.layout)
        subjects = resolve_subjects(args.by)
        svg_width = resolve_width(args.svg_width)
        svg_rows = resolve_rows(args.svg_rows)
    except (ClocMissing, ConfigError, ValueError) as exc:
        print(f"clocwork: {exc}", file=sys.stderr)
        return 2

    visibility = resolve_visibility(args)
    specs, unmatched = filter_projects(config.projects, args.only, visibility)
    for name in unmatched:
        print(f"clocwork: no project matches --only {name!r}", file=sys.stderr)
    if not specs:
        print("clocwork: nothing to count", file=sys.stderr)
        if not args.only and visibility != "all" and config.projects:
            other = "--all" if visibility == "private" else "--private or --all"
            print(f"clocwork: no {visibility} projects; try {other}", file=sys.stderr)
        return 2

    # --stdout must keep stdout clean for piping, so progress goes to stderr.
    # A first clone is the slowest thing this program does, so it gets its own
    # word rather than sitting silently under "counting".
    def progress(spec: ProjectSpec) -> None:
        verb = "syncing" if spec.is_remote else "counting"
        print(f"  {verb} {spec.name}...", file=sys.stderr)

    reports = collect_all(
        specs,
        timeout=args.timeout,
        on_progress=None if args.quiet else progress,
        fetch=args.fetch,
    )

    if masking(args):
        reports = mask_private(
            specs,
            reports,
            args.mask or config.mask_label,
            each=args.mask_each,
        )

    report = Report(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        projects=reports,
        cloc_version=cloc_version(),
        sort_key=args.sort,
    )

    if args.stdout:
        print(
            render_pkg.render(
                args.stdout,
                report,
                detail=args.detail,
                sections=sections,
                layout=layouts[0],
                width=svg_width,
                by=subjects[0],
                rows=svg_rows,
                title=args.svg_title,
                subtitle=args.svg_subtitle,
            )
        )
    else:
        # A relative path in [cli] out already resolved against the config
        # file, and so does this default, so the flag and the config key agree
        # about where out/ is. root and cache resolve the same way. Only a
        # typed --out follows the working directory, because that is where
        # you typed it.
        out_dir = (
            Path(args.out).expanduser()
            if args.out
            else config.source.parent / DEFAULT_OUT
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in formats:
            fmt = render_pkg.get(name)
            # One file per format. The SVG writes one per layout and subject.
            draws = (
                [(layout, by) for layout in layouts for by in subjects]
                if "layout" in fmt.options
                else [(None, None)]
            )
            for layout, by in draws:
                target = output_path(out_dir, args.basename, fmt, layout, by)
                target.write_text(
                    render_pkg.render(
                        name,
                        report,
                        detail=args.detail,
                        sections=sections,
                        layout=layout,
                        width=svg_width,
                        by=by,
                        rows=svg_rows,
                        title=args.svg_title,
                        subtitle=args.svg_subtitle,
                    ),
                    encoding="utf-8",
                )
                if not args.quiet:
                    print(f"  wrote {target}", file=sys.stderr)
        if not args.quiet:
            print(render_pkg.render("txt", report, detail=False, sections=sections))

    for project in report.failures:
        print(
            f"clocwork: skipped {project.name} ({project.path}): {project.error}",
            file=sys.stderr,
        )

    if not report.counted:
        print("clocwork: every project failed", file=sys.stderr)
        return 2
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
