import hashlib
import io
import json
import math
import os
import random
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image, ImageOps

from arca_chrome_extension import (
    ArcaChromeExtensionError,
    extension_payload_to_cookie_jar,
    install_arca_session_bridge,
)
from arca_login_window import ArcaLoginWindowManager

from arca_style_collector import (
    ArcaCollectorError,
    connect_arca_cookie_jar,
    delete_arca_style,
    get_collection_job,
    get_latest_resumable_collection_job,
    get_image_restore_estimate,
    get_arca_browser_session_status,
    get_arca_style_detail,
    get_arca_image_gallery_page,
    get_arca_style_page,
    get_arca_style_statistics,
    get_arca_tag_statistics,
    get_arca_quality_sequence_statistics,
    get_style_maker_prompt_presets,
    get_shared_style_artist_pool,
    get_shared_style_dependency_images,
    get_completed_coverage,
    init_arca_style_tables,
    import_arca_browser_session,
    import_arca_style_seed,
    mark_interrupted_collection_jobs,
    normalize_collect_payload,
    normalize_arca_article_url,
    pause_collection_job,
    revalidate_stored_metadata,
    start_collection_job,
    start_image_restore_job,
    start_url_collection_job,
    resume_collection_job,
    stop_collection_job,
    split_artist_quality_prompt,
    update_arca_style,
    extract_novelai_metadata,
)
from arca_image_archive import (
    ARCHIVE_BYTES,
    ARCHIVE_FILENAME,
    ARCHIVE_IMAGE_COUNT,
    ARCHIVE_SHA256,
    append_local_upload,
    discard_local_upload,
    finish_local_upload,
    start_google_archive_job,
    start_local_upload,
)

from novelai import (
    MODEL,
    NovelAIError,
    combine_base_prompt,
    combine_generation_prompt,
    generate_novelai_png,
    normalize_generation_data,
    test_novelai_subscription,
)
from model_definitions import model_definitions_for_api, normalize_model_id
from style_store import (
    SettingsError,
    delete_app_key,
    delete_style,
    DELETE_CONFIRMATION_CATEGORIES,
    default_delete_confirmation_preferences,
    get_style_detail,
    list_generated_images,
    list_styles,
    load_app_key,
    load_skip_delete_confirmation,
    normalize_delete_confirmation_preferences,
    load_prompt_preset_overrides,
    release_generation_request,
    reserve_generation_request,
    save_app_key,
    save_skip_delete_confirmation,
    save_prompt_preset_override,
    save_generated_result,
    delete_generated_image_batch,
)
from confirmed_style_store import (
    MAX_IMAGE_BYTES as MAX_CONFIRMED_IMAGE_BYTES,
    create_confirmed_style,
    create_confirmed_style_group,
    delete_confirmed_style,
    get_confirmed_style,
    init_confirmed_style_tables,
    inspect_image,
    list_confirmed_styles,
    normalize_confirmed_model_name,
    update_confirmed_style,
)
from comparison_store import (
    create_group,
    delete_group,
    delete_result,
    get_group,
    init_comparison_tables,
    list_groups,
    remove_group_results,
    save_result,
    set_group_seed,
    update_group_style_ids,
)

from style_logic import (
    SCORE_SELECTION_WEIGHT,
    assign_weights,
    build_artist_prompt,
    exact_score,
    normalize_style_artists,
    select_artists,
    style_hash,
)


def resolve_runtime_paths(frozen, executable, module_file, bundle_dir=None):
    source_dir = Path(module_file).resolve().parent
    if frozen:
        resource_dir = Path(bundle_dir or source_dir).resolve()
        data_dir = Path(executable).resolve().parent / "data"
    else:
        resource_dir = source_dir
        data_dir = source_dir / "data"
    return resource_dir, data_dir


RESOURCE_DIR, DATA_DIR = resolve_runtime_paths(
    frozen=bool(getattr(sys, "frozen", False)),
    executable=sys.executable,
    module_file=__file__,
    bundle_dir=getattr(sys, "_MEIPASS", None),
)
BASE_DIR = RESOURCE_DIR
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
GENERATED_DIR = DATA_DIR / "generated"
CONFIRMED_STYLE_IMAGE_DIR = DATA_DIR / "confirmed_style_images"
COMPARISON_IMAGE_DIR = DATA_DIR / "comparison_images"
ARCA_STYLE_IMAGE_DIR = DATA_DIR / "arca_style_images"
ARCA_STYLE_SEED_PATH = RESOURCE_DIR / "arca_style_seed.sqlite"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "artist_rater.sqlite"
ARCA_SESSION_BRIDGE_SOURCE_DIR = RESOURCE_DIR / "static" / "arca_session_bridge"
DANBOORU_BASE_URL = "https://danbooru.donmai.us"
DEFAULT_CUTOFF_DATE = "2025-01-31"
REQUEST_TIMEOUT = 12
USER_AGENT = "DanbooruArtistRater/1.0 (local personal tool)"

ARCA_LOGIN_MANAGER = ArcaLoginWindowManager(
    DATA_DIR / "arca_login_profile",
    lambda jar: connect_arca_cookie_jar(jar, "전용 Chrome"),
)

app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.config["JSON_AS_ASCII"] = False
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def json_response(payload, status=200):
    return app.response_class(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    ARCA_STYLE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_tag TEXT NOT NULL UNIQUE,
                score INTEGER NOT NULL,
                memo TEXT DEFAULT '',
                favorite INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                mode TEXT NOT NULL,
                query_text TEXT DEFAULT '',
                query_tags_json TEXT DEFAULT '[]',
                matched_post_count INTEGER DEFAULT 0,
                artist_post_count INTEGER DEFAULT 0,
                representative_post_id INTEGER,
                representative_thumbnail_path TEXT DEFAULT '',
                representative_preview_url TEXT DEFAULT '',
                sample_post_ids_json TEXT DEFAULT '[]',
                prompt_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rating_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rating_id INTEGER NOT NULL,
                post_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                source_url TEXT DEFAULT '',
                post_url TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(rating_id, post_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artist_cache (
                artist_tag TEXT PRIMARY KEY,
                artist_post_count INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS art_styles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                style_hash TEXT NOT NULL UNIQUE,
                artists_json TEXT NOT NULL,
                artist_prompt TEXT NOT NULL,
                representative_image_path TEXT DEFAULT '',
                image_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generated_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                style_id INTEGER NOT NULL,
                image_path TEXT NOT NULL,
                base_prompt TEXT DEFAULT '',
                negative_prompt TEXT DEFAULT '',
                character_prompts_json TEXT DEFAULT '[]',
                combined_prompt TEXT NOT NULL,
                artist_prompt TEXT NOT NULL,
                artists_json TEXT NOT NULL,
                seed INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                sampler TEXT NOT NULL,
                noise_schedule TEXT NOT NULL DEFAULT 'native',
                steps INTEGER NOT NULL,
                scale REAL NOT NULL,
                cfg_rescale REAL NOT NULL,
                model TEXT NOT NULL,
                complexity TEXT NOT NULL DEFAULT '',
                quality_toggle INTEGER NOT NULL DEFAULT 0,
                uc_preset INTEGER NOT NULL DEFAULT 0,
                shared_dependency_reference_id INTEGER,
                shared_dependency_reference_title TEXT,
                shared_dependency_reference_source_url TEXT,
                shared_dependency_artist_policy TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(style_id) REFERENCES art_styles(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generation_requests (
                request_id TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('processing', 'complete')),
                image_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(image_id) REFERENCES generated_images(id)
            )
            """
        )
        image_columns = {row[1] for row in conn.execute("PRAGMA table_info(generated_images)")}
        if "noise_schedule" not in image_columns:
            conn.execute("ALTER TABLE generated_images ADD COLUMN noise_schedule TEXT NOT NULL DEFAULT 'native'")
        generated_migrations = {
            "quality_prompt": "TEXT NOT NULL DEFAULT ''",
            "original_quality_prompt": "TEXT NOT NULL DEFAULT ''",
            "excluded_quality_tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "fixed_prompt": "TEXT NOT NULL DEFAULT ''",
            "variety_plus": "INTEGER",
            "skip_cfg_above_sigma": "REAL",
            "shared_dependency_reference_id": "INTEGER",
            "shared_dependency_reference_title": "TEXT",
            "shared_dependency_reference_source_url": "TEXT",
            "shared_dependency_artist_policy": "TEXT",
            "complexity": "TEXT NOT NULL DEFAULT ''",
            "quality_toggle": "INTEGER NOT NULL DEFAULT 0",
            "uc_preset": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, declaration in generated_migrations.items():
            if column not in image_columns:
                conn.execute(f"ALTER TABLE generated_images ADD COLUMN {column} {declaration}")

    from style_store import reconcile_generated_storage

    reconcile_generated_storage(DB_PATH, GENERATED_DIR)
    init_confirmed_style_tables(DB_PATH)
    init_comparison_tables(DB_PATH)
    init_arca_style_tables(DB_PATH)
    import_arca_style_seed(DB_PATH, ARCA_STYLE_SEED_PATH)
    revalidate_stored_metadata(DB_PATH)
    mark_interrupted_collection_jobs(DB_PATH)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_text():
    return datetime.now(timezone.utc).isoformat()


def normalize_query_text(text):
    if not text:
        return []
    pieces = re.split(r"[\s,\n\r]+", text.strip())
    tags = []
    seen = set()
    for piece in pieces:
        tag = piece.strip().strip(",")
        if not tag:
            continue
        tag = re.sub(r"\s+", "_", tag)
        tag = tag.replace(" ", "_")
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def normalize_cutoff_date(value):
    if value is None:
        return DEFAULT_CUTOFF_DATE
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("cutoff_date는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("cutoff_date는 실제 유효한 날짜여야 합니다.")
    return value


def cutoff_datetime(cutoff_date=DEFAULT_CUTOFF_DATE):
    normalized = normalize_cutoff_date(cutoff_date)
    cutoff = datetime.combine(date.fromisoformat(normalized), time(23, 59, 59))
    return cutoff.replace(tzinfo=timezone.utc)


def parse_post_datetime(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_before_cutoff(post, cutoff_date=DEFAULT_CUTOFF_DATE):
    created = parse_post_datetime(post.get("created_at"))
    return bool(created and created <= cutoff_datetime(cutoff_date))


def danbooru_get(path, params):
    url = f"{DANBOORU_BASE_URL}{path}"
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response.json()


def post_image_url(post):
    for key in ("preview_file_url", "large_file_url", "file_url"):
        value = post.get(key)
        if value:
            return value
    return ""


def post_to_sample(post):
    image_url = post_image_url(post)
    if not image_url:
        return None
    post_id = post.get("id")
    return {
        "id": post_id,
        "preview_url": image_url,
        "large_url": post.get("large_file_url") or post.get("file_url") or image_url,
        "post_url": f"{DANBOORU_BASE_URL}/posts/{post_id}" if post_id else "",
        "created_at": post.get("created_at") or "",
        "rating": post.get("rating") or "",
        "score": post.get("score") or 0,
    }


def search_posts(tags, fetch_pages=1, limit=100, cutoff_date=DEFAULT_CUTOFF_DATE):
    pages = max(1, min(int(fetch_pages or 1), 10))
    limit = max(1, min(int(limit or 100), 100))
    cutoff_date = normalize_cutoff_date(cutoff_date)
    query = " ".join([tag for tag in tags if tag] + [f"date:<={cutoff_date}"])
    posts = []
    for page in range(1, pages + 1):
        data = danbooru_get("/posts.json", {"tags": query, "limit": limit, "page": page})
        if not isinstance(data, list):
            break
        filtered = [post for post in data if isinstance(post, dict) and is_before_cutoff(post, cutoff_date)]
        posts.extend(filtered)
        if len(data) < limit:
            break
    return posts


def autocomplete_tags(query, category=None):
    query = (query or "").strip()
    if not query:
        return []
    params = {
        "search[name_matches]": f"{query}*",
        "search[hide_empty]": "yes",
        "search[order]": "count",
        "limit": 20,
    }
    if category is not None:
        params["search[category]"] = int(category)
    data = danbooru_get("/tags.json", params)
    category_names = {0: "general", 1: "artist", 3: "copyright", 4: "character"}
    results = []
    for item in data if isinstance(data, list) else []:
        item_category = item.get("category", 0)
        if category is not None and item_category != int(category):
            continue
        results.append(
            {
                "name": item.get("name", ""),
                "category": item_category,
                "category_name": category_names.get(item_category, "other"),
                "post_count": item.get("post_count", 0),
                "is_deprecated": bool(item.get("is_deprecated", False)),
            }
        )
    return sorted(results, key=lambda item: int(item.get("post_count") or 0), reverse=True)


def get_artist_post_count(artist_tag):
    with db() as conn:
        cached = conn.execute(
            "SELECT artist_post_count FROM artist_cache WHERE artist_tag = ?",
            (artist_tag,),
        ).fetchone()
        if cached:
            return int(cached["artist_post_count"] or 0)
    try:
        data = danbooru_get(
            "/tags.json",
            {
                "search[name]": artist_tag,
                "search[category]": 1,
                "limit": 1,
            },
        )
        count = 0
        if isinstance(data, list) and data:
            count = int(data[0].get("post_count") or 0)
    except requests.RequestException:
        count = 0
    with db() as conn:
        conn.execute(
            """
            INSERT INTO artist_cache (artist_tag, artist_post_count, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(artist_tag) DO UPDATE SET
                artist_post_count = excluded.artist_post_count,
                updated_at = excluded.updated_at
            """,
            (artist_tag, count, now_text()),
        )
    return count


def get_rated_artist_set():
    with db() as conn:
        rows = conn.execute("SELECT artist_tag FROM ratings").fetchall()
    return {row["artist_tag"] for row in rows}


def normalize_rating_tag_filter(value):
    if not isinstance(value, str):
        raise ValueError("평가 작가 태그 필터는 문자열이어야 합니다.")
    return re.sub(r"\s+", "_", value.strip()).casefold()


def normalize_rating_tag_rules(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("평가 작가 태그별 인원은 최대 20개의 배열이어야 합니다.")
    normalized = []
    seen = set()
    for rule in value:
        if not isinstance(rule, dict):
            raise ValueError("평가 작가 태그별 인원 형식을 확인하세요.")
        tag = normalize_rating_tag_filter(rule.get("tag", ""))
        count = rule.get("count")
        if not tag:
            raise ValueError("평가 작가 태그를 입력하세요.")
        if type(count) is not int or count < 1 or count > 50:
            raise ValueError("평가 작가 태그별 인원은 1명부터 50명 사이의 정수여야 합니다.")
        if tag in seen:
            raise ValueError(f"같은 평가 작가 태그를 두 번 지정할 수 없습니다: {tag}")
        seen.add(tag)
        normalized.append({"tag": tag, "count": count})
    return normalized


def normalize_rating_exclude_tags(value):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("평가 작가 제외 태그는 최대 20개의 배열이어야 합니다.")
    normalized = []
    seen = set()
    for item in value:
        tag = normalize_rating_tag_filter(item)
        if not tag:
            raise ValueError("제외할 평가 작가 태그를 입력하세요.")
        if tag in seen:
            raise ValueError(f"같은 제외 태그를 두 번 지정할 수 없습니다: {tag}")
        seen.add(tag)
        normalized.append(tag)
    return normalized


def rating_matches_tag_filter(row, tag_filter):
    if not tag_filter:
        return True
    try:
        query_tags = json.loads(row["query_tags_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        query_tags = []
    if not isinstance(query_tags, list):
        query_tags = []
    if not query_tags:
        query_tags = normalize_query_text(row["query_text"] or "")
    return any(
        re.sub(r"\s+", "_", str(tag).strip()).casefold() == tag_filter
        for tag in query_tags
    )


def safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "artist").strip("._")
    return value[:120] or "artist"


def download_thumbnail(url, artist_tag, post_id):
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return ""
    filename = f"{safe_filename(artist_tag)}_{safe_filename(str(post_id or 'post'))}.webp"
    target = THUMBNAIL_DIR / filename
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        response.raise_for_status()
        payload = io.BytesIO()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                payload.write(chunk)
        payload.seek(0)
        with Image.open(payload) as opened:
            image = ImageOps.exif_transpose(opened)
            image.thumbnail((768, 768), Image.Resampling.LANCZOS)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
            with temporary.open("wb") as handle:
                image.save(handle, format="WEBP", quality=85, method=3)
        os.replace(temporary, target)
    except (requests.RequestException, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        if temporary.exists():
            temporary.unlink()
        return ""
    finally:
        if temporary.exists():
            temporary.unlink()
    return filename


def thumbnail_filename(artist_tag, post_id):
    return f"{safe_filename(artist_tag)}_{safe_filename(str(post_id or 'post'))}.webp"


def safe_thumbnail_path(filename):
    if not filename:
        return None
    name = str(filename)
    path = Path(name)
    root = THUMBNAIL_DIR.resolve()
    if path.is_absolute() or path.name != name:
        return None
    target = (THUMBNAIL_DIR / name).resolve()
    if root not in target.parents:
        return None
    return target


def remove_unreferenced_thumbnail_paths(filenames):
    names = {str(filename) for filename in filenames if filename}
    if not names:
        return
    with db() as conn:
        referenced = {
            row[0]
            for row in conn.execute(
                "SELECT representative_thumbnail_path FROM ratings WHERE representative_thumbnail_path IN ({})".format(
                    ",".join("?" for _ in names)
                ),
                tuple(names),
            ).fetchall()
        }
        referenced.update(
            row[0]
            for row in conn.execute(
                "SELECT image_path FROM rating_examples WHERE image_path IN ({})".format(
                    ",".join("?" for _ in names)
                ),
                tuple(names),
            ).fetchall()
        )
    for filename in names - referenced:
        target = safe_thumbnail_path(filename)
        if target and target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def rating_examples_payload(rating_id):
    with db() as conn:
        rating = conn.execute(
            "SELECT id,artist_tag,representative_post_id,representative_thumbnail_path,representative_preview_url FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
        if not rating:
            return None
        rows = conn.execute(
            "SELECT id,post_id,image_path,source_url,post_url,created_at FROM rating_examples WHERE rating_id = ? ORDER BY id",
            (rating_id,),
        ).fetchall()
    representative_path = rating["representative_thumbnail_path"] or ""
    representative_post_id = rating["representative_post_id"]
    examples = []
    for row in rows:
        image_path = row["image_path"] or ""
        image_url = f"/thumbnails/{image_path}" if safe_thumbnail_path(image_path) else ""
        examples.append(
            {
                "id": row["id"],
                "post_id": row["post_id"],
                "image_url": image_url,
                "source_url": row["source_url"] or "",
                "post_url": row["post_url"] or "",
                "created_at": row["created_at"] or "",
                "is_thumbnail": bool(
                    image_path == representative_path
                    or row["post_id"] == representative_post_id
                ),
            }
        )
    return {
        "ok": True,
        "rating": {
            "id": rating["id"],
            "artist_tag": rating["artist_tag"],
            "representative_post_id": rating["representative_post_id"],
            "representative_thumbnail_path": representative_path,
            "representative_preview_url": rating["representative_preview_url"] or "",
            "thumbnail_url": f"/thumbnails/{representative_path}" if safe_thumbnail_path(representative_path) else "",
        },
        "examples": examples,
    }


def choose_candidate(candidates, random_mode):
    if not candidates:
        return None
    if random_mode == "uniform":
        return random.choice(candidates)
    if random_mode == "weighted":
        weights = [max(1, item["matched_post_count"]) for item in candidates]
    else:
        weights = [math.sqrt(max(1, item["matched_post_count"])) for item in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def choose_candidate_pool(candidates, random_mode, limit):
    limit = max(1, min(int(limit or 12), 30))
    pool = []
    remaining = list(candidates)
    while remaining and len(pool) < limit:
        selected = choose_candidate(remaining, random_mode)
        pool.append(selected)
        remaining = [item for item in remaining if item["artist_tag"] != selected["artist_tag"]]
    return pool


def search_posts_for_cutoff(tags, fetch_pages=1, limit=100, cutoff_date=DEFAULT_CUTOFF_DATE):
    kwargs = {"fetch_pages": fetch_pages}
    if limit != 100:
        kwargs["limit"] = limit
    if cutoff_date != DEFAULT_CUTOFF_DATE:
        kwargs["cutoff_date"] = cutoff_date
    return search_posts(tags, **kwargs)


def fetch_artist_samples(artist_tag, query_tags, sample_limit, latest_first=False, cutoff_date=DEFAULT_CUTOFF_DATE):
    sample_limit = max(1, min(int(sample_limit or 12), 30))
    if latest_first:
        posts = search_posts_for_cutoff([artist_tag], fetch_pages=1, cutoff_date=cutoff_date)
        return [sample for post in posts if (sample := post_to_sample(post))][:sample_limit]

    posts = []
    seen = set()
    for tags in ([artist_tag] + query_tags, [artist_tag]):
        try:
            for post in search_posts_for_cutoff(tags, fetch_pages=3, cutoff_date=cutoff_date):
                post_id = post.get("id")
                if post_id in seen:
                    continue
                seen.add(post_id)
                sample = post_to_sample(post)
                if sample:
                    posts.append(sample)
        except requests.RequestException:
            if tags == [artist_tag]:
                raise
    random.shuffle(posts)
    return posts[:sample_limit]


def choose_candidate_pool_with_exclusions(candidates, random_mode, limit, exclude_query_tags, cutoff_date=DEFAULT_CUTOFF_DATE):
    limit = max(1, min(int(limit or 12), 30))
    pool = []
    excluded_count = 0
    remaining = list(candidates)
    while remaining and len(pool) < limit:
        selected = choose_candidate(remaining, random_mode)
        remaining = [item for item in remaining if item["artist_tag"] != selected["artist_tag"]]
        if exclude_query_tags and search_posts_for_cutoff(
            [selected["artist_tag"], *exclude_query_tags], fetch_pages=1, limit=1, cutoff_date=cutoff_date
        ):
            excluded_count += 1
            continue
        pool.append(selected)
    return pool, excluded_count


def candidate_prompt(artist_tag):
    return f"{artist_tag}, masterpiece, best quality, very aesthetic"


def candidate_payload(candidate):
    artist = candidate["artist_tag"]
    return {
        "artist": artist,
        "artist_tag": artist,
        "matched_post_count": candidate["matched_post_count"],
        "artist_post_count": candidate["artist_post_count"],
        "prompt_text": candidate_prompt(artist),
    }


def global_artist_candidates(min_artist_post_count, pages_to_try, cutoff_date=DEFAULT_CUTOFF_DATE):
    min_artist_post_count = max(0, int(min_artist_post_count or 0))
    pages_to_try = max(1, min(int(pages_to_try or 5), 10))
    pages = random.sample(range(1, 30), k=min(pages_to_try, 29))
    candidates = []
    for page in pages:
        data = danbooru_get(
            "/tags.json",
            {
                "search[category]": 1,
                "search[hide_empty]": "yes",
                "search[order]": "count",
                "limit": 100,
                "page": page,
            },
        )
        if not isinstance(data, list):
            continue
        for item in data:
            count = int(item.get("post_count") or 0)
            name = item.get("name")
            if name and count >= min_artist_post_count:
                candidates.append(
                    {
                        "artist_tag": name,
                        "matched_post_count": count,
                        "artist_post_count": count,
                    }
                )
    return candidates


def build_candidate_pool(payload):
    query_text = payload.get("query_text", "")
    query_tags = normalize_query_text(query_text)
    exclude_query_tags = normalize_query_text(payload.get("exclude_query_text", ""))
    latest_samples = payload.get("latest_samples") is True
    min_artist_post_count = int(payload.get("min_artist_post_count") or 1000)
    min_match_count = int(payload.get("min_match_count") or 3)
    fetch_pages = int(payload.get("fetch_pages") or 5)
    candidate_limit = int(payload.get("candidate_limit") or 12)
    random_mode = payload.get("random_mode") or "soft_weighted"
    random_mode = random_mode if random_mode in {"uniform", "weighted", "soft_weighted"} else "soft_weighted"
    cutoff_date = normalize_cutoff_date(payload.get("cutoff_date"))
    rated = get_rated_artist_set()
    excluded_artists = rated | {
        str(artist).strip()
        for artist in payload.get("exclude_artist_tags", [])
        if str(artist).strip()
    }
    filter_stats = {
        "requested_count": candidate_limit,
        "excluded_artist_count": len(excluded_artists),
        "fetched_post_count": 0,
        "artist_tagged_post_count": 0,
        "unique_artist_count": 0,
        "min_match_candidate_count": 0,
        "post_count_filtered_count": 0,
        "exclude_prompt_filtered_count": 0,
        "final_candidate_count": 0,
    }

    if not query_tags:
        mode = "global_random"
        raw_candidates = global_artist_candidates(min_artist_post_count, fetch_pages, cutoff_date)
        filter_stats["unique_artist_count"] = len(raw_candidates)
        candidates = [
            item
            for item in raw_candidates
            if item["artist_tag"] not in excluded_artists and item["artist_post_count"] >= min_artist_post_count
        ]
        filter_stats["min_match_candidate_count"] = len(raw_candidates)
        filter_stats["post_count_filtered_count"] = len(raw_candidates) - len(candidates)
    else:
        mode = "tag_filtered_random"
        posts = search_posts_for_cutoff(query_tags, fetch_pages=fetch_pages, cutoff_date=cutoff_date)
        filter_stats["fetched_post_count"] = len(posts)
        artist_posts = {}
        for post in posts:
            artist_string = (post.get("tag_string_artist") or "").strip()
            if not artist_string:
                continue
            filter_stats["artist_tagged_post_count"] += 1
            for artist in artist_string.split():
                artist_posts.setdefault(artist, []).append(post)

        filter_stats["unique_artist_count"] = len(artist_posts)
        candidates = []
        min_match_artists = []
        for artist, matched_posts in artist_posts.items():
            if len(matched_posts) < min_match_count:
                continue
            min_match_artists.append(artist)
            if artist in excluded_artists:
                continue
            artist_post_count = get_artist_post_count(artist)
            if artist_post_count and artist_post_count < min_artist_post_count:
                filter_stats["post_count_filtered_count"] += 1
                continue
            candidates.append(
                {
                    "artist_tag": artist,
                    "matched_post_count": len(matched_posts),
                    "artist_post_count": artist_post_count,
                }
            )
        filter_stats["min_match_candidate_count"] = len(min_match_artists)

    filter_stats["final_candidate_count"] = len(candidates)
    if not candidates:
        return {
            "ok": False,
            "reason": "후보 작가가 없습니다. 태그 조건이 좁거나, fetch_pages/min_match_count/min_artist_post_count 설정이 빡빡하거나, 이미 평가한 작가가 많을 수 있습니다.",
            "mode": "global_random" if not query_tags else "tag_filtered_random",
            "query_tags": query_tags,
            "cutoff_date": cutoff_date,
            "filter_stats": filter_stats,
        }

    selected_pool, exclude_prompt_filtered_count = choose_candidate_pool_with_exclusions(
        candidates, random_mode, candidate_limit, exclude_query_tags, cutoff_date
    )
    filter_stats["exclude_prompt_filtered_count"] = exclude_prompt_filtered_count
    filter_stats["final_candidate_count"] = len(selected_pool)
    if not selected_pool:
        return {
            "ok": False,
            "reason": "제외 프롬프트를 적용한 뒤 표시할 후보 작가가 없습니다.",
            "mode": mode,
            "query_tags": query_tags,
            "exclude_query_tags": exclude_query_tags,
            "latest_samples": latest_samples,
            "cutoff_date": cutoff_date,
            "filter_stats": filter_stats,
        }
    return {
        "ok": True,
        "mode": mode,
        "query_tags": query_tags,
        "exclude_query_tags": exclude_query_tags,
        "latest_samples": latest_samples,
        "cutoff_date": cutoff_date,
        "candidate_count": len(selected_pool),
        "candidates": [candidate_payload(candidate) for candidate in selected_pool],
        "filter_stats": filter_stats,
    }


def pick_random_artist(payload):
    sample_limit = int(payload.get("sample_limit") or 12)
    pool = build_candidate_pool(payload)
    if not pool.get("ok"):
        return pool
    if not pool["candidates"]:
        return {
            "ok": False,
            "reason": "후보 작가가 없습니다.",
            "mode": pool["mode"],
            "query_tags": pool["query_tags"],
        }

    selected = pool["candidates"][0]
    samples = fetch_artist_samples(
        selected["artist_tag"], pool["query_tags"], sample_limit, pool.get("latest_samples", False), pool["cutoff_date"]
    )
    if not samples:
        return {
            "ok": False,
            "reason": "선택된 작가의 표시 가능한 샘플 이미지를 찾지 못했습니다.",
            "mode": pool["mode"],
            "query_tags": pool["query_tags"],
            "cutoff_date": pool["cutoff_date"],
        }

    return {
        "ok": True,
        "mode": pool["mode"],
        "query_tags": pool["query_tags"],
        "cutoff_date": pool["cutoff_date"],
        "artist": selected["artist"],
        "matched_post_count": selected["matched_post_count"],
        "artist_post_count": selected["artist_post_count"],
        "candidate_count": pool["candidate_count"],
        "samples": samples,
        "prompt_text": selected["prompt_text"],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tags/autocomplete")
def api_autocomplete():
    try:
        category = request.args.get("category")
        category = int(category) if category is not None else None
        return json_response(autocomplete_tags(request.args.get("q", ""), category=category))
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)


@app.route("/api/candidates", methods=["POST"])
def api_candidates():
    try:
        return json_response(build_candidate_pool(request.get_json(silent=True) or {}))
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)
    except Exception as exc:
        return json_response({"ok": False, "error": f"처리 오류: {exc}"}, 400)


@app.route("/api/artist_samples", methods=["POST"])
def api_artist_samples():
    payload = request.get_json(silent=True) or {}
    artist_tag = (payload.get("artist_tag") or payload.get("artist") or "").strip()
    if not artist_tag:
        return json_response({"ok": False, "error": "artist_tag가 필요합니다."}, 400)
    query_tags = payload.get("query_tags") or normalize_query_text(payload.get("query_text", ""))
    sample_limit = int(payload.get("sample_limit") or 10)
    latest_samples = payload.get("latest_samples") is True
    try:
        cutoff_date = normalize_cutoff_date(payload.get("cutoff_date"))
        if cutoff_date == DEFAULT_CUTOFF_DATE:
            samples = fetch_artist_samples(artist_tag, query_tags, sample_limit, latest_samples)
        else:
            samples = fetch_artist_samples(artist_tag, query_tags, sample_limit, latest_samples, cutoff_date)
    except ValueError as exc:
        return json_response({"ok": False, "error": str(exc)}, 400)
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)
    if not samples:
        return json_response(
            {
                "ok": False,
                "reason": "선택된 작가의 표시 가능한 샘플 이미지를 찾지 못했습니다.",
                "artist": artist_tag,
                "query_tags": query_tags,
                "cutoff_date": cutoff_date,
            }
        )
    return json_response(
        {
            "ok": True,
            "mode": payload.get("mode") or "tag_filtered_random",
            "query_tags": query_tags,
            "cutoff_date": cutoff_date,
            "artist": artist_tag,
            "matched_post_count": int(payload.get("matched_post_count") or 0),
            "artist_post_count": int(payload.get("artist_post_count") or 0),
            "samples": samples,
            "prompt_text": payload.get("prompt_text") or candidate_prompt(artist_tag),
        }
    )


@app.route("/api/pick", methods=["POST"])
def api_pick():
    try:
        return json_response(pick_random_artist(request.get_json(silent=True) or {}))
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)
    except Exception as exc:
        return json_response({"ok": False, "error": f"처리 오류: {exc}"}, 400)


@app.route("/api/ratings", methods=["POST"])
def api_create_rating():
    payload = request.get_json(silent=True) or {}
    artist_tag = (payload.get("artist_tag") or "").strip()
    score = payload.get("score")
    if not artist_tag:
        return json_response({"ok": False, "error": "artist_tag가 필요합니다."}, 400)
    if score is None:
        return json_response({"ok": False, "error": "score가 필요합니다."}, 400)
    score = int(score)
    if score < 1 or score > 5:
        return json_response({"ok": False, "error": "score는 1~5여야 합니다."}, 400)

    representative_post_id = payload.get("representative_post_id")
    representative_preview_url = payload.get("representative_preview_url") or ""
    thumbnail = download_thumbnail(representative_preview_url, artist_tag, representative_post_id)
    created_at = now_text()
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO ratings (
                    artist_tag, score, memo, mode, query_text,
                    query_tags_json, matched_post_count, artist_post_count,
                    representative_post_id, representative_thumbnail_path,
                    representative_preview_url, sample_post_ids_json, prompt_text,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artist_tag,
                    score,
                    payload.get("memo") or "",
                    payload.get("mode") or "tag_filtered_random",
                    payload.get("query_text") or "",
                    json.dumps(payload.get("query_tags") or [], ensure_ascii=False),
                    int(payload.get("matched_post_count") or 0),
                    int(payload.get("artist_post_count") or 0),
                    representative_post_id,
                    thumbnail,
                    representative_preview_url,
                    json.dumps(payload.get("sample_post_ids") or [], ensure_ascii=False),
                    payload.get("prompt_text") or "",
                    created_at,
                    created_at,
                ),
            )
    except sqlite3.IntegrityError:
        return json_response({"ok": False, "error": "이미 평가한 작가입니다."}, 409)
    return json_response({"ok": True})


@app.route("/api/ratings")
def api_list_ratings():
    conditions = []
    params = []
    score_min = request.args.get("score_min")
    score_max = request.args.get("score_max")
    if score_min:
        conditions.append("score >= ?")
        params.append(int(score_min))
    if score_max:
        conditions.append("score <= ?")
        params.append(int(score_max))
    q = (request.args.get("q") or "").strip()
    if q:
        conditions.append("(artist_tag LIKE ? OR memo LIKE ? OR query_text LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])

    sort_sql = {
        "score_desc": "score DESC, updated_at DESC",
        "score_asc": "score ASC, updated_at DESC",
        "artist": "artist_tag ASC",
        "post_count_desc": "artist_post_count DESC, updated_at DESC",
        "recent": "updated_at DESC",
    }.get(request.args.get("sort") or "recent", "updated_at DESC")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM ratings {where} ORDER BY {sort_sql}", params).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item.pop("favorite", None)
        item.pop("blocked", None)
        filename = item.get("representative_thumbnail_path") or ""
        item["thumbnail_url"] = f"/thumbnails/{filename}" if filename else ""
        try:
            item["query_tags"] = json.loads(item.get("query_tags_json") or "[]")
            item["sample_post_ids"] = json.loads(item.get("sample_post_ids_json") or "[]")
        except json.JSONDecodeError:
            item["query_tags"] = []
            item["sample_post_ids"] = []
        items.append(item)
    return json_response(items)


@app.route("/api/style-maker/artists", methods=["POST"])
def api_style_maker_artists():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json_response({"ok": False, "error": "요청 내용을 확인하세요."}, 400)

    try:
        rng_seed = payload.get("rng_seed")
        if rng_seed is not None and type(rng_seed) is not int:
            raise ValueError("난수 시드는 JSON 정수여야 합니다.")
        if (
            "prefer_high_scores" in payload
            and type(payload["prefer_high_scores"]) is not bool
        ):
            raise ValueError("평점 우선 여부는 JSON 불리언이어야 합니다.")
        prefer_high_scores = payload.get("prefer_high_scores", False)
        shared_artist_min = payload.get("shared_artist_min", 0)
        shared_artist_max = payload.get("shared_artist_max", 0)
        if (
            type(shared_artist_min) is not int
            or type(shared_artist_max) is not int
            or shared_artist_min < 0
            or shared_artist_max < 0
            or shared_artist_max > 50
        ):
            raise ValueError("공유 그림체 작가 인원은 0부터 50 사이의 정수여야 합니다.")
        if shared_artist_min > shared_artist_max:
            raise ValueError("공유 그림체 작가 최소 인원은 최대 인원보다 클 수 없습니다.")
        rating_tag_rules = normalize_rating_tag_rules(payload.get("rating_tag_rules"))
        rating_exclude_tags = normalize_rating_exclude_tags(payload.get("rating_exclude_tags"))
        rating_tag_filter = normalize_rating_tag_filter(payload.get("rating_tag_filter", ""))
        if "ranges" in payload and not isinstance(payload["ranges"], list):
            raise ValueError("가중치 구간은 JSON 배열이어야 합니다.")
        ranges = payload.get("ranges", [])
        reroll = payload.get("reroll")
        if reroll is None:
            reroll = "weights" if "artists" in payload else "all"
        if reroll not in {"all", "artists", "weights"}:
            raise ValueError("Reroll mode must be all, artists, or weights.")
        supplied = payload.get("artists") if "artists" in payload else None
        current_artists = None
        if reroll in {"artists", "weights"}:
            current_artists = validate_supplied_style_artists(
                supplied,
                require_weights=reroll == "artists",
            )
        fixed_payload = payload.get("fixed_artists", [])
        if not isinstance(fixed_payload, list):
            raise ValueError("고정 작가 목록 형식을 확인하세요.")
        fixed_artists = (
            validate_supplied_style_artists(fixed_payload, require_weights=True)
            if fixed_payload else []
        )
        fixed_slots = []
        for item in fixed_payload:
            slot = item.get("slot")
            if slot is None:
                continue
            if type(slot) is not int or slot < 0:
                raise ValueError("고정 작가 자리는 0 이상의 정수여야 합니다.")
            if slot > 0:
                fixed_slots.append(slot)
        fixed_names = {
            item["artist"].replace("_", " ").casefold()
            for item in fixed_artists
        }

        shared_dependency = payload.get("weight_mode") == "shared_dependency"
        dependency_reference = None
        dependency_reference_id = None
        dependency_meta = {}
        dependency_ratios = {"fixed": 0, "reference": 100, "rated": 0, "other_shared": 0}
        dependency_reference_mode = "random"
        dependency_artist_policy = "highest"
        if shared_dependency:
            (
                requested_reference_id,
                dependency_ratios,
                dependency_reference_mode,
                dependency_artist_policy,
            ) = _shared_dependency_options(payload)
            if reroll == "weights" and requested_reference_id is None:
                raise ValueError("가중치 다시 뽑기에는 기존 공유 그림체 기준 이미지 ID가 필요합니다.")
            if reroll != "weights" or requested_reference_id is not None:
                dependency_images = get_shared_style_dependency_images(DB_PATH)
                if not dependency_images:
                    raise ValueError("기준으로 사용할 인식 가능한 공유 그림체 이미지가 없습니다.")
                dependency_rng = random.Random(rng_seed)
                if requested_reference_id is not None:
                    requested_reference = next(
                        (item for item in dependency_images if item.get("id") == requested_reference_id),
                        None,
                    )
                    if requested_reference is None:
                        raise ValueError("공유 그림체 기준 이미지를 찾을 수 없습니다.")
                    dependency_reference = requested_reference if (dependency_reference_mode == "fixed" or reroll == "weights") else dependency_rng.choice(dependency_images)
                elif reroll != "weights":
                    dependency_reference = dependency_rng.choice(dependency_images)
                if dependency_reference is not None:
                    dependency_reference_id = dependency_reference["id"]
                    dependency_meta = {
                        "shared_dependency_reference_id": dependency_reference_id,
                        "shared_dependency_reference": dependency_reference,
                        "shared_dependency_scale": dependency_reference.get("scale"),
                        "shared_dependency_cfg_rescale": dependency_reference.get("cfg_rescale"),
                        "shared_dependency_reference_mode": dependency_reference_mode,
                        "shared_dependency_artist_policy": dependency_artist_policy,
                    }

        if reroll == "weights":
            artists = current_artists
            if shared_dependency:
                weighted = [dict(item) for item in current_artists]
                artist_prompt = build_artist_prompt(weighted)
                return json_response({
                    "ok": True,
                    "artists": weighted,
                    "artist_prompt": artist_prompt,
                    "style_hash": style_hash(weighted),
                    **dependency_meta,
                })
        else:
            scores = payload.get("scores", [1, 2, 3, 4, 5])
            if not isinstance(scores, list) or not scores:
                raise ValueError("선택할 평점을 하나 이상 지정하세요.")
            scores = [exact_score(score) for score in scores]
            with closing(db()) as conn:
                rows = conn.execute(
                    "SELECT artist_tag, score, query_text, query_tags_json FROM ratings"
                ).fetchall()
            rated_rows = [
                row for row in rows
                if rating_tag_rules or rating_matches_tag_filter(row, rating_tag_filter)
            ]
            if rating_exclude_tags:
                rated_rows = [
                    row for row in rated_rows
                    if not any(
                        rating_matches_tag_filter(row, excluded_tag)
                        for excluded_tag in rating_exclude_tags
                    )
                ]
            excluded_rated_names = set(fixed_names)
            if reroll == "artists":
                excluded_rated_names.update(
                    item["artist"].replace("_", " ").casefold()
                    for item in current_artists
                )
            rated_rows = [
                row for row in rated_rows
                if row["artist_tag"].replace("_", " ").casefold()
                not in excluded_rated_names
            ]
            pool = [
                {"artist": row["artist_tag"], "score": row["score"]}
                for row in rated_rows
            ]
            target_count = payload.get("count", len(current_artists) if reroll == "artists" else 12)
            if shared_dependency:
                if dependency_reference is None:
                    raise ValueError("공유 그림체 기준 이미지가 필요합니다. 가중치 다시 뽑기에는 기존 기준 이미지 ID를 보내세요.")
                blocked_names = {
                    _style_artist_key(item["artist"])
                    for item in (current_artists or [])
                } if reroll == "artists" else set()
                selected_rated_rows = rated_rows
                if rating_tag_rules:
                    allowed_tags = {rule["tag"] for rule in rating_tag_rules}
                    selected_rated_rows = [
                        row for row in selected_rated_rows
                        if any(rating_matches_tag_filter(row, tag) for tag in allowed_tags)
                    ]
                rated_pool_dependency = [
                    {"artist": row["artist_tag"], "score": row["score"]}
                    for row in selected_rated_rows
                    if _style_artist_key(row["artist_tag"]) not in blocked_names
                    and row["score"] in scores
                ]
                other_shared_pool = []
                for image in dependency_images:
                    if image.get("id") == dependency_reference_id:
                        continue
                    for item in image.get("artists", []):
                        if _style_artist_key(item.get("artist")) not in blocked_names:
                            other_shared_pool.append(dict(item))
                weighted = _shared_dependency_result(
                    target_count=len(dependency_reference.get("artists", [])),
                    fixed_artists=fixed_artists,
                    reference=dependency_reference,
                    source_ratios=dependency_ratios,
                    rated_pool=rated_pool_dependency,
                    other_shared_pool=other_shared_pool,
                    min_weight=payload.get("min_weight", 0.1),
                    max_weight=payload.get("max_weight", 2.3),
                    prefer_high_scores=prefer_high_scores,
                    ranges=ranges,
                    weight_mode=payload.get("weight_mode", "balanced"),
                    weight_profile=payload.get("weight_profile"),
                    rng_seed=rng_seed,
                    blocked_names=blocked_names,
                    artist_policy=dependency_artist_policy,
                )
                artist_prompt = build_artist_prompt(weighted)
                return json_response({
                    "ok": True,
                    "artists": weighted,
                    "artist_prompt": artist_prompt,
                    "style_hash": style_hash(weighted),
                    **dependency_meta,
                })
            target_count = int(target_count)
            if target_count < 1:
                raise ValueError("작가 수는 1명 이상이어야 합니다.")
            if len(fixed_artists) > target_count:
                raise ValueError("고정 작가 수는 전체 작가 수보다 많을 수 없습니다.")
            if any(slot > target_count for slot in fixed_slots):
                raise ValueError("고정 작가 자리는 전체 작가 수를 넘을 수 없습니다.")
            random_target_count = target_count - len(fixed_artists)
            tagged_target_count = sum(rule["count"] for rule in rating_tag_rules)
            if not shared_dependency and tagged_target_count + shared_artist_min > random_target_count:
                raise ValueError(
                    "태그 지정 인원과 공유 작가 최소 인원의 합이 고정 작가를 제외한 남은 자리보다 많습니다."
                )
            occupied_slots = {slot - 1 for slot in fixed_slots}
            open_slots = [
                index for index in range(target_count)
                if index not in occupied_slots
            ][:random_target_count]
            profile_positions = [
                slot / max(1, target_count - 1)
                for slot in open_slots
            ]
            rng = random.Random(rng_seed)
            shared_pool = get_shared_style_artist_pool(DB_PATH) if shared_artist_max else []
            current_names = {
                item["artist"].replace("_", " ").casefold()
                for item in (current_artists or [])
            } | fixed_names
            shared_pool = [
                item for item in shared_pool
                if item["artist"].replace("_", " ").casefold() not in current_names
            ]
            unique_shared_pool = {}
            for item in shared_pool:
                normalized_name = item["artist"].replace("_", " ").casefold()
                unique_shared_pool.setdefault(normalized_name, item)
            shared_pool = list(unique_shared_pool.values())
            shared_limit = min(
                shared_artist_max,
                random_target_count - tagged_target_count,
                len(shared_pool),
            )
            if shared_artist_min > shared_limit:
                raise ValueError("공유 그림체에서 선택 가능한 작가가 최소 인원보다 적습니다.")
            shared_count = rng.randint(shared_artist_min, shared_limit) if shared_limit else 0
            selected_shared = rng.sample(shared_pool, shared_count)
            rated_names = {
                item["artist"].replace("_", " ").casefold()
                for item in pool if item["score"] in scores
            }
            while len(selected_shared) < shared_limit:
                selected_names = {
                    item["artist"].replace("_", " ").casefold()
                    for item in selected_shared
                }
                rated_available = [
                    item for item in pool
                    if item["score"] in scores
                    and item["artist"].replace("_", " ").casefold() not in selected_names
                ]
                if len(rated_available) >= random_target_count - len(selected_shared):
                    break
                remaining_shared = [
                    item for item in shared_pool
                    if item["artist"].replace("_", " ").casefold() not in selected_names
                ]
                if not remaining_shared:
                    break
                shared_only = [
                    item for item in remaining_shared
                    if item["artist"].replace("_", " ").casefold() not in rated_names
                ]
                selected_shared.append(rng.choice(shared_only or remaining_shared))
            shared_artists = [
                {"artist": item["artist"], "shared_style": True}
                for item in selected_shared
            ]
            shared_names = {item["artist"].replace("_", " ").casefold() for item in shared_artists}
            available_rows = [
                row for row in rated_rows
                if row["artist_tag"].replace("_", " ").casefold() not in shared_names
                and row["score"] in scores
            ]
            tagged_artists = []
            selected_rated_names = set()
            rule_pools = []
            for rule in rating_tag_rules:
                candidates = [
                    row for row in available_rows
                    if rating_matches_tag_filter(row, rule["tag"])
                ]
                rule_pools.append((len(candidates), rule, candidates))
            for _, rule, candidates in sorted(rule_pools, key=lambda item: item[0]):
                candidate_pool = [
                    {"artist": row["artist_tag"], "score": row["score"]}
                    for row in candidates
                    if row["artist_tag"].replace("_", " ").casefold()
                    not in selected_rated_names
                ]
                if len(candidate_pool) < rule["count"]:
                    raise ValueError(
                        f"'{rule['tag']}' 태그에서 선택 가능한 평가 작가가 {rule['count']}명보다 적습니다."
                    )
                selected = select_artists(
                    candidate_pool,
                    rule["count"],
                    scores,
                    rng_seed=rng.randrange(0, 2**32),
                )
                tagged_artists.extend(selected)
                selected_rated_names.update(
                    item["artist"].replace("_", " ").casefold()
                    for item in selected
                )
            unrestricted_count = (
                random_target_count - len(shared_artists) - len(tagged_artists)
            )
            unrestricted_pool = [
                {"artist": row["artist_tag"], "score": row["score"]}
                for row in available_rows
                if row["artist_tag"].replace("_", " ").casefold()
                not in selected_rated_names
            ]
            unrestricted_artists = select_artists(
                unrestricted_pool,
                unrestricted_count,
                scores,
                rng_seed=rng.randrange(0, 2**32),
            ) if unrestricted_count else []
            artists = tagged_artists + unrestricted_artists + shared_artists
            rng.shuffle(artists)

        if reroll == "artists":
            current_random_artists = [
                item for item in current_artists
                if item["artist"].replace("_", " ").casefold() not in fixed_names
            ]
            if len(current_random_artists) == len(artists):
                weighted = [
                    item | {"weight": current_random_artists[index]["weight"]}
                    for index, item in enumerate(artists)
                ]
            else:
                weighted = assign_weights(
                    artists,
                    payload.get("weight_mode", "balanced"),
                    payload.get("min_weight", 0.1),
                    payload.get("max_weight", 2.3),
                    prefer_high_scores,
                    ranges,
                    rng_seed=rng_seed,
                    profile=payload.get("weight_profile"),
                    positions=profile_positions,
                )
            weighted.extend(fixed_artists)
        else:
            weighted = assign_weights(
                artists,
                payload.get("weight_mode", "balanced"),
                payload.get("min_weight", 0.1),
                payload.get("max_weight", 2.3),
                prefer_high_scores,
                ranges,
                rng_seed=rng_seed,
                profile=payload.get("weight_profile"),
                positions=profile_positions if reroll != "weights" else None,
            )
            if reroll != "weights":
                weighted.extend(fixed_artists)
            if reroll != "weights" and payload.get("weight_mode") != "profile":
                weighted.sort(key=lambda item: item["weight"])
        artist_prompt = build_artist_prompt(weighted)
        return json_response(
            {
                "ok": True,
                "artists": weighted,
                "artist_prompt": artist_prompt,
                "style_hash": style_hash(weighted),
            }
        )
    except (TypeError, ValueError, OverflowError) as exc:
        return json_response({"ok": False, "error": str(exc)}, 400)


@app.route("/api/style-maker/prompt-presets", methods=["POST"])
def api_style_maker_prompt_presets():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json_response({"ok": False, "error": "요청 내용을 확인해 주세요."}, 400)
    try:
        result = get_style_maker_prompt_presets(
            DB_PATH,
            payload.get("artists", []),
            payload.get("limit", 30),
        )
        overrides = load_prompt_preset_overrides(SETTINGS_JSON_PATH, DATA_DIR)
        for preset in result.get("presets", []):
            preset["original_quality_prompt"] = preset.get("base_prompt") or preset.get("quality_prompt") or ""
            override = overrides.get(preset.get("key"))
            if override:
                preset["base_prompt"] = override
                preset["quality_prompt"] = override
                preset["modified"] = True
            image = preset.get("representative_image") or {}
            image_path = image.get("image_path") or ""
            image["image_url"] = f"/arca-style-images/{image_path}" if image_path else image.get("remote_image_url") or ""
            image["thumbnail_url"] = f"/style-manager-thumbnails/shared/{image_path}" if image_path else image["image_url"]
        return json_response({"ok": True, **result})
    except (ArcaCollectorError, SettingsError) as exc:
        return json_response({"ok": False, "error": str(exc)}, 400)


@app.route("/api/style-maker/prompt-presets/<preset_key>", methods=["PATCH"])
def api_update_style_maker_prompt_preset(preset_key):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json_response({"ok": False, "error": "요청 내용을 확인해 주세요."}, 400)
    try:
        quality_prompt = save_prompt_preset_override(
            SETTINGS_JSON_PATH,
            DATA_DIR,
            preset_key,
            payload.get("quality_prompt"),
        )
        return json_response({"ok": True, "key": preset_key, "quality_prompt": quality_prompt, "modified": True})
    except (ValueError, SettingsError) as exc:
        return json_response({"ok": False, "error": str(exc)}, 400)


@app.route("/api/settings/novelai", methods=["GET", "PUT", "DELETE"])
def api_novelai_settings():
    try:
        if request.method == "GET":
            return json_response(
                {"configured": bool(load_app_key(SETTINGS_JSON_PATH, DATA_DIR))}
            )

        if request.method == "DELETE":
            delete_app_key(SETTINGS_JSON_PATH, DATA_DIR)
            return json_response({"configured": False})

        if request.mimetype != "application/json":
            return json_response({"error": "Request must use application/json."}, 400)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return json_response({"error": "Request body must be a JSON object."}, 400)
        try:
            save_app_key(SETTINGS_JSON_PATH, payload.get("app_key"), DATA_DIR)
        except ValueError as exc:
            return json_response({"error": str(exc)}, 400)
        return json_response({"configured": True})
    except SettingsError:
        return json_response(
            {"error": "Settings file is invalid or unsafe; no changes were made."},
            409,
        )


@app.route("/api/settings/novelai/test", methods=["POST"])
def api_test_novelai_settings():
    try:
        app_key = load_app_key(SETTINGS_JSON_PATH, DATA_DIR)
    except SettingsError:
        return json_response(
            {
                "ok": False,
                "configured": False,
                "error": "Settings file is invalid or unsafe; no changes were made.",
            },
            409,
        )
    if not app_key:
        return json_response(
            {
                "ok": False,
                "configured": False,
                "error": "저장된 NovelAI App Key가 없습니다.",
            },
            400,
        )
    try:
        result = test_novelai_subscription(app_key)
    except NovelAIError as exc:
        return json_response(
            {
                "ok": False,
                "configured": True,
                "error": exc.public_message,
            },
            exc.status_code,
        )
    response = {"ok": True, "configured": True, "anlas": result["anlas"]}
    if result.get("usage"):
        response["usage"] = result["usage"]
    return json_response(response)


@app.route("/api/settings/preferences", methods=["GET", "PUT"])
def api_settings_preferences():
    try:
        if request.method == "GET":
            return json_response({
                "skip_delete_confirmation": load_skip_delete_confirmation(
                    SETTINGS_JSON_PATH, DATA_DIR
                ),
            })
        if request.mimetype != "application/json":
            return json_response({"error": "Request must use application/json."}, 400)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return json_response({"error": "Request body must be a JSON object."}, 400)
        if set(payload) != {"skip_delete_confirmation"}:
            return json_response({"error": "Only skip_delete_confirmation is accepted."}, 400)
        try:
            value = payload.get("skip_delete_confirmation")
            if not isinstance(value, dict):
                raise ValueError("skip_delete_confirmation must be an object.")
            value = normalize_delete_confirmation_preferences(value)
            save_skip_delete_confirmation(SETTINGS_JSON_PATH, value, DATA_DIR)
        except ValueError as exc:
            return json_response({"error": str(exc)}, 400)
        return json_response({"skip_delete_confirmation": value})
    except SettingsError:
        return json_response(
            {"error": "Settings file is invalid or unsafe; no changes were made."},
            409,
        )


def validate_supplied_style_artists(supplied, require_weights=False):
    if not isinstance(supplied, list) or not supplied:
        raise ValueError("작가 목록을 하나 이상 입력하세요.")

    artists = []
    seen = set()
    for item in supplied:
        if not isinstance(item, dict):
            raise ValueError("작가 목록 형식을 확인하세요.")
        artist = str(item.get("artist") or "").strip()
        if not artist:
            raise ValueError("작가 태그를 확인하세요.")
        normalized_name = _style_artist_key(artist)
        if normalized_name in seen:
            raise ValueError("중복된 작가는 사용할 수 없습니다.")
        normalized = {"artist": artist}
        if item.get("score") is not None:
            normalized["score"] = exact_score(
                item.get("score"),
                "작가 평점은 1부터 5 사이의 정수여야 합니다.",
            )
        if "weight" in item:
            normalized["weight"] = normalize_style_artists([item])[0]["weight"]
        elif require_weights:
            raise ValueError("Artist reroll requires the current positional weights.")
        if type(item.get("slot")) is int and item["slot"] >= 0:
            normalized["slot"] = item["slot"]
        if item.get("random_weight") is True:
            normalized["random_weight"] = True
        artists.append(normalized)
        seen.add(normalized_name)

    return artists


def _style_artist_key(value):
    return str(value or "").replace("_", " ").strip().casefold()


def _shared_dependency_options(payload):
    """Validate the one-stage source allocation for shared dependency mode."""
    if "shared_dependency_percent" in payload:
        raise ValueError("공유 그림체 의존의 이전 퍼센트 설정은 사용할 수 없습니다.")
    reference_id = payload.get("shared_dependency_reference_id")
    if reference_id is not None and (type(reference_id) is not int or reference_id < 1):
        raise ValueError("공유 그림체 기준 이미지 ID를 확인하세요.")
    reference_mode = payload.get("shared_dependency_reference_mode")
    if reference_mode is None:
        # Before explicit modes were introduced, all/artist rerolls ignored
        # the incoming reference ID and selected a fresh random basis. Weight
        # rerolls still use that ID below to preserve the current basis.
        reference_mode = "random"
    if reference_mode not in {"random", "fixed"}:
        raise ValueError("공유 그림체 기준 선택 방식은 random 또는 fixed여야 합니다.")
    if reference_mode == "fixed" and reference_id is None and payload.get("reroll") != "weights":
        raise ValueError("고정 기준 그림체 이미지 ID가 필요합니다.")
    ratios = payload.get("shared_dependency_source_ratios", {
        "fixed": 0,
        "reference": 100,
        "rated": 0,
        "other_shared": 0,
    })
    if not isinstance(ratios, dict):
        raise ValueError("공유 그림체 의존 공급원 비율 형식을 확인하세요.")
    expected = {"fixed", "reference", "rated", "other_shared"}
    if set(ratios) != expected:
        raise ValueError("공유 그림체 의존 공급원 비율은 fixed, reference, rated, other_shared만 사용할 수 있습니다.")
    normalized = {}
    for name in ("fixed", "reference", "rated", "other_shared"):
        value = ratios.get(name)
        if type(value) is not int or not 0 <= value <= 100:
            raise ValueError("공유 그림체 의존 공급원 비율은 0부터 100 사이의 정수여야 합니다.")
        normalized[name] = value
    if sum(normalized.values()) != 100:
        raise ValueError("공유 그림체 의존 공급원 비율의 합은 100이어야 합니다.")
    artist_policy = payload.get("shared_dependency_artist_policy")
    if artist_policy is None:
        for alias in (
            "shared_dependency_reference_artist_policy",
            "shared_dependency_artist_selection",
            "shared_dependency_reference_artist_selection",
            "shared_dependency_artist_mode",
            "shared_dependency_reference_artist_mode",
        ):
            if alias in payload:
                artist_policy = payload.get(alias)
                break
    if artist_policy is None:
        artist_policy = "highest"
    if artist_policy not in {"highest", "random"}:
        raise ValueError("공유 그림체 기준 작가 선택 방식은 highest 또는 random이어야 합니다.")
    return reference_id, normalized, reference_mode, artist_policy


def _largest_remainder_counts(total, ratios):
    if total <= 0:
        return {name: 0 for name in ratios}
    raw = {name: total * value / 100 for name, value in ratios.items()}
    counts = {name: math.floor(value) for name, value in raw.items()}
    remainder = total - sum(counts.values())
    order = sorted(ratios, key=lambda name: (-(raw[name] - counts[name]), name))
    for name in order[:remainder]:
        counts[name] += 1
    return counts


def _shared_dependency_pick(pool, count, rng, preserve_weights=False):
    if count <= 0:
        return []
    if count > len(pool):
        raise ValueError("공유 그림체 의존 공급원에서 작가를 충분히 찾지 못했습니다.")
    if preserve_weights:
        indexes = list(range(len(pool)))
        selected_indexes = rng.sample(indexes, count)
        return [dict(pool[index]) for index in selected_indexes]
    candidates = [dict(item) for item in pool]
    selected = []
    while len(selected) < count:
        weights = [SCORE_SELECTION_WEIGHT.get(int(item.get("score", 3)), 0.55) for item in candidates]
        index = rng.choices(range(len(candidates)), weights=weights, k=1)[0]
        selected.append(candidates.pop(index))
    return selected


def _shared_dependency_result(
    *,
    target_count,
    fixed_artists,
    reference,
    source_ratios,
    rated_pool,
    other_shared_pool,
    min_weight,
    max_weight,
    prefer_high_scores,
    ranges,
    weight_mode,
    weight_profile,
    rng_seed,
    blocked_names=None,
    artist_policy="highest",
):
    all_reference_artists = []
    reference_by_name = {}
    for item in reference.get("artists", []):
        key = _style_artist_key(item.get("artist"))
        if key and key not in reference_by_name:
            reference_by_name[key] = dict(item)
            all_reference_artists.append(dict(item))
    total_count = len(all_reference_artists)
    if total_count < 1:
        raise ValueError("기준 공유 그림체에서 파싱 가능한 작가를 찾지 못했습니다.")

    rng = random.Random(rng_seed)
    fixed_by_name = {}
    for item in fixed_artists:
        key = _style_artist_key(item.get("artist"))
        if key and key not in fixed_by_name:
            fixed_by_name[key] = dict(item)
    blocked = {_style_artist_key(name) for name in (blocked_names or [])}
    blocked -= set(fixed_by_name)
    desired_counts = _largest_remainder_counts(total_count, source_ratios)
    fixed_candidates = list(fixed_by_name.values())
    selected_fixed = _shared_dependency_pick(
        fixed_candidates,
        min(desired_counts["fixed"], len(fixed_candidates)),
        rng,
        preserve_weights=True,
    )
    selected_fixed = [dict(item, shared_dependency_source="fixed") for item in selected_fixed]
    fixed_names = {_style_artist_key(item["artist"]) for item in selected_fixed}
    blocked |= fixed_names
    def unique_pool(items, source, *, shared=False):
        result = []
        seen = set()
        for item in items:
            key = _style_artist_key(item.get("artist"))
            if not key or key in seen or key in blocked:
                continue
            seen.add(key)
            entry = dict(item, shared_dependency_source=source)
            if shared:
                entry["shared_style"] = True
            result.append(entry)
        return result

    reference_pool = unique_pool(all_reference_artists, "reference", shared=True)
    pools = {
        "reference": reference_pool,
        "rated": unique_pool(rated_pool, "rated"),
        "other_shared": unique_pool(other_shared_pool, "other_shared", shared=True),
    }
    selected_by_source = {name: [] for name in pools}
    used_names = set(fixed_names)

    def select_reference(pool, count):
        available = [item for item in pool if _style_artist_key(item["artist"]) not in used_names]
        take = min(count, len(available))
        if take <= 0:
            return []
        if artist_policy == "random":
            return rng.sample(available, take)
        highest = max(
            available,
            key=lambda item: (float(item.get("weight", 1.0)), -available.index(item)),
        )
        selected = [highest]
        remaining = [item for item in available if item is not highest]
        if take > 1:
            selected.extend(rng.sample(remaining, take - 1))
        selected_names = {_style_artist_key(item["artist"]) for item in selected}
        return [item for item in available if _style_artist_key(item["artist"]) in selected_names]

    def select_source(name, count):
        available = [item for item in pools[name] if _style_artist_key(item["artist"]) not in used_names]
        take = min(count, len(available))
        if name == "reference":
            selected = select_reference(available, take)
        else:
            selected = _shared_dependency_pick(
                available, take, rng, preserve_weights=name == "other_shared"
            )
        selected_by_source[name].extend(selected)
        used_names.update(_style_artist_key(item["artist"]) for item in selected)
        return take

    unavailable = desired_counts["fixed"] - len(selected_fixed)
    for name in ("reference", "rated", "other_shared"):
        unavailable += desired_counts[name] - select_source(name, desired_counts[name])
    if unavailable:
        fallback_sources = [
            name for name in ("reference", "rated", "other_shared")
            if source_ratios[name] > 0
        ]
        while unavailable:
            progressed = False
            for name in fallback_sources:
                if select_source(name, 1):
                    unavailable -= 1
                    progressed = True
                    if unavailable == 0:
                        break
            if not progressed:
                break
    if unavailable:
        raise ValueError("공급원 후보가 부족하여 전체 작가 수를 채울 수 없습니다.")

    reference_order = {
        _style_artist_key(item["artist"]): index
        for index, item in enumerate(all_reference_artists)
    }
    selected_by_source["reference"].sort(
        key=lambda item: reference_order.get(_style_artist_key(item["artist"]), len(reference_order))
    )
    selected_reference = selected_by_source["reference"]
    selected_fill = (
        selected_reference
        + selected_by_source["rated"]
        + selected_by_source["other_shared"]
    )
    all_non_fixed = selected_fill
    needs_weights = [item for item in all_non_fixed if "weight" not in item]
    if needs_weights:
        weighted = assign_weights(
            all_non_fixed,
            weight_mode if weight_mode in {"random", "balanced", "custom", "profile"} else "balanced",
            min_weight,
            max_weight,
            prefer_high_scores,
            ranges,
            rng_seed=rng.randrange(0, 2**32),
            profile=weight_profile,
        )
    else:
        weighted = all_non_fixed
    # Restore reference/other-shared source weights after assigning fill weights.
    original_weights = {
        _style_artist_key(item["artist"]): item.get("weight")
        for item in selected_reference + selected_by_source["other_shared"]
    }
    for item in weighted:
        key = _style_artist_key(item["artist"])
        if key in original_weights and original_weights[key] is not None:
            item["weight"] = round(float(original_weights[key]), 2)
    # Keep explicit fixed table positions in the returned prompt order. Slot 0
    # remains the existing random-order marker; unpositioned rows fill the
    # remaining open positions after the dependency selection.
    placed = [None] * total_count
    pending_fixed = []
    for item in selected_fixed:
        slot = item.get("slot")
        if type(slot) is int and 0 < slot <= total_count and placed[slot - 1] is None:
            placed[slot - 1] = dict(item)
        else:
            pending_fixed.append(dict(item))
    # Reserve the remaining positions for slot-0/unpositioned fixed rows
    # before filling dependency artists; otherwise the latter can consume all
    # empty slots and silently drop fixed rows.
    remaining_fixed = iter(pending_fixed)
    for index, item in enumerate(placed):
        if item is None:
            try:
                placed[index] = next(remaining_fixed)
            except StopIteration:
                break
    open_items = iter(weighted)
    for index, item in enumerate(placed):
        if item is None:
            try:
                placed[index] = next(open_items)
            except StopIteration:
                break
    return [item for item in placed if item is not None]


def _generation_response(result):
    payload = {
        "style_id": result["style_id"],
        "image_id": result["image_id"],
        "image_path": result["image_path"],
        "image_url": f'/generated/{result["image_path"]}',
        "artist_prompt": result["artist_prompt"],
        "seed": result["seed"],
        "width": result["width"],
        "height": result["height"],
        "sampler": result["sampler"],
        "noise_schedule": result["noise_schedule"],
        "steps": result["steps"],
        "scale": result["scale"],
        "cfg_rescale": result["cfg_rescale"],
        "model": result["model"],
        "complexity": result.get("complexity") or "",
        "quality_toggle": bool(result.get("quality_toggle")),
        "uc_preset": result.get("uc_preset") or 0,
    }
    for key in (
        "shared_dependency_reference_id",
        "shared_dependency_reference_mode",
        "shared_dependency_reference_title",
        "shared_dependency_reference_source_url",
        "shared_dependency_scale_source",
        "shared_dependency_cfg_rescale_source",
        "shared_dependency_artist_policy",
    ):
        if key in result and result[key] is not None:
            payload[key] = result[key]
    return payload


def _valid_generation_reference_value(value, minimum, maximum):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        return None
    return numeric


def _validate_generation_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    request_id = payload.get("request_id")
    if type(request_id) is not str or not SAFE_REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must be a nonempty safe string up to 128 characters.")
    generation_payload = dict(payload)
    if payload.get("weight_mode") == "shared_dependency":
        artist_policy = payload.get("shared_dependency_artist_policy")
        if artist_policy is None:
            for alias in (
                "shared_dependency_reference_artist_policy",
                "shared_dependency_artist_selection",
                "shared_dependency_reference_artist_selection",
                "shared_dependency_artist_mode",
                "shared_dependency_reference_artist_mode",
            ):
                if alias in payload:
                    artist_policy = payload.get(alias)
                    break
        if artist_policy is None:
            artist_policy = "highest"
        if artist_policy not in {"highest", "random"}:
            raise ValueError("공유 그림체 기준 작가 선택 방식은 highest 또는 random이어야 합니다.")
        generation_payload["shared_dependency_artist_policy"] = artist_policy
    reference_id = payload.get("shared_dependency_reference_id")
    if payload.get("weight_mode") == "shared_dependency" and reference_id is not None:
        reference_mode = payload.get("shared_dependency_reference_mode", "fixed")
        if reference_mode not in {"random", "fixed"}:
            raise ValueError("공유 그림체 기준 선택 방식은 random 또는 fixed여야 합니다.")
        if type(reference_id) is not int or reference_id < 1:
            raise ValueError("공유 그림체 기준 이미지 ID를 확인하세요.")
        reference = next(
            (
                item for item in get_shared_style_dependency_images(DB_PATH)
                if item.get("id") == reference_id
            ),
            None,
        )
        if reference is None:
            raise ValueError("공유 그림체 기준 이미지를 찾을 수 없습니다.")
        scale = _valid_generation_reference_value(reference.get("scale"), 0, 10)
        cfg_rescale = _valid_generation_reference_value(reference.get("cfg_rescale"), 0, 1)
        generation_payload["shared_dependency_scale_source"] = "reference" if scale is not None else "fallback"
        generation_payload["shared_dependency_cfg_rescale_source"] = "reference" if cfg_rescale is not None else "fallback"
        if scale is not None:
            generation_payload["scale"] = scale
        if cfg_rescale is not None:
            generation_payload["cfg_rescale"] = cfg_rescale
        generation_payload["shared_dependency_reference_id"] = reference_id
        generation_payload["shared_dependency_reference_mode"] = reference_mode
        generation_payload["shared_dependency_reference"] = {
            "id": reference_id,
            "title": reference.get("title") or "",
            "source_url": reference.get("source_url") or "",
        }
    normalized = normalize_generation_data(generation_payload)
    normalized["request_id"] = request_id
    normalized["seed_provided"] = "seed" in payload
    normalized_artists = normalize_style_artists(payload.get("artists"))
    normalized["artists"] = normalized_artists
    return normalized


def _generation_payload_hash(data):
    canonical = {
        "artists": data["artists"],
        "base_prompt": data["base_prompt"],
        "quality_prompt": data["quality_prompt"],
        "original_quality_prompt": data["original_quality_prompt"],
        "excluded_quality_tags": data["excluded_quality_tags"],
        "fixed_prompt": data["fixed_prompt"],
        "negative_prompt": data["negative_prompt"],
        "character_prompts": data["character_prompts"],
        "width": data["width"],
        "height": data["height"],
        "sampler": data["sampler"],
        "noise_schedule": data["noise_schedule"],
        "steps": data["steps"],
        "scale": data["scale"],
        "cfg_rescale": data["cfg_rescale"],
        "weight_mode": data.get("weight_mode"),
        "shared_dependency_reference_id": data.get("shared_dependency_reference_id"),
        "shared_dependency_reference_mode": data.get("shared_dependency_reference_mode"),
        "variety_plus": data["variety_plus"],
        "skip_cfg_above_sigma": data["skip_cfg_above_sigma"],
        "seed": data["seed"] if data["seed_provided"] else None,
        "model": data["model"],
        "quality_toggle": data["quality_toggle"],
        "uc_preset": data["uc_preset"],
        "complexity": data["complexity"],
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@app.route("/api/style-maker/generate", methods=["POST"])
def api_style_maker_generate():
    if not request.is_json:
        return json_response({"error": "Request must use application/json."}, 400)
    try:
        data = _validate_generation_request(request.get_json(silent=True))
    except (TypeError, ValueError, OverflowError) as exc:
        return json_response({"error": str(exc)}, 400)

    request_id = data["request_id"]
    payload_hash = _generation_payload_hash(data)
    try:
        reservation, existing = reserve_generation_request(
            DB_PATH, request_id, payload_hash
        )
    except sqlite3.Error:
        return json_response({"error": "Could not reserve the generation request."}, 500)
    if reservation == "mismatch":
        return json_response(
            {"error": "request_id was already used with a different payload."}, 409
        )
    if reservation == "complete":
        return json_response(_generation_response(existing))
    if reservation == "processing":
        return json_response({"error": "Generation request is already processing."}, 409)

    completed = False
    try:
        try:
            app_key = load_app_key(SETTINGS_JSON_PATH, DATA_DIR)
        except SettingsError:
            return json_response({"error": "Settings file is invalid or unsafe."}, 409)
        if not app_key:
            return json_response({"error": "No NovelAI App Key is configured."}, 400)

        artist_prompt = build_artist_prompt(data["artists"])
        combined_prompt = combine_generation_prompt(data, artist_prompt)
        png_bytes, actual_seed = generate_novelai_png(
            app_key, data, artist_prompt, None, data["model"]
        )
        result = save_generated_result(
            DB_PATH,
            GENERATED_DIR,
            request_id=request_id,
            artists=data["artists"],
            png_bytes=png_bytes,
            base_prompt=data["base_prompt"],
            quality_prompt=data["quality_prompt"],
            original_quality_prompt=data["original_quality_prompt"],
            excluded_quality_tags=data["excluded_quality_tags"],
            fixed_prompt=data["fixed_prompt"],
            negative_prompt=data["negative_prompt"],
            character_prompts=data["character_prompts"],
            combined_prompt=combined_prompt,
            seed=actual_seed,
            width=data["width"],
            height=data["height"],
            sampler=data["sampler"],
            noise_schedule=data["noise_schedule"],
            steps=data["steps"],
            scale=data["scale"],
            cfg_rescale=data["cfg_rescale"],
            variety_plus=data["variety_plus"],
            skip_cfg_above_sigma=data["skip_cfg_above_sigma"],
            model=data["model"],
            complexity=data["complexity"],
            quality_toggle=data["quality_toggle"],
            uc_preset=data["uc_preset"],
            shared_dependency_reference=data.get("shared_dependency_reference"),
            shared_dependency_artist_policy=data.get("shared_dependency_artist_policy"),
        )
        for key in (
            "shared_dependency_reference_id",
            "shared_dependency_reference_title",
            "shared_dependency_reference_source_url",
            "shared_dependency_scale_source",
            "shared_dependency_cfg_rescale_source",
            "shared_dependency_artist_policy",
        ):
            if key in data:
                result[key] = data[key]
        result["seed"] = actual_seed
        completed = True
        return json_response(_generation_response(result))
    except NovelAIError as exc:
        return json_response({"error": exc.public_message}, exc.status_code)
    except (OSError, sqlite3.Error, ValueError):
        return json_response({"error": "Could not store the generated image."}, 500)
    finally:
        if not completed:
            release_generation_request(DB_PATH, request_id)


@app.route("/api/style-maker/models", methods=["GET"])
def api_style_maker_models():
    return json_response(
        [
            item
            for item in model_definitions_for_api()
            if item["generation"] in {"V5", "V4.5"}
        ]
    )


def _add_generated_urls(item):
    image_path = item.get("image_path") or ""
    if image_path:
        item["image_url"] = f"/generated/{image_path}"
        item["thumbnail_url"] = f"/style-manager-thumbnails/generated/{image_path}"
    representative = item.get("representative_image_path") or ""
    if representative:
        item["representative_image_url"] = f"/generated/{representative}"
    return item


@app.route("/api/art-styles", methods=["GET"])
def api_art_styles():
    return json_response([_add_generated_urls(item) for item in list_styles(DB_PATH)])


@app.route("/api/art-styles/delete-batch", methods=["POST"])
def api_delete_art_styles_batch():
    payload = request.get_json(silent=True)
    style_ids = payload.get("style_ids") if isinstance(payload, dict) else None
    if (
        not isinstance(style_ids, list)
        or not style_ids
        or len(style_ids) > 500
        or any(type(style_id) is not int or style_id < 1 for style_id in style_ids)
    ):
        return json_response(
            {"error": "style_ids must be a nonempty list of up to 500 positive integers."},
            400,
        )
    unique_ids = list(dict.fromkeys(style_ids))
    deleted_ids = []
    missing_ids = []
    for style_id in unique_ids:
        if delete_style(DB_PATH, GENERATED_DIR, style_id) is None:
            missing_ids.append(style_id)
        else:
            deleted_ids.append(style_id)
    return json_response({"deleted_ids": deleted_ids, "missing_ids": missing_ids})


@app.route("/api/art-styles/<int:style_id>", methods=["GET", "DELETE"])
def api_art_style_detail(style_id):
    if request.method == "DELETE":
        deleted = delete_style(DB_PATH, GENERATED_DIR, style_id)
        if deleted is None:
            return json_response({"error": "Art style not found."}, 404)
        return json_response(deleted)
    detail = get_style_detail(DB_PATH, style_id)
    if detail is None:
        return json_response({"error": "Art style not found."}, 404)
    _add_generated_urls(detail)
    detail["images"] = [_add_generated_urls(image) for image in detail["images"]]
    return json_response(detail)


def _add_arca_urls(item):
    def add_image_url(image):
        if not image:
            return
        image_path = image.get("image_path") or ""
        image["image_url"] = f"/arca-style-images/{image_path}" if image_path else ""
        image["image_available"] = bool(image_path)

    representative = item.get("representative_image_path") or ""
    item["representative_image_url"] = f"/arca-style-images/{representative}" if representative else ""
    item["representative_image_available"] = bool(representative)
    for image in item.get("images", []):
        add_image_url(image)
    for collection_name in ("artists", "quality_tags", "quality_sequences"):
        for entry in item.get(collection_name, []):
            add_image_url(entry.get("representative_image"))
    for group in item.get("style_groups", []):
        for image in group.get("images", []):
            add_image_url(image)
    return item


def _add_confirmed_url(item):
    if item and item.get("image_path"):
        item["image_url"] = f'/confirmed-style-images/{item["image_path"]}'
        item["thumbnail_url"] = f'/style-manager-thumbnails/confirmed/{item["image_path"]}'
    for image in (item or {}).get("images", []):
        image_path = image.get("image_path") or ""
        image["image_url"] = f"/confirmed-style-images/{image_path}" if image_path else ""
    return item


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _confirmed_metadata_from_bytes(image_bytes, content_type=""):
    image_info = inspect_image(image_bytes)
    metadata = extract_novelai_metadata(image_bytes, content_type)
    artist_prompt, quality_prompt = split_artist_quality_prompt(metadata.get("base_prompt") or "")
    raw_metadata = _json_object(metadata.get("raw_metadata_json"))
    character_prompts = [
        entry.get("prompt") if isinstance(entry, dict) else entry
        for entry in metadata.get("character_prompts") or []
    ]
    character_prompts = [str(prompt).strip() for prompt in character_prompts if str(prompt or "").strip()]
    return {
        "metadata_status": metadata.get("metadata_status") or "no_metadata",
        "artist_prompt": artist_prompt,
        "quality_prompt": quality_prompt,
        "original_quality_prompt": quality_prompt,
        "excluded_quality_tags": [],
        "fixed_prompt": "",
        "character_prompts": character_prompts,
        "negative_prompt": metadata.get("negative_prompt") or "",
        "sampler": metadata.get("sampler") or "",
        "noise_schedule": metadata.get("noise_schedule") or "",
        "steps": metadata.get("steps"),
        "scale": metadata.get("scale"),
        "cfg_rescale": metadata.get("cfg_rescale"),
        "variety_plus": metadata.get("variety_plus"),
        "skip_cfg_above_sigma": metadata.get("skip_cfg_above_sigma"),
        "model": normalize_confirmed_model_name(metadata.get("model")),
        "complexity": metadata.get("complexity") or "",
        "width": metadata.get("width") or image_info["width"],
        "height": metadata.get("height") or image_info["height"],
        "seed": metadata.get("seed") or None,
        "raw_metadata": raw_metadata,
    }


def _safe_source_image(root, relative_path):
    path = Path(str(relative_path or "").replace("\\", "/"))
    resolved_root = Path(root).resolve()
    target = (resolved_root / path).resolve()
    if not relative_path or resolved_root not in target.parents or not target.is_file():
        raise ValueError("원본 이미지가 로컬에 저장되어 있지 않습니다.")
    return target.read_bytes()


def _confirmed_source(source_type, source_id):
    connection = db()
    try:
        if source_type == "generated":
            row = connection.execute("SELECT * FROM generated_images WHERE id=?", (source_id,)).fetchone()
            if row is None:
                raise ValueError("제작 기록 이미지를 찾을 수 없습니다.")
            item = dict(row)
            image_bytes = _safe_source_image(GENERATED_DIR, item.get("image_path"))
            try:
                excluded = json.loads(item.get("excluded_quality_tags_json") or "[]")
            except json.JSONDecodeError:
                excluded = []
            try:
                character_prompts = json.loads(item.get("character_prompts_json") or "[]")
            except json.JSONDecodeError:
                character_prompts = []
            quality = item.get("quality_prompt") or item.get("base_prompt") or ""
            payload = {
                "name": f"제작 그림체 #{source_id}",
                "description": "",
                "artist_prompt": item.get("artist_prompt") or "",
                "quality_prompt": quality,
                "original_quality_prompt": item.get("original_quality_prompt") or quality,
                "excluded_quality_tags": excluded,
                "fixed_prompt": item.get("fixed_prompt") or "",
                "character_prompts": character_prompts,
                "negative_prompt": item.get("negative_prompt") or "",
                "sampler": item.get("sampler") or "",
                "noise_schedule": item.get("noise_schedule") or "",
                "steps": item.get("steps"),
                "scale": item.get("scale"),
                "cfg_rescale": item.get("cfg_rescale"),
                "variety_plus": bool(item["variety_plus"]) if item.get("variety_plus") is not None else None,
                "skip_cfg_above_sigma": item.get("skip_cfg_above_sigma"),
                "model": item.get("model") or "",
                "complexity": item.get("complexity") or "",
                "quality_toggle": bool(item.get("quality_toggle")),
                "uc_preset": item.get("uc_preset") or 0,
                "width": item.get("width"),
                "height": item.get("height"),
                "seed": item.get("seed"),
                "raw_metadata": {},
                "source_type": "generated",
                "source_id": source_id,
                "source_url": "",
            }
            return image_bytes, payload
        if source_type == "shared":
            row = connection.execute(
                """
                SELECT image.*,item.title,item.source_url
                FROM arca_style_images image
                JOIN arca_style_items item ON item.id=image.item_id
                WHERE image.id=?
                """,
                (source_id,),
            ).fetchone()
            if row is None:
                raise ValueError("공유 그림체 이미지를 찾을 수 없습니다.")
            item = dict(row)
            image_bytes = _safe_source_image(ARCA_STYLE_IMAGE_DIR, item.get("image_path"))
            image_metadata = extract_novelai_metadata(image_bytes, item.get("content_type") or "")
            prompt = item.get("base_prompt") or item.get("prompt") or ""
            artist_prompt, quality_prompt = split_artist_quality_prompt(prompt)
            raw_metadata = _json_object(item.get("raw_metadata_json"))
            skip_present = "skip_cfg_above_sigma" in raw_metadata
            skip_cfg = raw_metadata.get("skip_cfg_above_sigma") if skip_present else None
            payload = {
                "name": item.get("title") or f"공유 그림체 #{source_id}",
                "description": "",
                "artist_prompt": artist_prompt,
                "quality_prompt": quality_prompt,
                "original_quality_prompt": quality_prompt,
                "excluded_quality_tags": [],
                "fixed_prompt": "",
                "character_prompts": [
                    entry.get("prompt") if isinstance(entry, dict) else entry
                    for entry in image_metadata.get("character_prompts") or []
                    if str(entry.get("prompt") if isinstance(entry, dict) else entry or "").strip()
                ],
                "negative_prompt": item.get("negative_prompt") or "",
                "sampler": item.get("sampler") or "",
                "noise_schedule": item.get("noise_schedule") or "",
                "steps": item.get("steps"),
                "scale": item.get("scale"),
                "cfg_rescale": item.get("cfg_rescale"),
                "variety_plus": bool(skip_cfg) if skip_present else None,
                "skip_cfg_above_sigma": skip_cfg,
                "model": item.get("model") or image_metadata.get("model") or "",
                "complexity": image_metadata.get("complexity") or "",
                "quality_toggle": bool(item.get("quality_toggle")) if item.get("quality_toggle") is not None else False,
                "uc_preset": item.get("uc_preset") or 0,
                "width": item.get("width"),
                "height": item.get("height"),
                "seed": item.get("seed") or None,
                "raw_metadata": raw_metadata,
                "source_type": "shared",
                "source_id": source_id,
                "source_url": item.get("source_url") or "",
            }
            return image_bytes, payload
    finally:
        connection.close()
    raise ValueError("확정 그림체 원본 종류를 확인해 주세요.")


@app.route("/api/style-manager/generated", methods=["GET"])
def api_style_manager_generated():
    return json_response([_add_generated_urls(item) for item in list_generated_images(DB_PATH)])


@app.route("/api/style-manager/generated/delete-batch", methods=["POST"])
def api_delete_generated_images_batch():
    payload = request.get_json(silent=True)
    image_ids = payload.get("image_ids") if isinstance(payload, dict) else None
    if not isinstance(image_ids, list) or not image_ids or len(image_ids) > 500 or any(type(value) is not int or value < 1 for value in image_ids):
        return json_response({"error": "image_ids must contain up to 500 positive integers."}, 400)
    deleted_ids = delete_generated_image_batch(DB_PATH, GENERATED_DIR, image_ids)
    return json_response({"deleted_ids": deleted_ids})


@app.route("/api/style-manager/shared", methods=["GET"])
def api_style_manager_shared():
    try:
        result = get_arca_image_gallery_page(
            DB_PATH,
            request.args.get("offset", 0),
            request.args.get("limit", 60),
            ARCA_STYLE_IMAGE_DIR,
            {
                "q": request.args.get("q", ""),
                "tab": request.args.get("tab", "all"),
                "metadata": request.args.get("metadata", "all"),
                "model": request.args.get("model", "all"),
                "recommendation_min": request.args.get("recommendation_min", ""),
                "sort": request.args.get("sort", "posted_desc"),
            },
        )
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)
    dependency_by_id = {
        candidate["id"]: candidate
        for candidate in get_shared_style_dependency_images(DB_PATH)
    }
    for item in result["items"]:
        local_path = item.get("image_path") or ""
        item["image_url"] = f"/arca-style-images/{local_path}" if local_path else item.get("remote_image_url") or ""
        item["thumbnail_url"] = f"/style-manager-thumbnails/shared/{local_path}" if local_path else item["image_url"]
        item["image_available"] = bool(item["image_url"])
        dependency = dependency_by_id.get(item.get("id"))
        item["shared_dependency_eligible"] = dependency is not None
        item["shared_dependency_artists"] = dependency.get("artists", []) if dependency else []
        if local_path and not item.get("model"):
            try:
                image_metadata = extract_novelai_metadata(
                    _safe_source_image(ARCA_STYLE_IMAGE_DIR, local_path),
                    item.get("content_type") or "",
                )
                item["model"] = image_metadata.get("model") or ""
            except ValueError:
                pass
    return json_response(result)


@app.route("/api/confirmed-styles/extract", methods=["POST"])
def api_extract_confirmed_style():
    uploaded = request.files.get("image")
    if uploaded is None:
        return json_response({"error": "이미지 파일을 선택해 주세요."}, 400)
    image_bytes = uploaded.stream.read(MAX_CONFIRMED_IMAGE_BYTES + 1)
    try:
        result = _confirmed_metadata_from_bytes(image_bytes, uploaded.mimetype or "")
    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@app.route("/api/confirmed-styles", methods=["GET", "POST"])
def api_confirmed_styles():
    if request.method == "GET":
        return json_response([_add_confirmed_url(item) for item in list_confirmed_styles(DB_PATH)])
    try:
        if request.mimetype and request.mimetype.startswith("multipart/form-data"):
            uploaded = request.files.get("image")
            if uploaded is None:
                raise ValueError("이미지 파일을 선택해 주세요.")
            image_bytes = uploaded.stream.read(MAX_CONFIRMED_IMAGE_BYTES + 1)
            supplied = json.loads(request.form.get("data") or "{}")
            if not isinstance(supplied, dict):
                raise ValueError("그림체 입력값을 확인해 주세요.")
            extracted = _confirmed_metadata_from_bytes(image_bytes, uploaded.mimetype or "")
            payload = {**extracted, **supplied, "source_type": "manual", "source_id": None}
        else:
            supplied = request.get_json(silent=True)
            if not isinstance(supplied, dict):
                raise ValueError("그림체 입력값을 확인해 주세요.")
            source_type = supplied.get("source_type")
            source_id = supplied.get("source_id")
            if source_type not in {"generated", "shared"} or type(source_id) is not int:
                raise ValueError("확정할 원본 그림체를 확인해 주세요.")
            image_bytes, defaults = _confirmed_source(source_type, source_id)
            payload = {**defaults, **supplied, "source_type": source_type, "source_id": source_id}
            if not str(supplied.get("model") or "").strip():
                payload["model"] = defaults.get("model") or ""
        created = create_confirmed_style(DB_PATH, CONFIRMED_STYLE_IMAGE_DIR, image_bytes, payload)
        return json_response(_add_confirmed_url(created), 201)
    except (ValueError, json.JSONDecodeError) as exc:
        return json_response({"error": str(exc)}, 400)
    except (OSError, sqlite3.Error):
        return json_response({"error": "확정 그림체를 저장하지 못했습니다."}, 500)


@app.route("/api/confirmed-styles/delete-batch", methods=["POST"])
def api_delete_confirmed_styles_batch():
    payload = request.get_json(silent=True)
    style_ids = payload.get("style_ids") if isinstance(payload, dict) else None
    if not isinstance(style_ids, list) or not style_ids or len(style_ids) > 500 or any(type(value) is not int or value < 1 for value in style_ids):
        return json_response({"error": "style_ids must contain up to 500 positive integers."}, 400)
    deleted_ids = [style_id for style_id in dict.fromkeys(style_ids) if delete_confirmed_style(DB_PATH, CONFIRMED_STYLE_IMAGE_DIR, style_id)]
    return json_response({"deleted_ids": deleted_ids})


@app.route("/api/confirmed-styles/import-batch", methods=["POST"])
def api_import_confirmed_styles_batch():
    uploads = request.files.getlist("images")
    try:
        manifest = json.loads(request.form.get("manifest") or "[]")
        if not uploads or len(uploads) > 500:
            raise ValueError("이미지는 한 번에 1장부터 500장까지 가져올 수 있습니다.")
        if not isinstance(manifest, list) or not manifest or len(manifest) > 500:
            raise ValueError("그림체 묶음 정보를 확인해 주세요.")
        image_bytes = [upload.stream.read(MAX_CONFIRMED_IMAGE_BYTES + 1) for upload in uploads]
        used_indexes = set()
        normalized_groups = []
        for group in manifest:
            if not isinstance(group, dict) or not isinstance(group.get("file_indexes"), list):
                raise ValueError("그림체 묶음 정보를 확인해 주세요.")
            indexes = group["file_indexes"]
            if (
                not indexes
                or any(type(index) is not int or index < 0 or index >= len(uploads) for index in indexes)
                or len(set(indexes)) != len(indexes)
                or used_indexes.intersection(indexes)
            ):
                raise ValueError("그림체 이미지 순서를 확인해 주세요.")
            data = group.get("data") or {}
            if not isinstance(data, dict):
                raise ValueError("그림체 입력값을 확인해 주세요.")
            used_indexes.update(indexes)
            normalized_groups.append((indexes, data))
        if used_indexes != set(range(len(uploads))):
            raise ValueError("저장되지 않은 이미지가 있습니다.")

        created = []
        try:
            for indexes, supplied in normalized_groups:
                first = indexes[0]
                extracted = _confirmed_metadata_from_bytes(
                    image_bytes[first], uploads[first].mimetype or ""
                )
                payload = {
                    **extracted,
                    **supplied,
                    "source_type": "manual",
                    "source_id": None,
                }
                item = create_confirmed_style_group(
                    DB_PATH,
                    CONFIRMED_STYLE_IMAGE_DIR,
                    [image_bytes[index] for index in indexes],
                    payload,
                )
                created.append(item)
        except Exception:
            for item in created:
                delete_confirmed_style(DB_PATH, CONFIRMED_STYLE_IMAGE_DIR, item["id"])
            raise
        return json_response([_add_confirmed_url(item) for item in created], 201)
    except (ValueError, json.JSONDecodeError) as exc:
        return json_response({"error": str(exc)}, 400)
    except (OSError, sqlite3.Error):
        return json_response({"error": "그림체 묶음을 저장하지 못했습니다."}, 500)


@app.route("/api/confirmed-styles/<int:style_id>", methods=["GET", "PATCH", "DELETE"])
def api_confirmed_style_detail(style_id):
    if request.method == "DELETE":
        if not delete_confirmed_style(DB_PATH, CONFIRMED_STYLE_IMAGE_DIR, style_id):
            return json_response({"error": "확정 그림체를 찾을 수 없습니다."}, 404)
        return json_response({"deleted": True, "id": style_id})
    if request.method == "PATCH":
        try:
            updated = update_confirmed_style(DB_PATH, style_id, request.get_json(silent=True))
        except ValueError as exc:
            return json_response({"error": str(exc)}, 400)
        if updated is None:
            return json_response({"error": "확정 그림체를 찾을 수 없습니다."}, 404)
        return json_response(_add_confirmed_url(updated))
    item = get_confirmed_style(DB_PATH, style_id)
    if item is None:
        return json_response({"error": "확정 그림체를 찾을 수 없습니다."}, 404)
    return json_response(_add_confirmed_url(item))


def _comparison_model(value, fallback):
    text = str(value or "").strip()
    if not text:
        return fallback
    return normalize_model_id(text)


def _comparison_generation_data(group, style):
    defaults = group.get("defaults") or {}
    def value(key, fallback): return style.get(key) if style.get(key) not in (None, "") else defaults.get(key, fallback)
    base_prompt = ", ".join(part for part in [style.get("quality_prompt"), style.get("fixed_prompt"), group.get("fixed_prompt")] if part)
    model = _comparison_model(style.get("model"), _comparison_model(defaults.get("model"), MODEL))
    complexity = (
        style["complexity"]
        if "complexity" in style and style.get("complexity") is not None
        else defaults.get("complexity", "")
    )
    return {
        "base_prompt": base_prompt, "quality_prompt": style.get("quality_prompt") or "",
        "original_quality_prompt": style.get("original_quality_prompt") or style.get("quality_prompt") or "",
        "fixed_prompt": group.get("fixed_prompt") or "", "excluded_quality_tags": [],
        "negative_prompt": style.get("negative_prompt") or "", "character_prompts": group.get("character_prompts") or [],
        "width": group["width"], "height": group["height"], "sampler": value("sampler", "k_euler_ancestral"),
        "noise_schedule": value("noise_schedule", "karras"), "steps": value("steps", 28),
        "scale": value("scale", 5.0), "cfg_rescale": value("cfg_rescale", 0.0),
        "variety_plus": value("variety_plus", False), "complexity": complexity,
        "quality_toggle": value("quality_toggle", False), "uc_preset": value("uc_preset", 0),
        "model": model,
    }, model


def _comparison_result_url(result):
    item = dict(result)
    item["image_url"] = f'/comparison-images/{item["image_path"]}'
    return item


def _generate_comparison_style(group, style_id):
    style = get_confirmed_style(DB_PATH, style_id)
    if not style:
        raise ValueError("확정 그림체를 찾을 수 없습니다.")
    try:
        key = load_app_key(SETTINGS_JSON_PATH, DATA_DIR)
    except SettingsError:
        raise ValueError("설정 파일이 올바르지 않습니다.") from None
    if not key:
        raise ValueError("NovelAI App Key가 설정되어 있지 않습니다.")
    data, model = _comparison_generation_data(group, style)
    common_seed = group.get("seed")
    if group["seed_mode"] == "none":
        data["seed"] = style.get("seed") or random.SystemRandom().randint(1, 4294967295)
    elif common_seed:
        data["seed"] = common_seed
    else:
        data["seed"] = random.SystemRandom().randint(1, 4294967295)
    try:
        png, actual_seed = generate_novelai_png(
            key, data, style.get("artist_prompt") or "", model=model
        )
    except NovelAIError as exc:
        style_name = style.get("name") or f"확정 그림체 #{style_id}"
        settings = f"{model}, {data['sampler']} / {data['noise_schedule']}, {data['steps']} steps, {data['width']}×{data['height']}"
        raise NovelAIError(
            exc.status_code,
            f"{style_name} 생성 실패 ({settings}) · {exc.public_message}",
        ) from None
    if group["seed_mode"] == "first" and common_seed is None:
        set_group_seed(DB_PATH, group["id"], actual_seed)
    snapshot = {
        **data,
        "seed": actual_seed,
        "model": model,
        "artist_prompt": style.get("artist_prompt") or "",
        "quality_prompt": style.get("quality_prompt") or "",
        "style_fixed_prompt": style.get("fixed_prompt") or "",
        "comparison_fixed_prompt": group.get("fixed_prompt") or "",
        "style_name": style.get("name") or f"확정 그림체 #{style_id}",
    }
    save_result(
        DB_PATH,
        COMPARISON_IMAGE_DIR,
        group["id"],
        style_id,
        snapshot["style_name"],
        png,
        snapshot,
    )
    refreshed = get_group(DB_PATH, group["id"])
    result = next(
        item for item in refreshed["results"] if item.get("confirmed_style_id") == style_id
    )
    return _comparison_result_url(result)


@app.route("/api/comparisons", methods=["GET", "POST"])
def api_comparisons():
    if request.method == "GET":
        groups = list_groups(DB_PATH)
        for group in groups:
            group["results"] = [_comparison_result_url(result) for result in group["results"]]
        return json_response(groups)
    payload = request.get_json(silent=True) or {}
    style_ids = payload.get("style_ids")
    editing_group = type(payload.get("group_id")) is int
    if not isinstance(style_ids, list) or any(type(value) is not int or value < 1 for value in style_ids) or (not editing_group and not style_ids):
        return json_response({"error": "확정 그림체 선택을 확인해 주세요."}, 400)
    try:
        group_id = payload.get("group_id")
        if editing_group:
            group = get_group(DB_PATH, group_id)
            if group is None: raise ValueError("비교군을 찾을 수 없습니다.")
            update_group_style_ids(DB_PATH, group_id, style_ids)
            remove_group_results(DB_PATH, COMPARISON_IMAGE_DIR, group_id, style_ids)
        else:
            group_id = create_group(DB_PATH, payload)
        group = get_group(DB_PATH, group_id)
        existing_style_ids = {result.get("confirmed_style_id") for result in group.get("results", [])}
        pending_style_ids = [style_id for style_id in dict.fromkeys(style_ids) if style_id not in existing_style_ids]
        if payload.get("defer_generation") is True:
            return json_response({
                "id": group_id,
                "pending_style_ids": pending_style_ids,
                "generated_count": len(existing_style_ids),
                "total_count": len(style_ids),
            }, 200 if editing_group else 201)
        for style_id in pending_style_ids:
            group = get_group(DB_PATH, group_id)
            _generate_comparison_style(group, style_id)
        return json_response({"id": group_id}, 200 if editing_group else 201)
    except (ValueError, NovelAIError) as exc:
        return json_response({"error": getattr(exc, "public_message", str(exc))}, getattr(exc, "status_code", 400))


@app.route("/api/comparisons/<int:group_id>/styles/<int:style_id>/generate", methods=["POST"])
def api_generate_comparison_style(group_id, style_id):
    group = get_group(DB_PATH, group_id)
    if group is None:
        return json_response({"error": "비교군을 찾을 수 없습니다."}, 404)
    if style_id not in group.get("selected_style_ids", []):
        return json_response({"error": "이 비교군에 선택되지 않은 확정 그림체입니다."}, 400)
    try:
        return json_response(_generate_comparison_style(group, style_id), 201)
    except (ValueError, NovelAIError) as exc:
        return json_response({"error": getattr(exc, "public_message", str(exc))}, getattr(exc, "status_code", 400))


@app.route("/api/comparison-results/<int:result_id>", methods=["DELETE"])
def api_delete_comparison_result(result_id):
    if not delete_result(DB_PATH, COMPARISON_IMAGE_DIR, result_id): return json_response({"error": "결과를 찾을 수 없습니다."}, 404)
    return json_response({"deleted": True})


@app.route("/api/comparisons/<int:group_id>", methods=["DELETE"])
def api_delete_comparison_group(group_id):
    if not delete_group(DB_PATH, COMPARISON_IMAGE_DIR, group_id):
        return json_response({"error": "비교군을 찾을 수 없습니다."}, 404)
    return json_response({"deleted": True, "id": group_id})


@app.route("/api/arca-styles/collect", methods=["POST"])
def api_collect_arca_styles():
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ArcaCollectorError("요청 데이터가 올바르지 않습니다.")
        job_id = start_collection_job(DB_PATH, ARCA_STYLE_IMAGE_DIR, payload)
        return json_response({"job_id": job_id, "status": "queued"}, 202)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)
    except requests.RequestException:
        app.logger.exception("Arca collection request failed")
        return json_response({"error": "수집 대상에 연결하지 못했습니다."}, 502)
    except Exception:
        app.logger.exception("Unexpected Arca collection failure")
        return json_response({"error": "수집 중 오류가 발생했습니다."}, 500)


@app.route("/api/arca-styles/restore-images", methods=["POST"])
def api_restore_arca_style_images():
    try:
        job_id = start_image_restore_job(DB_PATH, ARCA_STYLE_IMAGE_DIR)
        return json_response({"job_id": job_id, "status": "queued"}, 202)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/restore-images/prepare", methods=["POST"])
def api_prepare_arca_style_images():
    return json_response(get_image_restore_estimate(DB_PATH, ARCA_STYLE_IMAGE_DIR))


@app.route("/api/arca-styles/restore-images/estimate")
def api_arca_style_image_restore_estimate():
    return json_response(get_image_restore_estimate(DB_PATH, ARCA_STYLE_IMAGE_DIR))


@app.route("/api/arca-styles/image-archive")
def api_arca_style_image_archive():
    return json_response({
        "filename": ARCHIVE_FILENAME,
        "bytes": ARCHIVE_BYTES,
        "image_count": ARCHIVE_IMAGE_COUNT,
        "sha256": ARCHIVE_SHA256,
    })


@app.route("/api/arca-styles/image-archive/google", methods=["POST"])
def api_download_arca_style_image_archive():
    try:
        job_id = start_google_archive_job(DB_PATH, ARCA_STYLE_IMAGE_DIR, DATA_DIR, ARCA_STYLE_SEED_PATH)
        return json_response({"job_id": job_id, "status": "queued"}, 202)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/image-archive/upload/start", methods=["POST"])
def api_start_arca_style_image_archive_upload():
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ArcaCollectorError("로컬 ZIP 정보를 확인해 주세요.")
        return json_response(start_local_upload(DATA_DIR, payload.get("name"), payload.get("size")))
    except (ArcaCollectorError, TypeError, ValueError) as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/image-archive/upload/<upload_id>", methods=["PUT"])
def api_append_arca_style_image_archive_upload(upload_id):
    try:
        offset = int(request.args.get("offset", ""))
        result = append_local_upload(
            upload_id,
            offset,
            request.stream,
            request.content_length,
        )
        return json_response(result)
    except (ArcaCollectorError, TypeError, ValueError) as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/image-archive/upload/<upload_id>", methods=["DELETE"])
def api_discard_arca_style_image_archive_upload(upload_id):
    discard_local_upload(upload_id)
    return json_response({"discarded": True})


@app.route("/api/arca-styles/image-archive/upload/<upload_id>/finish", methods=["POST"])
def api_finish_arca_style_image_archive_upload(upload_id):
    try:
        job_id = finish_local_upload(
            DB_PATH, ARCA_STYLE_IMAGE_DIR, DATA_DIR, ARCA_STYLE_SEED_PATH, upload_id,
        )
        return json_response({"job_id": job_id, "status": "queued"}, 202)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/collection-jobs/<int:job_id>")
def api_arca_collection_job(job_id):
    job = get_collection_job(DB_PATH, job_id)
    if job is None:
        return json_response({"error": "수집 작업을 찾을 수 없습니다."}, 404)
    return json_response(job)


@app.route("/api/arca-styles/collection-jobs/current")
def api_current_arca_collection_job():
    return json_response(get_latest_resumable_collection_job(DB_PATH) or {})


@app.route("/api/arca-styles/collection-jobs/<int:job_id>/<action>", methods=["POST"])
def api_control_arca_collection_job(job_id, action):
    try:
        if action == "pause":
            return json_response(pause_collection_job(DB_PATH, job_id))
        if action == "resume":
            resumed_job_id = resume_collection_job(
                DB_PATH, ARCA_STYLE_IMAGE_DIR, job_id, ARCA_STYLE_SEED_PATH,
            )
            return json_response({"job_id": resumed_job_id, "status": "running"})
        if action == "stop":
            return json_response(stop_collection_job(DB_PATH, job_id))
        return json_response({"error": "지원하지 않는 수집 제어입니다."}, 404)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/collect-url", methods=["POST"])
def api_collect_arca_style_url():
    try:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ArcaCollectorError("요청 데이터가 올바르지 않습니다.")
        source_url = normalize_arca_article_url(payload.get("source_url"))
        job_id = start_url_collection_job(DB_PATH, ARCA_STYLE_IMAGE_DIR, source_url)
        return json_response({"job_id": job_id, "status": "queued"}, 202)
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


def _safe_arca_browser_status(status, login_status=None):
    connected = bool(status.get("connected"))
    if connected:
        browser = str(status.get("browser") or "")
        return {
            "connected": True, "browser": browser, "error": "",
            "state": "connected", "message": f"{browser or '브라우저'} 로그인 연결됨",
        }
    login_status = login_status or ARCA_LOGIN_MANAGER.status()
    return {
        "connected": bool(login_status.get("connected")),
        "browser": str(login_status.get("browser") or ""),
        "error": str(login_status.get("error") or ""),
        "state": str(login_status.get("state") or "idle"),
        "message": str(login_status.get("message") or "브라우저 로그인 연결 안 됨"),
    }


@app.route("/api/arca-styles/browser-session", methods=["GET"])
def api_arca_browser_session_status():
    return json_response(_safe_arca_browser_status(get_arca_browser_session_status()))


@app.route("/api/arca-styles/browser-session/import", methods=["POST"])
def api_import_arca_browser_session():
    imported = import_arca_browser_session()
    if imported.get("connected"):
        return json_response(_safe_arca_browser_status(imported), 200)
    return json_response(_safe_arca_browser_status(imported, ARCA_LOGIN_MANAGER.start()), 202)


@app.route("/api/arca-styles/browser-session/extension", methods=["POST"])
def api_connect_arca_browser_extension():
    if request.headers.get("X-Arca-Session-Bridge") != "1":
        return json_response({"error": "Chrome 브리지 요청을 확인할 수 없습니다."}, 403)
    try:
        cookie_jar = extension_payload_to_cookie_jar(request.get_json(silent=True))
    except ArcaChromeExtensionError as exc:
        return json_response({"error": str(exc)}, 400)
    connected = connect_arca_cookie_jar(cookie_jar, "현재 Chrome")
    if connected.get("connected"):
        return json_response(_safe_arca_browser_status(connected))
    error = str(connected.get("error") or "아카라이브 로그인을 확인하지 못했습니다.")
    return json_response({
        "connected": False,
        "browser": "",
        "error": error,
        "state": "failed",
        "message": error,
    }, 401)


@app.route("/api/arca-styles/browser-session/extension/setup", methods=["POST"])
def api_setup_arca_browser_extension():
    if request.mimetype != "application/json":
        return json_response({"error": "JSON 요청이 필요합니다."}, 415)
    try:
        path = install_arca_session_bridge(DATA_DIR, source_dir=ARCA_SESSION_BRIDGE_SOURCE_DIR)
        return json_response({"ok": True, "path": str(path)})
    except (ArcaChromeExtensionError, OSError):
        return json_response({"error": "Chrome 연동 확장 폴더를 준비하지 못했습니다."}, 500)


@app.route("/api/arca-styles", methods=["GET"])
def api_arca_styles():
    filters = {
        key: request.args.get(key)
        for key in ("q", "tab", "metadata", "start_date", "end_date", "sort", "page", "per_page", "recommendation_min", "model")
        if request.args.get(key) is not None
    }
    try:
        result = get_arca_style_page(DB_PATH, filters)
        result["items"] = [_add_arca_urls(item) for item in result["items"]]
        return json_response(result)
    except (ValueError, ArcaCollectorError) as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/statistics", methods=["GET"])
def api_arca_style_statistics():
    filters = {
        key: request.args.get(key)
        for key in ("recommendation_min", "recommendation_max", "model")
        if request.args.get(key) not in (None, "")
    }
    try:
        return json_response(_add_arca_urls(get_arca_style_statistics(DB_PATH, filters)))
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/statistics/tag", methods=["GET"])
def api_arca_tag_statistics():
    try:
        filters = {
            key: request.args.get(key)
            for key in ("recommendation_min", "recommendation_max", "model")
            if request.args.get(key) not in (None, "")
        }
        result = get_arca_tag_statistics(
            DB_PATH,
            request.args.get("kind"),
            request.args.get("tag"),
            request.args.get("limit", 24),
            filters,
        )
        return json_response(_add_arca_urls(result))
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/statistics/sequence", methods=["GET"])
def api_arca_quality_sequence_statistics():
    try:
        filters = {
            key: request.args.get(key)
            for key in ("recommendation_min", "recommendation_max", "model")
            if request.args.get(key) not in (None, "")
        }
        result = get_arca_quality_sequence_statistics(
            DB_PATH,
            request.args.getlist("tag"),
            request.args.get("limit", 40),
            filters,
        )
        return json_response(_add_arca_urls(result))
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/search-status", methods=["GET"])
def api_arca_search_status():
    try:
        params = normalize_collect_payload(request.args.to_dict(flat=True) | {"tabs": request.args.getlist("tabs") or ["NAI", "R18_NAI"]})
        coverage = get_completed_coverage(DB_PATH, params)
        return json_response({"coverage": [{"start_date": start.isoformat(), "end_date": end.isoformat()} for start, end in coverage]})
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/api/arca-styles/<int:item_id>", methods=["GET", "PATCH", "DELETE"])
def api_arca_style_detail(item_id):
    try:
        if request.method == "PATCH":
            item = update_arca_style(DB_PATH, item_id, request.get_json(silent=True))
        elif request.method == "DELETE":
            result = delete_arca_style(DB_PATH, ARCA_STYLE_IMAGE_DIR, item_id)
            if not result:
                return json_response({"error": "수집 항목을 찾을 수 없습니다."}, 404)
            return json_response(result)
        else:
            model_filter = request.args.get("model")
            item = (
                get_arca_style_detail(DB_PATH, item_id, {"model": model_filter})
                if model_filter not in (None, "")
                else get_arca_style_detail(DB_PATH, item_id)
            )
        if item is None:
            return json_response({"error": "수집 항목을 찾을 수 없습니다."}, 404)
        return json_response(_add_arca_urls(item))
    except ArcaCollectorError as exc:
        return json_response({"error": str(exc)}, 400)


@app.route("/arca-style-images/<path:filename>")
def arca_style_image(filename):
    normalized = filename.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or normalized != filename:
        return json_response({"error": "Invalid archive image path."}, 400)
    target, root = (ARCA_STYLE_IMAGE_DIR / path).resolve(), ARCA_STYLE_IMAGE_DIR.resolve()
    if root not in target.parents:
        return json_response({"error": "Invalid archive image path."}, 400)
    return send_from_directory(root, path.as_posix())


@app.route("/generated/<path:filename>")
def generated(filename):
    normalized = filename.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or normalized != filename:
        return json_response({"error": "Invalid generated image path."}, 400)
    target = (GENERATED_DIR / path).resolve()
    root = GENERATED_DIR.resolve()
    if root not in target.parents:
        return json_response({"error": "Invalid generated image path."}, 400)
    return send_from_directory(root, path.as_posix())


@app.route("/confirmed-style-images/<path:filename>")
def confirmed_style_image(filename):
    normalized = filename.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or normalized != filename:
        return json_response({"error": "Invalid confirmed image path."}, 400)
    target = (CONFIRMED_STYLE_IMAGE_DIR / path).resolve()
    root = CONFIRMED_STYLE_IMAGE_DIR.resolve()
    if target.parent != root:
        return json_response({"error": "Invalid confirmed image path."}, 400)
    return send_from_directory(root, path.as_posix())


@app.route("/style-manager-thumbnails/<source>/<path:filename>")
def style_manager_thumbnail(source, filename):
    roots = {
        "generated": GENERATED_DIR,
        "confirmed": CONFIRMED_STYLE_IMAGE_DIR,
        "shared": ARCA_STYLE_IMAGE_DIR,
    }
    root = roots.get(source)
    normalized = filename.replace("\\", "/")
    path = Path(normalized)
    if root is None or path.is_absolute() or ".." in path.parts or normalized != filename:
        return json_response({"error": "Invalid style manager thumbnail path."}, 400)
    resolved_root = root.resolve()
    target = (resolved_root / path).resolve()
    if resolved_root not in target.parents or not target.is_file():
        return json_response({"error": "Style manager image not found."}, 404)

    stat = target.stat()
    cache_key = hashlib.sha256(
        f"{source}\0{path.as_posix()}\0{stat.st_mtime_ns}\0{stat.st_size}".encode("utf-8")
    ).hexdigest()
    cache_root = DATA_DIR / "style_manager_thumbnails"
    cache_root.mkdir(parents=True, exist_ok=True)
    cached = cache_root / f"{cache_key}.webp"
    if not cached.is_file():
        temporary = cache_root / f"{cache_key}.{os.getpid()}.{random.getrandbits(64):016x}.tmp"
        try:
            with Image.open(target) as opened:
                image = ImageOps.exif_transpose(opened)
                image.thumbnail((384, 384), Image.Resampling.LANCZOS)
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                image.save(temporary, format="WEBP", quality=82, method=2)
            try:
                temporary.replace(cached)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        except (OSError, ValueError, Image.DecompressionBombError):
            temporary.unlink(missing_ok=True)
            return send_from_directory(resolved_root, path.as_posix())
    response = send_from_directory(cache_root, cached.name, max_age=31536000)
    response.mimetype = "image/webp"
    return response


@app.route("/comparison-images/<path:filename>")
def comparison_image(filename):
    path = Path(filename)
    if path.is_absolute() or ".." in path.parts: return json_response({"error": "Invalid comparison image path."}, 400)
    return send_from_directory(COMPARISON_IMAGE_DIR, path.as_posix())


@app.route("/api/ratings/<int:rating_id>", methods=["PATCH"])
def api_update_rating(rating_id):
    payload = request.get_json(silent=True) or {}
    allowed = []
    params = []
    if "score" in payload:
        score = int(payload["score"])
        if score < 1 or score > 5:
            return json_response({"ok": False, "error": "score는 1~5여야 합니다."}, 400)
        allowed.append("score = ?")
        params.append(score)
    for key in ("memo",):
        if key in payload:
            allowed.append(f"{key} = ?")
            params.append(payload[key])
    if "query_text" in payload:
        if not isinstance(payload["query_text"], str):
            return json_response({"ok": False, "error": "쿼리 프롬프트는 문자열이어야 합니다."}, 400)
        query_text = payload["query_text"].strip()
        allowed.extend(("query_text = ?", "query_tags_json = ?"))
        params.extend((query_text, json.dumps(normalize_query_text(query_text), ensure_ascii=False)))
    if not allowed:
        return json_response({"ok": False, "error": "수정할 값이 없습니다."}, 400)
    allowed.append("updated_at = ?")
    params.append(now_text())
    params.append(rating_id)
    with db() as conn:
        cursor = conn.execute(f"UPDATE ratings SET {', '.join(allowed)} WHERE id = ?", params)
    if cursor.rowcount == 0:
        return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
    return json_response({"ok": True})


@app.route("/api/ratings/<int:rating_id>/thumbnail", methods=["POST"])
def api_find_rating_thumbnail(rating_id):
    with db() as conn:
        row = conn.execute(
            "SELECT artist_tag,query_tags_json FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
    if not row:
        return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
    try:
        query_tags = json.loads(row["query_tags_json"] or "[]")
    except json.JSONDecodeError:
        query_tags = []
    try:
        samples = fetch_artist_samples(row["artist_tag"], query_tags, 1)
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)
    if not samples:
        return json_response({"ok": False, "error": "Danbooru에서 썸네일을 찾지 못했습니다."}, 404)
    sample = samples[0]
    preview_url = sample.get("large_url") or sample.get("preview_url") or ""
    thumbnail = download_thumbnail(preview_url, row["artist_tag"], sample.get("id"))
    if not thumbnail:
        return json_response({"ok": False, "error": "썸네일 저장에 실패했습니다."}, 502)
    with db() as conn:
        conn.execute(
            "UPDATE ratings SET representative_post_id=?,representative_thumbnail_path=?,representative_preview_url=?,sample_post_ids_json=?,updated_at=? WHERE id=?",
            (sample.get("id"), thumbnail, preview_url, json.dumps([sample.get("id")]), now_text(), rating_id),
        )
    return json_response({"ok": True, "thumbnail_url": f"/thumbnails/{thumbnail}"})


@app.route("/api/ratings/<int:rating_id>/examples", methods=["GET"])
def api_list_rating_examples(rating_id):
    payload = rating_examples_payload(rating_id)
    if payload is None:
        return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
    return json_response(payload)


@app.route("/api/ratings/<int:rating_id>/examples/collect", methods=["POST"])
def api_collect_rating_examples(rating_id):
    with db() as conn:
        rating = conn.execute(
            "SELECT artist_tag,query_tags_json,representative_post_id FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
        if not rating:
            return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
        stored_ids = {
            str(row[0])
            for row in conn.execute(
                "SELECT post_id FROM rating_examples WHERE rating_id = ?",
                (rating_id,),
            ).fetchall()
            if row[0] is not None
        }
    try:
        query_tags = json.loads(rating["query_tags_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        query_tags = []
    if not isinstance(query_tags, list):
        query_tags = []
    request_payload = request.get_json(silent=True)
    if not isinstance(request_payload, dict):
        request_payload = {}
    try:
        sample_limit = max(1, min(int(request_payload.get("sample_limit") or 10), 30))
    except (TypeError, ValueError):
        sample_limit = 10
    try:
        samples = fetch_artist_samples(rating["artist_tag"], query_tags, sample_limit)
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)

    stored_count = 0
    for sample in samples or []:
        post_id = sample.get("id") if isinstance(sample, dict) else None
        if post_id is None or str(post_id) == str(rating["representative_post_id"] or "") or str(post_id) in stored_ids:
            continue
        source_url = str(sample.get("large_url") or sample.get("preview_url") or "").strip()
        if not source_url:
            continue
        filename = thumbnail_filename(rating["artist_tag"], post_id)
        existing_path = safe_thumbnail_path(filename)
        if existing_path and existing_path.exists():
            continue
        image_path = download_thumbnail(source_url, rating["artist_tag"], post_id)
        if not image_path:
            continue
        post_url = str(sample.get("post_url") or "").strip()
        if not post_url and str(post_id).isdigit():
            post_url = f"{DANBOORU_BASE_URL}/posts/{post_id}"
        try:
            with db() as conn:
                conn.execute(
                    "INSERT INTO rating_examples (rating_id,post_id,image_path,source_url,post_url,created_at) VALUES (?,?,?,?,?,?)",
                    (
                        rating_id,
                        post_id,
                        image_path,
                        source_url,
                        post_url,
                        now_text(),
                    ),
                )
        except sqlite3.IntegrityError:
            remove_unreferenced_thumbnail_paths([image_path])
            continue
        stored_ids.add(str(post_id))
        stored_count += 1

    payload = rating_examples_payload(rating_id)
    payload["saved_count"] = stored_count
    return json_response(payload)


@app.route("/api/ratings/<int:rating_id>/examples/<int:example_id>/thumbnail", methods=["POST"])
def api_set_rating_example_thumbnail(rating_id, example_id):
    with db() as conn:
        row = conn.execute(
            """
            SELECT e.id,e.post_id,e.image_path,e.source_url
            FROM rating_examples e
            JOIN ratings r ON r.id = e.rating_id
            WHERE e.rating_id = ? AND e.id = ?
            """,
            (rating_id, example_id),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "예제를 찾을 수 없습니다."}, 404)
        example_ids = [
            item[0]
            for item in conn.execute(
                "SELECT post_id FROM rating_examples WHERE rating_id = ? ORDER BY id",
                (rating_id,),
            ).fetchall()
            if item[0] is not None
        ]
        conn.execute(
            "UPDATE ratings SET representative_post_id=?,representative_thumbnail_path=?,representative_preview_url=?,sample_post_ids_json=?,updated_at=? WHERE id=?",
            (
                row["post_id"],
                row["image_path"],
                row["source_url"] or "",
                json.dumps(example_ids, ensure_ascii=False),
                now_text(),
                rating_id,
            ),
        )
    payload = rating_examples_payload(rating_id)
    return json_response(payload)


@app.route("/api/ratings/<int:rating_id>/examples/<int:example_id>", methods=["DELETE"])
def api_delete_rating_example(rating_id, example_id):
    with db() as conn:
        rating = conn.execute(
            "SELECT representative_post_id,representative_thumbnail_path,sample_post_ids_json FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
        row = conn.execute(
            "SELECT id,post_id,image_path FROM rating_examples WHERE rating_id = ? AND id = ?",
            (rating_id, example_id),
        ).fetchone()
        if not rating or not row:
            return json_response({"ok": False, "error": "예제를 찾을 수 없습니다."}, 404)
        is_current = bool(
            rating["representative_thumbnail_path"]
            and rating["representative_thumbnail_path"] == row["image_path"]
        )
        if is_current:
            conn.execute(
                "UPDATE ratings SET representative_post_id=NULL,representative_thumbnail_path='',representative_preview_url='',sample_post_ids_json='[]',updated_at=? WHERE id=?",
                (now_text(), rating_id),
            )
        else:
            try:
                sample_ids = json.loads(rating["sample_post_ids_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                sample_ids = []
            sample_ids = [item for item in sample_ids if str(item) != str(row["post_id"])]
            conn.execute(
                "UPDATE ratings SET sample_post_ids_json=?,updated_at=? WHERE id=?",
                (json.dumps(sample_ids, ensure_ascii=False), now_text(), rating_id),
            )
        conn.execute(
            "DELETE FROM rating_examples WHERE rating_id = ? AND id = ?",
            (rating_id, example_id),
        )
    remove_unreferenced_thumbnail_paths([row["image_path"]])
    payload = rating_examples_payload(rating_id)
    payload["deleted_example_id"] = example_id
    return json_response(payload)


@app.route("/api/ratings/<int:rating_id>", methods=["DELETE"])
def api_delete_rating(rating_id):
    with db() as conn:
        row = conn.execute(
            "SELECT representative_thumbnail_path FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
        example_paths = [
            item[0]
            for item in conn.execute(
                "SELECT image_path FROM rating_examples WHERE rating_id = ?",
                (rating_id,),
            ).fetchall()
        ]
        conn.execute("DELETE FROM rating_examples WHERE rating_id = ?", (rating_id,))
        conn.execute("DELETE FROM ratings WHERE id = ?", (rating_id,))
    remove_unreferenced_thumbnail_paths([row["representative_thumbnail_path"], *example_paths])
    return json_response({"ok": True})


@app.route("/thumbnails/<path:filename>")
def thumbnails(filename):
    safe_name = Path(filename).name
    if safe_name != filename:
        return json_response({"ok": False, "error": "잘못된 파일 경로입니다."}, 400)
    return send_from_directory(THUMBNAIL_DIR, safe_name)


if __name__ == "__main__":
    init_db()
    print("Danbooru Artist Rater")
    print("Open http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)
