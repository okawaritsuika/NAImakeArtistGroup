import json
import tempfile
import unittest
from pathlib import Path

from arca_chrome_extension import (
    ArcaChromeExtensionError,
    EXTENSION_ASSETS,
    MAX_COOKIE_VALUE_LENGTH,
    MAX_EXTENSION_COOKIES,
    extension_payload_to_cookie_jar,
    install_arca_session_bridge,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "static" / "arca_session_bridge"


class ChromeExtensionAssetTest(unittest.TestCase):
    def test_manifest_uses_only_bounded_mv3_permissions(self):
        manifest = json.loads((ASSET_DIR / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["permissions"], ["cookies"])
        self.assertEqual(set(manifest["host_permissions"]), {
            "https://arca.live/*",
            "https://*.arca.live/*",
            "http://127.0.0.1/*",
        })
        serialized = json.dumps(manifest)
        self.assertNotIn("<all_urls>", serialized)
        self.assertNotIn("tabs", manifest["permissions"])
        self.assertNotIn("content_scripts", manifest)

    def test_popup_reads_arca_cookies_and_sends_only_to_local_bridge(self):
        script = (ASSET_DIR / "popup.js").read_text(encoding="utf-8")

        self.assertIn('chrome.cookies.getAll({ domain: "arca.live" })', script)
        self.assertIn('http://127.0.0.1:5001/api/arca-styles/browser-session/extension', script)
        self.assertIn('"X-Arca-Session-Bridge": "1"', script)
        for marker in ("console.", "localStorage", "sessionStorage", "chrome.storage"):
            self.assertNotIn(marker, script)


class ExtensionCookiePayloadTest(unittest.TestCase):
    @staticmethod
    def cookie(domain=".arca.live", name="session", value="secret", **changes):
        result = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": "/",
            "secure": True,
        }
        result.update(changes)
        return result

    def test_keeps_only_arca_domains_without_exposing_values(self):
        jar = extension_payload_to_cookie_jar({"cookies": [
            self.cookie(),
            self.cookie(domain="images.arca.live", name="image-session", value="image-secret"),
            self.cookie(domain="evil-arca.live", name="unrelated", value="other-secret"),
            self.cookie(domain="example.com", name="external", value="external-secret"),
        ]})

        self.assertEqual(
            {(cookie.domain, cookie.name) for cookie in jar},
            {(".arca.live", "session"), ("images.arca.live", "image-session")},
        )

    def test_rejects_oversized_cookie_counts_and_values_safely(self):
        with self.assertRaises(ArcaChromeExtensionError):
            extension_payload_to_cookie_jar({
                "cookies": [self.cookie(name=f"cookie-{index}") for index in range(MAX_EXTENSION_COOKIES + 1)],
            })

        secret = "never-show-" + "x" * MAX_COOKIE_VALUE_LENGTH
        with self.assertRaises(ArcaChromeExtensionError) as raised:
            extension_payload_to_cookie_jar({"cookies": [self.cookie(value=secret)]})
        self.assertNotIn(secret, str(raised.exception))

    def test_rejects_payloads_without_an_arca_cookie(self):
        with self.assertRaises(ArcaChromeExtensionError):
            extension_payload_to_cookie_jar({"cookies": [self.cookie(domain="notarca.live")]})


class ExtensionInstallTest(unittest.TestCase):
    def test_copies_only_allowlisted_assets_then_opens_persistent_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for name in EXTENSION_ASSETS:
                (source / name).write_text(f"asset:{name}", encoding="utf-8")
            (source / "not-allowed.txt").write_text("do not copy", encoding="utf-8")
            opened = []

            destination = install_arca_session_bridge(
                root / "data",
                source_dir=source,
                opener=opened.append,
            )

            self.assertEqual(destination, (root / "data" / "arca_session_bridge").resolve())
            self.assertEqual({path.name for path in destination.iterdir()}, set(EXTENSION_ASSETS))
            self.assertEqual(opened, [destination])
            for name in EXTENSION_ASSETS:
                self.assertEqual((destination / name).read_text(encoding="utf-8"), f"asset:{name}")

    def test_missing_asset_does_not_open_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            opened = []

            with self.assertRaises(ArcaChromeExtensionError):
                install_arca_session_bridge(root / "data", source_dir=source, opener=opened.append)

            self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
