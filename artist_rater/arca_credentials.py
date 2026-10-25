"""Current-Windows-user encrypted storage for an Arca login."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from threading import RLock


MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 4096
MAX_FILE_SIZE = 64 * 1024
_FILE_HEADER = b"ARCA-CREDENTIALS-DPAPI-1\n"
_STORE_LOCK = RLock()


class ArcaCredentialsError(ValueError):
    pass


def _require_windows():
    if os.name != "nt":
        raise ArcaCredentialsError("로그인 정보 저장은 Windows에서만 사용할 수 있습니다.")


def _validate_credentials(username, password):
    for value, limit in ((username, MAX_USERNAME_LENGTH), (password, MAX_PASSWORD_LENGTH)):
        if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
            raise ArcaCredentialsError("로그인 아이디와 비밀번호를 올바르게 입력해 주세요.")
    if not username.strip():
        raise ArcaCredentialsError("로그인 아이디와 비밀번호를 올바르게 입력해 주세요.")
    return {"username": username, "password": password}


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, protect):
    _require_windows()
    source_buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = _DataBlob()
    kernel32 = None
    try:
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_pointer = ctypes.POINTER(_DataBlob)
        crypt32.CryptProtectData.argtypes = [
            blob_pointer, wintypes.LPCWSTR, blob_pointer, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, blob_pointer,
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [
            blob_pointer, ctypes.POINTER(wintypes.LPWSTR), blob_pointer, ctypes.c_void_p,
            ctypes.c_void_p, wintypes.DWORD, blob_pointer,
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        # UI_FORBIDDEN only: do not enable LOCAL_MACHINE, which would weaken user binding.
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
            raise ArcaCredentialsError("Windows에서 로그인 정보를 암호화하거나 복원하지 못했습니다.")
        if not destination.pbData or not 0 < destination.cbData <= MAX_FILE_SIZE:
            raise ArcaCredentialsError("저장된 로그인 정보를 확인하지 못했습니다.")
        return ctypes.string_at(destination.pbData, destination.cbData)
    except ArcaCredentialsError:
        raise
    except Exception:
        raise ArcaCredentialsError("Windows에서 로그인 정보를 암호화하거나 복원하지 못했습니다.") from None
    finally:
        ctypes.memset(source_buffer, 0, len(source_buffer))
        if kernel32 is not None and destination.pbData:
            ctypes.memset(destination.pbData, 0, destination.cbData)
            kernel32.LocalFree(destination.pbData)


class ArcaCredentialsStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, username, password):
        _require_windows()
        credentials = _validate_credentials(username, password)
        temporary_path = None
        with _STORE_LOCK:
            try:
                plaintext = json.dumps({"version": 1, **credentials}, ensure_ascii=False).encode("utf-8")
                encrypted = _FILE_HEADER + _dpapi(plaintext, protect=True)
                if len(encrypted) > MAX_FILE_SIZE:
                    raise ArcaCredentialsError("로그인 정보가 저장 가능한 크기를 초과했습니다.")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent, prefix=".arca-login-", suffix=".tmp", delete=False) as handle:
                    temporary_path = Path(handle.name)
                    handle.write(encrypted)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary_path.replace(self.path)
            except ArcaCredentialsError:
                raise
            except Exception:
                raise ArcaCredentialsError("로그인 정보를 안전하게 저장하지 못했습니다.") from None
            finally:
                if temporary_path is not None:
                    try:
                        temporary_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def load(self):
        with _STORE_LOCK:
            try:
                try:
                    with self.path.open("rb") as handle:
                        encrypted = handle.read(MAX_FILE_SIZE + 1)
                except FileNotFoundError:
                    return None
                _require_windows()
                if len(encrypted) > MAX_FILE_SIZE or not encrypted.startswith(_FILE_HEADER) or len(encrypted) == len(_FILE_HEADER):
                    raise ArcaCredentialsError("저장된 로그인 정보를 확인하지 못했습니다. 삭제 후 다시 저장해 주세요.")
                plaintext = _dpapi(encrypted[len(_FILE_HEADER):], protect=False)
                credentials = json.loads(plaintext.decode("utf-8"))
                if not isinstance(credentials, dict) or credentials.get("version") != 1:
                    raise ArcaCredentialsError("저장된 로그인 정보를 확인하지 못했습니다. 삭제 후 다시 저장해 주세요.")
                return _validate_credentials(credentials.get("username"), credentials.get("password"))
            except ArcaCredentialsError:
                raise
            except Exception:
                raise ArcaCredentialsError("저장된 로그인 정보를 복원하지 못했습니다. 삭제 후 다시 저장해 주세요.") from None

    def status(self):
        credentials = self.load()
        return {"saved": credentials is not None, "username": credentials["username"] if credentials else ""}

    def delete(self):
        _require_windows()
        with _STORE_LOCK:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                raise ArcaCredentialsError("저장된 로그인 정보를 삭제하지 못했습니다.") from None
