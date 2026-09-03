import io
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
import urllib.error
import warnings
import zipfile
import zlib
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import app
import style_store
from arca_style_collector import ArcaCollectorError
from nai_artist_test_store import complete_item, create_test, save_direct_rating
from style_group_store import create_group, record_style_group_artist_decision


SECRET_KEY = "secret-key-value"


def valid_png(width=832, height=1216):
    def chunk(kind, payload):
        checksum = zlib.crc32(kind)
        checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    scanlines = (b"\x00" + (b"\x00" * (width * 4))) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


def zip_response(entries):
    payload = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, value in entries:
                archive.writestr(name, value)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read = Mock(return_value=payload.getvalue())
    return response


class SettingsStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.trusted_root = Path(self.temp_dir.name) / "data"
        self.settings_path = self.trusted_root / "settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_missing_settings_returns_empty_string(self):
        self.trusted_root.mkdir()
        self.assertEqual(
            style_store.load_app_key(self.settings_path, self.trusted_root), ""
        )

    def test_corrupt_settings_raise_and_preserve_original_bytes(self):
        self.trusted_root.mkdir()
        for original in (b"not-json", b"[]", b'"text"', b"\xff\xfe"):
            with self.subTest(original=original):
                self.settings_path.write_bytes(original)
                operations = (
                    lambda: style_store.load_app_key(
                        self.settings_path, self.trusted_root
                    ),
                    lambda: style_store.save_app_key(
                        self.settings_path, SECRET_KEY, self.trusted_root
                    ),
                    lambda: style_store.delete_app_key(
                        self.settings_path, self.trusted_root
                    ),
                )
                for operation in operations:
                    with self.assertRaises(style_store.SettingsError):
                        operation()
                    self.assertEqual(self.settings_path.read_bytes(), original)

    def test_save_preserves_unrelated_settings_and_stores_trimmed_key(self):
        self.trusted_root.mkdir()
        self.settings_path.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": "old"}),
            encoding="utf-8",
        )

        style_store.save_app_key(
            self.settings_path, f"  {SECRET_KEY}\t", self.trusted_root
        )

        self.assertEqual(
            style_store.load_app_key(self.settings_path, self.trusted_root), SECRET_KEY
        )
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {"theme": "dark", "novelai_app_key": SECRET_KEY},
        )
        self.assertEqual(list(self.trusted_root.glob("*.tmp")), [])

    def test_save_rejects_malformed_keys(self):
        values = (None, "", "   ", 1, True, [], {}, "line\nbreak", "bad\x00key", "x" * 8193)
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                style_store.save_app_key(
                    self.settings_path, value, self.trusted_root
                )
        self.assertFalse(self.settings_path.exists())

    def test_atomic_replace_failure_preserves_prior_file_and_cleans_temp(self):
        self.trusted_root.mkdir()
        original = json.dumps({"novelai_app_key": "old"}).encode("utf-8")
        self.settings_path.write_bytes(original)

        with patch("style_store.Path.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(style_store.SettingsError):
                style_store.save_app_key(
                    self.settings_path, SECRET_KEY, self.trusted_root
                )

        self.assertEqual(self.settings_path.read_bytes(), original)
        self.assertEqual(list(self.trusted_root.glob("*.tmp")), [])

    def test_rejects_settings_outside_trusted_root(self):
        self.trusted_root.mkdir()
        outside = Path(self.temp_dir.name) / "settings.json"
        with self.assertRaises(style_store.SettingsError):
            style_store.load_app_key(outside, self.trusted_root)

    def test_rejects_symlink_settings_file(self):
        self.trusted_root.mkdir()
        target = Path(self.temp_dir.name) / "target.json"
        target.write_text("{}", encoding="utf-8")
        try:
            self.settings_path.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaises(style_store.SettingsError):
            style_store.load_app_key(self.settings_path, self.trusted_root)

    def test_rejects_symlinked_directory_component(self):
        real_root = Path(self.temp_dir.name) / "real"
        real_root.mkdir()
        linked_root = Path(self.temp_dir.name) / "linked"
        try:
            linked_root.symlink_to(real_root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlink creation unavailable: {exc}")
        with self.assertRaises(style_store.SettingsError):
            style_store.save_app_key(
                linked_root / "settings.json", SECRET_KEY, linked_root
            )

    def test_delete_preserves_other_settings_or_removes_empty_file(self):
        self.trusted_root.mkdir()
        self.settings_path.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": SECRET_KEY}),
            encoding="utf-8",
        )
        style_store.delete_app_key(self.settings_path, self.trusted_root)
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {"theme": "dark"},
        )

        self.settings_path.write_text(
            json.dumps({"novelai_app_key": SECRET_KEY}), encoding="utf-8"
        )
        style_store.delete_app_key(self.settings_path, self.trusted_root)
        self.assertFalse(self.settings_path.exists())

    def test_skip_delete_confirmation_round_trip_preserves_other_settings(self):
        self.trusted_root.mkdir()
        self.settings_path.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": SECRET_KEY}),
            encoding="utf-8",
        )
        defaults = style_store.default_delete_confirmation_preferences()
        self.assertEqual(
            style_store.load_skip_delete_confirmation(self.settings_path, self.trusted_root), defaults
        )
        preferences = style_store.default_delete_confirmation_preferences(True)
        style_store.save_skip_delete_confirmation(
            self.settings_path, preferences, self.trusted_root
        )
        self.assertEqual(style_store.load_skip_delete_confirmation(self.settings_path, self.trusted_root), preferences)
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {"theme": "dark", "novelai_app_key": SECRET_KEY, "skip_delete_confirmation": preferences},
        )

    def test_legacy_boolean_migrates_to_all_categories(self):
        self.trusted_root.mkdir()
        self.settings_path.write_text(json.dumps({"skip_delete_confirmation": True}), encoding="utf-8")
        self.assertEqual(
            style_store.load_skip_delete_confirmation(self.settings_path, self.trusted_root),
            style_store.default_delete_confirmation_preferences(True),
        )


class StyleApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.originals = (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        )
        app.DATA_DIR = self.tmp
        app.THUMBNAIL_DIR = self.tmp / "thumbnails"
        app.GENERATED_DIR = self.tmp / "generated"
        app.SETTINGS_JSON_PATH = self.tmp / "settings.json"
        app.DB_PATH = self.tmp / "artist_rater.sqlite"
        app.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
        ) = self.originals
        self.temp_dir.cleanup()

    def assert_secret_absent(self, response):
        self.assertNotIn(SECRET_KEY, response.get_data(as_text=True))
        with closing(sqlite3.connect(app.DB_PATH)) as conn:
            dump = "\n".join(conn.iterdump())
        self.assertNotIn(SECRET_KEY, dump)

    def make_artist_source_fixture(self):
        timestamp = app.now_text()
        with closing(app.db()) as conn, conn:
            conn.execute(
                """
                INSERT INTO ratings
                    (artist_tag, score, rating_status, mode, query_text, query_tags_json, created_at, updated_at)
                VALUES (?, ?, 'rated', 'manual', ?, ?, ?, ?)
                """,
                ("same_artist", 2, "fixture query", '["portrait"]', timestamp, timestamp),
            )
        test = create_test(
            app.DB_PATH,
            "보완 NAI 테스트",
            {
                "base_prompt": "{{artist}}, watercolor",
                "prompt_variants": [{"prompt": "{{artist}}, watercolor", "images_per_artist": 1}],
                "model": "nai-diffusion-5-full",
                "width": 832,
                "height": 1216,
                "sampler": "k_euler_ancestral",
                "steps": 28,
                "scale": 5.0,
                "cfg_rescale": 0.4,
            },
            [
                {"artist_tag": "same_artist"},
                {"artist_tag": "unrated_direct"},
            ],
            1,
            0,
        )
        save_direct_rating(app.DB_PATH, test["id"], "same_artist", 4)
        group_dir = self.tmp / "style_group_images"
        group = create_group(
            app.DB_PATH,
            group_dir,
            "보완 그림체 그룹",
            sources=[{"source_type": "nai_test", "source_id": str(test["id"]), "label": "연결 NAI"}],
        )
        record_style_group_artist_decision(
            app.DB_PATH,
            group_dir,
            group["id"],
            "same_artist",
            True,
            direct=True,
        )
        record_style_group_artist_decision(
            app.DB_PATH,
            group_dir,
            group["id"],
            "unrated_direct",
            True,
            direct=True,
        )
        return test, group

    def style_artist_payload(self, **overrides):
        payload = {
            "count": 1,
            "scores": [1, 2, 3, 4, 5],
            "weight_mode": "random",
            "min_weight": 1.0,
            "max_weight": 1.0,
            "rng_seed": 7,
        }
        payload.update(overrides)
        return payload

    def test_style_maker_artist_sources_validate_minimum_duplicate_and_type(self):
        for source_value in (
            [],
            [
                {"source_type": "nai_test", "source_id": "1"},
                {"source_type": "nai_test", "source_id": "1"},
            ],
            [{"source_type": "unknown", "source_id": "1"}],
        ):
            with self.subTest(source_value=source_value):
                response = self.client.post(
                    "/api/style-maker/artists",
                    json=self.style_artist_payload(artist_sources=source_value),
                )
                self.assertEqual(response.status_code, 400)

    def test_style_maker_artist_source_list_contains_all_source_sections(self):
        test, group = self.make_artist_source_fixture()

        response = self.client.get("/api/style-maker/artist-sources")

        self.assertEqual(response.status_code, 200)
        sources = response.get_json()["sources"]
        self.assertTrue({item["source_type"] for item in sources} >= {"rating_management", "nai_test", "style_group"})
        self.assertIn({"source_type": "nai_test", "source_id": str(test["id"])}, [
            {"source_type": item["source_type"], "source_id": item["source_id"]} for item in sources
        ])
        self.assertIn({"source_type": "style_group", "source_id": str(group["id"])}, [
            {"source_type": item["source_type"], "source_id": item["source_id"]} for item in sources
        ])

    def test_style_maker_nai_artist_source_detail_contains_prompt_settings_and_scores(self):
        test, _ = self.make_artist_source_fixture()

        response = self.client.get(f"/api/style-maker/artist-sources/nai_test/{test['id']}")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        same = next(item for item in data["artists"] if item["artist_key"] == "same artist")
        self.assertEqual(same["score"], 4.0)
        self.assertEqual(same["score_bucket"], 4)
        self.assertEqual(data["prompts"][0]["prompt"], "{{artist}}, watercolor")
        self.assertEqual(data["settings"]["model"], "nai-diffusion-5-full")
        self.assertEqual(data["settings"]["width"], 832)

    def test_style_group_detail_shows_unscored_direct_artist_but_candidate_excludes_it(self):
        _, group = self.make_artist_source_fixture()

        detail = self.client.get(f"/api/style-maker/artist-sources/style_group/{group['id']}")
        self.assertEqual(detail.status_code, 200)
        unscored = next(item for item in detail.get_json()["artists"] if item["artist_key"] == "unrated direct")
        self.assertIsNone(unscored["score"])
        self.assertIsNone(unscored["score_bucket"])
        self.assertEqual(unscored["score_sources"], [])

        candidates = self.client.post(
            "/api/style-maker/artists",
            json=self.style_artist_payload(artist_sources=[{"source_type": "style_group", "source_id": str(group["id"])}]),
        )
        self.assertEqual(candidates.status_code, 200)
        self.assertEqual([item["artist"] for item in candidates.get_json()["artists"]], ["same_artist"])

    def test_style_maker_artist_sources_average_and_legacy_rating_source_fallback(self):
        test, group = self.make_artist_source_fixture()
        sources = [
            {"source_type": "rating_management", "source_id": "all"},
            {"source_type": "nai_test", "source_id": str(test["id"])},
            {"source_type": "style_group", "source_id": str(group["id"])},
        ]

        averaged = self.client.post(
            "/api/style-maker/artists",
            json=self.style_artist_payload(artist_sources=sources, scores=[3]),
        )
        self.assertEqual(averaged.status_code, 200)
        self.assertEqual(averaged.get_json()["artists"][0]["artist"], "same_artist")
        self.assertEqual(averaged.get_json()["artists"][0]["score"], 3)

        legacy = self.client.post(
            "/api/style-maker/artists",
            json=self.style_artist_payload(rating_source="danbooru", scores=[2]),
        )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.get_json()["artists"][0]["artist"], "same_artist")
        self.assertEqual(legacy.get_json()["artists"][0]["score"], 2)

    def test_settings_round_trip_never_returns_or_stores_key_in_database(self):
        response = self.client.put(
            "/api/settings/novelai", json={"app_key": SECRET_KEY}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"configured": True})
        get_response = self.client.get("/api/settings/novelai")
        self.assertEqual(get_response.get_json(), {"configured": True})
        self.assert_secret_absent(response)
        self.assert_secret_absent(get_response)

    def test_missing_settings_report_not_configured(self):
        response = self.client.get("/api/settings/novelai")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"configured": False})

    def test_delete_confirmation_preference_round_trip_and_validation(self):
        defaults = style_store.default_delete_confirmation_preferences()
        self.assertEqual(
            self.client.get("/api/settings/preferences").get_json(),
            {"skip_delete_confirmation": defaults},
        )
        preferences = {**defaults, "rating": True, "novelai_key": True}
        saved = self.client.put(
            "/api/settings/preferences", json={"skip_delete_confirmation": preferences}
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json(), {"skip_delete_confirmation": preferences})
        self.assertEqual(
            self.client.get("/api/settings/preferences").get_json(),
            {"skip_delete_confirmation": preferences},
        )
        invalid = self.client.put(
            "/api/settings/preferences", json={"skip_delete_confirmation": {"rating": True}}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.get("/api/settings/preferences").get_json()["skip_delete_confirmation"], preferences)

    @patch("app.get_style_maker_prompt_presets")
    def test_style_maker_prompt_presets_use_selected_artists(self, get_presets):
        get_presets.return_value = {
            "presets": [{"key": "preset", "quality_prompt": "masterpiece", "negative_prompt": "lowres"}],
            "selected_artist_count": 1,
        }

        response = self.client.post(
            "/api/style-maker/prompt-presets",
            json={"artists": ["alpha"], "limit": 12},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        get_presets.assert_called_once_with(app.DB_PATH, ["alpha"], 12)

    @patch("app.get_style_maker_prompt_presets")
    def test_style_maker_prompt_presets_pass_model_filter(self, get_presets):
        get_presets.return_value = {"presets": [], "selected_artist_count": 1}

        response = self.client.post(
            "/api/style-maker/prompt-presets",
            json={"artists": ["alpha"], "limit": 12, "model_filter": "v5"},
        )

        self.assertEqual(response.status_code, 200)
        get_presets.assert_called_once_with(app.DB_PATH, ["alpha"], 12, "v5")

    @patch("app.get_style_maker_prompt_presets", side_effect=ArcaCollectorError("모델 필터 값이 올바르지 않습니다."))
    def test_style_maker_prompt_presets_returns_bad_request_for_invalid_model_filter(self, get_presets):
        response = self.client.post(
            "/api/style-maker/prompt-presets",
            json={"artists": ["alpha"], "model_filter": "v3"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])

    @patch("app.get_style_maker_prompt_presets")
    def test_edited_prompt_preset_is_persisted_and_returned_on_later_load(self, get_presets):
        app.save_app_key(app.SETTINGS_JSON_PATH, SECRET_KEY, app.DATA_DIR)
        get_presets.return_value = {
            "presets": [{
                "key": "0123456789abcdef",
                "base_prompt": "original quality",
                "quality_prompt": "original quality",
                "negative_prompt": "lowres",
                "excluded_tags": [{"tag": "1girl", "prompt": "1girl"}],
                "representative_image": {"image_path": "sample.png"},
            }],
            "selected_artist_count": 0,
        }
        updated = self.client.patch(
            "/api/style-maker/prompt-presets/0123456789abcdef",
            json={"quality_prompt": "edited quality, cinematic lighting"},
        )
        self.assertEqual(updated.status_code, 200)

        loaded = self.client.post(
            "/api/style-maker/prompt-presets",
            json={"artists": [], "limit": 30},
        ).get_json()["presets"][0]
        self.assertEqual(loaded["quality_prompt"], "edited quality, cinematic lighting")
        self.assertEqual(loaded["original_quality_prompt"], "original quality")
        self.assertTrue(loaded["modified"])
        self.assertEqual(loaded["representative_image"]["thumbnail_url"], "/style-manager-thumbnails/shared/sample.png")
        saved = json.loads(app.SETTINGS_JSON_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["prompt_preset_overrides"]["0123456789abcdef"], "edited quality, cinematic lighting")
        self.assertEqual(saved["novelai_app_key"], SECRET_KEY)

    def test_put_requires_json_object_and_rejects_malformed_keys(self):
        invalid_requests = (
            {"data": json.dumps({"app_key": SECRET_KEY}), "content_type": "text/plain"},
            {"json": {"app_key": SECRET_KEY}, "content_type": "application/vnd.api+json"},
            {"data": "not-json", "content_type": "application/json"},
            {"json": []},
            {"json": {}},
            {"json": {"app_key": ""}},
            {"json": {"app_key": "line\nbreak"}},
            {"json": {"app_key": "bad\x00key"}},
            {"json": {"app_key": "x" * 8193}},
            {"json": {"app_key": 123}},
            {"json": {"app_key": True}},
        )
        for kwargs in invalid_requests:
            with self.subTest(kwargs=kwargs):
                response = self.client.put("/api/settings/novelai", **kwargs)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(app.SETTINGS_JSON_PATH.exists())
                self.assert_secret_absent(response)

    def test_put_trims_outer_whitespace_before_storage(self):
        response = self.client.put(
            "/api/settings/novelai", json={"app_key": f"  {SECRET_KEY}\t"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            style_store.load_app_key(app.SETTINGS_JSON_PATH, app.DATA_DIR),
            SECRET_KEY,
        )

    def test_corrupt_settings_return_conflict_without_modification(self):
        original = b"\xffbroken-json"
        app.SETTINGS_JSON_PATH.write_bytes(original)

        responses = (
            self.client.get("/api/settings/novelai"),
            self.client.put(
                "/api/settings/novelai", json={"app_key": SECRET_KEY}
            ),
            self.client.delete("/api/settings/novelai"),
            self.client.post("/api/settings/novelai/test"),
        )
        for response in responses:
            with self.subTest(method=response.request.method):
                self.assertEqual(response.status_code, 409)
                self.assertIn("settings", response.get_json()["error"].lower())
                self.assert_secret_absent(response)
                self.assertEqual(app.SETTINGS_JSON_PATH.read_bytes(), original)

    @patch("app.test_novelai_subscription", return_value={"anlas": 1234})
    def test_connection_uses_server_saved_key_without_returning_it(self, test_subscription):
        self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})
        response = self.client.post("/api/settings/novelai/test")
        self.assertEqual(
            response.get_json(), {"ok": True, "configured": True, "anlas": 1234}
        )
        test_subscription.assert_called_once_with(SECRET_KEY)
        self.assert_secret_absent(response)

    def test_connection_without_saved_key_is_rejected(self):
        response = self.client.post("/api/settings/novelai/test")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["configured"], False)
        self.assertEqual(response.get_json()["ok"], False)

    @patch("app.test_novelai_subscription")
    def test_connection_returns_sanitized_auth_error(self, test_subscription):
        test_subscription.side_effect = app.NovelAIError(401, "Authentication failed.")
        self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})
        response = self.client.post("/api/settings/novelai/test")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["configured"], True)
        self.assertEqual(response.get_json()["error"], "Authentication failed.")
        self.assert_secret_absent(response)

    def test_delete_preserves_unrelated_settings_and_returns_false(self):
        app.SETTINGS_JSON_PATH.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": SECRET_KEY}),
            encoding="utf-8",
        )
        response = self.client.delete("/api/settings/novelai")
        self.assertEqual(response.get_json(), {"configured": False})
        self.assertEqual(
            json.loads(app.SETTINGS_JSON_PATH.read_text(encoding="utf-8")),
            {"theme": "dark"},
        )
        self.assert_secret_absent(response)


class NovelAIGenerationTest(unittest.TestCase):
    def generation_data(self, **overrides):
        data = {
            "width": 832,
            "height": 1216,
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.4,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "native",
            "base_prompt": "masterpiece",
            "negative_prompt": "lowres",
            "character_prompts": [" hero ", " villain "],
        }
        data.update(overrides)
        return data

    def test_combine_base_prompt_has_no_dangling_commas(self):
        from novelai import combine_base_prompt

        self.assertEqual(combine_base_prompt(" base ", " artist "), "artist, base")
        self.assertEqual(combine_base_prompt("base", "artist", "leading"), "leading, artist, base")
        self.assertEqual(combine_base_prompt("base", "artist", ""), "artist, base")
        self.assertEqual(combine_base_prompt("base", ""), "base")
        self.assertEqual(combine_base_prompt("", "artist"), "artist")
        self.assertEqual(combine_base_prompt("", ""), "")

    def test_generation_normalizes_optional_leading_prompt(self):
        from novelai import normalize_generation_data

        normalized = normalize_generation_data(self.generation_data(leading_prompt="  style prefix  "))
        self.assertEqual(normalized["leading_prompt"], "style prefix")
        self.assertEqual(normalize_generation_data(self.generation_data())["leading_prompt"], "")

    def test_generation_normalizes_numeric_tag_closers(self):
        from novelai import build_generation_payload

        payload = build_generation_payload(
            self.generation_data(
                base_prompt="2::year 2025::",
                negative_prompt="-2::bad 3::",
                character_prompts=["1.2::character 2::"],
            ),
            "1.5::artist:matrix16::",
            42,
        )
        self.assertEqual(payload["input"], "1.5::artist:matrix16 ::, 2::year 2025 ::")
        self.assertEqual(payload["parameters"]["negative_prompt"], "-2::bad 3 ::")
        self.assertEqual(
            payload["parameters"]["v4_prompt"]["caption"]["char_captions"][0]["char_caption"],
            "1.2::character 2 ::",
        )

    def test_build_generation_payload_is_exact_v45_structure(self):
        from novelai import MODEL, build_generation_payload

        payload = build_generation_payload(self.generation_data(), "1.2::artist::", 42)
        self.assertEqual(
            payload,
            {
                "input": "1.2::artist::, masterpiece",
                "model": "nai-diffusion-4-5-full",
                "action": "generate",
                "parameters": {
                    "width": 832,
                    "height": 1216,
                    "n_samples": 1,
                    "seed": 42,
                    "extra_noise_seed": 42,
                    "sampler": "k_euler_ancestral",
                    "steps": 28,
                    "scale": 5.0,
                    "negative_prompt": "lowres",
                    "cfg_rescale": 0.4,
                    "noise_schedule": "native",
                    "params_version": 3,
                    "legacy": False,
                    "legacy_v3_extend": False,
                    "add_original_image": False,
                    "ucPreset": 0,
                    "qualityToggle": False,
                    "prefer_brownian": True,
                    "controlnet_strength": 1.0,
                    "dynamic_thresholding": False,
                    "sm": False,
                    "sm_dyn": False,
                    "deliberate_euler_ancestral_bug": False,
                    "reference_image_multiple": [],
                    "reference_information_extracted_multiple": [],
                    "reference_strength_multiple": [],
                    "v4_negative_prompt": {
                        "caption": {
                            "base_caption": "lowres",
                            "char_captions": [
                                {"char_caption": "lowres", "centers": [{"x": 0.5, "y": 0.5}]},
                                {"char_caption": "lowres", "centers": [{"x": 0.5, "y": 0.5}]},
                            ],
                        },
                        "use_coords": False,
                        "use_order": False,
                        "legacy_uc": False,
                    },
                    "v4_prompt": {
                        "caption": {
                            "base_caption": "1.2::artist::, masterpiece",
                            "char_captions": [
                                {"char_caption": "hero", "centers": [{"x": 0.5, "y": 0.5}]},
                                {"char_caption": "villain", "centers": [{"x": 0.5, "y": 0.5}]},
                            ],
                        },
                        "use_coords": False,
                        "use_order": True,
                        "legacy_uc": False,
                    },
                },
            },
        )
        self.assertEqual(MODEL, payload["model"])

    def test_generation_payload_uses_selected_noise_schedule(self):
        from novelai import build_generation_payload

        payload = build_generation_payload(
            self.generation_data(noise_schedule="karras"), "artist", 42
        )
        self.assertEqual(payload["parameters"]["noise_schedule"], "karras")

    def test_generation_transport_posts_json_and_extracts_first_png(self):
        from novelai import GENERATION_URL, generate_novelai_png

        png = valid_png()
        opener = Mock(return_value=zip_response([("notes.txt", b"x"), ("image.png", png)]))
        image, seed = generate_novelai_png(
            SECRET_KEY,
            self.generation_data(seed=123),
            "artist",
            opener=opener,
        )
        self.assertEqual((image, seed), (png, 123))
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, GENERATION_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertRegex(request.headers["X-correlation-id"], r"^[A-Za-z0-9]{6}$")
        self.assertEqual(request.unredirected_hdrs["Authorization"], f"Bearer {SECRET_KEY}")
        self.assertEqual(json.loads(request.data)["parameters"]["seed"], 123)

    @patch("novelai.random.SystemRandom")
    def test_generation_uses_bounded_random_seed_when_omitted(self, system_random):
        from novelai import generate_novelai_png

        system_random.return_value.randint.return_value = 4294967295
        image, seed = generate_novelai_png(
            SECRET_KEY,
            self.generation_data(),
            "artist",
            opener=Mock(return_value=zip_response([("image.png", valid_png())])),
        )
        self.assertEqual(image, valid_png())
        self.assertEqual(seed, 4294967295)
        system_random.return_value.randint.assert_called_once_with(1, 4294967295)

    def test_generation_rejects_unsafe_or_invalid_zip_content(self):
        from novelai import MAX_IMAGE_BYTES, NovelAIError, generate_novelai_png

        cases = (
            Mock(return_value=zip_response([("../image.png", valid_png())])),
            Mock(return_value=zip_response([("image.png", b"not-png")])),
            Mock(return_value=zip_response([("image.png", b"x" * (MAX_IMAGE_BYTES + 1))])),
            Mock(return_value=zip_response([("notes.txt", b"none")])),
            Mock(return_value=Mock(__enter__=Mock(return_value=Mock(read=Mock(return_value=b"bad-zip"))), __exit__=Mock(return_value=False))),
        )
        for opener in cases:
            with self.subTest(opener=opener), self.assertRaises(NovelAIError) as raised:
                generate_novelai_png(SECRET_KEY, self.generation_data(seed=1), "artist", opener=opener)
            self.assertEqual(raised.exception.status_code, 502)
            self.assertNotIn(SECRET_KEY, str(raised.exception))

    def test_generation_rejects_png_dimension_mismatch(self):
        from novelai import NovelAIError, generate_novelai_png

        opener = Mock(return_value=zip_response([("image.png", valid_png(64, 64))]))
        with self.assertRaises(NovelAIError) as raised:
            generate_novelai_png(
                SECRET_KEY, self.generation_data(seed=1), "artist", opener=opener
            )
        self.assertEqual(raised.exception.status_code, 502)

    def test_generation_rejects_duplicate_normalized_zip_names(self):
        from novelai import NovelAIError, generate_novelai_png

        opener = Mock(
            return_value=zip_response(
                [("folder\\image.png", valid_png()), ("folder/image.png", valid_png())]
            )
        )
        with self.assertRaises(NovelAIError) as raised:
            generate_novelai_png(
                SECRET_KEY, self.generation_data(seed=1), "artist", opener=opener
            )
        self.assertEqual(raised.exception.status_code, 502)

    def test_generation_rejects_zip_entry_count_and_total_size(self):
        from novelai import MAX_ZIP_ENTRIES, NovelAIError, generate_novelai_png

        cases = (
            [(f"note-{index}.txt", b"x") for index in range(MAX_ZIP_ENTRIES + 1)],
            [("large.txt", b"x" * 2048), ("image.png", valid_png())],
        )
        patches = (patch("novelai.MAX_ZIP_UNCOMPRESSED_BYTES", 1024 * 1024), patch("novelai.MAX_ZIP_UNCOMPRESSED_BYTES", 1024))
        for entries, size_patch in zip(cases, patches):
            with self.subTest(entries=len(entries)), size_patch:
                with self.assertRaises(NovelAIError):
                    generate_novelai_png(
                        SECRET_KEY,
                        self.generation_data(seed=1),
                        "artist",
                        opener=Mock(return_value=zip_response(entries)),
                    )

    def test_generation_rejects_suspicious_zip_compression_ratio(self):
        from novelai import NovelAIError, generate_novelai_png

        entries = [("bomb.txt", b"A" * 1000000), ("image.png", valid_png())]
        with self.assertRaises(NovelAIError) as raised:
            generate_novelai_png(
                SECRET_KEY,
                self.generation_data(seed=1),
                "artist",
                opener=Mock(return_value=zip_response(entries)),
            )
        self.assertEqual(raised.exception.status_code, 502)

    def test_generation_closes_and_sanitizes_http_error(self):
        from novelai import NovelAIError, generate_novelai_png

        body = io.BytesIO(f"upstream leaked {SECRET_KEY}".encode())
        error = urllib.error.HTTPError("url", 429, "rate limited", {}, body)
        with self.assertRaises(NovelAIError) as raised:
            generate_novelai_png(
                SECRET_KEY,
                self.generation_data(seed=1),
                "artist",
                opener=Mock(side_effect=error),
            )
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn(SECRET_KEY, str(raised.exception))
        self.assertTrue(body.closed)

    def test_generation_reports_sanitized_upstream_json_reason(self):
        from novelai import NovelAIError, generate_novelai_png

        body = io.BytesIO(json.dumps({"message": f"invalid sampler {SECRET_KEY}"}).encode())
        error = urllib.error.HTTPError("url", 500, "failure", {}, body)
        with self.assertRaises(NovelAIError) as raised:
            generate_novelai_png(
                SECRET_KEY,
                self.generation_data(seed=1),
                "artist",
                opener=Mock(side_effect=error),
            )
        self.assertIn("invalid sampler", raised.exception.public_message)
        self.assertRegex(raised.exception.public_message, r"요청 ID [A-Za-z0-9]{6}")
        self.assertNotIn(SECRET_KEY, raised.exception.public_message)


class GenerationApiTest(StyleApiTest):
    def setUp(self):
        super().setUp()
        with closing(app.db()) as conn, conn:
            conn.executemany(
                "INSERT INTO ratings (artist_tag, score, mode, created_at, updated_at) VALUES (?, ?, 'random', ?, ?)",
                [
                    ("artist_a", 5, app.now_text(), app.now_text()),
                    ("artist_b", 4, app.now_text(), app.now_text()),
                ],
            )

    def request_payload(self, **overrides):
        payload = {
            "request_id": "request-001",
            "artists": [
                {"artist": "artist_b", "score": 4, "weight": 1.1},
                {"artist": "artist_a", "score": 5, "weight": 1.2},
            ],
            "base_prompt": "masterpiece",
            "negative_prompt": "lowres",
            "character_prompts": [" hero ", " villain "],
            "width": 832,
            "height": 1216,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "karras",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.4,
            "seed": 123456,
        }
        payload.update(overrides)
        return payload

    def save_key(self):
        response = self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})
        self.assertEqual(response.status_code, 200)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_generation_request_passes_leading_prompt_to_novelai(self, generate):
        self.save_key()
        response = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(leading_prompt="style prefix"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.call_args.args[1]["leading_prompt"], "style prefix")

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_generation_saves_png_and_complete_metadata(self, generate):
        self.save_key()
        response = self.client.post("/api/style-maker/generate", json=self.request_payload())
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(
            set(data),
            {
                "style_id", "image_id", "image_url", "image_path", "artist_prompt", "seed",
                "width", "height", "sampler", "noise_schedule", "steps", "scale", "cfg_rescale", "model",
                "complexity", "quality_toggle", "uc_preset",
            },
        )

        self.assertEqual(data["sampler"], "k_euler_ancestral")
        self.assertEqual(data["noise_schedule"], "karras")
        self.assertEqual(data["steps"], 28)
        self.assertEqual(data["scale"], 5.0)
        self.assertEqual(data["cfg_rescale"], 0.4)
        self.assertEqual(data["complexity"], "")
        self.assertFalse(data["quality_toggle"])
        self.assertEqual(data["uc_preset"], 0)
        self.assertEqual(data["image_url"], f'/generated/{data["image_path"]}')
        self.assertTrue((app.GENERATED_DIR / data["image_path"]).is_file())
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0], SECRET_KEY)
        self.assertNotIn(SECRET_KEY, response.get_data(as_text=True))

        detail = self.client.get(f'/api/art-styles/{data["style_id"]}').get_json()
        image = detail["images"][0]
        self.assertEqual(image["base_prompt"], "masterpiece")
        self.assertEqual(image["negative_prompt"], "lowres")
        self.assertEqual(image["character_prompts"], ["hero", "villain"])
        self.assertEqual(image["combined_prompt"], f'{data["artist_prompt"]}, masterpiece')
        self.assertEqual(image["artists"], self.request_payload()["artists"])
        self.assertEqual(image["seed"], 123456)
        self.assertEqual(image["width"], 832)
        self.assertEqual(image["height"], 1216)
        self.assertEqual(image["sampler"], "k_euler_ancestral")
        self.assertEqual(image["noise_schedule"], "karras")
        self.assertEqual(image["steps"], 28)
        self.assertEqual(image["scale"], 5.0)
        self.assertEqual(image["cfg_rescale"], 0.4)
        self.assertEqual(image["model"], "nai-diffusion-4-5-full")
        self.assertEqual(image["image_url"], f'/generated/{image["image_path"]}')
        self.assertNotIn("app_key", json.dumps(detail))

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_generation_preserves_nondefault_model_settings_in_response_and_history(self, generate):
        self.save_key()
        payload = self.request_payload(
            request_id="request-settings",
            model="nai-diffusion-5-curated",
            complexity="ultra",
            quality_toggle=True,
            uc_preset=3,
        )
        response = self.client.post("/api/style-maker/generate", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["model"], "nai-diffusion-5-curated")
        self.assertEqual(data["complexity"], "ultra")
        self.assertIs(data["quality_toggle"], True)
        self.assertEqual(data["uc_preset"], 3)
        detail = self.client.get(f"/api/art-styles/{data['style_id']}").get_json()
        image = detail["images"][0]
        self.assertEqual(image["model"], "nai-diffusion-5-curated")
        self.assertEqual(image["complexity"], "ultra")
        self.assertEqual(image["quality_toggle"], 1)
        self.assertEqual(image["uc_preset"], 3)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_duplicate_request_does_not_pay_twice(self, generate):
        self.save_key()
        first = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        second = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        self.assertEqual(first, second)
        generate.assert_called_once()

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_duplicate_request_without_client_seed_does_not_pay_twice(self, generate):
        self.save_key()
        payload = self.request_payload()
        payload.pop("seed")

        first = self.client.post("/api/style-maker/generate", json=payload)
        second = self.client.post("/api/style-maker/generate", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.get_json(), first.get_json())
        generate.assert_called_once()

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_completed_request_id_rejects_different_payload(self, generate):
        self.save_key()
        first = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        )
        second = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(base_prompt="different"),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertIn("different payload", second.get_json()["error"])
        generate.assert_called_once()

    def test_processing_request_is_reserved_across_independent_clients(self):
        self.save_key()
        entered = threading.Event()
        release = threading.Event()
        responses = []

        def generate(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return valid_png(), 123456

        def post_generation():
            with app.app.test_client() as client:
                responses.append(
                    client.post(
                        "/api/style-maker/generate", json=self.request_payload()
                    )
                )

        with patch("app.generate_novelai_png", side_effect=generate) as generator:
            worker = threading.Thread(target=post_generation)
            worker.start()
            self.assertTrue(entered.wait(5))
            with app.app.test_client() as second_client:
                second = second_client.post(
                    "/api/style-maker/generate", json=self.request_payload()
                )
            release.set()
            worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(second.status_code, 409)
        self.assertIn("processing", second.get_json()["error"])
        self.assertEqual(responses[0].status_code, 200)
        generator.assert_called_once()

    @patch("app.generate_novelai_png")
    def test_failed_generation_releases_reservation_for_retry(self, generate):
        self.save_key()
        generate.side_effect = [
            app.NovelAIError(502, "NovelAI generation failed."),
            (valid_png(), 123456),
        ]

        first = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        )
        second = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        )

        self.assertEqual(first.status_code, 502)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(generate.call_count, 2)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_final_promotion_failure_cleans_database_and_allows_retry(self, generate):
        self.save_key()

        with patch("style_store.Path.replace", side_effect=OSError("replace failed")):
            failed = self.client.post(
                "/api/style-maker/generate", json=self.request_payload()
            )

        self.assertEqual(failed.status_code, 500)
        with closing(app.db()) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM generation_requests").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0
            )

        retried = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        )

        self.assertEqual(retried.status_code, 200)
        self.assertTrue((app.GENERATED_DIR / retried.get_json()["image_path"]).is_file())
        self.assertEqual(generate.call_count, 2)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_reconcile_missing_completed_image_removes_reservation_and_allows_retry(
        self, generate
    ):
        self.save_key()
        first = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(request_id="kept-image"),
        ).get_json()
        missing = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(request_id="missing-image"),
        ).get_json()
        (app.GENERATED_DIR / missing["image_path"]).unlink()

        app.init_db()

        with closing(app.db()) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM generation_requests WHERE request_id = ?",
                    ("missing-image",),
                ).fetchone()
            )
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM generated_images WHERE request_id = ?",
                    ("missing-image",),
                ).fetchone()
            )
            style = conn.execute(
                "SELECT image_count, representative_image_path FROM art_styles WHERE id = ?",
                (first["style_id"],),
            ).fetchone()
            self.assertEqual(style["image_count"], 1)
            self.assertEqual(style["representative_image_path"], first["image_path"])

        retried = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(request_id="missing-image"),
        )

        self.assertEqual(retried.status_code, 200)
        self.assertTrue((app.GENERATED_DIR / retried.get_json()["image_path"]).is_file())
        with closing(app.db()) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT image_count FROM art_styles WHERE id = ?",
                    (first["style_id"],),
                ).fetchone()[0],
                2,
            )
        self.assertEqual(generate.call_count, 3)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_generation_accepts_unrated_artists_without_scores(self, generate):
        self.save_key()
        payload = self.request_payload(
            request_id="unrated-artist",
            artists=[{"artist": "missing", "weight": 1.0}],
        )

        response = self.client.post("/api/style-maker/generate", json=payload)

        self.assertEqual(response.status_code, 200)
        detail = self.client.get(f"/api/art-styles/{response.get_json()['style_id']}").get_json()
        self.assertEqual(detail["artists"], [{"artist": "missing", "weight": 1.0}])
        generate.assert_called_once()

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_style_identity_ignores_base_prompt_but_tracks_artist_order_and_weight(self, generate):
        self.save_key()
        first = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        second = self.client.post("/api/style-maker/generate", json=self.request_payload(request_id="request-002", base_prompt="portrait")).get_json()
        reversed_artists = list(reversed(self.request_payload()["artists"]))
        third = self.client.post("/api/style-maker/generate", json=self.request_payload(request_id="request-003", artists=reversed_artists)).get_json()
        changed_weight = [dict(item) for item in self.request_payload()["artists"]]
        changed_weight[0]["weight"] = 1.05
        fourth = self.client.post("/api/style-maker/generate", json=self.request_payload(request_id="request-004", artists=changed_weight)).get_json()
        self.assertEqual(first["style_id"], second["style_id"])
        self.assertNotEqual(first["style_id"], third["style_id"])
        self.assertNotEqual(first["style_id"], fourth["style_id"])
        styles = self.client.get("/api/art-styles").get_json()
        self.assertEqual(len(styles), 3)
        grouped = next(item for item in styles if item["id"] == first["style_id"])
        self.assertEqual(grouped["image_count"], 2)
        self.assertTrue(grouped["representative_image_url"].startswith("/generated/"))

    def test_generation_requires_saved_key(self):
        response = self.client.post("/api/style-maker/generate", json=self.request_payload())
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(SECRET_KEY, response.get_data(as_text=True))

    @patch("app.generate_novelai_png")
    def test_generation_returns_sanitized_upstream_failure(self, generate):
        self.save_key()
        generate.side_effect = app.NovelAIError(502, "NovelAI generation failed.")
        response = self.client.post("/api/style-maker/generate", json=self.request_payload())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": "NovelAI generation failed."})
        self.assertNotIn(SECRET_KEY, response.get_data(as_text=True))

    @patch("app.generate_novelai_png", return_value=(valid_png(), 999))
    def test_generation_validates_request_strictly(self, generate):
        self.save_key()
        invalid = (
            {"data": "[]", "content_type": "application/json"},
            {"json": self.request_payload(request_id="")},
            {"json": self.request_payload(request_id="../bad")},
            {"json": self.request_payload(request_id="x" * 129)},
            {"json": self.request_payload(artists=[])},
            {"json": self.request_payload(base_prompt=1)},
            {"json": self.request_payload(negative_prompt=[])},
            {"json": self.request_payload(character_prompts="hero")},
            {"json": self.request_payload(character_prompts=[1])},
            {"json": self.request_payload(character_prompts=[""])},
            {"json": self.request_payload(character_prompts=["hero", "   "])},
            {"json": self.request_payload(character_prompts=["x"] * 17)},
            {"json": self.request_payload(width=0)},
            {"json": self.request_payload(width=65)},
            {"json": self.request_payload(width=2112)},
            {"json": self.request_payload(height=True)},
            {"json": self.request_payload(steps=0)},
            {"json": self.request_payload(steps=True)},
            {"json": self.request_payload(steps=51)},
            {"json": self.request_payload(scale=float("inf"))},
            {"json": self.request_payload(scale=-0.1)},
            {"json": self.request_payload(scale=True)},
            {"json": self.request_payload(cfg_rescale=float("nan"))},
            {"json": self.request_payload(cfg_rescale=1.1)},
            {"json": self.request_payload(sampler="")},
            {"json": self.request_payload(sampler="bad sampler")},
            {"json": self.request_payload(seed=True)},
            {"json": self.request_payload(seed=None)},
            {"json": self.request_payload(seed=0)},
            {"json": self.request_payload(seed=4294967296)},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                response = self.client.post("/api/style-maker/generate", **kwargs)
                self.assertEqual(response.status_code, 400)
        generate.assert_not_called()

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_generated_route_serves_only_generated_directory(self, generate):
        self.save_key()
        result = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        image_response = self.client.get(result["image_url"])
        try:
            self.assertEqual(image_response.data, valid_png())
        finally:
            image_response.close()
        secret = app.DATA_DIR / "outside.txt"
        secret.write_text("secret", encoding="utf-8")
        for path in ("../outside.txt", "%2e%2e/outside.txt", "1/../../outside.txt"):
            with self.subTest(path=path):
                response = self.client.get(f"/generated/{path}")
                self.assertIn(response.status_code, (400, 404))
                self.assertNotIn(b"secret", response.data)

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_delete_style_removes_database_records_and_files(self, generate):
        self.save_key()
        result = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        ).get_json()
        image_path = app.GENERATED_DIR / result["image_path"]
        style_dir = image_path.parent

        deleted = style_store.delete_style(
            app.DB_PATH, app.GENERATED_DIR, result["style_id"]
        )

        self.assertEqual(
            deleted, {"style_id": result["style_id"], "deleted": True}
        )
        self.assertFalse(image_path.exists())
        self.assertFalse(style_dir.exists())
        with closing(app.db()) as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM art_styles").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM generated_images").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM generation_requests").fetchone()[0], 0
            )

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_delete_style_is_bounded_and_handles_missing_data(self, generate):
        self.save_key()
        result = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        ).get_json()
        generated_path = app.GENERATED_DIR / result["image_path"]
        outside_path = app.DATA_DIR / "outside-generated.png"
        outside_path.write_bytes(valid_png())
        generated_path.unlink()
        with closing(app.db()) as conn:
            conn.execute(
                "UPDATE generated_images SET image_path = ? WHERE id = ?",
                ("../outside-generated.png", result["image_id"]),
            )
            conn.commit()

        deleted = style_store.delete_style(
            app.DB_PATH, app.GENERATED_DIR, result["style_id"]
        )

        self.assertEqual(deleted["deleted"], True)
        self.assertTrue(outside_path.is_file())
        self.assertIsNone(
            style_store.delete_style(app.DB_PATH, app.GENERATED_DIR, 999999)
        )

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_delete_art_style_api_removes_style_and_image(self, generate):
        self.save_key()
        result = self.client.post(
            "/api/style-maker/generate", json=self.request_payload()
        ).get_json()
        image_path = app.GENERATED_DIR / result["image_path"]

        response = self.client.delete(f'/api/art-styles/{result["style_id"]}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"style_id": result["style_id"], "deleted": True},
        )
        self.assertEqual(
            self.client.get(f'/api/art-styles/{result["style_id"]}').status_code,
            404,
        )
        self.assertFalse(image_path.exists())

    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_batch_delete_art_styles_removes_selected_styles(self, generate):
        self.save_key()
        first = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(request_id="batch-delete-1"),
        ).get_json()
        second = self.client.post(
            "/api/style-maker/generate",
            json=self.request_payload(
                request_id="batch-delete-2",
                artists=[{"artist": "artist_a", "score": 5, "weight": 1.7}],
            ),
        ).get_json()

        response = self.client.post(
            "/api/art-styles/delete-batch",
            json={"style_ids": [first["style_id"], second["style_id"], first["style_id"], 999999]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted_ids"], [first["style_id"], second["style_id"]])
        self.assertEqual(response.get_json()["missing_ids"], [999999])
        self.assertEqual(self.client.get("/api/art-styles").get_json(), [])

    def test_batch_delete_art_styles_rejects_invalid_ids(self):
        for payload in ({}, {"style_ids": []}, {"style_ids": [True]}, {"style_ids": [0]}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/art-styles/delete-batch", json=payload)
                self.assertEqual(response.status_code, 400)

    def test_unknown_style_returns_404(self):
        for method in (self.client.get, self.client.delete):
            with self.subTest(method=method.__name__):
                response = method("/api/art-styles/999")
                self.assertEqual(response.status_code, 404)


    @patch("app.generate_novelai_png", return_value=(valid_png(), 123456))
    def test_shared_dependency_snapshot_is_returned_for_generation_and_history(self, generate):
        self.save_key()
        dependency = {
            "id": 11,
            "item_id": 1,
            "title": "기준 공유 그림체",
            "source_url": "https://arca.live/b/aiart/11",
            "artists": [{"artist": "reference", "weight": 1.0}],
            "scale": 5.0,
            "cfg_rescale": 0.2,
        }
        payload = self.request_payload(
            request_id="shared-dependency-generation",
            weight_mode="shared_dependency",
            shared_dependency_reference_id=11,
        )
        with patch.object(app, "get_shared_style_dependency_images", return_value=[dependency]):
            first = self.client.post("/api/style-maker/generate", json=payload)
            second = self.client.post("/api/style-maker/generate", json=payload)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(first.get_json()["shared_dependency_reference_id"], 11)
        self.assertEqual(first.get_json()["shared_dependency_reference_title"], "기준 공유 그림체")
        self.assertEqual(first.get_json()["shared_dependency_reference_source_url"], dependency["source_url"])
        for key in (
            "shared_dependency_reference_id",
            "shared_dependency_reference_title",
            "shared_dependency_reference_source_url",
        ):
            self.assertEqual(second.get_json()[key], first.get_json()[key])
        history = self.client.get("/api/style-manager/generated").get_json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["shared_dependency_reference_id"], 11)
        self.assertEqual(history[0]["shared_dependency_reference_title"], "기준 공유 그림체")
        self.assertEqual(history[0]["shared_dependency_reference_source_url"], dependency["source_url"])
        generate.assert_called_once()


class NovelAISubscriptionTest(unittest.TestCase):
    def response(self, payload):
        response = Mock()
        response.read.return_value = payload
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_subscription_request_and_anlas_total(self):
        from novelai import REQUEST_TIMEOUT, USER_AGENT, test_novelai_subscription

        response = self.response(
            json.dumps(
                {
                    "trainingStepsLeft": {
                        "fixedTrainingStepsLeft": 120,
                        "purchasedTrainingSteps": 34,
                    }
                }
            ).encode("utf-8")
        )
        opener = Mock(return_value=response)
        result = test_novelai_subscription(SECRET_KEY, opener=opener)
        self.assertEqual(result, {"anlas": 154})
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://image.novelai.net/user/subscription")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(
            request.unredirected_hdrs["Authorization"], f"Bearer {SECRET_KEY}"
        )
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertEqual(opener.call_args.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_subscription_sanitizes_http_network_and_json_errors(self):
        from novelai import NovelAIError, test_novelai_subscription

        cases = (
            (urllib.error.HTTPError("url", 403, "forbidden", {}, io.BytesIO(b"body")), 403),
            (urllib.error.HTTPError("url", 500, "failure", {}, io.BytesIO(b"body")), 502),
            (urllib.error.URLError(f"network {SECRET_KEY}"), 502),
        )
        for upstream_error, status in cases:
            with self.subTest(error=type(upstream_error).__name__):
                with self.assertRaises(NovelAIError) as raised:
                    test_novelai_subscription(
                        SECRET_KEY, opener=Mock(side_effect=upstream_error)
                    )
                self.assertEqual(raised.exception.status, status)
                self.assertNotIn(SECRET_KEY, str(raised.exception))

        with self.assertRaises(NovelAIError) as raised:
            test_novelai_subscription(
                SECRET_KEY, opener=Mock(return_value=self.response(b"not-json"))
            )
        self.assertEqual(raised.exception.status, 502)

    def test_subscription_reports_windows_socket_permission_block(self):
        from novelai import NovelAIError, test_novelai_subscription

        blocked = PermissionError(13, "socket access denied", None, 10013, None)
        with self.assertRaises(NovelAIError) as raised:
            test_novelai_subscription(
                SECRET_KEY,
                opener=Mock(side_effect=urllib.error.URLError(blocked)),
            )

        self.assertIn("Windows", raised.exception.public_message)
        self.assertIn("10013", raised.exception.public_message)

    def test_cross_host_redirect_is_rejected_without_resending_key(self):
        from novelai import NovelAIError, test_novelai_subscription

        requests_seen = []

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests_seen.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{target.server_port}/stolen"
                )
                self.end_headers()

            def log_message(self, format, *args):
                pass

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (target, redirect)
        ]
        for thread in threads:
            thread.start()
        try:
            with patch(
                "novelai.SUBSCRIPTION_URL",
                f"http://127.0.0.1:{redirect.server_port}/subscription",
            ):
                with self.assertRaises(NovelAIError) as raised:
                    test_novelai_subscription(SECRET_KEY)
            self.assertEqual(raised.exception.status, 502)
            self.assertEqual(requests_seen, [])
        finally:
            redirect.shutdown()
            target.shutdown()
            redirect.server_close()
            target.server_close()

    def test_subscription_rejects_oversized_response(self):
        from novelai import MAX_SUBSCRIPTION_BYTES, NovelAIError, test_novelai_subscription

        response = self.response(b"x" * (MAX_SUBSCRIPTION_BYTES + 1))
        with self.assertRaises(NovelAIError) as raised:
            test_novelai_subscription(SECRET_KEY, opener=Mock(return_value=response))
        self.assertEqual(raised.exception.status, 502)
        response.read.assert_called_once_with(MAX_SUBSCRIPTION_BYTES + 1)

    def test_subscription_closes_http_error(self):
        from novelai import NovelAIError, test_novelai_subscription

        body = io.BytesIO(b"failure")
        error = urllib.error.HTTPError("url", 500, "failure", {}, body)
        with self.assertRaises(NovelAIError):
            test_novelai_subscription(SECRET_KEY, opener=Mock(side_effect=error))
        self.assertTrue(body.closed)

    def test_subscription_requires_exact_nonnegative_integer_counts(self):
        from novelai import NovelAIError, test_novelai_subscription

        invalid_steps = (
            None,
            [],
            {},
            {"fixedTrainingStepsLeft": 1},
            {"fixedTrainingStepsLeft": True, "purchasedTrainingSteps": 0},
            {"fixedTrainingStepsLeft": 1.0, "purchasedTrainingSteps": 0},
            {"fixedTrainingStepsLeft": "1", "purchasedTrainingSteps": 0},
            {"fixedTrainingStepsLeft": -1, "purchasedTrainingSteps": 0},
        )
        for steps in invalid_steps:
            with self.subTest(steps=steps):
                response = self.response(
                    json.dumps({"trainingStepsLeft": steps}).encode("utf-8")
                )
                with self.assertRaises(NovelAIError) as raised:
                    test_novelai_subscription(
                        SECRET_KEY, opener=Mock(return_value=response)
                    )
                self.assertEqual(raised.exception.status, 502)
                self.assertNotIn(SECRET_KEY, str(raised.exception))

class ConfirmedStyleApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp_dir.name)
        self.originals = (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
            app.CONFIRMED_STYLE_IMAGE_DIR,
            app.COMPARISON_IMAGE_DIR,
            app.ARCA_STYLE_IMAGE_DIR,
            app.ARCA_STYLE_SEED_PATH,
        )
        app.DATA_DIR = self.tmp
        app.THUMBNAIL_DIR = self.tmp / "thumbnails"
        app.GENERATED_DIR = self.tmp / "generated"
        app.SETTINGS_JSON_PATH = self.tmp / "settings.json"
        app.DB_PATH = self.tmp / "artist_rater.sqlite"
        app.CONFIRMED_STYLE_IMAGE_DIR = self.tmp / "confirmed_style_images"
        app.COMPARISON_IMAGE_DIR = self.tmp / "comparison_images"
        app.ARCA_STYLE_IMAGE_DIR = self.tmp / "arca_style_images"
        app.ARCA_STYLE_SEED_PATH = self.tmp / "missing-seed.sqlite"
        app.init_db()
        self.client = app.app.test_client()

    def tearDown(self):
        (
            app.DATA_DIR,
            app.THUMBNAIL_DIR,
            app.GENERATED_DIR,
            app.SETTINGS_JSON_PATH,
            app.DB_PATH,
            app.CONFIRMED_STYLE_IMAGE_DIR,
            app.COMPARISON_IMAGE_DIR,
            app.ARCA_STYLE_IMAGE_DIR,
            app.ARCA_STYLE_SEED_PATH,
        ) = self.originals
        self.temp_dir.cleanup()

    def test_style_manager_thumbnail_is_resized_and_cached(self):
        from PIL import Image

        app.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        source = app.GENERATED_DIR / "large.png"
        source.write_bytes(valid_png(900, 600))

        first = self.client.get("/style-manager-thumbnails/generated/large.png")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.mimetype, "image/webp")
        with Image.open(io.BytesIO(first.data)) as thumbnail:
            self.assertLessEqual(thumbnail.width, 384)
            self.assertLessEqual(thumbnail.height, 384)

        second = self.client.get("/style-manager-thumbnails/generated/large.png")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data, first.data)
        cache_files = list((app.DATA_DIR / "style_manager_thumbnails").glob("*.webp"))
        self.assertEqual(len(cache_files), 1)
        first.close()
        second.close()

    @patch("app.generate_novelai_png")
    def test_comparison_deferred_generation_reports_each_result_and_replaces_it(self, generate):
        style = app.create_confirmed_style(
            app.DB_PATH,
            app.CONFIRMED_STYLE_IMAGE_DIR,
            valid_png(64, 64),
            {
                "name": "비교 스타일",
                "artist_prompt": "1.5::artist:matrix16::",
                "quality_prompt": "best quality",
                "negative_prompt": "lowres",
                "sampler": "k_euler_ancestral",
                "noise_schedule": "karras",
                "steps": 28,
                "scale": 5.0,
                "cfg_rescale": 0.2,
                "model": "nai-diffusion-4-5-full",
            },
        )
        self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})
        prepared = self.client.post("/api/comparisons", json={
            "name": "진행 비교군",
            "style_ids": [style["id"]],
            "fixed_prompt": "white sheet",
            "character_prompts": ["1girl"],
            "width": 64,
            "height": 64,
            "seed_mode": "none",
            "defaults": {},
            "defer_generation": True,
        })
        self.assertEqual(prepared.status_code, 201)
        prepared_data = prepared.get_json()
        self.assertEqual(prepared_data["pending_style_ids"], [style["id"]])
        self.assertEqual(prepared_data["generated_count"], 0)
        self.assertEqual(prepared_data["total_count"], 1)

        generate.side_effect = [(valid_png(64, 64), 101), (valid_png(64, 64), 202)]
        endpoint = f"/api/comparisons/{prepared_data['id']}/styles/{style['id']}/generate"
        first = self.client.post(endpoint, json={})
        second = self.client.post(endpoint, json={})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        groups = self.client.get("/api/comparisons").get_json()
        self.assertEqual(groups[0]["selected_style_ids"], [style["id"]])
        self.assertEqual(len(groups[0]["results"]), 1)
        self.assertEqual(groups[0]["results"][0]["settings"]["seed"], 202)
        self.assertEqual(groups[0]["results"][0]["settings"]["artist_prompt"], "1.5::artist:matrix16 ::")
        self.assertEqual(len(list(app.COMPARISON_IMAGE_DIR.iterdir())), 1)

    @staticmethod
    def metadata_png(source="NovelAI Diffusion V4.5"):
        from PIL import Image, PngImagePlugin

        output = io.BytesIO()
        png_info = PngImagePlugin.PngInfo()
        png_info.add_text("Software", "NovelAI")
        png_info.add_text("Source", source)
        prompt = "1.2::artist:test artist::, very aesthetic"
        png_info.add_text("Comment", json.dumps({
            "prompt": prompt,
            "uc": "lowres",
            "v4_prompt": {"caption": {"base_caption": prompt, "char_captions": [
                {"char_caption": "1girl, blue hair", "centers": [{"x": 0.5, "y": 0.5}]},
            ]}},
            "sampler": "k_euler_ancestral",
            "noise_schedule": "karras",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.2,
            "seed": 123,
            "width": 32,
            "height": 48,
            "skip_cfg_above_sigma": 59.04722600415217,
        }))
        Image.new("RGB", (32, 48), "white").save(output, format="PNG", pnginfo=png_info)
        return output.getvalue()

    @staticmethod
    def metadata_webp():
        from PIL import Image

        output = io.BytesIO()
        prompt = "1.2::artist:webp artist::, very aesthetic"
        exif = Image.Exif()
        exif[37510] = b"UNICODE\x00" + json.dumps({
            "prompt": prompt,
            "uc": "lowres",
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "source": "NovelAI Diffusion V4.5 Full",
        }).encode("utf-16-be")
        Image.new("RGB", (32, 48), "white").save(output, format="WEBP", lossless=True, exif=exif)
        return output.getvalue()

    def test_confirmed_extract_preserves_ambiguous_v45_build_label(self):
        extracted = self.client.post(
            "/api/confirmed-styles/extract",
            data={"image": (io.BytesIO(self.metadata_png("NovelAI Diffusion V4.5 4BDE2A90")), "style.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(extracted.status_code, 200)
        self.assertEqual(extracted.get_json()["model"], "NovelAI Diffusion V4.5 4BDE2A90")

    def test_confirmed_extract_reads_webp_exif_user_comment(self):
        extracted = self.client.post(
            "/api/confirmed-styles/extract",
            data={"image": (io.BytesIO(self.metadata_webp()), "style.webp")},
            content_type="multipart/form-data",
        )

        self.assertEqual(extracted.status_code, 200)
        metadata = extracted.get_json()
        self.assertEqual(metadata["metadata_status"], "ok")
        self.assertIn("artist:webp artist", metadata["artist_prompt"])
        self.assertEqual(metadata["negative_prompt"], "lowres")
        self.assertEqual(metadata["model"], "NovelAI Diffusion V4.5 Full")

    def test_manual_image_extract_create_update_and_delete(self):
        image_bytes = self.metadata_png()
        extracted = self.client.post(
            "/api/confirmed-styles/extract",
            data={"image": (io.BytesIO(image_bytes), "style.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(extracted.status_code, 200)
        metadata = extracted.get_json()
        self.assertEqual(metadata["metadata_status"], "ok")
        self.assertIn("artist:test artist", metadata["artist_prompt"])
        self.assertEqual(metadata["character_prompts"], ["1girl, blue hair"])
        self.assertTrue(metadata["variety_plus"])
        self.assertEqual(metadata["model"], "NovelAI Diffusion V4.5")

        created = self.client.post(
            "/api/confirmed-styles",
            data={
                "image": (io.BytesIO(image_bytes), "style.png"),
                "data": json.dumps({"name": "직접 그림체", "description": "메모"}, ensure_ascii=False),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(created.status_code, 201)
        item = created.get_json()
        self.assertEqual(item["name"], "직접 그림체")
        self.assertEqual(item["image_count"], 1)
        self.assertEqual(item["character_prompts"], ["1girl, blue hair"])
        self.assertEqual(len(item["images"]), 1)
        self.assertTrue((app.CONFIRMED_STYLE_IMAGE_DIR / item["image_path"]).is_file())

        updated = self.client.patch(f"/api/confirmed-styles/{item['id']}", json={"description": "수정한 설명"})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["description"], "수정한 설명")
        self.assertEqual(self.client.delete(f"/api/confirmed-styles/{item['id']}").status_code, 200)
        self.assertFalse((app.CONFIRMED_STYLE_IMAGE_DIR / item["image_path"]).exists())

    def test_manual_batch_import_saves_and_deletes_images_as_one_style_group(self):
        first = self.metadata_png()
        second = self.metadata_png()
        response = self.client.post(
            "/api/confirmed-styles/import-batch",
            data={
                "images": [
                    (io.BytesIO(first), "first.png"),
                    (io.BytesIO(second), "second.png"),
                ],
                "manifest": json.dumps([
                    {
                        "file_indexes": [0, 1],
                        "data": {
                            "name": "묶음 그림체",
                            "artist_prompt": "1.2::artist:test artist::",
                        },
                    }
                ], ensure_ascii=False),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201)
        styles = response.get_json()
        self.assertEqual(len(styles), 1)
        self.assertEqual(styles[0]["image_count"], 2)
        self.assertEqual(len(styles[0]["images"]), 2)
        paths = [image["image_path"] for image in styles[0]["images"]]
        self.assertTrue(all((app.CONFIRMED_STYLE_IMAGE_DIR / path).is_file() for path in paths))

        deleted = self.client.delete(f"/api/confirmed-styles/{styles[0]['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(all(not (app.CONFIRMED_STYLE_IMAGE_DIR / path).exists() for path in paths))

    def test_generated_results_are_individual_cards_and_copy_to_confirmed(self):
        common = {
            "db_path": app.DB_PATH,
            "generated_dir": app.GENERATED_DIR,
            "artists": [{"artist": "same_artist", "weight": 1.0}],
            "png_bytes": valid_png(64, 64),
            "base_prompt": "very aesthetic, white sheet",
            "quality_prompt": "very aesthetic",
            "original_quality_prompt": "very aesthetic, masterpiece",
            "excluded_quality_tags": ["masterpiece"],
            "fixed_prompt": "white sheet",
            "negative_prompt": "lowres",
            "character_prompts": [],
            "combined_prompt": "artist:same artist, very aesthetic, white sheet",
            "seed": 123,
            "width": 64,
            "height": 64,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "karras",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.2,
            "variety_plus": True,
            "skip_cfg_above_sigma": 59.04722600415217,
            "model": "nai-diffusion-4-5-full",
        }
        first = style_store.save_generated_result(request_id="individual-1", **common)
        style_store.save_generated_result(request_id="individual-2", **common)
        generated = self.client.get("/api/style-manager/generated").get_json()
        self.assertEqual(len(generated), 2)
        self.assertEqual({item["style_id"] for item in generated}, {first["style_id"]})
        self.assertTrue(all(item["image_url"].startswith("/generated/") for item in generated))
        self.assertTrue(all(item["thumbnail_url"].startswith("/style-manager-thumbnails/generated/") for item in generated))
        self.assertTrue(all(item["sampler"] == "k_euler_ancestral" for item in generated))
        self.assertTrue(all(item["noise_schedule"] == "karras" for item in generated))
        self.assertTrue(all(item["steps"] == 28 for item in generated))

        confirmed = self.client.post(
            "/api/confirmed-styles",
            json={"source_type": "generated", "source_id": first["image_id"], "name": "확정본"},
        )
        self.assertEqual(confirmed.status_code, 201)
        confirmed_item = confirmed.get_json()
        self.assertEqual(confirmed_item["excluded_quality_tags"], ["masterpiece"])
        self.assertEqual(confirmed_item["sampler"], "k_euler_ancestral")
        self.assertEqual(confirmed_item["noise_schedule"], "karras")
        self.assertEqual(confirmed_item["steps"], 28)
        self.assertEqual(confirmed_item["scale"], 5.0)
        self.assertEqual(confirmed_item["cfg_rescale"], 0.2)
        self.assertTrue(confirmed_item["image_url"].startswith("/confirmed-style-images/"))
        self.assertTrue(confirmed_item["thumbnail_url"].startswith("/style-manager-thumbnails/confirmed/"))
        self.assertEqual(len(self.client.get("/api/style-manager/generated").get_json()), 2)

    def test_style_manager_generated_and_all_history_sources(self):
        original_comparison_dir = app.COMPARISON_IMAGE_DIR
        app.COMPARISON_IMAGE_DIR = self.tmp / "comparison_images"
        try:
            common = {
                "db_path": app.DB_PATH,
                "generated_dir": app.GENERATED_DIR,
                "artists": [{"artist": "history_artist", "weight": 1.0}],
                "png_bytes": valid_png(64, 64),
                "base_prompt": "very aesthetic, history fixture",
                "quality_prompt": "very aesthetic",
                "original_quality_prompt": "very aesthetic, masterpiece",
                "excluded_quality_tags": [],
                "fixed_prompt": "history fixture",
                "negative_prompt": "lowres",
                "character_prompts": [],
                "combined_prompt": "artist:history artist, very aesthetic, history fixture",
                "seed": 101,
                "width": 64,
                "height": 64,
                "sampler": "k_euler_ancestral",
                "noise_schedule": "karras",
                "steps": 28,
                "scale": 5.0,
                "cfg_rescale": 0.2,
                "variety_plus": True,
                "skip_cfg_above_sigma": 59.04722600415217,
                "model": "nai-diffusion-4-5-full",
            }
            style_maker_image = style_store.save_generated_result(
                request_id="history-style-maker", **common
            )
            nai_test_image = style_store.save_generated_result(
                request_id="history-nai-test", **common
            )
            nai_test = create_test(
                app.DB_PATH,
                "회귀 NAI 테스트",
                {
                    "base_prompt": "{{artist}}, history fixture",
                    "prompt_variants": [
                        {"prompt": "{{artist}}, history fixture", "images_per_artist": 1}
                    ],
                    "model": "nai-diffusion-4-5-full",
                    "width": 64,
                    "height": 64,
                },
                [{"artist_tag": "history_artist"}],
                1,
                0,
            )
            complete_item(
                app.DB_PATH,
                nai_test["id"],
                nai_test["items"][0]["id"],
                nai_test_image["image_id"],
            )

            comparison_group_id = app.create_group(
                app.DB_PATH,
                {
                    "name": "회귀 비교군",
                    "fixed_prompt": "그룹 고정 프롬프트",
                    "character_prompts": ["comparison character"],
                    "width": 64,
                    "height": 64,
                    "seed_mode": "none",
                    "style_ids": [style_maker_image["style_id"]],
                    "defaults": {"model": "nai-diffusion-4-5-full"},
                },
            )
            app.save_result(
                app.DB_PATH,
                app.COMPARISON_IMAGE_DIR,
                comparison_group_id,
                style_maker_image["style_id"],
                "회귀 비교 스타일",
                valid_png(64, 64),
                {"seed": 202, "steps": 24},
            )
            with closing(app.db()) as connection:
                comparison_result_id = connection.execute(
                    "SELECT id FROM comparison_results WHERE group_id=?",
                    (comparison_group_id,),
                ).fetchone()[0]

            generated_response = self.client.get("/api/style-manager/generated")
            self.assertEqual(generated_response.status_code, 200)
            generated = generated_response.get_json()
            self.assertEqual([item["id"] for item in generated], [style_maker_image["image_id"]])

            all_response = self.client.get("/api/style-manager/all-generated")
            self.assertEqual(all_response.status_code, 200)
            records = all_response.get_json()
            self.assertEqual(len(records), 3)
            by_key = {item["record_key"]: item for item in records}
            self.assertEqual(
                set(by_key),
                {
                    f"generated:{style_maker_image['image_id']}",
                    f"generated:{nai_test_image['image_id']}",
                    f"comparison:{comparison_result_id}",
                },
            )
            self.assertEqual(
                {item["source_type"] for item in records},
                {"style_maker", "nai_artist_test", "comparison"},
            )
            style_record = by_key[f"generated:{style_maker_image['image_id']}"]
            nai_record = by_key[f"generated:{nai_test_image['image_id']}"]
            comparison_record = by_key[f"comparison:{comparison_result_id}"]
            self.assertEqual(
                [item["record_key"] for item in records],
                sorted(
                    by_key,
                    key=lambda key: (by_key[key]["created_at"], key),
                    reverse=True,
                ),
            )
            self.assertEqual(style_record["source_label"], "그림체 제작")
            self.assertEqual(nai_record["source_label"], "NAI 작가 테스트")
            self.assertIn("회귀 NAI 테스트", nai_record["source_name"])
            self.assertEqual(comparison_record["source_label"], "비교군 관리")
            self.assertIn("회귀 비교군", comparison_record["source_name"])
            self.assertTrue(style_record["image_url"].startswith("/generated/"))
            self.assertTrue(nai_record["image_url"].startswith("/generated/"))
            self.assertTrue(comparison_record["image_url"].startswith("/comparison-images/"))
            self.assertTrue(
                comparison_record["thumbnail_url"].startswith(
                    "/style-manager-thumbnails/comparison/"
                )
            )
            self.assertEqual(comparison_record["model"], "nai-diffusion-4-5-full")
            self.assertEqual(comparison_record["character_prompts"], ["comparison character"])
        finally:
            app.COMPARISON_IMAGE_DIR = original_comparison_dir

    def test_shared_gallery_flattens_images_from_the_same_post(self):
        app.ARCA_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (app.ARCA_STYLE_IMAGE_DIR / "one.png").write_bytes(valid_png(64, 64))
        (app.ARCA_STYLE_IMAGE_DIR / "two.png").write_bytes(valid_png(64, 64))
        with closing(app.db()) as connection, connection:
            item_id = connection.execute(
                "INSERT INTO arca_style_items(source_url,title,collected_at,updated_at) VALUES(?,?,?,?)",
                ("https://arca.live/b/aiart/1", "공유글", app.now_text(), app.now_text()),
            ).lastrowid
            connection.executemany(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                [
                    (item_id, "https://image/one", "one.png", "artist:first", "artist:first", app.now_text()),
                    (item_id, "https://image/two", "two.png", "artist:second", "artist:second", app.now_text()),
                    (item_id, "https://image/missing", "missing.png", "artist:missing", "artist:missing", app.now_text()),
                    (item_id, "https://image/remote-only", "", "artist:remote", "artist:remote", app.now_text()),
                ],
            )
        response = self.client.get("/api/style-manager/shared?offset=0&limit=60")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 2)
        self.assertTrue(all(item["title"] == "공유글" for item in data["items"]))
        self.assertEqual({item["image_path"] for item in data["items"]}, {"one.png", "two.png"})
        self.assertTrue(all(item["thumbnail_url"].startswith("/style-manager-thumbnails/shared/") for item in data["items"]))
        page_one = self.client.get("/api/style-manager/shared?offset=0&limit=1").get_json()
        page_two = self.client.get("/api/style-manager/shared?offset=1&limit=1").get_json()
        self.assertEqual(len(page_one["items"]), 1)
        self.assertEqual(len(page_two["items"]), 1)
        self.assertTrue(page_one["has_more"])
        self.assertFalse(page_two["has_more"])

    def test_shared_style_confirmation_recovers_model_from_local_png_metadata(self):
        app.ARCA_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (app.ARCA_STYLE_IMAGE_DIR / "metadata.png").write_bytes(self.metadata_png())
        with closing(app.db()) as connection, connection:
            item_id = connection.execute(
                "INSERT INTO arca_style_items(source_url,title,collected_at,updated_at) VALUES(?,?,?,?)",
                ("https://arca.live/b/aiart/metadata", "메타데이터 공유", app.now_text(), app.now_text()),
            ).lastrowid
            image_id = connection.execute(
                """
                INSERT INTO arca_style_images(
                    item_id,image_url,image_path,content_type,prompt,base_prompt,model,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    item_id,
                    "https://image/metadata",
                    "metadata.png",
                    "image/png",
                    "artist:test artist",
                    "artist:test artist",
                    "",
                    app.now_text(),
                ),
            ).lastrowid

        gallery_item = self.client.get("/api/style-manager/shared").get_json()["items"][0]
        self.assertEqual(gallery_item["model"], "NovelAI Diffusion V4.5")

        confirmed = self.client.post(
            "/api/confirmed-styles",
            json={"source_type": "shared", "source_id": image_id, "model": ""},
        )
        self.assertEqual(confirmed.status_code, 201)
        self.assertEqual(confirmed.get_json()["model"], "NovelAI Diffusion V4.5")

    def test_shared_gallery_searches_and_filters_all_available_images(self):
        app.ARCA_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("alpha.png", "beta.png"):
            (app.ARCA_STYLE_IMAGE_DIR / name).write_bytes(valid_png(64, 64))
        with closing(app.db()) as connection, connection:
            first_item = connection.execute(
                "INSERT INTO arca_style_items(source_url,title,board_tab,posted_at,recommendation_count,collected_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/10", "알파 그림체", "NAI", "2026-01-01", 5, app.now_text(), app.now_text()),
            ).lastrowid
            second_item = connection.execute(
                "INSERT INTO arca_style_items(source_url,title,board_tab,posted_at,recommendation_count,collected_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/20", "베타 그림체", "R18_NAI", "2026-02-01", 50, app.now_text(), app.now_text()),
            ).lastrowid
            connection.executemany(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                [
                    (first_item, "https://image/alpha", "alpha.png", "ok", "artist:alpha", "artist:alpha", app.now_text()),
                    (second_item, "https://image/beta", "beta.png", "no_metadata", "artist:beta", "artist:beta", app.now_text()),
                ],
            )

        searched = self.client.get("/api/style-manager/shared?q=beta").get_json()
        self.assertEqual([item["image_path"] for item in searched["items"]], ["beta.png"])
        filtered = self.client.get(
            "/api/style-manager/shared?tab=R18_NAI&metadata=no_metadata&recommendation_min=10"
        ).get_json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["image_path"], "beta.png")
        ordered = self.client.get("/api/style-manager/shared?sort=posted_asc").get_json()
        self.assertEqual([item["image_path"] for item in ordered["items"]], ["alpha.png", "beta.png"])

    def test_shared_gallery_v5_filter_keeps_canonical_and_source_build_images(self):
        app.ARCA_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        for name in ("v5-full.png", "v5-curated.png", "v5-build.png", "v45-full.png"):
            (app.ARCA_STYLE_IMAGE_DIR / name).write_bytes(valid_png(64, 64))
        with closing(app.db()) as connection, connection:
            item_id = connection.execute(
                "INSERT INTO arca_style_items(source_url,title,board_tab,collected_at,updated_at) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/v5-models", "V5 그림체 공유", "NAI", app.now_text(), app.now_text()),
            ).lastrowid
            connection.executemany(
                """
                INSERT INTO arca_style_images(
                    item_id,image_url,image_path,metadata_status,prompt,base_prompt,model,
                    model_id,model_family,model_generation,model_variant,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (item_id, "https://image/v5-full", "v5-full.png", "ok", "artist:full", "artist:full", "nai-diffusion-5-full", "nai-diffusion-5-full", "v5", "v5", "full", app.now_text()),
                    (item_id, "https://image/v5-curated", "v5-curated.png", "ok", "artist:curated", "artist:curated", "nai-diffusion-5-curated", "nai-diffusion-5-curated", "v5", "v5", "curated", app.now_text()),
                    (item_id, "https://image/v5-build", "v5-build.png", "ok", "artist:build", "artist:build", "NovelAI Diffusion V5 4BDE2A90", "", "v5", "v5", "unknown", app.now_text()),
                    (item_id, "https://image/v45-full", "v45-full.png", "ok", "artist:v45", "artist:v45", "nai-diffusion-4-5-full", "nai-diffusion-4-5-full", "v4.5", "v4.5", "full", app.now_text()),
                ],
            )

        v5 = self.client.get("/api/style-manager/shared?model=v5").get_json()
        self.assertEqual({item["image_path"] for item in v5["items"]}, {"v5-full.png", "v5-curated.png", "v5-build.png"})
        self.assertEqual(
            {item["model_family"] for item in v5["items"]},
            {"v5"},
        )
        full = self.client.get("/api/style-manager/shared?model=nai-diffusion-5-full").get_json()
        self.assertEqual([item["image_path"] for item in full["items"]], ["v5-full.png"])


class VarietyPlusRequestTest(unittest.TestCase):
    def test_variety_plus_adds_current_v45_skip_cfg_value(self):
        from novelai import VARIETY_PLUS_SKIP_CFG, build_generation_payload

        data = {
            "base_prompt": "test",
            "negative_prompt": "",
            "character_prompts": [],
            "width": 832,
            "height": 1216,
            "sampler": "k_euler_ancestral",
            "noise_schedule": "karras",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.0,
            "seed": 1,
            "variety_plus": True,
        }
        payload = build_generation_payload(data, "artist:test")
        self.assertEqual(payload["parameters"]["skip_cfg_above_sigma"], VARIETY_PLUS_SKIP_CFG)


if __name__ == "__main__":
    unittest.main()
