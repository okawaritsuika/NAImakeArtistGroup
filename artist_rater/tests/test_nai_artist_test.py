import tempfile
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

import app
from nai_artist_test_store import (
    append_test_items,
    claim_next_item,
    complete_item,
    create_test,
    delete_test,
    get_test,
    init_nai_artist_test_tables,
    latest_direct_rating_map,
    list_artist_history,
    save_item_rating,
    save_direct_rating,
    set_status,
)
from novelai import build_generation_payload, combine_generation_prompt


class NaiArtistTestStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "artist_rater.sqlite"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE generated_images (id INTEGER PRIMARY KEY, image_path TEXT)")
        init_nai_artist_test_tables(self.db_path)
        self.config = {"base_prompt": "{{artist}}, 1girl", "character_prompts": []}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_marker_and_limits_are_validated(self):
        with self.assertRaises(ValueError):
            create_test(self.db_path, "bad", {"base_prompt": "{{artist}}, {{artist}}"}, [{"artist_tag": "a"}], 1, 2)
        with self.assertRaises(ValueError):
            create_test(self.db_path, "bad", self.config, [{"artist_tag": "a"}], 101, 2)
        with self.assertRaises(ValueError):
            create_test(self.db_path, "bad", self.config, [{"artist_tag": "a"}], 1, float("inf"))

    def test_omitted_seed_stays_random_per_generation_item(self):
        config = {
            "base_prompt": "{{artist}}, 1girl", "character_prompts": [], "width": 832, "height": 1216,
            "sampler": "k_euler_ancestral", "noise_schedule": "karras", "steps": 28,
            "scale": 5, "cfg_rescale": 0, "model": "nai-diffusion-4-5-full",
        }
        without_seed = app._nai_artist_test_config({"config": config})
        with_seed = app._nai_artist_test_config({"config": {**config, "seed": 123}})
        self.assertNotIn("seed", without_seed)
        self.assertEqual(with_seed["seed"], 123)

    def test_cancel_keeps_unfinished_items_resumable(self):
        test = create_test(self.db_path, "batch", self.config, [{"artist_tag": "a", "score": 4}], 2, 2)
        set_status(self.db_path, test["id"], "running")
        first, state = claim_next_item(self.db_path, test["id"])
        self.assertEqual(state, "claimed")
        set_status(self.db_path, test["id"], "cancelled")
        stopped = get_test(self.db_path, test["id"])
        self.assertEqual(stopped["status"], "cancelled")
        self.assertTrue(all(item["status"] == "pending" for item in stopped["items"]))
        set_status(self.db_path, test["id"], "running")
        resumed, state = claim_next_item(self.db_path, test["id"])
        self.assertEqual(state, "claimed")
        self.assertEqual(resumed["id"], first["id"])

    def test_prompt_variants_expand_items_with_their_own_templates(self):
        test = create_test(
            self.db_path,
            "variants",
            self.config,
            [{"artist_tag": "a", "score": 4}, {"artist_tag": "b", "score": 3}],
            1,
            2,
            prompt_variants=[
                {"prompt": "{{artist}}, morning", "images_per_artist": 2},
                {"prompt": "{{artist}}, evening", "images_per_artist": 3},
            ],
        )
        self.assertEqual(test["total_count"], 10)
        self.assertEqual([item["prompt_index"] for item in test["items"][:5]], [0, 0, 1, 1, 1])
        self.assertEqual(test["items"][0]["prompt_template"], "{{artist}}, morning")
        self.assertEqual(test["items"][2]["prompt_template"], "{{artist}}, evening")

    def test_completion_and_rating_are_visible_after_commit(self):
        test = create_test(self.db_path, "batch", self.config, [{"artist_tag": "a", "score": 4}], 1, 2)
        set_status(self.db_path, test["id"], "running")
        item, _ = claim_next_item(self.db_path, test["id"])
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'test.png')")
        completed = complete_item(self.db_path, test["id"], item["id"], 9)
        self.assertEqual(completed["status"], "running")
        completed = save_item_rating(self.db_path, test["id"], item["id"], 5)
        self.assertEqual(completed["status"], "completed")
        rated = save_direct_rating(self.db_path, test["id"], "a", 5)
        self.assertEqual(rated["artists"][0]["nai_direct_score"], 5)

    def test_claim_continues_generation_before_image_rating_and_records_generation_time(self):
        test = create_test(self.db_path, "batch", self.config, [{"artist_tag": "a"}], 2, 2)
        set_status(self.db_path, test["id"], "running")
        first, state = claim_next_item(self.db_path, test["id"])
        self.assertEqual(state, "claimed")
        self.assertTrue(first["generation_requested_at"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'test.png')")
        complete_item(self.db_path, test["id"], first["id"], 9)
        second, second_state = claim_next_item(self.db_path, test["id"])
        self.assertEqual(second_state, "claimed")
        self.assertNotEqual(second["id"], first["id"])

    def test_image_ratings_average_and_complete_only_after_all_images_are_rated(self):
        test = create_test(self.db_path, "batch", self.config, [{"artist_tag": "a"}], 2, 2)
        set_status(self.db_path, test["id"], "running")
        first, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("INSERT INTO generated_images(id, image_path) VALUES(?, ?)", [(9, "one.png"), (10, "two.png")])
        complete_item(self.db_path, test["id"], first["id"], 9)
        with self.assertRaisesRegex(RuntimeError, "모든 이미지 생성"):
            save_item_rating(self.db_path, test["id"], first["id"], 3)
        second, state = claim_next_item(self.db_path, test["id"])
        self.assertEqual(state, "claimed")
        complete_item(self.db_path, test["id"], second["id"], 10)
        rated = save_item_rating(self.db_path, test["id"], first["id"], 3)
        self.assertEqual(rated["status"], "running")
        self.assertEqual(rated["rated_count"], 1)
        self.assertEqual(rated["artists"][0]["nai_direct_score"], 3.0)
        completed = save_item_rating(self.db_path, test["id"], second["id"], 4)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["generated_count"], 2)
        self.assertEqual(completed["rated_count"], 2)
        self.assertEqual(completed["remaining_count"], 0)
        self.assertEqual(completed["artists"][0]["nai_direct_score"], 3.5)

    def test_style_maker_uses_half_up_integer_bucket_for_average(self):
        self.assertEqual(app._nai_direct_score_bucket(1.5), 2)
        self.assertEqual(app._nai_direct_score_bucket(3.5), 4)

    def test_generated_image_delete_does_not_block_test_batch(self):
        test = create_test(self.db_path, "batch", self.config, [{"artist_tag": "a"}], 1, 2)
        set_status(self.db_path, test["id"], "running")
        item, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'test.png')")
        complete_item(self.db_path, test["id"], item["id"], 9)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM generated_images WHERE id=9")
            remaining = conn.execute("SELECT generated_image_id FROM nai_artist_test_items WHERE id=?", (item["id"],)).fetchone()[0]
            mappings = conn.execute("SELECT COUNT(*) FROM nai_artist_test_images WHERE item_id=?", (item["id"],)).fetchone()[0]
        self.assertIsNone(remaining)
        self.assertEqual(mappings, 0)

    def test_artist_marker_is_replaced_once_without_separate_artist_prefix(self):
        artist_prompt = "1::artist:sample artist::"
        data = {"base_prompt": "portrait, {{artist}}, blue sky", "leading_prompt": "masterpiece"}
        data["base_prompt"] = data["base_prompt"].replace("{{artist}}", artist_prompt)
        combined = combine_generation_prompt(data, "")
        self.assertEqual(combined.count(artist_prompt), 1)
        self.assertEqual(combined, "masterpiece, portrait, 1::artist:sample artist::, blue sky")

    def test_novelai_payload_keeps_marker_position_and_single_artist_tag(self):
        artist_prompt = "1::artist:sample artist::"
        data = {
            "base_prompt": f"portrait, {artist_prompt}, blue sky",
            "leading_prompt": "masterpiece",
            "negative_prompt": "bad",
            "character_prompts": [],
            "width": 832,
            "height": 1216,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "karras",
            "steps": 28,
            "scale": 5,
            "cfg_rescale": 0,
            "variety_plus": False,
            "quality_toggle": False,
            "uc_preset": 0,
            "complexity": "",
            "model": "nai-diffusion-4-5-full",
            "seed": 123,
        }
        payload = build_generation_payload(data, "")
        generated_input = payload["input"]
        self.assertEqual(generated_input.count("artist:sample artist"), 1)
        self.assertLess(generated_input.index("portrait"), generated_input.index("artist:sample artist"))
        self.assertLess(generated_input.index("artist:sample artist"), generated_input.index("blue sky"))

    def test_latest_direct_rating_wins_across_batches(self):
        first = create_test(self.db_path, "first", self.config, [{"artist_tag": "a"}], 1, 2)
        second = create_test(self.db_path, "second", self.config, [{"artist_tag": "a"}], 1, 2)
        save_direct_rating(self.db_path, first["id"], "a", 2)
        save_direct_rating(self.db_path, second["id"], "a", 5)
        self.assertEqual(latest_direct_rating_map(self.db_path)["a"]["score"], 5)

    def test_artist_history_contains_cross_test_prompt_and_settings(self):
        test = create_test(self.db_path, "history", self.config, [{"artist_tag": "a"}], 1, 2, prompt_variants=[{"prompt": "{{artist}}, sunset", "images_per_artist": 1}])
        set_status(self.db_path, test["id"], "running")
        item, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'history.png')")
        complete_item(self.db_path, test["id"], item["id"], 9)
        history = list_artist_history(self.db_path)
        self.assertEqual(history["artists"][0]["artist_tag"], "a")
        self.assertEqual(history["items"][0]["prompt_template"], "{{artist}}, sunset")
        self.assertEqual(history["items"][0]["effective_prompt"], "a, sunset")

    def test_append_all_preserves_existing_ratings_and_adds_sequential_items(self):
        test = create_test(self.db_path, "append", self.config, [{"artist_tag": "a", "score": 4}, {"artist_tag": "b", "score": 3}], 1, 2)
        set_status(self.db_path, test["id"], "running")
        first, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'append.png')")
        complete_item(self.db_path, test["id"], first["id"], 9)
        set_status(self.db_path, test["id"], "cancelled")
        appended = append_test_items(self.db_path, test["id"], [{"prompt": "{{artist}}, evening", "images_per_artist": 2}], "all")
        self.assertEqual(appended["appended_count"], 4)
        self.assertEqual(appended["items"][0]["id"], first["id"])
        self.assertEqual(appended["items"][0]["status"], "complete")
        self.assertEqual(appended["items"][-1]["ordinal"], 6)
        self.assertEqual(appended["items"][-1]["prompt_template"], "{{artist}}, evening")
        self.assertEqual(appended["status"], "paused")

    def test_append_remaining_rejects_zero_and_running(self):
        test = create_test(self.db_path, "append", self.config, [{"artist_tag": "a"}], 1, 2)
        with self.assertRaisesRegex(RuntimeError, "실행 중"):
            set_status(self.db_path, test["id"], "running")
            append_test_items(self.db_path, test["id"], [{"prompt": "{{artist}}, extra", "images_per_artist": 1}], "all")
        done = create_test(self.db_path, "done", self.config, [{"artist_tag": "a"}], 1, 2)
        set_status(self.db_path, done["id"], "running")
        item, _ = claim_next_item(self.db_path, done["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(10, 'done.png')")
        complete_item(self.db_path, done["id"], item["id"], 10)
        set_status(self.db_path, done["id"], "cancelled")
        with self.assertRaisesRegex(ValueError, "추가할 작가"):
            append_test_items(self.db_path, done["id"], [{"prompt": "{{artist}}, extra", "images_per_artist": 1}], "remaining")

    def test_append_completed_batch_preserves_rated_item_and_average(self):
        test = create_test(self.db_path, "completed append", self.config, [{"artist_tag": "a", "score": 4}], 1, 0)
        set_status(self.db_path, test["id"], "running")
        item, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(30, 'rated.png')")
        complete_item(self.db_path, test["id"], item["id"], 30)
        completed = save_item_rating(self.db_path, test["id"], item["id"], 5)
        old_item = completed["items"][0]
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["artists"][0]["nai_direct_score"], 5.0)
        appended = append_test_items(self.db_path, test["id"], [{"prompt": "{{artist}}, appended", "images_per_artist": 1}], "all")
        self.assertEqual(appended["status"], "paused")
        self.assertEqual(appended["appended_count"], 1)
        self.assertEqual(appended["items"][0]["id"], old_item["id"])
        self.assertEqual(appended["items"][0]["generated_image_id"], 30)
        self.assertEqual(appended["items"][0]["image_score"], 5)
        self.assertEqual(appended["items"][0]["rated_at"], old_item["rated_at"])
        self.assertEqual(appended["artists"][0]["nai_direct_score"], 5.0)
        self.assertEqual(appended["items"][-1]["artist_tag"], "a")
        self.assertEqual(appended["items"][-1]["status"], "pending")

    def test_append_evaluation_pending_running_batch_preserves_unrated_items(self):
        test = create_test(self.db_path, "evaluation append", self.config, [{"artist_tag": "a"}], 2, 0)
        set_status(self.db_path, test["id"], "running")
        first, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(31, 'first.png')")
        complete_item(self.db_path, test["id"], first["id"], 31)
        second, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(32, 'second.png')")
        complete_item(self.db_path, test["id"], second["id"], 32)
        evaluation_pending = get_test(self.db_path, test["id"])
        self.assertEqual(evaluation_pending["status"], "running")
        self.assertEqual(evaluation_pending["generated_count"], 2)
        self.assertEqual(evaluation_pending["rated_count"], 0)
        appended = append_test_items(self.db_path, test["id"], [{"prompt": "{{artist}}, after", "images_per_artist": 1}], "all")
        self.assertEqual(appended["status"], "paused")
        self.assertEqual(appended["appended_count"], 1)
        self.assertEqual([(item["generated_image_id"], item["image_score"]) for item in appended["items"][:2]], [(31, None), (32, None)])
        self.assertEqual(appended["items"][-1]["status"], "pending")

    def test_append_remaining_targets_only_artists_with_unfinished_items(self):
        test = create_test(self.db_path, "remaining append", self.config, [{"artist_tag": "done"}, {"artist_tag": "unfinished"}], 2, 0)
        set_status(self.db_path, test["id"], "running")
        first, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(33, 'done-one.png')")
        complete_item(self.db_path, test["id"], first["id"], 33)
        second, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(34, 'done-two.png')")
        complete_item(self.db_path, test["id"], second["id"], 34)
        set_status(self.db_path, test["id"], "paused")
        appended = append_test_items(self.db_path, test["id"], [{"prompt": "{{artist}}, remaining", "images_per_artist": 2}], "remaining")
        self.assertEqual(appended["appended_count"], 2)
        new_items = appended["items"][-2:]
        self.assertEqual({item["artist_tag"] for item in new_items}, {"unfinished"})
        self.assertTrue(all(item["status"] == "pending" for item in new_items))

    def test_delete_cascades_batch_rows_but_preserves_generated_image(self):
        test = create_test(self.db_path, "deletable", self.config, [{"artist_tag": "a"}], 1, 0)
        set_status(self.db_path, test["id"], "running")
        item, _ = claim_next_item(self.db_path, test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(41, 'keep.png')")
        complete_item(self.db_path, test["id"], item["id"], 41)
        completed = save_item_rating(self.db_path, test["id"], item["id"], 4)
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(delete_test(self.db_path, test["id"]))
        self.assertIsNone(get_test(self.db_path, test["id"]))
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generated_images WHERE id=41").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nai_artist_tests WHERE id=?", (test["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nai_artist_test_items WHERE test_id=?", (test["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nai_artist_test_ratings WHERE test_id=?", (test["id"],)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nai_artist_test_images WHERE test_id=?", (test["id"],)).fetchone()[0], 0)

    def test_delete_rejects_running_and_returns_false_for_missing(self):
        test = create_test(self.db_path, "running", self.config, [{"artist_tag": "a"}], 1, 0)
        set_status(self.db_path, test["id"], "running")
        with self.assertRaisesRegex(RuntimeError, "실행 중인 테스트"):
            delete_test(self.db_path, test["id"])
        self.assertFalse(delete_test(self.db_path, 99999))


class NaiArtistTestArtistsApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "artist_rater.sqlite"
        self.original_db_path = app.DB_PATH
        app.DB_PATH = self.db_path
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY, artist_tag TEXT UNIQUE, score INTEGER, memo TEXT, representative_thumbnail_path TEXT, updated_at TEXT)")
            conn.executemany(
                "INSERT INTO ratings(artist_tag,score,memo,representative_thumbnail_path,updated_at) VALUES(?,?,?,?,?)",
                [("low", 2, "", "", "2026-01-01"), ("high", 5, "", "", "2026-02-01")],
            )
        init_nai_artist_test_tables(self.db_path)
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_artist_endpoint_honors_allowlisted_sort_and_rejects_unknown_sort(self):
        response = self.client.get("/api/nai-artist-tests/artists?sort=score_desc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["artist_tag"] for item in response.get_json()], ["high", "low"])
        self.assertEqual([item["rating_id"] for item in response.get_json()], [2, 1])
        self.assertIn("thumbnail_url", response.get_json()[0])
        recent = self.client.get("/api/nai-artist-tests/artists?sort=recent")
        self.assertEqual([item["artist_tag"] for item in recent.get_json()], ["high", "low"])
        invalid = self.client.get("/api/nai-artist-tests/artists?sort=unsafe")
        self.assertEqual(invalid.status_code, 400)


class NaiArtistTestItemRatingApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "artist_rater.sqlite"
        self.original_db_path = app.DB_PATH
        app.DB_PATH = self.db_path
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE generated_images (id INTEGER PRIMARY KEY, image_path TEXT)")
            conn.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY, artist_tag TEXT UNIQUE, score INTEGER, memo TEXT, representative_thumbnail_path TEXT, updated_at TEXT)")
            conn.execute("INSERT INTO ratings(artist_tag,score) VALUES('a', 4)")
        init_nai_artist_test_tables(self.db_path)
        self.test = create_test(self.db_path, "batch", {"base_prompt": "{{artist}}"}, [{"artist_tag": "a"}], 1, 0)
        set_status(self.db_path, self.test["id"], "running")
        item, _ = claim_next_item(self.db_path, self.test["id"])
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO generated_images(id, image_path) VALUES(9, 'test.png')")
        complete_item(self.db_path, self.test["id"], item["id"], 9)
        self.item_id = item["id"]
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_item_rating_route_returns_average_and_rejects_missing_item(self):
        response = self.client.post(f"/api/nai-artist-tests/{self.test['id']}/items/{self.item_id}/rating", json={"score": 4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["artists"][0]["nai_direct_score"], 4.0)
        missing = self.client.post(f"/api/nai-artist-tests/{self.test['id']}/items/999/rating", json={"score": 4})
        self.assertEqual(missing.status_code, 404)

    def test_append_route_rejects_running_and_accepts_cancelled_batch(self):
        running_test = create_test(self.db_path, "running", {"base_prompt": "{{artist}}"}, [{"artist_tag": "a"}], 2, 0)
        set_status(self.db_path, running_test["id"], "running")
        running = self.client.post(f"/api/nai-artist-tests/{running_test['id']}/append", json={"target_scope": "all", "prompt_variants": [{"prompt": "{{artist}}, extra", "images_per_artist": 1}]})
        self.assertEqual(running.status_code, 409)
        self.client.post(f"/api/nai-artist-tests/{self.test['id']}/cancel")
        response = self.client.post(f"/api/nai-artist-tests/{self.test['id']}/append", json={"target_scope": "all", "prompt_variants": [{"prompt": "{{artist}}, extra", "images_per_artist": 1}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["appended_count"], 1)

    def test_delete_route_rejects_running_then_deletes_batch_only(self):
        blocked = self.client.delete(f"/api/nai-artist-tests/{self.test['id']}")
        self.assertEqual(blocked.status_code, 409)
        self.client.post(f"/api/nai-artist-tests/{self.test['id']}/items/{self.item_id}/rating", json={"score": 4})
        deleted = self.client.delete(f"/api/nai-artist-tests/{self.test['id']}")
        self.assertEqual(deleted.status_code, 200)
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generated_images WHERE id=9").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nai_artist_tests WHERE id=?", (self.test["id"],)).fetchone()[0], 0)
        missing = self.client.delete("/api/nai-artist-tests/99999")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
