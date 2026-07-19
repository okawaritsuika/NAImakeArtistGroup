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
        self.assertEqual(combine_base_prompt("base", ""), "base")
        self.assertEqual(combine_base_prompt("", "artist"), "artist")
        self.assertEqual(combine_base_prompt("", ""), "")

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
                    "add_original_image": True,
                    "prefer_brownian": True,
                    "use_coords": False,
                    "v4_negative_prompt": {
                        "caption": {"base_caption": "lowres", "char_captions": []},
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
            },
        )

        self.assertEqual(data["sampler"], "k_euler_ancestral")
        self.assertEqual(data["noise_schedule"], "karras")
        self.assertEqual(data["steps"], 28)
        self.assertEqual(data["scale"], 5.0)
        self.assertEqual(data["cfg_rescale"], 0.4)
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


if __name__ == "__main__":
    unittest.main()
