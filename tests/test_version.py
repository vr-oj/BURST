import unittest
from pathlib import Path

from buti_app.utils.version import (
    APP_VERSION,
    parse_version,
    render_windows_version_info,
    windows_version_tuple,
)


class VersionTests(unittest.TestCase):
    def test_runtime_version_matches_version_file(self):
        version_file = Path(__file__).parents[1] / "buti_app" / "VERSION"
        self.assertEqual(APP_VERSION, version_file.read_text(encoding="utf-8").strip())

    def test_supported_versions_parse(self):
        self.assertEqual(parse_version("1.2.0"), (1, 2, 0, None, None))
        self.assertEqual(parse_version("2.3.4-beta.5"), (2, 3, 4, "beta", 5))

    def test_invalid_version_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_version("v2.0")

    def test_windows_version_orders_prereleases_before_final(self):
        self.assertEqual(windows_version_tuple("2.3.4-beta.5"), (2, 3, 4, 2005))
        self.assertEqual(windows_version_tuple("2.3.4"), (2, 3, 4, 65535))

    def test_windows_resource_contains_numeric_and_display_versions(self):
        resource = render_windows_version_info("1.2.0")
        self.assertIn("filevers=(1, 2, 0, 65535)", resource)
        self.assertIn("ProductVersion', u'1.2.0'", resource)
        self.assertIn("OriginalFilename', u'BURST.exe'", resource)


if __name__ == "__main__":
    unittest.main()
