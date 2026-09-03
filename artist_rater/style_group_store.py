"""Persistent storage for style-group review sessions.

The source images used by a group are deliberately copied into a private
``style_group_images`` directory when accepted.  A group therefore remains
usable even when a rating or a generated-image history row is later removed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from confirmed_style_store import inspect_image
from png_validator import validate_png


MAX_NAME_LENGTH = 200
MAX_IMAGE_BYTES = 32 * 1024 * 1024
SOURCE_TYPES = {"danbooru", "rating_management", "nai_test"}
SOURCE_ALIASES = {
    "rating": "danbooru", "ratings": "danbooru", "danbooru": "danbooru",
    "rating_management": "rating_management", "ratings_management": "rating_management",
    "nai": "nai_test", "test": "nai_test", "nai_test": "nai_test",
}
MODERN_SOURCE_TYPES = {"rating_management", "nai_test"}


def _connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical_source_type(value):
    result = SOURCE_ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())
    if result not in SOURCE_TYPES:
        raise ValueError("source_type must be danbooru or nai_test.")
    return result


def _source_id(value):
    if value in (None, ""):
        raise ValueError("source_id is required.")
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError("source_id must be an integer.") from None
    if value < 1:
        raise ValueError("source_id must be positive.")
    return str(value)


def normalize_artist_tag(value):
    """Return the stable matching key for a Danbooru/NAI artist tag."""
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def _modern_source_type(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"rating", "ratings", "danbooru"}:
        return "rating_management"
    if normalized in {"nai", "test"}:
        return "nai_test"
    if normalized not in MODERN_SOURCE_TYPES:
        raise ValueError("source_type must be rating_management or nai_test.")
    return normalized


def _modern_source_id(source_type, value):
    source_type = _modern_source_type(source_type)
    if source_type == "rating_management":
        return "all"
    return _source_id(value)


def _safe_relative(value):
    normalized = str(value or "").replace("\\", "/")
    path = Path(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or normalized != path.as_posix():
        return ""
    return normalized


def init_style_group_tables(db_path):
    with closing(_connect(db_path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS style_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                reference_image_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS style_group_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL DEFAULT 0,
                cursor INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, source_type, source_id),
                FOREIGN KEY(group_id) REFERENCES style_groups(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS style_group_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                source_id INTEGER NOT NULL,
                candidate_key TEXT NOT NULL,
                included INTEGER NOT NULL CHECK(included IN (0, 1)),
                candidate_position INTEGER NOT NULL DEFAULT 0,
                decided_at TEXT NOT NULL,
                UNIQUE(group_id, source_id, candidate_key),
                FOREIGN KEY(group_id) REFERENCES style_groups(id) ON DELETE CASCADE,
                FOREIGN KEY(source_id) REFERENCES style_group_sources(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS style_group_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL DEFAULT '',
                candidate_key TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL,
                original_name TEXT NOT NULL DEFAULT '',
                width INTEGER,
                height INTEGER,
                sha256 TEXT NOT NULL,
                is_reference INTEGER NOT NULL DEFAULT 0 CHECK(is_reference IN (0, 1)),
                created_at TEXT NOT NULL,
                UNIQUE(group_id, sha256),
                FOREIGN KEY(group_id) REFERENCES style_groups(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_style_group_sources_order
                ON style_group_sources(group_id, position, id);
            CREATE INDEX IF NOT EXISTS idx_style_group_decisions_source
                ON style_group_decisions(group_id, source_id, candidate_position);
            CREATE INDEX IF NOT EXISTS idx_style_group_images_group
                ON style_group_images(group_id, is_reference DESC, created_at, id);
            """
        )
        # The first version of this feature classified individual images.
        # Keep those rows intact and add the author-centered state alongside
        # them so an already-used database upgrades without a destructive
        # migration.
        group_columns = {row[1] for row in connection.execute("PRAGMA table_info(style_groups)")}
        for column, declaration in (
            ("base_source_type", "TEXT NOT NULL DEFAULT ''"),
            ("base_source_id", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in group_columns:
                connection.execute(f"ALTER TABLE style_groups ADD COLUMN {column} {declaration}")
        image_columns = {row[1] for row in connection.execute("PRAGMA table_info(style_group_images)")}
        if "artist_key" not in image_columns:
            connection.execute("ALTER TABLE style_group_images ADD COLUMN artist_key TEXT NOT NULL DEFAULT ''")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS style_group_schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS style_group_artists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                artist_key TEXT NOT NULL,
                artist_tag TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'included'
                    CHECK(decision IN ('pending','included','excluded')),
                direct INTEGER NOT NULL DEFAULT 0 CHECK(direct IN (0, 1)),
                decision_source_type TEXT NOT NULL DEFAULT '',
                decision_source_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(group_id, artist_key),
                FOREIGN KEY(group_id) REFERENCES style_groups(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_style_group_artists_queue
                ON style_group_artists(group_id, decision, artist_key);
            CREATE TABLE IF NOT EXISTS style_group_image_artists (
                image_id INTEGER NOT NULL,
                artist_key TEXT NOT NULL,
                PRIMARY KEY(image_id, artist_key),
                FOREIGN KEY(image_id) REFERENCES style_group_images(id) ON DELETE CASCADE
            );
            """
        )
        _migrate_legacy_artist_decisions(connection)


def _validate_name(name):
    value = str(name or "").strip()
    if not value:
        raise ValueError("그림체 그룹 이름을 입력해 주세요.")
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError("그림체 그룹 이름이 너무 깁니다.")
    return value


def _validate_bytes(image_bytes):
    if not isinstance(image_bytes, bytes) or not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("이미지는 1바이트 이상 32MB 이하만 저장할 수 있습니다.")
    try:
        info = inspect_image(image_bytes)
    except ValueError:
        raise
    # Keep the same decompression safety boundary for non-PNG files too.
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except (OSError, ValueError):
        raise ValueError("PNG, JPEG, WebP 이미지만 사용할 수 있습니다.") from None
    if info["content_type"] == "image/png":
        validate_png(image_bytes)
    return info


def _write_copy(image_dir, group_id, image_bytes, suffix, digest=None):
    root = Path(image_dir).resolve()
    group_root = (root / str(int(group_id))).resolve()
    if root not in group_root.parents:
        raise ValueError("Invalid style group image directory.")
    group_root.mkdir(parents=True, exist_ok=True)
    digest = digest or hashlib.sha256(image_bytes).hexdigest()
    suffix = suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    filename = f"{digest}{suffix}"
    target = (group_root / filename).resolve()
    if group_root not in target.parents:
        raise ValueError("Invalid style group image path.")
    if not target.is_file():
        target.write_bytes(image_bytes)
    return target.relative_to(root).as_posix()


def _decode_image(row):
    item = dict(row)
    item["is_reference"] = bool(item.get("is_reference"))
    item["image_url"] = f"/style-group-images/{item['image_path']}" if item.get("image_path") else ""
    return item


def _decode_source(row):
    item = dict(row)
    item["position"] = int(item.get("position") or 0)
    item["cursor"] = int(item.get("cursor") or 0)
    return item


def _group_payload(connection, group_id, source_roots=None):
    row = connection.execute("SELECT * FROM style_groups WHERE id=?", (group_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    images = connection.execute(
        "SELECT * FROM style_group_images WHERE group_id=? ORDER BY is_reference DESC, created_at, id",
        (group_id,),
    ).fetchall()
    image_artist_keys = {}
    try:
        for link in connection.execute(
            "SELECT image_id,artist_key FROM style_group_image_artists WHERE image_id IN ({})".format(
                ",".join("?" for _ in images) or "NULL"
            ),
            [image["id"] for image in images],
        ).fetchall():
            image_artist_keys.setdefault(link["image_id"], []).append(link["artist_key"])
    except sqlite3.OperationalError:
        pass
    sources = connection.execute(
        "SELECT * FROM style_group_sources WHERE group_id=? ORDER BY position, id", (group_id,)
    ).fetchall()
    item["images"] = []
    for image in images:
        decoded = _decode_image(image)
        decoded["artist_keys"] = image_artist_keys.get(image["id"], [])
        item["images"].append(decoded)
    item["sources"] = [_decode_source(source) for source in sources]
    item["image_count"] = len(images)
    item["source_count"] = len(sources)
    item["reference_image_url"] = (
        f"/style-group-images/{item['reference_image_path']}" if item.get("reference_image_path") else ""
    )
    try:
        item["base_source"] = {
            "source_type": item.get("base_source_type") or "",
            "source_id": item.get("base_source_id") or "",
        }
        artist_rows = connection.execute(
            """SELECT * FROM style_group_artists
               WHERE group_id=? ORDER BY decision='excluded', artist_tag COLLATE NOCASE, id""",
            (group_id,),
        ).fetchall()
        item["artists"] = [dict(row) for row in artist_rows]
        item["included_artists"] = [dict(row) for row in artist_rows if row["decision"] == "included"]
        item["excluded_artists"] = [dict(row) for row in artist_rows if row["decision"] == "excluded"]
        item["artist_count"] = len(item["included_artists"])
        item["unreviewed_count"] = 0
        base_type = item.get("base_source_type") or ""
        base_id = item.get("base_source_id") or ""
        if base_type in MODERN_SOURCE_TYPES and base_id:
            try:
                roots = source_roots or {}
                base_rows = _source_rows(connection, base_type, base_id)
                if roots:
                    base_rows = [row for row in base_rows if _source_file(row, roots) is not None]
                else:
                    base_rows = [row for row in base_rows if row.get("image_path")]
                base_artists = {row["artist_key"] for row in base_rows if row.get("artist_key")}
                decided = {row["artist_key"] for row in artist_rows if row["decision"] in {"included", "excluded"}}
                item["unreviewed_count"] = len(base_artists - decided)
            except (NameError, sqlite3.Error, TypeError, ValueError):
                item["unreviewed_count"] = 0
    except sqlite3.OperationalError:
        # A caller opening a legacy database before init_style_group_tables()
        # should still receive the original image-oriented payload.
        item["base_source"] = {"source_type": "", "source_id": ""}
        item["artists"] = []
        item["included_artists"] = []
        item["excluded_artists"] = []
        item["artist_count"] = 0
    return item


def list_groups(db_path):
    roots = _source_roots(db_path)
    with closing(_connect(db_path)) as connection:
        rows = connection.execute("SELECT id FROM style_groups ORDER BY updated_at DESC, id DESC").fetchall()
        return [_group_payload(connection, row[0], roots) for row in rows]


def get_group(db_path, group_id):
    roots = _source_roots(db_path)
    with closing(_connect(db_path)) as connection:
        return _group_payload(connection, int(group_id), roots)


def _insert_sources(connection, group_id, sources):
    inserted = []
    for index, source in enumerate(sources or []):
        if not isinstance(source, dict):
            raise ValueError("sources must contain objects.")
        source_type = _canonical_source_type(source.get("source_type"))
        source_id = (
            "all" if source_type == "rating_management"
            else _source_id(source.get("source_id", source.get("id")))
        )
        label = str(source.get("label") or source.get("name") or "").strip()[:200]
        try:
            position = int(source.get("position", index))
        except (TypeError, ValueError):
            position = index
        if position < 0:
            position = index
        existing = connection.execute(
            "SELECT id FROM style_group_sources WHERE group_id=? AND source_type=? AND source_id=?",
            (group_id, source_type, source_id),
        ).fetchone()
        if existing:
            connection.execute(
                "UPDATE style_group_sources SET label=?, position=?, updated_at=? WHERE id=?",
                (label, position, _now(), existing[0]),
            )
            inserted.append(existing[0])
            continue
        cursor = connection.execute(
            """INSERT INTO style_group_sources
               (group_id,source_type,source_id,label,position,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (group_id, source_type, source_id, label, position, _now(), _now()),
        )
        inserted.append(cursor.lastrowid)
    return inserted


def create_group(db_path, image_dir, name, sources=None, reference_bytes=None, reference_name=""):
    value = _validate_name(name)
    if sources is not None and not isinstance(sources, list):
        raise ValueError("sources must be a list.")
    reference_info = _validate_bytes(reference_bytes) if reference_bytes is not None else None
    with closing(_connect(db_path)) as connection, connection:
        timestamp = _now()
        cursor = connection.execute(
            "INSERT INTO style_groups(name,reference_image_path,created_at,updated_at) VALUES(?,?,?,?)",
            (value, "", timestamp, timestamp),
        )
        group_id = cursor.lastrowid
        if reference_bytes is not None:
            digest = hashlib.sha256(reference_bytes).hexdigest()
            relative = _write_copy(image_dir, group_id, reference_bytes, reference_info["suffix"], digest)
            connection.execute(
                """INSERT INTO style_group_images
                   (group_id,source_type,source_id,candidate_key,image_path,original_name,width,height,sha256,is_reference,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (group_id, "upload", "", f"upload:{digest}", relative, str(reference_name or "")[:200], reference_info["width"], reference_info["height"], digest, 1, timestamp),
            )
            connection.execute("UPDATE style_groups SET reference_image_path=? WHERE id=?", (relative, group_id))
        _insert_sources(connection, group_id, sources or [])
        return _group_payload(connection, group_id)


def add_sources(db_path, group_id, sources):
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        _insert_sources(connection, int(group_id), sources)
        connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (_now(), group_id))
        return _group_payload(connection, int(group_id))


def add_uploaded_image(db_path, image_dir, group_id, image_bytes, original_name=""):
    """Copy an uploaded image into an existing group and make it reference."""
    info = _validate_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        existing = connection.execute("SELECT id FROM style_group_images WHERE group_id=? AND sha256=?", (group_id, digest)).fetchone()
        if existing:
            connection.execute("UPDATE style_group_images SET is_reference=0 WHERE group_id=?", (group_id,))
            connection.execute("UPDATE style_group_images SET is_reference=1 WHERE id=?", (existing[0],))
            row = connection.execute("SELECT image_path FROM style_group_images WHERE id=?", (existing[0],)).fetchone()
            connection.execute("UPDATE style_groups SET reference_image_path=?,updated_at=? WHERE id=?", (row[0], _now(), group_id))
            return _group_payload(connection, int(group_id))
        relative = _write_copy(image_dir, group_id, image_bytes, info["suffix"], digest)
        timestamp = _now()
        connection.execute("UPDATE style_group_images SET is_reference=0 WHERE group_id=?", (group_id,))
        connection.execute(
            """INSERT INTO style_group_images
               (group_id,source_type,source_id,candidate_key,image_path,original_name,width,height,sha256,is_reference,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (group_id, "upload", "", f"upload:{digest}", relative, str(original_name or "")[:200], info["width"], info["height"], digest, 1, timestamp),
        )
        connection.execute("UPDATE style_groups SET reference_image_path=?,updated_at=? WHERE id=?", (relative, timestamp, group_id))
        return _group_payload(connection, int(group_id))


def update_group(db_path, group_id, name=None, reference_image_id=None, clear_reference=False):
    removed_path = None
    result = None
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        if name is not None:
            connection.execute("UPDATE style_groups SET name=?, updated_at=? WHERE id=?", (_validate_name(name), _now(), group_id))
        if clear_reference:
            old_reference = connection.execute(
                "SELECT id FROM style_group_images WHERE group_id=? AND is_reference=1 LIMIT 1", (group_id,)
            ).fetchone()
            connection.execute("UPDATE style_group_images SET is_reference=0 WHERE group_id=?", (group_id,))
            connection.execute("UPDATE style_groups SET reference_image_path='', updated_at=? WHERE id=?", (_now(), group_id))
            if old_reference is not None:
                removed_path = _remove_reference_only_image(connection, group_id, old_reference[0])
        elif reference_image_id is not None:
            image = connection.execute("SELECT image_path FROM style_group_images WHERE id=? AND group_id=?", (reference_image_id, group_id)).fetchone()
            if image is None:
                raise ValueError("그룹에 포함된 이미지만 기준 이미지로 지정할 수 있습니다.")
            connection.execute("UPDATE style_group_images SET is_reference=0 WHERE group_id=?", (group_id,))
            connection.execute("UPDATE style_group_images SET is_reference=1 WHERE id=?", (reference_image_id,))
            connection.execute("UPDATE style_groups SET reference_image_path=?, updated_at=? WHERE id=?", (image[0], _now(), group_id))
        result = _group_payload(connection, int(group_id))
    if removed_path:
        root = Path(db_path).resolve().parent / "style_group_images"
        target = (root / _safe_relative(removed_path)).resolve()
        if root.resolve() in target.parents and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    return result


def _source_row(connection, group_id, source_id):
    return connection.execute("SELECT * FROM style_group_sources WHERE id=? AND group_id=?", (source_id, group_id)).fetchone()


def _candidate_rows(connection, source):
    source_type, source_id = source["source_type"], source["source_id"]
    if source_type == "danbooru":
        rating = connection.execute("SELECT id,artist_tag,representative_thumbnail_path FROM ratings WHERE id=?", (source_id,)).fetchone()
        if rating is None:
            return []
        rows = []
        if rating["representative_thumbnail_path"]:
            rows.append({"candidate_key": f"thumbnail:{rating['representative_thumbnail_path']}", "image_path": rating["representative_thumbnail_path"], "source_root": "thumbnails", "label": rating["artist_tag"]})
        examples = connection.execute("SELECT id,image_path,post_id FROM rating_examples WHERE rating_id=? ORDER BY id", (source_id,)).fetchall()
        seen = {item["image_path"] for item in rows}
        for example in examples:
            if example["image_path"] in seen:
                continue
            seen.add(example["image_path"])
            rows.append({"candidate_key": f"example:{example['id']}", "image_path": example["image_path"], "source_root": "thumbnails", "label": rating["artist_tag"], "post_id": example["post_id"]})
        return rows
    if source_type == "nai_test":
        rows = connection.execute(
            """SELECT i.id,g.image_path,i.artist_tag,i.ordinal
               FROM nai_artist_test_items i JOIN generated_images g ON g.id=i.generated_image_id
               WHERE i.test_id=? AND i.status='complete' AND i.generated_image_id IS NOT NULL
               ORDER BY i.ordinal,i.id""",
            (source_id,),
        ).fetchall()
        return [
            {"candidate_key": f"item:{row['id']}", "image_path": row["image_path"], "source_root": "generated", "label": row["artist_tag"], "ordinal": row["ordinal"]}
            for row in rows if row["image_path"]
        ]
    return []


def _candidate_payload(connection, source, candidate, decisions):
    item = dict(candidate)
    item.pop("source_root", None)
    item["source_id"] = source["id"]
    item["source_type"] = source["source_type"]
    item["image_url"] = f"/{'thumbnails' if candidate['source_root'] == 'thumbnails' else 'generated'}/{_safe_relative(candidate['image_path'])}"
    decision = decisions.get(candidate["candidate_key"])
    item["decision"] = None if decision is None else bool(decision)
    item["decided"] = decision is not None
    return item


def _list_candidates_connection(connection, group_id, source_id=None):
    sources = connection.execute("SELECT * FROM style_group_sources WHERE group_id=? ORDER BY position,id", (group_id,)).fetchall()
    result = []
    for source in sources:
        if source_id is not None and int(source["id"]) != int(source_id):
            continue
        candidates = _candidate_rows(connection, source)
        decision_rows = connection.execute("SELECT candidate_key,included FROM style_group_decisions WHERE group_id=? AND source_id=?", (group_id, source["id"])).fetchall()
        decisions = {row["candidate_key"]: int(row["included"]) for row in decision_rows}
        unresolved = [index for index, candidate in enumerate(candidates) if candidate["candidate_key"] not in decisions]
        current_index = unresolved[0] if unresolved else len(candidates)
        payload = _decode_source(source)
        payload["total_count"] = len(candidates)
        payload["decided_count"] = len(decisions)
        payload["included_count"] = sum(1 for value in decisions.values() if value)
        payload["completed"] = not unresolved
        payload["current_index"] = current_index
        payload["candidates"] = [_candidate_payload(connection, source, candidate, decisions) for candidate in candidates]
        payload["current"] = payload["candidates"][current_index] if current_index < len(candidates) else None
        result.append(payload)
    return result


def list_candidates(db_path, group_id, source_id=None):
    with closing(_connect(db_path)) as connection:
        return _list_candidates_connection(connection, group_id, source_id)


def _source_file(candidate, roots):
    root_value = roots.get(candidate["source_root"])
    if not root_value:
        return None
    root = Path(root_value).resolve()
    relative = _safe_relative(candidate.get("image_path"))
    if not relative:
        return None
    target = (root / relative).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


def record_decision(db_path, image_dir, group_id, source_id, candidate_key, include, source_roots):
    if not isinstance(include, bool):
        include = bool(include)
    with closing(_connect(db_path)) as connection, connection:
        source = _source_row(connection, group_id, source_id)
        if source is None:
            return None
        candidates = _candidate_rows(connection, source)
        candidate_position = next((index for index, row in enumerate(candidates) if row["candidate_key"] == candidate_key), None)
        if candidate_position is None:
            raise ValueError("현재 소스에서 찾을 수 없는 후보 이미지입니다.")
        timestamp = _now()
        connection.execute(
            """INSERT INTO style_group_decisions(group_id,source_id,candidate_key,included,candidate_position,decided_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(group_id,source_id,candidate_key) DO UPDATE SET included=excluded.included,candidate_position=excluded.candidate_position,decided_at=excluded.decided_at""",
            (group_id, source_id, candidate_key, 1 if include else 0, candidate_position, timestamp),
        )
        if include:
            source_file = _source_file(candidates[candidate_position], source_roots)
            if source_file is None:
                raise ValueError("원본 이미지 파일을 찾을 수 없습니다.")
            try:
                if source_file.stat().st_size > MAX_IMAGE_BYTES:
                    raise ValueError("원본 이미지가 너무 큽니다.")
            except OSError:
                raise ValueError("원본 이미지 파일을 읽을 수 없습니다.") from None
            image_bytes = source_file.read_bytes()
            info = _validate_bytes(image_bytes)
            digest = hashlib.sha256(image_bytes).hexdigest()
            existing = connection.execute("SELECT id FROM style_group_images WHERE group_id=? AND sha256=?", (group_id, digest)).fetchone()
            if existing is None:
                relative = _write_copy(image_dir, group_id, image_bytes, info["suffix"], digest)
                connection.execute(
                    """INSERT INTO style_group_images
                       (group_id,source_type,source_id,candidate_key,image_path,original_name,width,height,sha256,is_reference,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (group_id, source["source_type"], source["source_id"], candidate_key, relative, source_file.name[:200], info["width"], info["height"], digest, 0, timestamp),
                )
                if connection.execute("SELECT reference_image_path FROM style_groups WHERE id=?", (group_id,)).fetchone()[0] == "":
                    connection.execute("UPDATE style_group_images SET is_reference=1 WHERE group_id=? AND sha256=?", (group_id, digest))
                    connection.execute("UPDATE style_groups SET reference_image_path=? WHERE id=?", (relative, group_id))
        decisions = connection.execute("SELECT candidate_key,included FROM style_group_decisions WHERE group_id=? AND source_id=?", (group_id, source_id)).fetchall()
        decision_map = {row["candidate_key"]: int(row["included"]) for row in decisions}
        unresolved = [index for index, candidate in enumerate(candidates) if candidate["candidate_key"] not in decision_map]
        cursor = unresolved[0] if unresolved else len(candidates)
        status = "completed" if not unresolved else "active"
        connection.execute("UPDATE style_group_sources SET cursor=?,status=?,updated_at=? WHERE id=?", (cursor, status, timestamp, source_id))
        connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (timestamp, group_id))
        payload = _group_payload(connection, int(group_id))
        source_payload = next(item for item in _list_candidates_connection(connection, group_id) if int(item["id"]) == int(source_id))
        payload["source"] = source_payload
        payload["next"] = source_payload.get("current")
        return payload


def remove_image(db_path, image_dir, group_id, image_id):
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute("SELECT * FROM style_group_images WHERE id=? AND group_id=?", (image_id, group_id)).fetchone()
        if row is None:
            return None
        connection.execute("DELETE FROM style_group_images WHERE id=?", (image_id,))
        if row["image_path"]:
            root = Path(image_dir).resolve()
            target = (root / _safe_relative(row["image_path"])).resolve()
            if root in target.parents and target.is_file():
                try:
                    target.unlink()
                except OSError:
                    pass
        current = connection.execute("SELECT image_path FROM style_group_images WHERE group_id=? AND is_reference=1 ORDER BY id LIMIT 1", (group_id,)).fetchone()
        if current is None:
            connection.execute("UPDATE style_groups SET reference_image_path='',updated_at=? WHERE id=?", (_now(), group_id))
        else:
            connection.execute("UPDATE style_groups SET reference_image_path=?,updated_at=? WHERE id=?", (current[0], _now(), group_id))
        return _group_payload(connection, int(group_id))


def delete_group(db_path, image_dir, group_id):
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute("SELECT id FROM style_groups WHERE id=?", (group_id,)).fetchone()
        if row is None:
            return False
        image_paths = [item[0] for item in connection.execute("SELECT image_path FROM style_group_images WHERE group_id=?", (group_id,)).fetchall()]
        connection.execute("DELETE FROM style_groups WHERE id=?", (group_id,))
    root = Path(image_dir).resolve()
    for relative in image_paths:
        target = (root / _safe_relative(relative)).resolve()
        if root in target.parents and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    target = (root / str(int(group_id))).resolve()
    if root in target.parents and target.is_dir() and not any(target.iterdir()):
        target.rmdir()
    return True


# Names kept explicit for callers and small integration tests.
create_style_group = create_group
list_style_groups = list_groups
get_style_group = get_group
add_style_group_sources = add_sources
list_style_group_candidates = list_candidates
decide_style_group_candidate = record_decision


# ---------------------------------------------------------------------------
# Author-centered groups
# ---------------------------------------------------------------------------

def _legacy_artist_for_decision(connection, source_type, source_id, candidate_key):
    """Best-effort author inference for the pre-author image decisions."""
    try:
        if source_type in {"danbooru", "rating", "ratings"}:
            row = connection.execute("SELECT artist_tag FROM ratings WHERE id=?", (int(source_id),)).fetchone()
            return row[0] if row else ""
        if source_type == "nai_test":
            if str(candidate_key).startswith("item:"):
                item_id = int(str(candidate_key).split(":", 1)[1])
                row = connection.execute(
                    "SELECT artist_tag FROM nai_artist_test_items WHERE id=? AND test_id=?",
                    (item_id, int(source_id)),
                ).fetchone()
                return row[0] if row else ""
    except (TypeError, ValueError, sqlite3.Error):
        return ""
    return ""


def _migrate_legacy_artist_decisions(connection):
    """Migrate inferable image decisions exactly once, never delete legacy rows."""
    version = connection.execute(
        "SELECT value FROM style_group_schema_meta WHERE key='artist_decisions_version'"
    ).fetchone()
    if version and int(version[0] or 0) >= 1:
        return
    try:
        decisions = connection.execute(
            """SELECT d.group_id,d.candidate_key,d.included,s.source_type,s.source_id
               FROM style_group_decisions d JOIN style_group_sources s ON s.id=d.source_id"""
        ).fetchall()
    except sqlite3.OperationalError:
        decisions = []
    grouped = {}
    for row in decisions:
        artist_tag = _legacy_artist_for_decision(
            connection, row["source_type"], row["source_id"], row["candidate_key"]
        )
        artist_key = normalize_artist_tag(artist_tag)
        if not artist_key:
            continue
        key = (row["group_id"], artist_key)
        entry = grouped.setdefault(key, {"artist_tag": artist_tag, "included": False})
        entry["included"] = entry["included"] or bool(row["included"])
    timestamp = _now()
    for (group_id, artist_key), entry in grouped.items():
        connection.execute(
            """INSERT OR IGNORE INTO style_group_artists
               (group_id,artist_key,artist_tag,decision,direct,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (group_id, artist_key, entry["artist_tag"], "included" if entry["included"] else "excluded", 0, timestamp, timestamp),
        )
    connection.execute(
        "INSERT INTO style_group_schema_meta(key,value) VALUES('artist_decisions_version','1') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )

def _default_source_roots(db_path):
    root = Path(db_path).resolve().parent
    return {"thumbnails": root / "thumbnails", "generated": root / "generated"}


def _source_roots(db_path, source_roots=None):
    roots = _default_source_roots(db_path)
    for name, value in (source_roots or {}).items():
        if name in {"thumbnails", "generated"} and value:
            roots[name] = Path(value)
    return roots


def _source_file(row, roots):
    root = roots.get(row.get("source_root"))
    relative = _safe_relative(row.get("image_path"))
    if not root or not relative:
        return None
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


def _source_rows(connection, source_type, source_id):
    """Return source images with their normalized author keys.

    This intentionally reads source tables each time.  The group stores only
    accepted copies, so deleting or changing a source never mutates a group.
    """
    source_type = _modern_source_type(source_type)
    source_id = _modern_source_id(source_type, source_id)
    rows = []
    if source_type == "rating_management":
        ratings = connection.execute(
            "SELECT id,artist_tag,representative_thumbnail_path FROM ratings ORDER BY id"
        ).fetchall()
        for rating in ratings:
            artist_tag = str(rating["artist_tag"] or "").strip()
            artist_key = normalize_artist_tag(artist_tag)
            if not artist_key:
                continue
            representative = rating["representative_thumbnail_path"] or ""
            if representative:
                rows.append({
                    "candidate_key": f"rating:{rating['id']}:representative:{representative}",
                    "image_path": representative,
                    "source_root": "thumbnails",
                    "source_type": source_type,
                    "source_id": source_id,
                    "artist_key": artist_key,
                    "artist_tag": artist_tag,
                    "rating_id": rating["id"],
                    "post_id": rating["id"],
                })
            try:
                examples = connection.execute(
                    "SELECT id,image_path,post_id FROM rating_examples WHERE rating_id=? ORDER BY id",
                    (rating["id"],),
                ).fetchall()
            except sqlite3.OperationalError:
                examples = []
            seen_paths = {representative} if representative else set()
            for example in examples:
                path = example["image_path"] or ""
                if not path or path in seen_paths:
                    continue
                seen_paths.add(path)
                rows.append({
                    "candidate_key": f"rating_example:{example['id']}",
                    "image_path": path,
                    "source_root": "thumbnails",
                    "source_type": source_type,
                    "source_id": source_id,
                    "artist_key": artist_key,
                    "artist_tag": artist_tag,
                    "rating_id": rating["id"],
                    "post_id": example["post_id"],
                })
        return rows
    try:
        return [
            {
                "candidate_key": f"nai_item:{row['id']}",
                "image_path": row["image_path"],
                "source_root": "generated",
                "source_type": source_type,
                "source_id": source_id,
                "artist_key": normalize_artist_tag(row["artist_tag"]),
                "artist_tag": row["artist_tag"],
                "item_id": row["id"],
                "ordinal": row["ordinal"],
            }
            for row in connection.execute(
                """SELECT i.id,i.artist_tag,i.ordinal,g.image_path
                   FROM nai_artist_test_items i
                   JOIN generated_images g ON g.id=i.generated_image_id
                   WHERE i.test_id=? AND i.status='complete'
                     AND i.generated_image_id IS NOT NULL AND g.image_path!=''
                   ORDER BY i.ordinal,i.id""",
                (int(source_id),),
            ).fetchall()
            if normalize_artist_tag(row["artist_tag"])
        ]
    except (sqlite3.OperationalError, TypeError, ValueError):
        return []


def _public_source_image(row, roots):
    path = _safe_relative(row.get("image_path"))
    target = _source_file(row, roots)
    item = {
        "candidate_key": row.get("candidate_key", ""),
        "artist_key": row.get("artist_key", ""),
        "artist_tag": row.get("artist_tag", ""),
        "source_type": row.get("source_type", ""),
        "source_id": row.get("source_id", ""),
        "image_path": path,
        "image_url": "",
        "post_id": row.get("post_id"),
        "item_id": row.get("item_id"),
        "ordinal": row.get("ordinal"),
    }
    if target is not None:
        item["image_url"] = f"/{row['source_root']}/{path}"
    return item


def _group_sources(connection, group_id):
    return connection.execute(
        """SELECT * FROM style_group_sources
           WHERE group_id=? AND source_type IN ('rating_management','nai_test')
           ORDER BY id""",
        (group_id,),
    ).fetchall()


def _artist_summary(rows, roots):
    grouped = {}
    for row in rows:
        if _source_file(row, roots) is None:
            continue
        key = row["artist_key"]
        entry = grouped.setdefault(key, {
            "artist_key": key,
            "artist_tag": row["artist_tag"],
            "image_count": 0,
            "representative": None,
        })
        entry["image_count"] += 1
        if entry["representative"] is None:
            entry["representative"] = _public_source_image(row, roots)
    return list(grouped.values())


def list_style_group_targets(db_path, source_roots=None):
    """List the single rating-management source and each NAI test source."""
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection:
        rating_rows = _source_rows(connection, "rating_management", "all")
        rating_artists = _artist_summary(rating_rows, roots)
        targets = []
        if rating_artists:
            targets.append({
                "source_type": "rating_management",
                "source_id": "all",
                "name": "평가 관리",
                "label": "평가 관리 전체",
                "artist_count": len(rating_artists),
                "image_count": sum(_source_file(row, roots) is not None for row in rating_rows),
                "artists": rating_artists,
            })
        try:
            tests = connection.execute(
                "SELECT id,name,status FROM nai_artist_tests ORDER BY updated_at DESC,id DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            tests = []
        for test in tests:
            rows = _source_rows(connection, "nai_test", test["id"])
            artists = _artist_summary(rows, roots)
            if not artists:
                continue
            targets.append({
                "source_type": "nai_test",
                "source_id": str(test["id"]),
                "name": test["name"],
                "label": test["name"],
                "status": test["status"],
                "artist_count": len(artists),
                "image_count": sum(_source_file(row, roots) is not None for row in rows),
                "artists": artists,
            })
    return targets


def create_author_group(db_path, image_dir, name, sources, base_source=None,
                        reference=None, source_roots=None):
    if not isinstance(sources, list) or not sources:
        raise ValueError("하나 이상의 출처를 선택해 주세요.")
    normalized = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("출처 형식을 확인해 주세요.")
        source_type = _modern_source_type(source.get("source_type"))
        source_id = _modern_source_id(source_type, source.get("source_id", source.get("id")))
        key = (source_type, source_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"source_type": source_type, "source_id": source_id, "label": source.get("label") or source.get("name") or ""})
    if not normalized:
        raise ValueError("하나 이상의 출처를 선택해 주세요.")
    base = base_source or normalized[0]
    base_type = _modern_source_type(base.get("source_type"))
    base_id = _modern_source_id(base_type, base.get("source_id", base.get("id")))
    if (base_type, base_id) not in seen:
        raise ValueError("기본 대상은 선택한 출처 중 하나여야 합니다.")
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection:
        for source in normalized:
            rows = _source_rows(connection, source["source_type"], source["source_id"])
            if not any(_source_file(row, roots) is not None for row in rows):
                raise ValueError("로컬 그림이 있는 출처만 선택할 수 있습니다.")
    with closing(_connect(db_path)) as connection, connection:
        timestamp = _now()
        cursor = connection.execute(
            "INSERT INTO style_groups(name,reference_image_path,base_source_type,base_source_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (_validate_name(name), "", base_type, base_id, timestamp, timestamp),
        )
        group_id = cursor.lastrowid
        _insert_sources(connection, group_id, normalized)
    if reference:
        if not isinstance(reference, dict):
            raise ValueError("기준 이미지 선택을 확인해 주세요.")
        select_style_group_reference(
            db_path, image_dir, group_id, reference.get("source_type"),
            reference.get("source_id"), reference.get("candidate_key"), source_roots,
        )
    return get_group(db_path, group_id)


def set_style_group_base_source(db_path, group_id, source_type, source_id):
    source_type = _modern_source_type(source_type)
    source_id = _modern_source_id(source_type, source_id)
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        if connection.execute(
            "SELECT 1 FROM style_group_sources WHERE group_id=? AND source_type=? AND source_id=?",
            (group_id, source_type, source_id),
        ).fetchone() is None:
            raise ValueError("기본 대상은 연결된 출처 중 하나여야 합니다.")
        connection.execute(
            "UPDATE style_groups SET base_source_type=?,base_source_id=?,updated_at=? WHERE id=?",
            (source_type, source_id, _now(), group_id),
        )
    return get_group(db_path, group_id)


def list_style_group_source_gallery(db_path, source_type, source_id, source_roots=None):
    source_type = _modern_source_type(source_type)
    source_id = _modern_source_id(source_type, source_id)
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection:
        rows = _source_rows(connection, source_type, source_id)
    images = [_public_source_image(row, roots) for row in rows if _source_file(row, roots) is not None]
    return {
        "source_type": source_type,
        "source_id": source_id,
        "images": images,
        "artists": _artist_summary(rows, roots),
    }


def _modern_rows_for_group(connection, group_id, source_roots):
    result = []
    for source in _group_sources(connection, group_id):
        rows = _source_rows(connection, source["source_type"], source["source_id"])
        result.append((source, rows, source_roots))
    return result


def list_style_group_artist_review(db_path, group_id, artist_key=None,
                                   source_roots=None):
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection:
        group = _group_payload(connection, group_id)
        if group is None:
            return None
        base = (group.get("base_source_type"), group.get("base_source_id"))
        base_rows = _source_rows(connection, base[0], base[1]) if base[0] in MODERN_SOURCE_TYPES else []
        available = _artist_summary(base_rows, roots)
        decisions = {
            row["artist_key"]: row["decision"]
            for row in connection.execute("SELECT artist_key,decision FROM style_group_artists WHERE group_id=?", (group_id,)).fetchall()
        }
        pending = [artist for artist in available if decisions.get(artist["artist_key"]) not in {"included", "excluded"}]
        if artist_key:
            artist_key = normalize_artist_tag(artist_key)
        current = next((artist for artist in available if artist["artist_key"] == artist_key), None) if artist_key else (pending[0] if pending else None)
        if current is None and artist_key:
            current = next((artist for artist in group.get("artists", []) if artist["artist_key"] == artist_key), None)
        if current is None:
            return {
                "group": group, "artist": None, "sources": [], "queue": pending,
                "next_artist": pending[0] if pending else None,
            }
        sources = []
        for source, rows, roots in _modern_rows_for_group(connection, group_id, roots):
            images = [
                _public_source_image(row, roots)
                for row in rows
                if row["artist_key"] == current["artist_key"] and _source_file(row, roots) is not None
            ]
            if images:
                sources.append({
                    "source_type": source["source_type"],
                    "source_id": source["source_id"],
                    "label": source["label"] or source["source_type"],
                    "representative": images[0],
                    "images": images,
                })
        current["decision"] = decisions.get(current["artist_key"])
        return {
            "group": group,
            "artist": current,
            "sources": sources,
            "queue": pending,
            "next_artist": next((artist for artist in pending if artist["artist_key"] != current["artist_key"]), None),
        }


def _set_reference(connection, group_id, image_id):
    connection.execute("UPDATE style_group_images SET is_reference=0 WHERE group_id=?", (group_id,))
    row = connection.execute("SELECT image_path FROM style_group_images WHERE id=? AND group_id=?", (image_id, group_id)).fetchone()
    if row is None:
        raise ValueError("기준 이미지를 찾을 수 없습니다.")
    connection.execute("UPDATE style_group_images SET is_reference=1 WHERE id=?", (image_id,))
    connection.execute("UPDATE style_groups SET reference_image_path=?,updated_at=? WHERE id=?", (row[0], _now(), group_id))


def _remove_reference_only_image(connection, group_id, image_id):
    """Remove an old standalone reference, retaining included author images."""
    row = connection.execute(
        "SELECT id,image_path,artist_key FROM style_group_images WHERE id=? AND group_id=?",
        (image_id, group_id),
    ).fetchone()
    if row is None or row[2]:
        return None
    linked = connection.execute(
        "SELECT 1 FROM style_group_image_artists WHERE image_id=? LIMIT 1", (image_id,)
    ).fetchone()
    if linked is not None:
        return None
    connection.execute("DELETE FROM style_group_images WHERE id=? AND group_id=?", (image_id, group_id))
    return row[1]


def _copy_modern_row(connection, image_dir, group_id, row, roots, associate_artist=True):
    source_file = _source_file(row, roots)
    if source_file is None:
        return None
    if source_file.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("원본 이미지가 너무 큽니다.")
    image_bytes = source_file.read_bytes()
    info = _validate_bytes(image_bytes)
    digest = hashlib.sha256(image_bytes).hexdigest()
    existing = connection.execute("SELECT id FROM style_group_images WHERE group_id=? AND sha256=?", (group_id, digest)).fetchone()
    if existing:
        if associate_artist and row.get("artist_key"):
            connection.execute(
                "INSERT OR IGNORE INTO style_group_image_artists(image_id,artist_key) VALUES(?,?)",
                (existing[0], row["artist_key"]),
            )
        return int(existing[0])
    relative = _write_copy(image_dir, group_id, image_bytes, info["suffix"], digest)
    connection.execute(
        """INSERT INTO style_group_images
           (group_id,source_type,source_id,candidate_key,artist_key,image_path,original_name,width,height,sha256,is_reference,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (group_id, row["source_type"], str(row["source_id"]), row["candidate_key"], row["artist_key"] if associate_artist else "", relative,
         source_file.name[:200], info["width"], info["height"], digest, 0, _now()),
    )
    image_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    if associate_artist and row.get("artist_key"):
        connection.execute(
            "INSERT OR IGNORE INTO style_group_image_artists(image_id,artist_key) VALUES(?,?)",
            (image_id, row["artist_key"]),
        )
    return image_id


def _remove_modern_artist_images(connection, image_dir, group_id, artist_key):
    rows = connection.execute(
        """SELECT i.id,i.image_path FROM style_group_images i
           LEFT JOIN style_group_image_artists link ON link.image_id=i.id AND link.artist_key=?
           WHERE i.group_id=? AND i.is_reference=0 AND (i.artist_key=? OR link.image_id IS NOT NULL)""",
        (artist_key, group_id, artist_key),
    ).fetchall()
    deleted_paths = []
    for row in rows:
        connection.execute(
            "DELETE FROM style_group_image_artists WHERE image_id=? AND artist_key=?",
            (row["id"], artist_key),
        )
        remaining = connection.execute(
            "SELECT 1 FROM style_group_image_artists WHERE image_id=? LIMIT 1", (row["id"],)
        ).fetchone()
        if remaining is None:
            connection.execute("DELETE FROM style_group_images WHERE id=?", (row["id"],))
            deleted_paths.append(row["image_path"])
    root = Path(image_dir).resolve()
    for relative in deleted_paths:
        path = (root / _safe_relative(relative)).resolve()
        if root in path.parents and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def record_style_group_artist_decision(db_path, image_dir, group_id, artist_tag,
                                       include, source_roots=None,
                                       reference_source_type=None,
                                       reference_source_id=None,
                                       reference_candidate_key=None,
                                       direct=False):
    artist_key = normalize_artist_tag(artist_tag)
    if not artist_key:
        raise ValueError("artist_tag is required.")
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection, connection:
        group = connection.execute("SELECT * FROM style_groups WHERE id=?", (group_id,)).fetchone()
        if group is None:
            return None
        sources = _group_sources(connection, group_id)
        if not sources and not direct:
            raise ValueError("작가 중심 출처가 연결되지 않았습니다.")
        timestamp = _now()
        existing = connection.execute("SELECT id FROM style_group_artists WHERE group_id=? AND artist_key=?", (group_id, artist_key)).fetchone()
        decision = "included" if include else "excluded"
        if existing:
            connection.execute(
                """UPDATE style_group_artists SET artist_tag=?,decision=?,direct=?,updated_at=?
                   WHERE id=?""",
                (str(artist_tag or artist_key).strip(), decision, 1 if direct else 0, timestamp, existing[0]),
            )
        else:
            connection.execute(
                """INSERT INTO style_group_artists
                   (group_id,artist_key,artist_tag,decision,direct,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (group_id, artist_key, str(artist_tag or artist_key).strip(), decision, 1 if direct else 0, timestamp, timestamp),
            )
        if not include:
            _remove_modern_artist_images(connection, image_dir, group_id, artist_key)
        else:
            selected_reference = None
            if reference_candidate_key:
                ref_type = _modern_source_type(reference_source_type)
                ref_id = _modern_source_id(ref_type, reference_source_id)
                selected_reference = next(
                    (row for row in _source_rows(connection, ref_type, ref_id)
                     if row["artist_key"] == artist_key and row["candidate_key"] == reference_candidate_key),
                    None,
                )
            copied = []
            for source in sources:
                for row in _source_rows(connection, source["source_type"], source["source_id"]):
                    if row["artist_key"] == artist_key:
                        image_id = _copy_modern_row(connection, image_dir, group_id, row, roots)
                        if image_id is not None:
                            copied.append((row, image_id))
            if not copied and not direct:
                raise ValueError("현재 선택한 출처에 로컬 이미지가 없습니다.")
            if not group["reference_image_path"] and copied:
                wanted = selected_reference or copied[0][0]
                wanted_id = next((image_id for row, image_id in copied if row["candidate_key"] == wanted["candidate_key"]), copied[0][1])
                _set_reference(connection, group_id, wanted_id)
        connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (timestamp, group_id))
        payload = _group_payload(connection, group_id)
    return payload


def select_style_group_reference(db_path, image_dir, group_id, source_type,
                                 source_id, candidate_key, source_roots=None):
    source_type = _modern_source_type(source_type)
    source_id = _modern_source_id(source_type, source_id)
    roots = _source_roots(db_path, source_roots)
    removed_path = None
    payload = None
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        old_reference = connection.execute(
            "SELECT id FROM style_group_images WHERE group_id=? AND is_reference=1 LIMIT 1", (group_id,)
        ).fetchone()
        row = next((candidate for candidate in _source_rows(connection, source_type, source_id)
                    if candidate["candidate_key"] == candidate_key), None)
        if row is None:
            raise ValueError("선택한 출처에서 기준 이미지를 찾을 수 없습니다.")
        image_id = _copy_modern_row(connection, image_dir, group_id, row, roots, associate_artist=False)
        if image_id is None:
            raise ValueError("선택한 기준 이미지 파일을 찾을 수 없습니다.")
        _set_reference(connection, group_id, image_id)
        if old_reference is not None and int(old_reference[0]) != int(image_id):
            removed_path = _remove_reference_only_image(connection, group_id, old_reference[0])
        payload = _group_payload(connection, group_id, roots)
    if removed_path:
        root = Path(image_dir).resolve()
        target = (root / _safe_relative(removed_path)).resolve()
        if root in target.parents and target.is_file():
            try:
                target.unlink()
            except OSError:
                pass
    return payload


def add_style_group_direct_artist(db_path, group_id, artist_tag, image_dir=None):
    image_dir = image_dir or (Path(db_path).parent / "style_group_images")
    return record_style_group_artist_decision(db_path, image_dir, group_id, artist_tag, True, direct=True)


def remove_style_group_artist(db_path, image_dir, group_id, artist_key):
    artist_key = normalize_artist_tag(artist_key)
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        _remove_modern_artist_images(connection, image_dir, group_id, artist_key)
        connection.execute("DELETE FROM style_group_artists WHERE group_id=? AND artist_key=?", (group_id, artist_key))
        connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (_now(), group_id))
        return _group_payload(connection, group_id)


def reconsider_style_group_artist(db_path, group_id, artist_key, source_roots=None):
    artist_key = normalize_artist_tag(artist_key)
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute("SELECT artist_tag FROM style_group_artists WHERE group_id=? AND artist_key=?", (group_id, artist_key)).fetchone()
        if row is None:
            raise ValueError("제외된 작가를 찾을 수 없습니다.")
    return list_style_group_artist_review(db_path, group_id, artist_key, source_roots)


def add_style_group_sources_modern(db_path, image_dir, group_id, sources, source_roots=None):
    if not isinstance(sources, list):
        raise ValueError("sources must be a list.")
    roots = _source_roots(db_path, source_roots)
    with closing(_connect(db_path)) as connection, connection:
        if connection.execute("SELECT 1 FROM style_groups WHERE id=?", (group_id,)).fetchone() is None:
            return None
        normalized_sources = []
        for source in sources:
            source_type = _modern_source_type(source.get("source_type"))
            source_id = _modern_source_id(source_type, source.get("source_id", source.get("id")))
            if not any(_source_file(row, roots) is not None for row in _source_rows(connection, source_type, source_id)):
                raise ValueError("로컬 그림이 있는 출처만 연결할 수 있습니다.")
            normalized_sources.append((source, source_type, source_id))
        for source, source_type, source_id in normalized_sources:
            connection.execute(
                """INSERT OR IGNORE INTO style_group_sources
                   (group_id,source_type,source_id,label,position,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (group_id, source_type, source_id, str(source.get("label") or source.get("name") or ""), 0, _now(), _now()),
            )
        included = connection.execute(
            "SELECT artist_key FROM style_group_artists WHERE group_id=? AND decision='included'",
            (group_id,),
        ).fetchall()
        for source, source_type, source_id in normalized_sources:
            for artist in included:
                for row in _source_rows(connection, source_type, source_id):
                    if row["artist_key"] == artist["artist_key"]:
                        _copy_modern_row(connection, image_dir, group_id, row, roots)
        connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (_now(), group_id))
        return _group_payload(connection, group_id)


def sync_style_group_generated_image(db_path, image_dir, test_id, artist_tag,
                                     generated_image_id=None, image_path=None):
    """Attach a newly completed NAI image to every matching group."""
    artist_key = normalize_artist_tag(artist_tag)
    roots = _source_roots(db_path)
    with closing(_connect(db_path)) as connection, connection:
        if image_path is None and generated_image_id is not None:
            row = connection.execute("SELECT image_path FROM generated_images WHERE id=?", (generated_image_id,)).fetchone()
            image_path = row[0] if row else ""
        if not image_path:
            return 0
        matched = 0
        groups = connection.execute(
            """SELECT g.id FROM style_groups g
               JOIN style_group_sources s ON s.group_id=g.id
               JOIN style_group_artists a ON a.group_id=g.id AND a.artist_key=? AND a.decision='included'
               WHERE s.source_type='nai_test' AND s.source_id=?""",
            (artist_key, str(test_id)),
        ).fetchall()
        row = {
            "candidate_key": f"nai_generated:{generated_image_id or image_path}",
            "image_path": image_path,
            "source_root": "generated",
            "source_type": "nai_test",
            "source_id": str(test_id),
            "artist_key": artist_key,
            "artist_tag": artist_tag,
        }
        for group in groups:
            if _copy_modern_row(connection, image_dir, group[0], row, roots) is not None:
                matched += 1
            connection.execute("UPDATE style_groups SET updated_at=? WHERE id=?", (_now(), group[0]))
        return matched


# Explicit aliases make the author-centered API easy to discover while the
# original image-level names above remain valid for existing clients.
get_style_group_artist_gallery = list_style_group_artist_review
get_style_group_source_gallery = list_style_group_source_gallery
