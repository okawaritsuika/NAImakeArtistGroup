import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app
from arca_style_collector import get_shared_style_dependency_images, init_arca_style_tables


def _dependency_images():
    return [
        {
            "id": 11,
            "item_id": 1,
            "title": "reference",
            "source_url": "https://arca.live/b/aiart/11",
            "artists": [
                {"artist": "ref_low", "weight": 0.5},
                {"artist": "ref_high", "weight": 1.7},
                {"artist": "ref_mid", "weight": 1.0},
                {"artist": "ref_last", "weight": 0.8},
            ],
            "scale": 7,
            "cfg_rescale": 0.25,
        },
        {
            "id": 12,
            "item_id": 2,
            "title": "other",
            "source_url": "https://arca.live/b/aiart/12",
            "artists": [
                {"artist": "other_a", "weight": 1.2},
                {"artist": "ref_low", "weight": 1.1},
            ],
            "scale": None,
            "cfg_rescale": None,
        },
    ]


class SharedDependencyCollectorTest(unittest.TestCase):
    def test_image_prompt_artists_and_metadata_are_filtered_and_normalized(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "arca.sqlite"
            init_arca_style_tables(path)
            now = "2026-08-15T00:00:00"
            with closing(app.sqlite3.connect(path)) as conn, conn:
                conn.row_factory = app.sqlite3.Row
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,board_tab,title,metadata_status,collected_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("https://arca.live/b/aiart/1", "NAI", "공유 그림체", "ok", now, now),
                )
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,base_prompt,scale,cfg_rescale,created_at) VALUES(?,?,?,?,?,?,?)",
                    (1, "https://img/1.png", "ok", "artist:first, 1.7::artist:weighted::, masterpiece, artist:plain", 5, 0, now),
                )
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,board_tab,title,metadata_status,collected_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("https://arca.live/b/aiart/2", "NAI", "개인 제목", "ok", now, now),
                )
                conn.execute(
                    "INSERT INTO arca_collection_jobs(request_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (json.dumps({"source_url": "https://arca.live/b/aiart/2"}), "done", "done", now, now),
                )
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,scale,cfg_rescale,created_at) VALUES(?,?,?,?,?,?,?)",
                    (2, "https://img/2.png", "ok", "artist:direct_only", 6, 0.3, now),
                )
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,board_tab,title,metadata_status,collected_at,updated_at) VALUES(?,?,?,?,?,?)",
                    ("https://arca.live/b/aiart/3", "NAI", "공유 그림체", "ok", now, now),
                )
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,created_at) VALUES(?,?,?,?,?)",
                    (3, "https://img/3.png", "none", "artist:ignored", now),
                )
            result = get_shared_style_dependency_images(path)
            self.assertEqual([item["id"] for item in result], [1, 2])
            self.assertEqual(
                [(item["artist"], item["weight"]) for item in result[0]["artists"]],
                [("first", 1.0), ("weighted", 1.7), ("plain", 1.0)],
            )
            self.assertEqual((result[0]["scale"], result[0]["cfg_rescale"]), (5, 0))
            self.assertEqual((result[1]["scale"], result[1]["cfg_rescale"]), (6, 0.3))


class SharedDependencyApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original = (app.DATA_DIR, app.DB_PATH, app.THUMBNAIL_DIR, app.GENERATED_DIR, app.ARCA_STYLE_SEED_PATH)
        app.DATA_DIR = root
        app.DB_PATH = root / "artist.sqlite"
        app.THUMBNAIL_DIR = root / "thumbnails"
        app.GENERATED_DIR = root / "generated"
        app.ARCA_STYLE_SEED_PATH = root / "missing.sqlite"
        app.init_db()
        now = app.now_text()
        with closing(app.db()) as conn, conn:
            for artist, score in (("rated_a", 5), ("rated_b", 4), ("rated_c", 2)):
                conn.execute(
                    "INSERT INTO ratings(artist_tag,score,mode,query_tags_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (artist, score, "manual", "[]", now, now),
                )
        self.client = app.app.test_client()

    def tearDown(self):
        app.DATA_DIR, app.DB_PATH, app.THUMBNAIL_DIR, app.GENERATED_DIR, app.ARCA_STYLE_SEED_PATH = self.original
        self.temp_dir.cleanup()

    def _post(self, **payload):
        base = {
            "count": 99,
            "scores": [1, 2, 3, 4, 5],
            "weight_mode": "shared_dependency",
            "shared_dependency_source_ratios": {"fixed": 0, "reference": 100, "rated": 0, "other_shared": 0},
            "shared_dependency_reference_id": 11,
            "rng_seed": 8,
        }
        base.update(payload)
        return self.client.post("/api/style-maker/artists", json=base)

    def test_reference_count_ignores_style_artist_count_and_preserves_order_weights(self):
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(count=1)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 4)
        self.assertEqual([item["artist"] for item in artists], ["ref_low", "ref_high", "ref_mid", "ref_last"])
        self.assertEqual([item["weight"] for item in artists], [0.5, 1.7, 1.0, 0.8])

    def test_reference_artist_policy_random_does_not_force_highest_weight(self):
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(
                shared_dependency_artist_policy="random",
                shared_dependency_source_ratios={"fixed": 0, "reference": 50, "rated": 50, "other_shared": 0},
                rng_seed=2,
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 4)
        self.assertNotIn("ref_high", {item["artist"] for item in artists})
        self.assertEqual(response.get_json()["shared_dependency_artist_policy"], "random")

    def test_reference_artist_policy_rejects_unknown_value(self):
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(shared_dependency_artist_policy="weighted")
        self.assertEqual(response.status_code, 400)

    def test_largest_remainder_allocates_four_sources_exactly(self):
        fixed = [{"artist": "fixed_a", "weight": 2.2, "slot": 2}]
        ratios = {"fixed": 25, "reference": 25, "rated": 25, "other_shared": 25}
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(shared_dependency_source_ratios=ratios, fixed_artists=fixed)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 4)
        self.assertEqual(len({item["artist"].casefold() for item in artists}), 4)
        self.assertEqual(artists[1]["artist"], "fixed_a")
        self.assertEqual(artists[1]["weight"], 2.2)
        self.assertEqual({item.get("shared_dependency_source") for item in artists}, {"fixed", "reference", "rated", "other_shared"})

    def test_fixed_subset_is_seeded_and_fixed_fields_are_preserved(self):
        fixed = [
            {"artist": "fixed_a", "weight": 2.2, "slot": 1, "random_weight": True},
            {"artist": "fixed_b", "weight": 1.8, "slot": 0},
            {"artist": "fixed_c", "weight": 1.4},
        ]
        ratios = {"fixed": 50, "reference": 50, "rated": 0, "other_shared": 0}
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            first = self._post(shared_dependency_source_ratios=ratios, fixed_artists=fixed, rng_seed=33).get_json()["artists"]
            second = self._post(shared_dependency_source_ratios=ratios, fixed_artists=fixed, rng_seed=33).get_json()["artists"]
        self.assertEqual(first, second)
        selected = [item for item in first if item["artist"].startswith("fixed_")]
        self.assertEqual(len(selected), 2)
        for item in selected:
            source = next(row for row in fixed if row["artist"] == item["artist"])
            self.assertEqual(item["weight"], source["weight"])
            if "slot" in source:
                self.assertEqual(item.get("slot"), source["slot"])
            if source.get("random_weight"):
                self.assertTrue(item.get("random_weight"))

    def test_fixed_overlap_wins_and_reference_highest_is_already_satisfied(self):
        fixed = [{"artist": "ref_high", "weight": 2.2, "slot": 2}]
        ratios = {"fixed": 25, "reference": 75, "rated": 0, "other_shared": 0}
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(shared_dependency_source_ratios=ratios, fixed_artists=fixed)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 4)
        self.assertEqual(artists[1]["artist"], "ref_high")
        self.assertEqual(artists[1]["weight"], 2.2)
        self.assertEqual(len({item["artist"] for item in artists}), 4)

    def test_out_of_range_and_conflicting_fixed_slots_never_drop_selected_fixed(self):
        fixed = [
            {"artist": "fixed_a", "weight": 2.2, "slot": 2},
            {"artist": "fixed_b", "weight": 1.8, "slot": 2},
            {"artist": "fixed_c", "weight": 1.4, "slot": 99},
        ]
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            response = self._post(
                shared_dependency_source_ratios={"fixed": 75, "reference": 25, "rated": 0, "other_shared": 0},
                fixed_artists=fixed,
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 4)
        self.assertEqual({item["artist"] for item in artists if item["artist"].startswith("fixed_")}, {item["artist"] for item in fixed})
        self.assertEqual(artists[1]["artist"], "fixed_a")

    def test_shortage_redistributes_to_nonzero_sources_and_errors_when_impossible(self):
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            redistributed = self._post(shared_dependency_source_ratios={"fixed": 50, "reference": 50, "rated": 0, "other_shared": 0})
            impossible = self._post(shared_dependency_source_ratios={"fixed": 0, "reference": 0, "rated": 100, "other_shared": 0})
        self.assertEqual(redistributed.status_code, 200, redistributed.get_data(as_text=True))
        self.assertEqual(len(redistributed.get_json()["artists"]), 4)
        self.assertEqual(impossible.status_code, 400)
        self.assertIn("공급원 후보", impossible.get_json()["error"])

    def test_validation_rejects_aliases_types_bad_sum_and_unknown_reference(self):
        with patch.object(app, "get_shared_style_dependency_images", return_value=_dependency_images()):
            self.assertEqual(self._post(shared_dependency_reference_id=999).status_code, 400)
            self.assertEqual(self._post(shared_dependency_percent=50).status_code, 400)
            self.assertEqual(self._post(shared_dependency_source_ratios={"fixed": "50", "reference": 50, "rated": 0, "other_shared": 0}).status_code, 400)
            self.assertEqual(self._post(shared_dependency_source_ratios={"fixed": 20, "reference": 20, "rated": 20, "other_shared": 20}).status_code, 400)

    def test_generation_scale_and_cfg_fallback_are_independent(self):
        payload = {
            "request_id": "shared-dependency-test",
            "weight_mode": "shared_dependency",
            "shared_dependency_reference_id": 11,
            "artists": [{"artist": "alpha", "weight": 1}],
            "base_prompt": "", "quality_prompt": "", "original_quality_prompt": "", "fixed_prompt": "",
            "negative_prompt": "", "character_prompts": [], "width": 832, "height": 1216,
            "sampler": "k_euler_ancestral", "noise_schedule": "karras", "steps": 28,
            "scale": 5, "cfg_rescale": 0.8, "variety_plus": False,
        }
        images = _dependency_images()
        images[0]["scale"] = None
        images[0]["cfg_rescale"] = 0.25
        with patch.object(app, "get_shared_style_dependency_images", return_value=images):
            normalized = app._validate_generation_request(payload)
        self.assertEqual(normalized["scale"], 5)
        self.assertEqual(normalized["cfg_rescale"], 0.25)
        self.assertEqual(normalized["shared_dependency_scale_source"], "fallback")
        self.assertEqual(normalized["shared_dependency_cfg_rescale_source"], "reference")
        self.assertEqual(
            normalized["shared_dependency_reference"],
            {
                "id": 11,
                "title": "reference",
                "source_url": "https://arca.live/b/aiart/11",
            },
        )

    def test_reroll_lifecycle_and_blocked_highest_are_safe(self):
        images = _dependency_images()
        with patch.object(app, "get_shared_style_dependency_images", return_value=images):
            all_response = self._post(reroll="all", rng_seed=0)
            weight_response = self._post(reroll="weights", artists=[{"artist": "current", "weight": 1.0}], rng_seed=0)
        self.assertEqual(all_response.status_code, 200, all_response.get_data(as_text=True))
        self.assertEqual(all_response.get_json()["shared_dependency_reference_id"], 12)
        self.assertEqual(weight_response.status_code, 200, weight_response.get_data(as_text=True))
        self.assertEqual(weight_response.get_json()["shared_dependency_reference_id"], 11)

        with patch.object(app, "get_shared_style_dependency_images", return_value=images):
            fixed_all = self._post(reroll="all", shared_dependency_reference_mode="fixed")
            fixed_artists = self._post(
                reroll="artists",
                artists=[{"artist": "old", "weight": 1.0}],
                shared_dependency_reference_mode="fixed",
            )
        self.assertEqual(fixed_all.status_code, 200, fixed_all.get_data(as_text=True))
        self.assertEqual(fixed_all.get_json()["shared_dependency_reference_id"], 11)
        self.assertEqual(fixed_artists.status_code, 200, fixed_artists.get_data(as_text=True))
        self.assertEqual(fixed_artists.get_json()["shared_dependency_reference_id"], 11)

        one_reference = [images[0]]
        with patch.object(app, "get_shared_style_dependency_images", return_value=one_reference):
            response = self._post(
                reroll="artists",
                artists=[{"artist": "ref_high", "weight": 1.1}, {"artist": "old_random", "weight": 0.8}],
                shared_dependency_source_ratios={"fixed": 0, "reference": 75, "rated": 25, "other_shared": 0},
                rng_seed=3,
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        names = {item["artist"] for item in response.get_json()["artists"]}
        self.assertEqual(len(names), 4)
        self.assertNotIn("ref_high", names)
        self.assertIn("ref_mid", names)


if __name__ == "__main__":
    unittest.main()
