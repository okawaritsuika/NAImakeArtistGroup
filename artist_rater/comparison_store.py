import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_comparison_tables(db_path):
    with closing(_connect(db_path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS comparison_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '', fixed_prompt TEXT NOT NULL DEFAULT '',
                character_prompts_json TEXT NOT NULL DEFAULT '[]', width INTEGER NOT NULL, height INTEGER NOT NULL,
                seed_mode TEXT NOT NULL DEFAULT 'none', seed INTEGER,
                defaults_json TEXT NOT NULL DEFAULT '{}', selected_style_ids_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                CHECK(seed_mode IN ('manual','first','none'))
            );
            CREATE TABLE IF NOT EXISTS comparison_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL REFERENCES comparison_groups(id) ON DELETE CASCADE,
                confirmed_style_id INTEGER, style_name TEXT NOT NULL, image_path TEXT NOT NULL, settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, UNIQUE(group_id, confirmed_style_id)
            );
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(comparison_groups)")}
        if "selected_style_ids_json" not in columns:
            connection.execute(
                "ALTER TABLE comparison_groups ADD COLUMN selected_style_ids_json TEXT NOT NULL DEFAULT '[]'"
            )
        groups = connection.execute(
            "SELECT id,selected_style_ids_json FROM comparison_groups"
        ).fetchall()
        for group in groups:
            try:
                selected = json.loads(group["selected_style_ids_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                selected = []
            if selected:
                continue
            style_ids = [row[0] for row in connection.execute(
                "SELECT confirmed_style_id FROM comparison_results WHERE group_id=? AND confirmed_style_id IS NOT NULL ORDER BY id",
                (group["id"],),
            )]
            if style_ids:
                connection.execute(
                    "UPDATE comparison_groups SET selected_style_ids_json=? WHERE id=?",
                    (json.dumps(style_ids), group["id"]),
                )


def _decode(row):
    item = dict(row)
    for key, fallback in (("character_prompts_json", []), ("defaults_json", {}), ("selected_style_ids_json", []), ("settings_json", {})):
        if key in item:
            try: item[key[:-5] if key.endswith("_json") else key] = json.loads(item.pop(key) or json.dumps(fallback))
            except json.JSONDecodeError: item[key[:-5] if key.endswith("_json") else key] = fallback
    return item


def list_groups(db_path):
    with closing(_connect(db_path)) as connection:
        groups = [_decode(row) for row in connection.execute("SELECT * FROM comparison_groups ORDER BY updated_at DESC,id DESC")]
        for group in groups:
            group["results"] = [_decode(row) for row in connection.execute("SELECT * FROM comparison_results WHERE group_id=? ORDER BY id", (group["id"],))]
    return groups


def create_group(db_path, payload):
    name = str(payload.get("name") or "비교군").strip()[:200]
    width, height = int(payload["width"]), int(payload["height"])
    if width < 64 or height < 64: raise ValueError("너비와 높이는 64 이상이어야 합니다.")
    seed_mode = payload.get("seed_mode", "none")
    if seed_mode not in {"manual", "first", "none"}: raise ValueError("시드 방식을 확인해 주세요.")
    seed = payload.get("seed")
    if seed_mode == "manual" and (type(seed) is not int or not 1 <= seed <= 4294967295): raise ValueError("시드를 입력해 주세요.")
    if seed_mode != "manual": seed = None
    prompts = payload.get("character_prompts", [])
    if not isinstance(prompts, list) or any(not isinstance(item, str) for item in prompts): raise ValueError("캐릭터 프롬프트를 확인해 주세요.")
    if len([item for item in prompts if item.strip()]) > 6: raise ValueError("캐릭터 프롬프트는 최대 6개까지 추가할 수 있습니다.")
    style_ids = normalize_style_ids(payload.get("style_ids"))
    timestamp = datetime.now(timezone.utc).isoformat()
    with closing(_connect(db_path)) as connection, connection:
        cursor = connection.execute("INSERT INTO comparison_groups(name,fixed_prompt,character_prompts_json,width,height,seed_mode,seed,defaults_json,selected_style_ids_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (name, str(payload.get("fixed_prompt") or "").strip(), json.dumps([item.strip() for item in prompts if item.strip()], ensure_ascii=False), width, height, seed_mode, seed, json.dumps(payload.get("defaults") or {}, ensure_ascii=False), json.dumps(style_ids), timestamp, timestamp))
        return cursor.lastrowid


def normalize_style_ids(values):
    if not isinstance(values, list) or any(type(value) is not int or value < 1 for value in values):
        raise ValueError("확정 그림체 선택을 확인해 주세요.")
    return list(dict.fromkeys(values))


def update_group_style_ids(db_path, group_id, style_ids):
    selected = normalize_style_ids(style_ids)
    timestamp = datetime.now(timezone.utc).isoformat()
    with closing(_connect(db_path)) as connection, connection:
        cursor = connection.execute(
            "UPDATE comparison_groups SET selected_style_ids_json=?,updated_at=? WHERE id=?",
            (json.dumps(selected), timestamp, group_id),
        )
    return cursor.rowcount > 0


def get_group(db_path, group_id):
    return next((item for item in list_groups(db_path) if item["id"] == group_id), None)


def save_result(db_path, image_dir, group_id, style_id, style_name, png_bytes, settings):
    root = Path(image_dir).resolve(); root.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"; target = (root / filename).resolve()
    if target.parent != root:
        raise ValueError("Comparison image path is invalid.")
    target.write_bytes(png_bytes)
    timestamp = datetime.now(timezone.utc).isoformat()
    old_path = ""
    try:
        with closing(_connect(db_path)) as connection, connection:
            existing = connection.execute(
                "SELECT image_path FROM comparison_results WHERE group_id=? AND confirmed_style_id=?",
                (group_id, style_id),
            ).fetchone()
            old_path = existing["image_path"] if existing else ""
            connection.execute("""
                INSERT INTO comparison_results(group_id,confirmed_style_id,style_name,image_path,settings_json,created_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(group_id,confirmed_style_id) DO UPDATE SET
                    style_name=excluded.style_name,image_path=excluded.image_path,
                    settings_json=excluded.settings_json,created_at=excluded.created_at
            """, (group_id, style_id, style_name, filename, json.dumps(settings, ensure_ascii=False), timestamp))
            connection.execute("UPDATE comparison_groups SET updated_at=? WHERE id=?", (timestamp, group_id))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    if old_path and old_path != filename:
        old_target = (root / old_path).resolve()
        if old_target.parent == root:
            old_target.unlink(missing_ok=True)
    return filename


def set_group_seed(db_path, group_id, seed):
    with closing(_connect(db_path)) as connection, connection:
        connection.execute("UPDATE comparison_groups SET seed=? WHERE id=?", (seed, group_id))


def remove_group_results(db_path, image_dir, group_id, keep_style_ids):
    keep = {int(value) for value in keep_style_ids}
    with closing(_connect(db_path)) as connection, connection:
        rows = connection.execute(
            "SELECT id,confirmed_style_id,image_path FROM comparison_results WHERE group_id=?",
            (group_id,),
        ).fetchall()
        removed = [row for row in rows if row["confirmed_style_id"] not in keep]
        if removed:
            placeholders = ",".join("?" for _ in removed)
            connection.execute(
                f"DELETE FROM comparison_results WHERE id IN ({placeholders})",
                [row["id"] for row in removed],
            )
    root = Path(image_dir).resolve()
    for row in removed:
        target = (root / row["image_path"]).resolve()
        if target.parent == root:
            target.unlink(missing_ok=True)
    return [row["id"] for row in removed]


def delete_result(db_path, image_dir, result_id):
    with closing(_connect(db_path)) as connection, connection:
        row = connection.execute("SELECT image_path FROM comparison_results WHERE id=?", (result_id,)).fetchone()
        if not row: return False
        connection.execute("DELETE FROM comparison_results WHERE id=?", (result_id,))
    (Path(image_dir) / row["image_path"]).unlink(missing_ok=True); return True


def delete_group(db_path, image_dir, group_id):
    with closing(_connect(db_path)) as connection, connection:
        exists = connection.execute("SELECT 1 FROM comparison_groups WHERE id=?", (group_id,)).fetchone()
        if not exists:
            return False
        rows = connection.execute("SELECT image_path FROM comparison_results WHERE group_id=?", (group_id,)).fetchall()
        connection.execute("DELETE FROM comparison_groups WHERE id=?", (group_id,))
    root = Path(image_dir).resolve()
    for row in rows:
        target = (root / row["image_path"]).resolve()
        if target.parent == root:
            target.unlink(missing_ok=True)
    return True
