import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from PIL import Image

from arca_style_collector import init_arca_style_tables
from confirmed_style_store import init_confirmed_style_tables
from novelai_metadata import classify_model
import style_worldcup_store
from style_worldcup_store import (
    WorldcupConflict, choose_winner, create_worldcup, get_worldcup,
    init_worldcup_tables, list_candidates, list_worldcups, preview_candidates,
)


class WorldcupStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "test.sqlite"
        self.images = self.root / "arca_style_images"
        self.images.mkdir()
        self.confirmed_images = self.root / "confirmed_style_images"
        self.confirmed_images.mkdir()
        init_arca_style_tables(self.db)
        init_confirmed_style_tables(self.db)
        init_worldcup_tables(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def add_image(self, prompt="artist:example, watercolor", recommendation=10,
                  base=None, negative="", characters="[]", image_path=None,
                  local=True, status="ok", item_status="ok", item_id=None, model=""):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            number = connection.execute("SELECT COUNT(*) FROM arca_style_images").fetchone()[0] + 1
            if item_id is None:
                item_id = connection.execute(
                    "INSERT INTO arca_style_items(source_url,title,metadata_status,recommendation_count,collected_at,updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/{number}", f"그림체 {number}", item_status, recommendation, "now", "now"),
                ).lastrowid
            image_path = image_path if image_path is not None else f"image-{number}.png"
            image_id = connection.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,prompt,base_prompt,negative_prompt,character_prompts_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, f"https://image.example/{number}.png", image_path, status,
                 prompt, prompt if base is None else base, negative, characters, "now"),
            ).lastrowid
            model_fields = classify_model(model)
            connection.execute("UPDATE arca_style_images SET model=?,model_id=?,model_family=? WHERE id=?",
                               (model, model_fields["model_id"], model_fields["model_family"], image_id))
        if local:
            path = self.images / image_path
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (2, 2), (number % 255, 0, 0)).save(path, format="PNG")
        return item_id

    def add_confirmed(self, artist="artist:confirmed", quality="watercolor", fixed="",
                      original_quality="", negative="", characters="[]", raw_metadata="{}",
                      paths=None, local=True, model=""):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            number = connection.execute("SELECT COUNT(*) FROM confirmed_styles").fetchone()[0] + 1
            paths = paths if paths is not None else [f"confirmed-{number}.png"]
            style_id = connection.execute(
                "INSERT INTO confirmed_styles(name,image_path,artist_prompt,quality_prompt,fixed_prompt,"
                "original_quality_prompt,negative_prompt,character_prompts_json,raw_metadata_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (f"확정 그림체 {number}", paths[0], artist, quality, fixed, original_quality,
                 negative, characters, raw_metadata, "now", "now"),
            ).lastrowid
            connection.execute("UPDATE confirmed_styles SET model=? WHERE id=?", (model, style_id))
            connection.executemany(
                "INSERT INTO confirmed_style_images(style_id,image_path,position,created_at) VALUES(?,?,?,?)",
                [(style_id, path, ordinal, "now") for ordinal, path in enumerate(paths)],
            )
        if local:
            for relative in paths:
                path = self.confirmed_images / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (2, 2), (0, number % 255, 0)).save(path, format="PNG")
        return style_id

    def preview(self, confirmed_image_root=None, **filters):
        return preview_candidates(self.db, self.images, filters, confirmed_image_root=confirmed_image_root)["count"]

    def create(self, size=2, confirmed_image_root=None, **payload):
        return create_worldcup(
            self.db, self.images, {"name": "저장 월드컵", "size": size, **payload},
            confirmed_image_root=confirmed_image_root,
        )

    def test_filters_parse_weights_match_complete_tags_and_ignore_other_prompts(self):
        self.add_image(
            "ignored legacy", base="1.2::artist:Alpha_One, watercolor::, {{Blue Hair}}, [soft lighting], artist:Beta",
            negative="monochrome, artist:negative", characters='[{"prompt":"character tag"}]',
        )
        self.add_image("artist:alphabet, watercolor painting, blue hair")
        self.add_image("artist:alpha_one, watercolor", base="artist:other, sketch")
        self.assertEqual(self.preview(include_artists=["ARTISTS: ALPHA ONE", "beta"], include_tags=["blue_hair", "WATERCOLOR"]), 1)
        self.assertEqual(self.preview(include_tags=["watercolor"]), 1)
        self.assertEqual(self.preview(include_artists=["alpha"]), 0)
        self.assertEqual(self.preview(include_tags=["monochrome"]), 0)
        self.assertEqual(self.preview(include_tags=["character tag"]), 0)
        self.assertEqual(self.preview(exclude_tags=["missing", "watercolor"]), 2)
        self.assertEqual(self.preview(exclude_artists=["missing", "beta"]), 2)
        self.assertEqual(self.preview(include_artists="alpha_one, beta", include_tags="blue hair\nwatercolor"), 1)

    def test_legacy_fallback_and_image_metadata_are_independent_of_item_metadata(self):
        self.add_image("artist:legacy, ink", base="", item_status="none")
        self.add_image("artist:legacy, ink", status="none")
        self.assertEqual(self.preview(include_artists=["legacy"]), 1)

    def test_unified_artist_tags_normalize_prefix_spacing_and_plural_without_changing_general_tags(self):
        variants = ["artist:alpha_one", "artist: alpha_one", "artists:alpha_one", "ARTISTS :  Alpha One"]
        for tag in variants:
            self.add_image(f"1.2::{tag}::, blue_hair, style: watercolor")
        self.add_image("artist:alphabet, blue hair, style:watercolor")
        self.add_image("artist:other, blue hair", negative="artist:alpha_one")
        for tag in variants:
            with self.subTest(tag=tag):
                self.assertEqual(self.preview(include_tags=[tag]), 4)
                self.assertEqual(self.preview(exclude_tags=[tag]), 2)
        self.assertEqual(self.preview(include_artists=["alpha one"]), 4)
        self.assertEqual(self.preview(exclude_artists=["alpha one"]), 2)
        self.assertEqual(self.preview(include_tags=["artist:alpha"]), 0)
        self.assertEqual(self.preview(include_tags=["BLUE_HAIR"]), 6)
        self.assertEqual(self.preview(include_tags=["style: watercolor"]), 4)
        self.assertEqual(self.preview(include_tags=["style:watercolor"]), 1)
        cup = self.create(size="all", include_tags=variants)
        self.assertEqual(cup["filters"]["include_tags"], ["artist:alpha one"])
        self.assertEqual(cup["size"], 4)

    def test_recommendation_threshold_is_strict_and_excludes_unknown_only_when_set(self):
        for recommendation in (None, 0, 5, 6):
            self.add_image(recommendation=recommendation)
        self.assertEqual(self.preview(), 4)
        self.assertEqual(self.preview(exclude_recommendation_lte=5), 1)
        self.assertEqual(self.preview(exclude_recommendation_lte=0), 2)

    def test_only_safe_existing_files_are_available_and_urls_are_encoded(self):
        self.add_image(image_path="nested/a #한글.png")
        self.add_image(local=False)
        self.add_image(image_path="../outside.png")
        self.add_image(image_path=str(self.root / "absolute.png"), local=False)
        self.add_image(image_path="nested\\windows.png", local=False)
        self.add_image(image_path="image.png:stream", local=False)
        self.add_image(image_path="second.png")
        self.assertEqual(self.preview(), 2)
        cup = self.create()
        self.assertTrue(any("a%20%23%ED%95%9C%EA%B8%80.png" in row["image_url"] for row in cup["participants"]))
        for row in cup["participants"]:
            self.assertTrue(row["available"])
            self.assertNotIn("image_path", row)

    def test_invalid_payloads_and_limits_are_rejected(self):
        for payload in (None, [], {"filters": []}, {"include_tags": None},
                        {"include_tags": ["x"] * 51}, {"include_tags": ["x" * 201]},
                        {"include_artists": [True]}, {"exclude_recommendation_lte": True},
                        {"exclude_recommendation_lte": 1.5}, {"exclude_recommendation_lte": "5"},
                        {"exclude_recommendation_lte": -1}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                preview_candidates(self.db, self.images, payload)
        for size in (True, 2.0, "2", 0, 1, 3, 129, "ALL"):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.create(size=size)
        with self.assertRaises(ValueError):
            self.create(name="x" * 201)

    def test_insufficient_candidates_leave_no_partial_tournament(self):
        self.add_image()
        with self.assertRaisesRegex(ValueError, "부족"):
            self.create()
        self.assertEqual(list_worldcups(self.db, self.images), [])
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcup_participants").fetchone()[0], 0)

    def test_complete_resume_and_new_tournament_preserve_snapshots(self):
        for number in range(4):
            self.add_image(prompt=f"artist:artist_{number}, ink")
        cup = self.create(size=4, filters={"include_tags": ["ink"]})
        original_participants = cup["participants"]
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": 1})
        resumed = get_worldcup(self.db, self.images, cup["id"])
        self.assertEqual(resumed, cup)
        self.assertEqual(cup["current_match"], {"left": 2, "right": 3, "round_size": 4, "match_number": 2, "matches_in_round": 2})
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 1, "winner": 2})
        self.assertEqual(cup["current_match"]["round_size"], 2)
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 2, "winner": 1})
        self.assertEqual((cup["status"], cup["revision"], cup["winner"]), ("completed", 3, 1))
        self.assertIsNone(cup["current_match"])
        self.assertEqual([row["round_size"] for row in cup["history"]], [4, 4, 2])
        self.assertEqual(cup["participants"], original_participants)
        new_cup = self.create(size=4)
        self.assertNotEqual(new_cup["id"], cup["id"])
        self.assertEqual(new_cup["history"], [])
        summaries = list_worldcups(self.db, self.images)
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[1]["winner"], original_participants[1])
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM arca_style_images")
            connection.execute("DELETE FROM arca_style_items")
        for path in self.images.glob("*.png"):
            path.unlink()
        saved = get_worldcup(self.db, self.images, cup["id"])
        self.assertEqual(saved["winner"], 1)
        self.assertEqual(saved["participants"][1]["base_prompt"], original_participants[1]["base_prompt"])
        self.assertFalse(saved["participants"][1]["available"])
        self.assertEqual(saved["participants"][1]["image_url"], "")

    def test_duplicate_stale_invalid_and_missing_selections_do_not_advance(self):
        for _ in range(4):
            self.add_image()
        cup = self.create(size=4)
        for payload in ({"revision": 0, "winner": 2}, {"revision": True, "winner": 0},
                        {"revision": 0, "winner": 0.0}, {"revision": 0, "winner": True}):
            with self.assertRaises(ValueError):
                choose_winner(self.db, self.images, cup["id"], payload)
        self.assertEqual(get_worldcup(self.db, self.images, cup["id"])["revision"], 0)
        chosen = choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": 0})
        with self.assertRaises(WorldcupConflict):
            choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": 1})
        self.assertEqual(get_worldcup(self.db, self.images, cup["id"]), chosen)
        with self.assertRaises(LookupError):
            choose_winner(self.db, self.images, 99999, {"revision": 0, "winner": 0})
        self.assertIsNone(get_worldcup(self.db, self.images, 99999))

    def test_concurrent_choices_commit_exactly_once(self):
        self.add_image()
        self.add_image()
        cup = self.create()
        barrier = Barrier(2)

        def choose(ordinal):
            barrier.wait(timeout=5)
            try:
                choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": ordinal})
                return "saved"
            except WorldcupConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(choose, [0, 1]))
        self.assertCountEqual(results, ["saved", "conflict"])
        saved = get_worldcup(self.db, self.images, cup["id"])
        self.assertEqual((saved["revision"], len(saved["history"])), (1, 1))
        with self.assertRaises(WorldcupConflict):
            choose_winner(self.db, self.images, cup["id"], {"revision": 1, "winner": 0})

    def test_all_candidates_with_byes_complete_in_n_minus_one_choices(self):
        for count in (3, 5, 6, 129):
            with self.subTest(count=count):
                expected_sources = set()
                for _ in range(count):
                    number = self.add_image(prompt=f"artist:example, cohort {count}")
                    expected_sources.add(f"https://arca.live/b/aiart/{number}")
                cup = self.create(size="all", include_tags=[f"cohort {count}"])
                self.assertEqual(cup["size"], count)
                self.assertEqual(len(cup["participants"]), count)
                self.assertEqual({row["source_url"] for row in cup["participants"]}, expected_sources)
                self.assertEqual({row["ordinal"] for row in cup["participants"]}, set(range(count)))
                round_size = 1 << (count - 1).bit_length()
                self.assertEqual(cup["current_match"]["round_size"], round_size)
                self.assertEqual(cup["current_match"]["bye_count"], round_size - count)
                self.assertEqual(cup["current_match"]["matches_in_round"], count - round_size // 2)
                appeared = set()
                while cup["status"] == "playing":
                    match = cup["current_match"]
                    appeared.update((match["left"], match["right"]))
                    cup = choose_winner(self.db, self.images, cup["id"], {
                        "revision": cup["revision"], "winner": max(match["left"], match["right"]),
                    })
                self.assertEqual(appeared, set(range(count)))
                self.assertEqual((cup["revision"], len(cup["history"])), (count - 1, count - 1))
                self.assertEqual(cup["winner"], count - 1)
                self.assertEqual(cup["history"][0]["round_size"], round_size)
                self.assertEqual(cup["history"][-1]["round_size"], 2)

    def test_numeric_size_above_128_is_supported_and_still_requires_enough_images(self):
        with self.assertRaisesRegex(ValueError, "부족"):
            self.create(size=256)
        for _ in range(256):
            self.add_image()
        cup = self.create(size=256)
        self.assertEqual(cup["size"], 256)
        self.assertEqual(len(cup["participants"]), 256)
        self.assertEqual(cup["current_match"]["matches_in_round"], 128)
        self.assertNotIn("bye_count", cup["current_match"])

    def test_odd_tournament_resumes_mid_round_and_stale_selection_cannot_advance(self):
        for _ in range(7):
            self.add_image()
        cup = self.create(size="all")
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": 1})
        resumed = get_worldcup(self.db, self.images, cup["id"])
        self.assertEqual(resumed, cup)
        self.assertEqual(resumed["current_match"], {
            "left": 2, "right": 3, "round_size": 8, "match_number": 2,
            "matches_in_round": 3, "bye_count": 1,
        })
        with self.assertRaises(WorldcupConflict):
            choose_winner(self.db, self.images, cup["id"], {"revision": 0, "winner": 0})
        self.assertEqual(get_worldcup(self.db, self.images, cup["id"]), resumed)
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 1, "winner": 2})
        cup = choose_winner(self.db, self.images, cup["id"], {"revision": 2, "winner": 5})
        self.assertEqual(cup["current_match"]["round_size"], 4)
        self.assertNotIn("bye_count", cup["current_match"])
        with closing(sqlite3.connect(self.db)) as connection:
            state = json.loads(connection.execute("SELECT state_json FROM style_worldcups WHERE id=?", (cup["id"],)).fetchone()[0])
        self.assertEqual(state["round"], [1, 2, 5, 6])

    def test_legacy_state_without_byes_or_round_size_resumes(self):
        for _ in range(4):
            self.add_image()
        cup = self.create(size=4)
        legacy = {"round": [0, 1, 2, 3], "next_round": [1], "winner": None,
                  "history": [{"round_size": 4, "left": 0, "right": 1, "winner": 1}]}
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE style_worldcups SET state_json=?,revision=1 WHERE id=?", (json.dumps(legacy), cup["id"]))
        resumed = get_worldcup(self.db, self.images, cup["id"])
        self.assertEqual(resumed["current_match"], {"left": 2, "right": 3, "round_size": 4, "match_number": 2, "matches_in_round": 2})
        resumed = choose_winner(self.db, self.images, cup["id"], {"revision": 1, "winner": 3})
        resumed = choose_winner(self.db, self.images, cup["id"], {"revision": 2, "winner": 3})
        self.assertEqual((resumed["status"], resumed["winner"], resumed["revision"]), ("completed", 3, 3))

    def test_all_requires_at_least_two_candidates_without_partial_storage(self):
        for count in (0, 1):
            with self.subTest(count=count):
                if count:
                    self.add_image()
                with self.assertRaisesRegex(ValueError, "2장 이상"):
                    self.create(size="all")
                self.assertEqual(list_worldcups(self.db, self.images), [])
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcup_participants").fetchone()[0], 0)

    def test_gallery_previews_contain_four_unique_participants_and_winner_first(self):
        for _ in range(5):
            self.add_image()
        cup = self.create(size="all")
        summary = list_worldcups(self.db, self.images)[0]
        self.assertIsNone(summary["winner"])
        self.assertEqual(summary["preview_participants"], cup["participants"][:4])
        while cup["status"] == "playing":
            match = cup["current_match"]
            cup = choose_winner(self.db, self.images, cup["id"], {
                "revision": cup["revision"], "winner": max(match["left"], match["right"]),
            })
        summary = list_worldcups(self.db, self.images)[0]
        previews = summary["preview_participants"]
        self.assertEqual(summary["winner"], cup["participants"][4])
        self.assertEqual(previews[0], summary["winner"])
        self.assertEqual([row["ordinal"] for row in previews], [4, 0, 1, 2])
        with closing(sqlite3.connect(self.db)) as connection:
            image_path = connection.execute("SELECT image_path FROM style_worldcup_participants WHERE worldcup_id=? AND ordinal=4", (cup["id"],)).fetchone()[0]
        (self.images / image_path).unlink()
        missing = list_worldcups(self.db, self.images)[0]["preview_participants"][0]
        self.assertFalse(missing["available"])
        self.assertEqual(missing["image_url"], "")
        small = self.create(size=2)
        self.assertEqual(len(list_worldcups(self.db, self.images)[0]["preview_participants"]), small["size"])

    def test_exclusions_remove_whole_images_without_editing_original_prompts(self):
        self.add_image("artist:blocked, artist:kept, watercolor")
        self.add_image("artist:kept, monochrome")
        self.add_image("artist:kept, watercolor", negative="artist:blocked, monochrome")
        self.add_image("artist:another, ink")

        def source_rows():
            with closing(sqlite3.connect(self.db)) as connection:
                return tuple(connection.execute("SELECT * FROM arca_style_items ORDER BY id")), tuple(connection.execute("SELECT * FROM arca_style_images ORDER BY id"))

        before = source_rows()
        file_bytes = {path.name: path.read_bytes() for path in self.images.iterdir()}
        filters = {"exclude_artists": ["blocked"], "exclude_tags": ["monochrome"]}
        self.assertEqual(self.preview(**filters), 2)
        cup = self.create(size="all", **filters)
        self.assertEqual({row["base_prompt"] for row in cup["participants"]}, {
            "artist:kept, watercolor", "artist:another, ink",
        })
        self.assertEqual(source_rows(), before)
        self.assertEqual({path.name: path.read_bytes() for path in self.images.iterdir()}, file_bytes)

    def test_compact_choices_query_only_next_match_then_completed_winner(self):
        for _ in range(4):
            self.add_image()
        cup = self.create(size=4)
        participants = cup["participants"]
        for revision, winner, expected_ordinals in ((0, 0, [2, 3]), (1, 3, [0, 3]), (2, 3, [3])):
            with self.subTest(revision=revision):
                with patch("style_worldcup_store._local_image", wraps=style_worldcup_store._local_image) as local_image:
                    result = choose_winner(self.db, self.images, cup["id"], {
                        "revision": revision, "winner": winner, "compact": True,
                    })
                self.assertTrue(result["participants_partial"])
                self.assertEqual(result["participants"], [participants[ordinal] for ordinal in expected_ordinals])
                self.assertEqual(local_image.call_count, len(expected_ordinals))
                self.assertLessEqual(local_image.call_count, 2)
                full = get_worldcup(self.db, self.images, cup["id"])
                self.assertEqual(full["participants"], participants)
                self.assertNotIn("participants_partial", full)
                self.assertEqual(
                    {key: value for key, value in result.items() if key not in ("participants", "participants_partial")},
                    {key: value for key, value in full.items() if key != "participants"},
                )
        self.assertEqual((result["status"], result["winner"], len(result["history"])), ("completed", 3, 3))

    def test_compact_is_opt_in_and_create_get_and_default_choice_keep_full_participants(self):
        for _ in range(8):
            self.add_image()
        cup = self.create(size=8, compact=True)
        self.assertEqual(len(cup["participants"]), 8)
        self.assertNotIn("participants_partial", cup)
        for revision, extra in enumerate(({}, {"compact": False}, {"compact": "true"}, {"compact": 1})):
            with self.subTest(extra=extra):
                with patch("style_worldcup_store._local_image", wraps=style_worldcup_store._local_image) as local_image:
                    cup = choose_winner(self.db, self.images, cup["id"], {
                        "revision": revision, "winner": cup["current_match"]["left"], **extra,
                    })
                self.assertEqual(len(cup["participants"]), 8)
                self.assertEqual(local_image.call_count, 8)
                self.assertNotIn("participants_partial", cup)
                self.assertEqual(cup, get_worldcup(self.db, self.images, cup["id"]))

    def test_candidate_sources_default_shared_and_confirmed_groups_use_one_image(self):
        self.add_image()
        self.add_image()
        self.add_confirmed(paths=["confirmed-a.png", "confirmed-b.png"])
        self.add_confirmed(paths=["confirmed-c.png"])
        self.assertEqual(preview_candidates(self.db, self.images, {}), {
            "count": 2, "counts": {"shared": 2, "confirmed": 0},
        })
        confirmed = self.create(size="all", sources=["confirmed"], confirmed_image_root=self.confirmed_images, name="")
        self.assertEqual(confirmed["name"], "그림체 월드컵")
        self.assertEqual(confirmed["size"], 2)
        self.assertEqual(confirmed["filters"]["sources"], ["confirmed"])
        self.assertEqual({row["image_source"] for row in confirmed["participants"]}, {"confirmed"})
        self.assertEqual({row["image_url"] for row in confirmed["participants"]}, {
            "/confirmed-style-images/confirmed-a.png", "/confirmed-style-images/confirmed-c.png",
        })
        self.assertTrue(all(row["recommendation_count"] is None for row in confirmed["participants"]))
        combined = {"sources": ["shared", "confirmed", "shared"]}
        self.assertEqual(preview_candidates(self.db, self.images, combined, confirmed_image_root=self.confirmed_images), {
            "count": 4, "counts": {"shared": 2, "confirmed": 2},
        })
        mixed = self.create(size="all", filters=combined, confirmed_image_root=self.confirmed_images)
        self.assertEqual(mixed["filters"]["sources"], ["shared", "confirmed"])
        self.assertEqual(mixed["size"], 4)
        self.assertEqual({row["image_source"] for row in mixed["participants"]}, {"shared", "confirmed"})

    def test_sources_validation_and_missing_confirmed_root_are_explicit(self):
        for sources in (None, [], "confirmed", {}, ["unknown"], ["shared", True], ["shared", []]):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                self.preview(sources=sources, confirmed_image_root=self.confirmed_images)
        with self.assertRaisesRegex(ValueError, "확정 그림체 이미지 폴더"):
            self.preview(sources=["confirmed"])
        with self.assertRaisesRegex(ValueError, "확정 그림체 이미지 폴더"):
            self.create(size="all", sources=["shared", "confirmed"])
        self.assertEqual(list_worldcups(self.db, self.images), [])

    def test_confirmed_filter_uses_current_artist_quality_and_fixed_only(self):
        self.add_confirmed(
            artist="1.4::artist:Alpha_One::", quality="{{watercolor}}", fixed="blue_hair",
            original_quality="obsolete tag", negative="monochrome, artist:negative",
            characters='[{"prompt":"character tag"}]', raw_metadata='{"prompt":"raw tag"}',
            paths=["a.png", "b.png"],
        )
        options = {"sources": ["confirmed"], "confirmed_image_root": self.confirmed_images}
        self.assertEqual(self.preview(include_artists=["alpha one"], include_tags=["watercolor", "blue hair"], **options), 1)
        for tag in ("obsolete tag", "monochrome", "character tag", "raw tag", "watercolor painting"):
            with self.subTest(tag=tag):
                self.assertEqual(self.preview(include_tags=[tag], **options), 0)
        self.assertEqual(self.preview(include_artists=["negative"], **options), 0)
        self.assertEqual(self.preview(exclude_tags=["watercolor"], **options), 0)
        self.add_image("artist:example, ink")
        cup = self.create(size="all", sources=["shared", "confirmed"], confirmed_image_root=self.confirmed_images)
        self.assertEqual(next(row["base_prompt"] for row in cup["participants"] if row["image_source"] == "confirmed"),
                         "1.4::artist:Alpha_One::, {{watercolor}}, blue_hair")

    def test_recommendation_threshold_only_filters_shared_source(self):
        for recommendation in (None, 5, 6):
            self.add_image(recommendation=recommendation)
        self.add_confirmed(paths=["a.png", "b.png"])
        preview = preview_candidates(self.db, self.images, {
            "sources": ["shared", "confirmed"], "exclude_recommendation_lte": 5,
        }, confirmed_image_root=self.confirmed_images)
        self.assertEqual(preview, {"count": 2, "counts": {"shared": 1, "confirmed": 1}})
        self.assertEqual(self.preview(
            sources=["confirmed"], exclude_recommendation_lte=2147483647,
            confirmed_image_root=self.confirmed_images,
        ), 1)

    def test_mixed_compact_tournament_survives_source_deletion_and_full_resume(self):
        self.add_image()
        self.add_confirmed(paths=["a.png"])
        self.add_confirmed(paths=["b.png"])
        cup = self.create(size="all", sources=["shared", "confirmed"], confirmed_image_root=self.confirmed_images)
        original = cup["participants"]
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM arca_style_images")
            connection.execute("DELETE FROM arca_style_items")
            connection.execute("DELETE FROM confirmed_style_images")
            connection.execute("DELETE FROM confirmed_styles")
        cup = choose_winner(self.db, self.images, cup["id"], {
            "revision": 0, "winner": 1, "compact": True,
        }, confirmed_image_root=self.confirmed_images)
        self.assertTrue(cup["participants_partial"])
        self.assertEqual(cup["participants"], original[1:])
        full = get_worldcup(self.db, self.images, cup["id"], confirmed_image_root=self.confirmed_images)
        self.assertEqual(full["participants"], original)
        self.assertEqual(full["history"], cup["history"])
        completed = choose_winner(self.db, self.images, cup["id"], {
            "revision": 1, "winner": 2, "compact": True,
        }, confirmed_image_root=self.confirmed_images)
        self.assertEqual((completed["status"], completed["winner"]), ("completed", 2))
        self.assertEqual(completed["participants"], [original[2]])
        summary = list_worldcups(self.db, self.images, confirmed_image_root=self.confirmed_images)[0]
        self.assertEqual(summary["winner"], original[2])
        self.assertEqual({row["image_source"] for row in summary["preview_participants"]}, {"shared", "confirmed"})

    def test_confirmed_file_safety_and_source_roots_do_not_overlap(self):
        self.add_image(image_path="shared-only.png")
        self.add_confirmed(paths=["safe/한 #.png", "../escape.png", str(self.root / "absolute.png")])
        self.add_confirmed(paths=["shared-only.png", "missing.png", "bad\\windows.png", "file.png:stream"], local=False)
        self.add_confirmed(paths=["second.png"])
        self.assertEqual(self.preview(sources=["confirmed"], confirmed_image_root=self.confirmed_images), 2)
        cup = self.create(size="all", sources=["confirmed"], confirmed_image_root=self.confirmed_images)
        self.assertTrue(all(row["image_url"].startswith("/confirmed-style-images/") for row in cup["participants"]))
        self.assertTrue(any("%ED%95%9C%20%23.png" in row["image_url"] for row in cup["participants"]))
        with self.assertRaisesRegex(ValueError, "확정 그림체 이미지 폴더"):
            get_worldcup(self.db, self.images, cup["id"])
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE style_worldcup_participants SET image_source='unknown' WHERE worldcup_id=?", (cup["id"],))
        unknown = get_worldcup(self.db, self.images, cup["id"], confirmed_image_root=self.confirmed_images)
        self.assertTrue(all(row["image_source"] == "unknown" for row in unknown["participants"]))
        self.assertTrue(all(row["image_url"] == "" and not row["available"] for row in unknown["participants"]))

    def test_legacy_participant_schema_upgrade_preserves_saved_results(self):
        legacy_db = self.root / "legacy.sqlite"
        self.add_image(image_path="legacy.png")
        state = {"round": [0, 1], "next_round": [1], "winner": 1,
                 "history": [{"round_size": 2, "left": 0, "right": 1, "winner": 1}]}
        with closing(sqlite3.connect(legacy_db)) as connection, connection:
            connection.executescript("""
                CREATE TABLE style_worldcups (
                    id INTEGER PRIMARY KEY, uuid TEXT UNIQUE, name TEXT, size INTEGER, status TEXT,
                    revision INTEGER, filters_json TEXT, state_json TEXT, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE style_worldcup_participants (
                    id INTEGER PRIMARY KEY, worldcup_id INTEGER, ordinal INTEGER,
                    title TEXT, source_url TEXT, base_prompt TEXT, recommendation_count INTEGER,
                    image_path TEXT, UNIQUE(worldcup_id,ordinal)
                );
            """)
            connection.execute("INSERT INTO style_worldcups VALUES(1,'legacy','기존 결과',2,'completed',1,'{}',?,'old','old')", (json.dumps(state),))
            connection.executemany("INSERT INTO style_worldcup_participants VALUES(?,1,?,'기존 그림','','artist:legacy',9,'legacy.png')", [(1, 0), (2, 1)])
        init_worldcup_tables(legacy_db)
        init_worldcup_tables(legacy_db)
        saved = get_worldcup(legacy_db, self.images, 1)
        self.assertEqual((saved["name"], saved["status"], saved["winner"], saved["revision"]), ("기존 결과", "completed", 1, 1))
        self.assertEqual(saved["filters"], {})
        self.assertEqual(saved["history"], state["history"])
        self.assertEqual([row["image_source"] for row in saved["participants"]], ["shared", "shared"])
        self.assertTrue(all(row["image_url"] == "/arca-style-images/legacy.png" for row in saved["participants"]))
        with closing(sqlite3.connect(legacy_db)) as connection:
            self.assertEqual(connection.execute("SELECT uuid,state_json,created_at,updated_at FROM style_worldcups").fetchone(), ("legacy", json.dumps(state), "old", "old"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcup_participants").fetchone()[0], 2)

    def test_candidate_gallery_pagination_counts_and_compact_auto_selection(self):
        self.add_image()
        self.add_image()
        self.add_confirmed(paths=["a.png"])
        self.add_confirmed(paths=["b.png"])
        options = {"sources": ["shared", "confirmed"], "per_page": 2}
        first = list_candidates(self.db, self.images, options, confirmed_image_root=self.confirmed_images)
        second = list_candidates(self.db, self.images, {**options, "page": 2}, confirmed_image_root=self.confirmed_images)
        self.assertEqual((first["count"], first["counts"], first["page"], first["per_page"]), (4, {"shared": 2, "confirmed": 2}, 1, 2))
        self.assertEqual([row["key"] for row in first["items"]], ["shared:1", "shared:2"])
        self.assertEqual([row["key"] for row in second["items"]], ["confirmed:1", "confirmed:2"])
        self.assertNotIn("selection", first)
        all_keys = {row["key"] for row in first["items"] + second["items"]}
        for size in (2, "all"):
            result = list_candidates(self.db, self.images, {
                **options, "auto_size": size, "page": 3,
            }, confirmed_image_root=self.confirmed_images)
            self.assertEqual(result["items"], [])
            self.assertEqual(len(result["selection"]), 4 if size == "all" else 2)
            self.assertEqual(len({row["key"] for row in result["selection"]}), len(result["selection"]))
            self.assertTrue({row["key"] for row in result["selection"]}.issubset(all_keys))
            for summary in result["selection"]:
                self.assertEqual(set(summary), {"key", "group_key", "detail_url", "title", "image_source", "image_url", "thumbnail_url", "model_label", "available", "recommendation_count"})
                self.assertTrue(summary["available"])
        empty = list_candidates(self.db, self.images, {"include_tags": ["not present"]})
        self.assertEqual((empty["count"], empty["items"], empty["per_page"]), (0, [], 24))

    def test_candidate_gallery_rejects_invalid_page_or_auto_size(self):
        self.add_image()
        self.add_image()
        for payload in ({"page": 0}, {"page": True}, {"page": "1"}, {"per_page": 0},
                        {"per_page": 61}, {"per_page": 2.0}, {"auto_size": True},
                        {"auto_size": None}, {"auto_size": 3}, {"auto_size": 4}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                list_candidates(self.db, self.images, payload)
        for count in (0, 1):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "2장 이상"):
                list_candidates(self.db, self.images, {"include_tags": [f"count {count}"], "auto_size": "all"})
            if count == 0:
                self.add_image("artist:example, count 1")

    def test_exact_selected_three_candidates_preserve_only_reviewed_images(self):
        self.add_image()
        self.add_image()
        self.add_confirmed(paths=["a.png"])
        self.add_confirmed(paths=["b.png"])
        gallery = list_candidates(self.db, self.images, {
            "sources": ["shared", "confirmed"], "auto_size": "all",
        }, confirmed_image_root=self.confirmed_images)
        reviewed = [row for row in gallery["selection"] if row["key"] != "shared:2"]
        cup = self.create(size="all", sources=["shared", "confirmed"],
                          selected_candidates=[row["key"] for row in reviewed],
                          confirmed_image_root=self.confirmed_images)
        self.assertEqual(cup["size"], 3)
        self.assertEqual({row["image_url"] for row in cup["participants"]}, {row["image_url"] for row in reviewed})
        self.assertEqual(cup["current_match"]["bye_count"], 1)
        with self.assertRaisesRegex(ValueError, "일치"):
            self.create(size=2, sources=["shared", "confirmed"],
                        selected_candidates=[row["key"] for row in reviewed],
                        confirmed_image_root=self.confirmed_images)
        smaller = self.create(size=2, selected_candidates=["shared:1", "shared:2"])
        self.assertEqual(smaller["size"], 2)

    def test_selected_candidates_reject_duplicates_filters_stale_rows_and_missing_files(self):
        self.add_image("artist:included, watercolor")
        self.add_image("artist:excluded, monochrome")
        self.add_image("artist:included, ink")
        self.add_confirmed()
        list_candidates(self.db, self.images, {"auto_size": "all"})
        for keys in (None, [], ["shared:1"], ["shared:1", "shared:1"],
                     ["shared:1", True], ["shared:1", "unknown:1"],
                     ["shared:1", "shared:0"], ["shared:1", "shared:999"],
                     ["shared:1", "confirmed:1"]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.create(size="all", selected_candidates=keys)
        for filters in ({"exclude_tags": ["monochrome"]}, {"include_artists": ["included"]}):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValueError, "현재 조건"):
                self.create(size="all", selected_candidates=["shared:1", "shared:2"], **filters)
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM arca_style_images WHERE id=2")
        with self.assertRaisesRegex(ValueError, "현재 조건"):
            self.create(size="all", selected_candidates=["shared:1", "shared:2"])
        (self.images / "image-3.png").unlink()
        with self.assertRaisesRegex(ValueError, "현재 조건"):
            self.create(size="all", selected_candidates=["shared:1", "shared:3"])
        self.assertEqual(list_worldcups(self.db, self.images), [])

    def test_candidate_gallery_uses_base_filters_and_rejects_escaping_paths(self):
        self.add_image("artist:included, watercolor", negative="monochrome")
        self.add_image("artist:included, watercolor", image_path="../outside.png")
        self.add_confirmed(artist="artist:included", quality="watercolor", negative="monochrome", paths=["nested/a #.png"])
        self.add_confirmed(paths=["../confirmed-outside.png"])
        options = {"sources": ["shared", "confirmed"], "include_tags": ["watercolor"]}
        result = list_candidates(self.db, self.images, options, confirmed_image_root=self.confirmed_images)
        self.assertEqual(result["counts"], {"shared": 1, "confirmed": 1})
        self.assertEqual({row["key"] for row in result["items"]}, {"shared:1", "confirmed:1"})
        self.assertEqual(result["items"][1]["image_url"], "/confirmed-style-images/nested/a%20%23.png")
        negative = list_candidates(self.db, self.images, {**options, "include_tags": ["monochrome"]}, confirmed_image_root=self.confirmed_images)
        self.assertEqual((negative["count"], negative["items"]), (0, []))

    def test_group_representative_is_first_safe_image_matching_all_filters(self):
        group = self.add_image("artist:example, watercolor", model="V4.5 Full", recommendation=12)
        self.add_image("artist:example, monochrome", model="V5 Full Medium", item_id=group)
        self.add_image("artist:example, watercolor", model="V5 Full Medium", item_id=group, local=False)
        self.add_image("artist:example, watercolor", model="V5 Full Medium", item_id=group, image_path="../outside.png")
        self.add_image("artist:example, watercolor", model="V5 Full Medium", item_id=group)
        self.add_image("artist:example, watercolor", model="V5 Full Medium", item_id=group)
        self.add_confirmed(model="V5 Full Medium", paths=["missing.png", "first.png", "later.png"])
        (self.confirmed_images / "missing.png").unlink()
        filters = {"sources": ["shared", "confirmed"], "model": "nai-diffusion-5-full-medium",
                   "include_tags": ["watercolor"], "exclude_tags": ["monochrome"], "exclude_recommendation_lte": 11}
        options = {"confirmed_image_root": self.confirmed_images}
        expected = {"shared:5", "confirmed:2"}
        self.assertEqual(preview_candidates(self.db, self.images, filters, **options), {
            "count": 2, "counts": {"shared": 1, "confirmed": 1},
        })
        gallery = list_candidates(self.db, self.images, {**filters, "auto_size": "all"}, **options)
        self.assertEqual({row["key"] for row in gallery["items"]}, expected)
        self.assertEqual({row["key"] for row in gallery["selection"]}, expected)
        cup = self.create(size="all", **filters, **options, selected_candidates=sorted(expected))
        self.assertEqual({row["image_url"] for row in cup["participants"]}, {
            "/arca-style-images/image-5.png", "/confirmed-style-images/first.png",
        })
        # A lost representative falls back on the next eligible image, but an
        # already reviewed key must never silently change at tournament creation.
        (self.images / "image-5.png").unlink()
        with self.assertRaisesRegex(ValueError, "현재 조건"):
            self.create(size="all", **filters, **options, selected_candidates=sorted(expected))
        refreshed = list_candidates(self.db, self.images, filters, **options)
        self.assertEqual({row["key"] for row in refreshed["items"]}, {"shared:6", "confirmed:2"})

    def test_same_group_cannot_be_entered_twice_but_distinct_groups_with_same_prompt_remain(self):
        first = self.add_image()
        self.add_image(item_id=first)
        self.add_image()
        self.add_confirmed(paths=["one.png", "two.png"])
        options = {"sources": ["shared", "confirmed"], "confirmed_image_root": self.confirmed_images}
        self.assertEqual(self.preview(**options), 3)
        for keys in (["shared:1", "shared:2"], ["confirmed:1", "confirmed:2"]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.create(size="all", selected_candidates=keys, **options)
        self.assertEqual(list_worldcups(self.db, self.images, confirmed_image_root=self.confirmed_images), [])
        cup = self.create(size="all", selected_candidates=["shared:1", "shared:3"], **options)
        self.assertEqual(cup["size"], 2)

    def test_model_filters_share_existing_generation_and_medium_classification(self):
        models = ["NovelAI Diffusion V5 0ADF9AB7", "NovelAI Diffusion V5 93F4BD30", "NovelAI Diffusion V5 DB276663", "V4.5 Full", "", "NovelAI Diffusion V5 unknown-build"]
        for model in models:
            self.add_image(model=model)
            self.add_confirmed(model=model)
        options = {"sources": ["shared", "confirmed"], "confirmed_image_root": self.confirmed_images}
        for model, per_source in (("all", 6), ("v5", 4), ("v4.5", 1), ("unknown", 1),
                                  ("nai-diffusion-5-full-medium", 1), ("v5-full", 1), ("v5-curated", 1),
                                  ("nai-diffusion-4-5-full", 1), ("nai-diffusion-4-5-curated", 0)):
            with self.subTest(model=model):
                self.assertEqual(self.preview(model=model, **options), per_source * 2)
        gallery = list_candidates(self.db, self.images, {
            "sources": options["sources"], "model": "V5 Full Medium", "auto_size": "all",
        }, confirmed_image_root=self.confirmed_images)
        self.assertEqual({row["key"] for row in gallery["items"]}, {"shared:2", "confirmed:2"})
        self.assertEqual({row["model_label"] for row in gallery["items"]}, {"V5 Full Medium"})
        cup = self.create(size="all", model="V5 Full Medium", **options)
        self.assertEqual(cup["size"], 2)
        self.assertEqual(cup["filters"]["model"], "nai-diffusion-5-full-medium")
        for invalid in (True, [], {}, "v6", "medium"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.preview(model=invalid, **options)

    def test_confirmed_representative_respects_position_before_image_id(self):
        self.add_confirmed(paths=["a.png", "b.png", "c.png"])
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("UPDATE confirmed_style_images SET position=-1 WHERE image_path='c.png'")
        gallery = list_candidates(self.db, self.images, {"sources": ["confirmed"]}, confirmed_image_root=self.confirmed_images)
        self.assertEqual([row["key"] for row in gallery["items"]], ["confirmed:3"])

    def test_large_grouped_gallery_checks_only_one_file_per_represented_group(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            for group in range(100):
                path = f"group-{group}.png"
                Image.new("RGB", (2, 2)).save(self.images / path)
                item = connection.execute(
                    "INSERT INTO arca_style_items(source_url,collected_at,updated_at) VALUES(?,?,?)",
                    (f"https://example.invalid/{group}", "now", "now"),
                ).lastrowid
                connection.executemany(
                    "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                    [(item, f"https://example.invalid/{group}/{index}", path, "ok", "watercolor", "now") for index in range(10)],
                )
        with patch.object(style_worldcup_store, "_local_image", wraps=style_worldcup_store._local_image) as checked:
            gallery = list_candidates(self.db, self.images, {"per_page": 60})
        self.assertEqual((gallery["count"], len(gallery["items"])), (100, 60))
        self.assertEqual(checked.call_count, 100)
        self.assertTrue(all(call.kwargs == {"root_is_resolved": True} for call in checked.call_args_list))

    def test_thumbnail_urls_encode_source_paths_without_exposing_original_metadata(self):
        self.add_image(image_path="nested/shared #한.png")
        self.add_confirmed(paths=["nested/confirmed #한.png"])
        gallery = list_candidates(self.db, self.images, {"sources": ["shared", "confirmed"]}, confirmed_image_root=self.confirmed_images)
        for row in gallery["items"]:
            self.assertTrue(row["thumbnail_url"].startswith(f"/style-manager-thumbnails/{row['image_source']}/nested/"))
            self.assertIn("%20%23%ED%95%9C.png", row["thumbnail_url"])
            self.assertNotIn("base_prompt", row)
            self.assertNotIn("image_path", row)

    def test_recommendation_sort_precedes_paging_and_missing_counts_stay_last(self):
        for recommendation in (None, 10, 0, 10, 30):
            self.add_image(recommendation=recommendation)
        self.add_confirmed()
        options = {"sources": ["shared", "confirmed"], "per_page": 2}
        expected = {
            "default": ["shared:1", "shared:2", "shared:3", "shared:4", "shared:5", "confirmed:1"],
            "recommendation_desc": ["shared:5", "shared:2", "shared:4", "shared:3", "shared:1", "confirmed:1"],
            "recommendation_asc": ["shared:3", "shared:2", "shared:4", "shared:5", "shared:1", "confirmed:1"],
        }
        for sort, keys in expected.items():
            actual = []
            for page in range(1, 4):
                gallery = list_candidates(self.db, self.images, {**options, "sort": sort, "page": page}, confirmed_image_root=self.confirmed_images)
                self.assertEqual(gallery["counts"], {"shared": 5, "confirmed": 1})
                actual.extend(row["key"] for row in gallery["items"])
            self.assertEqual(actual, keys)
        for sort in (None, True, [], {}, "recommendation", "newest"):
            with self.subTest(sort=sort), self.assertRaises(ValueError):
                list_candidates(self.db, self.images, {"sort": sort})

    def test_group_and_detail_identifiers_follow_item_not_representative_image(self):
        group = self.add_image(local=False)
        self.add_image(item_id=group)
        self.add_confirmed(paths=["missing.png", "representative.png"])
        (self.confirmed_images / "missing.png").unlink()
        gallery = list_candidates(self.db, self.images, {"sources": ["shared", "confirmed"], "auto_size": "all"}, confirmed_image_root=self.confirmed_images)
        expected = {
            "shared:2": ("shared:1", "/api/arca-styles/1"),
            "confirmed:2": ("confirmed:1", "/api/confirmed-styles/1"),
        }
        for row in gallery["items"] + gallery["selection"]:
            self.assertEqual((row["group_key"], row["detail_url"]), expected[row["key"]])

    def test_explicit_all_scope_keeps_exact_selection_across_gallery_filter_changes(self):
        group = self.add_image("artist:one, watercolor", model="V5 Full", recommendation=0)
        self.add_image("artist:one, monochrome", model="V4.5 Full", item_id=group)
        self.add_confirmed(model="V5 Full Medium", quality="watercolor")
        options = {"sources": ["shared", "confirmed"], "confirmed_image_root": self.confirmed_images,
                   "model": "v4.5", "include_tags": ["missing"], "exclude_tags": ["watercolor"], "exclude_recommendation_lte": 99}
        keys = ["shared:2", "confirmed:1"]
        with self.assertRaisesRegex(ValueError, "현재 조건"):
            self.create(size="all", selected_candidates=keys, **options)
        cup = self.create(size="all", selected_candidates=keys, selection_scope="all", **options)
        self.assertEqual(cup["size"], 2)
        self.assertEqual(cup["filters"]["selection_scope"], "all")
        self.assertEqual(cup["filters"]["model"], "v4.5")
        self.assertEqual({row["image_url"] for row in cup["participants"]}, {
            "/arca-style-images/image-2.png", "/confirmed-style-images/confirmed-1.png",
        })
        self.assertEqual(get_worldcup(self.db, self.images, cup["id"], confirmed_image_root=self.confirmed_images), cup)

    def test_explicit_all_scope_rejects_duplicate_groups_invalid_scope_and_source(self):
        group = self.add_image()
        self.add_image(item_id=group)
        self.add_confirmed(paths=["a.png", "b.png"])
        options = {"sources": ["shared", "confirmed"], "confirmed_image_root": self.confirmed_images, "selection_scope": "all"}
        for keys in (["shared:1", "shared:2"], ["confirmed:1", "confirmed:2"]):
            with self.subTest(keys=keys), self.assertRaisesRegex(ValueError, "중복"):
                self.create(size="all", selected_candidates=keys, **options)
        for scope in (None, True, [], {}, "any"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                self.create(size="all", selection_scope=scope)
        with self.assertRaises(ValueError):
            self.create(size="all", **options)
        for keys in ([], ["shared:1"], ["shared:1", True], ["shared:1", "unknown:1"]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.create(size="all", selected_candidates=keys, **options)
        with self.assertRaisesRegex(ValueError, "현재 조건"):
            self.create(size="all", sources=["shared"], selection_scope="all", selected_candidates=["shared:1", "confirmed:1"])
        self.assertEqual(list_worldcups(self.db, self.images, confirmed_image_root=self.confirmed_images), [])

    def test_explicit_all_scope_still_rejects_lost_unsafe_or_metadata_invalid_images(self):
        self.add_image()
        self.add_image()
        self.add_image()
        self.add_image()
        self.add_confirmed()
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("DELETE FROM arca_style_images WHERE id=1")
            connection.execute("UPDATE arca_style_images SET image_path='../outside.png' WHERE id=2")
            connection.execute("UPDATE arca_style_images SET metadata_status='no_metadata' WHERE id=3")
        (self.images / "image-4.png").unlink()
        options = {"sources": ["shared", "confirmed"], "confirmed_image_root": self.confirmed_images, "selection_scope": "all"}
        for index in range(1, 5):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "현재 조건"):
                self.create(size="all", selected_candidates=[f"shared:{index}", "confirmed:1"], **options)
        self.assertEqual(list_worldcups(self.db, self.images, confirmed_image_root=self.confirmed_images), [])


if __name__ == "__main__":
    unittest.main()
