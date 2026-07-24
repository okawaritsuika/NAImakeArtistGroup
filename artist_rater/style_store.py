import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from png_validator import validate_png
from style_logic import build_artist_prompt, normalize_style_artists, style_hash


MAX_APP_KEY_LENGTH = 8192
MAX_PROMPT_PRESET_LENGTH = 16384
ORPHAN_CLEANUP_AGE_SECONDS = 60 * 60


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


def load_prompt_preset_overrides(settings_path, trusted_root):
    stored = _load_trusted_settings(settings_path, trusted_root).get("prompt_preset_overrides")
    if not isinstance(stored, dict):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(key, str) and re.fullmatch(r"[0-9a-f]{16}", key) and isinstance(value, str)
    }


def save_prompt_preset_override(settings_path, trusted_root, preset_key, quality_prompt):
    if not isinstance(preset_key, str) or not re.fullmatch(r"[0-9a-f]{16}", preset_key):
        raise ValueError("수집 프롬프트 키를 확인해 주세요.")
    if not isinstance(quality_prompt, str):
        raise ValueError("퀄리티 프롬프트는 문자열이어야 합니다.")
    normalized = quality_prompt.strip()
    if not normalized:
        raise ValueError("퀄리티 프롬프트를 입력해 주세요.")
    if len(normalized) > MAX_PROMPT_PRESET_LENGTH:
        raise ValueError("퀄리티 프롬프트가 너무 깁니다.")
    settings = _load_trusted_settings(settings_path, trusted_root)
    overrides = settings.get("prompt_preset_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
    overrides[preset_key] = normalized
    settings["prompt_preset_overrides"] = overrides
    _write_trusted_settings(settings_path, settings, trusted_root)
    return normalized


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
    return final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp")


def _staged_file_candidates(final_path):
    return final_path.parent.glob(f".{final_path.name}.*.tmp")


def _stored_result(row):
    return {
        "style_id": row["style_id"],
        "image_id": row["image_id"],
        "image_path": row["image_path"],
        "artist_prompt": row["artist_prompt"],
        "style_hash": row["style_hash"],
        "seed": row["seed"],
        "width": row["width"],
        "height": row["height"],
        "sampler": row["sampler"],
        "noise_schedule": row["noise_schedule"],
        "steps": row["steps"],
        "scale": row["scale"],
        "cfg_rescale": row["cfg_rescale"],
        "variety_plus": bool(row["variety_plus"]) if row["variety_plus"] is not None else None,
        "skip_cfg_above_sigma": row["skip_cfg_above_sigma"],
        "model": row["model"],
    }


def _find_request(conn, request_id):
    return conn.execute(
        """
        SELECT generated_images.id AS image_id, generated_images.style_id,
               generated_images.image_path, generated_images.artist_prompt,
               generated_images.seed, generated_images.width,
               generated_images.height, generated_images.sampler,
               generated_images.noise_schedule,
               generated_images.steps, generated_images.scale,
               generated_images.cfg_rescale, generated_images.variety_plus,
               generated_images.skip_cfg_above_sigma, generated_images.model,
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


def reserve_generation_request(db_path, request_id, payload_hash):
    timestamp = datetime.now(timezone.utc).isoformat()
    conn = connect_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT payload_hash, status, image_id FROM generation_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO generation_requests (
                    request_id, payload_hash, status, image_id, created_at, updated_at
                ) VALUES (?, ?, 'processing', NULL, ?, ?)
                """,
                (request_id, payload_hash, timestamp, timestamp),
            )
            conn.commit()
            return "reserved", None
        if row["payload_hash"] != payload_hash:
            conn.commit()
            return "mismatch", None
        if row["status"] == "complete" and row["image_id"] is not None:
            result_row = conn.execute(
                """
                SELECT generated_images.id AS image_id, generated_images.style_id,
                       generated_images.image_path, generated_images.artist_prompt,
                       generated_images.seed, generated_images.width,
                       generated_images.height, generated_images.sampler,
                       generated_images.noise_schedule,
                       generated_images.steps, generated_images.scale,
                       generated_images.cfg_rescale, generated_images.variety_plus,
                       generated_images.skip_cfg_above_sigma, generated_images.model,
                       art_styles.style_hash
                FROM generated_images
                JOIN art_styles ON art_styles.id = generated_images.style_id
                WHERE generated_images.id = ?
                """,
                (row["image_id"],),
            ).fetchone()
            if result_row is not None:
                conn.commit()
                return "complete", _stored_result(result_row)
        conn.commit()
        return "processing", None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def release_generation_request(db_path, request_id):
    conn = connect_db(db_path)
    try:
        with conn:
            conn.execute(
                "DELETE FROM generation_requests WHERE request_id = ?",
                (request_id,),
            )
    finally:
        conn.close()


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


def _delete_generated_images(conn, image_ids, style_ids, timestamp):
    image_ids = list(image_ids)
    if not image_ids:
        return
    placeholders = ",".join("?" for _ in image_ids)
    conn.execute(
        f"DELETE FROM generation_requests WHERE image_id IN ({placeholders})",
        image_ids,
    )
    conn.execute(
        f"DELETE FROM generated_images WHERE id IN ({placeholders})",
        image_ids,
    )
    for style_id in set(style_ids):
        _recompute_style(conn, style_id, timestamp)


def _compensate_failed_promotion(db_path, image_id, style_id, timestamp):
    conn = connect_db(db_path)
    try:
        with conn:
            _delete_generated_images(conn, [image_id], [style_id], timestamp)
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
    quality_prompt="",
    original_quality_prompt="",
    excluded_quality_tags=None,
    fixed_prompt="",
    negative_prompt="",
    character_prompts=None,
    combined_prompt="",
    seed=0,
    width=0,
    height=0,
    sampler="",
    noise_schedule="native",
    steps=0,
    scale=0.0,
    cfg_rescale=0.0,
    variety_plus=False,
    skip_cfg_above_sigma=None,
    model="",
):
    request_id = str(request_id or "")
    if not request_id.strip():
        raise ValueError("request_id is required.")
    png_data = validate_png(
        png_bytes,
        expected_width=width if width else None,
        expected_height=height if height else None,
    )

    normalized_artists = normalize_style_artists(artists)
    artists_json = json.dumps(normalized_artists, ensure_ascii=False, separators=(",", ":"))
    character_prompts_json = json.dumps(
        character_prompts or [], ensure_ascii=False, separators=(",", ":")
    )
    excluded_quality_tags_json = json.dumps(
        excluded_quality_tags or [], ensure_ascii=False, separators=(",", ":")
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
            conn.execute(
                """
                UPDATE generation_requests
                SET status = 'complete', image_id = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (existing["image_id"], timestamp, request_id),
            )
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
                    request_id, style_id, image_path, base_prompt, quality_prompt,
                    original_quality_prompt, excluded_quality_tags_json, fixed_prompt, negative_prompt,
                    character_prompts_json, combined_prompt, artist_prompt,
                    artists_json, seed, width, height, sampler, noise_schedule, steps, scale,
                    cfg_rescale, variety_plus, skip_cfg_above_sigma, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    style_id,
                    relative_path,
                    base_prompt,
                    quality_prompt,
                    original_quality_prompt,
                    excluded_quality_tags_json,
                    fixed_prompt,
                    negative_prompt,
                    character_prompts_json,
                    combined_prompt,
                    artist_prompt,
                    artists_json,
                    int(seed),
                    int(width),
                    int(height),
                    sampler,
                    noise_schedule,
                    int(steps),
                    float(scale),
                    float(cfg_rescale),
                    1 if variety_plus else 0,
                    skip_cfg_above_sigma,
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
        conn.execute(
            """
            UPDATE generation_requests
            SET status = 'complete', image_id = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (image_id, timestamp, request_id),
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
            "width": int(width),
            "height": int(height),
            "sampler": sampler,
            "noise_schedule": noise_schedule,
            "steps": int(steps),
            "scale": float(scale),
            "cfg_rescale": float(cfg_rescale),
            "variety_plus": bool(variety_plus),
            "skip_cfg_above_sigma": skip_cfg_above_sigma,
            "model": model,
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
        staged_paths = sorted(
            (path for path in _staged_file_candidates(final_path) if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not final_path.exists() and staged_paths:
            final_path.parent.mkdir(parents=True, exist_ok=True)
            staged_paths[0].replace(final_path)
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
                _delete_generated_images(
                    conn,
                    missing_image_ids,
                    affected_style_ids,
                    timestamp,
                )
        finally:
            conn.close()

    stale_before = time.time() - ORPHAN_CLEANUP_AGE_SECONDS
    for temp_path in root.rglob("*.tmp"):
        if temp_path.stat().st_mtime < stale_before:
            temp_path.unlink(missing_ok=True)
    for png_path in root.rglob("*.png"):
        if (
            png_path.resolve() not in referenced
            and png_path.stat().st_mtime < stale_before
        ):
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


def list_generated_images(db_path):
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """
            SELECT generated_images.*,
                   EXISTS(
                       SELECT 1 FROM confirmed_styles
                       WHERE source_type='generated' AND source_id=generated_images.id
                   ) AS confirmed
            FROM generated_images
            ORDER BY generated_images.created_at DESC, generated_images.id DESC
            """
        ).fetchall()
    finally:
        conn.close()
    images = []
    for row in rows:
        item = dict(row)
        _parse_json_field(item, "artists_json", "artists")
        _parse_json_field(item, "character_prompts_json", "character_prompts")
        _parse_json_field(item, "excluded_quality_tags_json", "excluded_quality_tags")
        item["confirmed"] = bool(item.get("confirmed"))
        if item.get("variety_plus") is not None:
            item["variety_plus"] = bool(item["variety_plus"])
        images.append(item)
    return images


def delete_generated_image_batch(db_path, generated_dir, image_ids):
    unique_ids = list(dict.fromkeys(int(image_id) for image_id in image_ids))
    if not unique_ids:
        return []
    placeholders = ",".join("?" for _ in unique_ids)
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            f"SELECT id,style_id,image_path FROM generated_images WHERE id IN ({placeholders})",
            unique_ids,
        ).fetchall()
        with conn:
            _delete_generated_images(
                conn,
                [row["id"] for row in rows],
                [row["style_id"] for row in rows],
                datetime.now(timezone.utc).isoformat(),
            )
    finally:
        conn.close()
    root = Path(generated_dir).resolve()
    for row in rows:
        target = (root / row["image_path"]).resolve()
        if root in target.parents:
            target.unlink(missing_ok=True)
    return [row["id"] for row in rows]


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


def delete_style(db_path, generated_dir, style_id):
    conn = connect_db(db_path)
    try:
        with conn:
            style = conn.execute(
                "SELECT id FROM art_styles WHERE id = ?", (style_id,)
            ).fetchone()
            if style is None:
                return None
            image_rows = conn.execute(
                "SELECT id, image_path FROM generated_images WHERE style_id = ?",
                (style_id,),
            ).fetchall()
            image_ids = [row["id"] for row in image_rows]
            if image_ids:
                placeholders = ",".join("?" for _ in image_ids)
                conn.execute(
                    f"DELETE FROM generation_requests WHERE image_id IN ({placeholders})",
                    image_ids,
                )
            conn.execute("DELETE FROM generated_images WHERE style_id = ?", (style_id,))
            conn.execute("DELETE FROM art_styles WHERE id = ?", (style_id,))
    finally:
        conn.close()

    root = Path(generated_dir).resolve()
    for row in image_rows:
        target = (root / row["image_path"]).resolve()
        if root not in target.parents:
            continue
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    style_dir = (root / str(int(style_id))).resolve()
    if style_dir.parent == root:
        try:
            style_dir.rmdir()
        except OSError:
            pass
    return {"style_id": int(style_id), "deleted": True}
