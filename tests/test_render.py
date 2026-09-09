# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

import colorsys
import itertools
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from clocwork import __url__
from clocwork import render as render_pkg
from clocwork.render import svg
from clocwork.render.svg import banner as banner_layout
from clocwork.render.svg import bar as bar_layout
from clocwork.render.svg import bars as bars_layout
from clocwork.render.svg import card as card_layout
from clocwork.render.svg import donut as donut_layout
from clocwork.render.svg import strip as strip_layout
from tests.helpers import sample_report

NS = "{http://www.w3.org/2000/svg}"


def languages_report(count: int, code=lambda i: 100 - i):
    """A report with `count` languages, largest first."""
    from clocwork.model import LangCount, ProjectReport, Report

    return Report(
        generated_at="2026-01-01 00:00 UTC",
        projects=[
            ProjectReport(
                name="p",
                path="/p",
                languages={
                    f"Lang{i}": LangCount(1, 1, 1, code(i)) for i in range(count)
                },
            )
        ],
    )


def attr(element: ET.Element, name: str) -> str:
    """`Element.get` is Optional; every attribute read below is a required one."""
    value = element.get(name)
    if value is None:
        raise AssertionError(f"<{element.tag}> is missing the {name!r} attribute")
    return value


class TestHelpers(unittest.TestCase):
    def test_group_digits(self):
        self.assertEqual(render_pkg.group_digits(1234567), "1 234 567")
        self.assertEqual(render_pkg.group_digits(42), "42")

    def test_humanize(self):
        self.assertEqual(render_pkg.humanize(999), "999")
        self.assertEqual(render_pkg.humanize(1500), "1.5k")
        self.assertEqual(render_pkg.humanize(127173), "127k")
        self.assertEqual(render_pkg.humanize(2_400_000), "2.4M")

    def test_percent_handles_empty_report(self):
        self.assertEqual(render_pkg.percent(5, 0), 0.0)

    def test_color_is_stable_for_unknown_languages(self):
        self.assertEqual(
            render_pkg.color_for("Brainfuck"), render_pkg.color_for("Brainfuck")
        )
        self.assertEqual(render_pkg.color_for("Go"), "#00add8")


def hue_of(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0]


def distance(first: str, second: str) -> float:
    """Plain RGB distance, enough to catch two languages painted alike."""
    return sum(
        (int(first[i : i + 2], 16) - int(second[i : i + 2], 16)) ** 2 for i in (1, 3, 5)
    ) ** 0.5


class TestPalette(unittest.TestCase):
    """Language colours have to survive both backgrounds without losing the
    identity linguist gave them."""

    def test_contrast_ratio_endpoints(self):
        self.assertAlmostEqual(
            render_pkg.contrast_ratio("#ffffff", "#000000"), 21.0, places=2
        )
        self.assertAlmostEqual(render_pkg.contrast_ratio("#3572a5", "#3572a5"), 1.0)

    def test_the_light_palette_is_linguist_untouched(self):
        for language, color in render_pkg.LANGUAGE_COLORS.items():
            with self.subTest(language=language):
                self.assertEqual(render_pkg.color_for(language), color)

    def test_every_language_clears_the_floor_on_the_dark_card(self):
        for language in render_pkg.LANGUAGE_COLORS:
            with self.subTest(language=language):
                ratio = render_pkg.contrast_ratio(
                    render_pkg.color_for(language, dark=True), render_pkg.DARK_BG
                )
                self.assertGreaterEqual(ratio, render_pkg.CONTRAST_FLOOR)

    def test_hashed_colours_clear_the_floor_in_both_themes(self):
        # The hue hash has one fixed lightness, which fails on white for the
        # yellow-greens and on the card for the reds and blues. Unlike the
        # table, it has no identity to protect, so both ends get fitted.
        for name in ("Zig", "Nim", "Awk", "Prolog", "COBOL", "Odin", "Io", "Raku"):
            with self.subTest(language=name):
                for dark, background in (
                    (False, render_pkg.LIGHT_BG),
                    (True, render_pkg.DARK_BG),
                ):
                    ratio = render_pkg.contrast_ratio(
                        render_pkg.color_for(name, dark=dark), background
                    )
                    self.assertGreaterEqual(ratio, render_pkg.CONTRAST_FLOOR)

    def test_fitting_keeps_the_hue(self):
        # Lua at #000080 is the card background; it comes back navy, not grey.
        lit = render_pkg.color_for("Lua", dark=True)
        self.assertNotEqual(lit, render_pkg.LANGUAGE_COLORS["Lua"])
        self.assertAlmostEqual(
            hue_of(lit), hue_of(render_pkg.LANGUAGE_COLORS["Lua"]), places=2
        )

    def test_dark_colours_stay_apart(self):
        # Lightening pulls colours towards each other. The shipped light table
        # is itself 19 apart at its closest (Elixir/Haskell), so the floor here
        # is what the derivation costs, not a target it aims for.
        colors = {
            language: render_pkg.color_for(language, dark=True)
            for language in render_pkg.LANGUAGE_COLORS
        }
        # Bourne Shell and make each share a colour with an alias on purpose.
        unique = sorted(set(colors.values()))
        for index, first in enumerate(unique):
            for second in unique[index + 1 :]:
                self.assertGreaterEqual(
                    distance(first, second), 15, f"{first} and {second}"
                )

    def test_hashed_hues_do_not_bunch_up(self):
        # The sum-of-characters hash this replaced put six of these names in
        # the greens, which nobody can tell apart once a whole chart is hashed.
        names = [
            "DUD", "RetroFlops", "Magic Link SSO", "gLifestream", "Time Tracker",
            "Cheetah News", "On This Day", "dproxy", "Anubis", "YACT", "wcomp",
            "WebXiangpianpu", "Daily Echoes", "clocwork",
        ]
        hues = sorted(render_pkg._hue(name) for name in names)
        gaps = [b - a for a, b in itertools.pairwise(hues)]
        gaps.append(360 - hues[-1] + hues[0])
        self.assertGreaterEqual(min(gaps), 5)

    def test_the_palette_backgrounds_match_the_two_stylesheets(self):
        from clocwork.render import html

        for stylesheet in (html.STYLE, svg.STYLE):
            self.assertIn(render_pkg.DARK_BG, stylesheet)
            self.assertIn(render_pkg.LIGHT_BG, stylesheet)

    def test_class_names_are_numbered_not_slugged(self):
        # `C` and `C#` would slug to the same identifier.
        names = render_pkg.palette(["C", "C#", "Vuejs Component"])
        self.assertEqual(len(set(names.values())), 3)
        self.assertTrue(all(cls.isalnum() for cls in names.values()))


class TestRegistry(unittest.TestCase):
    def test_every_named_format_resolves(self):
        for name in render_pkg.FORMAT_NAMES:
            self.assertTrue(render_pkg.get(name).extension.startswith("."))

    def test_unknown_format(self):
        with self.assertRaises(KeyError):
            render_pkg.get("pdf")

    def test_the_svg_options_match_what_its_render_accepts(self):
        # `render` drops an option that the signature takes and the frozenset
        # does not name, and says nothing about it. Comparing the two beats
        # trusting whoever adds the next one to edit both.
        import inspect

        accepted = set(inspect.signature(svg.render).parameters) - {
            "report", "detail", "sections",
        }
        self.assertEqual(render_pkg.get("svg").options, accepted)

    def test_svg_gets_its_own_filename(self):
        self.assertEqual(render_pkg.get("svg").filename_stem, "card")
        self.assertIsNone(render_pkg.get("txt").filename_stem)


class TestAllFormats(unittest.TestCase):
    def test_each_format_reports_projects_and_the_grand_total(self):
        report = sample_report()
        for name in render_pkg.FORMAT_NAMES:
            with self.subTest(format=name):
                output = render_pkg.render(name, report)
                self.assertTrue(output.strip())
                self.assertIn("2 050", output)  # grand total, grouped
                if name != "svg":  # by default the card lists languages
                    self.assertIn("alpha", output)
        # ...but the SVG drawn by project does name them.
        self.assertIn("alpha", render_pkg.render("svg", report, by="project"))

    def test_detail_adds_the_per_project_breakdown(self):
        report = sample_report()
        for name in ("txt", "md", "html"):
            with self.subTest(format=name):
                brief = render_pkg.render(name, report, detail=False)
                full = render_pkg.render(name, report, detail=True)
                self.assertGreater(len(full), len(brief))

    def test_failures_are_surfaced(self):
        report = sample_report(with_failure=True)
        for name in ("txt", "md", "html"):
            with self.subTest(format=name):
                output = render_pkg.render(name, report, detail=False)
                self.assertIn("gamma", output)

    def test_empty_report_does_not_crash(self):
        from clocwork.model import Report

        empty = Report(generated_at="now", projects=[])
        for name in render_pkg.FORMAT_NAMES:
            with self.subTest(format=name):
                self.assertTrue(render_pkg.render(name, empty).strip())


# Each format spells its headings its own way; the pair is what matters.
HEADINGS = {
    "txt": ("By project", "By language"),
    "md": ("## By project", "## By language"),
    "html": ("<h2>By project</h2>", "<h2>By language</h2>"),
}


class TestSections(unittest.TestCase):
    """--sections picks summary tables. It is presentation only. Whichever
    table survives holds the numbers it would have held in a full run."""

    def test_both_tables_by_default(self):
        report = sample_report()
        for name, (project, language) in HEADINGS.items():
            with self.subTest(format=name):
                output = render_pkg.render(name, report)
                self.assertIn(project, output)
                self.assertIn(language, output)

    def test_projects_come_before_languages_everywhere(self):
        """One order across the three text formats, so a reader moving between
        them finds the tables where the last one had them."""
        report = sample_report()
        for name, (project, language) in HEADINGS.items():
            with self.subTest(format=name):
                output = render_pkg.render(name, report)
                self.assertLess(output.index(project), output.index(language))

    def test_selecting_one_drops_the_other(self):
        report = sample_report()
        for name, (project, language) in HEADINGS.items():
            with self.subTest(format=name):
                only_language = render_pkg.render(name, report, sections=["language"])
                self.assertIn(language, only_language)
                self.assertNotIn(project, only_language)

                only_project = render_pkg.render(name, report, sections=["project"])
                self.assertIn(project, only_project)
                self.assertNotIn(language, only_project)

    def test_the_grand_total_survives_either_way(self):
        report = sample_report()
        for name in HEADINGS:
            for sections in (["project"], ["language"], ["project", "language"]):
                with self.subTest(format=name, sections=sections):
                    output = render_pkg.render(name, report, sections=sections)
                    self.assertIn("2 050", output)

    def test_detail_is_independent_of_the_summary_tables(self):
        report = sample_report()
        output = render_pkg.render("md", report, detail=True, sections=["language"])
        self.assertIn("## Per project, per language", output)
        self.assertNotIn("## By project", output)

    def test_the_card_ignores_the_setting(self):
        report = sample_report()
        full = render_pkg.render("svg", report)
        for sections in (["project"], ["language"]):
            with self.subTest(sections=sections):
                self.assertEqual(
                    render_pkg.render("svg", report, sections=sections), full
                )


class TestTxt(unittest.TestCase):
    def test_table_columns_line_up(self):
        from clocwork.render.txt import table

        lines = table(["A", "Long header"], [["x", "1"]], "lr")
        self.assertEqual(len({len(line) for line in lines}), 1)

    def test_shares_add_up(self):
        output = render_pkg.render("txt", sample_report())
        self.assertEqual(output.count("100.0%"), 2)  # one per summary table

    def test_one_section_leaves_one_summary_table(self):
        output = render_pkg.render("txt", sample_report(), sections=["language"])
        self.assertEqual(output.count("100.0%"), 1)


class TestMarkdown(unittest.TestCase):
    def test_tables_have_separator_rows(self):
        output = render_pkg.render("md", sample_report())
        self.assertIn("| --- | ---:", output)

    def test_detail_uses_collapsible_sections(self):
        output = render_pkg.render("md", sample_report(), detail=True)
        self.assertIn("<details>", output)
        self.assertEqual(output.count("<details>"), output.count("</details>"))

    def test_a_url_turns_the_project_name_into_a_link(self):
        output = render_pkg.render("md", sample_report(), detail=True)
        self.assertIn("| [alpha](https://example.com/alpha) |", output)
        # A <summary> is HTML, so the link there is an anchor, not Markdown.
        self.assertIn('<summary><a href="https://example.com/alpha">alpha</a>', output)

    def test_a_project_without_a_url_stays_plain_text(self):
        output = render_pkg.render("md", sample_report())
        self.assertIn("| beta |", output)
        self.assertNotIn("[beta](", output)


class TestHtml(unittest.TestCase):
    def test_is_self_contained(self):
        output = render_pkg.render("html", sample_report())
        self.assertIn("<style>", output)
        self.assertNotIn("http://", output)
        self.assertNotIn("<script", output)

    def test_defines_a_dark_palette(self):
        output = render_pkg.render("html", sample_report())
        self.assertIn("prefers-color-scheme: dark", output)

    def test_language_colours_are_theme_aware_variables(self):
        output = render_pkg.render("html", sample_report(), detail=True)
        self.assertIn(":root{--l0:", output)
        self.assertIn("@media (prefers-color-scheme: dark){:root{--l0:", output)
        # Every dot and bar segment reads the variable rather than a literal, so
        # one declaration serves both themes.
        self.assertIn("background:var(--l0,", output)
        self.assertNotIn("background:#", output)

    def test_a_dark_only_language_carries_both_colours(self):
        # Nothing in the sample report moves between themes, so ask for one
        # that does. Lua's navy is the card background until `_fit` lifts it.
        from clocwork.model import LangCount, ProjectReport, Report

        report = Report(
            generated_at="now",
            projects=[
                ProjectReport(
                    name="lua", path="/p", languages={"Lua": LangCount(1, 1, 1, 1)}
                )
            ],
        )
        output = render_pkg.render("html", report)
        self.assertIn(f"--l0:{render_pkg.color_for('Lua')};", output)
        self.assertIn(f"--l0:{render_pkg.color_for('Lua', dark=True)};", output)

    def test_a_url_turns_the_project_name_into_a_link(self):
        output = render_pkg.render("html", sample_report(), detail=True)
        self.assertIn('<a href="https://example.com/alpha">alpha</a>', output)
        self.assertNotIn('>beta</a>', output)

    def test_a_url_is_escaped_into_the_href(self):
        from clocwork.model import ProjectReport, Report

        report = Report(
            generated_at="now",
            projects=[
                ProjectReport(
                    name="q&a",
                    path="/tmp/q",
                    url="https://example.com/a?x=1&y=2",
                    languages=sample_report().counted[0].languages,
                )
            ],
        )
        output = render_pkg.render("html", report)
        self.assertIn(
            '<a href="https://example.com/a?x=1&amp;y=2">q&amp;a</a>', output
        )

    def test_escapes_project_names(self):
        from clocwork.model import LangCount, ProjectReport, Report

        report = Report(
            generated_at="now",
            projects=[
                ProjectReport(
                    name="<script>x</script>",
                    path="/p",
                    languages={"Go": LangCount(1, 1, 1, 1)},
                )
            ],
        )
        output = render_pkg.render("html", report)
        self.assertNotIn("<script>x", output)
        self.assertIn("&lt;script&gt;", output)


class TestSvg(unittest.TestCase):
    """Invariants every layout has to keep, whatever it draws."""

    def cards(self) -> list[tuple[str, str, str]]:
        """Every shape over every subject. The invariants hold for all of them."""
        return [
            (layout, by, render_pkg.render("svg", sample_report(), layout=layout,
                                           by=by))
            for layout in render_pkg.LAYOUT_NAMES
            for by in render_pkg.SUBJECT_NAMES
        ]

    def test_is_well_formed_xml(self):
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                self.assertTrue(ET.fromstring(output).tag.endswith("svg"))

    def test_carries_explicit_dimensions(self):
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                root = ET.fromstring(output)
                self.assertTrue(int(attr(root, "width")) > 0)
                self.assertTrue(int(attr(root, "height")) > 0)

    def test_the_width_can_be_overridden(self):
        for layout in render_pkg.LAYOUT_NAMES:
            with self.subTest(layout=layout):
                root = ET.fromstring(
                    render_pkg.render("svg", sample_report(), layout=layout, width=600)
                )
                self.assertEqual(root.get("width"), "600")
                self.assertEqual(attr(root, "viewBox").split()[2], "600")

    def test_unknown_layout_is_rejected(self):
        with self.assertRaises(KeyError):
            render_pkg.render("svg", sample_report(), layout="nope")

    def test_unknown_subject_is_rejected(self):
        with self.assertRaises(KeyError):
            render_pkg.render("svg", sample_report(), by="files")

    def test_no_foreign_object_or_external_refs(self):
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                self.assertNotIn("foreignObject", output)
                self.assertNotIn(
                    "http://", output.replace("http://www.w3.org/2000/svg", "")
                )

    def test_colours_survive_a_stripped_style_block(self):
        # Every drawn element carries a literal fill, so a sanitiser that drops
        # <style> still leaves a readable light-theme picture.
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                root = ET.fromstring(output)
                clipped = {
                    e for clip in root.iter(f"{NS}clipPath") for e in clip.iter()
                }
                for tag in ("rect", "text", "circle", "path"):
                    for element in root.iter(f"{NS}{tag}"):
                        if element in clipped:  # clip shapes are never painted
                            continue
                        self.assertIsNotNone(
                            element.get("fill"), f"{tag} without fill"
                        )

    def test_every_language_element_has_a_class_with_a_dark_rule(self):
        for layout, by, output in self.cards():
            if layout in render_pkg.FRAMELESS_LAYOUTS:
                continue  # no background of their own, so no theme to switch
            with self.subTest(layout=layout, by=by):
                root = ET.fromstring(output)
                style = "".join(next(root.iter(f"{NS}style")).itertext())
                # The shared dark block comes first, the language block last.
                dark = style.split("@media (prefers-color-scheme: dark)")[-1]
                painted = 0
                for tag in ("rect", "circle", "path"):
                    for element in root.iter(f"{NS}{tag}"):
                        cls = element.get("class")
                        if cls is None or not re.fullmatch(r"l\d+", cls):
                            continue
                        painted += 1
                        self.assertIsNotNone(element.get("fill"))
                        self.assertIn(f".{cls} {{ fill:", style)
                        self.assertIn(f".{cls} {{ fill:", dark)
                self.assertTrue(painted, "no language-coloured elements found")

    def test_a_dark_only_language_is_overridden_not_replaced(self):
        from clocwork.model import LangCount, ProjectReport, Report

        report = Report(
            generated_at="now",
            projects=[
                ProjectReport(
                    name="lua", path="/p", languages={"Lua": LangCount(1, 1, 1, 1)}
                )
            ],
        )
        for layout in render_pkg.LAYOUT_NAMES:
            if layout in render_pkg.FRAMELESS_LAYOUTS:
                continue  # covered by the any_bg tests below
            with self.subTest(layout=layout):
                output = render_pkg.render("svg", report, layout=layout)
                # Light stays on the element as a presentation attribute; dark
                # only ever arrives through the stylesheet.
                self.assertIn(f'fill="{render_pkg.color_for("Lua")}"', output)
                self.assertIn(
                    f"fill: {render_pkg.color_for('Lua', dark=True)};", output
                )

    def test_the_frameless_list_matches_what_the_layouts_draw(self):
        # A frame and a theme-aware palette go together. This list names the
        # layouts that get neither, so it must not drift from what they draw.
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                framed = 'class="bg"' in output
                self.assertEqual(
                    framed, layout not in render_pkg.FRAMELESS_LAYOUTS
                )

    def test_the_frameless_layouts_ask_for_no_theme(self):
        # prefers-color-scheme describes the viewer, not the page behind the
        # image. GitHub makes those the same thing. A JetBrains preview does
        # not, rendering light on a dark page. So a layout with no background
        # of its own must not depend on the answer.
        for layout, by, output in self.cards():
            if layout not in render_pkg.FRAMELESS_LAYOUTS:
                continue
            with self.subTest(layout=layout, by=by):
                self.assertNotIn("prefers-color-scheme", output)

    def test_frameless_colours_clear_the_floor_on_both_backgrounds(self):
        # The test that would have caught it. Near-black text sat at 1.13:1
        # on the dark card and passed everything else in this class.
        for layout, by, output in self.cards():
            if layout not in render_pkg.FRAMELESS_LAYOUTS:
                continue
            root = ET.fromstring(output)
            fills = {
                fill
                for tag in ("text", "circle", "rect")
                for element in root.iter(f"{NS}{tag}")
                if (fill := element.get("fill"))
            }
            for fill in fills:
                for background in (render_pkg.LIGHT_BG, render_pkg.DARK_BG):
                    with self.subTest(layout=layout, by=by, fill=fill,
                                      background=background):
                        self.assertGreaterEqual(
                            render_pkg.contrast_ratio(fill, background),
                            render_pkg.CONTRAST_FLOOR,
                        )

    def test_the_style_block_carries_no_markup(self):
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                root = ET.fromstring(output)
                style = "".join(next(root.iter(f"{NS}style")).itertext())
                # Language names never reach the stylesheet, so nothing there
                # needs escaping, and nothing there can close it early.
                self.assertNotIn("<", style)
                self.assertNotIn("&", style)

    def test_every_element_stays_inside_the_canvas(self):
        for layout, by, output in self.cards():
            with self.subTest(layout=layout, by=by):
                root = ET.fromstring(output)
                height = int(attr(root, "height"))
                width = int(attr(root, "width"))
                for text in root.iter(f"{NS}text"):
                    self.assertLess(float(attr(text, "y")), height)
                    self.assertGreater(float(attr(text, "y")), 0)
                    self.assertLessEqual(float(attr(text, "x")), width)
                for circle in root.iter(f"{NS}circle"):
                    self.assertLess(float(attr(circle, "cy")) + 4, height)
                    self.assertGreaterEqual(float(attr(circle, "cy")) - 4, 0)

    def test_an_empty_report_renders_in_every_layout(self):
        from clocwork.model import Report

        empty = Report(generated_at="now", projects=[])
        for layout in render_pkg.LAYOUT_NAMES:
            for by in render_pkg.SUBJECT_NAMES:
                with self.subTest(layout=layout, by=by):
                    output = render_pkg.render("svg", empty, layout=layout, by=by)
                    self.assertTrue(ET.fromstring(output).tag.endswith("svg"))


class TestSvgSubjects(unittest.TestCase):
    """`series` is the only place that knows what a layout is drawn over."""

    def test_languages_are_the_default(self):
        self.assertEqual(
            svg.series(sample_report()),
            [("Go", 1050), ("TypeScript", 600), ("JSON", 400)],
        )

    def test_projects_carry_their_own_totals(self):
        self.assertEqual(
            svg.series(sample_report(), "project"), [("alpha", 1400), ("beta", 650)]
        )

    def test_a_failed_project_is_not_a_row(self):
        labels = [name for name, _ in svg.series(sample_report(True), "project")]
        self.assertNotIn("gamma", labels)

    def test_the_sort_key_reaches_both_subjects(self):
        from dataclasses import replace

        by_name = replace(sample_report(), sort_key="name")
        self.assertEqual(
            [name for name, _ in svg.series(by_name)], ["Go", "JSON", "TypeScript"]
        )
        self.assertEqual(
            [name for name, _ in svg.series(by_name, "project")], ["alpha", "beta"]
        )

    def test_a_masked_project_reaches_the_card_under_its_label(self):
        from clocwork.model import Report, merge_projects

        masked = Report(
            generated_at="now",
            projects=[merge_projects(sample_report().counted, "UNDISCLOSED")],
        )
        output = render_pkg.render("svg", masked, layout="bars", by="project")
        self.assertIn("UNDISCLOSED", output)
        self.assertNotIn("alpha", output)

    def test_a_long_label_gives_way_to_its_value(self):
        from clocwork.model import LangCount, ProjectReport, Report

        long_name = "a-project-with-an-unreasonably-long-name-" * 2
        report = Report(
            generated_at="now",
            projects=[
                ProjectReport(
                    name=long_name,
                    path="/p",
                    languages={"Go": LangCount(1, 1, 1, 100)},
                )
            ],
        )
        # The strip is wide enough to print this name in full, so it gets a
        # width where even one chip does not fit.
        for layout, width in (("card", None), ("bars", None), ("donut", None),
                              ("strip", 300)):
            with self.subTest(layout=layout):
                output = render_pkg.render(
                    "svg", report, layout=layout, width=width, by="project"
                )
                self.assertIn(svg.ELLIPSIS, output)
                self.assertNotIn(f">{long_name}<", output)


class TestSvgRows(unittest.TestCase):
    """`rows` caps the labelled list. It is a shape, not a filter. The
    proportion bar and the donut ring still cover everything counted."""

    LISTING = ("card", "bars", "donut")

    def labels(self, output: str) -> list[str]:
        root = ET.fromstring(output)
        return [t.text or "" for t in root.iter(f"{NS}text")]

    def test_the_default_is_the_registry_default(self):
        report = languages_report(12)
        for layout in self.LISTING:
            with self.subTest(layout=layout):
                default = render_pkg.render("svg", report, layout=layout)
                spelled = render_pkg.render(
                    "svg", report, layout=layout, rows=render_pkg.DEFAULT_ROWS
                )
                self.assertEqual(default, spelled)

    def test_a_raised_cap_labels_more_rows(self):
        report = languages_report(12)
        for layout in self.LISTING:
            with self.subTest(layout=layout):
                listed = render_pkg.render("svg", report, layout=layout, rows=10)
                self.assertIn("Lang9", listed)
                self.assertNotIn(
                    "Lang9", render_pkg.render("svg", report, layout=layout)
                )

    def test_a_lowered_cap_labels_fewer(self):
        report = languages_report(12)
        for layout in self.LISTING:
            with self.subTest(layout=layout):
                listed = render_pkg.render("svg", report, layout=layout, rows=2)
                self.assertIn("Lang0", listed)
                self.assertNotIn("Lang2", listed)

    def test_zero_labels_every_row(self):
        report = languages_report(12)
        for layout in self.LISTING:
            with self.subTest(layout=layout):
                listed = render_pkg.render("svg", report, layout=layout, rows=0)
                for i in range(12):
                    self.assertIn(f"Lang{i}", listed)

    def test_the_total_never_moves(self):
        # The card's bar and the donut's ring cover everything, so a cap
        # changes which rows get a name and nothing else.
        report = languages_report(12)

        def coloured(layout, rows):
            root = ET.fromstring(
                render_pkg.render("svg", report, layout=layout, rows=rows)
            )
            return sum(
                1
                for tag in ("rect", "path")
                for e in root.iter(f"{NS}{tag}")
                if re.fullmatch(r"l\d+", e.get("class") or "")
            )

        for layout in ("card", "donut"):
            with self.subTest(layout=layout):
                self.assertEqual(coloured(layout, 2), coloured(layout, 0))

    def test_the_frameless_layouts_ignore_it(self):
        # `strip` wraps *lines* rather than listing entries, and `bar` has no
        # list at all. Both draw everything already.
        report = languages_report(12)
        for layout in ("strip", "bar"):
            with self.subTest(layout=layout):
                plain = render_pkg.render("svg", report, layout=layout)
                for rows in (0, 2, 40):
                    self.assertEqual(
                        plain,
                        render_pkg.render("svg", report, layout=layout, rows=rows),
                    )

    def test_an_uncapped_donut_legend_stays_on_the_card(self):
        # The legend is centred on the ring, so without a floor a long one
        # would grow off the top edge.
        root = ET.fromstring(
            render_pkg.render("svg", languages_report(20), layout="donut", rows=0)
        )
        height = int(attr(root, "height"))
        for element in root.iter(f"{NS}text"):
            self.assertGreater(float(attr(element, "y")), 0)
            self.assertLess(float(attr(element, "y")), height)
        for circle in root.iter(f"{NS}circle"):
            self.assertGreaterEqual(float(attr(circle, "cy")) - 4, 0)
            self.assertLess(float(attr(circle, "cy")) + 4, height)


class TestEllipsize(unittest.TestCase):
    def test_a_label_that_fits_is_untouched(self):
        self.assertEqual(svg.ellipsize("Go", 12, 500, 200), "Go")

    def test_a_long_label_is_cut_and_marked(self):
        shortened = svg.ellipsize("an extremely long project name", 12, 500, 60)
        self.assertTrue(shortened.endswith(svg.ELLIPSIS))
        self.assertLessEqual(svg.text_width(shortened, 12, 500), 60)

    def test_no_room_at_all_still_returns_something_drawable(self):
        self.assertEqual(svg.ellipsize("Go", 12, 500, 1), svg.ELLIPSIS)


class TestSvgCardLayout(unittest.TestCase):
    """The card is hand-positioned, so guard the spacing that a change could
    silently break."""

    def height(self, report) -> int:
        card = ET.fromstring(render_pkg.render("svg", report, layout="card"))
        return int(attr(card, "height"))

    def test_first_language_row_clears_the_proportion_bar(self):
        bar_bottom = card_layout.BAR_TOP + card_layout.BAR_HEIGHT
        first_dot_top = card_layout.ROWS_TOP + card_layout.ROW_BASELINE_OFFSET - 8
        self.assertGreater(first_dot_top, bar_bottom)

    def test_height_grows_with_the_number_of_languages(self):
        self.assertEqual(
            self.height(languages_report(3)) + card_layout.ROW_HEIGHT,
            self.height(languages_report(4)),
        )
        # The card lists at most DEFAULT_ROWS rows, so it stops growing there.
        self.assertEqual(
            self.height(languages_report(render_pkg.DEFAULT_ROWS)),
            self.height(languages_report(render_pkg.DEFAULT_ROWS + 5)),
        )

    def test_bar_segments_fill_the_track_without_overflowing(self):
        for layout, width in (
            ("card", card_layout.WIDTH - 2 * card_layout.PAD),
            ("bar", bar_layout.WIDTH - 2 * bar_layout.PAD),
            ("banner", banner_layout.WIDTH - 2 * banner_layout.PAD),
        ):
            with self.subTest(layout=layout):
                root = ET.fromstring(
                    render_pkg.render("svg", sample_report(), layout=layout)
                )
                group = next(g for g in root.iter(f"{NS}g") if g.get("id") == "bar")
                segments = list(group.iter(f"{NS}rect"))
                self.assertTrue(segments)
                span = sum(float(attr(r, "width")) for r in segments)
                self.assertAlmostEqual(span, width, 1)


class TestSvgStripLayout(unittest.TestCase):
    """The strip is the only layout that wraps, and it wraps on an estimate."""

    def rows(self, report, width) -> int:
        root = ET.fromstring(
            render_pkg.render("svg", report, layout="strip", width=width)
        )
        return len({attr(t, "y") for t in root.iter(f"{NS}text")})

    def test_a_narrower_strip_wraps_into_more_rows(self):
        report = languages_report(8)
        self.assertGreater(self.rows(report, 300), self.rows(report, 900))

    def test_height_follows_the_row_count(self):
        report = languages_report(8)
        for width in (300, 900):
            with self.subTest(width=width):
                root = ET.fromstring(
                    render_pkg.render("svg", report, layout="strip", width=width)
                )
                self.assertEqual(
                    int(attr(root, "height")),
                    2 * strip_layout.PAD
                    + self.rows(report, width) * strip_layout.LINE_HEIGHT,
                )

    def test_chips_stay_inside_the_canvas(self):
        # Measured the same way the layout measures them. If the estimate is
        # wrong the picture is wrong, so the test uses the estimate too.
        width = 420
        root = ET.fromstring(
            render_pkg.render("svg", languages_report(12), layout="strip", width=width)
        )
        for element in root.iter(f"{NS}text"):
            size = float(attr(element, "font-size"))
            weight = int(attr(element, "font-weight"))
            right = float(attr(element, "x")) + svg.text_width(
                element.text or "", size, weight
            )
            self.assertLessEqual(right, width - strip_layout.PAD + 1)

    def test_the_overflow_chip_replaces_the_rows_that_do_not_fit(self):
        output = render_pkg.render(
            "svg", languages_report(60), layout="strip", width=420
        )
        root = ET.fromstring(output)
        rows = len({attr(t, "y") for t in root.iter(f"{NS}text")})
        self.assertLessEqual(rows, strip_layout.MAX_ROWS)
        self.assertRegex(output, r"\+\d+ more")


class TestSvgOtherLayouts(unittest.TestCase):
    def test_the_bar_keeps_one_height_whatever_the_language_count(self):
        heights = {
            int(
                attr(
                    ET.fromstring(
                        render_pkg.render("svg", languages_report(n), layout="bar")
                    ),
                    "height",
                )
            )
            for n in (1, 3, 20)
        }
        self.assertEqual(heights, {bar_layout.HEIGHT})

    def test_no_ranked_bar_is_wider_than_the_row(self):
        root = ET.fromstring(
            render_pkg.render("svg", sample_report(), layout="bars")
        )
        inner = bars_layout.WIDTH - 2 * bars_layout.PAD
        painted = [
            r
            for r in root.iter(f"{NS}rect")
            if (r.get("class") or "").startswith("l")
        ]
        self.assertTrue(painted)
        for rect in painted:
            self.assertLessEqual(float(attr(rect, "width")), inner)
        # The largest language fills its row, so the ranking reads as a ranking.
        self.assertAlmostEqual(float(attr(painted[0], "width")), inner, 1)

    def test_ranked_rows_stop_at_the_top_languages(self):
        def height(count):
            return int(
                attr(
                    ET.fromstring(
                        render_pkg.render("svg", languages_report(count), layout="bars")
                    ),
                    "height",
                )
            )

        self.assertEqual(height(3) + bars_layout.ROW_HEIGHT, height(4))
        self.assertEqual(
            height(render_pkg.DEFAULT_ROWS), height(render_pkg.DEFAULT_ROWS + 5)
        )

    def test_the_donut_draws_a_sector_for_every_language(self):
        root = ET.fromstring(
            render_pkg.render("svg", sample_report(), layout="donut")
        )
        classes = {attr(p, "class") for p in root.iter(f"{NS}path")}
        self.assertEqual(classes, {"l0", "l1", "l2"})

    def test_a_single_language_donut_is_split_rather_than_degenerate(self):
        root = ET.fromstring(
            render_pkg.render("svg", languages_report(1), layout="donut")
        )
        paths = list(root.iter(f"{NS}path"))
        # One full turn cannot be one arc, because the end point would be the
        # start.
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(
            attr(paths[0], "d").split("A")[0], attr(paths[1], "d").split("A")[0]
        )

    def test_the_donut_ring_stays_inside_the_card(self):
        root = ET.fromstring(
            render_pkg.render("svg", sample_report(), layout="donut")
        )
        height = int(attr(root, "height"))
        self.assertLess(donut_layout.RING_BOTTOM, height)
        self.assertGreater(donut_layout.INNER_R, 0)

    def test_the_banner_keeps_its_aspect_ratio_at_every_width(self):
        # The one layout whose height comes from its width rather than from
        # how many rows it lists.
        for width in (banner_layout.WIDTH, 900, 640, 200):
            with self.subTest(width=width):
                root = ET.fromstring(
                    render_pkg.render(
                        "svg", sample_report(), layout="banner", width=width
                    )
                )
                self.assertEqual(int(attr(root, "width")), width)
                self.assertEqual(
                    int(attr(root, "height")),
                    round(width * banner_layout.HEIGHT / banner_layout.WIDTH),
                )

    def test_the_banner_ring_clears_the_bar(self):
        self.assertLess(
            banner_layout.CENTER_Y + banner_layout.OUTER_R, banner_layout.BAR_TOP
        )
        self.assertGreater(banner_layout.CENTER_X - banner_layout.OUTER_R,
                           banner_layout.PAD)
        self.assertGreater(banner_layout.INNER_R, 0)

    def test_the_banner_draws_the_headings_it_is_given(self):
        plain = render_pkg.render("svg", sample_report(), layout="banner")
        self.assertNotIn("Grand Designs", plain)
        titled = render_pkg.render(
            "svg", sample_report(), layout="banner",
            title="Grand Designs", subtitle="every line of it",
        )
        self.assertIn("Grand Designs", titled)
        self.assertIn("every line of it", titled)
        # No heading shortens the stack rather than leaving a gap. The card
        # is the same height either way and still names the total.
        self.assertEqual(
            int(attr(ET.fromstring(plain), "height")),
            int(attr(ET.fromstring(titled), "height")),
        )
        self.assertIn("LINES OF CODE", plain)

    def test_a_heading_is_escaped_rather_than_injected(self):
        output = render_pkg.render(
            "svg", sample_report(), layout="banner", title="<script>&"
        )
        self.assertIn("&lt;script&gt;&amp;", output)
        self.assertTrue(ET.fromstring(output).tag.endswith("svg"))

    def test_the_banner_chip_line_is_a_ceiling_not_a_count(self):
        # `rows` caps the chips, but so does the width, so a raised cap adds
        # chips only while they fit. Either way the line never overruns.
        report = languages_report(12)
        room = banner_layout.WIDTH - 2 * banner_layout.PAD
        counts = []
        for rows in (2, 6, 0):
            root = ET.fromstring(
                render_pkg.render("svg", report, layout="banner", rows=rows)
            )
            baseline = banner_layout.CHIPS_BASELINE
            chips = [
                element
                for element in root.iter(f"{NS}text")
                if float(attr(element, "y")) == baseline
            ]
            self.assertTrue(chips)
            last = chips[-1]
            span = float(attr(last, "x")) - banner_layout.PAD + svg.text_width(
                last.text or "", float(attr(last, "font-size"))
            )
            self.assertLessEqual(span, room)
            counts.append(len([c for c in chips if (c.text or "").startswith("Lang")]))
        self.assertLessEqual(counts[0], 2)
        self.assertGreater(counts[1], counts[0])
        self.assertGreaterEqual(counts[2], counts[1])

    def test_the_other_layouts_ignore_the_headings(self):
        # Same contract as `rows` on the frameless pair. Every layout takes
        # the argument so `svg.render` can forward blindly, and only the one
        # with somewhere to put it draws anything.
        report = sample_report()
        for layout in render_pkg.LAYOUT_NAMES:
            if layout == "banner":
                continue
            with self.subTest(layout=layout):
                self.assertEqual(
                    render_pkg.render("svg", report, layout=layout),
                    render_pkg.render(
                        "svg", report, layout=layout, title="T", subtitle="S"
                    ),
                )


class TestUnstamped(unittest.TestCase):
    """`--date none` leaves no stamp. What is left has to read as a sentence
    rather than as one with a hole in it, and the attribution is unaffected:
    dropping the date drops nothing about who produced the numbers."""

    def unstamped(self, fmt: str, **kwargs) -> str:
        return render_pkg.render(fmt, sample_report(generated_at=""), **kwargs)

    def test_txt_drops_the_clause_rather_than_emptying_it(self):
        output = self.unstamped("txt")
        self.assertIn("Generated by clocwork", output)
        self.assertNotIn("Generated:", output)

    def test_markdown_drops_the_clause_rather_than_emptying_it(self):
        self.assertIn(
            f"Generated by [clocwork]({__url__})", self.unstamped("md")
        )

    def test_html_starts_its_meta_line_at_the_attribution(self):
        # No "Generated &middot;" with nothing in front of the separator.
        output = self.unstamped("html")
        self.assertIn(f'<p class="meta"><a href="{__url__}">clocwork</a>', output)
        self.assertNotIn("Generated", output)

    def test_the_signature_is_the_two_names_and_no_separator(self):
        self.assertEqual(
            svg.footer_line(sample_report(generated_at="")), "clocwork · cloc"
        )

    def test_the_signed_layouts_still_carry_it(self):
        for layout in TestAttribution.SIGNED:
            with self.subTest(layout=layout):
                root = ET.fromstring(
                    self.unstamped("svg", layout=layout)
                )
                drawn = " ".join(t.text or "" for t in root.iter(f"{NS}text"))
                self.assertIn("clocwork · cloc", drawn)

    def test_every_format_still_renders(self):
        for name in render_pkg.FORMAT_NAMES:
            with self.subTest(format=name):
                self.assertTrue(self.unstamped(name).strip())


class TestAttribution(unittest.TestCase):
    """Two programs make a report: clocwork draws it, cloc counts the lines.
    Every signed output says both, and the frameless layouts say neither."""

    SIGNED = ("card", "bars", "donut", "banner")
    FRAMELESS = ("strip", "bar")

    def signature(self, layout: str) -> str:
        root = ET.fromstring(
            render_pkg.render("svg", sample_report(), layout=layout)
        )
        return " ".join(t.text or "" for t in root.iter(f"{NS}text"))

    def test_the_framed_layouts_name_both_programs_and_the_date(self):
        for layout in self.SIGNED:
            with self.subTest(layout=layout):
                footer = svg.footer_line(sample_report())
                self.assertIn(footer, self.signature(layout))
                self.assertIn("clocwork", footer)
                self.assertIn("cloc ", footer)
                self.assertIn("2026-01-01", footer)

    def test_the_frameless_layouts_carry_no_signature(self):
        # Deliberate, like the missing frame. They sit under other content.
        for layout in self.FRAMELESS:
            with self.subTest(layout=layout):
                self.assertNotIn("clocwork", self.signature(layout))

    def test_the_signature_fits_inside_the_card(self):
        # Each layout at its own footer size. The banner is two and a half
        # times the width of the other three and sets its footer to match, so
        # one hardcoded size would measure the right string at the wrong size.
        for layout, module in (
            ("card", card_layout),
            ("bars", bars_layout),
            ("donut", donut_layout),
            ("banner", banner_layout),
        ):
            with self.subTest(layout=layout):
                width = svg.text_width(
                    svg.footer_line(sample_report()), module.FOOTER_SIZE
                )
                self.assertLess(width, module.WIDTH - 2 * module.PAD)

    def versioned(self, name: str, version: str) -> re.Pattern:
        """`name version`, whether or not the name is wrapped in a link."""
        return re.compile(
            rf"{re.escape(name)}(\]\([^)]+\)|</a>)? {re.escape(version)}"
        )

    def test_the_text_formats_name_both_programs_with_their_versions(self):
        report = sample_report()
        for fmt in ("txt", "md", "html"):
            with self.subTest(format=fmt):
                output = render_pkg.render(fmt, report)
                self.assertRegex(
                    output, self.versioned("clocwork", report.clocwork_version)
                )
                self.assertRegex(output, self.versioned("cloc", "2.10"))

    def test_markdown_and_html_link_both_programs(self):
        # Either both names carry a link or neither does; one linked and the
        # other not is the imbalance this attribution exists to avoid. TXT and
        # the SVG have nowhere to put a link and so carry none.
        report = sample_report()
        self.assertIn(f"[clocwork]({__url__})", render_pkg.render("md", report))
        self.assertIn(f"[cloc]({render_pkg.CLOC_URL})",
                      render_pkg.render("md", report))
        html = render_pkg.render("html", report)
        self.assertIn(f'<a href="{__url__}">clocwork</a>', html)
        self.assertIn(f'<a href="{render_pkg.CLOC_URL}">cloc</a>', html)
        self.assertNotIn("http", render_pkg.render("txt", report))

    def test_the_packaged_url_matches_the_one_the_reports_link(self):
        # Two spellings of one address drift; the reports link `__url__` and
        # PyPI shows what pyproject says, so they have to agree.
        import tomllib

        root = Path(__file__).resolve().parent.parent
        with open(root / "pyproject.toml", "rb") as handle:
            urls = tomllib.load(handle)["project"]["urls"]
        self.assertEqual(set(urls.values()), {__url__})


if __name__ == "__main__":
    unittest.main()
