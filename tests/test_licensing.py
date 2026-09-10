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


# The repository root is named rather than walked. It also holds README.md,
# LICENSE, EXCEPTION.md and pyproject.toml, none of which takes a comment
# header, so adding a file here has to be as deliberate as adding one to the
# root was.
ROOT_FILES = ("action.yml",)


def sources() -> list[Path]:
    """Every file the wheel and the sdist carry, plus bin/, scripts/ and action.yml.

    bin/ and scripts/ are walked instead of named, so the next script added to
    either is covered without anyone remembering to list it.
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
    return [*found, *scripts, *(ROOT / name for name in ROOT_FILES)]


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
        self.assertEqual(project["license-files"], ["LICENSE", "EXCEPTION.md"])
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertTrue((ROOT / "EXCEPTION.md").is_file())

    def test_the_licence_file_holds_the_gpl_and_nothing_else(self):
        """GitHub matches LICENSE against the licence texts it knows, whole.

        A notice at the top is a few hundred words the GPL does not have, which
        is enough to drop the match below the threshold, and the repository
        then shows no licence at all. The section 7 additional permission
        therefore lives in EXCEPTION.md, and this file stays verbatim.
        """
        licence = (ROOT / "LICENSE").read_text()
        self.assertEqual(
            licence.strip().splitlines()[0].strip(), "GNU GENERAL PUBLIC LICENSE"
        )
        exception = (ROOT / "EXCEPTION.md").read_text()
        self.assertIn("section 7", exception)
        self.assertNotIn("special exception", licence)


if __name__ == "__main__":
    unittest.main()
