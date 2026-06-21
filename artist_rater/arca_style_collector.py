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
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from threading import RLock, Thread
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
SEARCH_SCOPE = "title-category-session-v5"
GENERATION_KEYS = {"seed", "sampler", "steps", "scale", "noise_schedule", "model", "width", "height"}
STYLE_SIMILARITY_THRESHOLD = 0.55
TRANSIENT_TAG = re.compile(r"^(?:\d+(?:girl|boy)s?|solo|multiple girls|portrait|upper body|full body|looking at.*|smile|open mouth|.*hair|.*eyes|robot)$", re.I)


class ArcaCollectorError(Exception):
    pass


class ArcaBrowserSessionRequired(ArcaCollectorError):
    pass


_ARCA_BROWSER_LOCK = RLock()
_ARCA_BROWSER_COOKIES = CookieJar()
_ARCA_BROWSER_STATUS = {"connected": False, "browser": "", "error": ""}


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
        CREATE INDEX IF NOT EXISTS idx_arca_runs_lookup ON arca_collection_runs(keyword,tabs,max_pages,max_posts,status);
        """)
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_collection_runs)")}
        if "search_scope" not in run_columns:
            conn.execute("ALTER TABLE arca_collection_runs ADD COLUMN search_scope TEXT NOT NULL DEFAULT 'all'")
        _ensure_column(conn, "arca_collection_runs", "job_id", "INTEGER REFERENCES arca_collection_jobs(id)")
        _ensure_column(conn, "arca_style_images", "base_prompt", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "arca_style_images", "character_prompts_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "arca_style_items", "recommendation_count", "INTEGER")
        _ensure_column(conn, "arca_style_items", "view_count", "INTEGER")


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
        max_pages, max_posts = int(payload.get("max_pages", 5)), int(payload.get("max_posts", 80))
    except (TypeError, ValueError):
        raise ArcaCollectorError("페이지와 글 수는 숫자여야 합니다.")
    if not 1 <= max_pages <= 30 or not 1 <= max_posts <= 300:
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
            (json.dumps(params, ensure_ascii=False), "queued", "queued", params["max_pages"], now, now),
        ).lastrowid


def update_collection_job(db_path, job_id, **changes):
    allowed = {
        "status", "stage", "total_pages", "scanned_pages", "total_posts",
        "scanned_posts", "downloaded_images", "saved", "updated",
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
    return job


def mark_interrupted_collection_jobs(db_path):
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE arca_collection_jobs SET status='interrupted',stage='interrupted',error=?,finished_at=?,updated_at=? WHERE status IN ('queued','running')",
            ("앱이 종료되어 수집이 중단되었습니다.", now, now),
        )


def _run_collection_job(db_path, image_dir, params, job_id):
    try:
        update_collection_job(db_path, job_id, status="running", stage="searching")
        collect_arca_styles(db_path, image_dir, params, job_id=job_id)
    except Exception as exc:
        update_collection_job(db_path, job_id, status="failed", stage="failed", error=str(exc)[:1000])


def start_collection_job(db_path, image_dir, payload):
    params = normalize_collect_payload(payload)
    job_id = create_collection_job(db_path, params)
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


def collect_arca_style_url(db_path, image_dir, source_url, job_id=None, session=None):
    canonical = normalize_arca_article_url(source_url)
    init_arca_style_tables(db_path)
    session = session or create_arca_session()
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


def fetch_html(session, url):
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def download_image(session, image_url):
    response = session.get(image_url, timeout=IMAGE_TIMEOUT, stream=True)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
    if not content_type.startswith("image/"): raise ArcaCollectorError("이미지 응답이 아닙니다.")
    chunks, size = [], 0
    for chunk in response.iter_content(64 * 1024):
        size += len(chunk)
        if size > MAX_IMAGE_BYTES: raise ArcaCollectorError("이미지 크기 제한을 초과했습니다.")
        chunks.append(chunk)
    return b"".join(chunks), content_type


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


def list_arca_styles(db_path, filters=None):
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
    sort = filters.get("sort") or "posted_desc"
    if sort not in {"posted_desc", "posted_asc", "recommend_desc", "views_desc"}:
        raise ArcaCollectorError("아카라이브 날짜 정렬 값을 확인해 주세요.")
    limit = min(max(int(filters.get("limit", 200)), 1), 500)
    sql = "SELECT * FROM arca_style_items" + (" WHERE " + " AND ".join(clauses) if clauses else "")
    if sort in {"posted_desc", "posted_asc"}:
        direction = "DESC" if sort == "posted_desc" else "ASC"
        order_sql = f"CASE WHEN TRIM(COALESCE(posted_at,''))='' THEN 1 ELSE 0 END ASC,posted_at {direction},id DESC"
    else:
        column = "recommendation_count" if sort == "recommend_desc" else "view_count"
        order_sql = f"CASE WHEN {column} IS NULL THEN 1 ELSE 0 END ASC,{column} DESC,id DESC"
    sql += f" ORDER BY {order_sql} LIMIT ?"
    with closing(_connect(db_path)) as conn:
        items = [_row(row) for row in conn.execute(sql, (*args, limit))]
    for item in items:
        item["style_group_count"] = count_style_groups_for_item(db_path, item["id"])
    return items


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
    start, end = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
    uncovered = uncovered_date_intervals(start, end, get_completed_coverage(db_path, params))
    if not uncovered:
        if job_id:
            update_collection_job(db_path, job_id, status="completed", stage="completed", skipped_existing=1)
        return {"ok": True, "skipped_existing": True, "scanned_pages": 0, "scanned_posts": 0, "saved": 0, "updated": 0, "items": []}
    summary = {"ok": True, "skipped_existing": False, "scanned_pages": 0, "scanned_posts": 0, "saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "skipped": 0, "items": []}
    if job_id:
        update_collection_job(db_path, job_id, status="running", stage="searching", total_posts=params["max_posts"])
    for interval_start, interval_end in uncovered:
        interval_start_posts = summary["scanned_posts"]
        now = datetime.now().isoformat(timespec="seconds")
        with closing(_connect(db_path)) as conn, conn:
            run_id = conn.execute("INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,search_scope,status,created_at,updated_at,job_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (params["keyword"], _tabs_key(params["tabs"]), interval_start.isoformat(), interval_end.isoformat(), params["max_pages"], params["max_posts"], SEARCH_SCOPE, "running", now, now, job_id)).lastrowid
        try:
            seen = set()
            for page in range(1, params["max_pages"] + 1):
                for search_url in build_search_urls(params["keyword"], params["tabs"], page, category_params):
                    html = fetch_html(session, search_url); summary["scanned_pages"] += 1
                    if job_id:
                        update_collection_job(db_path, job_id, stage="scanning", scanned_pages=summary["scanned_pages"])
                    search_results = extract_search_results(html, ARCA_BASE_URL, params["keyword"])
                    for search_item in search_results:
                        article_url = search_item["source_url"]
                        if article_url in seen or summary["scanned_posts"] >= params["max_posts"]: continue
                        seen.add(article_url); summary["scanned_posts"] += 1
                        post_started = time.monotonic()
                        if job_id:
                            update_collection_job(db_path, job_id, stage="fetching_posts", scanned_posts=summary["scanned_posts"])
                        try:
                            article = extract_article_data(fetch_html(session, article_url), article_url)
                        except requests.RequestException:
                            summary["skipped"] += 1
                            continue
                        article.update(search_item)
                        if not article["posted_at"] or not interval_start <= date.fromisoformat(article["posted_at"]) <= interval_end or article["board_tab"] not in params["tabs"]: summary["skipped"] += 1; continue
                        downloaded_count, _ = _save_article(db_path, image_dir, session, article, summary, run_id=run_id)
                        if job_id:
                            previous = get_collection_job(db_path, job_id)
                            elapsed = max(time.monotonic() - post_started, 0.001)
                            prior_average = previous.get("average_post_seconds") if previous else None
                            average = elapsed if prior_average is None else (float(prior_average) * 0.7 + elapsed * 0.3)
                            update_collection_job(
                                db_path, job_id, stage="downloading",
                                downloaded_images=(previous["downloaded_images"] if previous else 0) + downloaded_count,
                                saved=summary["saved"], updated=summary["updated"], average_post_seconds=average,
                            )
            run_status = "completed" if summary["scanned_posts"] > interval_start_posts else "failed"
            run_error = "" if run_status == "completed" else "검색 결과 글 행을 받지 못했습니다."
            if run_status == "failed":
                summary["warning"] = run_error
            with closing(_connect(db_path)) as conn, conn: conn.execute("UPDATE arca_collection_runs SET status=?,error=?,scanned_pages=?,scanned_posts=?,saved=?,updated=?,updated_at=? WHERE id=?", (run_status, run_error, summary["scanned_pages"], summary["scanned_posts"], summary["saved"], summary["updated"], datetime.now().isoformat(timespec="seconds"), run_id))
            if run_status == "completed":
                with closing(_connect(db_path)) as conn, conn:
                    conn.execute(
                        "DELETE FROM arca_collection_invalidations WHERE keyword=? AND tabs=? AND max_pages=? AND max_posts=? AND search_scope=? AND invalidated_date BETWEEN ? AND ?",
                        (params["keyword"], _tabs_key(params["tabs"]), params["max_pages"], params["max_posts"], SEARCH_SCOPE, interval_start.isoformat(), interval_end.isoformat()),
                    )
        except Exception as exc:
            with closing(_connect(db_path)) as conn, conn: conn.execute("UPDATE arca_collection_runs SET status='failed',error=?,updated_at=? WHERE id=?", (str(exc)[:1000], datetime.now().isoformat(timespec="seconds"), run_id))
            raise
    if job_id:
        final_status = "failed" if summary.get("warning") else "completed"
        update_collection_job(db_path, job_id, status=final_status, stage=final_status, scanned_pages=summary["scanned_pages"], scanned_posts=summary["scanned_posts"], total_posts=summary["scanned_posts"], saved=summary["saved"], updated=summary["updated"], error=summary.get("warning", ""))
    return summary


def _save_article(db_path, image_dir, session, article, summary, run_id=None):
    image_root = Path(image_dir).resolve()
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT im.* FROM arca_style_images im JOIN arca_style_items i ON i.id=im.item_id WHERE i.source_url=?",
            (article["source_url"],),
        ).fetchall()
    existing = {_image_identity(row["image_url"]): dict(row) for row in rows}
    downloaded, new_urls, seen_identities = [], [], set()
    for image_url in article["image_urls"]:
        identity = _image_identity(image_url)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        stored = existing.get(identity)
        stored_path = (image_root / stored["image_path"]).resolve() if stored and stored.get("image_path") else None
        if stored and stored_path and image_root in stored_path.parents and stored_path.exists():
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
            downloaded.append((stored["image_url"], stored["image_path"], stored.get("content_type") or "image/png", meta))
        else:
            new_urls.append(image_url)
    def fetch_new_image(image_url):
        try:
            data, content_type = download_image(session, image_url)
            path = save_image_bytes(image_dir, image_url, data, content_type)
            return image_url, path, content_type, extract_novelai_metadata(data, content_type)
        except (requests.RequestException, ArcaCollectorError, OSError, zlib.error):
            return None
    with ThreadPoolExecutor(max_workers=min(4, len(new_urls) or 1)) as executor:
        new_downloads = [item for item in executor.map(fetch_new_image, new_urls) if item]
    downloaded.extend(new_downloads)
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
    return len(new_downloads), item_id
