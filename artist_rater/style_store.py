import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from style_logic import build_artist_prompt, normalize_style_artists, style_hash


def connect_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def generated_file_path(generated_dir, style_id, request_id):
    root = Path(generated_dir).resolve()
    request_text = str(request_id)
    safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_text).strip("._")
    if not safe_request_id:
        raise ValueError("request_id must contain a filename-safe character.")
    if safe_request_id != request_text:
        digest = hashlib.sha256(request_text.encode("utf-8")).hexdigest()[:12]
        safe_request_id = f"{safe_request_id}-{digest}"
    target = (root / str(int(style_id)) / f"{safe_request_id}.png").resolve()
    if root not in target.parents:
        raise ValueError("Generated image path must remain under generated_dir.")
    return target


def save_generated_result(
    db_path,
    generated_dir,
    *,
    request_id,
    artists,
    png_bytes,
    base_prompt="",
    negative_prompt="",
    character_prompts=None,
    combined_prompt="",
    seed=0,
    width=0,
    height=0,
    sampler="",
    steps=0,
    scale=0.0,
    cfg_rescale=0.0,
    model="",
):
    request_id = str(request_id or "").strip()
    if not request_id:
        raise ValueError("request_id is required.")
    if not isinstance(png_bytes, (bytes, bytearray)) or not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("png_bytes must contain a PNG image.")

    normalized_artists = normalize_style_artists(artists)
    artists_json = json.dumps(normalized_artists, ensure_ascii=False, separators=(",", ":"))
    character_prompts_json = json.dumps(
        character_prompts or [], ensure_ascii=False, separators=(",", ":")
    )
    identity_hash = style_hash(normalized_artists)
    artist_prompt = build_artist_prompt(normalized_artists)
    timestamp = datetime.now(timezone.utc).isoformat()
    generated_root = Path(generated_dir).resolve()
    generated_root.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    final_path = None
    final_replaced = False

    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO art_styles (
                style_hash, artists_json, artist_prompt, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(style_hash) DO UPDATE SET
                artists_json = excluded.artists_json,
                artist_prompt = excluded.artist_prompt,
                updated_at = excluded.updated_at
            """,
            (identity_hash, artists_json, artist_prompt, timestamp, timestamp),
        )
        style_row = conn.execute(
            "SELECT id FROM art_styles WHERE style_hash = ?", (identity_hash,)
        ).fetchone()
        style_id = style_row["id"]
        final_path = generated_file_path(generated_root, style_id, request_id)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_path.write_bytes(bytes(png_bytes))
        relative_path = final_path.relative_to(generated_root).as_posix()

        cursor = conn.execute(
            """
            INSERT INTO generated_images (
                request_id, style_id, image_path, base_prompt, negative_prompt,
                character_prompts_json, combined_prompt, artist_prompt,
                artists_json, seed, width, height, sampler, steps, scale,
                cfg_rescale, model, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                style_id,
                relative_path,
                base_prompt,
                negative_prompt,
                character_prompts_json,
                combined_prompt,
                artist_prompt,
                artists_json,
                int(seed),
                int(width),
                int(height),
                sampler,
                int(steps),
                float(scale),
                float(cfg_rescale),
                model,
                timestamp,
            ),
        )
        image_id = cursor.lastrowid
        temporary_path.replace(final_path)
        final_replaced = True
        conn.execute(
            """
            UPDATE art_styles
            SET representative_image_path = ?,
                image_count = image_count + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (relative_path, timestamp, style_id),
        )
        conn.commit()
        return {
            "style_id": style_id,
            "image_id": image_id,
            "image_path": relative_path,
            "artist_prompt": artist_prompt,
            "style_hash": identity_hash,
        }
    except Exception:
        conn.rollback()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if final_replaced and final_path is not None:
            final_path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def _parse_json_field(item, source_key, result_key):
    try:
        item[result_key] = json.loads(item.get(source_key) or "[]")
    except (TypeError, json.JSONDecodeError):
        item[result_key] = []
    item.pop(source_key, None)


def list_styles(db_path):
    conn = connect_db(db_path)
    try:
        rows = conn.execute("SELECT * FROM art_styles ORDER BY updated_at DESC, id DESC").fetchall()
    finally:
        conn.close()
    styles = []
    for row in rows:
        item = dict(row)
        _parse_json_field(item, "artists_json", "artists")
        styles.append(item)
    return styles


def get_style_detail(db_path, style_id):
    conn = connect_db(db_path)
    try:
        style_row = conn.execute("SELECT * FROM art_styles WHERE id = ?", (style_id,)).fetchone()
        if style_row is None:
            return None
        image_rows = conn.execute(
            "SELECT * FROM generated_images WHERE style_id = ? ORDER BY created_at DESC, id DESC",
            (style_id,),
        ).fetchall()
    finally:
        conn.close()
    style = dict(style_row)
    _parse_json_field(style, "artists_json", "artists")
    images = []
    for row in image_rows:
        image = dict(row)
        _parse_json_field(image, "artists_json", "artists")
        _parse_json_field(image, "character_prompts_json", "character_prompts")
        images.append(image)
    style["images"] = images
    return style
