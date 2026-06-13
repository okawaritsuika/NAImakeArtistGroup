import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class CandidateFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        app.DATA_DIR = self.tmp
        app.THUMBNAIL_DIR = self.tmp / "thumbnails"
        app.DB_PATH = self.tmp / "artist_rater.sqlite"
        app.init_db()
        self.client = app.app.test_client()

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
        fetch_samples.assert_called_once_with("artist_a", ["school_uniform"], 10)

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


if __name__ == "__main__":
    unittest.main()
