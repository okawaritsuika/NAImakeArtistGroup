import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from PIL import Image


class CandidateFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        app.DATA_DIR = self.tmp
        app.THUMBNAIL_DIR = self.tmp / "thumbnails"
        app.DB_PATH = self.tmp / "artist_rater.sqlite"
        app.init_db()
        self.client = app.app.test_client()

    def _fake_thumbnail(self, url, artist_tag, post_id):
        filename = app.thumbnail_filename(artist_tag, post_id)
        target = app.THUMBNAIL_DIR / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 24), (30, 120, 180)).save(target, format="WEBP")
        return filename

    def _create_rating(self, artist_tag):
        response = self.client.post(
            "/api/ratings",
            json={"artist_tag": artist_tag, "score": 4, "mode": "manual"},
        )
        self.assertEqual(response.status_code, 200)

    def test_autocomplete_sorts_tags_by_post_count_descending(self):
        tags = [
            {"name": "small", "category": 0, "post_count": 10},
            {"name": "large", "category": 0, "post_count": 500},
            {"name": "medium", "category": 0, "post_count": 100},
        ]
        with patch("app.danbooru_get", return_value=tags):
            results = app.autocomplete_tags("test")

        self.assertEqual([item["name"] for item in results], ["large", "medium", "small"])

    def test_artist_autocomplete_only_returns_artist_category(self):
        tags = [
            {"name": "general_tag", "category": 0, "post_count": 500},
            {"name": "artist_tag", "category": 1, "post_count": 100},
        ]
        with patch("app.danbooru_get", return_value=tags):
            results = app.autocomplete_tags("tag", category=1)

        self.assertEqual([item["name"] for item in results], ["artist_tag"])

    def test_manual_rating_saves_entered_query_tags(self):
        response = self.client.post(
            "/api/ratings",
            json={
                "artist_tag": "manual_artist",
                "score": 4,
                "memo": "manual",
                "mode": "manual",
                "query_text": "dakimakura_(medium), solo",
                "query_tags": ["dakimakura_(medium)", "solo"],
                "prompt_text": "manual_artist, masterpiece, best quality, very aesthetic",
            },
        )

        self.assertEqual(response.status_code, 200)
        item = self.client.get("/api/ratings").get_json()[0]
        self.assertEqual(item["mode"], "manual")
        self.assertEqual(item["query_tags"], ["dakimakura_(medium)", "solo"])

    def test_rating_query_prompt_can_be_updated_and_cleared(self):
        self.client.post(
            "/api/ratings",
            json={
                "artist_tag": "editable_artist",
                "score": 4,
                "query_text": "old_tag",
                "query_tags": ["old_tag"],
            },
        )

        response = self.client.patch(
            "/api/ratings/1",
            json={"query_text": "dakimakura_(medium), white_sheet"},
        )
        self.assertEqual(response.status_code, 200)
        item = self.client.get("/api/ratings").get_json()[0]
        self.assertEqual(item["query_text"], "dakimakura_(medium), white_sheet")
        self.assertEqual(item["query_tags"], ["dakimakura_(medium)", "white_sheet"])

        response = self.client.patch("/api/ratings/1", json={"query_text": ""})
        self.assertEqual(response.status_code, 200)
        item = self.client.get("/api/ratings").get_json()[0]
        self.assertEqual(item["query_text"], "")
        self.assertEqual(item["query_tags"], [])

    def test_missing_rating_thumbnail_can_be_fetched_from_danbooru(self):
        self.client.post("/api/ratings", json={"artist_tag": "manual_artist", "score": 4, "mode": "manual"})
        sample = {"id": 77, "preview_url": "https://example.test/77.jpg", "large_url": "https://example.test/77-large.jpg"}
        with patch("app.fetch_artist_samples", return_value=[sample]), patch(
            "app.download_thumbnail", return_value="manual_artist_77.jpg"
        ) as download:
            response = self.client.post("/api/ratings/1/thumbnail")

        self.assertEqual(response.status_code, 200)
        download.assert_called_once_with("https://example.test/77-large.jpg", "manual_artist", 77)
        item = self.client.get("/api/ratings").get_json()[0]
        self.assertEqual(item["thumbnail_url"], "/thumbnails/manual_artist_77.jpg")
        self.assertEqual(item["representative_post_id"], 77)

    def test_download_thumbnail_converts_new_images_to_small_webp(self):
        source = io.BytesIO()
        Image.new("RGBA", (1200, 600), (20, 120, 220, 160)).save(source, format="PNG")
        payload = source.getvalue()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                self.chunk_size = chunk_size
                return [payload[:37], payload[37:]]

        with patch("app.requests.get", return_value=FakeResponse()):
            filename = app.download_thumbnail("https://example.test/source.png", "webp_artist", 88)

        self.assertEqual(filename, "webp_artist_88.webp")
        target = app.THUMBNAIL_DIR / filename
        self.assertTrue(target.exists())
        with Image.open(target) as converted:
            self.assertEqual(converted.format, "WEBP")
            self.assertLessEqual(max(converted.size), 768)
            self.assertEqual(converted.size, (768, 384))
            converted.load()

    def test_download_thumbnail_cleans_up_when_image_decode_fails(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                return [b"not-an-image"]

        with patch("app.requests.get", return_value=FakeResponse()):
            filename = app.download_thumbnail("https://example.test/broken", "broken_artist", 89)

        self.assertEqual(filename, "")
        self.assertFalse((app.THUMBNAIL_DIR / "broken_artist_89.webp").exists())
        self.assertEqual(list(app.THUMBNAIL_DIR.glob(".broken_artist_89.webp.tmp")), [])

    def test_rating_examples_schema_is_created_without_foreign_key_dependency(self):
        with sqlite3.connect(app.DB_PATH) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(rating_examples)")}
            indexes = conn.execute("PRAGMA index_list(rating_examples)").fetchall()
        self.assertTrue({"id", "rating_id", "post_id", "image_path", "source_url", "post_url", "created_at"} <= columns)
        self.assertTrue(any("rating_examples" in str(index) or index[2] for index in indexes))

    def test_collect_rating_examples_saves_webp_paths_and_skips_duplicates(self):
        self._create_rating("stored_artist")
        samples = [
            {"id": 11, "large_url": "https://example.test/11-large.jpg", "preview_url": "https://example.test/11.jpg", "post_url": "https://danbooru.donmai.us/posts/11"},
            {"id": 12, "large_url": "https://example.test/12-large.jpg", "preview_url": "https://example.test/12.jpg", "post_url": "https://danbooru.donmai.us/posts/12"},
        ]
        next_samples = [samples[1], {"id": 13, "large_url": "https://example.test/13-large.jpg"}]
        with patch("app.fetch_artist_samples", side_effect=[samples, next_samples]), patch(
            "app.download_thumbnail", side_effect=self._fake_thumbnail
        ) as download:
            first = self.client.post("/api/ratings/1/examples/collect", json={"sample_limit": 10})
            second = self.client.post("/api/ratings/1/examples/collect", json={"sample_limit": 10})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["saved_count"], 2)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["saved_count"], 1)
        examples = self.client.get("/api/ratings/1/examples").get_json()["examples"]
        self.assertEqual([item["post_id"] for item in examples], [11, 12, 13])
        self.assertTrue(all(item["image_url"].endswith(".webp") for item in examples))
        self.assertEqual(examples[-1]["post_url"], "https://danbooru.donmai.us/posts/13")
        self.assertEqual(download.call_count, 3)

    def test_collect_rating_examples_returns_502_when_danbooru_fails(self):
        self._create_rating("failed_collect_artist")
        with patch(
            "app.fetch_artist_samples",
            side_effect=app.requests.RequestException("offline"),
        ):
            response = self.client.post("/api/ratings/1/examples/collect", json={})

        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.get_json()["ok"])

    def test_rating_example_can_be_set_as_thumbnail_and_deleted(self):
        self._create_rating("settable_artist")
        sample = {"id": 21, "large_url": "https://example.test/21-large.jpg", "post_url": "https://danbooru.donmai.us/posts/21"}
        with patch("app.fetch_artist_samples", return_value=[sample]), patch(
            "app.download_thumbnail", side_effect=self._fake_thumbnail
        ):
            collected = self.client.post("/api/ratings/1/examples/collect", json={})
        example = collected.get_json()["examples"][0]
        filename = app.THUMBNAIL_DIR / "settable_artist_21.webp"
        selected = self.client.post(f"/api/ratings/1/examples/{example['id']}/thumbnail")
        self.assertEqual(selected.status_code, 200)
        rating = self.client.get("/api/ratings").get_json()[0]
        self.assertEqual(rating["representative_post_id"], 21)
        self.assertEqual(rating["representative_thumbnail_path"], "settable_artist_21.webp")

        deleted = self.client.delete(f"/api/ratings/1/examples/{example['id']}")
        self.assertEqual(deleted.status_code, 200)
        rating = self.client.get("/api/ratings").get_json()[0]
        self.assertIsNone(rating["representative_post_id"])
        self.assertEqual(rating["representative_thumbnail_path"], "")
        self.assertFalse(filename.exists())

    def test_rating_example_ownership_and_rating_delete_cleanup(self):
        self._create_rating("owner_a")
        self._create_rating("owner_b")
        samples = [
            {"id": 31, "large_url": "https://example.test/31-large.jpg", "post_url": "https://danbooru.donmai.us/posts/31"},
            {"id": 32, "large_url": "https://example.test/32-large.jpg", "post_url": "https://danbooru.donmai.us/posts/32"},
        ]
        with patch("app.fetch_artist_samples", return_value=samples), patch(
            "app.download_thumbnail", side_effect=self._fake_thumbnail
        ):
            collected = self.client.post("/api/ratings/1/examples/collect", json={})
        example_id = collected.get_json()["examples"][0]["id"]
        self.assertEqual(self.client.post(f"/api/ratings/2/examples/{example_id}/thumbnail").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/ratings/2/examples/{example_id}").status_code, 404)
        paths = [app.THUMBNAIL_DIR / f"owner_a_{post_id}.webp" for post_id in (31, 32)]
        self.assertEqual(self.client.delete("/api/ratings/1").status_code, 200)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(self.client.get("/api/ratings/1/examples").status_code, 404)
        self.assertEqual(self.client.post("/api/ratings/999/examples/collect").status_code, 404)

    def test_candidates_endpoint_returns_artist_pool_without_samples(self):
        with patch("app.search_posts") as search_posts, patch("app.get_artist_post_count") as post_count:
            search_posts.return_value = [
                {
                    "id": 1,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "tag_string_artist": "artist_a",
                    "preview_file_url": "https://example.test/a.jpg",
                },
                {
                    "id": 2,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "tag_string_artist": "artist_b",
                    "preview_file_url": "https://example.test/b.jpg",
                },
            ]
            post_count.return_value = 2000

            response = self.client.post(
                "/api/candidates",
                json={
                    "query_text": "school_uniform",
                    "min_artist_post_count": 1000,
                    "min_match_count": 1,
                    "candidate_limit": 12,
                    "random_mode": "uniform",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["candidate_count"], 2)
        self.assertEqual(len(data["candidates"]), 2)
        self.assertNotIn("samples", data["candidates"][0])
        self.assertEqual(data["filter_stats"]["fetched_post_count"], 2)
        self.assertEqual(data["filter_stats"]["unique_artist_count"], 2)
        self.assertEqual(data["filter_stats"]["final_candidate_count"], 2)

    def test_candidates_endpoint_excludes_artists_seen_in_current_session(self):
        with patch("app.search_posts") as search_posts, patch("app.get_artist_post_count") as post_count:
            search_posts.return_value = [
                {
                    "id": 1,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "tag_string_artist": "artist_a",
                    "preview_file_url": "https://example.test/a.jpg",
                },
                {
                    "id": 2,
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "tag_string_artist": "artist_b",
                    "preview_file_url": "https://example.test/b.jpg",
                },
            ]
            post_count.return_value = 2000

            response = self.client.post(
                "/api/candidates",
                json={
                    "query_text": "school_uniform",
                    "min_artist_post_count": 1000,
                    "min_match_count": 1,
                    "candidate_limit": 12,
                    "random_mode": "uniform",
                    "exclude_artist_tags": ["artist_a"],
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual([item["artist"] for item in data["candidates"]], ["artist_b"])

    def test_candidates_are_drawn_then_filtered_by_exclusion_prompt(self):
        candidates = [
            {"artist_tag": "artist_a", "matched_post_count": 3, "artist_post_count": 2000},
            {"artist_tag": "artist_b", "matched_post_count": 2, "artist_post_count": 2000},
        ]

        def search_posts(tags, fetch_pages=1, limit=100):
            return [{"id": 1}] if tags == ["artist_a", "ai-generated"] else []

        with patch("app.global_artist_candidates", return_value=candidates), patch(
            "app.search_posts", side_effect=search_posts
        ), patch("app.choose_candidate", side_effect=lambda items, mode: items[0]):
            response = self.client.post(
                "/api/candidates",
                json={
                    "exclude_query_text": "ai-generated",
                    "candidate_limit": 1,
                    "random_mode": "uniform",
                },
            )

        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual([item["artist"] for item in data["candidates"]], ["artist_b"])
        self.assertEqual(data["exclude_query_tags"], ["ai-generated"])
        self.assertEqual(data["filter_stats"]["exclude_prompt_filtered_count"], 1)

    def test_artist_samples_endpoint_fetches_images_for_one_artist(self):
        sample = {
            "id": 10,
            "preview_url": "https://example.test/preview.jpg",
            "large_url": "https://example.test/large.jpg",
            "post_url": "https://danbooru.donmai.us/posts/10",
            "created_at": "2025-01-01T00:00:00+00:00",
            "rating": "s",
            "score": 8,
        }
        with patch("app.fetch_artist_samples", return_value=[sample]) as fetch_samples:
            response = self.client.post(
                "/api/artist_samples",
                json={
                    "artist_tag": "artist_a",
                    "query_tags": ["school_uniform"],
                    "sample_limit": 10,
                    "mode": "tag_filtered_random",
                    "matched_post_count": 4,
                    "artist_post_count": 2000,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["artist"], "artist_a")
        self.assertEqual(len(data["samples"]), 1)
        fetch_samples.assert_called_once_with("artist_a", ["school_uniform"], 10, False)

    def test_fetch_artist_samples_shuffles_danbooru_order(self):
        posts = [
            {
                "id": 1,
                "created_at": "2025-01-01T00:00:00+00:00",
                "preview_file_url": "https://example.test/1.jpg",
            },
            {
                "id": 2,
                "created_at": "2025-01-01T00:00:00+00:00",
                "preview_file_url": "https://example.test/2.jpg",
            },
            {
                "id": 3,
                "created_at": "2025-01-01T00:00:00+00:00",
                "preview_file_url": "https://example.test/3.jpg",
            },
        ]

        def reverse_shuffle(items):
            items.reverse()

        with patch("app.search_posts", return_value=posts), patch("app.random.shuffle", side_effect=reverse_shuffle):
            samples = app.fetch_artist_samples("artist_a", ["school_uniform"], 3)

        self.assertEqual([sample["id"] for sample in samples], [3, 2, 1])

    def test_fetch_artist_samples_keeps_latest_danbooru_order_when_requested(self):
        posts = [
            {"id": 3, "created_at": "2025-01-03T00:00:00+00:00", "preview_file_url": "https://example.test/3.jpg"},
            {"id": 2, "created_at": "2025-01-02T00:00:00+00:00", "preview_file_url": "https://example.test/2.jpg"},
            {"id": 1, "created_at": "2025-01-01T00:00:00+00:00", "preview_file_url": "https://example.test/1.jpg"},
        ]

        with patch("app.search_posts", return_value=posts) as search_posts, patch("app.random.shuffle") as shuffle:
            samples = app.fetch_artist_samples("artist_a", ["school_uniform"], 2, latest_first=True)

        self.assertEqual([sample["id"] for sample in samples], [3, 2])
        search_posts.assert_called_once_with(["artist_a"], fetch_pages=1)
        shuffle.assert_not_called()

    def test_search_posts_uses_requested_cutoff_tag_and_includes_cutoff_second(self):
        posts = [
            {"id": 1, "created_at": "2026-06-15T23:59:59Z"},
            {"id": 2, "created_at": "2026-06-16T00:00:00Z"},
        ]
        with patch("app.danbooru_get", return_value=posts) as danbooru_get:
            result = app.search_posts(["school_uniform"], cutoff_date="2026-06-15")

        self.assertEqual([item["id"] for item in result], [1])
        self.assertEqual(danbooru_get.call_args.args[0], "/posts.json")
        self.assertEqual(danbooru_get.call_args.args[1]["tags"], "school_uniform date:<=2026-06-15")

    def test_invalid_candidate_cutoff_date_is_rejected(self):
        response = self.client.post("/api/candidates", json={"cutoff_date": "2026-02-30"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("cutoff_date", response.get_json()["error"])

    def test_candidate_response_and_exclusion_search_keep_requested_cutoff(self):
        candidates = [
            {"artist_tag": "artist_a", "matched_post_count": 3, "artist_post_count": 2000},
        ]

        def search_posts(tags, fetch_pages=1, limit=100, cutoff_date=app.DEFAULT_CUTOFF_DATE):
            self.assertEqual(cutoff_date, "2026-06-15")
            return []

        with patch("app.search_posts", side_effect=search_posts), patch(
            "app.get_artist_post_count", return_value=2000
        ), patch("app.global_artist_candidates", return_value=candidates):
            response = self.client.post(
                "/api/candidates",
                json={"exclude_query_text": "ai-generated", "cutoff_date": "2026-06-15", "candidate_limit": 1},
            )

        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["cutoff_date"], "2026-06-15")

    def test_artist_samples_passes_candidate_cutoff_to_sample_lookup(self):
        with patch("app.fetch_artist_samples", return_value=[{"id": 1}]) as fetch_samples:
            response = self.client.post(
                "/api/artist_samples",
                json={"artist_tag": "artist_a", "cutoff_date": "2026-06-15"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cutoff_date"], "2026-06-15")
        fetch_samples.assert_called_once_with("artist_a", [], 10, False, "2026-06-15")


if __name__ == "__main__":
    unittest.main()
