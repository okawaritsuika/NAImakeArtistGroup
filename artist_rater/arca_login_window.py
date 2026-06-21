import os
import socket
import subprocess
import time
from pathlib import Path
from threading import RLock, Thread
from urllib.request import urlopen

from requests.cookies import RequestsCookieJar


PENDING_STATES = {"opening", "waiting"}


def find_chrome_executable():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("Chrome not found")


def reserve_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_cdp(endpoint, process, timeout_seconds=10):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(f"{endpoint}/json/version", timeout=0.5) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _connect_playwright_cdp(endpoint):
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        return playwright.chromium.connect_over_cdp(endpoint), playwright
    except Exception:
        playwright.stop()
        raise


def open_chrome_cdp(profile_dir, chrome_path=None, port=None, launcher=None, connector=None, readiness=None):
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    chrome_path = Path(chrome_path) if chrome_path else find_chrome_executable()
    port = int(port or reserve_local_port())
    endpoint = f"http://127.0.0.1:{port}"
    command = [
        str(chrome_path),
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "https://arca.live/b/aiart",
    ]
    launcher = launcher or subprocess.Popen
    process = launcher(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    readiness = readiness or wait_for_cdp
    if not readiness(endpoint, process):
        if process.poll() is None:
            process.terminate()
        raise RuntimeError("Chrome CDP unavailable")
    connector = connector or _connect_playwright_cdp
    try:
        browser, playwright = connector(endpoint)
        if not browser.contexts:
            raise RuntimeError("Chrome context unavailable")
        return browser.contexts[0], playwright, browser, process
    except Exception:
        if process.poll() is None:
            process.terminate()
        raise


class ArcaLoginWindowManager:
    def __init__(self, profile_dir, connector, context_factory=None, timeout_seconds=300, poll_seconds=1):
        self.profile_dir = Path(profile_dir)
        self.connector = connector
        self.context_factory = context_factory or self._open_chrome
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self._lock = RLock()
        self._thread = None
        self._status = self._public_status("idle", "")

    @staticmethod
    def _public_status(state, message, connected=False, browser="", error=""):
        return {
            "connected": bool(connected),
            "browser": str(browser or ""),
            "error": str(error or ""),
            "state": state,
            "message": str(message or ""),
        }

    def status(self):
        with self._lock:
            return dict(self._status)

    def _set_status(self, state, message, connected=False, browser="", error=""):
        with self._lock:
            self._status = self._public_status(state, message, connected, browser, error)

    def start(self):
        with self._lock:
            if self._status["state"] in PENDING_STATES and self._thread and self._thread.is_alive():
                return dict(self._status)
            self._status = self._public_status("opening", "로그인 창 여는 중…")
            self._thread = Thread(target=self._run, daemon=True, name="arca-login-window")
            self._thread.start()
            return dict(self._status)

    @staticmethod
    def _open_chrome(profile_dir):
        return open_chrome_cdp(profile_dir)

    @staticmethod
    def _cookie_jar(raw_cookies):
        jar = RequestsCookieJar()
        for cookie in raw_cookies or []:
            domain = str(cookie.get("domain") or "").lower()
            normalized = domain.lstrip(".")
            if normalized != "arca.live" and not normalized.endswith(".arca.live"):
                continue
            jar.set(
                str(cookie.get("name") or ""), str(cookie.get("value") or ""),
                domain=domain, path=str(cookie.get("path") or "/"),
                secure=bool(cookie.get("secure")),
            )
        return jar

    @staticmethod
    def _close(resources):
        padded = tuple(resources) + (None,) * (4 - len(resources))
        context, playwright, browser, process = padded[:4]
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                pass

    def _run(self):
        resources = (None, None)
        try:
            created = self.context_factory(self.profile_dir)
            resources = created if isinstance(created, tuple) else (created, None)
            context = resources[0]
            self._set_status("waiting", "로그인 창에서 아카라이브에 로그인해 주세요.")
            deadline = time.monotonic() + self.timeout_seconds
            while time.monotonic() < deadline:
                jar = self._cookie_jar(context.cookies(["https://arca.live"]))
                if list(jar):
                    result = self.connector(jar)
                    if result.get("connected"):
                        self._close(resources)
                        resources = (None, None)
                        self._set_status(
                            "connected", "전용 Chrome 로그인 연결됨",
                            connected=True, browser=result.get("browser") or "전용 Chrome",
                        )
                        return
                time.sleep(self.poll_seconds)
            self._set_status("failed", "로그인 시간이 초과되었습니다. 다시 시도해 주세요.", error="로그인 시간 초과")
        except Exception:
            self._set_status("failed", "로그인 창이 닫혔습니다. 다시 시도해 주세요.", error="로그인 창 종료")
        finally:
            if resources[0] is not None:
                self._close(resources)
