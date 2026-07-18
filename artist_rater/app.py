import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

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
    get_arca_style_page,
    get_arca_style_statistics,
    get_arca_tag_statistics,
    get_arca_quality_sequence_statistics,
    get_style_maker_prompt_presets,
    get_shared_style_artist_pool,
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
    update_arca_style,
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
    generate_novelai_png,
    normalize_generation_data,
    test_novelai_subscription,
)
from style_store import (
    SettingsError,
    delete_app_key,
    delete_style,
    get_style_detail,
    list_styles,
    load_app_key,
    release_generation_request,
    reserve_generation_request,
    save_app_key,
    save_generated_result,
)

from style_logic import (
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
ARCA_STYLE_IMAGE_DIR = DATA_DIR / "arca_style_images"
ARCA_STYLE_SEED_PATH = RESOURCE_DIR / "arca_style_seed.sqlite"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "artist_rater.sqlite"
ARCA_SESSION_BRIDGE_SOURCE_DIR = RESOURCE_DIR / "static" / "arca_session_bridge"
DANBOORU_BASE_URL = "https://danbooru.donmai.us"
CUTOFF = datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
DATE_TAG = "date:<=2025-01-31"
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

    from style_store import reconcile_generated_storage

    reconcile_generated_storage(DB_PATH, GENERATED_DIR)
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


def parse_cutoff_date(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_before_cutoff(post):
    created = parse_cutoff_date(post.get("created_at"))
    return bool(created and created <= CUTOFF)


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


def search_posts(tags, fetch_pages=1, limit=100):
    pages = max(1, min(int(fetch_pages or 1), 10))
    limit = max(1, min(int(limit or 100), 100))
    query = " ".join([tag for tag in tags if tag] + [DATE_TAG])
    posts = []
    for page in range(1, pages + 1):
        data = danbooru_get("/posts.json", {"tags": query, "limit": limit, "page": page})
        if not isinstance(data, list):
            break
        filtered = [post for post in data if isinstance(post, dict) and is_before_cutoff(post)]
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


def safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "artist").strip("._")
    return value[:120] or "artist"


def download_thumbnail(url, artist_tag, post_id):
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"}:
        return ""
    filename = f"{safe_filename(artist_tag)}_{safe_filename(str(post_id or 'post'))}.jpg"
    target = THUMBNAIL_DIR / filename
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
    except requests.RequestException:
        return ""
    return filename


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


def fetch_artist_samples(artist_tag, query_tags, sample_limit):
    sample_limit = max(1, min(int(sample_limit or 12), 30))
    posts = []
    seen = set()
    for tags in ([artist_tag] + query_tags, [artist_tag]):
        try:
            for post in search_posts(tags, fetch_pages=3):
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


def global_artist_candidates(min_artist_post_count, pages_to_try):
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
    min_artist_post_count = int(payload.get("min_artist_post_count") or 1000)
    min_match_count = int(payload.get("min_match_count") or 3)
    fetch_pages = int(payload.get("fetch_pages") or 5)
    candidate_limit = int(payload.get("candidate_limit") or 12)
    random_mode = payload.get("random_mode") or "soft_weighted"
    random_mode = random_mode if random_mode in {"uniform", "weighted", "soft_weighted"} else "soft_weighted"
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
        "final_candidate_count": 0,
    }

    if not query_tags:
        mode = "global_random"
        raw_candidates = global_artist_candidates(min_artist_post_count, fetch_pages)
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
        posts = search_posts(query_tags, fetch_pages=fetch_pages)
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
            "filter_stats": filter_stats,
        }

    selected_pool = choose_candidate_pool(candidates, random_mode, candidate_limit)
    return {
        "ok": True,
        "mode": mode,
        "query_tags": query_tags,
        "candidate_count": len(candidates),
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
    samples = fetch_artist_samples(selected["artist_tag"], pool["query_tags"], sample_limit)
    if not samples:
        return {
            "ok": False,
            "reason": "선택된 작가의 표시 가능한 샘플 이미지를 찾지 못했습니다.",
            "mode": pool["mode"],
            "query_tags": pool["query_tags"],
        }

    return {
        "ok": True,
        "mode": pool["mode"],
        "query_tags": pool["query_tags"],
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
    try:
        samples = fetch_artist_samples(artist_tag, query_tags, sample_limit)
    except requests.RequestException as exc:
        return json_response({"ok": False, "error": f"Danbooru API 오류: {exc}"}, 502)
    if not samples:
        return json_response(
            {
                "ok": False,
                "reason": "선택된 작가의 표시 가능한 샘플 이미지를 찾지 못했습니다.",
                "artist": artist_tag,
                "query_tags": query_tags,
            }
        )
    return json_response(
        {
            "ok": True,
            "mode": payload.get("mode") or "tag_filtered_random",
            "query_tags": query_tags,
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

        if reroll == "weights":
            artists = current_artists
        else:
            scores = payload.get("scores", [1, 2, 3, 4, 5])
            if not isinstance(scores, list) or not scores:
                raise ValueError("선택할 평점을 하나 이상 지정하세요.")
            scores = [exact_score(score) for score in scores]
            with closing(db()) as conn:
                rows = conn.execute("SELECT artist_tag, score FROM ratings").fetchall()
            pool = [
                {"artist": row["artist_tag"], "score": row["score"]}
                for row in rows
            ]
            if reroll == "artists":
                current_names = {item["artist"] for item in current_artists}
                pool = [item for item in pool if item["artist"] not in current_names]
            target_count = len(current_artists) if reroll == "artists" else payload.get("count", 12)
            target_count = int(target_count)
            rng = random.Random(rng_seed)
            shared_pool = get_shared_style_artist_pool(DB_PATH) if shared_artist_max else []
            current_names = {item["artist"].replace("_", " ").casefold() for item in (current_artists or [])}
            shared_pool = [
                item for item in shared_pool
                if item["artist"].replace("_", " ").casefold() not in current_names
            ]
            unique_shared_pool = {}
            for item in shared_pool:
                normalized_name = item["artist"].replace("_", " ").casefold()
                unique_shared_pool.setdefault(normalized_name, item)
            shared_pool = list(unique_shared_pool.values())
            shared_limit = min(shared_artist_max, target_count, len(shared_pool))
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
                if len(rated_available) >= target_count - len(selected_shared):
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
            pool = [item for item in pool if item["artist"].replace("_", " ").casefold() not in shared_names]
            rated_artists = select_artists(
                pool,
                target_count - len(shared_artists),
                scores,
                rng_seed=rng_seed,
            ) if target_count > len(shared_artists) else []
            artists = rated_artists + shared_artists
            rng.shuffle(artists)

        if reroll == "artists":
            weighted = [
                item | {"weight": current_artists[index]["weight"]}
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
            )
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
        return json_response({"ok": True, **result})
    except ArcaCollectorError as exc:
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
    return json_response(
        {"ok": True, "configured": True, "anlas": result["anlas"]}
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
        if artist in seen:
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
        artists.append(normalized)
        seen.add(artist)

    return artists


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
    }
    return payload


def _validate_generation_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    request_id = payload.get("request_id")
    if type(request_id) is not str or not SAFE_REQUEST_ID.fullmatch(request_id):
        raise ValueError("request_id must be a nonempty safe string up to 128 characters.")
    normalized = normalize_generation_data(payload)
    normalized["request_id"] = request_id
    normalized["seed_provided"] = "seed" in payload
    normalized_artists = normalize_style_artists(payload.get("artists"))
    normalized["artists"] = normalized_artists
    return normalized


def _generation_payload_hash(data):
    canonical = {
        "artists": data["artists"],
        "base_prompt": data["base_prompt"],
        "negative_prompt": data["negative_prompt"],
        "character_prompts": data["character_prompts"],
        "width": data["width"],
        "height": data["height"],
        "sampler": data["sampler"],
        "noise_schedule": data["noise_schedule"],
        "steps": data["steps"],
        "scale": data["scale"],
        "cfg_rescale": data["cfg_rescale"],
        "seed": data["seed"] if data["seed_provided"] else None,
        "model": MODEL,
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
        combined_prompt = combine_base_prompt(data["base_prompt"], artist_prompt)
        png_bytes, actual_seed = generate_novelai_png(app_key, data, artist_prompt)
        result = save_generated_result(
            DB_PATH,
            GENERATED_DIR,
            request_id=request_id,
            artists=data["artists"],
            png_bytes=png_bytes,
            base_prompt=data["base_prompt"],
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
            model=MODEL,
        )
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


def _add_generated_urls(item):
    image_path = item.get("image_path") or ""
    if image_path:
        item["image_url"] = f"/generated/{image_path}"
    representative = item.get("representative_image_path") or ""
    if representative:
        item["representative_image_url"] = f"/generated/{representative}"
    return item


@app.route("/api/art-styles", methods=["GET"])
def api_art_styles():
    return json_response([_add_generated_urls(item) for item in list_styles(DB_PATH)])


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
        for key in ("q", "tab", "metadata", "start_date", "end_date", "sort", "page", "per_page", "recommendation_min")
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
        for key in ("recommendation_min", "recommendation_max")
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
            for key in ("recommendation_min", "recommendation_max")
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
            for key in ("recommendation_min", "recommendation_max")
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
            item = get_arca_style_detail(DB_PATH, item_id)
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
    preview_url = sample.get("preview_url") or sample.get("large_url") or ""
    thumbnail = download_thumbnail(preview_url, row["artist_tag"], sample.get("id"))
    if not thumbnail:
        return json_response({"ok": False, "error": "썸네일 저장에 실패했습니다."}, 502)
    with db() as conn:
        conn.execute(
            "UPDATE ratings SET representative_post_id=?,representative_thumbnail_path=?,representative_preview_url=?,sample_post_ids_json=?,updated_at=? WHERE id=?",
            (sample.get("id"), thumbnail, preview_url, json.dumps([sample.get("id")]), now_text(), rating_id),
        )
    return json_response({"ok": True, "thumbnail_url": f"/thumbnails/{thumbnail}"})


@app.route("/api/ratings/<int:rating_id>", methods=["DELETE"])
def api_delete_rating(rating_id):
    with db() as conn:
        row = conn.execute(
            "SELECT representative_thumbnail_path FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
        if not row:
            return json_response({"ok": False, "error": "평가를 찾을 수 없습니다."}, 404)
        conn.execute("DELETE FROM ratings WHERE id = ?", (rating_id,))
    filename = row["representative_thumbnail_path"]
    if filename:
        target = (THUMBNAIL_DIR / filename).resolve()
        if THUMBNAIL_DIR.resolve() in target.parents and target.exists():
            target.unlink()
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
