import hashlib
import io
import json
import os
import ssl
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

import arca_image_archive as archive_module
from arca_image_archive import (
    ArcaImageArchiveError,
    _validated_manifest,
    append_local_upload,
    download_google_archive,
    install_image_archive,
    start_local_upload,
)
from arca_style_collector import get_collection_job, init_arca_style_tables


class FakeResponse:
    def __init__(self, status, headers, chunks):
        self.status_code = status
        self.headers = headers
        self._chunks = chunks
        self.closed = False

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ArcaImageArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "test.sqlite"
        self.seed_path = self.root / "seed.sqlite"
        self.image_dir = self.root / "images"
        init_arca_style_tables(self.db_path)
        init_arca_style_tables(self.seed_path)

    def tearDown(self):
        self.temp.cleanup()

    def make_archive(self, entries):
        path = self.root / "images.zip"
        files = []
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            for image_id, item_id, name, data in entries:
                archive.writestr(f"arca_style_images/{name}", data)
                files.append({
                    "image_id": image_id,
                    "item_id": item_id,
                    "name": name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                })
            archive.writestr("manifest.json", json.dumps({
                "format": archive_module.ARCHIVE_FORMAT,
                "version": 1,
                "file_count": len(files),
                "total_bytes": sum(item["bytes"] for item in files),
                "files": files,
            }))
        return path

    def test_resumes_google_download_from_existing_partial_file(self):
        target = self.root / "archive.partial"
        target.write_bytes(b"abc")
        response = FakeResponse(206, {
            "Content-Type": "application/octet-stream",
            "Content-Range": "bytes 3-5/6",
        }, [b"def"])
        session = FakeSession(response)
        with (
            patch.object(archive_module, "ARCHIVE_BYTES", 6),
            patch.object(archive_module, "_check_free_space"),
        ):
            download_google_archive(target, session=session)
        self.assertEqual(target.read_bytes(), b"abcdef")
        self.assertEqual(session.calls[0][1]["headers"], {"Range": "bytes=3-"})
        self.assertTrue(response.closed)

    def test_installs_by_stable_seed_identity_when_local_row_ids_differ(self):
        first_url = "https://ac.namu.la/path/one.png?expires=1&key=old"
        second_url = "https://ac.namu.la/path/two.png?expires=1&key=old"
        first_name = hashlib.sha256(first_url.encode()).hexdigest() + ".png"
        second_name = hashlib.sha256(second_url.encode()).hexdigest() + ".png"
        with closing(sqlite3.connect(self.seed_path)) as connection, connection:
            connection.execute(
                "INSERT INTO arca_style_items(id,source_url,collected_at,updated_at,metadata_status) "
                "VALUES(1,?,?,?,?)",
                ("https://arca.live/b/aiart/1", "now", "now", "ok"),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,image_path,metadata_status,created_at) "
                "VALUES(1,1,?,?,?,?)",
                (first_url, "", "ok", "now"),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,image_path,metadata_status,created_at) "
                "VALUES(2,1,?,?,?,?)",
                (second_url, "", "ok", "now"),
            )
        local_first_url = "https://ac.arca.live/path/one.png?expires=99&key=new"
        local_second_url = "https://ac.arca.live/path/two.png?expires=99&key=new"
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "INSERT INTO arca_style_items(id,source_url,collected_at,updated_at,representative_image_url,metadata_status) "
                "VALUES(91,?,?,?,?,?)",
                ("https://arca.live/b/aiart/1", "now", "now", local_first_url, "ok"),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,image_path,metadata_status,created_at) "
                "VALUES(101,91,?,?,?,?)",
                (local_first_url, "", "ok", "now"),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,image_path,metadata_status,created_at) "
                "VALUES(102,91,?,?,?,?)",
                (local_second_url, "", "ok", "now"),
            )
        archive_path = self.make_archive([
            (1, 1, first_name, b"first"),
            (2, 1, second_name, b"second"),
        ])
        archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        result = install_image_archive(
            archive_path,
            self.db_path,
            self.image_dir,
            self.seed_path,
            expected_archive_sha256=archive_hash,
            expected_archive_bytes=archive_path.stat().st_size,
            expected_count=2,
            expected_bytes=11,
        )
        self.assertEqual(result, {"installed": 2, "reused": 0, "updated_rows": 2, "skipped_rows": 0})
        self.assertEqual((self.image_dir / first_name).read_bytes(), b"first")
        self.assertEqual((self.image_dir / second_name).read_bytes(), b"second")
        with closing(sqlite3.connect(self.db_path)) as connection:
            paths = connection.execute("SELECT image_path FROM arca_style_images ORDER BY id").fetchall()
            representative = connection.execute(
                "SELECT representative_image_path FROM arca_style_items WHERE id=91"
            ).fetchone()[0]
        self.assertEqual(paths, [(first_name,), (second_name,)])
        self.assertEqual(representative, first_name)

    def test_archive_with_no_matching_local_rows_does_not_report_success(self):
        url = "https://ac.namu.la/path/one.png?expires=1&key=old"
        name = hashlib.sha256(url.encode()).hexdigest() + ".png"
        with closing(sqlite3.connect(self.seed_path)) as connection, connection:
            connection.execute(
                "INSERT INTO arca_style_items(id,source_url,collected_at,updated_at) VALUES(1,?,'now','now')",
                ("https://arca.live/b/aiart/1",),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,metadata_status,created_at) VALUES(1,1,?,'ok','now')",
                (url,),
            )
        archive_path = self.make_archive([(1, 1, name, b"image")])
        with self.assertRaisesRegex(ArcaImageArchiveError, "연결할.*없"):
            install_image_archive(
                archive_path, self.db_path, self.image_dir, self.seed_path,
                expected_archive_sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                expected_archive_bytes=archive_path.stat().st_size,
                expected_count=1, expected_bytes=5,
            )
        self.assertTrue(archive_path.is_file())
        self.assertFalse((self.image_dir / name).exists())

    def test_partial_install_reports_unmatched_images_and_keeps_zip(self):
        archive_path = self.root / "partial-install.zip"
        archive_path.write_bytes(b"archive")
        job_id = archive_module._create_archive_job(self.db_path, "local", archive_path)
        with patch.object(archive_module, "install_image_archive", return_value={
            "installed": 1, "reused": 0, "updated_rows": 1, "skipped_rows": 1,
        }):
            archive_module._run_archive_job(
                self.db_path, self.image_dir, self.root, self.seed_path,
                job_id, "local", archive_path,
            )
        job = get_collection_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["downloaded_images"], 1)
        self.assertIn("건너뛰었습니다", job["error"])
        self.assertTrue(archive_path.is_file())

    def test_rejects_archive_path_traversal(self):
        manifest = {
            "format": archive_module.ARCHIVE_FORMAT,
            "version": 1,
            "file_count": 1,
            "total_bytes": 1,
            "files": [{
                "image_id": 1,
                "item_id": 1,
                "name": "../escape.png",
                "bytes": 1,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }],
        }
        path = self.root / "bad.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("arca_style_images/../escape.png", b"x")
            archive.writestr("manifest.json", json.dumps(manifest))
        with zipfile.ZipFile(path) as archive:
            with self.assertRaises(ArcaImageArchiveError):
                _validated_manifest(archive, expected_count=1, expected_bytes=1)

    def test_local_zip_upload_is_chunked_before_install_job(self):
        with (
            patch.object(archive_module, "ARCHIVE_BYTES", 6),
            patch.object(archive_module, "_check_free_space"),
        ):
            upload = start_local_upload(self.root, "copy (1).zip", 6)
            first = append_local_upload(upload["upload_id"], 0, io.BytesIO(b"abc"), 3)
            second = append_local_upload(upload["upload_id"], 3, io.BytesIO(b"def"), 3)
        self.assertEqual(first["uploaded_bytes"], 3)
        self.assertEqual(second["uploaded_bytes"], 6)

    def add_image(self, db_path, item_id, image_id, source, url):
        with closing(sqlite3.connect(db_path)) as connection, connection:
            connection.execute(
                "INSERT INTO arca_style_items(id,source_url,collected_at,updated_at) VALUES(?,?,'now','now')",
                (item_id, source),
            )
            connection.execute(
                "INSERT INTO arca_style_images(id,item_id,image_url,metadata_status,created_at) VALUES(?,?,?,'ok','now')",
                (image_id, item_id, url),
            )

    def legacy_spec(self, path, image_bytes=5):
        return {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "image_count": 1,
            "image_bytes": image_bytes,
        }

    def test_legacy_pack_auto_detects_and_uses_historical_key_after_seed_ids_change(self):
        source = "https://arca.live/b/aiart/1"
        old_url = "https://ac.namu.la/path/one.png?expires=1&key=old"
        refreshed_url = "https://ac.arca.live/path/one.png?expires=99&key=new"
        name = hashlib.sha256(old_url.encode()).hexdigest() + ".png"
        self.add_image(self.seed_path, 50, 60, source, refreshed_url)
        self.add_image(self.db_path, 90, 100, source, refreshed_url)
        path = self.make_archive([(1, 1, name, b"image")])
        keys = {name: [source, archive_module._image_identity(old_url)]}
        with (
            patch.object(archive_module, "LEGACY_ARCHIVES", (self.legacy_spec(path),)),
            patch.object(archive_module, "_legacy_image_keys", return_value=keys),
        ):
            result = install_image_archive(path, self.db_path, self.image_dir, self.seed_path)
        self.assertEqual(result, {"installed": 1, "reused": 0, "updated_rows": 1, "skipped_rows": 0})
        self.assertEqual((self.image_dir / name).read_bytes(), b"image")
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT image_path FROM arca_style_images WHERE id=100").fetchone()[0], name)

    def test_legacy_pack_hash_mismatch_is_rejected_before_extracting_or_linking(self):
        path = self.make_archive([(1, 1, "a" * 64 + ".png", b"image")])
        spec = self.legacy_spec(path)
        spec["sha256"] = "0" * 64
        with patch.object(archive_module, "LEGACY_ARCHIVES", (spec,)):
            with self.assertRaisesRegex(ArcaImageArchiveError, "SHA-256"):
                install_image_archive(path, self.db_path, self.image_dir, self.seed_path)
        self.assertFalse(self.image_dir.exists())
        self.assertTrue(path.is_file())

    def test_legacy_pack_installs_current_seed_images_and_skips_removed_sources(self):
        source = "https://arca.live/b/aiart/1"
        url = "https://ac.namu.la/one.png"
        name = hashlib.sha256(url.encode()).hexdigest() + ".png"
        removed_name = "b" * 64 + ".png"
        self.add_image(self.seed_path, 50, 60, source, url)
        self.add_image(self.db_path, 90, 100, source, url)
        path = self.make_archive([(1, 1, name, b"image"), (2, 2, removed_name, b"other")])
        spec = self.legacy_spec(path, image_bytes=10)
        spec["image_count"] = 2
        keys = {
            name: [source, archive_module._image_identity(url)],
            removed_name: ["https://arca.live/b/aiart/2", archive_module._image_identity("https://ac.namu.la/removed.png")],
        }
        with (
            patch.object(archive_module, "LEGACY_ARCHIVES", (spec,)),
            patch.object(archive_module, "_legacy_image_keys", return_value=keys),
        ):
            result = install_image_archive(path, self.db_path, self.image_dir, self.seed_path)
        self.assertEqual(result, {"installed": 1, "reused": 0, "updated_rows": 1, "skipped_rows": 1})
        self.assertEqual((self.image_dir / name).read_bytes(), b"image")
        self.assertFalse((self.image_dir / removed_name).exists())

    def test_legacy_manifest_ids_cannot_link_an_unknown_filename_to_another_image(self):
        source = "https://arca.live/b/aiart/1"
        self.add_image(self.seed_path, 1, 1, source, "https://ac.namu.la/actual.png")
        self.add_image(self.db_path, 1, 1, source, "https://ac.namu.la/actual.png")
        name = "a" * 64 + ".png"
        path = self.make_archive([(1, 1, name, b"image")])
        with (
            patch.object(archive_module, "LEGACY_ARCHIVES", (self.legacy_spec(path),)),
            patch.object(archive_module, "_legacy_image_keys", return_value={}),
        ):
            with self.assertRaises(ArcaImageArchiveError):
                install_image_archive(path, self.db_path, self.image_dir, self.seed_path)
        self.assertFalse((self.image_dir / name).exists())
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertFalse(connection.execute("SELECT image_path FROM arca_style_images").fetchone()[0])

    def test_legacy_upload_uses_selected_size_through_append_finish_and_resume(self):
        spec = {"bytes": 9, "sha256": "0" * 64, "image_count": 1, "image_bytes": 5}
        with (
            patch.object(archive_module, "ARCHIVE_BYTES", 6),
            patch.object(archive_module, "LEGACY_ARCHIVES", (spec,)),
            patch.object(archive_module, "_check_free_space"),
            patch.object(archive_module, "_start_archive_job", return_value=42) as start_job,
        ):
            upload = start_local_upload(self.root, "renamed legacy.ZIP", 9)
            token = upload["upload_id"]
            first = append_local_upload(token, 0, io.BytesIO(b"abcdef"), 6)
            second = append_local_upload(token, 6, io.BytesIO(b"ghi"), 3)
            self.assertEqual(first["total_bytes"], 9)
            self.assertEqual(second, {"uploaded_bytes": 9, "total_bytes": 9})
            with self.assertRaises(ArcaImageArchiveError):
                append_local_upload(token, 9, io.BytesIO(b"j"), 1)
            self.assertEqual(archive_module.finish_local_upload(
                self.db_path, self.image_dir, self.root, self.seed_path, token,
            ), 42)
            final_path = start_job.call_args.args[-1]
            self.assertEqual(final_path.read_bytes(), b"abcdefghi")
            job = {"request_json": json.dumps({"mode": "local_upload", "archive_path": str(final_path)})}
            self.assertEqual(archive_module.resume_archive_job(
                self.db_path, self.image_dir, self.root, self.seed_path, job,
            ), 42)
            self.assertEqual(start_job.call_count, 2)

    def test_incomplete_legacy_upload_cannot_start_an_install(self):
        spec = {"bytes": 9, "sha256": "0" * 64, "image_count": 1, "image_bytes": 5}
        with (
            patch.object(archive_module, "LEGACY_ARCHIVES", (spec,)),
            patch.object(archive_module, "_check_free_space"),
            patch.object(archive_module, "_start_archive_job") as start_job,
        ):
            upload = start_local_upload(self.root, "legacy.zip", 9)
            append_local_upload(upload["upload_id"], 0, io.BytesIO(b"abc"), 3)
            with self.assertRaises(ArcaImageArchiveError):
                archive_module.finish_local_upload(
                    self.db_path, self.image_dir, self.root, self.seed_path, upload["upload_id"],
                )
            start_job.assert_not_called()

    def test_unknown_zip_size_and_non_zip_extension_are_rejected_before_upload(self):
        for name, size in (("unknown.zip", 123), ("images.txt", archive_module.ARCHIVE_BYTES)):
            with self.subTest(name=name), self.assertRaises(ArcaImageArchiveError):
                start_local_upload(self.root, name, size)
        self.assertFalse(list(self.root.glob("shared_images_upload_*")))

    def test_completed_legacy_job_reports_its_own_image_count(self):
        path = self.root / "legacy.zip"
        path.write_bytes(b"fixture")
        job_id = archive_module._create_archive_job(self.db_path, "local", path)
        with (
            patch.object(archive_module, "install_image_archive", return_value={
                "installed": 1, "reused": 1, "updated_rows": 2, "skipped_rows": 1,
            }),
            patch.object(archive_module, "_missing_seed_images", return_value=0),
        ):
            archive_module._run_archive_job(
                self.db_path, self.image_dir, self.root, self.seed_path, job_id, "local", path,
            )
        job = get_collection_job(self.db_path, job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["total_posts"], 3)
        self.assertEqual(job["scanned_posts"], 3)
        self.assertEqual(job["downloaded_images"], 2)
        self.assertTrue(path.exists())

    def test_download_tls_context_ignores_missing_optional_keylog_path(self):
        keylog = str(self.root / "missing-debug-directory" / "keys.log")
        with patch.dict(os.environ, {"SSLKEYLOGFILE": keylog}):
            adapter = archive_module._ArchiveHTTPSAdapter()
            try:
                context = adapter.poolmanager.connection_pool_kw["ssl_context"]
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)
                self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
                self.assertIsNone(context.keylog_filename)
                self.assertEqual(os.environ["SSLKEYLOGFILE"], keylog)
                self.assertFalse(Path(keylog).parent.exists())
            finally:
                adapter.close()

    def test_http_and_https_proxy_pools_keep_verified_download_context(self):
        adapter = archive_module._ArchiveHTTPSAdapter()
        try:
            context = adapter.poolmanager.connection_pool_kw["ssl_context"]
            for proxy in ("http://proxy.invalid:8080", "https://proxy.invalid:8443"):
                with self.subTest(proxy=proxy):
                    manager = adapter.proxy_manager_for(proxy)
                    self.assertIs(manager.connection_pool_kw["ssl_context"], context)
                    if proxy.startswith("https:"):
                        self.assertIs(manager.proxy_ssl_context, context)
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
        finally:
            adapter.close()

    def test_download_tls_connection_loads_ca_without_recreating_default_context(self):
        adapter = archive_module._ArchiveHTTPSAdapter()
        try:
            pool = adapter.poolmanager.connection_from_url("https://example.invalid/")
            adapter.cert_verify(pool, "https://example.invalid/", True, None)
            connection = pool._new_conn()
            context = adapter.poolmanager.connection_pool_kw["ssl_context"]
            with (
                patch.object(connection, "_new_conn", return_value=MagicMock()),
                patch("urllib3.connection.create_urllib3_context", side_effect=AssertionError("Default TLS context must not be recreated")),
                patch("urllib3.util.ssl_._ssl_wrap_socket_impl", return_value=MagicMock()) as wrap_socket,
            ):
                connection.connect()
            self.assertIs(connection.ssl_context, context)
            self.assertTrue(connection.is_verified)
            self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            wrap_socket.assert_called_once()
            connection.close()
        finally:
            adapter.close()

    def test_internal_download_session_mounts_tls_adapter_and_closes_after_error(self):
        session = MagicMock()
        session.get.side_effect = archive_module.requests.ConnectionError("fixture network failure")
        with (
            patch.object(archive_module.requests, "Session", return_value=session),
            patch.object(archive_module, "_check_free_space"),
        ):
            with self.assertRaises(archive_module.requests.ConnectionError):
                download_google_archive(self.root / "download.partial")
        session.mount.assert_called_once()
        scheme, adapter = session.mount.call_args.args
        self.assertEqual(scheme, "https://")
        self.assertIsInstance(adapter, archive_module._ArchiveHTTPSAdapter)
        self.assertEqual(adapter._ssl_context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(adapter._ssl_context.check_hostname)
        session.close.assert_called_once()
        adapter.close()


if __name__ == "__main__":
    unittest.main()
