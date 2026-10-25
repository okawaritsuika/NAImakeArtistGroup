import gc
import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app


class StyleWorldcupApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.originals = {name: getattr(app, name) for name in (
            "DATA_DIR", "THUMBNAIL_DIR", "GENERATED_DIR", "CONFIRMED_STYLE_IMAGE_DIR",
            "COMPARISON_IMAGE_DIR", "ARCA_STYLE_IMAGE_DIR", "STYLE_GROUP_IMAGE_DIR",
            "SETTINGS_JSON_PATH", "DB_PATH", "ARCA_STYLE_SEED_PATH", "MERGE_SOURCE_DIRS", "ARCA_LOGIN_MANAGER",
        )}
        app.configure_data_directories([root], root)
        app.ARCA_STYLE_SEED_PATH = root / "missing-seed.sqlite"
        app.init_db()
        self.client = app.app.test_client()
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            for number in range(4):
                item_id = connection.execute(
                    "INSERT INTO arca_style_items(source_url,title,collected_at,updated_at,recommendation_count) "
                    "VALUES(?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/{number + 1}", f"공유 그림체 {number + 1}", "now", "now", number + 10),
                ).lastrowid
                name = f"sample-{number}.png"
                Image.new("RGB", (24, 32), (number * 60, 80, 120)).save(app.ARCA_STYLE_IMAGE_DIR / name)
                connection.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,"
                    "base_prompt,negative_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                    (item_id, f"https://example.invalid/{number}.png", name, "ok",
                     "1.2::artist:sample_artist, blue_hair::, landscape", "red hair", "now"),
                )

    def tearDown(self):
        for name, value in self.originals.items():
            setattr(app, name, value)
        gc.collect()
        self.temp.cleanup()

    def create(self, **overrides):
        return self.client.post("/api/style-worldcups", json={"name": "나의 월드컵", "size": 4, **overrides})

    def add_confirmed(self, count=2, *, grouped=False, model=""):
        app.CONFIRMED_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            for number in range(count):
                name = f"confirmed-{number}.png"
                if number == 0 or not grouped:
                    style_id = connection.execute(
                        "INSERT INTO confirmed_styles(name,image_path,artist_prompt,quality_prompt,fixed_prompt,"
                        "negative_prompt,original_quality_prompt,character_prompts_json,created_at,updated_at,model) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        ("확정 그림체", name, "1.2::artist:sample_artist::", "blue_hair", "landscape",
                         "red hair", "old quality", '[{"prompt":"character only"}]', "now", "now", model),
                    ).lastrowid
                Image.new("RGB", (24, 32), (40, number * 7 % 256, 150)).save(app.CONFIRMED_STYLE_IMAGE_DIR / name)
                connection.execute(
                    "INSERT INTO confirmed_style_images(style_id,image_path,position,created_at) VALUES(?,?,?,?)",
                    (style_id, name, number, "now"),
                )

    def test_sources_count_and_confirmed_current_base_prompt(self):
        self.add_confirmed()
        for sources, threshold, expected in (
            (["shared"], None, {"shared": 4, "confirmed": 0}),
            (["confirmed"], 1000, {"shared": 0, "confirmed": 2}),
            (["shared", "confirmed"], 11, {"shared": 2, "confirmed": 2}),
        ):
            response = self.client.post("/api/style-worldcups/preview", json={
                "sources": sources, "exclude_recommendation_lte": threshold,
                "include_tags": ["artist:sample artist", "blue hair", "landscape"],
                "exclude_tags": ["red hair", "old quality", "character only"],
            })
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json(), {"count": sum(expected.values()), "counts": expected})
        for tag in ("red hair", "old quality", "character only"):
            response = self.client.post("/api/style-worldcups/preview", json={
                "sources": ["confirmed"], "include_tags": [tag],
            })
            self.assertEqual(response.get_json()["count"], 0)

    def test_candidate_gallery_pages_and_auto_selection_use_both_image_routes(self):
        self.add_confirmed()
        payload = {"filters": {"sources": ["shared", "confirmed"]}, "per_page": 4}
        first = self.client.post("/api/style-worldcups/candidates", json=payload)
        self.assertEqual(first.status_code, 200, first.get_json())
        first = first.get_json()
        self.assertEqual(first["counts"], {"shared": 4, "confirmed": 2})
        self.assertEqual([item["key"] for item in first["items"]], [f"shared:{i}" for i in range(1, 5)])
        self.assertNotIn("selection", first)
        second = self.client.post("/api/style-worldcups/candidates", json={**payload, "page": 2, "auto_size": "all"}).get_json()
        self.assertEqual([item["key"] for item in second["items"]], ["confirmed:1", "confirmed:2"])
        self.assertEqual(len(second["selection"]), 6)
        for item in second["selection"]:
            self.assertEqual(set(item), {"key", "group_key", "detail_url", "title", "image_source", "image_url", "thumbnail_url", "model_label", "available", "recommendation_count"})
            prefix = "/confirmed-style-images/" if item["image_source"] == "confirmed" else "/arca-style-images/"
            self.assertTrue(item["image_url"].startswith(prefix))
            with self.client.get(item["image_url"]) as image_response:
                self.assertEqual(image_response.status_code, 200)
            with self.client.get(item["thumbnail_url"]) as thumbnail_response:
                self.assertEqual(thumbnail_response.status_code, 200)
                self.assertEqual(thumbnail_response.mimetype, "image/webp")
        sample = self.client.post("/api/style-worldcups/candidates", json={**payload, "auto_size": 4}).get_json()
        self.assertEqual(len({item["key"] for item in sample["selection"]}), 4)

    def test_reviewed_mixed_selection_keeps_exact_members_and_saved_result(self):
        self.add_confirmed()
        payload = {"sources": ["shared", "confirmed"], "auto_size": "all"}
        selected = self.client.post("/api/style-worldcups/candidates", json=payload).get_json()["selection"]
        kept = [item for item in selected if item["key"] in {"shared:2", "confirmed:1", "confirmed:2"}]
        response = self.create(size="all", sources=payload["sources"], selected_candidates=[item["key"] for item in kept])
        self.assertEqual(response.status_code, 201, response.get_json())
        cup = response.get_json()
        self.assertEqual(cup["size"], 3)
        self.assertEqual({item["image_url"] for item in cup["participants"]}, {item["image_url"] for item in kept})
        self.assertEqual({item["image_source"] for item in cup["participants"]}, {"shared", "confirmed"})
        participants = cup["participants"]
        cup_id = cup["id"]
        for revision in range(2):
            cup = self.client.get(f"/api/style-worldcups/{cup_id}").get_json()
            response = self.client.post(f"/api/style-worldcups/{cup_id}/choose", json={
                "revision": revision, "winner": cup["current_match"]["left"], "compact": True,
            })
            self.assertEqual(response.status_code, 200, response.get_json())
        saved = self.client.get(f"/api/style-worldcups/{cup_id}").get_json()
        self.assertEqual(saved["status"], "completed")
        self.assertEqual(saved["participants"], participants)
        self.assertEqual(len(saved["history"]), 2)
        summary = self.client.get("/api/style-worldcups").get_json()[0]
        self.assertEqual(summary["preview_participants"][0]["ordinal"], saved["winner"])
        self.assertEqual({item["image_url"] for item in summary["preview_participants"]}, {item["image_url"] for item in kept})

    def test_changed_candidate_selection_is_rejected_without_substitution(self):
        self.add_confirmed()
        sources = ["shared", "confirmed"]
        candidates = self.client.post("/api/style-worldcups/candidates", json={"sources": sources}).get_json()["items"]
        self.assertEqual(len(candidates), 6)
        (app.CONFIRMED_STYLE_IMAGE_DIR / "confirmed-0.png").unlink()
        for keys, filters in (
            (["shared:1", "confirmed:1"], {}),
            (["shared:1", "confirmed:2"], {"exclude_recommendation_lte": 10}),
            (["confirmed:2", "confirmed:2"], {}),
            (["shared:1"], {}),
        ):
            response = self.create(size="all", sources=sources, selected_candidates=keys, **filters)
            self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(self.client.get("/api/style-worldcups").get_json(), [])

    def test_candidate_gallery_rejects_invalid_pagination_and_sources(self):
        for payload in ({"page": 0}, {"per_page": 61}, {"per_page": True}, {"auto_size": 3},
                        {"auto_size": 8}, {"sources": []}, {"sources": ["unknown"]}, {"sources": "shared"}):
            response = self.client.post("/api/style-worldcups/candidates", json=payload)
            self.assertEqual(response.status_code, 400, (payload, response.get_json()))

    def test_gallery_count_selection_and_create_deduplicate_each_source_group(self):
        self.add_confirmed(count=3, grouped=True)
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_images SET item_id=1 WHERE id=2")
        payload = {"sources": ["shared", "confirmed"]}
        preview = self.client.post("/api/style-worldcups/preview", json=payload).get_json()
        self.assertEqual(preview, {"count": 4, "counts": {"shared": 3, "confirmed": 1}})
        gallery = self.client.post("/api/style-worldcups/candidates", json={**payload, "auto_size": "all"}).get_json()
        expected = {"shared:1", "shared:3", "shared:4", "confirmed:1"}
        self.assertEqual({item["key"] for item in gallery["items"]}, expected)
        self.assertEqual({item["key"] for item in gallery["selection"]}, expected)
        for keys in (["shared:1", "shared:2"], ["confirmed:1", "confirmed:2"]):
            response = self.create(size="all", **payload, selected_candidates=keys)
            self.assertEqual(response.status_code, 400, response.get_json())
        cup = self.create(size="all", **payload, selected_candidates=sorted(expected)).get_json()
        self.assertEqual(cup["size"], 4)
        self.assertEqual(len({item["image_url"] for item in cup["participants"]}), 4)

    def test_model_medium_filter_and_thumbnail_cache_preserve_original_image(self):
        self.add_confirmed(count=1, model="NovelAI Diffusion V5 93F4BD30")
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_images SET model='V5 Full Medium',model_family='v5',model_id='nai-diffusion-5-full-medium' WHERE id=1")
            connection.execute("UPDATE arca_style_images SET model='V5 Full',model_family='v5',model_id='nai-diffusion-5-full' WHERE id=2")
        Image.new("RGB", (1200, 1600), "blue").save(app.ARCA_STYLE_IMAGE_DIR / "sample-0.png")
        original = (app.ARCA_STYLE_IMAGE_DIR / "sample-0.png").read_bytes()
        payload = {"sources": ["shared", "confirmed"], "model": "nai-diffusion-5-full-medium"}
        self.assertEqual(self.client.post("/api/style-worldcups/preview", json=payload).get_json()["count"], 2)
        self.assertEqual(self.client.post("/api/style-worldcups/preview", json={**payload, "model": "v5"}).get_json()["count"], 3)
        gallery = self.client.post("/api/style-worldcups/candidates", json={**payload, "auto_size": "all"}).get_json()
        self.assertEqual({item["model_label"] for item in gallery["items"]}, {"V5 Full Medium"})
        shared = next(item for item in gallery["items"] if item["image_source"] == "shared")
        with self.client.get(shared["thumbnail_url"]) as thumbnail_response:
            self.assertEqual(thumbnail_response.status_code, 200)
            with Image.open(io.BytesIO(thumbnail_response.data)) as thumbnail:
                self.assertEqual(thumbnail.size, (288, 384))
            etag = thumbnail_response.headers["ETag"]
        with self.client.get(shared["thumbnail_url"], headers={"If-None-Match": etag}) as cached:
            self.assertEqual(cached.status_code, 304)
        self.assertEqual((app.ARCA_STYLE_IMAGE_DIR / "sample-0.png").read_bytes(), original)
        cup = self.create(size="all", **payload, selected_candidates=[item["key"] for item in gallery["selection"]]).get_json()
        self.assertEqual(cup["size"], 2)
        self.assertEqual(cup["filters"]["model"], payload["model"])
        self.assertEqual(self.client.post("/api/style-worldcups/preview", json={"model": "invalid"}).status_code, 400)

    def test_v5_full_source_hash_index_upgrade_restores_filter_without_changing_saved_cups(self):
        self.add_confirmed(count=1, model="NovelAI Diffusion V5 657484A5")
        hashes = ("0ADF9AB7", "657484A5", "DB276663", "ABCDEF12")
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            for image_id, source_hash in enumerate(hashes, 1):
                connection.execute(
                    "UPDATE arca_style_images SET model=?,model_id='',model_family='v5',model_generation='v5',model_variant='unknown' WHERE id=?",
                    ("NovelAI Diffusion V5 " + source_hash, image_id),
                )
            connection.execute("UPDATE arca_maintenance_state SET revision='model-columns-v2-medium' WHERE name='model_columns'")
            originals = connection.execute("SELECT id,model,base_prompt,negative_prompt,image_path FROM arca_style_images ORDER BY id").fetchall()
        before = self.client.post("/api/style-worldcups/preview", json={"model": "nai-diffusion-5-full"})
        self.assertEqual(before.get_json()["count"], 0)
        saved = self.create(size="all", model="v5").get_json()
        self.assertEqual(saved["size"], 4)
        app.init_arca_style_tables(app.DB_PATH)
        payload = {"sources": ["shared", "confirmed"], "model": "nai-diffusion-5-full"}
        preview = self.client.post("/api/style-worldcups/preview", json=payload).get_json()
        self.assertEqual(preview, {"count": 3, "counts": {"shared": 2, "confirmed": 1}})
        gallery = self.client.post("/api/style-worldcups/candidates", json={**payload, "auto_size": "all"}).get_json()
        self.assertEqual({row["key"] for row in gallery["items"]}, {"shared:1", "shared:2", "confirmed:1"})
        self.assertEqual({row["model_label"] for row in gallery["items"]}, {"V5 Full"})
        created = self.create(size="all", **payload, selection_scope="all", selected_candidates=[row["key"] for row in gallery["selection"]])
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertEqual(created.get_json()["size"], 3)
        curated = self.client.post("/api/style-worldcups/candidates", json={"model": "nai-diffusion-5-curated"}).get_json()
        self.assertEqual([row["key"] for row in curated["items"]], ["shared:3"])
        self.assertEqual(curated["items"][0]["model_label"], "V5 Curated")
        self.assertEqual(self.client.get(f"/api/style-worldcups/{saved['id']}").get_json(), saved)
        with closing(sqlite3.connect(app.DB_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT id,model,base_prompt,negative_prompt,image_path FROM arca_style_images ORDER BY id").fetchall(), originals)

    def test_recommendation_sort_and_existing_group_detail_urls(self):
        self.add_confirmed(count=2, grouped=True)
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_items SET recommendation_count=NULL WHERE id=1")
            connection.execute("UPDATE arca_style_images SET item_id=3 WHERE id=4")
        payload = {"sources": ["shared", "confirmed"], "sort": "recommendation_desc", "per_page": 2}
        first = self.client.post("/api/style-worldcups/candidates", json=payload).get_json()
        second = self.client.post("/api/style-worldcups/candidates", json={**payload, "page": 2}).get_json()
        self.assertEqual([item["key"] for item in first["items"] + second["items"]],
                         ["shared:3", "shared:2", "shared:1", "confirmed:1"])
        for item in (first["items"][0], second["items"][1]):
            detail_response = self.client.get(item["detail_url"])
            self.assertEqual(detail_response.status_code, 200)
            detail = detail_response.get_json()
            self.assertEqual(len(detail["images"]), 2)
            self.assertEqual(item["group_key"], f"{item['image_source']}:{detail['id']}")
            if item["image_source"] == "shared":
                self.assertIn("blue_hair", detail["images"][0]["base_prompt"])
            else:
                self.assertIn("sample_artist", detail["artist_prompt"])
        invalid = self.client.post("/api/style-worldcups/candidates", json={"sort": "unsupported"})
        self.assertEqual(invalid.status_code, 400)

    def test_all_selection_scope_preserves_reviewed_images_after_filter_changes(self):
        self.add_confirmed(count=2, grouped=True, model="V5 Full Medium")
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_images SET item_id=1 WHERE id=2")
        payload = {"size": "all", "sources": ["shared", "confirmed"], "selection_scope": "all",
                   "model": "v4.5", "exclude_tags": ["blue hair"], "exclude_recommendation_lte": 999,
                   "selected_candidates": ["shared:2", "confirmed:2"]}
        response = self.create(**payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        cup = response.get_json()
        self.assertEqual(cup["filters"]["selection_scope"], "all")
        self.assertEqual({row["image_url"] for row in cup["participants"]}, {
            "/arca-style-images/sample-1.png", "/confirmed-style-images/confirmed-1.png",
        })
        self.assertEqual(self.client.get(f"/api/style-worldcups/{cup['id']}").get_json(), cup)
        for overrides in ({"selection_scope": "filtered"}, {"selection_scope": "invalid"},
                          {"selected_candidates": ["shared:1", "shared:2"]},
                          {"selected_candidates": ["confirmed:1", "confirmed:2"]},
                          {"sources": ["shared"]}):
            rejected = self.create(**{**payload, **overrides})
            self.assertEqual(rejected.status_code, 400, rejected.get_json())
        del payload["selected_candidates"]
        self.assertEqual(self.create(**payload).status_code, 400)

    def test_nested_confirmed_image_is_served_without_allowing_path_escape(self):
        self.add_confirmed()
        nested = app.CONFIRMED_STYLE_IMAGE_DIR / "nested" / "sample #1.png"
        nested.parent.mkdir()
        nested.write_bytes((app.CONFIRMED_STYLE_IMAGE_DIR / "confirmed-0.png").read_bytes())
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE confirmed_style_images SET image_path=? WHERE id=1", ("nested/sample #1.png",))
        response = self.client.post("/api/style-worldcups/candidates", json={"sources": ["confirmed"]})
        self.assertEqual(response.status_code, 200, response.get_json())
        item = response.get_json()["items"][0]
        self.assertEqual(item["image_url"], "/confirmed-style-images/nested/sample%20%231.png")
        with self.client.get(item["image_url"]) as image_response:
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response.data, nested.read_bytes())
        for path in ("../outside.png", "nested/../../outside.png", "nested%5Csample.png"):
            self.assertEqual(self.client.get("/confirmed-style-images/" + path).status_code, 400)

    def test_preview_uses_base_prompt_and_strict_recommendation_boundary(self):
        response = self.client.post("/api/style-worldcups/preview", json={
            "include_artists": ["sample artist"], "include_tags": ["blue hair"],
            "exclude_tags": ["red hair"], "exclude_recommendation_lte": 11,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 2)
        response = self.client.post("/api/style-worldcups/preview", json={"include_tags": ["red hair"]})
        self.assertEqual(response.get_json()["count"], 0)

    def test_unified_tag_filters_accept_artist_and_general_tags_together(self):
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_images SET base_prompt=base_prompt || ', artist:blocked_artist' WHERE id=1")
            connection.execute("UPDATE arca_style_images SET negative_prompt=negative_prompt || ', artist:blocked_artist'")
        filters = {
            "include_tags": ["artist:sample artist", "blue hair"],
            "exclude_tags": ["artist:blocked artist", "red hair"],
        }
        response = self.client.post("/api/style-worldcups/preview", json=filters)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 3)
        response = self.create(size="all", **filters)
        self.assertEqual(response.status_code, 201, response.get_json())
        cup = response.get_json()
        self.assertEqual(cup["size"], 3)
        self.assertEqual(cup["filters"]["include_artists"], [])
        self.assertEqual(cup["filters"]["exclude_artists"], [])
        self.assertTrue(all("blocked_artist" not in entry["base_prompt"] for entry in cup["participants"]))

    def test_complete_reopen_and_create_independent_worldcup(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.get_json())
        cup = response.get_json()
        cup_id = cup["id"]
        for revision in range(3):
            cup = app.app.test_client().get(f"/api/style-worldcups/{cup_id}").get_json()
            self.assertEqual(cup["revision"], revision)
            self.assertEqual(cup["status"], "playing")
            response = self.client.post(f"/api/style-worldcups/{cup_id}/choose", json={
                "revision": revision, "winner": cup["current_match"]["left"],
            })
            self.assertEqual(response.status_code, 200, response.get_json())
        finished = response.get_json()
        self.assertEqual(finished["status"], "completed")
        self.assertIsNone(finished["current_match"])
        self.assertEqual(len(finished["history"]), 3)
        self.assertIn(finished["winner"], [entry["ordinal"] for entry in finished["participants"]])
        second = self.create().get_json()
        self.assertNotEqual(second["id"], cup_id)
        summaries = self.client.get("/api/style-worldcups").get_json()
        self.assertEqual(len(summaries), 2)
        self.assertEqual(self.client.get(f"/api/style-worldcups/{cup_id}").get_json(), finished)

    def test_stale_selection_does_not_advance_twice(self):
        cup = self.create().get_json()
        url = f"/api/style-worldcups/{cup['id']}/choose"
        payload = {"revision": 0, "winner": cup["current_match"]["left"]}
        self.assertEqual(self.client.post(url, json=payload).status_code, 200)
        self.assertEqual(self.client.post(url, json=payload).status_code, 409)
        current = self.client.get(f"/api/style-worldcups/{cup['id']}").get_json()
        self.assertEqual(current["revision"], 1)
        self.assertEqual(len(current["history"]), 1)

    def test_all_filtered_candidates_finish_with_bye_and_gallery_preview(self):
        filters = {"exclude_recommendation_lte": 10}
        preview = self.client.post("/api/style-worldcups/preview", json=filters).get_json()
        self.assertEqual(preview["count"], 3)
        response = self.create(size="all", **filters)
        self.assertEqual(response.status_code, 201, response.get_json())
        cup = response.get_json()
        self.assertEqual(cup["size"], 3)
        self.assertEqual(len(cup["participants"]), 3)
        self.assertEqual(cup["current_match"]["round_size"], 4)
        summary = self.client.get("/api/style-worldcups").get_json()[0]
        self.assertEqual(len(summary["preview_participants"]), 3)
        self.assertTrue(all(entry["image_url"].startswith("/arca-style-images/") for entry in summary["preview_participants"]))
        for revision in range(2):
            cup = self.client.get(f"/api/style-worldcups/{cup['id']}").get_json()
            response = self.client.post(f"/api/style-worldcups/{cup['id']}/choose", json={
                "revision": revision, "winner": cup["current_match"]["left"],
            })
            self.assertEqual(response.status_code, 200, response.get_json())
        cup = response.get_json()
        self.assertEqual(cup["status"], "completed")
        self.assertEqual(len(cup["history"]), 2)
        summary = self.client.get("/api/style-worldcups").get_json()[0]
        self.assertEqual(summary["preview_participants"][0]["ordinal"], cup["winner"])

    def test_exclusion_removes_the_whole_style_and_does_not_edit_prompt(self):
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("UPDATE arca_style_images SET base_prompt=base_prompt || ', artist:blocked_artist, monochrome' WHERE id=1")
            before = connection.execute("SELECT id,base_prompt FROM arca_style_images ORDER BY id").fetchall()
        for filters in ({"exclude_artists": ["blocked artist"]}, {"exclude_tags": ["monochrome"]}):
            response = self.create(size="all", **filters)
            self.assertEqual(response.status_code, 201, response.get_json())
            cup = response.get_json()
            self.assertEqual(cup["size"], 3)
            self.assertTrue(all("blocked_artist" not in item["base_prompt"] for item in cup["participants"]))
        with closing(sqlite3.connect(app.DB_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT id,base_prompt FROM arca_style_images ORDER BY id").fetchall(), before)

    def test_compact_selection_updates_next_match_and_keeps_full_saved_result(self):
        cup = self.create(size="all", exclude_recommendation_lte=10).get_json()
        cup_id = cup["id"]
        participants = cup["participants"]
        self.assertEqual(len(participants), 3)
        self.assertNotIn("participants_partial", cup)
        for revision in range(2):
            payload = {"revision": revision, "winner": cup["current_match"]["left"], "compact": True}
            response = self.client.post(f"/api/style-worldcups/{cup_id}/choose", json=payload)
            self.assertEqual(response.status_code, 200, response.get_json())
            cup = response.get_json()
            self.assertTrue(cup["participants_partial"])
            expected = {cup["current_match"]["left"], cup["current_match"]["right"]} if cup["current_match"] else {cup["winner"]}
            self.assertEqual({entry["ordinal"] for entry in cup["participants"]}, expected)
            self.assertTrue(all(entry in participants for entry in cup["participants"]))
            self.assertEqual(self.client.post(f"/api/style-worldcups/{cup_id}/choose", json=payload).status_code, 409)
        self.assertEqual(cup["status"], "completed")
        self.assertEqual(len(cup["history"]), 2)
        saved = self.client.get(f"/api/style-worldcups/{cup_id}").get_json()
        self.assertNotIn("participants_partial", saved)
        self.assertEqual(saved["participants"], participants)
        self.assertEqual(saved["history"], cup["history"])
        self.assertEqual(saved["winner"], cup["winner"])

    def test_all_still_requires_two_matching_candidates(self):
        for threshold in (12, 13):
            response = self.create(size="all", exclude_recommendation_lte=threshold)
            self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(self.client.get("/api/style-worldcups").get_json(), [])

    def test_invalid_json_input_and_missing_worldcup(self):
        for value in ([], "wrong", False, None):
            for url in ("/api/style-worldcups", "/api/style-worldcups/preview", "/api/style-worldcups/candidates", "/api/style-worldcups/1/choose"):
                self.assertEqual(self.client.post(url, json=value).status_code, 400)
        self.assertEqual(self.client.get("/api/style-worldcups/9999").status_code, 404)
        self.assertEqual(self.client.post("/api/style-worldcups/9999/choose", json={"revision": 0, "winner": 0}).status_code, 404)
        self.assertEqual(self.create(size=8).status_code, 400)
        self.assertEqual(self.client.get("/api/style-worldcups").get_json(), [])

    def test_database_error_is_safe_for_ui(self):
        with patch("app.list_worldcups", side_effect=sqlite3.OperationalError("sensitive path")):
            response = self.client.get("/api/style-worldcups")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sensitive", response.get_data(as_text=True))

    def test_saved_snapshot_survives_source_metadata_removal(self):
        cup = self.create(size=2).get_json()
        with closing(sqlite3.connect(app.DB_PATH)) as connection, connection:
            connection.execute("DELETE FROM arca_style_images")
            connection.execute("DELETE FROM arca_style_items")
        saved = self.client.get(f"/api/style-worldcups/{cup['id']}").get_json()
        self.assertEqual(saved["participants"], cup["participants"])
        image_url = saved["participants"][0]["image_url"]
        with self.client.get(image_url) as response:
            self.assertEqual(response.status_code, 200)

    def test_header_template_and_assets_are_connected(self):
        html = self.client.get("/").get_data(as_text=True)
        for marker in ('data-tab="style-worldcup"', 'id="style-worldcup-tab"',
                       '/static/style_worldcup.js', '/static/style_worldcup.css'):
            self.assertIn(marker, html)
        self.assertEqual(html.count('id="worldcupForm"'), 1)


if __name__ == "__main__":
    unittest.main()
