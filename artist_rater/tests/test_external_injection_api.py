import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

import app
from PIL import Image

from nai_artist_test_store import (
    EXTERNAL_INJECTION_MARKER,
    EXTERNAL_INJECTION_MARKER_VERSION,
    EXTERNAL_INJECTION_GROUP_NAME,
    create_test,
)


class ExternalInjectionApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {
            name: getattr(app, name)
            for name in (
                "DATA_DIR", "THUMBNAIL_DIR", "GENERATED_DIR",
                "CONFIRMED_STYLE_IMAGE_DIR", "COMPARISON_IMAGE_DIR",
                "ARCA_STYLE_IMAGE_DIR", "STYLE_GROUP_IMAGE_DIR",
                "SETTINGS_JSON_PATH", "DB_PATH", "ARCA_STYLE_SEED_PATH",
                "MERGE_SOURCE_DIRS",
            )
        }
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
        self.client = app.app.test_client()

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp.cleanup()

    @staticmethod
    def _png(color):
        stream = BytesIO()
        Image.new("RGB", (8, 6), color).save(stream, format="PNG")
        return stream.getvalue()

    def _upload(self, artist_name, image_bytes=None, *, remote_addr="127.0.0.1", origin=None):
        image_bytes = self._png("red") if image_bytes is None else image_bytes
        headers = {"Origin": origin} if origin else None
        return self.client.post(
            "/api/external-injection",
            data={"artist_name": artist_name, "image": (BytesIO(image_bytes), "sample.png")},
            content_type="multipart/form-data",
            headers=headers,
            environ_overrides={"REMOTE_ADDR": remote_addr},
        )

    def test_upload_reuses_group_serves_history_and_supports_rating(self):
        first = self._upload("artist one", self._png("red"))
        second = self._upload("artist one", self._png("blue"))
        third = self._upload("artist two", self._png("green"))
        self.assertEqual([response.status_code for response in (first, second, third)], [201, 201, 201])
        first_payload, second_payload, third_payload = (response.get_json() for response in (first, second, third))
        self.assertEqual(first_payload["test_id"], second_payload["test_id"])
        self.assertEqual(first_payload["test_id"], third_payload["test_id"])
        self.assertNotEqual(first_payload["item_id"], second_payload["item_id"])

        tests = self.client.get("/api/nai-artist-tests").get_json()
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0]["name"], EXTERNAL_INJECTION_GROUP_NAME)
        self.assertEqual(tests[0]["config"][EXTERNAL_INJECTION_MARKER]["version"], EXTERNAL_INJECTION_MARKER_VERSION)
        self.assertEqual((tests[0]["total_count"], tests[0]["generated_count"]), (3, 3))
        detail = self.client.get(f"/api/nai-artist-tests/{first_payload['test_id']}").get_json()
        self.assertTrue(all(item["status"] == "complete" for item in detail["items"]))
        source = self.client.get(
            f"/api/style-maker/artist-sources/nai_test/{first_payload['test_id']}"
        ).get_json()
        self.assertEqual(
            {artist["artist_tag"]: artist["image_count"] for artist in source["artists"]},
            {"artist one": 2, "artist two": 1},
        )

        image_url = first_payload["image_url"]
        served = self.client.get(image_url)
        try:
            self.assertEqual(served.status_code, 200)
            self.assertEqual(served.data, self._png("red"))
        finally:
            served.close()
        history = self.client.get("/api/nai-artist-tests/artist-history").get_json()
        self.assertEqual(len(history["items"]), 3)
        self.assertEqual({item["artist_tag"] for item in history["items"]}, {"artist one", "artist two"})

        for item, score in zip(detail["items"], (5, 4, 3)):
            response = self.client.post(
                f"/api/nai-artist-tests/{first_payload['test_id']}/items/{item['id']}/rating",
                json={"score": score},
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/nai-artist-tests/{first_payload['test_id']}").get_json()["status"],
            "completed",
        )
        self.assertEqual(self.client.post(f"/api/nai-artist-tests/{first_payload['test_id']}/generate-next").status_code, 409)

    def test_same_name_ordinary_group_is_not_reused(self):
        ordinary = create_test(
            app.DB_PATH,
            EXTERNAL_INJECTION_GROUP_NAME,
            {"base_prompt": "{{artist}}"},
            [{"artist_tag": "ordinary"}],
            1,
            0,
        )
        response = self._upload("external")
        self.assertEqual(response.status_code, 201)
        tests = self.client.get("/api/nai-artist-tests").get_json()
        self.assertEqual(len(tests), 2)
        external = next(item for item in tests if item["id"] == response.get_json()["test_id"])
        self.assertNotEqual(external["id"], ordinary["id"])
        self.assertNotIn(EXTERNAL_INJECTION_MARKER, ordinary["config"])
        self.assertIn(EXTERNAL_INJECTION_MARKER, external["config"])

    def test_invalid_uploads_and_nonlocal_requests_are_rejected(self):
        missing_file = self.client.post(
            "/api/external-injection",
            data={"artist_name": "artist"},
            content_type="multipart/form-data",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(missing_file.status_code, 400)
        missing_name = self.client.post(
            "/api/external-injection",
            data={"artist_name": "", "image": (BytesIO(self._png("red")), "sample.png")},
            content_type="multipart/form-data",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(missing_name.status_code, 400)
        jpeg = BytesIO()
        Image.new("RGB", (4, 4), "red").save(jpeg, format="JPEG")
        self.assertEqual(self._upload("artist", jpeg.getvalue()).status_code, 400)
        self.assertEqual(self._upload("artist", b"not-an-image").status_code, 400)
        self.assertEqual(self._upload("artist", b"x" * (32 * 1024 * 1024 + 1)).status_code, 400)
        self.assertEqual(self._upload("x" * 201).status_code, 400)
        self.assertEqual(self._upload("artist", remote_addr="192.168.1.20").status_code, 403)
        self.assertEqual(self._upload("artist", origin="http://192.168.1.20:5001").status_code, 403)
        with closing(sqlite3.connect(app.DB_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM nai_artist_tests").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0], 0)

    def test_link_failure_cleans_generated_file_and_database_rows(self):
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute(
                """
                CREATE TRIGGER reject_external_link
                BEFORE INSERT ON nai_artist_test_images
                BEGIN
                    SELECT RAISE(ABORT, 'link failed');
                END
                """
            )
        response = self._upload("artist")
        self.assertEqual(response.status_code, 500)
        with closing(sqlite3.connect(app.DB_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM nai_artist_tests").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0)
        self.assertEqual(list(app.GENERATED_DIR.rglob("*.png")), [])

    def test_external_group_rejects_generation_append_routes(self):
        response = self._upload("artist")
        test_id = response.get_json()["test_id"]
        append = self.client.post(
            f"/api/nai-artist-tests/{test_id}/append",
            json={"prompt_variants": [{"prompt": "{{artist}} extra", "images_per_artist": 1}]},
        )
        self.assertEqual(append.status_code, 409)


if __name__ == "__main__":
    unittest.main()
