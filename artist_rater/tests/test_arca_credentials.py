import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import arca_credentials as credentials
from arca_credentials import ArcaCredentialsError, ArcaCredentialsStore


class ArcaCredentialsStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "login.bin"
        self.store = ArcaCredentialsStore(self.path)
        self.windows = patch("arca_credentials._require_windows")
        self.windows.start()

    def tearDown(self):
        self.windows.stop()
        self.temp.cleanup()

    def test_missing_file_and_delete_are_idempotent(self):
        self.assertIsNone(self.store.load())
        self.assertEqual(self.store.status(), {"saved": False, "username": ""})
        self.store.delete()
        self.path.write_bytes(b"corrupt")
        self.store.delete()
        self.store.delete()
        self.assertFalse(self.path.exists())

    def test_writes_only_encrypted_data_and_status_never_returns_password(self):
        fake_ciphertext = b"encrypted-fixture"
        with patch("arca_credentials._dpapi", return_value=fake_ciphertext) as dpapi:
            self.store.save("fixture-user", "fixture-password")
            plaintext = dpapi.call_args.args[0]
            dpapi.assert_called_once_with(plaintext, protect=True)
            self.assertEqual(json.loads(plaintext), {
                "version": 1, "username": "fixture-user", "password": "fixture-password",
            })
        self.assertEqual(self.path.read_bytes(), credentials._FILE_HEADER + fake_ciphertext)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertNotIn(b"fixture-user", self.path.read_bytes())
        self.assertNotIn(b"fixture-password", self.path.read_bytes())
        with patch("arca_credentials._dpapi", return_value=plaintext) as dpapi:
            self.assertEqual(self.store.status(), {"saved": True, "username": "fixture-user"})
            dpapi.assert_called_once_with(fake_ciphertext, protect=False)

    def test_invalid_inputs_are_rejected_before_writing_or_encrypting(self):
        invalid = [
            ("", "secret"), (" ", "secret"), (None, "secret"),
            ("user", ""), ("user", 42), ("user", "bad\x00secret"),
            ("u" * (credentials.MAX_USERNAME_LENGTH + 1), "secret"),
            ("user", "p" * (credentials.MAX_PASSWORD_LENGTH + 1)),
        ]
        with patch("arca_credentials._dpapi") as dpapi:
            for username, password in invalid:
                with self.subTest(username_type=type(username).__name__, password_type=type(password).__name__):
                    with self.assertRaises(ArcaCredentialsError):
                        self.store.save(username, password)
            dpapi.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_rejects_plaintext_corrupt_empty_and_oversized_files_without_dpapi(self):
        for contents in (
            b'{"username":"fixture-user","password":"fixture-password"}',
            b"", credentials._FILE_HEADER,
            credentials._FILE_HEADER + b"x" * credentials.MAX_FILE_SIZE,
        ):
            with self.subTest(size=len(contents)):
                self.path.write_bytes(contents)
                with patch("arca_credentials._dpapi") as dpapi:
                    with self.assertRaises(ArcaCredentialsError) as raised:
                        self.store.load()
                    self.assertNotIn("fixture-password", str(raised.exception))
                    dpapi.assert_not_called()

    def test_malformed_decrypted_json_is_redacted(self):
        self.path.write_bytes(credentials._FILE_HEADER + b"fixture-cipher")
        for plaintext in (
            b"fixture-password invalid json", b"[]", b"null", b"\xff",
            b'{"version":2,"username":"fixture-user","password":"fixture-password"}',
            b'{"version":1,"username":"fixture-user"}',
        ):
            with self.subTest(size=len(plaintext)):
                with patch("arca_credentials._dpapi", return_value=plaintext):
                    with self.assertRaises(ArcaCredentialsError) as raised:
                        self.store.load()
                    self.assertNotIn("fixture-password", str(raised.exception))

    def test_failed_atomic_replace_preserves_previous_file_and_removes_temp(self):
        self.path.write_bytes(b"previous-encrypted-fixture")
        with patch("arca_credentials._dpapi", return_value=b"new-encrypted-fixture"), \
                patch.object(Path, "replace", side_effect=OSError("fixture-password private-path")):
            with self.assertRaises(ArcaCredentialsError) as raised:
                self.store.save("fixture-user", "fixture-password")
        self.assertNotIn("fixture-password", str(raised.exception))
        self.assertNotIn("private-path", str(raised.exception))
        self.assertEqual(self.path.read_bytes(), b"previous-encrypted-fixture")
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_sync_failure_cleans_up_partial_write(self):
        with patch("arca_credentials._dpapi", return_value=b"fixture-cipher"), \
                patch("arca_credentials.os.fsync", side_effect=OSError("fixture-password")):
            with self.assertRaises(ArcaCredentialsError) as raised:
                self.store.save("fixture-user", "fixture-password")
        self.assertNotIn("fixture-password", str(raised.exception))
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_read_and_delete_errors_do_not_expose_path_or_secrets(self):
        with patch.object(Path, "open", side_effect=OSError("fixture-password private-path")):
            with self.assertRaises(ArcaCredentialsError) as raised:
                self.store.load()
        self.assertNotIn("fixture-password", str(raised.exception))
        self.assertNotIn("private-path", str(raised.exception))
        with patch.object(Path, "unlink", side_effect=OSError("fixture-password private-path")):
            with self.assertRaises(ArcaCredentialsError) as raised:
                self.store.delete()
        self.assertNotIn("fixture-password", str(raised.exception))
        self.assertNotIn("private-path", str(raised.exception))


class ArcaCredentialsPlatformTest(unittest.TestCase):
    def test_missing_credentials_remain_available_on_non_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ArcaCredentialsStore(Path(directory) / "missing.bin")
            with patch("arca_credentials.os.name", "posix"):
                self.assertIsNone(store.load())
                self.assertEqual(store.status(), {"saved": False, "username": ""})

    def test_non_windows_never_uses_plaintext_fallback(self):
        with patch("arca_credentials.os.name", "posix"):
            with self.assertRaises(ArcaCredentialsError) as raised:
                credentials._require_windows()
            self.assertIn("Windows", str(raised.exception))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI integration")
    def test_actual_current_user_dpapi_roundtrip_tamper_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "login.bin"
            store = ArcaCredentialsStore(path)
            store.save("fixture-한글-user", "fixture-비밀번호-☺")
            encrypted = path.read_bytes()
            self.assertNotIn("fixture-한글-user".encode(), encrypted)
            self.assertNotIn("fixture-비밀번호-☺".encode(), encrypted)
            self.assertEqual(store.load(), {"username": "fixture-한글-user", "password": "fixture-비밀번호-☺"})
            self.assertEqual(store.status(), {"saved": True, "username": "fixture-한글-user"})
            store.save("fixture-user", "   ")
            self.assertEqual(store.load()["password"], "   ")
            # A second encryption uses new DPAPI randomness and remains readable.
            store.save("fixture-user-2", "fixture-password-2")
            self.assertNotEqual(path.read_bytes(), encrypted)
            self.assertEqual(store.load()["username"], "fixture-user-2")
            path.write_bytes(credentials._FILE_HEADER + b"not-a-DPAPI-blob")
            with self.assertRaises(ArcaCredentialsError):
                store.load()
            store.delete()
            self.assertEqual(store.status(), {"saved": False, "username": ""})


if __name__ == "__main__":
    unittest.main()
