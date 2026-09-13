import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
