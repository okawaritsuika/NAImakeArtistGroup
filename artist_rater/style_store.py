import hashlib
import json
import os
import sqlite3
import struct
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

from style_logic import build_artist_prompt, normalize_style_artists, style_hash


MAX_APP_KEY_LENGTH = 8192


class SettingsError(Exception):
    pass


def _absolute_path(path):
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(path):
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                raise SettingsError("Settings path must not contain symlinks.")
        except OSError as exc:
            raise SettingsError("Settings path could not be validated.") from exc


def _validated_settings_path(settings_path, trusted_root):
    if trusted_root is None:
        raise SettingsError("A trusted settings directory is required.")
    path = _absolute_path(settings_path)
    root = _absolute_path(trusted_root)
    if path.parent != root:
        raise SettingsError("Settings file must be a direct child of the trusted directory.")
    _reject_symlink_components(root)
    _reject_symlink_components(path)
    return path


def _load_trusted_settings(settings_path, trusted_root):
    path = _validated_settings_path(settings_path, trusted_root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SettingsError("Settings file could not be read.") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SettingsError("Settings file is corrupt.") from exc
    if not isinstance(data, dict):
        raise SettingsError("Settings file must contain a JSON object.")
    return data


def _write_trusted_settings(settings_path, settings, trusted_root):
    path = _validated_settings_path(settings_path, trusted_root)
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(path.parent)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except SettingsError:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise SettingsError("Settings file could not be saved.") from exc


def normalize_app_key(app_key):
    if type(app_key) is not str:
        raise ValueError("NovelAI App Key must be a string.")
    normalized = app_key.strip()
    if not normalized:
        raise ValueError("NovelAI App Key is required.")
    if len(normalized) > MAX_APP_KEY_LENGTH:
        raise ValueError("NovelAI App Key is too long.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError("NovelAI App Key contains invalid control characters.")
    return normalized


def load_app_key(settings_path, trusted_root):
    value = _load_trusted_settings(settings_path, trusted_root).get("novelai_app_key")
    return value if type(value) is str else ""


def save_app_key(settings_path, app_key, trusted_root):
    normalized = normalize_app_key(app_key)
    settings = _load_trusted_settings(settings_path, trusted_root)
    settings["novelai_app_key"] = normalized
    _write_trusted_settings(settings_path, settings, trusted_root)


def delete_app_key(settings_path, trusted_root):
    path = _validated_settings_path(settings_path, trusted_root)
    settings = _load_trusted_settings(path, trusted_root)
    settings.pop("novelai_app_key", None)
    if settings:
        _write_trusted_settings(path, settings, trusted_root)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise SettingsError("Settings file could not be deleted.") from exc


def connect_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def generated_file_path(generated_dir, style_id, request_id):
    root = Path(generated_dir).resolve()
    request_text = str(request_id)
    if not request_text.strip():
        raise ValueError("request_id is required.")
    filename = f"{hashlib.sha256(request_text.encode('utf-8')).hexdigest()}.png"
    target = (root / str(int(style_id)) / filename).resolve()
    if root not in target.parents:
        raise ValueError("Generated image path must remain under generated_dir.")
    return target


def _staged_file_path(final_path):
    return final_path.with_name(f".{final_path.name}.staged.tmp")


def _validate_png(png_bytes):
    if not isinstance(png_bytes, (bytes, bytearray)):
        raise ValueError("png_bytes must contain a PNG image.")
    data = bytes(png_bytes)
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("png_bytes must contain a PNG image.")

    offset = 8
    chunk_index = 0
    saw_idat = False
    saw_iend = False
    idat_parts = []
    image_header = None
    while offset < len(data):
        if len(data) - offset < 12:
            raise ValueError("PNG chunk is truncated.")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            raise ValueError("PNG chunk is truncated.")
        chunk_data = data[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type)
        actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("PNG chunk CRC is invalid.")

        if chunk_index == 0:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("PNG must start with a valid IHDR chunk.")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width == 0
                or height == 0
                or bit_depth not in valid_depths.get(color_type, set())
                or compression != 0
                or filtering != 0
            ):
                raise ValueError("PNG IHDR fields are invalid.")
            if interlace != 0:
                raise ValueError("Interlaced PNG images are not supported.")
            image_header = (width, height, bit_depth, color_type)
        elif chunk_type == b"IHDR":
            raise ValueError("PNG contains multiple IHDR chunks.")

        if chunk_type == b"IDAT":
            saw_idat = True
            idat_parts.append(chunk_data)
        if chunk_type == b"IEND":
            if length != 0 or not saw_idat:
                raise ValueError("PNG IEND or IDAT structure is invalid.")
            saw_iend = True
            if chunk_end != len(data):
                raise ValueError("PNG contains data after IEND.")
            break
        offset = chunk_end
        chunk_index += 1

    if not saw_iend:
        raise ValueError("PNG is missing IEND.")
    try:
        decompressor = zlib.decompressobj()
        scanlines = decompressor.decompress(b"".join(idat_parts))
        scanlines += decompressor.flush()
    except zlib.error as exc:
        raise ValueError("PNG IDAT data is not valid zlib data.") from exc
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail:
        raise ValueError("PNG IDAT data is not a complete zlib stream.")

    width, height, bit_depth, color_type = image_header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * channels * bit_depth + 7) // 8
    expected_length = height * (1 + row_bytes)
    if len(scanlines) != expected_length:
        raise ValueError("PNG scanline data has an invalid length.")
    for row in range(height):
        if scanlines[row * (1 + row_bytes)] not in range(5):
            raise ValueError("PNG scanline has an invalid filter type.")
    return data


def _stored_result(row):
    return {
        "style_id": row["style_id"],
        "image_id": row["image_id"],
        "image_path": row["image_path"],
        "artist_prompt": row["artist_prompt"],
        "style_hash": row["style_hash"],
        "seed": row["seed"],
    }


def _find_request(conn, request_id):
    return conn.execute(
        """
        SELECT generated_images.id AS image_id, generated_images.style_id,
               generated_images.image_path, generated_images.artist_prompt,
               generated_images.seed,
               art_styles.style_hash
        FROM generated_images
        JOIN art_styles ON art_styles.id = generated_images.style_id
        WHERE generated_images.request_id = ?
        """,
        (request_id,),
    ).fetchone()


def get_generated_result(db_path, request_id):
    conn = connect_db(db_path)
    try:
        row = _find_request(conn, request_id)
    finally:
        conn.close()
    return _stored_result(row) if row is not None else None


def _recompute_style(conn, style_id, timestamp):
    rows = conn.execute(
        """
        SELECT image_path FROM generated_images
        WHERE style_id = ? ORDER BY created_at DESC, id DESC
        """,
        (style_id,),
    ).fetchall()
    if not rows:
        conn.execute("DELETE FROM art_styles WHERE id = ?", (style_id,))
        return
    conn.execute(
        """
        UPDATE art_styles
        SET representative_image_path = ?, image_count = ?, updated_at = ?
        WHERE id = ?
        """,
        (rows[0]["image_path"], len(rows), timestamp, style_id),
    )


def _compensate_failed_promotion(db_path, image_id, style_id, timestamp):
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM generated_images WHERE id = ?", (image_id,))
            _recompute_style(conn, style_id, timestamp)
    finally:
        conn.close()


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
    request_id = str(request_id or "")
    if not request_id.strip():
        raise ValueError("request_id is required.")
    png_data = _validate_png(png_bytes)

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
    staged_path = None
    final_path = None
    committed = False
    image_id = None
    style_id = None

    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = _find_request(conn, request_id)
        if existing is not None:
            conn.commit()
            return _stored_result(existing)
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
        staged_path = _staged_file_path(final_path)
        staged_path.write_bytes(png_data)
        relative_path = final_path.relative_to(generated_root).as_posix()

        try:
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
        except sqlite3.IntegrityError:
            conn.rollback()
            staged_path.unlink(missing_ok=True)
            existing = _find_request(conn, request_id)
            if existing is not None:
                return _stored_result(existing)
            raise
        image_id = cursor.lastrowid
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
        committed = True
        staged_path.replace(final_path)
        return {
            "style_id": style_id,
            "image_id": image_id,
            "image_path": relative_path,
            "artist_prompt": artist_prompt,
            "style_hash": identity_hash,
            "seed": int(seed),
        }
    except Exception:
        if not committed:
            conn.rollback()
        elif image_id is not None and style_id is not None:
            _compensate_failed_promotion(db_path, image_id, style_id, timestamp)
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def reconcile_generated_storage(db_path, generated_dir):
    root = Path(generated_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    try:
        rows = conn.execute("SELECT id, style_id, image_path FROM generated_images").fetchall()
    finally:
        conn.close()

    referenced = set()
    missing_image_ids = []
    affected_style_ids = set()
    for row in rows:
        final_path = (root / row["image_path"]).resolve()
        if root not in final_path.parents:
            missing_image_ids.append(row["id"])
            affected_style_ids.add(row["style_id"])
            continue
        staged_path = _staged_file_path(final_path)
        if not final_path.exists() and staged_path.is_file():
            final_path.parent.mkdir(parents=True, exist_ok=True)
            staged_path.replace(final_path)
        if final_path.is_file():
            referenced.add(final_path)
        else:
            missing_image_ids.append(row["id"])
            affected_style_ids.add(row["style_id"])

    if missing_image_ids:
        timestamp = datetime.now(timezone.utc).isoformat()
        conn = connect_db(db_path)
        try:
            with conn:
                placeholders = ",".join("?" for _ in missing_image_ids)
                conn.execute(
                    f"DELETE FROM generated_images WHERE id IN ({placeholders})",
                    missing_image_ids,
                )
                for style_id in affected_style_ids:
                    _recompute_style(conn, style_id, timestamp)
        finally:
            conn.close()

    for temp_path in root.rglob("*.tmp"):
        temp_path.unlink(missing_ok=True)
    for png_path in root.rglob("*.png"):
        if png_path.resolve() not in referenced:
            png_path.unlink(missing_ok=True)


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
