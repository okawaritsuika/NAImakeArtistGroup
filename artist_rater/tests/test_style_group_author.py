import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path

from PIL import Image

from style_group_store import (
    add_style_group_direct_artist,
    add_style_group_sources_modern,
    create_author_group,
    get_group,
    init_style_group_tables,
    list_style_group_artist_review,
    list_style_group_source_gallery,
    list_style_group_targets,
    record_style_group_artist_decision,
    select_style_group_reference,
    sync_style_group_generated_image,
)


def png_bytes(color):
    stream = BytesIO()
    Image.new("RGB", (12, 12), color).save(stream, format="PNG")
    return stream.getvalue()


class AuthorStyleGroupStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "artist_rater.sqlite"
        self.thumbnails = root / "thumbnails"
        self.generated = root / "generated"
        self.copies = root / "style_group_images"
        self.thumbnails.mkdir()
        self.generated.mkdir()
        (self.thumbnails / "artist_one.png").write_bytes(png_bytes("red"))
        (self.thumbnails / "artist_one_example.png").write_bytes(png_bytes("blue"))
        (self.thumbnails / "artist_two.png").write_bytes(png_bytes("green"))
        (self.generated / "test_one.png").write_bytes(png_bytes("purple"))
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE ratings (
                    id INTEGER PRIMARY KEY, artist_tag TEXT, score INTEGER,
                    representative_thumbnail_path TEXT
                );
                CREATE TABLE rating_examples (
                    id INTEGER PRIMARY KEY, rating_id INTEGER, post_id INTEGER,
                    image_path TEXT
                );
                CREATE TABLE generated_images (id INTEGER PRIMARY KEY, image_path TEXT);
                CREATE TABLE nai_artist_tests (id INTEGER PRIMARY KEY, name TEXT, status TEXT, updated_at TEXT);
                CREATE TABLE nai_artist_test_items (
                    id INTEGER PRIMARY KEY, test_id INTEGER, artist_tag TEXT,
                    ordinal INTEGER, status TEXT, generated_image_id INTEGER
                );
                INSERT INTO ratings VALUES (1, 'artist_one', 5, 'artist_one.png');
                INSERT INTO ratings VALUES (2, 'artist_two', 0, 'artist_two.png');
                INSERT INTO ratings VALUES (3, 'artist_three', 0, 'artist_one_example.png');
                INSERT INTO rating_examples VALUES (1, 1, 1001, 'artist_one_example.png');
                INSERT INTO generated_images VALUES (1, 'test_one.png');
                INSERT INTO nai_artist_tests VALUES (1, '테스트 1', 'completed', '1');
                INSERT INTO nai_artist_test_items VALUES (1, 1, 'Artist One', 1, 'complete', 1);
                """
            )
        init_style_group_tables(self.db)
        self.roots = {"thumbnails": self.thumbnails, "generated": self.generated}

    def tearDown(self):
        self.temp.cleanup()

    def test_targets_normalize_authors_and_source_gallery(self):
        targets = list_style_group_targets(self.db, self.roots)
        self.assertEqual([target["source_type"] for target in targets], ["rating_management", "nai_test"])
        self.assertEqual(targets[0]["artist_count"], 3)
        self.assertEqual(targets[1]["artists"][0]["artist_key"], "artist one")
        gallery = list_style_group_source_gallery(self.db, "rating_management", "all", self.roots)
        self.assertEqual(len(gallery["images"]), 4)

    def test_author_include_copies_all_sources_and_survives_delete(self):
        group = create_author_group(
            self.db,
            self.copies,
            "작가 중심",
            [
                {"source_type": "rating_management", "source_id": "all"},
                {"source_type": "nai_test", "source_id": 1},
            ],
            base_source={"source_type": "rating_management", "source_id": "all"},
        )
        self.assertEqual(group["unreviewed_count"], 3)
        review = list_style_group_artist_review(self.db, group["id"], source_roots=self.roots)
        self.assertEqual(review["artist"]["artist_key"], "artist one")
        self.assertEqual(len(review["sources"]), 2)
        result = record_style_group_artist_decision(
            self.db, self.copies, group["id"], "Artist_One", True, self.roots,
            "rating_management", "all", review["sources"][0]["representative"]["candidate_key"],
        )
        self.assertEqual(result["artist_count"], 1)
        self.assertEqual(result["unreviewed_count"], 2)
        self.assertEqual(len([image for image in result["images"] if image["is_reference"] or image["artist_key"]]), 3)
        for path in (self.thumbnails / "artist_one.png", self.thumbnails / "artist_one_example.png", self.generated / "test_one.png"):
            path.unlink()
        self.assertTrue(all((self.copies / image["image_path"]).is_file() for image in result["images"]))

    def test_reference_is_standalone_and_exclusion_direct_add_and_later_sync(self):
        group = create_author_group(
            self.db, self.copies, "기준", [{"source_type": "rating_management", "source_id": "all"}]
        )
        gallery = list_style_group_source_gallery(self.db, "rating_management", "all", self.roots)
        selected = gallery["images"][0]
        result = select_style_group_reference(
            self.db, self.copies, group["id"], "rating_management", "all", selected["candidate_key"], self.roots
        )
        self.assertEqual(result["artist_count"], 0)
        record_style_group_artist_decision(self.db, self.copies, group["id"], "artist_two", False, self.roots)
        add_style_group_direct_artist(self.db, group["id"], "New_Author")
        group = add_style_group_sources_modern(
            self.db, self.copies, group["id"], [{"source_type": "nai_test", "source_id": 1}], self.roots
        )
        self.assertEqual(group["artist_count"], 1)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("INSERT INTO generated_images VALUES (2, 'later.png')")
            connection.execute("INSERT INTO nai_artist_test_items VALUES (2, 1, 'New Author', 2, 'complete', 2)")
        (self.generated / "later.png").write_bytes(png_bytes("orange"))
        self.assertEqual(sync_style_group_generated_image(self.db, self.copies, 1, "new_author", 2), 1)
        synced = get_group(self.db, group["id"])
        self.assertTrue(any(image["artist_key"] == "new author" for image in synced["images"]))

    def test_reference_can_come_from_unconnected_test_without_adding_source(self):
        group = create_author_group(
            self.db,
            self.copies,
            "독립 기준",
            [{"source_type": "rating_management", "source_id": "all"}],
            base_source={"source_type": "rating_management", "source_id": "all"},
            reference={
                "source_type": "nai_test",
                "source_id": 1,
                "candidate_key": "nai_item:1",
            },
            source_roots=self.roots,
        )
        self.assertEqual(group["sources"][0]["source_type"], "rating_management")
        self.assertEqual(len(group["sources"]), 1)
        self.assertTrue(group["reference_image_path"])

    def test_shared_hash_survives_other_artist_removal_and_reference_replacement_cleans_standalone(self):
        group = create_author_group(
            self.db, self.copies, "공유 이미지", [{"source_type": "rating_management", "source_id": "all"}]
        )
        review = list_style_group_artist_review(self.db, group["id"], source_roots=self.roots)
        record_style_group_artist_decision(self.db, self.copies, group["id"], "artist_one", True, self.roots)
        record_style_group_artist_decision(self.db, self.copies, group["id"], "artist_three", True, self.roots)
        with closing(sqlite3.connect(self.db)) as connection:
            shared = connection.execute(
                "SELECT image_path FROM style_group_images WHERE group_id=? AND original_name='artist_one_example.png'",
                (group["id"],),
            ).fetchone()[0]
        record_style_group_artist_decision(self.db, self.copies, group["id"], "artist_one", False, self.roots)
        self.assertTrue((self.copies / shared).is_file())
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM style_group_image_artists WHERE artist_key='artist three'"
            ).fetchone())

        standalone = create_author_group(
            self.db, self.copies, "기준 교체", [{"source_type": "rating_management", "source_id": "all"}]
        )
        gallery = list_style_group_source_gallery(self.db, "rating_management", "all", self.roots)
        first = next(image for image in gallery["images"] if image["artist_key"] == "artist one")
        second = next(image for image in gallery["images"] if image["artist_key"] == "artist two")
        select_style_group_reference(self.db, self.copies, standalone["id"], "rating_management", "all", first["candidate_key"], self.roots)
        old_path = get_group(self.db, standalone["id"])["reference_image_path"]
        select_style_group_reference(self.db, self.copies, standalone["id"], "rating_management", "all", second["candidate_key"], self.roots)
        replaced = get_group(self.db, standalone["id"])
        self.assertNotEqual(replaced["reference_image_path"], old_path)
        self.assertFalse((self.copies / old_path).is_file())
        self.assertEqual(replaced["image_count"], 1)


if __name__ == "__main__":
    unittest.main()
