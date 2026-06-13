import tempfile
import unittest
from pathlib import Path

import app
from style_logic import build_artist_prompt, normalize_style_artists, style_hash
from style_store import get_style_detail, list_styles, save_generated_result


class StyleIdentityTest(unittest.TestCase):
    def test_prompt_preserves_artist_order(self):
        artists = [
            {"artist": "artist_b", "weight": 0.5, "score": 3},
            {"artist": "artist_a", "weight": 2.1, "score": 5},
        ]

        self.assertEqual(
            build_artist_prompt(artists),
            "0.5::artist_b::, 2.1::artist_a::",
        )

    def test_hash_changes_when_order_changes(self):
        artists = [
            {"artist": "artist_a", "weight": 1.0},
            {"artist": "artist_b", "weight": 1.5},
        ]

        self.assertNotEqual(style_hash(artists), style_hash(list(reversed(artists))))

    def test_hash_changes_when_weight_changes(self):
        original = [
            {"artist": "artist_a", "weight": 1.0},
            {"artist": "artist_b", "weight": 1.5},
        ]
        changed = [original[0], {"artist": "artist_b", "weight": 1.6}]

        self.assertNotEqual(style_hash(original), style_hash(changed))

    def test_hash_accepts_only_artist_identity_argument(self):
        artists = [{"artist": "artist_a", "weight": 1.25}]

        with self.assertRaises(TypeError):
            style_hash(artists, "base prompt")

    def test_normalize_validates_and_rounds_artist_identity(self):
        normalized = normalize_style_artists(
            [{"artist": " artist_a ", "weight": "1.236", "score": "4"}]
        )

        self.assertEqual(
            normalized,
            [{"artist": "artist_a", "weight": 1.24, "score": 4}],
        )
        for invalid in (
            [],
            [{"artist": "", "weight": 1}],
            [{"artist": "artist_a", "weight": 0}],
            [{"artist": "artist_a", "weight": "not-a-number"}],
            [
                {"artist": "artist_a", "weight": 1},
                {"artist": "artist_a", "weight": 2},
            ],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_style_artists(invalid)


class StyleStoreIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.db_path = self.data_dir / "artist_rater.sqlite"
        self.generated_dir = self.data_dir / "generated"
        self.originals = (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        )
        app.DATA_DIR = self.data_dir
        app.THUMBNAIL_DIR = self.data_dir / "thumbnails"
        app.GENERATED_DIR = self.generated_dir
        app.SETTINGS_JSON_PATH = self.data_dir / "settings.json"
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        ) = self.originals
        self.temp_dir.cleanup()

    def test_save_upserts_style_and_returns_parsed_list_and_detail(self):
        artists = [{"artist": "artist_a", "weight": 1.25, "score": 5}]
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": artists,
            "png_bytes": b"\x89PNG\r\n\x1a\nfirst",
            "base_prompt": "portrait",
            "negative_prompt": "lowres",
            "character_prompts": ["1girl"],
            "combined_prompt": "portrait, 1.25::artist_a::",
            "seed": 123,
            "width": 832,
            "height": 1216,
            "sampler": "k_euler",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.0,
            "model": "nai-diffusion-4-full",
        }

        first = save_generated_result(request_id="request-1", **common)
        second = save_generated_result(request_id="request-2", **common)

        self.assertEqual(first["style_id"], second["style_id"])
        self.assertTrue((self.generated_dir / first["image_path"]).is_file())
        self.assertEqual(list(self.generated_dir.rglob("*.tmp")), [])

        styles = list_styles(self.db_path)
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles[0]["artists"], artists)
        self.assertEqual(styles[0]["image_count"], 2)

        detail = get_style_detail(self.db_path, first["style_id"])
        self.assertEqual(detail["artists"], artists)
        self.assertEqual(len(detail["images"]), 2)
        self.assertEqual(detail["images"][0]["character_prompts"], ["1girl"])

    def test_distinct_request_ids_cannot_overwrite_the_same_file(self):
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": [{"artist": "artist_a", "weight": 1}],
            "png_bytes": b"\x89PNG\r\n\x1a\nimage",
        }

        first = save_generated_result(request_id="same/name", **common)
        second = save_generated_result(request_id="same?name", **common)

        self.assertNotEqual(first["image_path"], second["image_path"])
        self.assertTrue((self.generated_dir / first["image_path"]).is_file())
        self.assertTrue((self.generated_dir / second["image_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
