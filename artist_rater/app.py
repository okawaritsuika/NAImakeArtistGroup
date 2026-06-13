import json
import math
import os
import random
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
GENERATED_DIR = DATA_DIR / "generated"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "artist_rater.sqlite"
DANBOORU_BASE_URL = "https://danbooru.donmai.us"
CUTOFF = datetime(2025, 1, 31, 23, 59, 59, tzinfo=timezone.utc)
DATE_TAG = "date:<=2025-01-31"
REQUEST_TIMEOUT = 12
USER_AGENT = "DanbooruArtistRater/1.0 (local personal tool)"

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


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
                steps INTEGER NOT NULL,
                scale REAL NOT NULL,
                cfg_rescale REAL NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(style_id) REFERENCES art_styles(id)
            )
            """
        )

    from style_store import reconcile_generated_storage

    reconcile_generated_storage(DB_PATH, GENERATED_DIR)


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
    print("Open http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
