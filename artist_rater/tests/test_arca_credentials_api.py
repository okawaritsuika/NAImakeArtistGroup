import unittest
import threading
from unittest.mock import patch

import app


class ArcaCredentialsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.headers = {"X-Arca-Local-Request": "1"}
        store_patch = patch("app.ARCA_CREDENTIALS")
        manager_patch = patch("app.ARCA_LOGIN_MANAGER")
        self.store = store_patch.start()
        self.manager = manager_patch.start()
        self.addCleanup(store_patch.stop)
        self.addCleanup(manager_patch.stop)
        self.manager.status.return_value = {"state": "idle"}
        self.store.status.return_value = {"saved": True, "username": "test-user"}

    def test_save_and_status_never_return_password_and_disable_caching(self):
        response = self.client.post("/api/arca-styles/credentials", headers=self.headers,
                                    json={"username": "test-user", "password": "test-password"})
        self.assertEqual(response.status_code, 200)
        self.store.save.assert_called_once_with("test-user", "test-password")
        for result in (response, self.client.get("/api/arca-styles/credentials", headers=self.headers)):
            self.assertEqual(result.get_json(), {"saved": True, "username": "test-user"})
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertNotIn("test-password", result.get_data(as_text=True))

    def test_sensitive_routes_reject_cross_site_nonlocal_and_rebound_hosts(self):
        routes = [("GET", "/api/arca-styles/credentials"), ("POST", "/api/arca-styles/credentials"),
                  ("DELETE", "/api/arca-styles/credentials"), ("POST", "/api/arca-styles/browser-session/import")]
        bad_requests = [
            {}, {"headers": {**self.headers, "Origin": "https://example.com"}},
            {"headers": {**self.headers, "Origin": "http://localhost:9000"}},
            {"headers": self.headers, "base_url": "http://attacker.example"},
            {"headers": self.headers, "environ_overrides": {"REMOTE_ADDR": "192.168.1.5"}},
        ]
        for method, route in routes:
            for options in bad_requests:
                with self.subTest(method=method, options=options):
                    self.assertEqual(self.client.open(route, method=method, **options).status_code, 403)
        self.store.save.assert_not_called()
        self.store.load.assert_not_called()
        self.manager.start.assert_not_called()

    def test_delete_can_remove_an_unreadable_store_without_loading_it(self):
        self.store.status.return_value = {"saved": False, "username": ""}
        result = self.client.delete("/api/arca-styles/credentials", headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.store.delete.assert_called_once_with()
        self.store.load.assert_not_called()

    def test_rejects_malformed_and_oversized_save_requests(self):
        for body, content_type, code in [("username=abc", "text/plain", 415),
                                         ("[]", "application/json", 400),
                                         ("x" * 32769, "application/json", 413)]:
            response = self.client.post("/api/arca-styles/credentials", headers=self.headers,
                                        data=body, content_type=content_type)
            self.assertEqual(response.status_code, code)
        self.store.save.assert_not_called()

    def test_account_changes_are_blocked_while_login_is_pending(self):
        self.manager.status.return_value = {"state": "waiting"}
        for method in ("POST", "DELETE"):
            result = self.client.open("/api/arca-styles/credentials", method=method, headers=self.headers, json={})
            self.assertEqual(result.status_code, 409)
        self.store.save.assert_not_called()
        self.store.delete.assert_not_called()

    @patch("app.clear_arca_browser_session")
    def test_account_change_waits_for_inflight_login_then_rechecks_pending_state(self, clear_session):
        credentials = {"username": "account-a", "password": "fixture-password-a"}
        loaded = threading.Event()
        release_load = threading.Event()
        mutation_waiting = threading.Event()
        responses = {}
        failures = []

        class ObservedAccountLock:
            def __init__(self):
                self.lock = threading.RLock()

            def __enter__(self):
                if threading.current_thread().name == "account-mutation":
                    mutation_waiting.set()
                self.lock.acquire()

            def __exit__(self, *_args):
                self.lock.release()

        def load():
            loaded.set()
            if not release_load.wait(3):
                raise AssertionError("login load was not released")
            return credentials

        def start(**_kwargs):
            self.manager.status.return_value = {"state": "waiting"}
            return {"state": "opening", "message": "로그인 창 여는 중…"}

        def request(name, route, **options):
            try:
                with app.app.test_client() as client:
                    responses[name] = client.post(route, headers=self.headers, **options)
            except Exception as exc:
                failures.append(exc)

        self.store.load.side_effect = load
        self.manager.start.side_effect = start
        login = threading.Thread(target=request, args=("login", "/api/arca-styles/browser-session/import"), daemon=True)
        mutation = threading.Thread(name="account-mutation", target=request,
                                    args=("save", "/api/arca-styles/credentials"),
                                    kwargs={"json": {"username": "account-b", "password": "fixture-password-b"}}, daemon=True)
        with patch("app.ARCA_ACCOUNT_LOCK", ObservedAccountLock()):
            try:
                login.start()
                self.assertTrue(loaded.wait(3))
                mutation.start()
                self.assertTrue(mutation_waiting.wait(3))
                self.store.save.assert_not_called()
            finally:
                release_load.set()
                login.join(3)
                if mutation.ident is not None:
                    mutation.join(3)
        self.assertFalse(login.is_alive())
        self.assertFalse(mutation.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(responses["login"].status_code, 202)
        self.assertEqual(responses["save"].status_code, 409)
        self.store.save.assert_not_called()
        self.manager.start.assert_called_once_with(credentials=credentials)

    @patch("app.clear_arca_browser_session")
    @patch("app.import_arca_browser_session")
    def test_saved_account_goes_straight_to_managed_browser(self, import_session, clear_session):
        credentials = {"username": "test-user", "password": "test-password"}
        self.store.load.return_value = credentials
        self.manager.start.return_value = {"state": "opening", "message": "로그인 창 여는 중…"}
        result = self.client.post("/api/arca-styles/browser-session/import", headers=self.headers)
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.get_json()["state"], "opening")
        self.manager.start.assert_called_once_with(credentials=credentials)
        clear_session.assert_called_once_with()
        import_session.assert_not_called()
        self.assertNotIn("test-password", result.get_data(as_text=True))

    @patch("app.import_arca_browser_session")
    def test_unreadable_saved_account_does_not_fall_back_to_someone_else(self, import_session):
        self.store.load.side_effect = app.ArcaCredentialsError("저장된 로그인 정보를 복원하지 못했습니다.")
        result = self.client.post("/api/arca-styles/browser-session/import", headers=self.headers)
        self.assertEqual(result.status_code, 400)
        self.manager.start.assert_not_called()
        import_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
