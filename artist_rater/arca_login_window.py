import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import RLock, Thread
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from requests.cookies import RequestsCookieJar


PENDING_STATES = {"opening", "waiting"}
_CHROME_LAUNCH_LOCK = RLock()
LOGIN_URL = "https://arca.live/u/login"


class ArcaLoginWindowError(RuntimeError):
    """A bounded, user-facing browser setup error without private details."""


# Origin/action checks and writes happen in one page task, including after navigation.
_LOGIN_STEP_SCRIPT = """({stage, value}) => {
    if (location.origin !== "https://arca.live" || location.pathname !== "/u/login") return false;
    const form = document.querySelector("#loginForm");
    if (!form) return false;
    const action = new URL(form.getAttribute("action") || location.href, location.href);
    if (action.origin !== "https://arca.live" || action.pathname !== "/u/login") return false;
    const panel = form.querySelector(`#stage-${stage}.active`);
    if (!panel) return false;
    const input = panel.querySelector(stage === 1 ? "#idInput[name=username]" : "#idPassword[name=password]");
    const button = panel.querySelector("button[data-submitstage]");
    if (!input || !button || input.form !== form || button.disabled || !input.getClientRects().length) return false;
    input.value = value;
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new Event("change", {bubbles: true}));
    button.click();
    return true;
}"""


def _launch_external_chrome(command, launcher):
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return launcher(command, **kwargs)
    # PyInstaller's DLL search path is inherited by external Windows programs.
    import ctypes
    with _CHROME_LAUNCH_LOCK:
        kernel32 = ctypes.windll.kernel32
        size = kernel32.GetDllDirectoryW(0, None)
        previous = ctypes.create_unicode_buffer(size + 1)
        kernel32.GetDllDirectoryW(len(previous), previous)
        environment = os.environ.copy()
        bundle = os.path.normcase(os.path.abspath(getattr(sys, "_MEIPASS", "")))
        if getattr(sys, "_MEIPASS", None):
            environment["PATH"] = os.pathsep.join(
                entry for entry in environment.get("PATH", "").split(os.pathsep)
                if os.path.normcase(os.path.abspath(entry or ".")) != bundle
                and not os.path.normcase(os.path.abspath(entry or ".")).startswith(bundle + os.sep)
            )
        if not kernel32.SetDllDirectoryW(None):
            raise ArcaLoginWindowError("Chrome 실행 환경을 준비하지 못했습니다. 앱을 다시 실행해 주세요.")
        try:
            return launcher(command, env=environment, **kwargs)
        finally:
            kernel32.SetDllDirectoryW(ctypes.c_wchar_p(previous.value) if previous.value else None)



def find_chrome_executable():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise ArcaLoginWindowError("Chrome을 찾지 못했습니다. Chrome 설치 후 다시 시도해 주세요.")


def reserve_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_cdp(endpoint, process, timeout_seconds=10):
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener.open(f"{endpoint}/json/version", timeout=0.5) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _connect_playwright_cdp(endpoint):
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        # Read localhost directly and hand Playwright the WebSocket endpoint,
        # avoiding proxy discovery for its HTTP endpoint lookup as well.
        with build_opener(ProxyHandler({})).open(f"{endpoint}/json/version", timeout=2) as response:
            websocket = json.load(response).get("webSocketDebuggerUrl", "")
        parsed, expected = urlsplit(websocket), urlsplit(endpoint)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port != expected.port:
            raise RuntimeError("Unexpected Chrome control endpoint")
        return playwright.chromium.connect_over_cdp(websocket, timeout=10000), playwright
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
    try:
        process = _launch_external_chrome(command, launcher)
    except ArcaLoginWindowError:
        raise
    except Exception:
        raise ArcaLoginWindowError("로그인용 Chrome을 실행하지 못했습니다. Chrome 설치와 실행 권한을 확인해 주세요.") from None
    readiness = readiness or wait_for_cdp
    if not readiness(endpoint, process):
        if process.poll() is None:
            process.terminate()
        raise ArcaLoginWindowError("Chrome 로그인 창과 앱을 연결하지 못했습니다. 다른 로그인 창을 닫고 다시 시도해 주세요.")
    connector = connector or _connect_playwright_cdp
    browser = playwright = None
    try:
        browser, playwright = connector(endpoint)
        if not browser.contexts:
            raise RuntimeError("Chrome context unavailable")
        return browser.contexts[0], playwright, browser, process
    except Exception:
        for resource, method in ((browser, "close"), (playwright, "stop")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass
        if process.poll() is None:
            process.terminate()
        raise ArcaLoginWindowError("Chrome 제어 연결을 준비하지 못했습니다. 앱과 Chrome을 다시 실행해 주세요.") from None


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

    def start(self, credentials=None):
        with self._lock:
            if self._status["state"] in PENDING_STATES and self._thread and self._thread.is_alive():
                return dict(self._status)
            profile_dir = self.profile_dir
            copied = None
            if credentials is not None:
                if not isinstance(credentials, dict) or any(
                    not isinstance(credentials.get(key), str) or not credentials[key]
                    for key in ("username", "password")
                ):
                    raise ValueError("저장된 로그인 정보를 확인해 주세요.")
                copied = {key: credentials[key] for key in ("username", "password")}
                account = hashlib.sha256(copied["username"].encode("utf-8")).hexdigest()
                profile_dir = profile_dir / "accounts" / account
            self._status = self._public_status("opening", "로그인 창 여는 중…")
            self._thread = Thread(target=self._run, args=(copied, profile_dir), daemon=True, name="arca-login-window")
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

    @staticmethod
    def _autofill_once(page, credentials):
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            return "아카라이브 로그인 페이지에 접속하지 못했습니다. 열린 Chrome에서 접속과 로그인을 확인해 주세요."
        try:
            page.wait_for_function(
                "() => !!document.querySelector('#stage-1.active #idInput')",
                timeout=10000,
            )
            if not page.evaluate(_LOGIN_STEP_SCRIPT, {"stage": 1, "value": credentials["username"]}):
                return "아카라이브 로그인 화면을 확인하지 못해 자동 입력을 중단했습니다. 열린 Chrome에서 로그인해 주세요."
            page.wait_for_function(
                "() => !!document.querySelector('#loginForm .stage.active:not(#stage-1)')",
                timeout=15000,
            )
            if page.evaluate(_LOGIN_STEP_SCRIPT, {"stage": 2, "value": credentials["password"]}):
                return "저장한 계정으로 로그인을 요청했습니다. 캡차나 추가 인증이 나오면 열린 Chrome에서 완료해 주세요."
        except Exception:
            pass
        return "자동 입력을 마치지 못했습니다. 열린 Chrome에서 로그인 또는 추가 인증을 완료해 주세요."

    def _run(self, credentials=None, profile_dir=None):
        resources = (None, None)
        opened = False
        last_error = ""
        try:
            created = self.context_factory(profile_dir or self.profile_dir)
            resources = created if isinstance(created, tuple) else (created, None)
            context = resources[0]
            opened = True
            pages = context.pages
            page = pages[0] if pages else context.new_page()
            try:
                user_agent = page.evaluate("() => navigator.userAgent")
            except Exception:
                user_agent = ""
            waiting_message = "로그인 창에서 아카라이브에 로그인해 주세요."
            self._set_status("waiting", waiting_message)
            deadline = time.monotonic() + self.timeout_seconds
            previous_cookies, next_validation = None, 0
            while time.monotonic() < deadline:
                if page.is_closed():
                    break
                jar = self._cookie_jar(context.cookies(["https://arca.live"]))
                cookie_state = tuple((item.domain, item.path, item.name, item.value) for item in jar)
                now = time.monotonic()
                if cookie_state and (cookie_state != previous_cookies or now >= next_validation):
                    previous_cookies, next_validation = cookie_state, now + 10
                    try:
                        result = self.connector(jar, user_agent=user_agent)
                    except Exception:
                        result = {"connected": False, "error": "앱의 로그인 상태 확인에 실패했습니다. 잠시 후 다시 시도해 주세요."}
                    if result.get("connected"):
                        self._close(resources)
                        resources = (None, None)
                        self._set_status(
                            "connected", "전용 Chrome 로그인 연결됨",
                            connected=True, browser=result.get("browser") or "전용 Chrome",
                        )
                        return
                    last_error = str(result.get("error") or "")
                if credentials:
                    waiting_message = self._autofill_once(page, credentials)
                    credentials.clear()
                    credentials = None
                message = waiting_message + (" " + last_error if last_error else "")
                self._set_status("waiting", message, error=last_error)
                time.sleep(self.poll_seconds)
            if last_error:
                self._set_status("failed", last_error, error=last_error)
            elif page.is_closed():
                self._set_status("failed", "로그인 창이 닫혔습니다. 다시 시도해 주세요.", error="로그인 창 종료")
            else:
                self._set_status("failed", "로그인 시간이 초과되었습니다. 다시 시도해 주세요.", error="로그인 시간 초과")
        except ArcaLoginWindowError as exc:
            self._set_status("failed", str(exc), error=str(exc))
        except Exception:
            if last_error:
                self._set_status("failed", last_error, error=last_error)
            elif opened:
                self._set_status("failed", "로그인 창과 연결이 끊겼습니다. 다시 시도해 주세요.", error="로그인 창 연결 종료")
            else:
                self._set_status("failed", "로그인 창을 준비하지 못했습니다. Chrome 설치와 앱 실행 상태를 확인해 주세요.", error="로그인 창 준비 실패")
        finally:
            if credentials is not None:
                credentials.clear()
            if resources[0] is not None:
                self._close(resources)
