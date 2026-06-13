import struct
import tempfile
import unittest
import zlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app
from style_logic import build_artist_prompt, normalize_style_artists, style_hash
from style_store import connect_db, get_style_detail, list_styles, save_generated_result


def png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def tiny_png(pixel=b"\x00\xff\x00\x00\xff"):
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
            png_chunk(b"IDAT", zlib.compress(pixel)),
            png_chunk(b"IEND", b""),
        )
    )


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
            "png_bytes": tiny_png(),
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
        first_png = tiny_png()
        second_png = tiny_png(b"\x00\x00\xff\x00\xff")
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        first = save_generated_result(request_id="foo/", png_bytes=first_png, **common)
        second = save_generated_result(
            request_id="foo-14fe48f0fbfb", png_bytes=second_png, **common
        )

        self.assertNotEqual(first["image_path"], second["image_path"])
        self.assertEqual((self.generated_dir / first["image_path"]).read_bytes(), first_png)
        self.assertEqual((self.generated_dir / second["image_path"]).read_bytes(), second_png)

    def test_rejects_truncated_and_corrupt_crc_png_before_writing(self):
        valid_png = tiny_png()
        corrupt_crc = bytearray(valid_png)
        corrupt_crc[-5] ^= 0x01
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        for request_id, invalid_png in (
            ("truncated", valid_png[:-1]),
            ("corrupt-crc", bytes(corrupt_crc)),
        ):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                save_generated_result(
                    request_id=request_id, png_bytes=invalid_png, **common
                )

        with closing(connect_db(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0)
        self.assertEqual(list(self.generated_dir.rglob("*")), [])

    def test_request_id_retry_returns_existing_result_without_rewriting(self):
        first_png = tiny_png()
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "request_id": "retry-request",
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        first = save_generated_result(png_bytes=first_png, **common)
        second = save_generated_result(
            png_bytes=tiny_png(b"\x00\x00\x00\xff\xff"), **common
        )

        self.assertEqual(second, first)
        self.assertEqual((self.generated_dir / first["image_path"]).read_bytes(), first_png)
        style = list_styles(self.db_path)[0]
        self.assertEqual(style["image_count"], 1)

    def test_replace_failure_compensates_committed_database_rows(self):
        with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                save_generated_result(
                    self.db_path,
                    self.generated_dir,
                    request_id="replace-failure",
                    artists=[{"artist": "artist_a", "weight": 1}],
                    png_bytes=tiny_png(),
                )

        with closing(connect_db(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0)
        self.assertEqual(list(self.generated_dir.rglob("*.tmp")), [])
        self.assertEqual(list(self.generated_dir.rglob("*.png")), [])

    def test_replace_failure_restores_existing_style_summary(self):
        artists = [{"artist": "artist_a", "weight": 1}]
        first = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="first-image",
            artists=artists,
            png_bytes=tiny_png(),
        )

        with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                save_generated_result(
                    self.db_path,
                    self.generated_dir,
                    request_id="failed-second-image",
                    artists=artists,
                    png_bytes=tiny_png(b"\x00\x00\xff\x00\xff"),
                )

        style = list_styles(self.db_path)[0]
        self.assertEqual(style["image_count"], 1)
        self.assertEqual(style["representative_image_path"], first["image_path"])
        self.assertTrue((self.generated_dir / first["image_path"]).is_file())

    def test_reconcile_removes_stale_temp_and_unreferenced_png(self):
        saved = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="referenced",
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        stale_temp = self.generated_dir / "1" / ".stale.png.deadbeef.tmp"
        orphan = self.generated_dir / "1" / "orphan.png"
        stale_temp.write_bytes(b"stale")
        orphan.write_bytes(tiny_png())

        app.init_db()

        self.assertFalse(stale_temp.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue((self.generated_dir / saved["image_path"]).is_file())

    def test_reconcile_promotes_committed_staged_file(self):
        saved = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="crash-window",
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        final_path = self.generated_dir / saved["image_path"]
        staged_path = final_path.with_name(f".{final_path.name}.staged.tmp")
        final_path.replace(staged_path)

        app.init_db()

        self.assertTrue(final_path.is_file())
        self.assertFalse(staged_path.exists())


if __name__ == "__main__":
    unittest.main()
