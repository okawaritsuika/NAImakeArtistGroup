import math
import os
import shutil
from pathlib import Path

from requests.cookies import RequestsCookieJar


EXTENSION_ASSETS = ("manifest.json", "popup.html", "popup.css", "popup.js")
EXTENSION_DIRECTORY_NAME = "arca_session_bridge"
MAX_EXTENSION_COOKIES = 100
MAX_COOKIE_NAME_LENGTH = 256
MAX_COOKIE_VALUE_LENGTH = 8192
MAX_COOKIE_DOMAIN_LENGTH = 253
MAX_COOKIE_PATH_LENGTH = 2048
MAX_TOTAL_COOKIE_TEXT_LENGTH = 128 * 1024
MAX_COOKIE_EXPIRATION = 253402300799
COOKIE_NAME_SEPARATORS = set('()<>@,;:\\"/[]?={}')


class ArcaChromeExtensionError(ValueError):
    pass


def _cookie_text(cookie, key, limit, default=None, allow_empty=False):
    value = cookie.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
    if not allow_empty and not value:
        raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
    return value


def _normalized_arca_domain(value):
    leading_dot = value.startswith(".")
    normalized = value.lower().lstrip(".")
    if normalized != "arca.live" and not normalized.endswith(".arca.live"):
        return ""
    labels = normalized.split(".")
    if any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        or any(not (character.isascii() and (character.isalnum() or character == "-")) for character in label)
        for label in labels
    ):
        return ""
    return f".{normalized}" if leading_dot else normalized


def _cookie_expiration(cookie):
    value = cookie.get("expirationDate")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
    value = int(value)
    if not 0 < value <= MAX_COOKIE_EXPIRATION:
        raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
    return value


def extension_payload_to_cookie_jar(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list):
        raise ArcaChromeExtensionError("브리지 요청 데이터가 올바르지 않습니다.")
    cookies = payload["cookies"]
    if not cookies or len(cookies) > MAX_EXTENSION_COOKIES:
        raise ArcaChromeExtensionError("브리지 쿠키 개수가 허용 범위를 벗어났습니다.")

    jar = RequestsCookieJar()
    total_text_length = 0
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
        name = _cookie_text(cookie, "name", MAX_COOKIE_NAME_LENGTH)
        value = _cookie_text(cookie, "value", MAX_COOKIE_VALUE_LENGTH, allow_empty=True)
        domain = _cookie_text(cookie, "domain", MAX_COOKIE_DOMAIN_LENGTH)
        path = _cookie_text(cookie, "path", MAX_COOKIE_PATH_LENGTH, default="/")
        total_text_length += len(name) + len(value) + len(domain) + len(path)
        if total_text_length > MAX_TOTAL_COOKIE_TEXT_LENGTH:
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 너무 큽니다.")
        if any(ord(character) <= 32 or ord(character) >= 127 or character in COOKIE_NAME_SEPARATORS for character in name):
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
        if not path.startswith("/"):
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
        secure = cookie.get("secure", False)
        if not isinstance(secure, bool):
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.")
        expires = _cookie_expiration(cookie)
        normalized_domain = _normalized_arca_domain(domain)
        if not normalized_domain:
            continue
        try:
            jar.set(
                name,
                value,
                domain=normalized_domain,
                path=path,
                secure=secure,
                expires=expires,
            )
        except Exception:
            raise ArcaChromeExtensionError("브리지 쿠키 데이터가 올바르지 않습니다.") from None

    if not list(jar):
        raise ArcaChromeExtensionError("아카라이브 로그인 정보를 찾지 못했습니다.")
    return jar


def _open_in_explorer(path):
    if not hasattr(os, "startfile"):
        raise OSError("Explorer is unavailable")
    os.startfile(str(path))


def install_arca_session_bridge(data_dir, source_dir=None, opener=None):
    source = Path(source_dir or Path(__file__).resolve().parent / "static" / EXTENSION_DIRECTORY_NAME).resolve()
    asset_sources = [source / name for name in EXTENSION_ASSETS]
    if any(not path.is_file() for path in asset_sources):
        raise ArcaChromeExtensionError("Chrome 브리지 설치 파일을 찾지 못했습니다.")

    destination = Path(data_dir).resolve() / EXTENSION_DIRECTORY_NAME
    destination.mkdir(parents=True, exist_ok=True)
    for name, asset_source in zip(EXTENSION_ASSETS, asset_sources):
        shutil.copyfile(asset_source, destination / name)

    try:
        (opener or _open_in_explorer)(destination)
    except OSError:
        raise ArcaChromeExtensionError("Chrome 브리지 폴더를 열지 못했습니다.") from None
    return destination
