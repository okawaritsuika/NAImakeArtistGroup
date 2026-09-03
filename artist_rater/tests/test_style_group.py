import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

from PIL import Image

from style_group_store import (
    add_sources,
    create_group,
    get_group,
    init_style_group_tables,
    list_candidates,
    record_decision,
    remove_image,
    update_group,
)


def image_bytes(color="red"):
    stream = BytesIO()
    Image.new("RGB", (8, 8), color).save(stream, format="PNG")
    return stream.getvalue()


class StyleGroupStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "artist_rater.sqlite"
        self.thumbnails = self.root / "thumbnails"
        self.generated = self.root / "generated"
        self.images = self.root / "style_group_images"
        self.thumbnails.mkdir()
        self.generated.mkdir()
        self.candidate = self.thumbnails / "one.png"
        self.candidate.write_bytes(image_bytes())
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE ratings (id INTEGER PRIMARY KEY, artist_tag TEXT, score INTEGER, representative_thumbnail_path TEXT);
                CREATE TABLE rating_examples (id INTEGER PRIMARY KEY, rating_id INTEGER, post_id INTEGER, image_path TEXT);
                CREATE TABLE nai_artist_test_items (id INTEGER PRIMARY KEY, test_id INTEGER, status TEXT, generated_image_id INTEGER, artist_tag TEXT, ordinal INTEGER);
                CREATE TABLE generated_images (id INTEGER PRIMARY KEY, image_path TEXT);
                INSERT INTO ratings VALUES (1, 'artist_one', 5, 'one.png');
                """
            )
        init_style_group_tables(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_first_include_becomes_reference_and_survives_source_delete(self):
        group = create_group(self.db, self.images, "좋아하는 체", [{"source_type": "danbooru", "source_id": 1}])
        source = list_candidates(self.db, group["id"])[0]
        candidate = source["current"]
        result = record_decision(self.db, self.images, group["id"], source["id"], candidate["candidate_key"], True, {"thumbnails": self.thumbnails, "generated": self.generated})
        self.assertEqual(result["image_count"], 1)
        self.assertTrue(result["reference_image_path"])
        copied = self.images / result["reference_image_path"]
        self.assertTrue(copied.is_file())
        self.candidate.unlink()
        self.assertTrue((self.images / get_group(self.db, group["id"])["images"][0]["image_path"]).is_file())

    def test_exclusion_and_resume_are_persisted(self):
        self.candidate.write_bytes(image_bytes("blue"))
        group = create_group(self.db, self.images, "제외 테스트", [{"source_type": "danbooru", "source_id": 1}])
        source = list_candidates(self.db, group["id"])[0]
        record_decision(self.db, self.images, group["id"], source["id"], source["current"]["candidate_key"], False, {"thumbnails": self.thumbnails, "generated": self.generated})
        resumed = list_candidates(self.db, group["id"])[0]
        self.assertTrue(resumed["completed"])
        self.assertIsNone(resumed["current"])
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT included FROM style_group_decisions").fetchone()[0], 0)

    def test_source_order_can_be_extended_and_reference_can_be_cleared(self):
        group = create_group(self.db, self.images, "확장", [{"source_type": "danbooru", "source_id": 1, "position": 4}])
        add_sources(self.db, group["id"], [{"source_type": "danbooru", "source_id": 1, "position": 0}])
        self.assertEqual(len(get_group(self.db, group["id"])["sources"]), 1)
        updated = update_group(self.db, group["id"], clear_reference=True)
        self.assertEqual(updated["reference_image_path"], "")
        self.assertIsNone(remove_image(self.db, self.images, group["id"], 999))


if __name__ == "__main__":
    unittest.main()
