import ctypes
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import arca_login_window as login
from arca_login_window import ArcaLoginWindowError, ArcaLoginWindowManager, open_chrome_cdp


class FakePage:
    def __init__(self, allow_password=True, navigation_error=None):
        self.allow_password = allow_password
        self.navigation_error = navigation_error
        self.visits = []
        self.submissions = []
        self.closed = False

    def evaluate(self, script, arg=None):
        if arg is None:
            return "Chrome-login-test/1.0"
        self.submissions.append(dict(arg))
        return arg["stage"] == 1 or self.allow_password

    def goto(self, url, **kwargs):
        self.visits.append(url)
        if self.navigation_error:
            raise self.navigation_error

    def wait_for_function(self, script, **kwargs):
        pass

    def is_closed(self):
        return self.closed


class FakeContext:
    def __init__(self, cookie_batches=None, error=None, page=None):
        self.cookie_batches = list(cookie_batches or [[]])
        self.error = error
        self.closed = False
        self.pages = [page or FakePage()]

    def cookies(self, _urls):
        if self.error:
            raise self.error
        if len(self.cookie_batches) > 1:
            return self.cookie_batches.pop(0)
        return self.cookie_batches[0]

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


class FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]
        self.closed = False

    def close(self):
        self.closed = True


class FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def wait_for_state(manager, expected, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status()
        if status["state"] == expected:
            return status
        time.sleep(0.005)
    raise AssertionError(f"state did not become {expected}: {manager.status()}")


class ArcaLoginWindowManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.profile_dir = Path(self.temp.name) / "profile"

    def tearDown(self):
        self.temp.cleanup()

    def test_opens_normal_chrome_with_localhost_cdp_without_automation_flag(self):
        launched = {}
        process = FakeProcess()
        context = FakeContext()
        browser = FakeBrowser(context)
        playwright = FakePlaywright()
        connected = {}

        def launcher(command, **kwargs):
            launched["command"] = command
            launched["kwargs"] = kwargs
            return process

        def connector(endpoint):
            connected["endpoint"] = endpoint
            return browser, playwright

        resources = open_chrome_cdp(
            self.profile_dir, chrome_path=Path("C:/Chrome/chrome.exe"), port=43123,
            launcher=launcher, connector=connector,
            readiness=lambda endpoint, launched_process: (endpoint, launched_process) == ("http://127.0.0.1:43123", process),
        )

        command = launched["command"]
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertIn("--remote-debugging-port=43123", command)
        self.assertFalse(any("enable-automation" in value for value in command))
        self.assertEqual(connected["endpoint"], "http://127.0.0.1:43123")
        self.assertEqual(resources, (context, playwright, browser, process))

    def test_starts_only_one_login_window_worker(self):
        context = FakeContext()
        calls = []

        def factory(_profile_dir):
            calls.append(1)
            return context

        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **_kwargs: {"connected": False},
            context_factory=factory, timeout_seconds=0.2, poll_seconds=0.01,
        )
        manager.start()
        wait_for_state(manager, "waiting")
        manager.start()
        self.assertEqual(len(calls), 1)
        wait_for_state(manager, "failed")

    def test_filters_cookies_and_connects_then_closes_window(self):
        context = FakeContext(cookie_batches=[[
            {"name": "session", "value": "arca-secret", "domain": ".arca.live", "path": "/", "secure": True},
            {"name": "other", "value": "other-secret", "domain": ".example.com", "path": "/"},
        ]])
        received = []
        process = FakeProcess()
        browser = FakeBrowser(context)
        playwright = FakePlaywright()

        def connector(jar, **kwargs):
            self.assertEqual(kwargs["user_agent"], "Chrome-login-test/1.0")
            received.extend((cookie.domain, cookie.name) for cookie in jar)
            return {"connected": True, "browser": "전용 Chrome", "error": ""}

        manager = ArcaLoginWindowManager(
            self.profile_dir, connector,
            context_factory=lambda _path: (context, playwright, browser, process),
            timeout_seconds=1, poll_seconds=0.01,
        )
        manager.start()
        status = wait_for_state(manager, "connected")
        self.assertTrue(status["connected"])
        self.assertEqual(received, [(".arca.live", "session")])
        self.assertTrue(context.closed)
        self.assertTrue(browser.closed)
        self.assertTrue(playwright.stopped)
        self.assertTrue(process.terminated)
        self.assertNotIn("arca-secret", str(status))

    def test_closed_window_becomes_safe_failure(self):
        context = FakeContext(error=RuntimeError("private browser detail"))
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **_kwargs: {"connected": False},
            context_factory=lambda _path: context, timeout_seconds=1, poll_seconds=0.01,
        )
        manager.start()
        status = wait_for_state(manager, "failed")
        self.assertIn("로그인 창과 연결이 끊겼습니다", status["message"])
        self.assertNotIn("private browser detail", str(status))

    def test_timeout_becomes_safe_failure_and_closes_window(self):
        context = FakeContext()
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **_kwargs: {"connected": False},
            context_factory=lambda _path: context, timeout_seconds=0.03, poll_seconds=0.005,
        )
        manager.start()
        status = wait_for_state(manager, "failed")
        self.assertIn("시간이 초과", status["message"])
        self.assertTrue(context.closed)


    def test_saved_account_uses_private_stable_profile_and_does_not_keep_credentials(self):
        paths = []
        def factory(profile):
            paths.append(profile)
            return FakeContext()
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **kwargs: {"connected": False},
            context_factory=factory, timeout_seconds=0.03, poll_seconds=0.005,
        )
        for username, password in [("synthetic-account", "first-test-secret"), ("synthetic-account", "changed-test-secret"), ("second-account", "other-test-secret")]:
            manager.start({"username": username, "password": password})
            wait_for_state(manager, "failed")
        self.assertEqual(paths[0], paths[1])
        self.assertNotEqual(paths[0], paths[2])
        self.assertEqual(paths[0], self.profile_dir / "accounts" / hashlib.sha256(b"synthetic-account").hexdigest())
        self.assertNotIn("synthetic-account", str(paths[0]))
        self.assertNotIn("test-secret", str(manager.status()))
        self.assertFalse(any("credential" in key for key in vars(manager)))

    def test_existing_account_session_skips_credential_submission(self):
        context = FakeContext(cookie_batches=[[{"name": "session", "value": "test-cookie", "domain": ".arca.live"}]])
        credentials = {"username": "synthetic-account", "password": "test-secret"}
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **kwargs: {"connected": True},
            context_factory=lambda _path: context, timeout_seconds=0.03, poll_seconds=0.005,
        )
        manager._run(credentials)
        self.assertTrue(manager.status()["connected"])
        self.assertEqual(context.pages[0].visits, [])
        self.assertEqual(context.pages[0].submissions, [])
        self.assertEqual(credentials, {})

    def test_saved_credentials_submit_only_once_then_keep_window_for_manual_verification(self):
        page = FakePage(allow_password=False)
        context = FakeContext(page=page)
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **kwargs: {"connected": False},
            context_factory=lambda _path: context, timeout_seconds=0.2, poll_seconds=0.005,
        )
        original = {"username": "synthetic-account", "password": "test-secret"}
        manager.start(original)
        wait_for_state(manager, "waiting")
        time.sleep(0.03)
        self.assertFalse(context.closed)
        self.assertEqual(page.visits, [login.LOGIN_URL])
        self.assertEqual([item["stage"] for item in page.submissions], [1, 2])
        self.assertIn("추가 인증", manager.status()["message"])
        self.assertEqual(original["password"], "test-secret")
        wait_for_state(manager, "failed")
        self.assertEqual(len(page.submissions), 2)

    def test_validation_failure_remains_visible_after_timeout(self):
        context = FakeContext(cookie_batches=[[{"name": "session", "value": "test-cookie", "domain": ".arca.live"}]])
        error = "아카라이브 인증서 확인에 실패했습니다."
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar, **kwargs: {"connected": False, "error": error},
            context_factory=lambda _path: context, timeout_seconds=0.03, poll_seconds=0.005,
        )
        manager._run()
        self.assertEqual(manager.status()["error"], error)
        self.assertEqual(manager.status()["message"], error)
        self.assertNotIn("test-cookie", str(manager.status()))

    def test_startup_failure_does_not_claim_user_closed_window_or_leak_details(self):
        def factory(_path):
            raise RuntimeError("private-test-secret")
        manager = ArcaLoginWindowManager(self.profile_dir, lambda _jar, **kwargs: {}, context_factory=factory)
        manager._run({"username": "synthetic", "password": "test-secret"})
        self.assertIn("준비", manager.status()["message"])
        self.assertNotIn("닫혔", manager.status()["message"])
        self.assertNotIn("test-secret", str(manager.status()))

    def test_navigation_failure_keeps_window_waiting_without_submitting_credentials(self):
        page = FakePage(navigation_error=RuntimeError("private-test-secret"))
        message = ArcaLoginWindowManager._autofill_once(page, {"username": "synthetic", "password": "test-secret"})
        self.assertIn("접속하지 못했습니다", message)
        self.assertNotIn("test-secret", message)
        self.assertEqual(page.submissions, [])

    def test_cdp_readiness_bypasses_proxy_settings(self):
        process = FakeProcess()
        response = Mock()
        response.status = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(login, "ProxyHandler") as proxy, patch.object(login, "build_opener", return_value=opener):
            self.assertTrue(login.wait_for_cdp("http://127.0.0.1:43123", process))
        proxy.assert_called_once_with({})
        opener.open.assert_called_once_with("http://127.0.0.1:43123/json/version", timeout=0.5)

    def test_cdp_readiness_allows_chrome_starting_after_ten_seconds(self):
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(login, "build_opener", return_value=opener), \
                patch.object(login.time, "monotonic", side_effect=[0, 11]):
            self.assertTrue(login.wait_for_cdp("http://127.0.0.1:43123", FakeProcess()))

    def test_cdp_failure_is_classified_and_stops_only_the_created_process(self):
        process = FakeProcess()
        with self.assertRaises(ArcaLoginWindowError) as raised:
            open_chrome_cdp(self.profile_dir, chrome_path="C:/synthetic/chrome.exe", port=43123,
                            launcher=lambda *args, **kwargs: process, readiness=lambda *args: False)
        self.assertIn("연결하지 못했습니다", str(raised.exception))
        self.assertTrue(process.terminated)

    def test_frozen_chrome_launch_restores_dll_path_and_excludes_bundle_path(self):
        calls = []
        class Kernel:
            def GetDllDirectoryW(self, size, buffer):
                if buffer is not None:
                    buffer.value = "C:\\synthetic-bundle"
                return len("C:\\synthetic-bundle")
            def SetDllDirectoryW(self, value):
                calls.append(None if value is None else value.value)
                return 1
        kernel = Kernel()
        bundle = str(self.profile_dir / "bundle")
        safe = str(self.profile_dir / "external")
        received = {}
        def launcher(command, **kwargs):
            self.assertEqual(calls, [None])
            received.update(kwargs)
            raise OSError("synthetic launch failure")
        with patch.object(login.sys, "platform", "win32"), patch.object(login.sys, "frozen", True, create=True), \
             patch.object(login.sys, "_MEIPASS", bundle, create=True), \
             patch.object(ctypes, "windll", Mock(kernel32=kernel), create=True), \
             patch.dict(os.environ, {"PATH": os.pathsep.join([bundle, str(Path(bundle) / "child"), safe])}):
            with self.assertRaises(OSError):
                login._launch_external_chrome(["synthetic-chrome"], launcher)
        self.assertEqual(calls, [None, "C:\\synthetic-bundle"])
        self.assertEqual(received["env"]["PATH"], safe)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for atomic page input checks")
    def test_login_page_script_refuses_external_origin_and_external_form_action(self):
        harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));
const results = [];
for (const [origin, action, active, stage] of [
  ['https://arca.live', '', 1, 1], ['https://arca.live', '', 2, 2],
  ['https://example.com', '', 2, 2], ['https://arca.live', 'https://example.com/u/login', 2, 2],
  ['https://arca.live', '/not-login', 2, 2], ['https://arca.live', '', 3, 2],
]) {
  let clicks = 0;
  const input = { value: '', getClientRects: () => [1], dispatchEvent() {} };
  const button = { disabled: false, click: () => clicks++ };
  const panel = { querySelector: selector => selector.startsWith('button') ? button : input };
  const form = { getAttribute: () => action, querySelector: selector => selector === `#stage-${active}.active` ? panel : null };
  input.form = form;
  const context = vm.createContext({ URL, Event: class {}, location: {origin, pathname: '/u/login', href: origin + '/u/login'}, document: {querySelector: () => form} });
  const result = vm.runInContext('(' + source + ')', context)({stage, value: 'synthetic-test-value'});
  results.push({result, clicks, filled: !!input.value});
}
process.stdout.write(JSON.stringify(results));
"""
        result = subprocess.run([shutil.which("node"), "-e", harness], input=json.dumps(login._LOGIN_STEP_SCRIPT),
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertTrue(all(row == {"result": True, "clicks": 1, "filled": True} for row in rows[:2]))
        self.assertTrue(all(row == {"result": False, "clicks": 0, "filled": False} for row in rows[2:]))


    def test_cdp_connector_uses_only_the_direct_local_websocket(self):
        for websocket, succeeds in [("ws://127.0.0.1:43123/devtools/browser/test", True), ("ws://example.com:43123/browser/test", False)]:
            with self.subTest(websocket=websocket):
                driver = Mock()
                module = Mock()
                module.sync_playwright.return_value.start.return_value = driver
                opener = Mock()
                opener.open.return_value = io.BytesIO(json.dumps({"webSocketDebuggerUrl": websocket}).encode())
                with patch.dict(sys.modules, {"playwright.sync_api": module}), patch.object(login, "build_opener", return_value=opener):
                    if succeeds:
                        browser, received = login._connect_playwright_cdp("http://127.0.0.1:43123")
                        self.assertIs(received, driver)
                        driver.chromium.connect_over_cdp.assert_called_once_with(websocket, timeout=10000)
                        driver.stop.assert_not_called()
                    else:
                        with self.assertRaises(RuntimeError):
                            login._connect_playwright_cdp("http://127.0.0.1:43123")
                        driver.chromium.connect_over_cdp.assert_not_called()
                        driver.stop.assert_called_once()

    def test_missing_context_cleans_up_driver_and_created_chrome(self):
        process, driver, browser = FakeProcess(), FakePlaywright(), Mock()
        browser.contexts = []
        with self.assertRaises(ArcaLoginWindowError):
            open_chrome_cdp(self.profile_dir, chrome_path="C:/synthetic/chrome.exe", port=43123,
                            launcher=lambda *args, **kwargs: process, readiness=lambda *args: True,
                            connector=lambda endpoint: (browser, driver))
        self.assertTrue(process.terminated)
        self.assertTrue(driver.stopped)
        browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
