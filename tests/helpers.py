# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared fixtures for the test suite."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clocwork.model import LangCount, ProjectReport, Report

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def sample_report(
    with_failure: bool = False, generated_at: str = "2026-01-01 00:00 UTC"
) -> Report:
    alpha = ProjectReport(
        name="alpha",
        path="/tmp/alpha",
        # alpha carries a url and beta does not, so both branches of the
        # "name becomes a link" rendering are exercised.
        url="https://example.com/alpha",
        branch="main",
        commit="abc1234",
        languages={
            "Go": LangCount(files=10, blank=100, comment=50, code=1000),
            "JSON": LangCount(files=2, blank=0, comment=0, code=400),
        },
    )
    beta = ProjectReport(
        name="beta",
        path="/tmp/beta",
        languages={
            "TypeScript": LangCount(files=5, blank=40, comment=20, code=600),
            "Go": LangCount(files=1, blank=5, comment=2, code=50),
        },
    )
    projects = [alpha, beta]
    if with_failure:
        projects.append(
            ProjectReport(name="gamma", path="/tmp/gamma", error="directory not found")
        )
    return Report(generated_at=generated_at, projects=projects,
                  cloc_version="2.10")
