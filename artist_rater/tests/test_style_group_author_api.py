import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

import app
from PIL import Image


def image_bytes(color="red"):
    stream = BytesIO()
    Image.new("RGB", (10, 10), color).save(stream, format="PNG")
    return stream.getvalue()


class AuthorStyleGroupApiTest(unittest.TestCase):
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
        app.ARCA_STYLE_SEED_PATH = root / "missing.sqlite"
        app.MERGE_SOURCE_DIRS = []
        app.init_db()
        app.THUMBNAIL_DIR.joinpath("one.png").write_bytes(image_bytes())
        app.THUMBNAIL_DIR.joinpath("two.png").write_bytes(image_bytes("blue"))
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            timestamp = app.now_text()
            connection.execute(
                """INSERT INTO ratings
                   (artist_tag,score,rating_status,mode,representative_thumbnail_path,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("Artist_One", 5, "rated", "manual", "one.png", timestamp, timestamp),
            )
            connection.execute(
                """INSERT INTO ratings
                   (artist_tag,score,rating_status,mode,representative_thumbnail_path,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                ("artist_two", 0, "unrated", "style_group_import", "two.png", timestamp, timestamp),
            )
        self.client = app.app.test_client()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    def test_author_targets_create_review_decision_and_reference_gallery(self):
        targets = self.client.get("/api/style-groups/targets").get_json()
        self.assertEqual(targets["sources"][0]["source_type"], "rating_management")
        self.assertEqual(targets["sources"][0]["artists"][0]["artist_key"], "artist one")
        group = self.client.post(
            "/api/style-groups",
            json={
                "author_mode": True,
                "name": "작가 그룹",
                "sources": [{"source_type": "rating_management", "source_id": "all"}],
                "base_source": {"source_type": "rating_management", "source_id": "all"},
            },
        )
        self.assertEqual(group.status_code, 201)
        group_data = group.get_json()
        review = self.client.get(f"/api/style-groups/{group_data['id']}/artist-review").get_json()
        self.assertEqual(review["artist"]["artist_key"], "artist one")
        candidate = review["sources"][0]["representative"]
        decision = self.client.post(
            f"/api/style-groups/{group_data['id']}/artist-decision",
            json={
                "artist_tag": "Artist One",
                "include": True,
                "reference_source_type": candidate["source_type"],
                "reference_source_id": candidate["source_id"],
                "reference_candidate_key": candidate["candidate_key"],
            },
        )
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.get_json()["artist_count"], 1)
        gallery = self.client.get("/api/style-groups/source-gallery?source_type=rating_management&source_id=all")
        self.assertEqual(gallery.status_code, 200)
        self.assertEqual(len(gallery.get_json()["images"]), 2)
        reference = self.client.post(
            f"/api/style-groups/{group_data['id']}/reference",
            json={"source_type": "rating_management", "source_id": "all", "candidate_key": gallery.get_json()["images"][1]["candidate_key"]},
        )
        self.assertEqual(reference.status_code, 200)
        self.assertTrue(reference.get_json()["reference_image_path"])

    def test_unrated_rating_can_later_be_scored(self):
        created = self.client.post(
            "/api/ratings",
            json={"artist_tag": "direct_author", "rating_status": "unrated", "unrated": True},
        )
        self.assertEqual(created.status_code, 200)
        listed = self.client.get("/api/ratings?q=direct_author").get_json()
        self.assertEqual(listed[0]["rating_status"], "unrated")
        self.assertIsNone(listed[0]["score"])
        updated = self.client.patch("/api/ratings/3", json={"score": 4})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.get("/api/ratings?q=direct_author").get_json()[0]["score"], 4)


if __name__ == "__main__":
    unittest.main()
