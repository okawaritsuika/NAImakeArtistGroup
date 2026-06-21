import tempfile
import time
import unittest
from pathlib import Path

from arca_login_window import ArcaLoginWindowManager, open_chrome_cdp


class FakeContext:
    def __init__(self, cookie_batches=None, error=None):
        self.cookie_batches = list(cookie_batches or [[]])
        self.error = error
        self.closed = False

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
            self.profile_dir, lambda _jar: {"connected": False},
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

        def connector(jar):
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
            self.profile_dir, lambda _jar: {"connected": False},
            context_factory=lambda _path: context, timeout_seconds=1, poll_seconds=0.01,
        )
        manager.start()
        status = wait_for_state(manager, "failed")
        self.assertEqual(status["message"], "로그인 창이 닫혔습니다. 다시 시도해 주세요.")
        self.assertNotIn("private browser detail", str(status))

    def test_timeout_becomes_safe_failure_and_closes_window(self):
        context = FakeContext()
        manager = ArcaLoginWindowManager(
            self.profile_dir, lambda _jar: {"connected": False},
            context_factory=lambda _path: context, timeout_seconds=0.03, poll_seconds=0.005,
        )
        manager.start()
        status = wait_for_state(manager, "failed")
        self.assertIn("시간이 초과", status["message"])
        self.assertTrue(context.closed)


if __name__ == "__main__":
    unittest.main()
