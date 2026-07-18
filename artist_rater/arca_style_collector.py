import hashlib
import copy
import gzip
import io
import json
import re
import sqlite3
import struct
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from itertools import combinations
from pathlib import Path
from statistics import median
from threading import Event, RLock, Thread
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ARCA_BASE_URL = "https://arca.live"
ARCA_BOARD_PATH = "/b/aiart"
DEFAULT_KEYWORD = "그림체 공유"
REQUEST_TIMEOUT = 12
IMAGE_TIMEOUT = 20
MAX_IMAGE_BYTES = 32 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
EDITABLE_LIMIT = 100_000
SEARCH_SCOPE = "title-category-session-v6"
MAX_ARCHIVE_SEARCH_PAGE = 4096
COLLECTION_WORKERS = 6
IMAGE_RESTORE_WORKERS = 16
DEFAULT_IMAGE_ESTIMATE_BYTES = 4 * 1024 * 1024
IMAGE_RESTORE_ESTIMATE_BYTES_PER_SECOND = 8 * 1024 * 1024
GENERATION_KEYS = {"seed", "sampler", "steps", "scale", "noise_schedule", "model", "width", "height"}
STYLE_SIMILARITY_THRESHOLD = 0.55
TRANSIENT_TAG = re.compile(r"^(?:\d+(?:girl|boy)s?|solo|multiple girls|portrait|upper body|full body|looking at.*|smile|open mouth|.*hair|.*eyes|robot)$", re.I)
NON_PNG_IMAGE_TYPES = {
    ".avif": "image/avif", ".bmp": "image/bmp", ".gif": "image/gif",
    ".ico": "image/x-icon", ".jfif": "image/jpeg", ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".tif": "image/tiff",
    ".tiff": "image/tiff", ".webp": "image/webp",
}


class ArcaCollectorError(Exception):
    pass


class ArcaBrowserSessionRequired(ArcaCollectorError):
    pass


class ArcaCollectionStopped(ArcaCollectorError):
    pass


_ARCA_BROWSER_LOCK = RLock()
_ARCA_BROWSER_COOKIES = CookieJar()
_ARCA_BROWSER_STATUS = {"connected": False, "browser": "", "error": ""}
_COLLECTION_CONTROL_LOCK = RLock()
_COLLECTION_CONTROLS = {}


def create_arca_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Cache-Control": "no-cache",
    })
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def _is_arca_cookie(cookie):
    domain = str(getattr(cookie, "domain", "") or "").lower().lstrip(".")
    return domain == "arca.live" or domain.endswith(".arca.live")


def clear_arca_browser_session(error=""):
    global _ARCA_BROWSER_COOKIES, _ARCA_BROWSER_STATUS
    with _ARCA_BROWSER_LOCK:
        _ARCA_BROWSER_COOKIES = CookieJar()
        _ARCA_BROWSER_STATUS = {"connected": False, "browser": "", "error": str(error or "")}
        return dict(_ARCA_BROWSER_STATUS)


def get_arca_browser_session_status():
    with _ARCA_BROWSER_LOCK:
        return dict(_ARCA_BROWSER_STATUS)


def snapshot_imported_arca_cookies():
    with _ARCA_BROWSER_LOCK:
        return [copy.copy(cookie) for cookie in _ARCA_BROWSER_COOKIES]


def _apply_imported_arca_cookies(session):
    for cookie in snapshot_imported_arca_cookies():
        session.cookies.set_cookie(cookie)
    return session


def connect_arca_cookie_jar(cookie_jar, browser, validator=None):
    global _ARCA_BROWSER_COOKIES, _ARCA_BROWSER_STATUS
    filtered = CookieJar()
    for cookie in cookie_jar or []:
        if _is_arca_cookie(cookie):
            filtered.set_cookie(copy.copy(cookie))
    if not list(filtered):
        return clear_arca_browser_session("아카라이브 로그인 정보를 찾지 못했습니다.")
    try:
        session = create_arca_session()
        for cookie in filtered:
            session.cookies.set_cookie(copy.copy(cookie))
        categories = (validator or discover_category_params)(session)
        if "R18_NAI" not in categories:
            return clear_arca_browser_session("로그인했지만 🔞 NAI 접근을 확인하지 못했습니다.")
        with _ARCA_BROWSER_LOCK:
            _ARCA_BROWSER_COOKIES = filtered
            _ARCA_BROWSER_STATUS = {"connected": True, "browser": str(browser or ""), "error": ""}
            return dict(_ARCA_BROWSER_STATUS)
    except Exception:
        return clear_arca_browser_session("아카라이브 로그인 확인에 실패했습니다.")


def import_arca_browser_session(loaders=None, validator=None):
    global _ARCA_BROWSER_COOKIES, _ARCA_BROWSER_STATUS
    clear_arca_browser_session()
    if loaders is None:
        try:
            import browser_cookie3
        except ImportError:
            return clear_arca_browser_session("브라우저 로그인 가져오기 구성요소가 설치되지 않았습니다.")
        loaders = [
            ("Chrome", lambda: browser_cookie3.chrome(domain_name="arca.live")),
            ("Edge", lambda: browser_cookie3.edge(domain_name="arca.live")),
        ]
    validator = validator or discover_category_params
    for browser, loader in loaders:
        try:
            filtered = CookieJar()
            for cookie in loader():
                if _is_arca_cookie(cookie):
                    filtered.set_cookie(copy.copy(cookie))
            if not list(filtered):
                continue
            session = create_arca_session()
            for cookie in filtered:
                session.cookies.set_cookie(copy.copy(cookie))
            categories = validator(session)
            if "R18_NAI" not in categories:
                continue
            with _ARCA_BROWSER_LOCK:
                _ARCA_BROWSER_COOKIES = filtered
                _ARCA_BROWSER_STATUS = {"connected": True, "browser": browser, "error": ""}
                return dict(_ARCA_BROWSER_STATUS)
        except Exception:
            continue
    return clear_arca_browser_session("Chrome 또는 Edge에서 로그인된 아카라이브 세션을 찾지 못했습니다.")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table, name, declaration):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def init_arca_style_tables(db_path):
    with closing(_connect(db_path)) as conn, conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS arca_style_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source_url TEXT NOT NULL UNIQUE,
            article_id TEXT DEFAULT '', board_tab TEXT DEFAULT '', title TEXT DEFAULT '',
            author TEXT DEFAULT '', posted_at TEXT DEFAULT '', collected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, representative_image_url TEXT DEFAULT '',
            representative_image_path TEXT DEFAULT '', image_count INTEGER NOT NULL DEFAULT 0,
            metadata_status TEXT DEFAULT 'none', prompt TEXT DEFAULT '',
            negative_prompt TEXT DEFAULT '', seed TEXT DEFAULT '', sampler TEXT DEFAULT '',
            steps INTEGER, scale REAL, cfg_rescale REAL, noise_schedule TEXT DEFAULT '',
            model TEXT DEFAULT '', width INTEGER, height INTEGER,
            raw_metadata_json TEXT DEFAULT '{}', body_prompt_text TEXT DEFAULT '', memo TEXT DEFAULT '',
            recommendation_count INTEGER, view_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS arca_style_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL,
            image_url TEXT NOT NULL, image_path TEXT DEFAULT '', content_type TEXT DEFAULT '',
            metadata_status TEXT DEFAULT 'none', prompt TEXT DEFAULT '',
            negative_prompt TEXT DEFAULT '', seed TEXT DEFAULT '', sampler TEXT DEFAULT '',
            steps INTEGER, scale REAL, cfg_rescale REAL, noise_schedule TEXT DEFAULT '',
            model TEXT DEFAULT '', width INTEGER, height INTEGER,
            raw_metadata_json TEXT DEFAULT '{}', created_at TEXT NOT NULL,
            UNIQUE(item_id, image_url), FOREIGN KEY(item_id) REFERENCES arca_style_items(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS arca_collection_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT NOT NULL, tabs TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, max_pages INTEGER NOT NULL,
            max_posts INTEGER NOT NULL, search_scope TEXT NOT NULL DEFAULT 'title-row-stealth-v4', status TEXT NOT NULL, scanned_pages INTEGER DEFAULT 0,
            scanned_posts INTEGER DEFAULT 0, saved INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
            error TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS arca_collection_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, request_json TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'queued',
            total_pages INTEGER, scanned_pages INTEGER NOT NULL DEFAULT 0,
            total_posts INTEGER, scanned_posts INTEGER NOT NULL DEFAULT 0,
            downloaded_images INTEGER NOT NULL DEFAULT 0,
            downloaded_bytes INTEGER NOT NULL DEFAULT 0,
            estimated_bytes INTEGER,
            saved INTEGER NOT NULL DEFAULT 0, updated INTEGER NOT NULL DEFAULT 0,
            average_post_seconds REAL, skipped_existing INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '', started_at TEXT, finished_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS arca_collection_run_items (
            run_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
            PRIMARY KEY(run_id,item_id),
            FOREIGN KEY(run_id) REFERENCES arca_collection_runs(id) ON DELETE CASCADE,
            FOREIGN KEY(item_id) REFERENCES arca_style_items(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS arca_collection_invalidations (
            keyword TEXT NOT NULL, tabs TEXT NOT NULL,
            max_pages INTEGER NOT NULL, max_posts INTEGER NOT NULL,
            search_scope TEXT NOT NULL, invalidated_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(keyword,tabs,max_pages,max_posts,search_scope,invalidated_date)
        );
        CREATE INDEX IF NOT EXISTS idx_arca_items_posted ON arca_style_items(posted_at);
        CREATE INDEX IF NOT EXISTS idx_arca_items_tab ON arca_style_items(board_tab);
        CREATE INDEX IF NOT EXISTS idx_arca_items_metadata ON arca_style_items(metadata_status);
        CREATE INDEX IF NOT EXISTS idx_arca_images_item ON arca_style_images(item_id);
        CREATE INDEX IF NOT EXISTS idx_arca_items_metadata_tab ON arca_style_items(metadata_status,board_tab);
        CREATE INDEX IF NOT EXISTS idx_arca_images_metadata_item ON arca_style_images(metadata_status,item_id);
        CREATE INDEX IF NOT EXISTS idx_arca_runs_lookup ON arca_collection_runs(keyword,tabs,max_pages,max_posts,status);
        CREATE TABLE IF NOT EXISTS arca_prompt_preset_index (
            image_id INTEGER PRIMARY KEY, source_hash TEXT NOT NULL,
            base_prompt TEXT NOT NULL, negative_prompt TEXT NOT NULL,
            excluded_tags_json TEXT NOT NULL DEFAULT '[]', artists_json TEXT NOT NULL DEFAULT '[]',
            recommendation_count INTEGER,
            FOREIGN KEY(image_id) REFERENCES arca_style_images(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS arca_seed_imports (
            seed_hash TEXT PRIMARY KEY, imported_at TEXT NOT NULL
        );
        """)
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_collection_runs)")}
        if "search_scope" not in run_columns:
            conn.execute("ALTER TABLE arca_collection_runs ADD COLUMN search_scope TEXT NOT NULL DEFAULT 'all'")
        _ensure_column(conn, "arca_collection_runs", "job_id", "INTEGER REFERENCES arca_collection_jobs(id)")
        _ensure_column(conn, "arca_collection_jobs", "job_type", "TEXT NOT NULL DEFAULT 'collection'")
        _ensure_column(conn, "arca_collection_jobs", "downloaded_bytes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "arca_collection_jobs", "estimated_bytes", "INTEGER")
        _ensure_column(conn, "arca_style_images", "base_prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "arca_style_images", "character_prompts_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "arca_style_items", "recommendation_count", "INTEGER")
        _ensure_column(conn, "arca_style_items", "view_count", "INTEGER")


def _init_danbooru_seed_tables(conn):
    conn.executescript("""
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
        );
        CREATE TABLE IF NOT EXISTS artist_cache (
            artist_tag TEXT PRIMARY KEY,
            artist_post_count INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """)


def export_arca_style_seed(source_db, seed_db):
    """Create a distributable archive and Danbooru DB without local files or generated results."""
    source, target = Path(source_db).resolve(), Path(seed_db).resolve()
    if source == target:
        raise ValueError("Seed output must be different from the source database.")
    if not source.is_file():
        raise FileNotFoundError(f"Shared-style database not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    init_arca_style_tables(target)
    with closing(_connect(target)) as conn, conn:
        _init_danbooru_seed_tables(conn)
        conn.execute("ATTACH DATABASE ? AS source", (str(source),))
        source_tables = {
            row[0] for row in conn.execute("SELECT name FROM source.sqlite_master WHERE type='table'")
        }
        item_columns = [row[1] for row in conn.execute("PRAGMA main.table_info(arca_style_items)")]
        image_columns = [row[1] for row in conn.execute("PRAGMA main.table_info(arca_style_images)")]
        item_select = ["''" if name == "representative_image_path" else name for name in item_columns]
        image_select = ["''" if name == "image_path" else name for name in image_columns]
        conn.execute(
            f"INSERT INTO arca_style_items ({','.join(item_columns)}) "
            f"SELECT {','.join(item_select)} FROM source.arca_style_items"
        )
        conn.execute(
            f"INSERT INTO arca_style_images ({','.join(image_columns)}) "
            f"SELECT {','.join(image_select)} FROM source.arca_style_images"
        )
        run_columns = [
            row[1] for row in conn.execute("PRAGMA main.table_info(arca_collection_runs)")
            if row[1] != "job_id"
        ]
        conn.execute(
            f"INSERT INTO arca_collection_runs ({','.join(run_columns)}) "
            f"SELECT {','.join(run_columns)} FROM source.arca_collection_runs WHERE status='completed'"
        )
        conn.execute(
            "INSERT INTO arca_collection_run_items(run_id,item_id) "
            "SELECT ri.run_id,ri.item_id FROM source.arca_collection_run_items ri "
            "JOIN arca_collection_runs run ON run.id=ri.run_id "
            "JOIN arca_style_items item ON item.id=ri.item_id"
        )
        conn.execute(
            "INSERT OR IGNORE INTO arca_collection_invalidations "
            "SELECT * FROM source.arca_collection_invalidations"
        )
        if "artist_cache" in source_tables:
            conn.execute("INSERT INTO artist_cache SELECT * FROM source.artist_cache")
    with closing(sqlite3.connect(target)) as conn:
        conn.execute("VACUUM")
    return {
        "items": _table_count(target, "arca_style_items"),
        "images": _table_count(target, "arca_style_images"),
        "ratings": _table_count(target, "ratings"),
        "artist_cache": _table_count(target, "artist_cache"),
        "bytes": target.stat().st_size,
    }


def _table_count(db_path, table):
    with closing(_connect(db_path)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def import_arca_style_seed(db_path, seed_db):
    """Merge a bundled metadata-only seed once, preserving existing local rows and image files."""
    seed = Path(seed_db)
    if not seed.is_file():
        return {"imported": False, "items": 0, "images": 0}
    seed_hash = hashlib.sha256(seed.read_bytes()).hexdigest()
    init_arca_style_tables(db_path)
    with closing(_connect(db_path)) as conn, conn:
        _init_danbooru_seed_tables(conn)
        if conn.execute("SELECT 1 FROM arca_seed_imports WHERE seed_hash=?", (seed_hash,)).fetchone():
            return {"imported": False, "items": 0, "images": 0}
        before_items = conn.execute("SELECT COUNT(*) FROM arca_style_items").fetchone()[0]
        before_images = conn.execute("SELECT COUNT(*) FROM arca_style_images").fetchone()[0]
        conn.execute("ATTACH DATABASE ? AS seed", (str(seed.resolve()),))
        seed_tables = {
            row[0] for row in conn.execute("SELECT name FROM seed.sqlite_master WHERE type='table'")
        }
        if "ratings" in seed_tables:
            rating_columns = [
                row[1] for row in conn.execute("PRAGMA main.table_info(ratings)") if row[1] != "id"
            ]
            conn.execute(
                f"INSERT OR IGNORE INTO ratings ({','.join(rating_columns)}) "
                f"SELECT {','.join(rating_columns)} FROM seed.ratings"
            )
        if "artist_cache" in seed_tables:
            conn.execute("INSERT OR IGNORE INTO artist_cache SELECT * FROM seed.artist_cache")
        item_columns = [row[1] for row in conn.execute("PRAGMA main.table_info(arca_style_items)") if row[1] != "id"]
        conn.execute(
            f"INSERT OR IGNORE INTO arca_style_items ({','.join(item_columns)}) "
            f"SELECT {','.join(item_columns)} FROM seed.arca_style_items"
        )
        image_columns = [
            row[1] for row in conn.execute("PRAGMA main.table_info(arca_style_images)")
            if row[1] not in {"id", "item_id"}
        ]
        conn.execute(
            f"INSERT OR IGNORE INTO arca_style_images (item_id,{','.join(image_columns)}) "
            f"SELECT target.id,{','.join(f'image.{name}' for name in image_columns)} "
            "FROM seed.arca_style_images image "
            "JOIN seed.arca_style_items source ON source.id=image.item_id "
            "JOIN arca_style_items target ON target.source_url=source.source_url"
        )
        run_map = {}
        run_columns = [
            row[1] for row in conn.execute("PRAGMA main.table_info(arca_collection_runs)")
            if row[1] not in {"id", "job_id"}
        ]
        for row in conn.execute(f"SELECT id,{','.join(run_columns)} FROM seed.arca_collection_runs WHERE status='completed'"):
            cursor = conn.execute(
                f"INSERT INTO arca_collection_runs ({','.join(run_columns)}) VALUES ({','.join('?' for _ in run_columns)})",
                tuple(row[name] for name in run_columns),
            )
            run_map[row["id"]] = cursor.lastrowid
        for seed_run_id, run_id in run_map.items():
            conn.execute(
                "INSERT OR IGNORE INTO arca_collection_run_items(run_id,item_id) "
                "SELECT ?,target.id FROM seed.arca_collection_run_items link "
                "JOIN seed.arca_style_items source ON source.id=link.item_id "
                "JOIN arca_style_items target ON target.source_url=source.source_url "
                "WHERE link.run_id=?",
                (run_id, seed_run_id),
            )
        conn.execute(
            "INSERT OR IGNORE INTO arca_collection_invalidations "
            "SELECT * FROM seed.arca_collection_invalidations"
        )
        conn.execute(
            "INSERT INTO arca_seed_imports(seed_hash,imported_at) VALUES(?,?)",
            (seed_hash, datetime.now().isoformat(timespec="seconds")),
        )
        items = conn.execute("SELECT COUNT(*) FROM arca_style_items").fetchone()[0] - before_items
        images = conn.execute("SELECT COUNT(*) FROM arca_style_images").fetchone()[0] - before_images
    return {"imported": True, "items": items, "images": images}


def _iso_date(value, name):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ArcaCollectorError(f"{name} 형식은 YYYY-MM-DD여야 합니다.")


def normalize_collect_payload(payload):
    payload = payload if isinstance(payload, dict) else {}
    today = date.today()
    start = _iso_date(payload.get("start_date", today.isoformat()), "start_date")
    end = _iso_date(payload.get("end_date", today.isoformat()), "end_date")
    if start > end:
        raise ArcaCollectorError("시작일은 종료일보다 늦을 수 없습니다.")
    tabs = sorted(set(payload.get("tabs") or ["NAI", "R18_NAI"]))
    if not tabs or any(tab not in {"NAI", "R18_NAI"} for tab in tabs):
        raise ArcaCollectorError("NAI 또는 R18_NAI 탭을 선택해 주세요.")
    try:
        max_pages, max_posts = int(payload.get("max_pages", 0)), int(payload.get("max_posts", 0))
    except (TypeError, ValueError):
        raise ArcaCollectorError("페이지와 글 수는 숫자여야 합니다.")
    if not 0 <= max_pages <= MAX_ARCHIVE_SEARCH_PAGE or max_posts < 0:
        raise ArcaCollectorError("페이지 또는 글 수 제한이 범위를 벗어났습니다.")
    keyword = str(payload.get("keyword") or DEFAULT_KEYWORD).strip()
    if not keyword or len(keyword) > 200:
        raise ArcaCollectorError("검색어를 확인해 주세요.")
    return {"keyword": keyword, "tabs": tabs, "start_date": start.isoformat(), "end_date": end.isoformat(), "max_pages": max_pages, "max_posts": max_posts}


def merge_date_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def uncovered_date_intervals(start, end, covered):
    result, cursor = [], start
    for left, right in merge_date_intervals(covered):
        if right < cursor or left > end:
            continue
        if cursor < left:
            result.append((cursor, min(end, left - timedelta(days=1))))
        cursor = max(cursor, right + timedelta(days=1))
    if cursor <= end:
        result.append((cursor, end))
    return result


def _tabs_key(tabs):
    return ",".join(sorted(set(tabs)))


def create_collection_job(db_path, payload):
    params = normalize_collect_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        return conn.execute(
            "INSERT INTO arca_collection_jobs(request_json,status,stage,total_pages,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (
                json.dumps(params, ensure_ascii=False), "queued", "queued",
                params["max_pages"] * len(params["tabs"]) if params["max_pages"] else None,
                now, now,
            ),
        ).lastrowid


def update_collection_job(db_path, job_id, **changes):
    allowed = {
        "status", "stage", "total_pages", "scanned_pages", "total_posts",
        "scanned_posts", "downloaded_images", "downloaded_bytes", "estimated_bytes", "saved", "updated",
        "average_post_seconds", "skipped_existing", "error", "started_at", "finished_at",
    }
    values = {key: value for key, value in changes.items() if key in allowed}
    now = datetime.now().isoformat(timespec="seconds")
    if values.get("status") == "running" and "started_at" not in values:
        with closing(_connect(db_path)) as conn:
            current = conn.execute("SELECT started_at FROM arca_collection_jobs WHERE id=?", (job_id,)).fetchone()
        if current and not current[0]:
            values["started_at"] = now
    if values.get("status") in {"completed", "failed", "interrupted"} and "finished_at" not in values:
        values["finished_at"] = now
    values["updated_at"] = now
    if not values:
        return
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            f"UPDATE arca_collection_jobs SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
            (*values.values(), job_id),
        )


def get_collection_job(db_path, job_id):
    with closing(_connect(db_path)) as conn:
        job = _row(conn.execute("SELECT * FROM arca_collection_jobs WHERE id=?", (job_id,)).fetchone())
    if not job:
        return None
    started = datetime.fromisoformat(job["started_at"]) if job.get("started_at") else None
    finished = datetime.fromisoformat(job["finished_at"]) if job.get("finished_at") else None
    elapsed = max(0, int(((finished or datetime.now()) - started).total_seconds())) if started else 0
    remaining = None
    if job.get("average_post_seconds") is not None and job.get("total_posts") is not None:
        remaining = round(float(job["average_post_seconds"]) * max(int(job["total_posts"]) - int(job["scanned_posts"]), 0))
    job["elapsed_seconds"] = elapsed
    job["estimated_remaining_seconds"] = remaining
    job["progress"] = {
        "pages": [job["scanned_pages"], job["total_pages"]],
        "posts": [job["scanned_posts"], job["total_posts"]],
        "images": job["downloaded_images"],
    }
    if job.get("job_type") == "image_restore":
        job["progress"]["bytes"] = [job.get("downloaded_bytes") or 0, job.get("estimated_bytes")]
    return job


def get_latest_resumable_collection_job(db_path):
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT id,status FROM arca_collection_jobs ORDER BY id DESC LIMIT 1").fetchone()
    resumable = {"queued", "running", "pause_requested", "paused", "stop_requested", "interrupted", "stopped", "failed"}
    return get_collection_job(db_path, row[0]) if row and row[1] in resumable else None


def _register_collection_control(job_id):
    control = {"pause": Event(), "stop": Event()}
    with _COLLECTION_CONTROL_LOCK:
        _COLLECTION_CONTROLS[job_id] = control
    return control


def _collection_control(job_id):
    with _COLLECTION_CONTROL_LOCK:
        return _COLLECTION_CONTROLS.get(job_id)


def _remove_collection_control(job_id):
    with _COLLECTION_CONTROL_LOCK:
        _COLLECTION_CONTROLS.pop(job_id, None)


def _wait_for_collection_control(db_path, job_id, resume_stage):
    if not job_id:
        return
    control = _collection_control(job_id)
    if not control:
        return
    if control["stop"].is_set():
        raise ArcaCollectionStopped("사용자가 수집을 중지했습니다.")
    paused = False
    while control["pause"].is_set():
        if not paused:
            update_collection_job(db_path, job_id, status="paused", stage="paused")
            paused = True
        if control["stop"].wait(0.25):
            raise ArcaCollectionStopped("사용자가 수집을 중지했습니다.")
    if paused:
        update_collection_job(db_path, job_id, status="running", stage=resume_stage)


def pause_collection_job(db_path, job_id):
    job = get_collection_job(db_path, job_id)
    if not job:
        raise ArcaCollectorError("수집 작업을 찾을 수 없습니다.")
    control = _collection_control(job_id)
    if not control or job["status"] not in {"queued", "running", "pause_requested", "paused"}:
        raise ArcaCollectorError("현재 작업은 일시정지할 수 없습니다.")
    control["pause"].set()
    update_collection_job(db_path, job_id, status="pause_requested", stage="pause_requested")
    return get_collection_job(db_path, job_id)


def stop_collection_job(db_path, job_id):
    job = get_collection_job(db_path, job_id)
    if not job:
        raise ArcaCollectorError("수집 작업을 찾을 수 없습니다.")
    control = _collection_control(job_id)
    if not control or job["status"] not in {"queued", "running", "pause_requested", "paused", "stop_requested"}:
        raise ArcaCollectorError("현재 작업은 중지할 수 없습니다.")
    control["stop"].set()
    control["pause"].clear()
    update_collection_job(db_path, job_id, status="stop_requested", stage="stop_requested")
    return get_collection_job(db_path, job_id)


def resume_collection_job(db_path, image_dir, job_id):
    job = get_collection_job(db_path, job_id)
    if not job:
        raise ArcaCollectorError("수집 작업을 찾을 수 없습니다.")
    control = _collection_control(job_id)
    if control and job["status"] in {"pause_requested", "paused"}:
        control["pause"].clear()
        update_collection_job(db_path, job_id, status="running", stage="resuming")
        return job_id
    if job["status"] not in {"interrupted", "stopped", "failed"}:
        raise ArcaCollectorError("현재 작업은 이어서 시작할 수 없습니다.")
    if job.get("job_type") == "image_restore":
        return start_image_restore_job(db_path, image_dir)
    try:
        payload = json.loads(job["request_json"])
    except (TypeError, json.JSONDecodeError):
        raise ArcaCollectorError("이전 수집 조건을 읽지 못했습니다.")
    return start_collection_job(db_path, image_dir, payload)


def mark_interrupted_collection_jobs(db_path):
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE arca_collection_jobs SET status='interrupted',stage='interrupted',error=?,finished_at=?,updated_at=? "
            "WHERE status IN ('queued','running','pause_requested','paused','stop_requested')",
            ("앱이 종료되어 수집이 중단되었습니다.", now, now),
        )


def _run_collection_job(db_path, image_dir, params, job_id):
    try:
        update_collection_job(db_path, job_id, status="running", stage="searching")
        collect_arca_styles(db_path, image_dir, params, job_id=job_id)
    except ArcaCollectionStopped as exc:
        update_collection_job(db_path, job_id, status="stopped", stage="stopped", error=str(exc))
    except Exception as exc:
        update_collection_job(db_path, job_id, status="failed", stage="failed", error=str(exc)[:1000])
    finally:
        _remove_collection_control(job_id)


def start_collection_job(db_path, image_dir, payload):
    params = normalize_collect_payload(payload)
    job_id = create_collection_job(db_path, params)
    _register_collection_control(job_id)
    worker = Thread(target=_run_collection_job, args=(db_path, image_dir, params, job_id), daemon=True)
    worker.start()
    return job_id


def create_url_collection_job(db_path, source_url):
    canonical = normalize_arca_article_url(source_url)
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        return conn.execute(
            "INSERT INTO arca_collection_jobs(request_json,status,stage,total_pages,total_posts,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (json.dumps({"source_url": canonical}, ensure_ascii=False), "queued", "queued", 1, 1, now, now),
        ).lastrowid


def _local_image_exists(image_root, value):
    if not value:
        return False
    root = Path(image_root).resolve()
    path = (root / str(value)).resolve()
    return root in path.parents and path.is_file()


def _local_image_size(image_root, value):
    if not value:
        return 0
    root = Path(image_root).resolve()
    path = (root / str(value)).resolve()
    if root not in path.parents or not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _reusable_direct_item_id(db_path, image_dir, source_url):
    with closing(_connect(db_path)) as conn:
        item = conn.execute(
            "SELECT id,representative_image_path FROM arca_style_items WHERE source_url=? AND metadata_status='ok'",
            (source_url,),
        ).fetchone()
        if not item or not _local_image_exists(image_dir, item["representative_image_path"]):
            return None
        rows = conn.execute(
            "SELECT image_path FROM arca_style_images WHERE item_id=? AND metadata_status='ok' AND TRIM(COALESCE(image_path,''))<>''",
            (item["id"],),
        ).fetchall()
    return item["id"] if any(_local_image_exists(image_dir, row["image_path"]) for row in rows) else None


def collect_arca_style_url(db_path, image_dir, source_url, job_id=None, session=None):
    canonical = normalize_arca_article_url(source_url)
    init_arca_style_tables(db_path)
    reusable_item_id = _reusable_direct_item_id(db_path, image_dir, canonical)
    if reusable_item_id is not None:
        if job_id:
            update_collection_job(
                db_path, job_id, status="completed", stage="completed", total_pages=1,
                scanned_pages=0, total_posts=1, scanned_posts=0, downloaded_images=0,
                saved=0, updated=0, skipped_existing=1,
            )
        return {
            "ok": True, "item_id": reusable_item_id, "saved": 0, "updated": 0,
            "downloaded_images": 0, "skipped_existing": True,
        }
    if session is None:
        session = create_arca_session()
        if get_arca_browser_session_status()["connected"]:
            _apply_imported_arca_cookies(session)
    if job_id:
        update_collection_job(db_path, job_id, status="running", stage="fetching_posts", total_pages=1, scanned_pages=0, total_posts=1, scanned_posts=0)
    html = fetch_html(session, canonical)
    article = extract_article_data(html, canonical)
    if not article.get("image_urls"):
        raise ArcaCollectorError("게시글 본문에서 수집할 이미지를 찾지 못했습니다.")
    if job_id:
        update_collection_job(db_path, job_id, stage="downloading", scanned_pages=1, scanned_posts=1)
    summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
    downloaded_count, item_id = _save_article(db_path, image_dir, session, article, summary)
    result = {
        "ok": True, "item_id": item_id, "saved": summary["saved"], "updated": summary["updated"],
        "downloaded_images": downloaded_count,
    }
    if job_id:
        update_collection_job(
            db_path, job_id, status="completed", stage="completed", scanned_pages=1,
            total_posts=1, scanned_posts=1, downloaded_images=downloaded_count,
            saved=summary["saved"], updated=summary["updated"],
        )
    return result


def _run_url_collection_job(db_path, image_dir, source_url, job_id):
    try:
        collect_arca_style_url(db_path, image_dir, source_url, job_id=job_id)
    except Exception as exc:
        update_collection_job(db_path, job_id, status="failed", stage="failed", error=str(exc)[:1000])


def start_url_collection_job(db_path, image_dir, source_url):
    canonical = normalize_arca_article_url(source_url)
    job_id = create_url_collection_job(db_path, canonical)
    Thread(target=_run_url_collection_job, args=(db_path, image_dir, canonical, job_id), daemon=True).start()
    return job_id


def create_image_restore_job(db_path, image_dir):
    init_arca_style_tables(db_path)
    missing = _missing_image_rows(db_path, image_dir)
    estimate = get_image_restore_estimate(db_path, image_dir)
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        job_id = conn.execute(
            "INSERT INTO arca_collection_jobs(request_json,job_type,status,stage,total_pages,total_posts,estimated_bytes,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                json.dumps({"mode": "image_restore"}), "image_restore", "queued", "queued",
                0, len(missing), estimate["estimated_download_bytes"], now, now,
            ),
        ).lastrowid
    return job_id, missing


def _missing_image_rows(db_path, image_dir):
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT id,item_id,image_url,image_path,content_type FROM arca_style_images "
            "WHERE metadata_status='ok' AND TRIM(COALESCE(image_url,''))<>'' ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows if not _local_image_exists(image_dir, row["image_path"])]


def get_image_restore_estimate(db_path, image_dir):
    """Estimate a one-time image restore from local samples without slow network probes."""
    init_arca_style_tables(db_path)
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT image_path FROM arca_style_images "
            "WHERE metadata_status='ok' AND TRIM(COALESCE(image_url,''))<>''"
        ).fetchall()
    local_sizes = [size for row in rows if (size := _local_image_size(image_dir, row["image_path"]))]
    total_images = len(rows)
    local_images = len(local_sizes)
    missing_images = total_images - local_images
    average_bytes = (
        round(sum(local_sizes) / local_images)
        if local_images
        else DEFAULT_IMAGE_ESTIMATE_BYTES
    )
    estimated_bytes = average_bytes * missing_images
    return {
        "total_images": total_images,
        "local_images": local_images,
        "missing_images": missing_images,
        "local_bytes": sum(local_sizes),
        "average_image_bytes": average_bytes,
        "estimated_download_bytes": estimated_bytes,
        "estimated_seconds": round(estimated_bytes / IMAGE_RESTORE_ESTIMATE_BYTES_PER_SECOND),
        "estimate_source": "local_average" if local_images else "default_average",
        "parallel_workers": IMAGE_RESTORE_WORKERS,
    }


def restore_arca_style_images(db_path, image_dir, job_id, missing=None):
    rows = list(missing if missing is not None else _missing_image_rows(db_path, image_dir))
    total = len(rows)
    update_collection_job(
        db_path, job_id, status="running", stage="restoring_images", total_pages=0,
        scanned_pages=0, total_posts=total, scanned_posts=0, downloaded_images=0,
        downloaded_bytes=0,
    )
    if not rows:
        update_collection_job(db_path, job_id, status="completed", stage="completed", skipped_existing=1)
        return {"restored": 0, "failed": 0, "skipped_existing": True}
    session = create_arca_session()
    if get_arca_browser_session_status()["connected"]:
        _apply_imported_arca_cookies(session)

    def fetch_one(row):
        try:
            data, content_type = download_image(session, row["image_url"])
            return row, data, content_type
        except (requests.RequestException, ArcaCollectorError):
            return row, None, ""

    restored = failed = processed = downloaded_bytes = 0
    started = time.monotonic()
    workers = min(IMAGE_RESTORE_WORKERS, total)
    pending_rows = iter(rows)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for _ in range(workers):
            row = next(pending_rows, None)
            if row is None:
                break
            pending[executor.submit(fetch_one, row)] = row
        while pending:
            _wait_for_collection_control(db_path, job_id, "restoring_images")
            future = next(as_completed(tuple(pending)))
            pending.pop(future)
            row, data, content_type = future.result()
            processed += 1
            if data is None:
                failed += 1
            else:
                try:
                    path = save_image_bytes(image_dir, row["image_url"], data, content_type)
                except OSError:
                    failed += 1
                else:
                    restored += 1
                    downloaded_bytes += len(data)
                    with closing(_connect(db_path)) as conn, conn:
                        conn.execute(
                            "UPDATE arca_style_images SET image_path=?,content_type=? WHERE id=?",
                            (path, content_type, row["id"]),
                        )
                        conn.execute(
                            "UPDATE arca_style_items SET representative_image_path=? "
                            "WHERE id=? AND representative_image_url=?",
                            (path, row["item_id"], row["image_url"]),
                        )
            average = (time.monotonic() - started) / processed
            update_collection_job(
                db_path, job_id, stage="restoring_images", scanned_posts=processed,
                downloaded_images=restored, downloaded_bytes=downloaded_bytes,
                updated=restored, average_post_seconds=average,
            )
            row = next(pending_rows, None)
            if row is not None:
                pending[executor.submit(fetch_one, row)] = row
    error = f"{failed}개 이미지를 받지 못했습니다. 다시 실행하면 실패한 이미지만 재시도합니다." if failed else ""
    update_collection_job(
        db_path, job_id, status="completed", stage="completed", scanned_posts=processed,
        downloaded_images=restored, downloaded_bytes=downloaded_bytes,
        updated=restored, error=error,
    )
    return {
        "restored": restored, "failed": failed,
        "downloaded_bytes": downloaded_bytes, "skipped_existing": False,
    }


def _run_image_restore_job(db_path, image_dir, job_id, missing):
    try:
        restore_arca_style_images(db_path, image_dir, job_id, missing)
    except ArcaCollectionStopped as exc:
        update_collection_job(db_path, job_id, status="stopped", stage="stopped", error=str(exc))
    except Exception as exc:
        update_collection_job(db_path, job_id, status="failed", stage="failed", error=str(exc)[:1000])
    finally:
        _remove_collection_control(job_id)


def start_image_restore_job(db_path, image_dir):
    job_id, missing = create_image_restore_job(db_path, image_dir)
    _register_collection_control(job_id)
    Thread(target=_run_image_restore_job, args=(db_path, image_dir, job_id, missing), daemon=True).start()
    return job_id


def _get_completed_coverage_intervals(db_path, params):
    with closing(_connect(db_path)) as conn:
        rows = conn.execute("SELECT start_date,end_date FROM arca_collection_runs WHERE keyword=? AND tabs=? AND max_pages=? AND max_posts=? AND search_scope=? AND status='completed'", (params["keyword"], _tabs_key(params["tabs"]), params["max_pages"], params["max_posts"], SEARCH_SCOPE)).fetchall()
    return merge_date_intervals([(_iso_date(row[0], "start_date"), _iso_date(row[1], "end_date")) for row in rows])


def get_completed_coverage(db_path, params):
    completed = _get_completed_coverage_intervals(db_path, params)
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT invalidated_date FROM arca_collection_invalidations WHERE keyword=? AND tabs=? AND max_pages=? AND max_posts=? AND search_scope=?",
            (params["keyword"], _tabs_key(params["tabs"]), params["max_pages"], params["max_posts"], SEARCH_SCOPE),
        ).fetchall()
    invalidated = {date.fromisoformat(row[0]) for row in rows}
    effective = []
    for start, end in completed:
        cursor = start
        while cursor <= end:
            if cursor not in invalidated:
                effective.append((cursor, cursor))
            cursor += timedelta(days=1)
    return merge_date_intervals(effective)


class _HTMLScan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []
    def handle_starttag(self, tag, attrs): self.tags.append((tag, dict(attrs)))
    def handle_data(self, data): self.text.append(data)


class _CategoryLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = {"href": dict(attrs).get("href", ""), "text": []}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current["href"], " ".join(self.current["text"]).strip()))
            self.current = None


class _SearchResultParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.depth = 0
        self.roles = []
        self.results = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self.current is None:
            if tag == "a" and {"vrow", "column"} <= classes and "notice" not in classes:
                self.current = {"href": attributes.get("href", ""), "title": [], "badge": [], "posted_at": ""}
                self.depth = 1
                self.roles = [None]
            return
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.depth += 1
        role = "title" if "title" in classes else ("badge" if "badge" in classes else None)
        self.roles.append(role)
        if tag == "time" and attributes.get("datetime"):
            self.current["posted_at"] = attributes["datetime"][:10]

    def handle_data(self, data):
        if self.current is None or not data.strip():
            return
        if "title" in self.roles:
            self.current["title"].append(data)
        elif "badge" in self.roles:
            self.current["badge"].append(data)

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == "a" and self.depth == 1:
            self.results.append(self.current)
            self.current = None
            self.depth = 0
            self.roles = []
            return
        if self.roles:
            self.roles.pop()
        self.depth = max(0, self.depth - 1)


class _ArticleContentParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.found = False
        self.depth = 0
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if not self.active:
            if tag == "div" and "article-content" in classes:
                self.active = True
                self.found = True
                self.depth = 1
            return
        self.tags.append((tag, attributes))
        if tag not in self.VOID_TAGS:
            self.depth += 1

    def handle_data(self, data):
        if self.active and data.strip():
            self.text.append(data.strip())

    def handle_endtag(self, tag):
        if not self.active or tag in self.VOID_TAGS:
            return
        self.depth -= 1
        if self.depth <= 0:
            self.active = False


def _safe_url(value, base):
    if not value: return ""
    url = urljoin(base, value.strip())
    return url if urlparse(url).scheme in {"http", "https"} else ""


def normalize_arca_article_url(value):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "arca.live":
        raise ArcaCollectorError("아카라이브 공개 게시글 URL을 확인해 주세요.")
    match = re.fullmatch(r"/b/aiart/(\d+)/?", parsed.path)
    if not match:
        raise ArcaCollectorError("https://arca.live/b/aiart/숫자 형식의 URL만 추가할 수 있습니다.")
    return f"https://arca.live/b/aiart/{match.group(1)}"


def _image_identity(value):
    parsed = urlparse(str(value or ""))
    stable = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() not in {"expires", "key", "type"}]
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", urlencode(sorted(stable)), ""))


def extract_article_links(html, base_url=ARCA_BASE_URL):
    parser = _HTMLScan(); parser.feed(html)
    result = []
    for tag, attrs in parser.tags:
        if tag != "a": continue
        url = _safe_url(attrs.get("href"), base_url)
        match = re.match(r"^(https?://[^/]+/b/aiart/\d+)", url)
        if match and match.group(1) not in result: result.append(match.group(1))
    return result


def extract_search_results(html, base_url=ARCA_BASE_URL, keyword=DEFAULT_KEYWORD):
    parser = _SearchResultParser()
    parser.feed(html)
    required_words = [word.casefold() for word in str(keyword).split() if word]
    results, seen = [], set()
    for raw in parser.results:
        title = " ".join("".join(raw["title"]).split())
        if not title or not all(word in title.casefold() for word in required_words):
            continue
        badge = " ".join("".join(raw["badge"]).split())
        if "🔞" in badge and "NAI" in badge:
            board_tab = "R18_NAI"
        elif badge == "NAI":
            board_tab = "NAI"
        else:
            continue
        source_url = _safe_url(raw["href"], base_url)
        match = re.match(r"^(https?://[^/]+/b/aiart/\d+)", source_url)
        if not match or match.group(1) in seen:
            continue
        source_url = match.group(1)
        seen.add(source_url)
        results.append({"source_url": source_url, "title": title, "board_tab": board_tab, "posted_at": raw["posted_at"]})
    return results


def extract_image_candidates(html, article_url):
    parser = _HTMLScan(); parser.feed(html)
    return _image_candidates_from_tags(parser.tags, article_url)


def _image_candidates_from_tags(tags, article_url):
    result = []
    def add(value):
        url = _safe_url(value, article_url)
        parsed = urlparse(url)
        if parsed.netloc.lower() == "ac.namu.la":
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query["type"] = "orig"
            url = urlunparse(parsed._replace(query=urlencode(query)))
        if url and url not in result: result.append(url)
    for tag, attrs in tags:
        if tag == "img":
            for key in ("data-original", "data-src", "src"): add(attrs.get(key))
        elif tag == "source":
            for part in (attrs.get("srcset") or "").split(","): add(part.strip().split(" ")[0])
        elif tag == "a" and re.search(r"\.(png|jpe?g|webp)(?:\?|$)", attrs.get("href", ""), re.I): add(attrs.get("href"))
    return result


def extract_article_data(html, article_url):
    parser = _HTMLScan(); parser.feed(html)
    full_text = "\n".join(part.strip() for part in parser.text if part.strip())
    content = _ArticleContentParser(); content.feed(html)
    text = "\n".join(content.text) if content.found else full_text
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if match: title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
    date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", full_text)
    tab = "R18_NAI" if "🔞 NAI" in full_text or "R18_NAI" in full_text else ("NAI" if re.search(r"\bNAI\b", full_text) else "")
    image_urls = _image_candidates_from_tags(content.tags, article_url) if content.found else extract_image_candidates(html, article_url)
    def article_stat(label):
        match = re.search(rf'<span[^>]*class=["\'][^"\']*head[^"\']*["\'][^>]*>\s*{label}\s*</span>\s*<span[^>]*class=["\'][^"\']*body[^"\']*["\'][^>]*>\s*([\d,]+)', html, re.I)
        return int(match.group(1).replace(",", "")) if match else None
    return {"source_url": article_url, "article_id": article_url.rstrip("/").split("/")[-1], "title": title, "posted_at": date_match.group(1) if date_match else "", "board_tab": tab, "author": "", "body_text": text, "image_urls": image_urls, "recommendation_count": article_stat("추천"), "view_count": article_stat("조회수")}


def extract_png_text_chunks(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"): return {}
    pos, result = 8, {}
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]; kind = data[pos+4:pos+8]; payload = data[pos+8:pos+8+length]; pos += 12 + length
        try:
            if kind == b"tEXt": key, value = payload.split(b"\0", 1); result[key.decode("latin1")] = value.decode("utf-8", "replace")
            elif kind == b"zTXt": key, rest = payload.split(b"\0", 1); result[key.decode("latin1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
            elif kind == b"iTXt":
                key, rest = payload.split(b"\0", 1); compressed = rest[0]; rest = rest[2:]; _, rest = rest.split(b"\0", 1); _, value = rest.split(b"\0", 1)
                result[key.decode("latin1")] = (zlib.decompress(value) if compressed else value).decode("utf-8", "replace")
        except (ValueError, zlib.error):
            continue
        if kind == b"IEND": break
    return result


def read_stealth_info(image_bytes):
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.mode != "RGBA":
                return None
            width, height = image.size
            alpha_bytes = image.getchannel("A").tobytes()
    except Exception:
        return None

    def get_bit(index):
        x, y = divmod(index, height)
        if x >= width:
            raise ValueError("stealth payload exceeds image bounds")
        return str(alpha_bytes[y * width + x] & 1)

    try:
        signature_bits = "".join(get_bit(index) for index in range(120))
        signature = bytes(int(signature_bits[index:index + 8], 2) for index in range(0, 120, 8)).decode("utf-8", "ignore")
        if signature != "stealth_pngcomp":
            return None
        length_bits = "".join(get_bit(index) for index in range(120, 152))
        payload_bit_length = int(length_bits, 2)
        if payload_bit_length <= 0 or payload_bit_length % 8 or 152 + payload_bit_length > width * height:
            return None
        payload_bits = "".join(get_bit(index) for index in range(152, 152 + payload_bit_length))
        compressed = bytes(int(payload_bits[index:index + 8], 2) for index in range(0, payload_bit_length, 8))
        return gzip.decompress(compressed).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError, zlib.error):
        return None


def _merge_raw_metadata(values, raw, allow_plain_prompt=True):
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("Comment"), str):
            nested = json.loads(parsed["Comment"])
            if isinstance(nested, dict):
                parsed = nested
        if isinstance(parsed, dict):
            values.update(parsed)
            return
    except (json.JSONDecodeError, TypeError):
        pass
    prompt_text = str(raw).split("Negative prompt:", 1)[0].strip()
    if allow_plain_prompt and prompt_text:
        values.setdefault("prompt", prompt_text)


def _is_novelai_metadata(values):
    if not isinstance(values, dict):
        return False
    if isinstance(values.get("v4_prompt"), dict):
        return True
    return bool(values.get("prompt")) and len(GENERATION_KEYS.intersection(values)) >= 2


def _extract_prompt_parts(values):
    v4_prompt = values.get("v4_prompt") if isinstance(values.get("v4_prompt"), dict) else {}
    caption = v4_prompt.get("caption") if isinstance(v4_prompt.get("caption"), dict) else {}
    base_prompt = str(caption.get("base_caption") or values.get("prompt") or values.get("prompts") or "")
    characters = []
    for entry in caption.get("char_captions", []) if isinstance(caption.get("char_captions"), list) else []:
        if isinstance(entry, dict) and entry.get("char_caption"):
            characters.append({
                "prompt": str(entry["char_caption"]),
                "centers": entry.get("centers") if isinstance(entry.get("centers"), list) else [],
            })
    v4_negative = values.get("v4_negative_prompt") if isinstance(values.get("v4_negative_prompt"), dict) else {}
    negative_caption = v4_negative.get("caption") if isinstance(v4_negative.get("caption"), dict) else {}
    negative_prompt = str(negative_caption.get("base_caption") or values.get("uc") or values.get("negative_prompt") or values.get("undesired_content") or "")
    return base_prompt, negative_prompt, characters


def extract_novelai_metadata(image_bytes, content_type=""):
    base = {"metadata_status": "no_metadata", "prompt": "", "base_prompt": "", "negative_prompt": "", "character_prompts": [], "seed": "", "sampler": "", "steps": None, "scale": None, "cfg_rescale": None, "noise_schedule": "", "model": "", "width": None, "height": None, "raw_metadata_json": "{}"}
    if not (image_bytes.startswith(b"\x89PNG") or "png" in content_type.lower()): return base
    chunks = extract_png_text_chunks(image_bytes)
    values = {}
    for key, raw in chunks.items():
        if key.lower() not in {"comment", "description", "software", "source", "parameters", "prompt", "uc"}: continue
        lowered_key = key.lower()
        if lowered_key == "uc":
            values["uc"] = raw
        else:
            _merge_raw_metadata(
                values,
                raw,
                allow_plain_prompt=lowered_key not in {"software", "source"},
            )
    stealth_raw = read_stealth_info(image_bytes)
    if stealth_raw:
        _merge_raw_metadata(values, stealth_raw)
    if not _is_novelai_metadata(values):
        return base
    def pick(*names):
        return next((values[name] for name in names if values.get(name) not in (None, "")), "")
    prompt, negative, characters = _extract_prompt_parts(values)
    if not prompt and not negative: return base
    base.update({"metadata_status": "ok", "prompt": str(prompt), "base_prompt": str(prompt), "negative_prompt": str(negative), "character_prompts": characters, "seed": str(pick("seed")), "sampler": str(pick("sampler")), "steps": pick("steps") or None, "scale": pick("scale") or None, "cfg_rescale": pick("cfg_rescale") or None, "noise_schedule": str(pick("noise_schedule")), "model": str(pick("model")), "width": pick("width") or None, "height": pick("height") or None, "raw_metadata_json": json.dumps(values, ensure_ascii=False)})
    return base


def revalidate_stored_metadata(db_path):
    with closing(_connect(db_path)) as conn, conn:
        for table in ("arca_style_images", "arca_style_items"):
            rows = conn.execute(f"SELECT id,raw_metadata_json FROM {table} WHERE metadata_status='ok'").fetchall()
            for row in rows:
                try:
                    values = json.loads(row["raw_metadata_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    values = {}
                if not _is_novelai_metadata(values):
                    assignments = "metadata_status='no_metadata',prompt='',negative_prompt=''"
                    if table == "arca_style_images":
                        assignments += ",base_prompt='',character_prompts_json='[]'"
                    conn.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (row["id"],))
                    continue
                prompt, negative, characters = _extract_prompt_parts(values)
                if table == "arca_style_images":
                    conn.execute(
                        "UPDATE arca_style_images SET prompt=?,base_prompt=?,negative_prompt=?,character_prompts_json=? WHERE id=?",
                        (prompt, prompt, negative, json.dumps(characters, ensure_ascii=False), row["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE arca_style_items SET prompt=?,negative_prompt=? WHERE id=?",
                        (prompt, negative, row["id"]),
                    )


def parse_body_prompt_fallback(text):
    prompt = re.search(r"(?:^|\n)\s*(?:prompt|프롬프트)\s*:\s*(.+)", text or "", re.I)
    uc = re.search(r"(?:^|\n)\s*(?:uc|negative prompt|네거티브)\s*:\s*(.+)", text or "", re.I)
    return {"prompt": prompt.group(1).strip() if prompt else "", "negative_prompt": uc.group(1).strip() if uc else ""}


def split_prompt_tags(prompt):
    tags, current, stack = [], [], []
    pairs = {"{": "}", "[": "]", "(": ")"}
    for char in str(prompt or ""):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if char == "," and not stack:
            value = "".join(current).strip()
            if value:
                tags.append(value)
            current = []
        else:
            current.append(char)
    value = "".join(current).strip()
    if value:
        tags.append(value)
    return tags


QUALITY_TAG_ALIASES = {
    "quality": "quality",
    "masterpiece": "masterpiece",
    "best quality": "best quality",
    "amazing quality": "amazing quality",
    "high quality": "high quality",
    "very aesthetic": "very aesthetic",
    "great aesthetic": "great aesthetic",
    "aesthetic": "aesthetic",
    "highres": "highres",
    "hires": "highres",
    "high res": "highres",
    "absurdres": "absurdres",
    "incredibly absurdres": "incredibly absurdres",
    "newest": "newest",
    "detailed": "detailed",
    "highly detailed": "highly detailed",
    "ultra detailed": "ultra detailed",
    "very detailed": "very detailed",
    "extremely detailed": "extremely detailed",
    "high detail": "high detail",
    "hyper detail": "hyper detail",
}
CHARACTER_CONTENT_TAGS = {
    "solo", "solo focus", "group", "couple", "multiple girls", "multiple boys",
    "female", "male", "woman", "man", "girl", "boy", "child", "adult", "teenager",
    "full body", "upper body", "lower body", "cowboy shot", "close-up", "headshot", "portrait",
    "feet out of frame", "cropped torso", "from above", "from below", "from behind", "from side",
    "looking at viewer", "looking away", "looking back", "eye contact", "profile",
    "standing", "sitting", "kneeling", "lying", "walking", "running", "jumping", "squatting",
    "arms up", "arms behind back", "arms crossed", "crossed legs", "spread legs", "hand on hip",
    "smile", "frown", "open mouth", "closed mouth", "blush", "tears", "expressionless",
    "school uniform", "military uniform", "maid", "nude", "topless", "bottomless", "barefoot",
}
CHARACTER_CONTENT_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"^(?:\d+|multiple)[ _]?(?:girls?|boys?|women|men|people|persons?|others?)$",
    r"^(?:young|old|mature|petite|tall|short|fat|thin|slim|muscular)\b",
    r"\b(?:hair|bangs|eyes?|eyebrows?|eyelashes|face|head|ears?|nose|mouth|lips|teeth|tongue)\b",
    r"\b(?:neck|shoulders?|arms?|elbows?|wrists?|hands?|fingers?|chest|breasts?|waist|stomach|navel)\b",
    r"\b(?:hips?|buttocks|thighs?|legs?|knees?|ankles?|feet|toes?|skin|body|torso)\b",
    r"\b(?:dress|skirt|shirt|blouse|jacket|coat|pants|shorts|uniform|swimsuit|underwear|bra|panties)\b",
    r"\b(?:socks?|stockings|gloves?|boots?|shoes?|heels?|hat|cap|ribbon|bowtie|necktie|collar)\b",
    r"\b(?:standing|sitting|kneeling|lying|walking|running|jumping|leaning|reaching|holding|posing)\b",
    r"^(?:view|viewing|focus)\b|\b(?:shot|view|focus|pose)$",
))
PROMPT_PRESET_INDEX_VERSION = "2"
_ARTIST_TAG_PATTERN = re.compile(r"^(?:artist|artists)\s*:\s*(.+)$", re.I)
_WEIGHT_PREFIX_PATTERN = re.compile(r"^(?:[+-]?\d+(?:\.\d+)?)?::\s*")
_WEIGHT_SUFFIX_PATTERN = re.compile(r"::(?:\s*[+-]?\d+(?:\.\d+)?)?$")
_SINGLE_WEIGHT_SUFFIX_PATTERN = re.compile(r":\s*[+-]?\d+(?:\.\d+)?$")
_EXPLICIT_WEIGHT_PREFIX_PATTERN = re.compile(r"[+-]?\d+(?:\.\d+)?::")
_EXPLICIT_WEIGHT_GROUP_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)::([\s\S]*)::$")
_EXPLICIT_WEIGHT_PREFIX_ONLY_PATTERN = re.compile(r"^([+-]?\d+(?:\.\d+)?)::([\s\S]+)$")
_NUMERIC_TAG_SUFFIX_PATTERN = re.compile(r"^(.+?):\s*([+-]?\d+(?:\.\d+)?)$")
WEIGHT_RANGE_LABELS = (
    "0 미만", "0.00–0.49", "0.50–0.79", "0.80–0.99", "1.00",
    "1.01–1.19", "1.20–1.49", "1.50–1.99", "2.00 이상",
)


def _unwrap_prompt_group(value):
    value = str(value or "").strip()
    pairs = {"{": "}", "[": "]", "(": ")"}
    if len(value) < 2 or value[0] not in pairs or value[-1] != pairs[value[0]]:
        return value
    stack = []
    for index, char in enumerate(value):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and index < len(value) - 1:
            return value
    return value[1:-1].strip() if not stack else value


def _expanded_prompt_tags(prompt):
    for tag in split_prompt_tags(prompt):
        inner = _unwrap_prompt_group(tag)
        if inner != tag:
            yield from _expanded_prompt_tags(inner)
        else:
            yield tag


def _split_weighted_prompt_units(prompt):
    units, current, stack = [], [], []
    pairs = {"{": "}", "[": "]", "(": ")"}
    explicit_weight = False
    text = str(prompt or "")
    index = 0
    while index < len(text):
        if explicit_weight and text.startswith("::", index):
            current.append("::")
            explicit_weight = False
            index += 2
            continue
        if not explicit_weight:
            match = _EXPLICIT_WEIGHT_PREFIX_PATTERN.match(text, index)
            previous = text[index - 1] if index else ""
            closing = text.find("::", match.end()) if match else -1
            if match and closing >= 0 and (not previous or not (previous.isalnum() or previous in "_.")):
                current.append(match.group(0))
                explicit_weight = True
                index = match.end()
                continue
            char = text[index]
            if char in pairs:
                stack.append(pairs[char])
            elif stack and char == stack[-1]:
                stack.pop()
            elif char == "," and not stack:
                value = "".join(current).strip()
                if value:
                    units.append(value)
                current = []
                index += 1
                continue
        current.append(text[index])
        index += 1
    value = "".join(current).strip()
    if value:
        units.append(value)
    return units


def _outer_prompt_group(value):
    value = str(value or "").strip()
    pairs = {"{": "}", "[": "]", "(": ")"}
    if len(value) < 2 or value[0] not in pairs or value[-1] != pairs[value[0]]:
        return None
    stack = []
    for index, char in enumerate(value):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack and index < len(value) - 1:
            return None
    if stack:
        return None
    factor = 1.05 if value[0] == "{" else 1 / 1.05 if value[0] == "[" else 1.0
    return value[1:-1].strip(), factor


def parse_weighted_prompt_tags(prompt, base_weight=1.0):
    parsed = []

    def visit(value, inherited_weight):
        for unit in _split_weighted_prompt_units(value):
            wrapper = _outer_prompt_group(unit)
            if wrapper:
                inner, factor = wrapper
                visit(inner, inherited_weight * factor)
                continue
            explicit = _EXPLICIT_WEIGHT_GROUP_PATTERN.fullmatch(unit)
            if explicit:
                visit(explicit.group(2), inherited_weight * float(explicit.group(1)))
                continue
            prefix_only = _EXPLICIT_WEIGHT_PREFIX_ONLY_PATTERN.fullmatch(unit)
            if prefix_only:
                visit(prefix_only.group(2), inherited_weight * float(prefix_only.group(1)))
                continue
            weight = inherited_weight
            numeric_suffix = _NUMERIC_TAG_SUFFIX_PATTERN.fullmatch(unit)
            if numeric_suffix:
                unit = numeric_suffix.group(1).strip()
                weight *= float(numeric_suffix.group(2))
            unit = _strip_prompt_weight(unit)
            if unit:
                parsed.append({"tag": unit, "weight": round(weight, 6), "order": len(parsed)})

    visit(prompt, float(base_weight))
    return parsed


def _weight_range_label(weight):
    value = float(weight)
    if value < 0:
        return WEIGHT_RANGE_LABELS[0]
    if value < 0.5:
        return WEIGHT_RANGE_LABELS[1]
    if value < 0.8:
        return WEIGHT_RANGE_LABELS[2]
    if value < 1.0 - 1e-6:
        return WEIGHT_RANGE_LABELS[3]
    if abs(value - 1.0) <= 1e-6:
        return WEIGHT_RANGE_LABELS[4]
    if value < 1.2:
        return WEIGHT_RANGE_LABELS[5]
    if value < 1.5:
        return WEIGHT_RANGE_LABELS[6]
    if value < 2.0:
        return WEIGHT_RANGE_LABELS[7]
    return WEIGHT_RANGE_LABELS[8]


def _weight_summary(weights):
    values = [float(value) for value in weights]
    counts = {label: 0 for label in WEIGHT_RANGE_LABELS}
    for value in values:
        counts[_weight_range_label(value)] += 1
    total = len(values)
    bins = [
        {"label": label, "count": counts[label], "percentage": round(counts[label] * 100 / total, 1) if total else 0.0}
        for label in WEIGHT_RANGE_LABELS
    ]
    dominant = max(bins, key=lambda entry: entry["count"])["label"] if total else ""
    return {
        "count": total,
        "average": round(sum(values) / total, 3) if total else None,
        "median": round(float(median(values)), 3) if total else None,
        "min": round(min(values), 3) if total else None,
        "max": round(max(values), 3) if total else None,
        "dominant_range": dominant,
        "bins": bins,
    }


def _strip_prompt_weight(tag):
    value = _normalized_tag(tag)
    value = _WEIGHT_PREFIX_PATTERN.sub("", value)
    value = _WEIGHT_SUFFIX_PATTERN.sub("", value)
    return _SINGLE_WEIGHT_SUFFIX_PATTERN.sub("", value).strip()


def _canonical_artist_tag(tag):
    match = _ARTIST_TAG_PATTERN.fullmatch(_strip_prompt_weight(tag))
    if not match:
        return ""
    artist = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
    return f"artist:{artist}" if artist else ""


def _canonical_quality_tag(tag):
    return QUALITY_TAG_ALIASES.get(_strip_prompt_weight(tag), "")


def _normalized_tag(tag):
    value = re.sub(r"\s+", " ", str(tag).strip()).casefold()
    return re.sub(r"(?<=\S)::?\s*([+-]?\d+(?:\.\d+)?)$", r":\1", value)


def weighted_tag_similarity(left, right):
    left_keys, right_keys = set(left), set(right)
    keys = left_keys | right_keys
    if not keys:
        return 0.0
    weight = lambda tag: 0.25 if TRANSIENT_TAG.match(tag) else 1.0
    return sum(weight(tag) for tag in left_keys & right_keys) / sum(weight(tag) for tag in keys)


def build_style_groups(images):
    prepared = []
    for image in images:
        item = dict(image)
        base_tags = split_prompt_tags(item.get("base_prompt") or item.get("prompt"))
        negative_tags = split_prompt_tags(item.get("negative_prompt"))
        item["_base_map"] = {_normalized_tag(tag): tag for tag in base_tags}
        item["_negative_map"] = {_normalized_tag(tag): tag for tag in negative_tags}
        item.setdefault("character_prompts", [])
        prepared.append(item)
    adjacency = [set() for _ in prepared]
    for left_index in range(len(prepared)):
        for right_index in range(left_index + 1, len(prepared)):
            score = weighted_tag_similarity(prepared[left_index]["_base_map"], prepared[right_index]["_base_map"])
            if score >= STYLE_SIMILARITY_THRESHOLD:
                adjacency[left_index].add(right_index)
                adjacency[right_index].add(left_index)
    groups, visited = [], set()
    for start in range(len(prepared)):
        if start in visited:
            continue
        pending, indexes = [start], []
        while pending:
            index = pending.pop()
            if index in visited:
                continue
            visited.add(index)
            indexes.append(index)
            pending.extend(adjacency[index] - visited)
        indexes.sort()
        members = [prepared[index] for index in indexes]
        common_base = set(members[0]["_base_map"])
        common_negative = set(members[0]["_negative_map"])
        for member in members[1:]:
            common_base &= set(member["_base_map"])
            common_negative &= set(member["_negative_map"])
        rendered = []
        for member in members:
            clean = {key: value for key, value in member.items() if not key.startswith("_")}
            clean["different_base_tags"] = [value for key, value in member["_base_map"].items() if key not in common_base]
            clean["different_negative_tags"] = [value for key, value in member["_negative_map"].items() if key not in common_negative]
            rendered.append(clean)
        groups.append({
            "singleton": len(rendered) == 1,
            "representative_image_id": rendered[0].get("id"),
            "common_base_tags": [value for key, value in members[0]["_base_map"].items() if key in common_base],
            "common_negative_tags": [value for key, value in members[0]["_negative_map"].items() if key in common_negative],
            "images": rendered,
        })
    return groups


def discover_category_params(session):
    html = fetch_html(session, urljoin(ARCA_BASE_URL, ARCA_BOARD_PATH))
    parser = _CategoryLinkParser(); parser.feed(html)
    result = {}
    for href, text in parser.links:
        normalized = re.sub(r"\s+", " ", text).strip()
        tab = "R18_NAI" if "🔞" in normalized and "NAI" in normalized.upper() else "NAI" if normalized.upper() == "NAI" else ""
        if not tab:
            continue
        params = dict(parse_qsl(urlparse(_safe_url(href, ARCA_BASE_URL)).query))
        if params:
            result[tab] = params
    return result


def build_search_urls(keyword, tabs, page, category_params=None):
    if isinstance(category_params, dict):
        bases = [category_params[tab] for tab in tabs if tab in category_params]
    else:
        bases = category_params or [{}]
    urls = []
    for params in bases:
        query = dict(params); query.update({"target": "title", "keyword": keyword, "p": page})
        urls.append(urlunparse(("https", "arca.live", ARCA_BOARD_PATH, "", urlencode(query), "")))
    return urls


def _search_item_date(item):
    try:
        return date.fromisoformat(str(item.get("posted_at") or ""))
    except (TypeError, ValueError):
        return None


def _search_page_date_bounds(items):
    dates = [posted_at for posted_at in (_search_item_date(item) for item in items) if posted_at]
    return (min(dates), max(dates)) if dates else (None, None)


def _locate_archive_page(fetch_page, end):
    """Find the first newest-to-oldest result page that might contain ``end``."""
    first_items = fetch_page(1)
    oldest, _ = _search_page_date_bounds(first_items)
    if not first_items or oldest is None or oldest <= end:
        return 1

    lower_page, upper_page = 1, 2
    while upper_page <= MAX_ARCHIVE_SEARCH_PAGE:
        items = fetch_page(upper_page)
        oldest, _ = _search_page_date_bounds(items)
        if not items or oldest is None or oldest <= end:
            break
        lower_page, upper_page = upper_page, upper_page * 2
    else:
        return MAX_ARCHIVE_SEARCH_PAGE

    while lower_page + 1 < upper_page:
        middle_page = (lower_page + upper_page) // 2
        items = fetch_page(middle_page)
        oldest, _ = _search_page_date_bounds(items)
        if not items or oldest is None or oldest <= end:
            upper_page = middle_page
        else:
            lower_page = middle_page
    return upper_page


def fetch_html(session, url):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def _clone_arca_session(session):
    cloned = create_arca_session()
    headers = getattr(session, "headers", None)
    if headers:
        cloned.headers.update(dict(headers))
    for cookie in getattr(session, "cookies", ()):
        cloned.cookies.set_cookie(copy.copy(cookie))
    return cloned


def _fetch_article_htmls(session, search_items):
    def fetch_one(search_item):
        worker_session = _clone_arca_session(session)
        started = time.monotonic()
        try:
            return search_item, fetch_html(worker_session, search_item["source_url"]), time.monotonic() - started
        except requests.RequestException:
            return search_item, None, time.monotonic() - started
        finally:
            close = getattr(worker_session, "close", None)
            if close:
                close()

    if not search_items:
        return
    workers = min(COLLECTION_WORKERS, len(search_items))
    pending_items = iter(search_items)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending = {}
        for _ in range(workers):
            search_item = next(pending_items, None)
            if search_item is None:
                break
            pending[executor.submit(fetch_one, search_item)] = search_item
        while pending:
            future = next(as_completed(tuple(pending)))
            pending.pop(future)
            yield future.result()
            search_item = next(pending_items, None)
            if search_item is not None:
                pending[executor.submit(fetch_one, search_item)] = search_item


def _obvious_non_png_content_type(image_url):
    return NON_PNG_IMAGE_TYPES.get(Path(urlparse(str(image_url or "")).path).suffix.lower(), "")


def download_image(session, image_url):
    response = session.get(image_url, timeout=IMAGE_TIMEOUT, stream=True)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ArcaCollectorError("이미지 응답이 아닙니다.")
        if content_type != "image/png":
            return None, content_type
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES: raise ArcaCollectorError("이미지 크기 제한을 초과했습니다.")
            chunks.append(chunk)
        return b"".join(chunks), content_type
    finally:
        close = getattr(response, "close", None)
        if close:
            close()


def save_image_bytes(image_dir, image_url, image_bytes, content_type):
    image_dir = Path(image_dir); image_dir.mkdir(parents=True, exist_ok=True)
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".img")
    name = hashlib.sha256(image_url.encode()).hexdigest() + ext
    (image_dir / name).write_bytes(image_bytes)
    return name


def _row(row): return dict(row) if row else None


def count_style_groups_for_item(db_path, item_id):
    with closing(_connect(db_path)) as conn:
        rows = [_row(row) for row in conn.execute(
            "SELECT id,prompt,base_prompt,negative_prompt,character_prompts_json FROM arca_style_images WHERE item_id=? AND TRIM(COALESCE(base_prompt,prompt,''))<>'' ORDER BY id",
            (item_id,),
        )]
    for image in rows:
        try:
            characters = json.loads(image.get("character_prompts_json") or "[]")
        except json.JSONDecodeError:
            characters = []
        image["character_prompts"] = characters if isinstance(characters, list) else []
    return len(build_style_groups(rows))


def _arca_style_list_query(filters):
    filters = filters or {}; clauses, args = [
        "TRIM(prompt) <> ''",
        "metadata_status = 'ok'",
        "title LIKE '%그림체%'",
        "title LIKE '%공유%'",
        "board_tab IN ('NAI','R18_NAI')",
    ], []
    title_clauses = clauses[2:4]
    del clauses[2:4]
    clauses.append(
        f"(({title_clauses[0]} AND {title_clauses[1]}) OR EXISTS ("
        "SELECT 1 FROM arca_collection_jobs direct_job "
        "WHERE json_extract(direct_job.request_json,'$.source_url')=arca_style_items.source_url))"
    )
    if filters.get("q"): clauses.append("(title LIKE ? OR prompt LIKE ? OR source_url LIKE ?)"); args += [f"%{filters['q']}%"] * 3
    if filters.get("tab") and filters["tab"] != "all": clauses.append("board_tab=?"); args.append(filters["tab"])
    if filters.get("metadata") and filters["metadata"] != "all": clauses.append("metadata_status=?"); args.append(filters["metadata"])
    recommendation_min = filters.get("recommendation_min")
    if recommendation_min not in (None, ""):
        try:
            recommendation_min = int(recommendation_min)
        except (TypeError, ValueError):
            raise ArcaCollectorError("최소 추천수는 0 이상의 정수여야 합니다.")
        if recommendation_min < 0:
            raise ArcaCollectorError("최소 추천수는 0 이상의 정수여야 합니다.")
        clauses.append("recommendation_count IS NOT NULL AND recommendation_count>=?")
        args.append(recommendation_min)
    sort = filters.get("sort") or "posted_desc"
    if sort not in {"posted_desc", "posted_asc", "recommend_desc", "views_desc"}:
        raise ArcaCollectorError("아카라이브 날짜 정렬 값을 확인해 주세요.")
    if sort in {"posted_desc", "posted_asc"}:
        direction = "DESC" if sort == "posted_desc" else "ASC"
        order_sql = f"CASE WHEN TRIM(COALESCE(posted_at,''))='' THEN 1 ELSE 0 END ASC,posted_at {direction},id DESC"
    else:
        column = "recommendation_count" if sort == "recommend_desc" else "view_count"
        order_sql = f"CASE WHEN {column} IS NULL THEN 1 ELSE 0 END ASC,{column} DESC,id DESC"
    return " WHERE " + " AND ".join(clauses) if clauses else "", args, order_sql


def list_arca_styles(db_path, filters=None):
    filters = filters or {}
    where_sql, args, order_sql = _arca_style_list_query(filters)
    try:
        limit = min(max(int(filters.get("limit", 200)), 1), 500)
        offset = max(int(filters.get("offset", 0)), 0)
    except (TypeError, ValueError):
        raise ArcaCollectorError("목록 표시 개수와 위치를 확인해 주세요.")
    sql = f"SELECT * FROM arca_style_items{where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?"
    with closing(_connect(db_path)) as conn:
        items = [_row(row) for row in conn.execute(sql, (*args, limit, offset))]
        grouped_images = {item["id"]: [] for item in items}
        if items:
            placeholders = ",".join("?" for _ in items)
            rows = conn.execute(
                f"SELECT item_id,id,prompt,base_prompt,negative_prompt,character_prompts_json FROM arca_style_images "
                f"WHERE item_id IN ({placeholders}) AND TRIM(COALESCE(base_prompt,prompt,''))<>'' ORDER BY item_id,id",
                tuple(item["id"] for item in items),
            ).fetchall()
            for row in rows:
                image = _row(row)
                try:
                    characters = json.loads(image.get("character_prompts_json") or "[]")
                except json.JSONDecodeError:
                    characters = []
                image["character_prompts"] = characters if isinstance(characters, list) else []
                grouped_images[image["item_id"]].append(image)
    for item in items:
        item["style_group_count"] = len(build_style_groups(grouped_images[item["id"]]))
    return items


def get_arca_style_page(db_path, filters=None):
    filters = dict(filters or {})
    try:
        page = max(int(filters.get("page", 1)), 1)
        per_page = min(max(int(filters.get("per_page", 50)), 1), 200)
    except (TypeError, ValueError):
        raise ArcaCollectorError("페이지와 페이지당 표시 개수를 확인해 주세요.")
    where_sql, args, _ = _arca_style_list_query(filters)
    with closing(_connect(db_path)) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM arca_style_items{where_sql}", tuple(args)).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    filters.update({"limit": per_page, "offset": (page - 1) * per_page})
    return {
        "items": list_arca_styles(db_path, filters),
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


def _recommendation_summary(values):
    numbers = [int(value) for value in values if value is not None]
    return {
        "recommendation_sample_count": len(numbers),
        "average_recommendations": round(sum(numbers) / len(numbers), 1) if numbers else None,
        "median_recommendations": round(float(median(numbers)), 1) if numbers else None,
        "max_recommendations": max(numbers) if numbers else None,
    }


def _statistics_entries(counts, total, weights_by_tag, representatives=None, recommendations_by_tag=None):
    representatives = representatives or {}
    recommendations_by_tag = recommendations_by_tag or {}
    entries = []
    for tag, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0])):
        weights = _weight_summary(weights_by_tag.get(tag, []))
        entry = {
            "tag": tag,
            "count": count,
            "percentage": round(count * 100 / total, 1) if total else 0.0,
            "average_weight": weights["average"],
            "median_weight": weights["median"],
            "max_weight": weights["max"],
            "dominant_weight_range": weights["dominant_range"],
            **_recommendation_summary(recommendations_by_tag.get(tag, [])),
        }
        if tag in representatives:
            entry["representative_image"] = representatives[tag]
        entries.append(entry)
    return entries


def _combination_entries(counts, total, representatives=None, recommendations=None):
    representatives = representatives or {}
    recommendations = recommendations or {}
    return [
        {
            "tags": list(tags), "size": len(tags), "count": count,
            "percentage": round(count * 100 / total, 1) if total else 0.0,
            **_recommendation_summary(recommendations.get(tags, [])),
            **({"representative_image": representatives[tags]} if tags in representatives else {}),
        }
        for tags, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


def _statistics_image_rows(db_path, filters=None):
    filters = filters or {}
    clauses = [
        "item.metadata_status = 'ok'",
        "TRIM(item.prompt) <> ''",
        "item.board_tab IN ('NAI','R18_NAI')",
        "image.metadata_status = 'ok'",
        "TRIM(COALESCE(NULLIF(image.base_prompt,''),image.prompt)) <> ''",
        "((item.title LIKE '%그림체%' AND item.title LIKE '%공유%') OR EXISTS ("
        "SELECT 1 FROM arca_collection_jobs direct_job "
        "WHERE json_extract(direct_job.request_json,'$.source_url')=item.source_url))",
    ]
    args = []
    if filters.get("q"):
        clauses.append("(item.title LIKE ? OR item.prompt LIKE ? OR item.source_url LIKE ?)")
        args.extend([f"%{filters['q']}%"] * 3)
    if filters.get("tab") and filters["tab"] != "all":
        clauses.append("item.board_tab=?")
        args.append(filters["tab"])
    recommendation_min = filters.get("recommendation_min")
    recommendation_max = filters.get("recommendation_max")
    try:
        recommendation_min = int(recommendation_min) if recommendation_min not in (None, "") else None
        recommendation_max = int(recommendation_max) if recommendation_max not in (None, "") else None
    except (TypeError, ValueError):
        raise ArcaCollectorError("추천수 범위는 0 이상의 숫자여야 합니다.")
    if (recommendation_min is not None and recommendation_min < 0) or (recommendation_max is not None and recommendation_max < 0):
        raise ArcaCollectorError("추천수 범위는 0 이상의 숫자여야 합니다.")
    if recommendation_min is not None and recommendation_max is not None and recommendation_min > recommendation_max:
        raise ArcaCollectorError("최소 추천수는 최대 추천수보다 클 수 없습니다.")
    if recommendation_min is not None:
        clauses.append("item.recommendation_count IS NOT NULL AND item.recommendation_count>=?")
        args.append(recommendation_min)
    if recommendation_max is not None:
        clauses.append("item.recommendation_count IS NOT NULL AND item.recommendation_count<=?")
        args.append(recommendation_max)
    sql = (
        "SELECT image.id,image.item_id,image.image_url,image.image_path,item.title,item.source_url,item.posted_at,item.board_tab,item.recommendation_count,"
        "COALESCE(NULLIF(image.base_prompt,''),image.prompt) AS base_prompt,"
        "COALESCE(NULLIF(image.negative_prompt,''),item.negative_prompt) AS negative_prompt "
        "FROM arca_style_images image JOIN arca_style_items item ON item.id=image.item_id "
        "WHERE " + " AND ".join(clauses)
    )
    with closing(_connect(db_path)) as conn:
        return conn.execute(sql, args).fetchall()


def _quality_tag_sequence(prompt):
    sequence = []
    for parsed in parse_weighted_prompt_tags(prompt):
        quality = _canonical_quality_tag(parsed["tag"])
        if quality and quality not in sequence:
            sequence.append(quality)
    return sequence


def _format_parsed_prompt_tag(parsed):
    tag = re.sub(r"\s+", " ", str(parsed["tag"] or "")).strip()
    weight = float(parsed["weight"])
    return tag if abs(weight - 1.0) <= 1e-6 else f"{weight:g}::{tag}::"


def _is_character_content_tag(tag):
    value = re.sub(r"\s+", " ", str(tag or "").replace("_", " ")).strip().casefold()
    return value in CHARACTER_CONTENT_TAGS or any(pattern.search(value) for pattern in CHARACTER_CONTENT_PATTERNS)


def _prompt_preset_parts(prompt):
    included = []
    excluded = []
    seen = set()
    for parsed in parse_weighted_prompt_tags(prompt):
        if _canonical_artist_tag(parsed["tag"]):
            continue
        formatted = _format_parsed_prompt_tag(parsed)
        key = _normalized_tag(formatted)
        if not formatted or key in seen:
            continue
        seen.add(key)
        if _is_character_content_tag(parsed["tag"]):
            excluded.append({"tag": str(parsed["tag"]).strip(), "prompt": formatted})
        else:
            included.append(formatted)
    return ", ".join(included), excluded


def _prompt_preset_source_hash(row):
    source = "\0".join((
        PROMPT_PRESET_INDEX_VERSION,
        str(row["base_prompt"] or ""),
        str(row["negative_prompt"] or ""),
        str(row["recommendation_count"] if row["recommendation_count"] is not None else ""),
    ))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _indexed_prompt_preset_rows(db_path):
    source_rows = _statistics_image_rows(db_path)
    indexed_rows = []
    with closing(_connect(db_path)) as conn, conn:
        existing = {
            row["image_id"]: row
            for row in conn.execute("SELECT * FROM arca_prompt_preset_index")
        }
        upserts = []
        for row in source_rows:
            image_id = int(row["id"])
            source_hash = _prompt_preset_source_hash(row)
            cached = existing.pop(image_id, None)
            try:
                if cached is None or cached["source_hash"] != source_hash:
                    raise ValueError
                excluded_tags = json.loads(cached["excluded_tags_json"] or "[]")
                parsed_artists = json.loads(cached["artists_json"] or "[]")
                if not isinstance(excluded_tags, list) or not isinstance(parsed_artists, list):
                    raise ValueError
                base_prompt = cached["base_prompt"]
                negative_prompt = cached["negative_prompt"]
            except (json.JSONDecodeError, TypeError, ValueError):
                base_prompt, excluded_tags = _prompt_preset_parts(row["base_prompt"])
                negative_prompt = str(row["negative_prompt"] or "").strip()
                parsed_artists = sorted({
                    artist for parsed in parse_weighted_prompt_tags(row["base_prompt"])
                    if (artist := _canonical_artist_tag(parsed["tag"]))
                })
                upserts.append((
                    image_id, source_hash, base_prompt, negative_prompt,
                    json.dumps(excluded_tags, ensure_ascii=False),
                    json.dumps(parsed_artists, ensure_ascii=False),
                    row["recommendation_count"],
                ))
            indexed_rows.append({
                "image_id": image_id,
                "base_prompt": base_prompt,
                "negative_prompt": negative_prompt,
                "excluded_tags": excluded_tags,
                "parsed_artists": set(parsed_artists),
                "recommendation_count": row["recommendation_count"],
            })
        if upserts:
            conn.executemany(
                """INSERT INTO arca_prompt_preset_index(
                    image_id,source_hash,base_prompt,negative_prompt,excluded_tags_json,artists_json,recommendation_count
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(image_id) DO UPDATE SET
                    source_hash=excluded.source_hash,base_prompt=excluded.base_prompt,
                    negative_prompt=excluded.negative_prompt,excluded_tags_json=excluded.excluded_tags_json,
                    artists_json=excluded.artists_json,recommendation_count=excluded.recommendation_count""",
                upserts,
            )
        if existing:
            conn.executemany(
                "DELETE FROM arca_prompt_preset_index WHERE image_id=?",
                ((image_id,) for image_id in existing),
            )
    return indexed_rows


def get_shared_style_artist_pool(db_path):
    counts = defaultdict(int)
    for row in _indexed_prompt_preset_rows(db_path):
        for artist in row["parsed_artists"]:
            name = artist.split(":", 1)[1].strip() if artist.startswith("artist:") else artist.strip()
            if name:
                counts[name] += 1
    return [
        {"artist": artist, "sample_count": count}
        for artist, count in sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    ]


def get_style_maker_prompt_presets(db_path, artists=None, limit=30):
    if not isinstance(artists, (list, tuple)):
        raise ArcaCollectorError("작가 목록을 확인해 주세요.")
    try:
        limit = min(max(int(limit), 1), 50)
    except (TypeError, ValueError):
        raise ArcaCollectorError("추천 프롬프트 개수는 숫자여야 합니다.")

    selected_artists = set()
    for value in artists:
        if not isinstance(value, str):
            raise ArcaCollectorError("작가 이름은 문자열이어야 합니다.")
        canonical = _canonical_artist_tag(value if value.casefold().startswith("artist:") else f"artist:{value}")
        if canonical:
            selected_artists.add(canonical)

    grouped = {}
    for row in _indexed_prompt_preset_rows(db_path):
        negative_prompt = row["negative_prompt"]
        base_prompt = row["base_prompt"]
        excluded_tags = row["excluded_tags"]
        if not base_prompt or not negative_prompt:
            continue
        parsed_artists = row["parsed_artists"]
        matched = tuple(sorted(selected_artists.intersection(parsed_artists)))
        excluded_key = tuple(item["prompt"] for item in excluded_tags)
        key = (base_prompt, negative_prompt, excluded_key)
        entry = grouped.setdefault(key, {
            "base_prompt": base_prompt,
            "quality_prompt": base_prompt,
            "negative_prompt": negative_prompt,
            "excluded_tags": excluded_tags,
            "sample_count": 0,
            "matched_artists": set(),
            "recommendations": [],
        })
        entry["sample_count"] += 1
        entry["matched_artists"].update(matched)
        if row["recommendation_count"] is not None:
            entry["recommendations"].append(int(row["recommendation_count"]))

    presets = []
    for (base_prompt, negative_prompt, excluded_key), entry in grouped.items():
        recommendations = entry.pop("recommendations")
        matched_artists = sorted(entry["matched_artists"])
        presets.append({
            "key": hashlib.sha256(f"{base_prompt}\0{negative_prompt}\0{excluded_key}".encode("utf-8")).hexdigest()[:16],
            "base_prompt": base_prompt,
            "quality_prompt": base_prompt,
            "negative_prompt": negative_prompt,
            "excluded_tags": entry["excluded_tags"],
            "sample_count": entry["sample_count"],
            "matched_artists": matched_artists,
            "match_count": len(matched_artists),
            "average_recommendations": round(sum(recommendations) / len(recommendations), 1) if recommendations else None,
        })
    presets.sort(key=lambda entry: (
        -entry["match_count"],
        -(entry["average_recommendations"] if entry["average_recommendations"] is not None else -1),
        -entry["sample_count"],
        entry["base_prompt"],
    ))
    return {"presets": presets[:limit], "selected_artist_count": len(selected_artists)}


def _statistics_representative(row, weight=None):
    image = {
        "id": row["id"], "image_url": row["image_url"], "image_path": row["image_path"],
        "title": row["title"], "source_url": row["source_url"], "posted_at": row["posted_at"],
        "prompt": row["base_prompt"], "recommendation_count": row["recommendation_count"],
    }
    if weight is not None:
        image["weight"] = round(float(weight), 3)
    return image


def get_arca_style_statistics(db_path, filters=None):
    artist_counts, quality_counts, post_ids = defaultdict(int), defaultdict(int), set()
    artist_weights, quality_weights = defaultdict(list), defaultdict(list)
    sequence_counts, bundle_counts, edge_counts = defaultdict(int), defaultdict(int), defaultdict(int)
    artist_recommendations, quality_recommendations = defaultdict(list), defaultdict(list)
    sequence_recommendations, bundle_recommendations = defaultdict(list), defaultdict(list)
    artist_representatives, quality_representatives, sequence_representatives = {}, {}, {}
    analyzed_image_count = analyzed_tag_count = images_with_artist = images_with_quality = 0
    for row in _statistics_image_rows(db_path, filters):
        analyzed_image_count += 1
        post_ids.add(row["item_id"])
        artists, quality_tags = defaultdict(list), defaultdict(list)
        quality_sequence = []
        for parsed in parse_weighted_prompt_tags(row["base_prompt"]):
            analyzed_tag_count += 1
            artist = _canonical_artist_tag(parsed["tag"])
            quality = _canonical_quality_tag(parsed["tag"])
            if artist:
                artists[artist].append(parsed["weight"])
            if quality:
                if quality not in quality_tags:
                    quality_sequence.append(quality)
                quality_tags[quality].append(parsed["weight"])
        if artists:
            images_with_artist += 1
            for artist, weights in artists.items():
                artist_counts[artist] += 1
                artist_weights[artist].extend(weights)
                if row["recommendation_count"] is not None:
                    artist_recommendations[artist].append(row["recommendation_count"])
                highest = max(weights)
                if artist not in artist_representatives or highest > artist_representatives[artist].get("weight", float("-inf")):
                    artist_representatives[artist] = _statistics_representative(row, highest)
        if quality_tags:
            images_with_quality += 1
            for quality, weights in quality_tags.items():
                quality_counts[quality] += 1
                quality_weights[quality].extend(weights)
                if row["recommendation_count"] is not None:
                    quality_recommendations[quality].append(row["recommendation_count"])
                highest = max(weights)
                if quality not in quality_representatives or highest > quality_representatives[quality].get("weight", float("-inf")):
                    quality_representatives[quality] = _statistics_representative(row, highest)
            if len(quality_sequence) >= 2:
                sequence_counts[tuple(quality_sequence)] += 1
                bundle_counts[tuple(sorted(quality_tags))] += 1
                if row["recommendation_count"] is not None:
                    sequence_recommendations[tuple(quality_sequence)].append(row["recommendation_count"])
                    bundle_recommendations[tuple(sorted(quality_tags))].append(row["recommendation_count"])
                sequence_representatives.setdefault(tuple(quality_sequence), _statistics_representative(row))
            for left, right in combinations(sorted(quality_tags), 2):
                edge_counts[(left, right)] += 1
    artist_entries = _statistics_entries(
        artist_counts, analyzed_image_count, artist_weights, artist_representatives, artist_recommendations,
    )
    quality_entries = _statistics_entries(
        quality_counts, analyzed_image_count, quality_weights, quality_representatives, quality_recommendations,
    )
    quality_entry_map = {entry["tag"]: entry for entry in quality_entries}
    return {
        "analyzed_image_count": analyzed_image_count,
        "analyzed_post_count": len(post_ids),
        "analyzed_tag_count": analyzed_tag_count,
        "images_with_artist": images_with_artist,
        "images_with_quality": images_with_quality,
        "artists": artist_entries,
        "quality_tags": quality_entries,
        "quality_sequences": _combination_entries(
            sequence_counts, analyzed_image_count, sequence_representatives, sequence_recommendations,
        ),
        "quality_bundles": _combination_entries(bundle_counts, analyzed_image_count, recommendations=bundle_recommendations),
        "quality_network": {
            "nodes": [
                {key: entry[key] for key in ("tag", "count", "percentage", "average_weight")}
                for entry in quality_entries
            ],
            "edges": [
                {
                    "source": pair[0], "target": pair[1], "count": count,
                    "percentage": round(count * 100 / analyzed_image_count, 1) if analyzed_image_count else 0.0,
                }
                for pair, count in sorted(edge_counts.items(), key=lambda entry: (-entry[1], entry[0]))
                if pair[0] in quality_entry_map and pair[1] in quality_entry_map
            ],
        },
        "collection_scope_note": "저장된 공유 그림체 이미지 기준이며, 수집은 선택한 날짜 범위의 검색 종료 지점까지 진행됩니다.",
    }


def get_arca_tag_statistics(db_path, kind, tag, image_limit=24, filters=None):
    kind = str(kind or "").strip().lower()
    if kind == "artist":
        canonical = _canonical_artist_tag(tag)
        canonicalizer = _canonical_artist_tag
    elif kind == "quality":
        canonical = _canonical_quality_tag(tag)
        canonicalizer = _canonical_quality_tag
    else:
        raise ArcaCollectorError("통계 태그 종류는 artist 또는 quality여야 합니다.")
    if not canonical:
        raise ArcaCollectorError("통계 태그를 확인해 주세요.")
    try:
        image_limit = min(max(int(image_limit), 1), 100)
    except (TypeError, ValueError):
        raise ArcaCollectorError("이미지 개수는 숫자여야 합니다.")
    weights, matched_images, related_counts = [], {}, defaultdict(int)
    for row in _statistics_image_rows(db_path, filters):
        parsed_tags = parse_weighted_prompt_tags(row["base_prompt"])
        matched_weights = [
            parsed["weight"] for parsed in parsed_tags
            if canonicalizer(parsed["tag"]) == canonical
        ]
        if not matched_weights:
            continue
        if kind == "quality":
            related_in_image = {
                quality for parsed in parsed_tags
                if (quality := _canonical_quality_tag(parsed["tag"])) and quality != canonical
            }
        else:
            related_in_image = {
                artist for parsed in parsed_tags
                if (artist := _canonical_artist_tag(parsed["tag"])) and artist != canonical
            }
        for related in related_in_image:
            related_counts[related] += 1
        weights.extend(matched_weights)
        matched_images[row["id"]] = {
            "id": row["id"], "item_id": row["item_id"],
            "image_url": row["image_url"], "image_path": row["image_path"],
            "title": row["title"], "source_url": row["source_url"],
            "posted_at": row["posted_at"], "board_tab": row["board_tab"],
            "prompt": row["base_prompt"], "recommendation_count": row["recommendation_count"],
            "weight": round(max(matched_weights), 3),
        }
    images = sorted(matched_images.values(), key=lambda image: (-image["weight"], -image["id"]))
    return {
        "kind": kind,
        "tag": canonical,
        "image_count": len(images),
        "occurrence_count": len(weights),
        "weights": _weight_summary(weights),
        "related_tags": [
            {
                "tag": related, "count": count,
                "percentage": round(count * 100 / len(images), 1) if images else 0.0,
            }
            for related, count in sorted(related_counts.items(), key=lambda entry: (-entry[1], entry[0]))
        ],
        "images": images[:image_limit],
    }


def get_arca_quality_sequence_statistics(db_path, tags, image_limit=40, filters=None):
    if not isinstance(tags, (list, tuple)):
        raise ArcaCollectorError("퀄리티 순서 조합을 확인해 주세요.")
    canonical_tags = [_canonical_quality_tag(tag) for tag in tags]
    if len(canonical_tags) < 2 or any(not tag for tag in canonical_tags):
        raise ArcaCollectorError("퀄리티 순서 조합은 두 개 이상의 유효한 태그여야 합니다.")
    try:
        image_limit = min(max(int(image_limit), 1), 100)
    except (TypeError, ValueError):
        raise ArcaCollectorError("이미지 개수는 숫자여야 합니다.")
    images = []
    for row in _statistics_image_rows(db_path, filters):
        if _quality_tag_sequence(row["base_prompt"]) != canonical_tags:
            continue
        images.append({
            "id": row["id"], "item_id": row["item_id"],
            "image_url": row["image_url"], "image_path": row["image_path"],
            "title": row["title"], "source_url": row["source_url"],
            "posted_at": row["posted_at"], "board_tab": row["board_tab"],
            "prompt": row["base_prompt"], "recommendation_count": row["recommendation_count"],
        })
    images.sort(key=lambda image: -image["id"])
    return {"tags": canonical_tags, "image_count": len(images), "images": images[:image_limit]}


def get_arca_style_detail(db_path, item_id):
    with closing(_connect(db_path)) as conn:
        item = _row(conn.execute("SELECT * FROM arca_style_items WHERE id=?", (item_id,)).fetchone())
        if item:
            item["images"] = [_row(row) for row in conn.execute("SELECT * FROM arca_style_images WHERE item_id=? ORDER BY id", (item_id,))]
            for image in item["images"]:
                image["base_prompt"] = image.get("base_prompt") or image.get("prompt") or ""
                try:
                    characters = json.loads(image.get("character_prompts_json") or "[]")
                except json.JSONDecodeError:
                    characters = []
                image["character_prompts"] = characters if isinstance(characters, list) else []
            item["prompts"] = [
                {"image_id": image["id"], "image_url": image["image_url"], "image_path": image["image_path"], "prompt": image["prompt"], "base_prompt": image["base_prompt"], "negative_prompt": image["negative_prompt"], "character_prompts": image["character_prompts"]}
                for image in item["images"] if (image.get("prompt") or "").strip()
            ]
            groupable = [image for image in item["images"] if (image.get("base_prompt") or "").strip()]
            item["style_groups"] = build_style_groups(groupable)
            item["style_group_count"] = len(item["style_groups"])
        return item


def update_arca_style(db_path, item_id, payload):
    if not isinstance(payload, dict): raise ArcaCollectorError("수정 데이터가 올바르지 않습니다.")
    values = {}
    for key in ("prompt", "negative_prompt", "memo"):
        if key in payload:
            if not isinstance(payload[key], str) or len(payload[key]) > EDITABLE_LIMIT: raise ArcaCollectorError(f"{key} 값이 올바르지 않습니다.")
            values[key] = payload[key]
    if not values: raise ArcaCollectorError("수정할 항목이 없습니다.")
    values["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        cursor = conn.execute(f"UPDATE arca_style_items SET {','.join(f'{key}=?' for key in values)} WHERE id=?", (*values.values(), item_id))
        if not cursor.rowcount: return None
    return get_arca_style_detail(db_path, item_id)


def delete_arca_style(db_path, image_dir, item_id):
    with closing(_connect(db_path)) as conn, conn:
        item = conn.execute("SELECT posted_at FROM arca_style_items WHERE id=?", (item_id,)).fetchone()
        if not item:
            return None
        posted_at = item[0] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item[0] or "") else None
        if posted_at:
            runs = conn.execute(
                "SELECT DISTINCT r.keyword,r.tabs,r.max_pages,r.max_posts,r.search_scope FROM arca_collection_runs r JOIN arca_collection_run_items ri ON ri.run_id=r.id WHERE ri.item_id=?",
                (item_id,),
            ).fetchall()
            now = datetime.now().isoformat(timespec="seconds")
            for run in runs:
                conn.execute(
                    "INSERT OR IGNORE INTO arca_collection_invalidations(keyword,tabs,max_pages,max_posts,search_scope,invalidated_date,created_at) VALUES(?,?,?,?,?,?,?)",
                    (*run, posted_at, now),
                )
        paths = [row[0] for row in conn.execute("SELECT image_path FROM arca_style_images WHERE item_id=?", (item_id,)) if row[0]]
        cursor = conn.execute("DELETE FROM arca_style_items WHERE id=?", (item_id,))
        referenced = {row[0] for row in conn.execute("SELECT image_path FROM arca_style_images WHERE image_path<>''")}
    root = Path(image_dir).resolve()
    for value in paths:
        path = (root / value).resolve()
        if path.parent == root and value not in referenced: path.unlink(missing_ok=True)
    return {"deleted": True, "recollect_date": posted_at}


def collect_arca_styles(db_path, image_dir, payload, job_id=None):
    params = normalize_collect_payload(payload); init_arca_style_tables(db_path)
    start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
    uncovered = uncovered_date_intervals(start, end, get_completed_coverage(db_path, params))
    if not uncovered:
        if job_id:
            update_collection_job(db_path, job_id, status="completed", stage="completed", skipped_existing=1)
        return {"ok": True, "skipped_existing": True, "scanned_pages": 0, "scanned_posts": 0, "saved": 0, "updated": 0, "items": []}
    browser_status = get_arca_browser_session_status()
    if "R18_NAI" in params["tabs"] and not browser_status["connected"]:
        raise ArcaBrowserSessionRequired("🔞 NAI 수집 전에 브라우저 로그인을 가져와 주세요.")
    session = create_arca_session()
    if browser_status["connected"]:
        _apply_imported_arca_cookies(session)
    category_params = discover_category_params(session)
    missing_tabs = [tab for tab in params["tabs"] if tab not in category_params]
    if missing_tabs:
        if "R18_NAI" in missing_tabs:
            clear_arca_browser_session("로그인 세션에서 🔞 NAI 항목을 확인하지 못했습니다.")
            raise ArcaBrowserSessionRequired("브라우저 로그인이 만료되었습니다. 다시 가져와 주세요.")
        raise ArcaCollectorError("아카라이브 NAI 검색 항목을 찾지 못했습니다.")
    summary = {"ok": True, "skipped_existing": False, "partial": False, "scanned_pages": 0, "scanned_posts": 0, "saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "skipped": 0, "items": []}
    if job_id:
        update_collection_job(
            db_path, job_id, status="running", stage="searching",
            total_posts=params["max_posts"] or None,
            total_pages=params["max_pages"] * len(params["tabs"]) * len(uncovered) if params["max_pages"] else None,
        )
    reached_post_limit = False
    for interval_start, interval_end in uncovered:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(_connect(db_path)) as conn, conn:
            run_id = conn.execute("INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,search_scope,status,created_at,updated_at,job_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (params["keyword"], _tabs_key(params["tabs"]), interval_start.isoformat(), interval_end.isoformat(), params["max_pages"], params["max_posts"], SEARCH_SCOPE, "running", now, now, job_id)).lastrowid
        try:
            seen = set()
            search_items = []
            interval_complete = True
            for tab in params["tabs"]:
                page_cache = {}

                def fetch_page(page):
                    _wait_for_collection_control(db_path, job_id, "scanning")
                    if page in page_cache:
                        return page_cache[page]
                    urls = build_search_urls(params["keyword"], [tab], page, category_params)
                    if not urls:
                        page_cache[page] = []
                        return page_cache[page]
                    html = fetch_html(session, urls[0]); summary["scanned_pages"] += 1
                    _wait_for_collection_control(db_path, job_id, "scanning")
                    if job_id:
                        update_collection_job(db_path, job_id, stage="scanning", scanned_pages=summary["scanned_pages"])
                    page_cache[page] = [
                        item for item in extract_search_results(html, ARCA_BASE_URL, params["keyword"])
                        if item.get("board_tab") == tab
                    ]
                    return page_cache[page]

                page = _locate_archive_page(fetch_page, interval_end)
                target_pages = 0
                reached_lower_boundary = False
                while page <= MAX_ARCHIVE_SEARCH_PAGE and (not params["max_pages"] or target_pages < params["max_pages"]):
                    search_results = fetch_page(page)
                    target_pages += 1
                    if not search_results:
                        reached_lower_boundary = True
                        break
                    oldest, newest = _search_page_date_bounds(search_results)
                    for search_item in search_results:
                        article_url = search_item["source_url"]
                        if article_url in seen:
                            continue
                        posted_at = _search_item_date(search_item)
                        if posted_at and not interval_start <= posted_at <= interval_end:
                            continue
                        seen.add(article_url)
                        search_items.append(search_item)
                        summary["scanned_posts"] += 1
                        if params["max_posts"] and summary["scanned_posts"] >= params["max_posts"]:
                            reached_post_limit = True
                            break
                    if reached_post_limit:
                        break
                    if newest and newest < interval_start:
                        reached_lower_boundary = True
                        break
                    if oldest and oldest < interval_start:
                        reached_lower_boundary = True
                        break
                    page += 1
                if reached_post_limit:
                    interval_complete = False
                    break
                if not reached_lower_boundary:
                    interval_complete = False
            if job_id and search_items:
                update_collection_job(db_path, job_id, stage="fetching_posts", scanned_posts=summary["scanned_posts"])
            for search_item, article_html, fetch_seconds in _fetch_article_htmls(session, search_items):
                _wait_for_collection_control(db_path, job_id, "fetching_posts")
                if article_html is None:
                    summary["skipped"] += 1
                    continue
                post_started = time.monotonic()
                article_url = search_item["source_url"]
                article = extract_article_data(article_html, article_url)
                article["source_url"] = article_url
                article["title"] = search_item.get("title") or article.get("title", "")
                article["board_tab"] = search_item.get("board_tab") or article.get("board_tab", "")
                if search_item.get("posted_at"):
                    try:
                        date.fromisoformat(search_item["posted_at"])
                        article["posted_at"] = search_item["posted_at"]
                    except ValueError:
                        pass
                try:
                    article_date = date.fromisoformat(article.get("posted_at") or "")
                except ValueError:
                    article_date = None
                if not article_date or not interval_start <= article_date <= interval_end or article["board_tab"] not in params["tabs"]:
                    summary["skipped"] += 1
                    continue
                _wait_for_collection_control(db_path, job_id, "downloading")
                downloaded_count, _ = _save_article(db_path, image_dir, session, article, summary, run_id=run_id)
                if job_id:
                    previous = get_collection_job(db_path, job_id)
                    elapsed = max(fetch_seconds + time.monotonic() - post_started, 0.001)
                    prior_average = previous.get("average_post_seconds") if previous else None
                    average = elapsed if prior_average is None else (float(prior_average) * 0.7 + elapsed * 0.3)
                    update_collection_job(
                        db_path, job_id, stage="downloading",
                        downloaded_images=(previous["downloaded_images"] if previous else 0) + downloaded_count,
                        saved=summary["saved"], updated=summary["updated"], average_post_seconds=average,
                    )
            run_status = "completed" if interval_complete else "partial"
            run_error = "" if interval_complete else "요청 기간의 검색 종료 지점을 확인하지 못해 일부만 수집했습니다."
            if not interval_complete:
                summary["partial"] = True
                summary["warning"] = run_error
            with closing(_connect(db_path)) as conn, conn: conn.execute("UPDATE arca_collection_runs SET status=?,error=?,scanned_pages=?,scanned_posts=?,saved=?,updated=?,updated_at=? WHERE id=?", (run_status, run_error, summary["scanned_pages"], summary["scanned_posts"], summary["saved"], summary["updated"], datetime.now().isoformat(timespec="seconds"), run_id))
            if run_status == "completed":
                with closing(_connect(db_path)) as conn, conn:
                    conn.execute(
                        "DELETE FROM arca_collection_invalidations WHERE keyword=? AND tabs=? AND max_pages=? AND max_posts=? AND search_scope=? AND invalidated_date BETWEEN ? AND ?",
                        (params["keyword"], _tabs_key(params["tabs"]), params["max_pages"], params["max_posts"], SEARCH_SCOPE, interval_start.isoformat(), interval_end.isoformat()),
                    )
        except ArcaCollectionStopped as exc:
            with closing(_connect(db_path)) as conn, conn:
                conn.execute(
                    "UPDATE arca_collection_runs SET status='partial',error=?,scanned_pages=?,scanned_posts=?,saved=?,updated=?,updated_at=? WHERE id=?",
                    (str(exc), summary["scanned_pages"], summary["scanned_posts"], summary["saved"], summary["updated"], datetime.now().isoformat(timespec="seconds"), run_id),
                )
            raise
        except Exception as exc:
            with closing(_connect(db_path)) as conn, conn: conn.execute("UPDATE arca_collection_runs SET status='failed',error=?,updated_at=? WHERE id=?", (str(exc)[:1000], datetime.now().isoformat(timespec="seconds"), run_id))
            raise
        if reached_post_limit:
            break
    if job_id:
        update_collection_job(db_path, job_id, status="completed", stage="completed", scanned_pages=summary["scanned_pages"], scanned_posts=summary["scanned_posts"], total_posts=summary["scanned_posts"], saved=summary["saved"], updated=summary["updated"], error=summary.get("warning", ""))
    return summary


def _save_article(db_path, image_dir, session, article, summary, run_id=None):
    image_root = Path(image_dir).resolve()
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT im.* FROM arca_style_images im JOIN arca_style_items i ON i.id=im.item_id WHERE i.source_url=?",
            (article["source_url"],),
        ).fetchall()
    existing = {_image_identity(row["image_url"]): dict(row) for row in rows}
    resolved, new_urls, identities, seen_identities = {}, [], [], set()

    def stored_record(stored):
        try:
            characters = json.loads(stored.get("character_prompts_json") or "[]")
        except json.JSONDecodeError:
            characters = []
        meta = {
            "metadata_status": stored.get("metadata_status") or "no_metadata",
            "prompt": stored.get("prompt") or "",
            "base_prompt": stored.get("base_prompt") or stored.get("prompt") or "",
            "negative_prompt": stored.get("negative_prompt") or "",
            "character_prompts": characters if isinstance(characters, list) else [],
            "seed": stored.get("seed") or "", "sampler": stored.get("sampler") or "",
            "steps": stored.get("steps"), "scale": stored.get("scale"),
            "cfg_rescale": stored.get("cfg_rescale"), "noise_schedule": stored.get("noise_schedule") or "",
            "model": stored.get("model") or "", "width": stored.get("width"), "height": stored.get("height"),
            "raw_metadata_json": stored.get("raw_metadata_json") or "{}",
        }
        return stored["image_url"], stored.get("image_path") or "", stored.get("content_type") or "image/png", meta

    for image_url in article["image_urls"]:
        identity = _image_identity(image_url)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        identities.append(identity)
        stored = existing.get(identity)
        stored_path = (image_root / stored["image_path"]).resolve() if stored and stored.get("image_path") else None
        if stored and stored.get("metadata_status") == "no_metadata":
            resolved[identity] = stored_record(stored)
        elif stored and stored_path and image_root in stored_path.parents and stored_path.exists():
            resolved[identity] = stored_record(stored)
        else:
            obvious_content_type = _obvious_non_png_content_type(image_url)
            if obvious_content_type:
                resolved[identity] = (image_url, "", obvious_content_type, extract_novelai_metadata(b""))
            else:
                new_urls.append(image_url)

    def fetch_new_image(image_url):
        try:
            data, content_type = download_image(session, image_url)
            if data is None:
                return image_url, None, content_type, extract_novelai_metadata(b"")
            meta = extract_novelai_metadata(data, content_type)
            return image_url, data if meta["metadata_status"] == "ok" else None, content_type, meta
        except (requests.RequestException, ArcaCollectorError, zlib.error):
            return None

    saved_count = 0
    if new_urls:
        pending_urls = iter(new_urls)
        image_workers = min(COLLECTION_WORKERS, len(new_urls))
        with ThreadPoolExecutor(max_workers=image_workers) as executor:
            pending = {}
            for _ in range(image_workers):
                image_url = next(pending_urls)
                pending[executor.submit(fetch_new_image, image_url)] = image_url
            while pending:
                future = next(as_completed(tuple(pending)))
                pending.pop(future)
                result = future.result()
                if result:
                    image_url, data, content_type, image_meta = result
                    path = ""
                    if data is not None:
                        try:
                            path = save_image_bytes(image_dir, image_url, data, content_type)
                        except OSError:
                            result = None
                        else:
                            saved_count += 1
                    if result:
                        resolved[_image_identity(image_url)] = (image_url, path, content_type, image_meta)
                try:
                    image_url = next(pending_urls)
                except StopIteration:
                    continue
                pending[executor.submit(fetch_new_image, image_url)] = image_url
    downloaded = [resolved[identity] for identity in identities if identity in resolved]
    representative = next((item for item in downloaded if item[3]["metadata_status"] == "ok"), downloaded[0] if downloaded else None)
    meta = representative[3] if representative else extract_novelai_metadata(b"")
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        exists = conn.execute("SELECT id FROM arca_style_items WHERE source_url=?", (article["source_url"],)).fetchone()
        fields = (article["article_id"], article["board_tab"], article["title"], article["author"], article["posted_at"], now, representative[0] if representative else "", representative[1] if representative else "", len(downloaded), meta["metadata_status"], meta["prompt"], meta["negative_prompt"], meta["seed"], meta["sampler"], meta["steps"], meta["scale"], meta["cfg_rescale"], meta["noise_schedule"], meta["model"], meta["width"], meta["height"], meta["raw_metadata_json"], article["body_text"], article.get("recommendation_count"), article.get("view_count"), article["source_url"])
        if exists:
            item_id = exists[0]; conn.execute("UPDATE arca_style_items SET article_id=?,board_tab=?,title=?,author=?,posted_at=?,updated_at=?,representative_image_url=?,representative_image_path=?,image_count=?,metadata_status=?,prompt=?,negative_prompt=?,seed=?,sampler=?,steps=?,scale=?,cfg_rescale=?,noise_schedule=?,model=?,width=?,height=?,raw_metadata_json=?,body_prompt_text=?,recommendation_count=?,view_count=? WHERE source_url=?", fields); summary["updated"] += 1
        else:
            item_id = conn.execute("INSERT INTO arca_style_items(article_id,board_tab,title,author,posted_at,collected_at,updated_at,representative_image_url,representative_image_path,image_count,metadata_status,prompt,negative_prompt,seed,sampler,steps,scale,cfg_rescale,noise_schedule,model,width,height,raw_metadata_json,body_prompt_text,recommendation_count,view_count,source_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fields[:5] + (now,) + fields[5:]).lastrowid; summary["saved"] += 1
        if run_id:
            conn.execute("INSERT OR IGNORE INTO arca_collection_run_items(run_id,item_id) VALUES(?,?)", (run_id, item_id))
        for image_url, path, content_type, image_meta in downloaded:
            conn.execute("""INSERT INTO arca_style_images(item_id,image_url,image_path,content_type,metadata_status,prompt,negative_prompt,seed,sampler,steps,scale,cfg_rescale,noise_schedule,model,width,height,raw_metadata_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(item_id,image_url) DO UPDATE SET image_path=excluded.image_path,content_type=excluded.content_type,metadata_status=excluded.metadata_status,prompt=excluded.prompt,negative_prompt=excluded.negative_prompt,seed=excluded.seed,sampler=excluded.sampler,steps=excluded.steps,scale=excluded.scale,cfg_rescale=excluded.cfg_rescale,noise_schedule=excluded.noise_schedule,model=excluded.model,width=excluded.width,height=excluded.height,raw_metadata_json=excluded.raw_metadata_json""", (item_id, image_url, path, content_type, image_meta["metadata_status"], image_meta["prompt"], image_meta["negative_prompt"], image_meta["seed"], image_meta["sampler"], image_meta["steps"], image_meta["scale"], image_meta["cfg_rescale"], image_meta["noise_schedule"], image_meta["model"], image_meta["width"], image_meta["height"], image_meta["raw_metadata_json"], now))
            conn.execute(
                "UPDATE arca_style_images SET base_prompt=?,character_prompts_json=? WHERE item_id=? AND image_url=?",
                (image_meta.get("base_prompt", image_meta["prompt"]), json.dumps(image_meta.get("character_prompts", []), ensure_ascii=False), item_id, image_url),
            )
        duplicate_rows = conn.execute(
            "SELECT id,image_url FROM arca_style_images WHERE item_id=? ORDER BY id DESC",
            (item_id,),
        ).fetchall()
        kept_identities, duplicate_ids = set(), []
        for duplicate_row in duplicate_rows:
            identity = _image_identity(duplicate_row["image_url"])
            if identity in kept_identities:
                duplicate_ids.append(duplicate_row["id"])
            else:
                kept_identities.add(identity)
        if duplicate_ids:
            conn.executemany("DELETE FROM arca_style_images WHERE id=?", ((image_id,) for image_id in duplicate_ids))
    summary["metadata_ok" if meta["metadata_status"] == "ok" else "no_metadata"] += 1; summary["items"].append({"id": item_id, "source_url": article["source_url"]})
    return saved_count, item_id
