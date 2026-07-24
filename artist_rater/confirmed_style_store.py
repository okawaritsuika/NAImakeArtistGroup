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


def normalize_confirmed_model_name(value):
    model = str(value or "").strip()
    lowered = model.casefold()
    if lowered.startswith("novelai diffusion v4.5 curated") or lowered == "nai-diffusion-4-5-curated":
        return "NovelAI Diffusion V4.5 Curated"
    if lowered.startswith("novelai diffusion v4.5") or lowered == "nai-diffusion-4-5-full":
        return "NovelAI Diffusion V4.5 Full"
    return model


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
                character_prompts_json TEXT NOT NULL DEFAULT '[]',
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
            CREATE TABLE IF NOT EXISTS confirmed_style_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                style_id INTEGER NOT NULL,
                image_path TEXT NOT NULL UNIQUE,
                width INTEGER,
                height INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(style_id) REFERENCES confirmed_styles(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_confirmed_style_images_style
                ON confirmed_style_images(style_id, position, id);
            INSERT INTO confirmed_style_images (style_id,image_path,width,height,position,created_at)
            SELECT id,image_path,width,height,0,created_at
            FROM confirmed_styles
            WHERE NOT EXISTS (
                SELECT 1 FROM confirmed_style_images image
                WHERE image.style_id=confirmed_styles.id
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(confirmed_styles)")}
        if "character_prompts_json" not in columns:
            connection.execute("ALTER TABLE confirmed_styles ADD COLUMN character_prompts_json TEXT NOT NULL DEFAULT '[]'")


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
    character_prompts = payload.get("character_prompts", [])
    if not isinstance(character_prompts, list) or len(character_prompts) > 20:
        raise ValueError("character_prompts must be a list of up to 20 strings.")
    normalized_characters = []
    for item in character_prompts:
        value = item.get("prompt") if isinstance(item, dict) else item
        if not isinstance(value, str):
            raise ValueError("Each character prompt must be a string.")
        value = normalize_numeric_prompt_closers(value.strip())
        if value and value not in normalized_characters:
            normalized_characters.append(value)
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
        "character_prompts_json": json.dumps(normalized_characters, ensure_ascii=False),
        "negative_prompt": normalize_numeric_prompt_closers(_text(payload, "negative_prompt")),
        "sampler": _text(payload, "sampler"),
        "noise_schedule": _text(payload, "noise_schedule"),
        "steps": _nullable_int(payload, "steps", 1, 1000),
        "scale": _nullable_float(payload, "scale", 0, 100),
        "cfg_rescale": _nullable_float(payload, "cfg_rescale", 0, 100),
        "variety_plus": _nullable_bool(payload, "variety_plus"),
        "skip_cfg_above_sigma": _nullable_float(payload, "skip_cfg_above_sigma", 0),
        "model": normalize_confirmed_model_name(_text(payload, "model")),
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
    item["model"] = normalize_confirmed_model_name(item.get("model"))
    try:
        item["excluded_quality_tags"] = json.loads(item.pop("excluded_quality_tags_json") or "[]")
    except json.JSONDecodeError:
        item["excluded_quality_tags"] = []
    try:
        item["character_prompts"] = json.loads(item.pop("character_prompts_json") or "[]")
    except json.JSONDecodeError:
        item["character_prompts"] = []
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
        items = [_decoded(row) for row in rows]
        _attach_confirmed_images(connection, items)
    return items


def get_confirmed_style(db_path, style_id):
    with closing(_connect(db_path)) as connection:
        row = connection.execute("SELECT * FROM confirmed_styles WHERE id=?", (style_id,)).fetchone()
        item = _decoded(row) if row else None
        if item:
            _attach_confirmed_images(connection, [item])
    return item


def _attach_confirmed_images(connection, items):
    if not items:
        return
    by_style = {item["id"]: item for item in items}
    placeholders = ",".join("?" for _ in by_style)
    rows = connection.execute(
        f"SELECT id,style_id,image_path,width,height,position FROM confirmed_style_images WHERE style_id IN ({placeholders}) ORDER BY position,id",
        list(by_style),
    ).fetchall()
    for item in items:
        item["images"] = []
    for row in rows:
        image = dict(row)
        by_style[image.pop("style_id")]["images"].append(image)
    for item in items:
        item["image_count"] = len(item["images"])


def create_confirmed_style(db_path, image_dir, image_bytes, payload):
    return create_confirmed_style_group(db_path, image_dir, [image_bytes], payload)


def create_confirmed_style_group(db_path, image_dir, image_bytes_list, payload):
    if not isinstance(image_bytes_list, list) or not image_bytes_list or len(image_bytes_list) > 500:
        raise ValueError("A confirmed style must contain 1 to 500 images.")
    image_infos = [inspect_image(image_bytes) for image_bytes in image_bytes_list]
    values = normalize_confirmed_style(payload)
    if not values["width"]:
        values["width"] = image_infos[0]["width"]
    if not values["height"]:
        values["height"] = image_infos[0]["height"]
    root = Path(image_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stored = []
    for image_bytes, image_info in zip(image_bytes_list, image_infos):
        relative_path = f"{uuid.uuid4().hex}{image_info['suffix']}"
        target = (root / relative_path).resolve()
        if target.parent != root:
            raise ValueError("Confirmed image path is invalid.")
        stored.append((relative_path, target, image_info))
        try:
            target.write_bytes(image_bytes)
        except Exception:
            for _, stored_target, _ in stored:
                stored_target.unlink(missing_ok=True)
            raise
    timestamp = datetime.now(timezone.utc).isoformat()
    columns = [*values, "image_path", "created_at", "updated_at"]
    parameters = [values[key] for key in values] + [stored[0][0], timestamp, timestamp]
    try:
        with closing(_connect(db_path)) as connection, connection:
            placeholders = ",".join("?" for _ in columns)
            cursor = connection.execute(
                f"INSERT INTO confirmed_styles ({','.join(columns)}) VALUES ({placeholders})",
                parameters,
            )
            style_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO confirmed_style_images (style_id,image_path,width,height,position,created_at) VALUES (?,?,?,?,?,?)",
                [
                    (style_id, relative_path, image_info["width"], image_info["height"], position, timestamp)
                    for position, (relative_path, _, image_info) in enumerate(stored)
                ],
            )
    except Exception:
        for _, target, _ in stored:
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
        image_rows = connection.execute(
            "SELECT image_path FROM confirmed_style_images WHERE style_id=?",
            (style_id,),
        ).fetchall()
        connection.execute("DELETE FROM confirmed_styles WHERE id=?", (style_id,))
    root = Path(image_dir).resolve()
    paths = {existing["image_path"], *(row["image_path"] for row in image_rows)}
    for image_path in paths:
        target = (root / image_path).resolve()
        if target.parent == root:
            target.unlink(missing_ok=True)
    return True
