# SPDX-FileCopyrightText: 2026 Wojciech Polak
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every source file says what it is licensed under, and says the same thing.

A header is easy to forget on a new file, and one file without it is exactly
the file someone copies out of the repo.
"""

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = "GPL-3.0-or-later"
HEADER = (
    "# SPDX-FileCopyrightText: 2026 Wojciech Polak\n"
    f"# SPDX-License-Identifier: {EXPECTED}\n"
)


def sources() -> list[Path]:
    """Every file the wheel and the sdist carry, plus bin/ and scripts/.

    Those two are walked instead of named, so the next script added to either
    is covered without anyone remembering to list it.
    """
    found = [
        path
        for directory in ("clocwork", "tests")
        for path in sorted((ROOT / directory).rglob("*.py"))
    ]
    scripts = [
        path
        for directory in ("bin", "scripts")
        for path in sorted((ROOT / directory).iterdir())
        if path.is_file()
    ]
    return [*found, *scripts]


class TestLicensing(unittest.TestCase):
    def test_every_source_file_carries_the_spdx_header(self):
        for path in sources():
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text()
                self.assertIn(HEADER, text)
                # Under the shebang where there is one, first line otherwise.
                # A header buried below the imports is one nobody reads.
                self.assertLess(text.index(HEADER), 40)

    def test_the_headers_agree_with_the_packaged_licence(self):
        with open(ROOT / "pyproject.toml", "rb") as handle:
            project = tomllib.load(handle)["project"]
        self.assertEqual(project["license"], EXPECTED)
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertTrue((ROOT / "LICENSE").is_file())


if __name__ == "__main__":
    unittest.main()
