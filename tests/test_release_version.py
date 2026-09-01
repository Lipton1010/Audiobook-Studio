import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_app_and_both_installers_share_one_version(self):
        app_version = (ROOT / "app" / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(app_version, r"^\d+\.\d+\.\d+$")
        for relative in (
            "install/AudiobookStudio.iss",
            "install/AudiobookStudio_Patch.iss",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            match = re.search(r'^#define MyAppVersion "([^"]+)"$', text, re.MULTILINE)
            self.assertIsNotNone(match, relative)
            self.assertEqual(match.group(1), app_version, relative)

    def test_canonical_builder_has_a_patch_mode(self):
        builder = (ROOT / "install" / "build_installer.bat").read_text(
            encoding="utf-8"
        )
        self.assertIn('if /I "%BUILD_KIND%"=="patch"', builder)
        self.assertIn('set "ISS_NAME=AudiobookStudio_Patch.iss"', builder)


if __name__ == "__main__":
    unittest.main()
