import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from nai_artist_test_store import (
    claim_specific_item,
    create_test,
    init_nai_artist_test_tables,
    prepare_test_artist_item,
)


class NaiArtistPrepareStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "artist_rater.sqlite"
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("CREATE TABLE generated_images (id INTEGER PRIMARY KEY, image_path TEXT)")
        init_nai_artist_test_tables(self.db_path)
        self.config = {"base_prompt": "{{artist}}, 1girl", "character_prompts": []}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_existing_artist_uses_next_pending_without_appending(self):
        test = create_test(self.db_path, "existing", self.config, [{"artist_tag": "Some_Artist"}], 1, 0)
        first = prepare_test_artist_item(self.db_path, test["id"], "some artist")
        self.assertEqual(first["appended_count"], 0)
        self.assertEqual(first["first_item_id"], test["items"][0]["id"])

    def test_new_artist_appends_all_pending_but_identifies_one_first_item(self):
        test = create_test(self.db_path, "new", self.config, [{"artist_tag": "existing"}], 2, 0)
        prepared = prepare_test_artist_item(self.db_path, test["id"], "new_artist")
        self.assertEqual(prepared["appended_count"], 2)
        new_items = [item for item in prepared["items"] if item["artist_tag"] == "new_artist"]
        self.assertEqual(len(new_items), 2)
        self.assertEqual(prepared["first_item_id"], new_items[0]["id"])
        claimed, state = claim_specific_item(self.db_path, test["id"], prepared["first_item_id"])
        self.assertEqual(state, "claimed")
        self.assertEqual(claimed["id"], prepared["first_item_id"])
        with closing(sqlite3.connect(self.db_path)) as connection:
            statuses = [
                row[0]
                for row in connection.execute(
                    "SELECT status FROM nai_artist_test_items WHERE test_id=? AND artist_tag=? ORDER BY ordinal",
                    (test["id"], "new_artist"),
                ).fetchall()
            ]
        self.assertEqual(statuses, ["processing", "pending"])


if __name__ == "__main__":
    unittest.main()
