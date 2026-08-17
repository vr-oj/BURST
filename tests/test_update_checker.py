import unittest

from buti_app.utils.update_checker import (
    is_version_newer,
    normalized_release_version,
    release_tag_from_url,
    resolve_latest_release,
    version_sort_key,
)


class FakeResponse:
    def __init__(self, final_url):
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def geturl(self):
        return self.final_url


class UpdateCheckerTests(unittest.TestCase):
    def test_normalizes_and_validates_release_tags(self):
        self.assertEqual(normalized_release_version(" v1.3.0 "), "1.3.0")
        self.assertEqual(
            normalized_release_version("1.4.0-rc.2"), "1.4.0-rc.2"
        )
        with self.assertRaises(ValueError):
            normalized_release_version("latest")

    def test_semantic_order_handles_prereleases_and_finals(self):
        self.assertTrue(is_version_newer("v1.3.1", "1.3.0"))
        self.assertTrue(is_version_newer("v1.4.0-beta.1", "1.3.9"))
        self.assertTrue(is_version_newer("v1.4.0", "1.4.0-rc.9"))
        self.assertFalse(is_version_newer("v1.3.0", "1.3.0"))
        self.assertLess(
            version_sort_key("1.4.0-alpha.1"),
            version_sort_key("1.4.0-beta.1"),
        )

    def test_extracts_the_tag_from_github_redirect_url(self):
        self.assertEqual(
            release_tag_from_url(
                "https://github.com/vr-oj/BURST/releases/tag/v1.3.0"
            ),
            "v1.3.0",
        )
        with self.assertRaises(ValueError):
            release_tag_from_url("https://github.com/vr-oj/BURST/releases/latest")

    def test_resolves_latest_release_with_timeout_and_user_agent(self):
        calls = []

        def fake_urlopen(request, *, context, timeout):
            calls.append((request, context, timeout))
            return FakeResponse(
                "https://github.com/vr-oj/BURST/releases/tag/v1.3.1"
            )

        tag, final_url = resolve_latest_release(
            "https://github.com/vr-oj/BURST/releases/latest",
            current_version="1.3.0",
            timeout=2.5,
            urlopen=fake_urlopen,
        )

        self.assertEqual(tag, "v1.3.1")
        self.assertTrue(final_url.endswith("/v1.3.1"))
        self.assertEqual(calls[0][2], 2.5)
        self.assertEqual(calls[0][0].get_header("User-agent"), "BURST/1.3.0")


if __name__ == "__main__":
    unittest.main()
