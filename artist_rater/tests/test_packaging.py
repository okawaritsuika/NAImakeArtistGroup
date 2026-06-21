import tempfile
import unittest
from pathlib import Path

import app


class PackagingTest(unittest.TestCase):
    def test_frozen_app_uses_bundle_for_assets_and_exe_folder_for_user_data(self):
        root = Path(tempfile.mkdtemp())
        resource_dir, data_dir = app.resolve_runtime_paths(
            frozen=True,
            executable=root / "DanbooruArtistRater.exe",
            module_file=root / "bundle" / "app.py",
            bundle_dir=root / "bundle",
        )
        self.assertEqual(resource_dir, root / "bundle")
        self.assertEqual(data_dir, root / "data")

    def test_source_app_keeps_assets_and_data_beside_app_module(self):
        root = Path(tempfile.mkdtemp())
        resource_dir, data_dir = app.resolve_runtime_paths(
            frozen=False,
            executable=root / "python.exe",
            module_file=root / "source" / "app.py",
            bundle_dir=None,
        )
        self.assertEqual(resource_dir, root / "source")
        self.assertEqual(data_dir, root / "source" / "data")

    def test_build_includes_web_assets_but_not_local_user_data(self):
        root = Path(__file__).resolve().parents[2]
        script = (root / "build_exe.ps1").read_text(encoding="utf-8")
        self.assertIn('$templatesDir = Join-Path $appDir "templates"', script)
        self.assertIn('$staticDir = Join-Path $appDir "static"', script)
        self.assertIn('"$templatesDir;templates"', script)
        self.assertIn('"$staticDir;static"', script)
        self.assertNotIn("data;data", script)

    def test_gitignore_excludes_release_secrets_and_generated_state(self):
        root = Path(__file__).resolve().parents[2]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        for marker in ("settings.json", "arca_login_profile", "*.sqlite*", "release/"):
            self.assertIn(marker, ignore)


if __name__ == "__main__":
    unittest.main()
