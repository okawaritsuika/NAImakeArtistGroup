import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import app
import style_store


SECRET_KEY = "secret-key-value"


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
        self.assertEqual(request.full_url, "https://api.novelai.net/user/subscription")
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
