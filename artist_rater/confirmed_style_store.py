import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from style_logic import normalize_numeric_prompt_closers


MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TEXT_LENGTH = 16384
ALLOWED_IMAGE_FORMATS = {
    "PNG": (".png", "image/png"),
    "JPEG": (".jpg", "image/jpeg"),
    "WEBP": (".webp", "image/webp"),
}


def _connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_confirmed_style_tables(db_path):
    with closing(_connect(db_path)) as connection, connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS confirmed_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL,
                artist_prompt TEXT NOT NULL DEFAULT '',
                quality_prompt TEXT NOT NULL DEFAULT '',
                original_quality_prompt TEXT NOT NULL DEFAULT '',
                excluded_quality_tags_json TEXT NOT NULL DEFAULT '[]',
                fixed_prompt TEXT NOT NULL DEFAULT '',
                negative_prompt TEXT NOT NULL DEFAULT '',
                sampler TEXT NOT NULL DEFAULT '',
                noise_schedule TEXT NOT NULL DEFAULT '',
                steps INTEGER,
                scale REAL,
                cfg_rescale REAL,
                variety_plus INTEGER,
                skip_cfg_above_sigma REAL,
                model TEXT NOT NULL DEFAULT '',
                width INTEGER,
                height INTEGER,
                seed INTEGER,
                raw_metadata_json TEXT NOT NULL DEFAULT '{}',
                source_type TEXT NOT NULL DEFAULT 'manual',
                source_id INTEGER,
                source_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK(variety_plus IS NULL OR variety_plus IN (0, 1)),
                CHECK(source_type IN ('manual', 'generated', 'shared'))
            );
            CREATE INDEX IF NOT EXISTS idx_confirmed_styles_updated
                ON confirmed_styles(updated_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_confirmed_styles_source
                ON confirmed_styles(source_type, source_id);
            """
        )


def _text(payload, key):
    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    value = value.strip()
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"{key} is too long.")
    return value


def _nullable_int(payload, key, minimum=0, maximum=4294967295):
    value = payload.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer.") from None
    if number < minimum or number > maximum:
        raise ValueError(f"{key} is out of range.")
    return number


def _nullable_float(payload, key, minimum=0.0, maximum=None):
    value = payload.get(key)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number.") from None
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise ValueError(f"{key} is out of range.")
    return number


def _nullable_bool(payload, key):
    value = payload.get(key)
    if value in (None, "", "unknown"):
        return None
    if value is True or value == 1 or value == "1":
        return 1
    if value is False or value == 0 or value == "0":
        return 0
    raise ValueError(f"{key} must be true, false, or unknown.")


def normalize_confirmed_style(payload):
    if not isinstance(payload, dict):
        raise ValueError("Style data must be an object.")
    excluded = payload.get("excluded_quality_tags", [])
    if not isinstance(excluded, list) or len(excluded) > 200:
        raise ValueError("excluded_quality_tags must be a list of up to 200 strings.")
    normalized_excluded = []
    for item in excluded:
        value = item.get("prompt") if isinstance(item, dict) else item
        if not isinstance(value, str):
            raise ValueError("Each excluded quality tag must be a string.")
        value = value.strip()
        if value and value not in normalized_excluded:
            normalized_excluded.append(value)
    source_type = str(payload.get("source_type") or "manual").strip()
    if source_type not in {"manual", "generated", "shared"}:
        raise ValueError("source_type is not supported.")
    source_id = _nullable_int(payload, "source_id", 1)
    raw_metadata = payload.get("raw_metadata", payload.get("raw_metadata_json", {}))
    if isinstance(raw_metadata, str):
        try:
            raw_metadata = json.loads(raw_metadata or "{}")
        except json.JSONDecodeError:
            raw_metadata = {}
    if not isinstance(raw_metadata, dict):
        raw_metadata = {}
    return {
        "name": _text(payload, "name"),
        "description": _text(payload, "description"),
        "artist_prompt": normalize_numeric_prompt_closers(_text(payload, "artist_prompt")),
        "quality_prompt": normalize_numeric_prompt_closers(_text(payload, "quality_prompt")),
        "original_quality_prompt": normalize_numeric_prompt_closers(_text(payload, "original_quality_prompt")),
        "excluded_quality_tags_json": json.dumps(normalized_excluded, ensure_ascii=False),
        "fixed_prompt": normalize_numeric_prompt_closers(_text(payload, "fixed_prompt")),
        "negative_prompt": normalize_numeric_prompt_closers(_text(payload, "negative_prompt")),
        "sampler": _text(payload, "sampler"),
        "noise_schedule": _text(payload, "noise_schedule"),
        "steps": _nullable_int(payload, "steps", 1, 1000),
        "scale": _nullable_float(payload, "scale", 0, 100),
        "cfg_rescale": _nullable_float(payload, "cfg_rescale", 0, 100),
        "variety_plus": _nullable_bool(payload, "variety_plus"),
        "skip_cfg_above_sigma": _nullable_float(payload, "skip_cfg_above_sigma", 0),
        "model": _text(payload, "model"),
        "width": _nullable_int(payload, "width", 1, 100000),
        "height": _nullable_int(payload, "height", 1, 100000),
        "seed": _nullable_int(payload, "seed", 0, 4294967295),
        "raw_metadata_json": json.dumps(raw_metadata, ensure_ascii=False),
        "source_type": source_type,
        "source_id": source_id,
        "source_url": _text(payload, "source_url"),
    }


def inspect_image(image_bytes):
    if not isinstance(image_bytes, bytes) or not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image must be between 1 byte and 32 MB.")
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.verify()
    except (OSError, ValueError):
        raise ValueError("PNG, JPEG, or WebP image is required.") from None
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("PNG, JPEG, or WebP image is required.")
    suffix, content_type = ALLOWED_IMAGE_FORMATS[image_format]
    return {"suffix": suffix, "content_type": content_type, "width": width, "height": height}


def _decoded(row):
    item = dict(row)
    for key in ("artist_prompt", "quality_prompt", "original_quality_prompt", "fixed_prompt", "negative_prompt"):
        item[key] = normalize_numeric_prompt_closers(item.get(key))
    try:
        item["excluded_quality_tags"] = json.loads(item.pop("excluded_quality_tags_json") or "[]")
    except json.JSONDecodeError:
        item["excluded_quality_tags"] = []
    try:
        item["raw_metadata"] = json.loads(item.pop("raw_metadata_json") or "{}")
    except json.JSONDecodeError:
        item["raw_metadata"] = {}
    if item.get("variety_plus") is not None:
        item["variety_plus"] = bool(item["variety_plus"])
    return item


def list_confirmed_styles(db_path):
    with closing(_connect(db_path)) as connection:
        rows = connection.execute("SELECT * FROM confirmed_styles ORDER BY updated_at DESC, id DESC").fetchall()
    return [_decoded(row) for row in rows]


def get_confirmed_style(db_path, style_id):
    with closing(_connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM confirmed_styles WHERE id=?", (style_id,)).fetchone()
    return _decoded(row) if row else None


def create_confirmed_style(db_path, image_dir, image_bytes, payload):
    image_info = inspect_image(image_bytes)
    values = normalize_confirmed_style(payload)
    if not values["width"]:
        values["width"] = image_info["width"]
    if not values["height"]:
        values["height"] = image_info["height"]
    root = Path(image_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    relative_path = f"{uuid.uuid4().hex}{image_info['suffix']}"
    target = (root / relative_path).resolve()
    if target.parent != root:
        raise ValueError("Confirmed image path is invalid.")
    target.write_bytes(image_bytes)
    timestamp = datetime.now(timezone.utc).isoformat()
    columns = [*values, "image_path", "created_at", "updated_at"]
    parameters = [values[key] for key in values] + [relative_path, timestamp, timestamp]
    try:
        with closing(_connect(db_path)) as connection, connection:
            placeholders = ",".join("?" for _ in columns)
            cursor = connection.execute(
                f"INSERT INTO confirmed_styles ({','.join(columns)}) VALUES ({placeholders})",
                parameters,
            )
            style_id = cursor.lastrowid
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return get_confirmed_style(db_path, style_id)


def update_confirmed_style(db_path, style_id, payload):
    existing = get_confirmed_style(db_path, style_id)
    if existing is None:
        return None
    merged = {**existing, **payload}
    merged["source_type"] = existing["source_type"]
    merged["source_id"] = existing["source_id"]
    values = normalize_confirmed_style(merged)
    timestamp = datetime.now(timezone.utc).isoformat()
    with closing(_connect(db_path)) as connection, connection:
        assignments = ",".join(f"{key}=?" for key in values)
        connection.execute(
            f"UPDATE confirmed_styles SET {assignments},updated_at=? WHERE id=?",
            ([values[key] for key in values] + [timestamp, style_id]),
        )
    return get_confirmed_style(db_path, style_id)


def delete_confirmed_style(db_path, image_dir, style_id):
    existing = get_confirmed_style(db_path, style_id)
    if existing is None:
        return False
    with closing(_connect(db_path)) as connection, connection:
        connection.execute("DELETE FROM confirmed_styles WHERE id=?", (style_id,))
    root = Path(image_dir).resolve()
    target = (root / existing["image_path"]).resolve()
    if target.parent == root:
        target.unlink(missing_ok=True)
    return True
