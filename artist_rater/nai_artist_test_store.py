"""Persistence helpers for resumable NovelAI artist test batches.

The tables in this module are deliberately separate from ``ratings``.  A
Danbooru rating describes the artist, while an NAI artist-test rating describes
the result of a particular local generation test.
"""

import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


MARKER = "{{artist}}"
MIN_IMAGES_PER_ARTIST = 1
MAX_IMAGES_PER_ARTIST = 100
MAX_TOTAL_ITEMS = 10000
MAX_DELAY_SECONDS = 24 * 60 * 60
TEST_STATUSES = {"pending", "running", "paused", "cancelled", "completed"}
ITEM_STATUSES = {"pending", "processing", "complete", "cancelled"}


def now_text():
    return datetime.now(timezone.utc).isoformat()


def init_nai_artist_test_tables(db_path):
    """Create or migrate only the tables owned by this feature."""
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nai_artist_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                images_per_artist INTEGER NOT NULL,
                delay_seconds REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','paused','cancelled','completed')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nai_artist_test_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                artist_tag TEXT NOT NULL,
                danbooru_score INTEGER,
                ordinal INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','processing','complete','cancelled')),
                request_id TEXT NOT NULL UNIQUE,
                generated_image_id INTEGER,
                prompt_index INTEGER NOT NULL DEFAULT 0,
                prompt_template TEXT NOT NULL DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(test_id) REFERENCES nai_artist_tests(id) ON DELETE CASCADE,
                FOREIGN KEY(generated_image_id) REFERENCES generated_images(id) ON DELETE SET NULL,
                UNIQUE(test_id, ordinal)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nai_artist_test_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                artist_tag TEXT NOT NULL,
                score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(test_id) REFERENCES nai_artist_tests(id) ON DELETE CASCADE,
                UNIQUE(test_id, artist_tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS nai_artist_test_images (
                test_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                generated_image_id INTEGER NOT NULL,
                artist_tag TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(test_id, item_id),
                UNIQUE(generated_image_id),
                FOREIGN KEY(test_id) REFERENCES nai_artist_tests(id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES nai_artist_test_items(id) ON DELETE CASCADE,
                FOREIGN KEY(generated_image_id) REFERENCES generated_images(id) ON DELETE CASCADE
            )
            """
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(nai_artist_test_items)").fetchall()}
        for column, definition in (
            ("image_score", "INTEGER CHECK(image_score BETWEEN 1 AND 5)"),
            ("rated_at", "TEXT"),
            ("generation_requested_at", "TEXT"),
            ("prompt_index", "INTEGER NOT NULL DEFAULT 0"),
            ("prompt_template", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE nai_artist_test_items ADD COLUMN {column} {definition}")


def validate_marker(base_prompt, marker=MARKER):
    if not isinstance(base_prompt, str):
        raise ValueError("base_prompt must be a string.")
    if base_prompt.count(marker) != 1:
        raise ValueError("base_prompt must contain exactly one {{artist}} marker.")


def validate_test_config(config):
    if not isinstance(config, dict):
        raise ValueError("generation settings must be an object.")
    validate_marker(config.get("base_prompt", ""))
    for key in ("negative_prompt", "fixed_prompt", "leading_prompt", "quality_prompt", "original_quality_prompt"):
        value = config.get(key, "")
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string.")
        if MARKER in value:
            raise ValueError("{{artist}} is only allowed in base_prompt.")
    characters = config.get("character_prompts", [])
    if not isinstance(characters, list) or any(not isinstance(value, str) for value in characters):
        raise ValueError("character_prompts must be a list of strings.")
    if any(MARKER in value for value in characters):
        raise ValueError("{{artist}} is only allowed in base_prompt.")
    return config


def validate_images_per_artist(value):
    if type(value) is not int or not MIN_IMAGES_PER_ARTIST <= value <= MAX_IMAGES_PER_ARTIST:
        raise ValueError("images_per_artist must be an integer from 1 to 100.")
    return value


def normalize_prompt_variants(config, images_per_artist=None, prompt_variants=None):
    """Return validated prompt/count rows while preserving legacy inputs."""
    raw = prompt_variants
    if raw is None and isinstance(config, dict):
        raw = config.get("prompt_variants")
    if raw is None:
        raw = [{"prompt": config.get("base_prompt", ""), "images_per_artist": images_per_artist}]
    if not isinstance(raw, list) or not raw:
        raise ValueError("prompt_variants must contain at least one prompt.")
    variants = []
    total_per_artist = 0
    for index, variant in enumerate(raw):
        if isinstance(variant, str):
            variant = {"prompt": variant, "images_per_artist": images_per_artist}
        if not isinstance(variant, dict):
            raise ValueError("prompt_variants must be objects.")
        prompt = variant.get("prompt", variant.get("base_prompt", ""))
        validate_marker(prompt)
        count = variant.get("images_per_artist", variant.get("count"))
        if count is None and images_per_artist is not None:
            count = images_per_artist
        count = validate_images_per_artist(count)
        total_per_artist += count
        if total_per_artist > MAX_TOTAL_ITEMS:
            raise ValueError("prompt_variants total is too large.")
        variants.append({"prompt": prompt, "images_per_artist": count, "prompt_index": index})
    return variants


def validate_delay_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("delay_seconds must be a finite number from 0 to 86400.")
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= MAX_DELAY_SECONDS:
        raise ValueError("delay_seconds must be a finite number from 0 to 86400.")
    return value


def _json(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def _test_item(row):
    item = dict(row)
    return item


def _test_row(row):
    if row is None:
        return None
    item = dict(row)
    item["config"] = _json(item.pop("config_json", "{}"))
    return item


def _update_status(conn, test_id, status, timestamp=None):
    if status not in TEST_STATUSES:
        raise ValueError("Invalid NAI artist test status.")
    timestamp = timestamp or now_text()
    completed_at = timestamp if status in {"completed", "cancelled"} else None
    conn.execute(
        "UPDATE nai_artist_tests SET status=?, updated_at=?, completed_at=COALESCE(?, completed_at) WHERE id=?",
        (status, timestamp, completed_at, test_id),
    )


def create_test(db_path, name, config, artists, images_per_artist, delay_seconds, prompt_variants=None):
    name = str(name or "").strip()
    if not name or len(name) > 200:
        raise ValueError("name must be a nonempty string up to 200 characters.")
    config = dict(config or {})
    raw_variants = prompt_variants if prompt_variants is not None else config.get("prompt_variants")
    if not config.get("base_prompt") and isinstance(raw_variants, list) and raw_variants:
        first = raw_variants[0] if isinstance(raw_variants[0], dict) else {"prompt": raw_variants[0]}
        config["base_prompt"] = first.get("prompt", first.get("base_prompt", ""))
    config = validate_test_config(config)
    images_per_artist = validate_images_per_artist(images_per_artist)
    variants = normalize_prompt_variants(config, images_per_artist, prompt_variants)
    delay_seconds = validate_delay_seconds(delay_seconds)
    if not isinstance(artists, list) or not artists:
        raise ValueError("At least one artist is required.")
    normalized_artists = []
    seen = set()
    for artist in artists:
        if not isinstance(artist, dict):
            raise ValueError("artists must be objects.")
        tag = str(artist.get("artist_tag", artist.get("artist", "")) or "").strip()
        key = tag.replace("_", " ").casefold()
        if not tag or key in seen:
            raise ValueError("artists must contain unique nonempty tags.")
        score = artist.get("danbooru_score", artist.get("score"))
        if score is not None and (type(score) is not int or not 1 <= score <= 5):
            raise ValueError("danbooru_score must be an integer from 1 to 5.")
        normalized_artists.append((tag, score))
        seen.add(key)
    total_items = len(normalized_artists) * sum(variant["images_per_artist"] for variant in variants)
    if total_items < 1 or total_items > MAX_TOTAL_ITEMS:
        raise ValueError("The total number of test images is too large.")
    config["prompt_variants"] = [{key: value for key, value in variant.items() if key != "prompt_index"} for variant in variants]
    config["base_prompt"] = variants[0]["prompt"]
    config["images_per_artist"] = images_per_artist
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.execute(
            """
            INSERT INTO nai_artist_tests
                (name, config_json, images_per_artist, delay_seconds, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (name, json.dumps(config, ensure_ascii=False, separators=(",", ":")), images_per_artist, delay_seconds, timestamp, timestamp),
        )
        test_id = cursor.lastrowid
        ordinal = 0
        for tag, score in normalized_artists:
            for variant in variants:
                for _ in range(variant["images_per_artist"]):
                    ordinal += 1
                    conn.execute(
                        """
                        INSERT INTO nai_artist_test_items
                            (test_id, artist_tag, danbooru_score, ordinal, prompt_index, prompt_template,
                             request_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (test_id, tag, score, ordinal, variant["prompt_index"], variant["prompt"],
                         f"nai-test-{test_id}-{ordinal}", timestamp, timestamp),
                    )
    return get_test(db_path, test_id)


def append_test_items(db_path, test_id, prompt_variants, target_scope="all"):
    """Append prompt rows to an existing batch without rewriting its history."""
    if target_scope not in {"all", "remaining"}:
        raise ValueError("target_scope must be all or remaining.")
    variants = normalize_prompt_variants({}, None, prompt_variants)
    timestamp = now_text()
    appended_count = 0
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        test = conn.execute("SELECT * FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            conn.rollback()
            raise LookupError("NAI artist test was not found.")
        if test["status"] == "running":
            active_generation = conn.execute(
                "SELECT 1 FROM nai_artist_test_items WHERE test_id=? AND status!='complete' LIMIT 1",
                (test_id,),
            ).fetchone()
            if active_generation is not None:
                conn.rollback()
                raise RuntimeError("실행 중인 테스트에는 프롬프트를 추가할 수 없습니다. 먼저 일시정지하세요.")
        existing_items = conn.execute(
            "SELECT artist_tag, danbooru_score, status FROM nai_artist_test_items WHERE test_id=? ORDER BY ordinal",
            (test_id,),
        ).fetchall()
        artists = []
        seen = set()
        for row in existing_items:
            key = row["artist_tag"].replace("_", " ").casefold()
            if target_scope == "remaining":
                has_remaining = any(
                    candidate["artist_tag"].replace("_", " ").casefold() == key
                    and candidate["status"] in {"pending", "processing"}
                    for candidate in existing_items
                )
                if not has_remaining:
                    continue
            if key not in seen:
                seen.add(key)
                artists.append((row["artist_tag"], row["danbooru_score"]))
        if not artists:
            conn.rollback()
            raise ValueError("선택 범위에 추가할 작가가 없습니다.")
        current_count = int(conn.execute("SELECT COUNT(*) FROM nai_artist_test_items WHERE test_id=?", (test_id,)).fetchone()[0])
        additional_count = len(artists) * sum(item["images_per_artist"] for item in variants)
        if current_count + additional_count > MAX_TOTAL_ITEMS:
            conn.rollback()
            raise ValueError("The total number of test images is too large.")
        config = _json(test["config_json"])
        stored_variants = config.get("prompt_variants")
        if not isinstance(stored_variants, list):
            stored_variants = [{"prompt": config.get("base_prompt", ""), "images_per_artist": test["images_per_artist"]}]
        prompt_index_start = len(stored_variants)
        stored_variants.extend(
            {"prompt": item["prompt"], "images_per_artist": item["images_per_artist"]}
            for item in variants
        )
        config["prompt_variants"] = stored_variants
        next_ordinal = int(conn.execute("SELECT COALESCE(MAX(ordinal), 0) FROM nai_artist_test_items WHERE test_id=?", (test_id,)).fetchone()[0])
        for artist_tag, score in artists:
            for variant_offset, variant in enumerate(variants):
                prompt_index = prompt_index_start + variant_offset
                for _ in range(variant["images_per_artist"]):
                    next_ordinal += 1
                    conn.execute(
                        """
                        INSERT INTO nai_artist_test_items
                            (test_id, artist_tag, danbooru_score, ordinal, prompt_index, prompt_template,
                             request_id, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (test_id, artist_tag, score, next_ordinal, prompt_index, variant["prompt"],
                         f"nai-test-{test_id}-{next_ordinal}", timestamp, timestamp),
                    )
                    appended_count += 1
        conn.execute(
            "UPDATE nai_artist_tests SET config_json=?, status='paused', completed_at=NULL, updated_at=? WHERE id=?",
            (json.dumps(config, ensure_ascii=False, separators=(",", ":")), timestamp, test_id),
        )
        conn.commit()
    result = get_test(db_path, test_id)
    result["appended_count"] = appended_count
    return result


def append_test_artist(db_path, test_id, artist_tag, danbooru_score=None):
    """Add one author using the test's stored prompt plan.

    This is deliberately separate from append_test_items: adding an author
    must not alter prompt variants or duplicate an existing normalized author.
    All rows start pending; the caller may claim exactly one item immediately.
    """
    artist_tag = str(artist_tag or "").strip()
    artist_key = " ".join(artist_tag.replace("_", " ").split()).casefold()
    if not artist_key:
        raise ValueError("artist_tag is required.")
    if danbooru_score is not None and (type(danbooru_score) is not int or not 1 <= danbooru_score <= 5):
        raise ValueError("danbooru_score must be an integer from 1 to 5.")
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        test = conn.execute("SELECT * FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            conn.rollback()
            raise LookupError("NAI artist test was not found.")
        if test["status"] == "running":
            conn.rollback()
            raise RuntimeError("실행 중인 테스트에는 작가를 추가할 수 없습니다. 먼저 일시정지하세요.")
        existing = conn.execute(
            "SELECT artist_tag FROM nai_artist_test_items WHERE test_id=?",
            (test_id,),
        ).fetchall()
        if any(" ".join(row["artist_tag"].replace("_", " ").split()).casefold() == artist_key for row in existing):
            conn.rollback()
            raise ValueError("이미 테스트에 포함된 작가입니다.")
        config = _json(test["config_json"])
        variants = config.get("prompt_variants")
        if not isinstance(variants, list) or not variants:
            variants = [{"prompt": config.get("base_prompt", ""), "images_per_artist": test["images_per_artist"]}]
        normalized = normalize_prompt_variants(config, test["images_per_artist"], variants)
        current_count = int(conn.execute("SELECT COUNT(*) FROM nai_artist_test_items WHERE test_id=?", (test_id,)).fetchone()[0])
        additional = sum(item["images_per_artist"] for item in normalized)
        if current_count + additional > MAX_TOTAL_ITEMS:
            conn.rollback()
            raise ValueError("The total number of test images is too large.")
        next_ordinal = int(conn.execute("SELECT COALESCE(MAX(ordinal),0) FROM nai_artist_test_items WHERE test_id=?", (test_id,)).fetchone()[0])
        first_item_id = None
        for variant in normalized:
            for _ in range(variant["images_per_artist"]):
                next_ordinal += 1
                cursor = conn.execute(
                    """INSERT INTO nai_artist_test_items
                       (test_id,artist_tag,danbooru_score,ordinal,prompt_index,prompt_template,request_id,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (test_id, artist_tag, danbooru_score, next_ordinal, variant["prompt_index"], variant["prompt"],
                     f"nai-test-{test_id}-{next_ordinal}", timestamp, timestamp),
                )
                first_item_id = first_item_id or cursor.lastrowid
        conn.execute(
            "UPDATE nai_artist_tests SET status='paused',completed_at=NULL,updated_at=? WHERE id=?",
            (timestamp, test_id),
        )
        conn.commit()
    result = get_test(db_path, test_id)
    result["first_item_id"] = first_item_id
    return result


def prepare_test_artist_item(db_path, test_id, artist_tag, danbooru_score=None):
    """Return exactly one pending item for an author, appending only if new."""
    artist_tag = str(artist_tag or "").strip()
    artist_key = " ".join(artist_tag.replace("_", " ").split()).casefold()
    if not artist_key:
        raise ValueError("artist_tag is required.")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        test = conn.execute("SELECT status FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            raise LookupError("NAI artist test was not found.")
        matching = conn.execute(
            "SELECT artist_tag FROM nai_artist_test_items WHERE test_id=?",
            (test_id,),
        ).fetchall()
        existing = next(
            (row for row in matching if " ".join(str(row["artist_tag"] or "").replace("_", " ").split()).casefold() == artist_key),
            None,
        )
        if existing is not None:
            pending = next(
                (
                    row for row in conn.execute(
                        "SELECT id,artist_tag FROM nai_artist_test_items WHERE test_id=? AND status='pending' ORDER BY ordinal",
                        (test_id,),
                    ).fetchall()
                    if " ".join(str(row["artist_tag"] or "").replace("_", " ").split()).casefold() == artist_key
                ),
                None,
            )
            if pending is None:
                raise ValueError("이 작가의 대기 중인 생성 항목이 없습니다.")
            result = get_test(db_path, test_id)
            result["first_item_id"] = pending["id"]
            result["appended_count"] = 0
            return result
    result = append_test_artist(db_path, test_id, artist_tag, danbooru_score)
    result["appended_count"] = len([
        item for item in result.get("items", [])
        if item.get("artist_tag") == artist_tag and item.get("status") == "pending"
    ])
    return result


def list_tests(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT t.*, COUNT(i.id) AS total_count,
                   SUM(CASE WHEN i.status='complete' THEN 1 ELSE 0 END) AS completed_count,
                   SUM(CASE WHEN i.status='complete' AND i.image_score IS NOT NULL THEN 1 ELSE 0 END) AS rated_count,
                   SUM(CASE WHEN i.status='complete' THEN 1 ELSE 0 END) AS generated_count,
                   SUM(CASE WHEN i.status!='complete' OR i.image_score IS NULL THEN 1 ELSE 0 END) AS remaining_count,
                   (SELECT g.image_path FROM nai_artist_test_items ci
                    JOIN generated_images g ON g.id=ci.generated_image_id
                    WHERE ci.test_id=t.id AND ci.status='complete'
                    ORDER BY ci.ordinal LIMIT 1) AS cover_image_path
            FROM nai_artist_tests t LEFT JOIN nai_artist_test_items i ON i.test_id=t.id
            GROUP BY t.id ORDER BY t.updated_at DESC, t.id DESC
            """
        ).fetchall()
    result = []
    for row in rows:
        item = _test_row(row)
        item["generated_count"] = int(item.get("generated_count") or 0)
        item["rated_count"] = int(item.get("rated_count") or 0)
        item["completed_count"] = int(item.get("completed_count") or 0)
        item["remaining_count"] = int(item.get("remaining_count") or 0)
        item["cover_image_url"] = f"/generated/{item['cover_image_path']}" if item.get("cover_image_path") else ""
        result.append(item)
    return result


def get_test_artist_source(db_path, test_id):
    """Read one test as an author-source payload for other read APIs."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        test = conn.execute(
            "SELECT id,name,status,config_json,created_at,updated_at FROM nai_artist_tests WHERE id=?",
            (int(test_id),),
        ).fetchone()
        if test is None:
            return None
        items = conn.execute(
            "SELECT artist_tag FROM nai_artist_test_items WHERE test_id=? ORDER BY ordinal,id",
            (int(test_id),),
        ).fetchall()
        ratings = conn.execute(
            "SELECT artist_tag,score,updated_at,id FROM nai_artist_test_ratings WHERE test_id=? ORDER BY updated_at DESC,id DESC",
            (int(test_id),),
        ).fetchall()
    score_by_key = {}
    for row in ratings:
        key = " ".join(str(row["artist_tag"] or "").replace("_", " ").split()).casefold()
        score_by_key.setdefault(key, row["score"])
    artists = {}
    for row in items:
        artist_tag = str(row["artist_tag"] or "").strip()
        key = " ".join(artist_tag.replace("_", " ").split()).casefold()
        if not key:
            continue
        artist = artists.setdefault(
            key,
            {"artist_key": key, "artist_tag": artist_tag, "image_count": 0},
        )
        artist["image_count"] += 1
    for key, artist in artists.items():
        artist["score"] = score_by_key.get(key)
    return {
        "source_type": "nai_test",
        "source_id": str(test["id"]),
        "label": test["name"],
        "name": test["name"],
        "status": test["status"],
        "created_at": test["created_at"] or "",
        "updated_at": test["updated_at"] or "",
        "config": _json(test["config_json"]),
        "artists": list(artists.values()),
    }


# Keep the read helper easy to locate beside the existing get_test API.
read_test_artist_source = get_test_artist_source


def list_generated_image_sources(db_path):
    """Map generated image ids to their NAI artist-test context.

    ``nai_artist_test_images`` is the canonical link table.  The item-table
    fallback keeps older records discoverable when a completed item was saved
    before that link row was introduced.
    """
    try:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT link.generated_image_id, link.test_id, test.name AS test_name,
                       link.artist_tag, link.created_at AS linked_at
                FROM nai_artist_test_images link
                JOIN nai_artist_tests test ON test.id=link.test_id
                WHERE link.generated_image_id IS NOT NULL
                UNION ALL
                SELECT item.generated_image_id, item.test_id, test.name AS test_name,
                       item.artist_tag, item.updated_at AS linked_at
                FROM nai_artist_test_items item
                JOIN nai_artist_tests test ON test.id=item.test_id
                WHERE item.generated_image_id IS NOT NULL
                ORDER BY linked_at DESC
                """
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "nai_artist_test" in str(exc):
            return {}
        raise
    sources = {}
    for row in rows:
        image_id = int(row["generated_image_id"])
        if image_id in sources:
            continue
        sources[image_id] = {
            "source_type": "nai_artist_test",
            "source_label": "NAI 작가 테스트",
            "source_name": str(row["test_name"] or "NAI 작가 테스트"),
            "source_id": int(row["test_id"]),
            "source_artist_tag": str(row["artist_tag"] or ""),
        }
    return sources


def list_artist_history(db_path, query=""):
    """Return cross-test generated samples grouped by artist for read-only browsing."""
    query = str(query or "").strip().casefold()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT i.*, t.name AS test_name, t.config_json, t.delay_seconds,
                   g.image_path, r.score AS nai_direct_score
            FROM nai_artist_test_items i
            JOIN nai_artist_tests t ON t.id=i.test_id
            JOIN generated_images g ON g.id=i.generated_image_id
            LEFT JOIN nai_artist_test_ratings r ON r.test_id=i.test_id AND r.artist_tag=i.artist_tag
            WHERE i.status='complete' AND i.generated_image_id IS NOT NULL
            ORDER BY i.artist_tag COLLATE NOCASE ASC, t.updated_at DESC, i.ordinal ASC
            """
        ).fetchall()
    items = []
    groups = {}
    for row in rows:
        item = dict(row)
        if query and query not in item["artist_tag"].casefold():
            continue
        config = _json(item.pop("config_json", "{}"))
        prompt = item.get("prompt_template") or config.get("base_prompt", "")
        item["config"] = config
        item["prompt_template"] = prompt
        item["effective_prompt"] = prompt.replace(MARKER, item["artist_tag"])
        item["image_url"] = f"/generated/{item['image_path']}" if item.get("image_path") else ""
        items.append(item)
        group = groups.setdefault(item["artist_tag"], {"artist_tag": item["artist_tag"], "image_count": 0, "rated_count": 0, "scores": [], "cover_image_path": item.get("image_path") or ""})
        group["image_count"] += 1
        if item.get("image_score") is not None:
            group["rated_count"] += 1
            group["scores"].append(float(item["image_score"]))
    artists = []
    for group in groups.values():
        scores = group.pop("scores")
        group["average"] = sum(scores) / len(scores) if scores else None
        group["cover_image_url"] = f"/generated/{group['cover_image_path']}" if group.get("cover_image_path") else ""
        artists.append(group)
    return {"artists": artists, "items": items}


def get_test(db_path, test_id):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if row is None:
            return None
        test = _test_row(row)
        stored_variants = test["config"].get("prompt_variants")
        if not isinstance(stored_variants, list) or not stored_variants:
            stored_variants = [{"prompt": test["config"].get("base_prompt", ""), "images_per_artist": test.get("images_per_artist", 1)}]
            test["config"]["prompt_variants"] = stored_variants
        items = conn.execute(
            """
            SELECT i.*, r.score AS nai_direct_score, g.image_path
            FROM nai_artist_test_items i
            LEFT JOIN nai_artist_test_ratings r ON r.test_id=i.test_id AND r.artist_tag=i.artist_tag
            LEFT JOIN generated_images g ON g.id=i.generated_image_id
            WHERE i.test_id=? ORDER BY i.ordinal
            """,
            (test_id,),
        ).fetchall()
        test["items"] = [_test_item(item) for item in items]
        for item in test["items"]:
            if not item.get("prompt_template"):
                variant = next((candidate for index, candidate in enumerate(stored_variants) if int(candidate.get("prompt_index", index)) == int(item.get("prompt_index") or 0)), stored_variants[0])
                item["prompt_template"] = variant.get("prompt", test["config"].get("base_prompt", ""))
        test["artists"] = []
        seen = set()
        for item in test["items"]:
            if item["artist_tag"] in seen:
                continue
            seen.add(item["artist_tag"])
            test["artists"].append({
                "artist_tag": item["artist_tag"],
                "danbooru_score": item["danbooru_score"],
                "nai_direct_score": item["nai_direct_score"],
                "rated_image_count": sum(
                    candidate["artist_tag"] == item["artist_tag"] and candidate["image_score"] is not None
                    for candidate in test["items"]
                ),
            })
        test["total_count"] = len(test["items"])
        test["generated_count"] = sum(item["status"] == "complete" for item in test["items"])
        test["completed_count"] = test["generated_count"]
        test["rated_count"] = sum(item["status"] == "complete" and item["image_score"] is not None for item in test["items"])
        test["remaining_count"] = sum(item["status"] != "complete" or item["image_score"] is None for item in test["items"])
        return test


def delete_test(db_path, test_id):
    """Delete one test batch and only its foreign-key-owned records.

    Generated images are deliberately not deleted here.  The item reference
    is owned by the batch and is removed by the FK cascade, while the shared
    ``generated_images`` row remains available to normal history management.
    """
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if row is None:
            conn.rollback()
            return False
        if row[0] == "running":
            conn.rollback()
            raise RuntimeError("실행 중인 테스트는 삭제할 수 없습니다. 먼저 일시정지하거나 중단하세요.")
        conn.execute("DELETE FROM nai_artist_tests WHERE id=?", (test_id,))
        conn.commit()
    return True


def recover_processing_items(db_path):
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("UPDATE nai_artist_test_items SET status='pending', updated_at=? WHERE status='processing'", (timestamp,))
        conn.execute("UPDATE nai_artist_tests SET status='paused', updated_at=? WHERE status='running'", (timestamp,))


def set_status(db_path, test_id, status):
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        row = conn.execute("SELECT status FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if row is None:
            return None
        if status in {"running", "pending"}:
            conn.execute("UPDATE nai_artist_test_items SET status='pending', updated_at=? WHERE test_id=? AND status IN ('processing','cancelled')", (timestamp, test_id))
            conn.execute(
                "UPDATE nai_artist_tests SET status=?, started_at=COALESCE(started_at, ?), updated_at=?, completed_at=NULL WHERE id=?",
                (status, timestamp, timestamp, test_id),
            )
        elif status == "paused":
            conn.execute("UPDATE nai_artist_test_items SET status='pending', updated_at=? WHERE test_id=? AND status='processing'", (timestamp, test_id))
            _update_status(conn, test_id, status, timestamp)
        elif status == "cancelled":
            # Cancellation is a resumable stop.  Completed samples remain
            # complete and all unfinished work remains (or becomes) pending.
            conn.execute("UPDATE nai_artist_test_items SET status='pending', updated_at=? WHERE test_id=? AND status='processing'", (timestamp, test_id))
            _update_status(conn, test_id, status, timestamp)
        else:
            _update_status(conn, test_id, status, timestamp)
    return get_test(db_path, test_id)


def claim_next_item(db_path, test_id):
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        test = conn.execute("SELECT * FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            conn.rollback()
            return None, "missing"
        if test["status"] not in {"running", "pending"}:
            conn.commit()
            return None, test["status"]
        conn.execute("UPDATE nai_artist_test_items SET status='pending', updated_at=? WHERE test_id=? AND status='processing'", (timestamp, test_id))
        item = conn.execute(
            "SELECT * FROM nai_artist_test_items WHERE test_id=? AND status='pending' ORDER BY ordinal LIMIT 1",
            (test_id,),
        ).fetchone()
        if item is None:
            awaiting = conn.execute(
                "SELECT * FROM nai_artist_test_items WHERE test_id=? AND status='complete' AND image_score IS NULL ORDER BY ordinal LIMIT 1",
                (test_id,),
            ).fetchone()
            if awaiting is not None:
                conn.commit()
                return dict(awaiting), "awaiting_rating"
            _update_status(conn, test_id, "completed", timestamp)
            conn.commit()
            return None, "completed"
        conn.execute(
            "UPDATE nai_artist_test_items SET status='processing', error='', generation_requested_at=?, updated_at=? WHERE id=?",
            (timestamp, timestamp, item["id"]),
        )
        conn.execute("UPDATE nai_artist_tests SET status='running', started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?", (timestamp, timestamp, test_id))
        claimed = conn.execute("SELECT * FROM nai_artist_test_items WHERE id=?", (item["id"],)).fetchone()
        conn.commit()
        return dict(claimed), "claimed"


def claim_specific_item(db_path, test_id, item_id):
    """Claim one pending item by id for the group "generate first" action."""
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        test = conn.execute("SELECT * FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            conn.rollback()
            return None, "missing"
        if test["status"] == "cancelled":
            conn.rollback()
            return None, test["status"]
        item = conn.execute(
            "SELECT * FROM nai_artist_test_items WHERE id=? AND test_id=? AND status='pending'",
            (item_id, test_id),
        ).fetchone()
        if item is None:
            conn.rollback()
            return None, "missing_item"
        conn.execute(
            "UPDATE nai_artist_test_items SET status='processing',error='',generation_requested_at=?,updated_at=? WHERE id=?",
            (timestamp, timestamp, item_id),
        )
        conn.execute(
            "UPDATE nai_artist_tests SET status='running',started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
            (timestamp, timestamp, test_id),
        )
        claimed = conn.execute("SELECT * FROM nai_artist_test_items WHERE id=?", (item_id,)).fetchone()
        conn.commit()
        return dict(claimed), "claimed"


def complete_item(db_path, test_id, item_id, generated_image_id):
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        row = conn.execute("SELECT artist_tag, status FROM nai_artist_test_items WHERE id=? AND test_id=?", (item_id, test_id)).fetchone()
        if row is None:
            return None
        if row[1] == "complete":
            pass
        else:
            conn.execute("UPDATE nai_artist_test_items SET status='complete', generated_image_id=?, error='', updated_at=? WHERE id=? AND test_id=?", (generated_image_id, timestamp, item_id, test_id))
            conn.execute(
                "INSERT OR IGNORE INTO nai_artist_test_images(test_id,item_id,generated_image_id,artist_tag,created_at) VALUES(?,?,?,?,?)",
                (test_id, item_id, generated_image_id, row[0], timestamp),
            )
            pending = conn.execute(
                "SELECT 1 FROM nai_artist_test_items WHERE test_id=? AND (status!='complete' OR image_score IS NULL) LIMIT 1",
                (test_id,),
            ).fetchone()
            if pending is None:
                _update_status(conn, test_id, "completed", timestamp)
            else:
                conn.execute("UPDATE nai_artist_tests SET status='running', completed_at=NULL, updated_at=? WHERE id=?", (timestamp, test_id))
    result = get_test(db_path, test_id)
    # Keep linked author groups current even when a caller completes an item
    # directly through the store rather than the Flask generation route.
    try:
        from style_group_store import sync_style_group_generated_image
        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute(
                "SELECT artist_tag FROM nai_artist_test_items WHERE id=? AND test_id=?",
                (item_id, test_id),
            ).fetchone()
            image = conn.execute(
                "SELECT image_path FROM generated_images WHERE id=?",
                (generated_image_id,),
            ).fetchone()
        if row and image:
            sync_style_group_generated_image(
                db_path,
                Path(db_path).parent / "style_group_images",
                test_id,
                row[0],
                generated_image_id=generated_image_id,
                image_path=image[0],
            )
    except (ImportError, OSError, sqlite3.Error, TypeError, ValueError):
        # Completion remains authoritative; a later read/sync can retry the
        # optional group attachment if the generated file is not ready yet.
        pass
    return result


def fail_item(db_path, test_id, item_id, error):
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("UPDATE nai_artist_test_items SET status='pending', error=?, updated_at=? WHERE id=? AND test_id=? AND status='processing'", (str(error or "")[:500], timestamp, item_id, test_id))
        conn.execute("UPDATE nai_artist_tests SET status='paused', updated_at=? WHERE id=? AND status='running'", (timestamp, test_id))


def save_item_rating(db_path, test_id, item_id, score):
    if type(score) is not int or not 1 <= score <= 5:
        raise ValueError("image_score must be an integer from 1 to 5.")
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        test = conn.execute("SELECT id FROM nai_artist_tests WHERE id=?", (test_id,)).fetchone()
        if test is None:
            raise LookupError("NAI artist test was not found.")
        item = conn.execute(
            "SELECT id, artist_tag, status, generated_image_id FROM nai_artist_test_items WHERE id=? AND test_id=?",
            (item_id, test_id),
        ).fetchone()
        if item is None:
            raise LookupError("NAI artist test item was not found.")
        if item["status"] != "complete" or item["generated_image_id"] is None:
            raise RuntimeError("이미 생성이 완료된 이미지에만 평가할 수 있습니다.")
        unfinished = conn.execute(
            "SELECT 1 FROM nai_artist_test_items WHERE test_id=? AND status!='complete' LIMIT 1",
            (test_id,),
        ).fetchone()
        if unfinished is not None:
            raise RuntimeError("모든 이미지 생성이 끝난 뒤 평가할 수 있습니다.")
        conn.execute(
            "UPDATE nai_artist_test_items SET image_score=?, rated_at=?, updated_at=? WHERE id=? AND test_id=?",
            (score, timestamp, timestamp, item_id, test_id),
        )
        average = conn.execute(
            "SELECT AVG(CAST(image_score AS REAL)) FROM nai_artist_test_items WHERE test_id=? AND artist_tag=? AND status='complete' AND image_score IS NOT NULL",
            (test_id, item["artist_tag"]),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO nai_artist_test_ratings(test_id,artist_tag,score,created_at,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(test_id,artist_tag) DO UPDATE SET score=excluded.score, updated_at=excluded.updated_at
            """,
            (test_id, item["artist_tag"], float(average), timestamp, timestamp),
        )
        incomplete = conn.execute(
            "SELECT 1 FROM nai_artist_test_items WHERE test_id=? AND (status!='complete' OR image_score IS NULL) LIMIT 1",
            (test_id,),
        ).fetchone()
        if incomplete is None:
            _update_status(conn, test_id, "completed", timestamp)
        else:
            conn.execute("UPDATE nai_artist_tests SET status='running', completed_at=NULL, updated_at=? WHERE id=? AND status IN ('running','pending','completed')", (timestamp, test_id))
    return get_test(db_path, test_id)


def save_direct_rating(db_path, test_id, artist_tag, score):
    artist_tag = str(artist_tag or "").strip()
    if not artist_tag or type(score) is not int or not 1 <= score <= 5:
        raise ValueError("artist_tag and score 1~5 are required.")
    timestamp = now_text()
    with closing(sqlite3.connect(db_path)) as conn, conn:
        row = conn.execute("SELECT 1 FROM nai_artist_test_items WHERE test_id=? AND artist_tag=? LIMIT 1", (test_id, artist_tag)).fetchone()
        if row is None:
            raise ValueError("Artist is not part of this test.")
        conn.execute(
            """
            INSERT INTO nai_artist_test_ratings(test_id,artist_tag,score,created_at,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(test_id,artist_tag) DO UPDATE SET score=excluded.score, updated_at=excluded.updated_at
            """,
            (test_id, artist_tag, score, timestamp, timestamp),
        )
    return get_test(db_path, test_id)


def latest_direct_rating_map(db_path):
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT artist_tag, score, updated_at FROM nai_artist_test_ratings
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    result = {}
    for row in rows:
        key = row["artist_tag"].replace("_", " ").casefold()
        result.setdefault(key, {"artist_tag": row["artist_tag"], "score": float(row["score"]), "updated_at": row["updated_at"]})
    return result
