import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

import app
from PIL import Image


class StyleGroupApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {name: getattr(app, name) for name in (
            "DATA_DIR", "THUMBNAIL_DIR", "GENERATED_DIR", "CONFIRMED_STYLE_IMAGE_DIR",
            "COMPARISON_IMAGE_DIR", "ARCA_STYLE_IMAGE_DIR", "STYLE_GROUP_IMAGE_DIR",
            "SETTINGS_JSON_PATH", "DB_PATH", "ARCA_STYLE_SEED_PATH", "MERGE_SOURCE_DIRS",
        )}
        app.DATA_DIR = root
        app.THUMBNAIL_DIR = root / "thumbnails"
        app.GENERATED_DIR = root / "generated"
        app.CONFIRMED_STYLE_IMAGE_DIR = root / "confirmed_style_images"
        app.COMPARISON_IMAGE_DIR = root / "comparison_images"
        app.ARCA_STYLE_IMAGE_DIR = root / "arca_style_images"
        app.STYLE_GROUP_IMAGE_DIR = root / "style_group_images"
        app.SETTINGS_JSON_PATH = root / "settings.json"
        app.DB_PATH = root / "artist_rater.sqlite"
        app.ARCA_STYLE_SEED_PATH = root / "missing-seed.sqlite"
        app.MERGE_SOURCE_DIRS = []
        app.init_db()
        stream = BytesIO()
        Image.new("RGB", (8, 8), "red").save(stream, format="PNG")
        app.THUMBNAIL_DIR.joinpath("artist.png").write_bytes(stream.getvalue())
        app.THUMBNAIL_DIR.joinpath("example.png").write_bytes(stream.getvalue())
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            timestamp = app.now_text()
            connection.execute(
                "INSERT INTO ratings(artist_tag,score,mode,representative_thumbnail_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("artist_one", 5, "manual", "artist.png", timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO ratings(artist_tag,score,mode,representative_thumbnail_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("artist_without_local_image", 4, "manual", "missing.png", timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO ratings(artist_tag,score,mode,representative_thumbnail_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("artist_example_only", 3, "manual", "missing-example.png", timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO rating_examples(rating_id,post_id,image_path,created_at) VALUES(?,?,?,?)",
                (3, 3001, "example.png", timestamp),
            )
        self.client = app.app.test_client()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_create_include_and_resume(self):
        response = self.client.post(
            "/api/style-groups",
            data={"name": "선호 체", "sources": json.dumps([{"source_type": "danbooru", "source_id": 1}])},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        group = response.get_json()
        candidates = self.client.get(f"/api/style-groups/{group['id']}/candidates").get_json()["sources"]
        current = candidates[0]["current"]
        decision = self.client.post(
            f"/api/style-groups/{group['id']}/decision",
            json={"source_id": current["source_id"], "candidate_key": current["candidate_key"], "include": True},
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.get_json()["image_count"], 1)
        self.assertTrue(decision.get_json()["reference_image_path"])

    def test_reference_upload_is_stored_in_group_directory(self):
        stream = BytesIO()
        Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
        response = self.client.post(
            "/api/style-groups",
            data={"name": "업로드 기준", "sources": "[]", "reference_image": (BytesIO(stream.getvalue()), "reference.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        group = response.get_json()
        self.assertTrue((app.STYLE_GROUP_IMAGE_DIR / group["images"][0]["image_path"]).is_file())

    def test_targets_exclude_ratings_without_local_candidates(self):
        response = self.client.get("/api/style-groups/targets")
        self.assertEqual(response.status_code, 200)
        targets = response.get_json()["danbooru"]
        self.assertEqual([item["artist_tag"] for item in targets], ["artist_example_only", "artist_one"])
        self.assertEqual(targets[0]["image_url"], "")


if __name__ == "__main__":
    unittest.main()
