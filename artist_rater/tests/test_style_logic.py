import json
import os
import struct
import tempfile
import time
import unittest
import zlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import app
from style_logic import (
    assign_weights,
    build_artist_prompt,
    normalize_style_artists,
    random_weight,
    select_artists,
    style_hash,
)
from style_store import (
    _staged_file_path,
    connect_db,
    get_style_detail,
    list_styles,
    save_generated_result,
)
from png_validator import validate_png


def png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def tiny_png(scanlines=b"\x00\xff\x00\x00\xff", width=1, height=1, interlace=0):
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(
                b"IHDR",
                struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, interlace),
            ),
            png_chunk(b"IDAT", zlib.compress(scanlines)),
            png_chunk(b"IEND", b""),
        )
    )


def png_with_idat(idat_payload):
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)),
            png_chunk(b"IDAT", idat_payload),
            png_chunk(b"IEND", b""),
        )
    )


class PngValidatorTest(unittest.TestCase):
    def test_rejects_expected_dimension_mismatch(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            validate_png(tiny_png(), expected_width=2, expected_height=1)

    def test_rejects_scanline_output_beyond_exact_cap(self):
        oversized = png_with_idat(zlib.compress(b"\x00" * 1000000))
        with self.assertRaisesRegex(ValueError, "scanline"):
            validate_png(oversized, expected_width=1, expected_height=1)


class StyleIdentityTest(unittest.TestCase):
    def test_prompt_preserves_artist_order(self):
        artists = [
            {"artist": "artist_b", "weight": 0.5, "score": 3},
            {"artist": "artist_a", "weight": 2.1, "score": 5},
        ]

        self.assertEqual(
            build_artist_prompt(artists),
            "0.5::artist:artist b::, 2.1::artist:artist a::",
        )

    def test_prompt_replaces_artist_tag_underscores_with_spaces(self):
        self.assertEqual(
            build_artist_prompt([{"artist": "some_artist_name", "weight": 1.25}]),
            "1.25::artist:some artist name::",
        )

    def test_prompt_adds_space_before_closing_marker_when_artist_ends_in_number(self):
        self.assertEqual(
            build_artist_prompt([{"artist": "artist_name_123", "weight": 1.25}]),
            "1.25::artist:artist name 123 ::",
        )

    def test_hash_changes_when_order_changes(self):
        artists = [
            {"artist": "artist_a", "weight": 1.0},
            {"artist": "artist_b", "weight": 1.5},
        ]

        self.assertNotEqual(style_hash(artists), style_hash(list(reversed(artists))))

    def test_hash_changes_when_weight_changes(self):
        original = [
            {"artist": "artist_a", "weight": 1.0},
            {"artist": "artist_b", "weight": 1.5},
        ]
        changed = [original[0], {"artist": "artist_b", "weight": 1.6}]

        self.assertNotEqual(style_hash(original), style_hash(changed))

    def test_hash_accepts_only_artist_identity_argument(self):
        artists = [{"artist": "artist_a", "weight": 1.25}]

        with self.assertRaises(TypeError):
            style_hash(artists, "base prompt")

    def test_normalize_validates_and_rounds_artist_identity(self):
        normalized = normalize_style_artists(
            [{"artist": " artist_a ", "weight": "1.236", "score": "4"}]
        )

        self.assertEqual(
            normalized,
            [{"artist": "artist_a", "weight": 1.24, "score": 4}],
        )
        for invalid in (
            [],
            [{"artist": "", "weight": 1}],
            [{"artist": "artist_a", "weight": 0}],
            [{"artist": "artist_a", "weight": "not-a-number"}],
            [
                {"artist": "artist_a", "weight": 1},
                {"artist": "artist_a", "weight": 2},
            ],
            [{"artist": "artist_a", "weight": 1, "score": True}],
            [{"artist": "artist_a", "weight": 1, "score": 4.5}],
            [{"artist": "artist_a", "weight": 1, "score": "4.0"}],
            [{"artist": "artist_a", "weight": 1, "score": 6}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_style_artists(invalid)


class ArtistSelectionTest(unittest.TestCase):
    def setUp(self):
        self.pool = [
            {"artist": f"artist_{index}", "score": score}
            for index, score in enumerate(
                [1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 5, 4], start=1
            )
        ]

    def test_selection_deduplicates_artist_records(self):
        pool = self.pool + [
            {"artist": "artist_1", "score": 5},
            {"artist": "artist_2", "score": 2},
        ]

        selected = select_artists(pool, 12, [1, 2, 3, 4, 5], rng_seed=7)

        self.assertEqual(len(selected), 12)
        self.assertEqual(len({item["artist"] for item in selected}), 12)

    def test_selection_filters_scores_and_rejects_invalid_count(self):
        selected = select_artists(self.pool, 3, [5], rng_seed=3)

        self.assertEqual({item["score"] for item in selected}, {5})
        with self.assertRaisesRegex(ValueError, "선택 가능한 작가"):
            select_artists(self.pool, 4, [5], rng_seed=3)
        with self.assertRaisesRegex(ValueError, "선택 가능한 작가"):
            select_artists(self.pool, 0, [5], rng_seed=3)
        with self.assertRaisesRegex(ValueError, "선택 가능한 작가"):
            select_artists(self.pool, 1.5, [5], rng_seed=3)

    def test_selection_is_deterministic_with_seed(self):
        first = select_artists(self.pool, 6, [1, 2, 3, 4, 5], rng_seed=19)
        second = select_artists(self.pool, 6, [1, 2, 3, 4, 5], rng_seed=19)

        self.assertEqual(first, second)

    def test_selection_rejects_non_integer_allowed_scores(self):
        for score in (True, 1.0, 1.5, "1.0", "1.5", 0, 6):
            with self.subTest(score=score), self.assertRaisesRegex(
                ValueError, "평점"
            ):
                select_artists(self.pool, 1, [score], rng_seed=1)

        self.assertEqual(
            select_artists(self.pool, 1, ["5"], rng_seed=1)[0]["score"],
            5,
        )


class WeightEngineTest(unittest.TestCase):
    def setUp(self):
        self.artists = [
            {"artist": f"artist_{index}", "score": score}
            for index, score in enumerate(
                [1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 5, 4], start=1
            )
        ]

    def test_random_weight_uses_only_positive_cent_values_inside_range(self):
        import random

        rng = random.Random(7)
        with self.assertRaisesRegex(ValueError, "센트"):
            random_weight(rng, 0.006, 0.006)
        with self.assertRaisesRegex(ValueError, "센트"):
            random_weight(rng, 0.011, 0.019)

        narrow = {random_weight(rng, 0.011, 0.021) for _ in range(20)}
        normal = {random_weight(rng, 0.1, 2.3) for _ in range(100)}
        self.assertEqual(narrow, {0.02})
        self.assertTrue(all(0.1 <= value <= 2.3 and value > 0 for value in normal))
        self.assertTrue(
            all(abs(value * 100 - round(value * 100)) < 1e-9 for value in normal)
        )

    def test_all_assignment_modes_reject_ranges_without_a_valid_cent(self):
        for mode, ranges in (
            ("random", []),
            ("balanced", []),
            (
                "custom",
                [{"min": 0.006, "max": 0.006, "max_people": 1}],
            ),
        ):
            with self.subTest(mode=mode), self.assertRaisesRegex(
                ValueError, "센트"
            ):
                assign_weights(
                    self.artists[:1],
                    mode,
                    0.006,
                    0.006,
                    False,
                    ranges,
                    rng_seed=1,
                )

    def test_balanced_twelve_has_exact_default_tiers_and_preserves_order(self):
        weighted = assign_weights(
            self.artists, "balanced", 0.1, 2.3, True, [], rng_seed=9
        )

        self.assertEqual(
            [item["artist"] for item in weighted],
            [item["artist"] for item in self.artists],
        )
        self.assertEqual(sum(item["weight"] < 1.0 for item in weighted), 5)
        self.assertEqual(sum(1.0 <= item["weight"] < 1.5 for item in weighted), 4)
        self.assertEqual(sum(item["weight"] >= 1.5 for item in weighted), 3)

    def test_balanced_high_tier_never_exceeds_twenty_five_percent(self):
        artists = [
            {"artist": f"artist_{index}", "score": (index % 5) + 1}
            for index in range(20)
        ]

        weighted = assign_weights(
            artists, "balanced", 0.1, 2.3, False, [], rng_seed=4
        )

        self.assertLessEqual(sum(item["weight"] >= 1.5 for item in weighted), 5)

    def test_balanced_without_low_keeps_high_cap_and_assigns_remainder_to_mid(self):
        weighted = assign_weights(
            self.artists, "balanced", 1.0, 2.3, False, [], rng_seed=4
        )

        self.assertEqual(sum(1.0 <= item["weight"] < 1.5 for item in weighted), 9)
        self.assertEqual(sum(item["weight"] >= 1.5 for item in weighted), 3)

    def test_balanced_high_only_range_explicitly_assigns_everyone_high(self):
        weighted = assign_weights(
            self.artists, "balanced", 1.5, 2.3, False, [], rng_seed=4
        )

        self.assertEqual(len(weighted), 12)
        self.assertTrue(all(item["weight"] >= 1.5 for item in weighted))

    def test_balanced_handles_tiny_counts_and_clipped_ranges(self):
        for minimum, maximum in (
            (0.4, 0.8),
            (0.91, 0.99),
            (1.1, 1.4),
            (1.8, 2.0),
        ):
            with self.subTest(minimum=minimum, maximum=maximum):
                weighted = assign_weights(
                    self.artists[:2],
                    "balanced",
                    minimum,
                    maximum,
                    True,
                    [],
                    rng_seed=2,
                )
                self.assertEqual(len(weighted), 2)
                self.assertTrue(
                    all(minimum <= item["weight"] <= maximum for item in weighted)
                )

    def test_custom_mode_rejects_invalid_ranges_and_capacity(self):
        with self.assertRaisesRegex(ValueError, "수용 인원"):
            assign_weights(
                self.artists[:4],
                "custom",
                0.1,
                2.3,
                False,
                [{"min": 0.1, "max": 0.9, "max_people": 3}],
                rng_seed=1,
            )
        invalid_ranges = (
            [{"min": 0, "max": 0.9, "max_people": 4}],
            [{"min": 0.1, "max": 2.4, "max_people": 4}],
            [{"min": 0.1, "max": 0.9, "max_people": 4.5}],
            [
                {"min": 0.1, "max": 1.0, "max_people": 2},
                {"min": 0.9, "max": 1.5, "max_people": 2},
            ],
        )
        for ranges in invalid_ranges:
            with self.subTest(ranges=ranges), self.assertRaisesRegex(
                ValueError, "사용자 구간"
            ):
                assign_weights(
                    self.artists[:4],
                    "custom",
                    0.1,
                    2.3,
                    False,
                    ranges,
                    rng_seed=1,
                )

    def test_custom_mode_validates_unreached_range_has_representable_cent(self):
        with self.assertRaisesRegex(ValueError, "센트"):
            assign_weights(
                self.artists[:1],
                "custom",
                0.001,
                2.3,
                False,
                [
                    {"min": 0.1, "max": 0.2, "max_people": 1},
                    {"min": 0.006, "max": 0.006, "max_people": 1},
                ],
                rng_seed=1,
            )

    def test_empty_custom_ranges_fall_back_to_seeded_random(self):
        first = assign_weights(
            self.artists[:3], "custom", 0.1, 2.3, False, [], rng_seed=2
        )
        second = assign_weights(
            self.artists[:3], "custom", 0.1, 2.3, False, [], rng_seed=2
        )

        self.assertEqual(first, second)
        self.assertTrue(all(0.1 <= item["weight"] <= 2.3 for item in first))

    def test_custom_ranges_allocate_in_user_supplied_order(self):
        class ControlledRng:
            def sample(self, items, count):
                return list(items)

            def randint(self, low, high):
                return low

        with patch("style_logic.random.Random", return_value=ControlledRng()):
            weighted = assign_weights(
                self.artists[:2],
                "custom",
                0.1,
                2.3,
                False,
                [
                    {"min": 0.1, "max": 0.2, "max_people": 1},
                    {"min": 1.5, "max": 1.6, "max_people": 1},
                ],
                rng_seed=1,
            )

        self.assertEqual(weighted[0]["weight"], 0.1)
        self.assertEqual(weighted[1]["weight"], 1.5)

    def test_profile_mode_interpolates_weights_by_prompt_position(self):
        weighted = assign_weights(
            self.artists[:5],
            "profile",
            0.1,
            2.3,
            False,
            [],
            rng_seed=7,
            profile=[
                {"position": 0, "weight": 0.2},
                {"position": 0.5, "weight": 2.0},
                {"position": 1, "weight": 0.6},
            ],
        )

        self.assertEqual([item["artist"] for item in weighted], [item["artist"] for item in self.artists[:5]])
        self.assertEqual(
            [item["weight"] for item in weighted],
            [0.2, 1.1, 2.0, 1.3, 0.6],
        )

    def test_profile_mode_uses_explicit_total_prompt_positions_without_jitter(self):
        weighted = assign_weights(
            self.artists[:2],
            "profile",
            0.1,
            2.3,
            False,
            [],
            rng_seed=7,
            profile=[
                {"position": 0, "weight": 1.5},
                {"position": 1 / 6, "weight": 1.0},
                {"position": 1, "weight": 2.3},
            ],
            positions=[0, 1 / 6],
        )

        self.assertEqual([item["weight"] for item in weighted], [1.5, 1.0])

    def test_profile_mode_rejects_invalid_control_points(self):
        invalid_profiles = (
            [],
            [{"position": 0, "weight": 1}],
            [{"position": 0, "weight": 1}, {"position": 0, "weight": 2}],
            [{"position": -0.1, "weight": 1}, {"position": 1, "weight": 2}],
            [{"position": 0, "weight": 0}, {"position": 1, "weight": 2}],
        )
        for profile in invalid_profiles:
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                assign_weights(
                    self.artists[:3], "profile", 0.1, 2.3, False, [], rng_seed=1, profile=profile
                )

    def test_score_priority_uses_exact_four_point_jitter(self):
        class ControlledRng:
            def __init__(self, values):
                self.values = iter(values)

            def random(self):
                return next(self.values)

            def randint(self, low, high):
                return low

        artists = [
            {"artist": "low", "score": 2},
            {"artist": "high", "score": 5},
            {"artist": "other_a", "score": 1},
            {"artist": "other_b", "score": 1},
        ]
        with patch(
            "style_logic.random.Random",
            return_value=ControlledRng([0.76, 0.0, 0.0, 0.0]),
        ):
            weighted = assign_weights(
                artists, "balanced", 0.1, 2.3, True, [], rng_seed=1
            )
        by_artist = {item["artist"]: item["weight"] for item in weighted}
        self.assertGreaterEqual(by_artist["low"], 1.5)

        artists[0]["score"] = 1
        with patch(
            "style_logic.random.Random",
            return_value=ControlledRng([0.99, 0.0, 0.0, 0.0]),
        ):
            weighted = assign_weights(
                artists, "balanced", 0.1, 2.3, True, [], rng_seed=1
            )
        by_artist = {item["artist"]: item["weight"] for item in weighted}
        self.assertGreaterEqual(by_artist["high"], 1.5)

    def test_score_priority_is_a_tendency_not_a_hard_exclusion(self):
        artists = [
            {"artist": "low", "score": 2},
            {"artist": "high", "score": 5},
            {"artist": "mid_a", "score": 3},
            {"artist": "mid_b", "score": 3},
        ]
        low_weights = []
        high_weights = []
        low_reached_high_tier = False
        for seed in range(100):
            weighted = assign_weights(
                artists, "balanced", 0.1, 2.3, True, [], rng_seed=seed
            )
            by_artist = {item["artist"]: item["weight"] for item in weighted}
            low_weights.append(by_artist["low"])
            high_weights.append(by_artist["high"])
            low_reached_high_tier |= by_artist["low"] >= 1.5

        self.assertGreater(sum(high_weights) / 100, sum(low_weights) / 100)
        self.assertTrue(low_reached_high_tier)

    def test_rejects_invalid_global_range_and_unknown_mode(self):
        invalid_bounds = ((float("nan"), 2.3), (0, 2.3), (2.0, 1.0))
        for minimum, maximum in invalid_bounds:
            with self.subTest(minimum=minimum, maximum=maximum), self.assertRaises(
                ValueError
            ):
                assign_weights(
                    self.artists[:1],
                    "random",
                    minimum,
                    maximum,
                    False,
                    [],
                )
        with self.assertRaisesRegex(ValueError, "가중치 모드"):
            assign_weights(
                self.artists[:1], "mystery", 0.1, 2.3, False, [], rng_seed=1
            )

    def test_assign_weights_rejects_non_integer_artist_scores(self):
        for score in (True, 3.0, 3.5, "3.0", 0, 6):
            with self.subTest(score=score), self.assertRaisesRegex(
                ValueError, "평점"
            ):
                assign_weights(
                    [{"artist": "artist_a", "score": score}],
                    "random",
                    0.1,
                    2.3,
                    False,
                    [],
                    rng_seed=1,
                )

        weighted = assign_weights(
            [{"artist": "artist_a", "score": "3"}],
            "random",
            0.1,
            2.3,
            False,
            [],
            rng_seed=1,
        )
        self.assertEqual(weighted[0]["score"], 3)


class ArtistStyleEndpointTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.originals = (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
            app.ARCA_STYLE_SEED_PATH,
        )
        app.DATA_DIR = self.data_dir
        app.THUMBNAIL_DIR = self.data_dir / "thumbnails"
        app.GENERATED_DIR = self.data_dir / "generated"
        app.SETTINGS_JSON_PATH = self.data_dir / "settings.json"
        app.DB_PATH = self.data_dir / "artist_rater.sqlite"
        app.ARCA_STYLE_SEED_PATH = self.data_dir / "missing-seed.sqlite"
        app.init_db()
        self.client = app.app.test_client()
        with closing(app.db()) as conn, conn:
            for artist, score in (("alpha", 5), ("beta", 4), ("gamma", 2)):
                conn.execute(
                    """
                    INSERT INTO ratings (
                        artist_tag, score, mode, created_at, updated_at
                    ) VALUES (?, ?, 'manual', ?, ?)
                    """,
                    (artist, score, app.now_text(), app.now_text()),
                )

    def tearDown(self):
        (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
            app.ARCA_STYLE_SEED_PATH,
        ) = self.originals
        self.temp_dir.cleanup()

    def test_endpoint_selects_from_ratings_table(self):
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 2,
                "scores": [4, 5],
                "weight_mode": "random",
                "min_weight": 0.5,
                "max_weight": 1.5,
                "prefer_high_scores": True,
                "rng_seed": 8,
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual({item["artist"] for item in data["artists"]}, {"alpha", "beta"})
        self.assertIn("artist_prompt", data)
        self.assertIn("style_hash", data)

    def test_endpoint_filters_rated_artists_by_saved_query_tag(self):
        with closing(app.db()) as conn, conn:
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag IN (?, ?)",
                (json.dumps(["dakimakura_(medium)"]), "alpha", "beta"),
            )
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["school_uniform"]), "gamma"),
            )

        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 2,
                "scores": [1, 2, 3, 4, 5],
                "rating_tag_filter": "dakimakura (medium)",
                "rng_seed": 4,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["artist"] for item in response.get_json()["artists"]},
            {"alpha", "beta"},
        )

    def test_endpoint_reserves_multiple_tag_counts_and_fills_remainder_from_all_ratings(self):
        with closing(app.db()) as conn, conn:
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["dakimakura_(medium)"]), "alpha"),
            )
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["portrait"]), "beta"),
            )
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["white_sheet"]), "gamma"),
            )

        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 3,
                "scores": [1, 2, 3, 4, 5],
                "rating_tag_rules": [
                    {"tag": "dakimakura (medium)", "count": 1},
                    {"tag": "white sheet", "count": 1},
                ],
                "rng_seed": 9,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["artist"] for item in response.get_json()["artists"]},
            {"alpha", "beta", "gamma"},
        )

    def test_endpoint_rejects_tag_counts_that_exceed_remaining_slots(self):
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 2,
                "scores": [1, 2, 3, 4, 5],
                "rating_tag_rules": [
                    {"tag": "dakimakura", "count": 2},
                    {"tag": "white_sheet", "count": 1},
                ],
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("남은 자리", response.get_json()["error"])

    def test_endpoint_rejects_duplicate_or_invalid_rating_tag_rules(self):
        payloads = (
            [{"tag": "white_sheet", "count": 1}, {"tag": "WHITE SHEET", "count": 1}],
            [{"tag": "white_sheet", "count": True}],
            [{"tag": "", "count": 1}],
        )
        for rules in payloads:
            with self.subTest(rules=rules):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={"count": 3, "scores": [1, 2, 3, 4, 5], "rating_tag_rules": rules},
                )
                self.assertEqual(response.status_code, 400)

    def test_endpoint_excludes_rated_artists_collected_with_selected_tags(self):
        with closing(app.db()) as conn, conn:
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["monochrome"]), "alpha"),
            )
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["portrait"]), "beta"),
            )
            conn.execute(
                "UPDATE ratings SET query_tags_json = ? WHERE artist_tag = ?",
                (json.dumps(["school_uniform"]), "gamma"),
            )

        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 2,
                "scores": [1, 2, 3, 4, 5],
                "rating_exclude_tags": ["monochrome"],
                "rng_seed": 12,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["artist"] for item in response.get_json()["artists"]},
            {"beta", "gamma"},
        )

    @patch("app.get_shared_style_artist_pool")
    def test_endpoint_can_fill_fixed_slots_from_shared_styles(self, shared_pool):
        shared_pool.return_value = [
            {"artist": "shared_alpha", "sample_count": 8},
            {"artist": "shared_beta", "sample_count": 5},
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 2,
                "scores": [1, 2, 3, 4, 5],
                "shared_artist_min": 2,
                "shared_artist_max": 2,
                "rng_seed": 5,
            },
        )
        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual({item["artist"] for item in artists}, {"shared_alpha", "shared_beta"})
        self.assertTrue(all(item["shared_style"] for item in artists))

    @patch("app.get_shared_style_artist_pool")
    def test_fixed_artists_reduce_the_remaining_shared_artist_slots(self, shared_pool):
        shared_pool.return_value = [
            {"artist": "shared_alpha", "sample_count": 8},
            {"artist": "shared_beta", "sample_count": 5},
        ]
        fixed = [
            {"artist": f"fixed_{index}", "weight": 0.5 + index * 0.1}
            for index in range(5)
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 7,
                "scores": [1, 2, 3, 4, 5],
                "shared_artist_min": 2,
                "shared_artist_max": 2,
                "fixed_artists": fixed,
                "rng_seed": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 7)
        self.assertEqual(sum(bool(item.get("shared_style")) for item in artists), 2)
        self.assertTrue({item["artist"] for item in fixed} <= {item["artist"] for item in artists})

    def test_zero_shared_slots_fill_only_the_remainder_from_rated_artists(self):
        fixed = [
            {"artist": f"fixed_{index}", "weight": 0.5 + index * 0.1}
            for index in range(5)
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 7,
                "scores": [4, 5],
                "shared_artist_min": 0,
                "shared_artist_max": 0,
                "fixed_artists": fixed,
                "rng_seed": 7,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 7)
        self.assertEqual({item["artist"] for item in artists if item.get("score")}, {"alpha", "beta"})
        self.assertFalse(any(item.get("shared_style") for item in artists))

    def test_profile_uses_open_total_slots_when_fixed_artists_occupy_later_positions(self):
        fixed = [
            {"artist": f"fixed_{index}", "weight": 0.7 + index * 0.1, "slot": index + 3}
            for index in range(5)
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 7,
                "scores": [4, 5],
                "shared_artist_min": 0,
                "shared_artist_max": 0,
                "fixed_artists": fixed,
                "weight_mode": "profile",
                "min_weight": 0.1,
                "max_weight": 2.3,
                "weight_profile": [
                    {"position": 0, "weight": 1.5},
                    {"position": 1 / 6, "weight": 1.0},
                    {"position": 1, "weight": 2.3},
                ],
                "rng_seed": 7,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        random_artists = [item for item in artists if not item["artist"].startswith("fixed_")]
        self.assertEqual([item["weight"] for item in random_artists], [1.5, 1.0])
        self.assertEqual(
            [item["weight"] for item in artists if item["artist"].startswith("fixed_")],
            [round(item["weight"], 2) for item in fixed],
        )

    @patch("app.get_shared_style_artist_pool")
    def test_endpoint_can_build_twelve_artists_only_from_shared_styles(self, shared_pool):
        shared_pool.return_value = [
            {"artist": f"shared_{index}", "sample_count": 20 - index}
            for index in range(12)
        ] + [{"artist": "shared 0", "sample_count": 1}]
        with closing(app.db()) as conn, conn:
            conn.execute("DELETE FROM ratings")
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "count": 12,
                "scores": [1, 2, 3, 4, 5],
                "shared_artist_min": 12,
                "shared_artist_max": 12,
                "rng_seed": 17,
            },
        )
        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 12)
        self.assertEqual(len({item["artist"].replace("_", " ").casefold() for item in artists}), 12)
        self.assertTrue(all(item["shared_style"] for item in artists))

    @patch("app.get_shared_style_artist_pool")
    def test_endpoint_randomizes_shared_count_inside_requested_range(self, shared_pool):
        shared_pool.return_value = [
            {"artist": f"shared_{index}", "sample_count": 20 - index}
            for index in range(8)
        ]
        counts = set()
        for seed in range(12):
            response = self.client.post(
                "/api/style-maker/artists",
                json={
                    "count": 5,
                    "scores": [1, 2, 3, 4, 5],
                    "shared_artist_min": 2,
                    "shared_artist_max": 4,
                    "rng_seed": seed,
                },
            )
            self.assertEqual(response.status_code, 200)
            counts.add(sum(bool(item.get("shared_style")) for item in response.get_json()["artists"]))
        self.assertTrue(counts <= {2, 3, 4})
        self.assertGreater(len(counts), 1)

    def test_optional_artists_preserve_order_and_only_reroll_weights(self):
        supplied = [
            {"artist": "gamma", "score": 2},
            {"artist": "alpha", "score": 5},
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "artists": supplied,
                "weight_mode": "random",
                "min_weight": 0.1,
                "max_weight": 2.3,
                "rng_seed": 11,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["artist"] for item in response.get_json()["artists"]],
            ["gamma", "alpha"],
        )

    def test_profile_mode_preserves_prompt_positions(self):
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "artists": [
                    {"artist": "gamma", "score": 2},
                    {"artist": "alpha", "score": 5},
                    {"artist": "beta", "score": 4},
                ],
                "reroll": "weights",
                "weight_mode": "profile",
                "min_weight": 0.1,
                "max_weight": 2.3,
                "weight_profile": [
                    {"position": 0, "weight": 0.2},
                    {"position": 0.5, "weight": 2.1},
                    {"position": 1, "weight": 0.4},
                ],
                "rng_seed": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual([item["artist"] for item in artists], ["gamma", "alpha", "beta"])
        self.assertGreater(artists[1]["weight"], artists[0]["weight"])
        self.assertGreater(artists[1]["weight"], artists[2]["weight"])

    def test_initial_and_all_reroll_results_are_sorted_by_weight_ascending(self):
        for payload in (
            {
                "count": 3,
                "scores": [2, 3, 4, 5],
                "weight_mode": "random",
                "rng_seed": 7,
            },
            {
                "reroll": "all",
                "count": 3,
                "scores": [2, 3, 4, 5],
                "weight_mode": "random",
                "rng_seed": 7,
            },
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/style-maker/artists", json=payload)
                weights = [item["weight"] for item in response.get_json()["artists"]]
                self.assertEqual(response.status_code, 200)
                self.assertEqual(weights, sorted(weights))

    def test_weight_reroll_preserves_artist_order_and_changes_only_weights(self):
        original_weights = [1.7, 0.4]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "reroll": "weights",
                "artists": [
                    {"artist": "gamma", "score": 2, "weight": 1.7},
                    {"artist": "alpha", "score": 5, "weight": 0.4},
                ],
                "weight_mode": "random",
                "rng_seed": 11,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(
            [item["artist"] for item in artists],
            ["gamma", "alpha"],
        )
        self.assertNotEqual([item["weight"] for item in artists], original_weights)

    def test_supplied_artists_do_not_require_scores_or_saved_ratings(self):
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "reroll": "weights",
                "artists": [
                    {"artist": "unrated_artist_a", "weight": 1.7},
                    {"artist": "unrated_artist_b", "weight": 0.4},
                ],
                "weight_mode": "random",
                "rng_seed": 11,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(
            [item["artist"] for item in artists],
            ["unrated_artist_a", "unrated_artist_b"],
        )
        self.assertNotIn("score", artists[0])
        self.assertIn("artist_prompt", response.get_json())

    def test_artist_reroll_selects_new_unique_artists_and_preserves_positional_weights(self):
        with closing(app.db()) as conn, conn:
            for artist, score in (("delta", 4), ("epsilon", 3)):
                conn.execute(
                    """
                    INSERT INTO ratings (
                        artist_tag, score, mode, created_at, updated_at
                    ) VALUES (?, ?, 'manual', ?, ?)
                    """,
                    (artist, score, app.now_text(), app.now_text()),
                )

        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "reroll": "artists",
                "artists": [
                    {"artist": "alpha", "score": 5, "weight": 1.7},
                    {"artist": "beta", "score": 4, "weight": 0.4},
                ],
                "count": 2,
                "scores": [2, 3, 4, 5],
                "rng_seed": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        names = [item["artist"] for item in artists]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(set(names).isdisjoint({"alpha", "beta"}))
        self.assertEqual([item["weight"] for item in artists], [1.7, 0.4])

    def test_artist_reroll_replaces_only_slots_remaining_after_fixed_artists(self):
        with closing(app.db()) as conn, conn:
            for artist, score in (("delta", 4), ("epsilon", 3)):
                conn.execute(
                    """
                    INSERT INTO ratings (
                        artist_tag, score, mode, created_at, updated_at
                    ) VALUES (?, ?, 'manual', ?, ?)
                    """,
                    (artist, score, app.now_text(), app.now_text()),
                )
        fixed = [
            {"artist": f"fixed_{index}", "weight": 0.5 + index * 0.1}
            for index in range(5)
        ]
        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "reroll": "artists",
                "artists": fixed + [
                    {"artist": "alpha", "score": 5, "weight": 1.7},
                    {"artist": "beta", "score": 4, "weight": 0.4},
                ],
                "fixed_artists": fixed,
                "count": 7,
                "scores": [2, 3, 4, 5],
                "rng_seed": 9,
            },
        )

        self.assertEqual(response.status_code, 200)
        artists = response.get_json()["artists"]
        self.assertEqual(len(artists), 7)
        self.assertTrue({item["artist"] for item in fixed} <= {item["artist"] for item in artists})
        random_artists = [item for item in artists if not item["artist"].startswith("fixed_")]
        self.assertEqual(len(random_artists), 2)
        self.assertTrue({item["artist"] for item in random_artists}.isdisjoint({"alpha", "beta"}))
        self.assertEqual([item["weight"] for item in random_artists], [1.7, 0.4])

    def test_endpoint_returns_400_for_invalid_user_input(self):
        invalid_payloads = (
            {"count": 4, "scores": [5]},
            {
                "artists": [
                    {"artist": "alpha", "score": 5},
                    {"artist": "alpha", "score": 5},
                ]
            },
            {"count": 1, "scores": [5], "weight_mode": "unknown"},
            {"count": 1, "scores": [5], "shared_artist_min": -1, "shared_artist_max": 1},
            {"count": 1, "scores": [5], "shared_artist_min": True, "shared_artist_max": 1},
            {"count": 1, "scores": [5], "shared_artist_min": 2, "shared_artist_max": 1},
            {"count": 1, "scores": [5], "shared_artist_max": -1},
            {"count": 1, "scores": [5], "shared_artist_max": True},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/api/style-maker/artists", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])
                self.assertTrue(response.get_json()["error"])

    def test_endpoint_strictly_validates_selected_scores(self):
        for score in (True, 1.0, 1.5, "1.0", "1.5", 0, 6):
            with self.subTest(score=score):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={"count": 1, "scores": [score]},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("평점", response.get_json()["error"])

        response = self.client.post(
            "/api/style-maker/artists",
            json={"count": 1, "scores": ["5"], "rng_seed": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["artists"][0]["score"], 5)

    def test_endpoint_strictly_validates_supplied_artist_scores(self):
        for score in (True, 5.0, 5.5, "5.0", "5.5", 0, 6):
            with self.subTest(score=score):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={"artists": [{"artist": "alpha", "score": score}]},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("평점", response.get_json()["error"])

        response = self.client.post(
            "/api/style-maker/artists",
            json={
                "artists": [{"artist": "alpha", "score": "5"}],
                "rng_seed": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["artists"][0]["score"], 5)

    def test_endpoint_requires_json_integer_rng_seed(self):
        for rng_seed in (True, 1.0, 1.5, "1"):
            with self.subTest(rng_seed=rng_seed):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={"count": 1, "scores": [5], "rng_seed": rng_seed},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("시드", response.get_json()["error"])

        for payload in (
            {"count": 1, "scores": [5]},
            {"count": 1, "scores": [5], "rng_seed": None},
            {"count": 1, "scores": [5], "rng_seed": 7},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post(
                        "/api/style-maker/artists", json=payload
                    ).status_code,
                    200,
                )

    def test_endpoint_requires_boolean_score_priority(self):
        for prefer_high_scores in (None, 0, 1, "false", []):
            with self.subTest(prefer_high_scores=prefer_high_scores):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={
                        "count": 1,
                        "scores": [5],
                        "prefer_high_scores": prefer_high_scores,
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("우선", response.get_json()["error"])

        for prefer_high_scores in (False, True):
            with self.subTest(prefer_high_scores=prefer_high_scores):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={
                        "count": 1,
                        "scores": [5],
                        "prefer_high_scores": prefer_high_scores,
                    },
                )
                self.assertEqual(response.status_code, 200)

    def test_endpoint_requires_ranges_to_be_json_array_when_supplied(self):
        for ranges in ({}, False, "", 0, None):
            with self.subTest(ranges=ranges):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json={"count": 1, "scores": [5], "ranges": ranges},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("구간", response.get_json()["error"])

        for payload in (
            {"count": 1, "scores": [5]},
            {"count": 1, "scores": [5], "ranges": []},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post(
                        "/api/style-maker/artists", json=payload
                    ).status_code,
                    200,
                )


class StyleStoreIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.db_path = self.data_dir / "artist_rater.sqlite"
        self.generated_dir = self.data_dir / "generated"
        self.originals = (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        )
        app.DATA_DIR = self.data_dir
        app.THUMBNAIL_DIR = self.data_dir / "thumbnails"
        app.GENERATED_DIR = self.generated_dir
        app.SETTINGS_JSON_PATH = self.data_dir / "settings.json"
        app.DB_PATH = self.db_path
        app.init_db()

    def tearDown(self):
        (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        ) = self.originals
        self.temp_dir.cleanup()

    def test_save_upserts_style_and_returns_parsed_list_and_detail(self):
        artists = [{"artist": "artist_a", "weight": 1.25, "score": 5}]
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": artists,
            "png_bytes": tiny_png(
                (b"\x00" + (b"\x00" * (832 * 4))) * 1216,
                width=832,
                height=1216,
            ),
            "base_prompt": "portrait",
            "negative_prompt": "lowres",
            "character_prompts": ["1girl"],
            "combined_prompt": "portrait, 1.25::artist:artist_a::",
            "seed": 123,
            "width": 832,
            "height": 1216,
            "sampler": "k_euler",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.0,
            "model": "nai-diffusion-4-full",
        }

        first = save_generated_result(request_id="request-1", **common)
        second = save_generated_result(request_id="request-2", **common)

        self.assertEqual(first["style_id"], second["style_id"])
        self.assertTrue((self.generated_dir / first["image_path"]).is_file())
        self.assertEqual(list(self.generated_dir.rglob("*.tmp")), [])

        styles = list_styles(self.db_path)
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles[0]["artists"], artists)
        self.assertEqual(styles[0]["image_count"], 2)

        detail = get_style_detail(self.db_path, first["style_id"])
        self.assertEqual(detail["artists"], artists)
        self.assertEqual(len(detail["images"]), 2)
        self.assertEqual(detail["images"][0]["character_prompts"], ["1girl"])

    def test_distinct_request_ids_cannot_overwrite_the_same_file(self):
        first_png = tiny_png()
        second_png = tiny_png(b"\x00\x00\xff\x00\xff")
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        first = save_generated_result(request_id="foo/", png_bytes=first_png, **common)
        second = save_generated_result(
            request_id="foo-14fe48f0fbfb", png_bytes=second_png, **common
        )

        self.assertNotEqual(first["image_path"], second["image_path"])
        self.assertEqual((self.generated_dir / first["image_path"]).read_bytes(), first_png)
        self.assertEqual((self.generated_dir / second["image_path"]).read_bytes(), second_png)

    def test_staged_file_names_are_unique(self):
        final_path = self.generated_dir / "1" / "image.png"
        self.assertNotEqual(_staged_file_path(final_path), _staged_file_path(final_path))

    def test_rejects_truncated_and_corrupt_crc_png_before_writing(self):
        valid_png = tiny_png()
        corrupt_crc = bytearray(valid_png)
        corrupt_crc[-5] ^= 0x01
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        for request_id, invalid_png in (
            ("truncated", valid_png[:-1]),
            ("corrupt-crc", bytes(corrupt_crc)),
        ):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                save_generated_result(
                    request_id=request_id, png_bytes=invalid_png, **common
                )

        with closing(connect_db(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0)
        self.assertEqual(list(self.generated_dir.rglob("*")), [])

    def test_rejects_invalid_zlib_and_invalid_scanlines(self):
        invalid_images = (
            ("invalid-zlib", png_with_idat(b"not-zlib")),
            ("wrong-length", tiny_png(b"\x00\xff\x00\x00")),
            ("invalid-filter", tiny_png(b"\x05\xff\x00\x00\xff")),
            ("interlaced", tiny_png(interlace=1)),
        )

        for request_id, invalid_png in invalid_images:
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                save_generated_result(
                    self.db_path,
                    self.generated_dir,
                    request_id=request_id,
                    artists=[{"artist": "artist_a", "weight": 1}],
                    png_bytes=invalid_png,
                )

    def test_storage_rejects_unexpected_png_dimensions(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            save_generated_result(
                self.db_path,
                self.generated_dir,
                request_id="wrong-dimensions",
                artists=[{"artist": "artist_a", "weight": 1}],
                png_bytes=tiny_png(),
                width=2,
                height=1,
            )

    def test_request_id_retry_returns_existing_result_without_rewriting(self):
        first_png = tiny_png()
        common = {
            "db_path": self.db_path,
            "generated_dir": self.generated_dir,
            "request_id": "retry-request",
            "artists": [{"artist": "artist_a", "weight": 1}],
        }

        first = save_generated_result(png_bytes=first_png, **common)
        second = save_generated_result(
            png_bytes=tiny_png(b"\x00\x00\x00\xff\xff"), **common
        )

        self.assertEqual(second, first)
        self.assertEqual((self.generated_dir / first["image_path"]).read_bytes(), first_png)
        style = list_styles(self.db_path)[0]
        self.assertEqual(style["image_count"], 1)

    def test_replace_failure_compensates_committed_database_rows(self):
        with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                save_generated_result(
                    self.db_path,
                    self.generated_dir,
                    request_id="replace-failure",
                    artists=[{"artist": "artist_a", "weight": 1}],
                    png_bytes=tiny_png(),
                )

        with closing(connect_db(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0)
        self.assertEqual(list(self.generated_dir.rglob("*.tmp")), [])
        self.assertEqual(list(self.generated_dir.rglob("*.png")), [])

    def test_replace_failure_restores_existing_style_summary(self):
        artists = [{"artist": "artist_a", "weight": 1}]
        first = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="first-image",
            artists=artists,
            png_bytes=tiny_png(),
        )

        with patch("pathlib.Path.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                save_generated_result(
                    self.db_path,
                    self.generated_dir,
                    request_id="failed-second-image",
                    artists=artists,
                    png_bytes=tiny_png(b"\x00\x00\xff\x00\xff"),
                )

        style = list_styles(self.db_path)[0]
        self.assertEqual(style["image_count"], 1)
        self.assertEqual(style["representative_image_path"], first["image_path"])
        self.assertTrue((self.generated_dir / first["image_path"]).is_file())

    def test_reconcile_removes_stale_temp_and_unreferenced_png(self):
        saved = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="referenced",
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        stale_temp = self.generated_dir / "1" / ".stale.png.deadbeef.tmp"
        orphan = self.generated_dir / "1" / "orphan.png"
        stale_temp.write_bytes(b"stale")
        orphan.write_bytes(tiny_png())
        stale_time = time.time() - 7200
        for path in (stale_temp, orphan):
            os.utime(path, (stale_time, stale_time))

        app.init_db()

        self.assertFalse(stale_temp.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue((self.generated_dir / saved["image_path"]).is_file())

    def test_reconcile_keeps_fresh_unreferenced_files(self):
        fresh_temp = self.generated_dir / "1" / ".fresh.png.token.tmp"
        fresh_orphan = self.generated_dir / "1" / "fresh-orphan.png"
        fresh_temp.parent.mkdir(parents=True)
        fresh_temp.write_bytes(b"fresh")
        fresh_orphan.write_bytes(tiny_png())

        app.init_db()

        self.assertTrue(fresh_temp.is_file())
        self.assertTrue(fresh_orphan.is_file())

    def test_reconcile_promotes_committed_staged_file(self):
        saved = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="crash-window",
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        final_path = self.generated_dir / saved["image_path"]
        staged_path = final_path.with_name(f".{final_path.name}.crash-token.tmp")
        final_path.replace(staged_path)

        app.init_db()

        self.assertTrue(final_path.is_file())
        self.assertFalse(staged_path.exists())

    def test_reconcile_removes_missing_image_record_and_allows_retry(self):
        request_id = "missing-only-image"
        saved = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id=request_id,
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        (self.generated_dir / saved["image_path"]).unlink()

        app.init_db()

        self.assertEqual(list_styles(self.db_path), [])
        retried = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id=request_id,
            artists=[{"artist": "artist_a", "weight": 1}],
            png_bytes=tiny_png(),
        )
        self.assertTrue((self.generated_dir / retried["image_path"]).is_file())

    def test_reconcile_recomputes_style_with_one_remaining_image(self):
        artists = [{"artist": "artist_a", "weight": 1}]
        first = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="remaining-image",
            artists=artists,
            png_bytes=tiny_png(),
        )
        missing = save_generated_result(
            self.db_path,
            self.generated_dir,
            request_id="missing-newest-image",
            artists=artists,
            png_bytes=tiny_png(b"\x00\x00\xff\x00\xff"),
        )
        (self.generated_dir / missing["image_path"]).unlink()

        app.init_db()

        style = list_styles(self.db_path)[0]
        self.assertEqual(style["image_count"], 1)
        self.assertEqual(style["representative_image_path"], first["image_path"])
        detail = get_style_detail(self.db_path, first["style_id"])
        self.assertEqual(
            [image["image_path"] for image in detail["images"]],
            [first["image_path"]],
        )


if __name__ == "__main__":
    unittest.main()
