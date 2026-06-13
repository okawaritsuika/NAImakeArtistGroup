import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import app
import style_store


SECRET_KEY = "secret-key-value"


class SettingsStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "nested" / "settings.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_missing_or_invalid_settings_returns_empty_string(self):
        self.assertEqual(style_store.load_app_key(self.settings_path), "")
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text("not-json", encoding="utf-8")
        self.assertEqual(style_store.load_app_key(self.settings_path), "")
        self.settings_path.write_text("[]", encoding="utf-8")
        self.assertEqual(style_store.load_app_key(self.settings_path), "")

    def test_save_preserves_unrelated_settings_and_exact_key(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": "old"}),
            encoding="utf-8",
        )

        style_store.save_app_key(self.settings_path, SECRET_KEY)

        self.assertEqual(style_store.load_app_key(self.settings_path), SECRET_KEY)
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {"theme": "dark", "novelai_app_key": SECRET_KEY},
        )
        self.assertEqual(list(self.settings_path.parent.glob("*.tmp")), [])

    def test_save_rejects_non_string_and_empty_values(self):
        for value in (None, "", 1, True, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                style_store.save_app_key(self.settings_path, value)
        self.assertFalse(self.settings_path.exists())

    def test_delete_preserves_other_settings_or_removes_empty_file(self):
        self.settings_path.parent.mkdir(parents=True)
        self.settings_path.write_text(
            json.dumps({"theme": "dark", "novelai_app_key": SECRET_KEY}),
            encoding="utf-8",
        )
        style_store.delete_app_key(self.settings_path)
        self.assertEqual(
            json.loads(self.settings_path.read_text(encoding="utf-8")),
            {"theme": "dark"},
        )

        self.settings_path.write_text(
            json.dumps({"novelai_app_key": SECRET_KEY}), encoding="utf-8"
        )
        style_store.delete_app_key(self.settings_path)
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

    def test_put_rejects_malformed_or_invalid_json_without_writing(self):
        invalid_requests = (
            {"data": "not-json", "content_type": "application/json"},
            {"json": []},
            {"json": {}},
            {"json": {"app_key": ""}},
            {"json": {"app_key": 123}},
            {"json": {"app_key": True}},
        )
        for kwargs in invalid_requests:
            with self.subTest(kwargs=kwargs):
                response = self.client.put("/api/settings/novelai", **kwargs)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(app.SETTINGS_JSON_PATH.exists())
                self.assert_secret_absent(response)

    @patch(
        "app.test_novelai_subscription",
        return_value={"anlas": 1234},
        create=True,
    )
    def test_connection_uses_server_saved_key_without_returning_it(self, test_subscription):
        self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})

        response = self.client.post("/api/settings/novelai/test")

        self.assertEqual(
            response.get_json(),
            {"ok": True, "configured": True, "anlas": 1234},
        )
        test_subscription.assert_called_once_with(SECRET_KEY)
        self.assert_secret_absent(response)

    def test_connection_without_saved_key_is_rejected(self):
        response = self.client.post("/api/settings/novelai/test")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["configured"], False)
        self.assertEqual(response.get_json()["ok"], False)

    @patch("app.test_novelai_subscription", create=True)
    def test_connection_returns_sanitized_auth_error(self, test_subscription):
        error_type = getattr(app, "NovelAIError", RuntimeError)
        test_subscription.side_effect = error_type(
            401, "NovelAI App Key 인증에 실패했습니다."
        )
        self.client.put("/api/settings/novelai", json={"app_key": SECRET_KEY})

        response = self.client.post("/api/settings/novelai/test")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["configured"], True)
        self.assertEqual(
            response.get_json()["error"], "NovelAI App Key 인증에 실패했습니다."
        )
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
    def test_subscription_request_and_anlas_total(self):
        from novelai import REQUEST_TIMEOUT, USER_AGENT, test_novelai_subscription

        response = Mock()
        response.read.return_value = json.dumps(
            {
                "trainingStepsLeft": {
                    "fixedTrainingStepsLeft": 120,
                    "purchasedTrainingSteps": 34,
                }
            }
        ).encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock(return_value=response)

        result = test_novelai_subscription(SECRET_KEY, opener=opener)

        self.assertEqual(result, {"anlas": 154})
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.novelai.net/user/subscription")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {SECRET_KEY}")
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertEqual(opener.call_args.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_subscription_sanitizes_auth_http_network_and_json_errors(self):
        from novelai import NovelAIError, test_novelai_subscription

        cases = (
            (
                urllib.error.HTTPError(
                    "https://api.novelai.net/user/subscription",
                    403,
                    "forbidden",
                    {},
                    io.BytesIO(f"body {SECRET_KEY}".encode()),
                ),
                403,
                "NovelAI App Key 인증에 실패했습니다.",
            ),
            (
                urllib.error.HTTPError(
                    "https://api.novelai.net/user/subscription",
                    500,
                    f"upstream {SECRET_KEY}",
                    {},
                    io.BytesIO(f"body {SECRET_KEY}".encode()),
                ),
                502,
                "NovelAI 요청에 실패했습니다. (HTTP 500)",
            ),
            (
                urllib.error.URLError(f"network {SECRET_KEY}"),
                502,
                "NovelAI 서버에 연결할 수 없습니다.",
            ),
        )
        for upstream_error, status, message in cases:
            with self.subTest(error=type(upstream_error).__name__):
                with self.assertRaises(NovelAIError) as raised:
                    test_novelai_subscription(
                        SECRET_KEY, opener=Mock(side_effect=upstream_error)
                    )
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(raised.exception.public_message, message)
                self.assertNotIn(SECRET_KEY, str(raised.exception))

        malformed = Mock()
        malformed.read.return_value = b"not-json"
        malformed.__enter__ = Mock(return_value=malformed)
        malformed.__exit__ = Mock(return_value=False)
        with self.assertRaises(NovelAIError) as raised:
            test_novelai_subscription(SECRET_KEY, opener=Mock(return_value=malformed))
        self.assertEqual(raised.exception.status, 502)
        self.assertEqual(
            raised.exception.public_message, "NovelAI 응답을 해석할 수 없습니다."
        )


if __name__ == "__main__":
    unittest.main()
