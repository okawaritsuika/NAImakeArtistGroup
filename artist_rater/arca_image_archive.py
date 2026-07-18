import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import RLock, Thread

import requests

from arca_style_collector import (
    ArcaCollectionStopped,
    ArcaCollectorError,
    _image_identity,
    _register_collection_control,
    _remove_collection_control,
    _wait_for_collection_control,
    init_arca_style_tables,
    update_collection_job,
)


DRIVE_FILE_ID = "1JdTHVsu7a99TB2NulAu0TxZhYlsJa5Fs"
ARCHIVE_FILENAME = "NAImakeArtistGroup_shared_images_v0.1.0.zip"
ARCHIVE_DOWNLOAD_URL = (
    f"https://drive.usercontent.google.com/download?id={DRIVE_FILE_ID}"
    "&export=download&confirm=t"
)
ARCHIVE_BYTES = 3_328_615_720
ARCHIVE_SHA256 = "a0e11b9ea5e6b07f8efd789eb5e78c4b4addfea318e4d1d692c0eeff26a5e4f6"
ARCHIVE_IMAGE_COUNT = 1_687
ARCHIVE_IMAGE_BYTES = 3_327_765_422
ARCHIVE_FORMAT = "naimakeartistgroup-shared-images"
DOWNLOAD_CHUNK_BYTES = 4 * 1024 * 1024
LOCAL_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
INSTALL_FREE_SPACE_MARGIN = 256 * 1024 * 1024
IMAGE_NAME = re.compile(r"^[0-9a-f]{64}\.png$")
SHA256_TEXT = re.compile(r"^[0-9a-f]{64}$")
_UPLOAD_LOCK = RLock()
_LOCAL_UPLOADS = {}


class ArcaImageArchiveError(ArcaCollectorError):
    pass


def _connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _archive_path(data_dir, suffix=".partial"):
    return Path(data_dir) / f"{ARCHIVE_FILENAME}{suffix}"


def _check_free_space(data_dir, archive_remaining):
    required = max(0, int(archive_remaining)) + ARCHIVE_IMAGE_BYTES + INSTALL_FREE_SPACE_MARGIN
    free = shutil.disk_usage(Path(data_dir)).free
    if free < required:
        raise ArcaImageArchiveError(
            f"압축 파일과 이미지 설치에 필요한 여유 공간이 부족합니다. "
            f"최소 {required / (1024 ** 3):.1f} GB가 필요합니다."
        )


def _create_archive_job(db_path, mode, archive_path):
    init_arca_style_tables(db_path)
    now = datetime.now().isoformat(timespec="seconds")
    request_json = json.dumps(
        {"mode": mode, "archive_path": str(Path(archive_path).resolve())},
        ensure_ascii=False,
    )
    with closing(_connect(db_path)) as connection, connection:
        return connection.execute(
            "INSERT INTO arca_collection_jobs("
            "request_json,job_type,status,stage,total_pages,total_posts,estimated_bytes,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                request_json, "image_archive", "queued", "queued", 0,
                ARCHIVE_IMAGE_COUNT, ARCHIVE_BYTES, now, now,
            ),
        ).lastrowid


def _drive_response(session, offset):
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    response = session.get(
        ARCHIVE_DOWNLOAD_URL,
        headers=headers,
        stream=True,
        timeout=(20, 60),
    )
    if response.status_code not in ({206} if offset else {200, 206}):
        response.close()
        raise ArcaImageArchiveError(f"Google Drive 다운로드 응답이 올바르지 않습니다. HTTP {response.status_code}")
    content_type = response.headers.get("Content-Type", "").lower()
    if "text/html" in content_type:
        response.close()
        raise ArcaImageArchiveError("Google Drive가 ZIP 대신 확인 페이지를 반환했습니다.")
    if offset:
        content_range = response.headers.get("Content-Range", "")
        if not content_range.startswith(f"bytes {offset}-") or not content_range.endswith(f"/{ARCHIVE_BYTES}"):
            response.close()
            raise ArcaImageArchiveError("Google Drive 이어받기 범위를 확인하지 못했습니다.")
    return response


def download_google_archive(target, progress=None, control=None, session=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.stat().st_size if target.exists() else 0
    if existing > ARCHIVE_BYTES:
        target.unlink()
        existing = 0
    _check_free_space(target.parent, ARCHIVE_BYTES - existing)
    if existing == ARCHIVE_BYTES:
        if progress:
            progress(existing, ARCHIVE_BYTES)
        return target
    own_session = session is None
    session = session or requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
    })
    try:
        response = _drive_response(session, existing)
        try:
            mode = "ab" if existing else "wb"
            downloaded = existing
            with target.open(mode) as handle:
                for chunk in response.iter_content(DOWNLOAD_CHUNK_BYTES):
                    if control:
                        control()
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > ARCHIVE_BYTES:
                        raise ArcaImageArchiveError("다운로드한 ZIP 크기가 예상보다 큽니다.")
                    if progress:
                        progress(downloaded, ARCHIVE_BYTES)
        finally:
            response.close()
    finally:
        if own_session:
            session.close()
    if target.stat().st_size != ARCHIVE_BYTES:
        raise ArcaImageArchiveError("Google Drive 다운로드가 끝까지 완료되지 않았습니다. 다시 누르면 이어받습니다.")
    return target


def _sha256_file(path, progress=None, control=None):
    digest = hashlib.sha256()
    processed = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            if control:
                control()
            digest.update(chunk)
            processed += len(chunk)
            if progress:
                progress(processed, Path(path).stat().st_size)
    return digest.hexdigest()


def _validated_manifest(archive, expected_count=ARCHIVE_IMAGE_COUNT, expected_bytes=ARCHIVE_IMAGE_BYTES):
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArcaImageArchiveError("ZIP의 manifest.json을 읽지 못했습니다.") from exc
    if manifest.get("format") != ARCHIVE_FORMAT or manifest.get("version") != 1:
        raise ArcaImageArchiveError("지원하지 않는 공유 그림체 ZIP 형식입니다.")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != expected_count:
        raise ArcaImageArchiveError("ZIP의 이미지 파일 수가 예상과 다릅니다.")
    if any(not isinstance(item, dict) for item in files):
        raise ArcaImageArchiveError("ZIP 매니페스트의 이미지 항목이 올바르지 않습니다.")
    if manifest.get("file_count") != expected_count or manifest.get("total_bytes") != expected_bytes:
        raise ArcaImageArchiveError("ZIP 매니페스트의 용량 정보가 예상과 다릅니다.")
    file_infos = [info for info in archive.infolist() if not info.is_dir()]
    infos = {info.filename: info for info in file_infos}
    if len(infos) != len(file_infos):
        raise ArcaImageArchiveError("ZIP에 중복된 파일 항목이 있습니다.")
    if set(infos) != {"manifest.json"} | {f"arca_style_images/{item.get('name', '')}" for item in files}:
        raise ArcaImageArchiveError("ZIP에 허용되지 않은 파일 또는 누락된 파일이 있습니다.")
    seen = set()
    total = 0
    for item in files:
        name = item.get("name")
        digest = item.get("sha256")
        if not isinstance(name, str) or not IMAGE_NAME.fullmatch(name) or name in seen:
            raise ArcaImageArchiveError("ZIP 이미지 파일명이 올바르지 않습니다.")
        if not isinstance(digest, str) or not SHA256_TEXT.fullmatch(digest):
            raise ArcaImageArchiveError("ZIP 이미지 해시가 올바르지 않습니다.")
        if type(item.get("image_id")) is not int or type(item.get("item_id")) is not int:
            raise ArcaImageArchiveError("ZIP 이미지 식별자가 올바르지 않습니다.")
        info = infos[f"arca_style_images/{name}"]
        if info.flag_bits & 0x1 or info.file_size != item.get("bytes") or info.file_size > 32 * 1024 * 1024:
            raise ArcaImageArchiveError("ZIP 이미지 크기 또는 암호화 상태가 올바르지 않습니다.")
        seen.add(name)
        total += info.file_size
    if total != expected_bytes:
        raise ArcaImageArchiveError("ZIP 이미지 전체 용량이 예상과 다릅니다.")
    return files


def _matching_database_rows(db_path, seed_db_path, manifest_files):
    """Resolve archive entries through stable seed metadata, never local row ids."""
    seed_path = Path(seed_db_path)
    if not seed_path.is_file():
        raise ArcaImageArchiveError("공유 그림체 ZIP 연결용 기본 DB를 찾지 못했습니다.")
    manifest_ids = {item["image_id"] for item in manifest_files}
    with closing(_connect(seed_path)) as seed:
        seed_rows = seed.execute(
            "SELECT image.id,image.item_id,image.image_url,item.source_url "
            "FROM arca_style_images image "
            "JOIN arca_style_items item ON item.id=image.item_id",
        ).fetchall()
    seed_by_id = {row["id"]: dict(row) for row in seed_rows if row["id"] in manifest_ids}
    archive_keys = {}
    for entry in manifest_files:
        seed_row = seed_by_id.get(entry["image_id"])
        expected_name = (
            hashlib.sha256(seed_row["image_url"].encode()).hexdigest() + ".png"
            if seed_row else ""
        )
        if (
            not seed_row
            or seed_row["item_id"] != entry["item_id"]
            or expected_name != entry["name"]
        ):
            raise ArcaImageArchiveError("공유 그림체 ZIP과 기본 DB의 이미지 연결 정보가 일치하지 않습니다.")
        key = (seed_row["source_url"], _image_identity(seed_row["image_url"]))
        if key in archive_keys:
            raise ArcaImageArchiveError("공유 그림체 ZIP의 안정 이미지 식별자가 중복됩니다.")
        archive_keys[key] = entry["name"]

    with closing(_connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT image.id,image.item_id,image.image_url,image.image_path,item.source_url "
            "FROM arca_style_images image "
            "JOIN arca_style_items item ON item.id=image.item_id "
            "WHERE image.metadata_status='ok'",
        ).fetchall()
    exact_rows = {(row["source_url"], row["image_url"]): dict(row) for row in rows}
    stable_rows = {}
    for row in rows:
        key = (row["source_url"], _image_identity(row["image_url"]))
        stable_rows.setdefault(key, dict(row))

    result = {}
    for entry in manifest_files:
        seed_row = seed_by_id[entry["image_id"]]
        stable_key = (seed_row["source_url"], _image_identity(seed_row["image_url"]))
        row = exact_rows.get((seed_row["source_url"], seed_row["image_url"])) or stable_rows.get(stable_key)
        if row:
            result[entry["name"]] = row
    return result


def install_image_archive(
    archive_path,
    db_path,
    image_dir,
    seed_db_path,
    progress=None,
    control=None,
    expected_archive_sha256=ARCHIVE_SHA256,
    expected_archive_bytes=ARCHIVE_BYTES,
    expected_count=ARCHIVE_IMAGE_COUNT,
    expected_bytes=ARCHIVE_IMAGE_BYTES,
):
    archive_path = Path(archive_path)
    if not archive_path.is_file() or archive_path.stat().st_size != expected_archive_bytes:
        raise ArcaImageArchiveError("공유 그림체 ZIP의 파일 크기가 예상과 다릅니다.")
    digest = _sha256_file(archive_path, control=control)
    if digest != expected_archive_sha256:
        raise ArcaImageArchiveError("공유 그림체 ZIP의 SHA-256이 일치하지 않습니다.")
    image_dir = Path(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        manifest_files = _validated_manifest(archive, expected_count, expected_bytes)
        database_rows = _matching_database_rows(db_path, seed_db_path, manifest_files)
        installed = reused = processed = 0
        started = time.monotonic()
        updates = []
        for item in manifest_files:
            if control:
                control()
            row = database_rows.get(item["name"])
            if not row:
                processed += 1
                if progress:
                    progress(processed, expected_count, installed, reused, time.monotonic() - started)
                continue
            target = image_dir / item["name"]
            valid_existing = (
                target.is_file()
                and target.stat().st_size == item["bytes"]
                and _sha256_file(target, control=control) == item["sha256"]
            )
            if valid_existing:
                reused += 1
            else:
                temporary = target.with_suffix(target.suffix + ".partial")
                digest = hashlib.sha256()
                try:
                    with archive.open(f"arca_style_images/{item['name']}") as source, temporary.open("wb") as output:
                        for chunk in iter(lambda: source.read(DOWNLOAD_CHUNK_BYTES), b""):
                            if control:
                                control()
                            output.write(chunk)
                            digest.update(chunk)
                    if temporary.stat().st_size != item["bytes"] or digest.hexdigest() != item["sha256"]:
                        raise ArcaImageArchiveError(f"압축 해제한 이미지 검증에 실패했습니다: {item['name']}")
                    os.replace(temporary, target)
                finally:
                    if temporary.exists():
                        temporary.unlink()
                installed += 1
            updates.append((item["name"], row["id"], row["item_id"]))
            processed += 1
            if progress:
                progress(processed, expected_count, installed, reused, time.monotonic() - started)
    with closing(_connect(db_path)) as connection, connection:
        connection.executemany(
            "UPDATE arca_style_images SET image_path=? WHERE id=? AND item_id=?",
            updates,
        )
        item_ids = sorted({item_id for _, _, item_id in updates})
        for item_id in item_ids:
            item = connection.execute(
                "SELECT representative_image_url FROM arca_style_items WHERE id=?",
                (item_id,),
            ).fetchone()
            images = connection.execute(
                "SELECT image_url,image_path FROM arca_style_images WHERE item_id=? AND TRIM(COALESCE(image_path,''))<>''",
                (item_id,),
            ).fetchall()
            representative = next(
                (row["image_path"] for row in images if _image_identity(row["image_url"]) == _image_identity(item[0])),
                "",
            ) if item and item[0] else ""
            if representative:
                connection.execute(
                    "UPDATE arca_style_items SET representative_image_path=? WHERE id=?",
                    (representative, item_id),
                )
    return {
        "installed": installed,
        "reused": reused,
        "updated_rows": len(updates),
        "skipped_rows": expected_count - len(updates),
    }


def _run_archive_job(db_path, image_dir, data_dir, seed_db_path, job_id, mode, archive_path):
    last_download_update = [0.0]

    def control(stage):
        _wait_for_collection_control(db_path, job_id, stage)

    def download_progress(done, total):
        now = time.monotonic()
        if done == total or now - last_download_update[0] >= 0.5:
            update_collection_job(
                db_path, job_id, stage="downloading_archive", downloaded_bytes=done,
            )
            last_download_update[0] = now

    try:
        update_collection_job(db_path, job_id, status="running", stage="downloading_archive")
        if mode == "google_drive":
            download_google_archive(
                archive_path,
                progress=download_progress,
                control=lambda: control("downloading_archive"),
            )
        else:
            update_collection_job(db_path, job_id, downloaded_bytes=ARCHIVE_BYTES)
        update_collection_job(db_path, job_id, stage="verifying_archive")

        def install_progress(processed, total, installed, reused, elapsed):
            update_collection_job(
                db_path, job_id, stage="extracting_archive", total_posts=total,
                scanned_posts=processed, downloaded_images=installed + reused,
                updated=installed, average_post_seconds=(elapsed / processed if processed else None),
            )

        result = install_image_archive(
            archive_path,
            db_path,
            image_dir,
            seed_db_path,
            progress=install_progress,
            control=lambda: control("extracting_archive"),
        )
        update_collection_job(
            db_path, job_id, status="completed", stage="completed",
            scanned_posts=ARCHIVE_IMAGE_COUNT,
            downloaded_images=result["updated_rows"], updated=result["installed"], error="",
        )
        Path(archive_path).unlink(missing_ok=True)
    except ArcaCollectionStopped as exc:
        update_collection_job(db_path, job_id, status="stopped", stage="stopped", error=str(exc))
    except Exception as exc:
        if Path(archive_path).is_file() and Path(archive_path).stat().st_size == ARCHIVE_BYTES:
            try:
                if _sha256_file(archive_path) != ARCHIVE_SHA256:
                    Path(archive_path).unlink()
            except OSError:
                pass
        update_collection_job(db_path, job_id, status="failed", stage="failed", error=str(exc)[:1000])
    finally:
        _remove_collection_control(job_id)


def _start_archive_job(db_path, image_dir, data_dir, seed_db_path, mode, archive_path):
    job_id = _create_archive_job(db_path, mode, archive_path)
    _register_collection_control(job_id)
    Thread(
        target=_run_archive_job,
        args=(db_path, image_dir, data_dir, seed_db_path, job_id, mode, archive_path),
        daemon=True,
    ).start()
    return job_id


def start_google_archive_job(db_path, image_dir, data_dir, seed_db_path):
    archive_path = _archive_path(data_dir)
    return _start_archive_job(db_path, image_dir, data_dir, seed_db_path, "google_drive", archive_path)


def start_local_archive_job(db_path, image_dir, data_dir, seed_db_path, archive_path):
    return _start_archive_job(db_path, image_dir, data_dir, seed_db_path, "local_upload", archive_path)


def resume_archive_job(db_path, image_dir, data_dir, seed_db_path, job):
    try:
        payload = json.loads(job.get("request_json") or "{}")
    except json.JSONDecodeError as exc:
        raise ArcaImageArchiveError("이전 ZIP 작업 정보를 읽지 못했습니다.") from exc
    if payload.get("mode") == "google_drive":
        return start_google_archive_job(db_path, image_dir, data_dir, seed_db_path)
    if payload.get("mode") == "local_upload":
        archive_path = Path(payload.get("archive_path", "")).resolve()
        data_root = Path(data_dir).resolve()
        if archive_path.parent != data_root or not archive_path.name.startswith("shared_images_upload_"):
            raise ArcaImageArchiveError("이전 로컬 ZIP 경로가 올바르지 않습니다.")
        if not archive_path.is_file() or archive_path.stat().st_size != ARCHIVE_BYTES:
            raise ArcaImageArchiveError("이전 로컬 ZIP을 찾지 못했습니다. 다시 선택해 주세요.")
        return start_local_archive_job(db_path, image_dir, data_dir, seed_db_path, archive_path)
    raise ArcaImageArchiveError("이전 ZIP 작업 방식을 확인하지 못했습니다.")


def start_local_upload(data_dir, filename, size):
    if Path(str(filename or "")).suffix.lower() != ".zip" or int(size or 0) != ARCHIVE_BYTES:
        raise ArcaImageArchiveError("선택한 ZIP의 파일명 또는 크기가 배포 파일과 다릅니다.")
    _check_free_space(data_dir, ARCHIVE_BYTES)
    token = uuid.uuid4().hex
    path = Path(data_dir) / f"shared_images_upload_{token}.zip.partial"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    with _UPLOAD_LOCK:
        _LOCAL_UPLOADS[token] = path
    return {"upload_id": token, "chunk_bytes": LOCAL_UPLOAD_CHUNK_BYTES, "uploaded_bytes": 0}


def discard_local_upload(upload_id):
    with _UPLOAD_LOCK:
        path = _LOCAL_UPLOADS.pop(upload_id, None)
    if path is not None:
        path.unlink(missing_ok=True)


def append_local_upload(upload_id, offset, stream, content_length):
    if not isinstance(upload_id, str) or not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise ArcaImageArchiveError("로컬 ZIP 업로드 식별자가 올바르지 않습니다.")
    with _UPLOAD_LOCK:
        path = _LOCAL_UPLOADS.get(upload_id)
    if path is None or not path.is_file():
        raise ArcaImageArchiveError("로컬 ZIP 업로드 작업을 찾지 못했습니다.")
    if type(offset) is not int or offset != path.stat().st_size:
        raise ArcaImageArchiveError("로컬 ZIP 업로드 위치가 일치하지 않습니다.")
    if content_length is None or not 0 < content_length <= LOCAL_UPLOAD_CHUNK_BYTES:
        raise ArcaImageArchiveError("로컬 ZIP 조각 크기가 올바르지 않습니다.")
    if offset + content_length > ARCHIVE_BYTES:
        raise ArcaImageArchiveError("로컬 ZIP 크기가 예상보다 큽니다.")
    remaining = content_length
    with path.open("ab") as handle:
        while remaining:
            chunk = stream.read(min(DOWNLOAD_CHUNK_BYTES, remaining))
            if not chunk:
                raise ArcaImageArchiveError("로컬 ZIP 조각이 중간에 끊겼습니다.")
            handle.write(chunk)
            remaining -= len(chunk)
    return {"uploaded_bytes": path.stat().st_size, "total_bytes": ARCHIVE_BYTES}


def finish_local_upload(db_path, image_dir, data_dir, seed_db_path, upload_id):
    with _UPLOAD_LOCK:
        path = _LOCAL_UPLOADS.pop(upload_id, None)
    if path is None or not path.is_file() or path.stat().st_size != ARCHIVE_BYTES:
        raise ArcaImageArchiveError("로컬 ZIP 업로드가 완료되지 않았습니다.")
    final_path = path.with_suffix("")
    os.replace(path, final_path)
    return start_local_archive_job(db_path, image_dir, data_dir, seed_db_path, final_path)
