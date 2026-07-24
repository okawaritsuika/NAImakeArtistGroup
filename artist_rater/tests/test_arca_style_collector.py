import json
import gzip
import io
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
import zlib
from contextlib import closing
from datetime import date
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import requests

import arca_style_collector as collector_module
from arca_style_collector import (
    ArcaCollectorError,
    ArcaBrowserSessionRequired,
    extract_article_links,
    extract_article_data,
    extract_image_candidates,
    extract_search_results,
    extract_novelai_metadata,
    get_completed_coverage,
    get_arca_style_detail,
    init_arca_style_tables,
    merge_date_intervals,
    normalize_collect_payload,
    normalize_arca_article_url,
    parse_body_prompt_fallback,
    revalidate_stored_metadata,
    uncovered_date_intervals,
    update_arca_style,
    USER_AGENT,
    SEARCH_SCOPE,
    create_arca_session,
    build_search_urls,
    clear_arca_browser_session,
    connect_arca_cookie_jar,
    discover_category_params,
    get_arca_browser_session_status,
    import_arca_browser_session,
    import_arca_style_seed,
    snapshot_imported_arca_cookies,
    build_style_groups,
    count_style_groups_for_item,
    create_collection_job,
    create_image_restore_job,
    create_image_url_refresh_job,
    create_url_collection_job,
    delete_arca_style,
    get_collection_job,
    get_latest_resumable_collection_job,
    get_image_restore_estimate,
    get_arca_style_statistics,
    get_arca_style_page,
    get_arca_tag_statistics,
    get_arca_quality_sequence_statistics,
    get_style_maker_prompt_presets,
    get_shared_style_artist_pool,
    list_arca_styles,
    parse_weighted_prompt_tags,
    pause_collection_job,
    resume_collection_job,
    restore_arca_style_images,
    refresh_arca_style_image_urls,
    stop_collection_job,
    split_prompt_tags,
    update_collection_job,
    _save_article,
    collect_arca_style_url,
    collect_arca_styles,
    export_arca_style_seed,
)


def png_with_text(key, value):
    def chunk(kind, payload):
        crc = zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", key.encode() + b"\0" + value.encode()) + chunk(b"IEND", b"")


def png_with_stealth(metadata, compressed=True):
    payload = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    if compressed:
        payload = gzip.compress(payload)
    signature = b"stealth_pngcomp" if compressed else b"stealth_pnginfo"
    bit_text = "".join(f"{byte:08b}" for byte in signature)
    bit_text += f"{len(payload) * 8:032b}"
    bit_text += "".join(f"{byte:08b}" for byte in payload)
    height = 64
    width = (len(bit_text) + height - 1) // height
    image = Image.new("RGBA", (width, height), (10, 20, 30, 254))
    alpha = bytearray(image.getchannel("A").tobytes())
    for index, bit in enumerate(bit_text):
        x, y = divmod(index, height)
        offset = y * width + x
        alpha[offset] = (alpha[offset] & 0xFE) | int(bit)
    image.putalpha(Image.frombytes("L", image.size, bytes(alpha)))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def webp_with_exif_user_comment(metadata):
    payload = json.dumps(metadata, ensure_ascii=False).encode("utf-16-be")
    exif = Image.Exif()
    exif[37510] = b"UNICODE\x00" + payload
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 30, 40)).save(output, "WEBP", lossless=True, exif=exif)
    return output.getvalue()


def webp_with_stealth(metadata):
    output = io.BytesIO()
    with Image.open(io.BytesIO(png_with_stealth(metadata))) as image:
        image.save(output, "WEBP", lossless=True)
    return output.getvalue()


class ArcaCollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "archive.sqlite"
        init_arca_style_tables(self.db_path)

    def tearDown(self):
        clear_arca_browser_session()
        self.temp.cleanup()

    @staticmethod
    def _cookie(domain, name, value):
        return Cookie(0, name, value, None, False, domain, True, domain.startswith("."), "/", True,
                      False, None, True, None, None, {}, False)

    def test_import_browser_session_tries_edge_after_chrome_and_filters_domains(self):
        jar = CookieJar()
        jar.set_cookie(self._cookie(".arca.live", "session", "secret-arca"))
        jar.set_cookie(self._cookie("example.com", "session", "secret-other"))

        def chrome():
            raise RuntimeError("locked secret-arca")

        result = import_arca_browser_session(
            loaders=[("Chrome", chrome), ("Edge", lambda: jar)],
            validator=lambda _session: {"NAI": {"category": "nai"}, "R18_NAI": {"category": "r18"}},
        )

        self.assertEqual(result, {"connected": True, "browser": "Edge", "error": ""})
        cookies = snapshot_imported_arca_cookies()
        self.assertEqual([(cookie.domain, cookie.name) for cookie in cookies], [(".arca.live", "session")])

    def test_failed_import_clears_previous_session_without_exposing_cookie_values(self):
        jar = CookieJar()
        jar.set_cookie(self._cookie("arca.live", "session", "do-not-expose"))
        import_arca_browser_session(
            loaders=[("Chrome", lambda: jar)],
            validator=lambda _session: {"R18_NAI": {"category": "r18"}},
        )

        result = import_arca_browser_session(
            loaders=[("Chrome", lambda: jar)],
            validator=lambda _session: {"NAI": {"category": "nai"}},
        )

        self.assertFalse(result["connected"])
        self.assertEqual(snapshot_imported_arca_cookies(), [])
        self.assertNotIn("do-not-expose", json.dumps(result))
        self.assertEqual(get_arca_browser_session_status(), result)

    def test_connects_validated_login_window_cookie_jar(self):
        jar = CookieJar()
        jar.set_cookie(self._cookie(".arca.live", "session", "login-window-secret"))
        status = connect_arca_cookie_jar(
            jar, "전용 Chrome",
            validator=lambda _session: {"R18_NAI": {"category": "r18"}},
        )
        self.assertEqual(status, {"connected": True, "browser": "전용 Chrome", "error": ""})
        self.assertEqual(len(snapshot_imported_arca_cookies()), 1)

    def test_rejects_login_window_cookie_without_r18_access(self):
        jar = CookieJar()
        jar.set_cookie(self._cookie(".arca.live", "session", "invalid-secret"))
        status = connect_arca_cookie_jar(
            jar, "전용 Chrome",
            validator=lambda _session: {"NAI": {"category": "nai"}},
        )
        self.assertFalse(status["connected"])
        self.assertEqual(snapshot_imported_arca_cookies(), [])
        self.assertNotIn("invalid-secret", str(status))

    def test_discovers_nai_and_r18_category_queries_from_board_links(self):
        html = '''
        <a href="/b/aiart?category=nai">NAI</a>
        <a href="/b/aiart?category=r18">🔞 NAI</a>
        <a href="/b/aiart?category=info">정보/자료</a>
        '''

        class Session:
            def get(self, _url, **_kwargs):
                return type("Response", (), {"text": html, "raise_for_status": lambda self: None})()

        self.assertEqual(discover_category_params(Session()), {
            "NAI": {"category": "nai"},
            "R18_NAI": {"category": "r18"},
        })

    def test_builds_one_search_url_per_requested_category(self):
        urls = build_search_urls("그림체 공유", ["NAI", "R18_NAI"], 2, {
            "NAI": {"category": "nai"},
            "R18_NAI": {"category": "r18"},
        })
        self.assertEqual(len(urls), 2)
        self.assertIn("category=nai", urls[0])
        self.assertIn("category=r18", urls[1])

    def test_r18_collection_without_browser_session_fails_before_creating_run(self):
        with self.assertRaises(ArcaBrowserSessionRequired):
            collect_arca_styles(self.db_path, Path(self.temp.name) / "images", {
                "start_date": "2026-06-20",
                "end_date": "2026-06-21",
                "tabs": ["R18_NAI"],
            })
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_collection_runs").fetchone()[0], 0)

    def test_schema_and_payload_validation(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"arca_style_items", "arca_style_images", "arca_collection_runs"} <= tables)
        payload = normalize_collect_payload({"start_date": "2026-01-01", "end_date": "2026-01-03"})
        self.assertEqual(payload["keyword"], "그림체 공유")
        self.assertEqual(payload["tabs"], ["NAI", "R18_NAI"])
        self.assertEqual((payload["max_pages"], payload["max_posts"]), (0, 0))
        with self.assertRaises(ArcaCollectorError):
            normalize_collect_payload({"start_date": "bad", "end_date": "2026-01-03"})
        with self.assertRaises(ArcaCollectorError):
            normalize_collect_payload({"start_date": "2026-01-03", "end_date": "2026-01-01"})

    def test_normalizes_one_public_arca_article_url(self):
        self.assertEqual(
            normalize_arca_article_url("https://arca.live/b/aiart/174457459?mode=best#x"),
            "https://arca.live/b/aiart/174457459",
        )
        for value in (
            "https://example.com/b/aiart/174457459",
            "https://arca.live/b/other/174457459",
            "https://arca.live/b/aiart/not-a-number",
        ):
            with self.assertRaises(ArcaCollectorError):
                normalize_arca_article_url(value)

    def test_metadata_seed_excludes_paths_and_imports_only_once(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            collector_module._init_danbooru_seed_tables(conn)
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,representative_image_url,representative_image_path,prompt) VALUES(?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/1", "now", "now", "https://img/1.png", "adult.png", "artist:foo"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                (item_id, "https://img/1.png", "adult.png", "ok", "artist:foo", "artist:foo", "now"),
            )
            conn.execute(
                "INSERT INTO ratings(artist_tag,score,mode,representative_thumbnail_path,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("danbooru_artist", 5, "manual", "thumbnail.jpg", "now", "now"),
            )
            conn.execute(
                "INSERT INTO artist_cache(artist_tag,artist_post_count,updated_at) VALUES(?,?,?)",
                ("danbooru_artist", 1234, "now"),
            )
            conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)")
            conn.execute("INSERT INTO settings VALUES('novelai_app_key','must-not-export')")
        seed = Path(self.temp.name) / "seed.sqlite"
        exported = export_arca_style_seed(self.db_path, seed)
        self.assertEqual((exported["items"], exported["images"]), (1, 1))
        self.assertEqual((exported["ratings"], exported["artist_cache"]), (0, 1))
        with closing(sqlite3.connect(seed)) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(conn.execute("SELECT representative_image_path FROM arca_style_items").fetchone()[0], "")
            self.assertEqual(conn.execute("SELECT image_path FROM arca_style_images").fetchone()[0], "")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT artist_post_count FROM artist_cache").fetchone()[0], 1234)
            self.assertNotIn("settings", tables)
            self.assertNotIn("generated_images", tables)
            self.assertNotIn("art_styles", tables)

        destination = Path(self.temp.name) / "destination.sqlite"
        init_arca_style_tables(destination)
        first = import_arca_style_seed(destination, seed)
        second = import_arca_style_seed(destination, seed)
        self.assertEqual(first, {"imported": True, "items": 1, "images": 1})
        self.assertEqual(second, {"imported": False, "items": 0, "images": 0})
        with closing(sqlite3.connect(destination)) as conn:
            self.assertIsNone(conn.execute("SELECT artist_tag,score FROM ratings").fetchone())
            self.assertEqual(conn.execute("SELECT artist_post_count FROM artist_cache").fetchone()[0], 1234)

    def test_image_restore_refreshes_each_fixed_post_before_downloading(self):
        image_dir = Path(self.temp.name) / "images"
        old_url = "https://ac.namu.la/path/1.png?expires=1&key=old&type=orig"
        fresh_url = "https://ac.namu.la/path/1.png?expires=9999999999&key=fresh&type=orig"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,representative_image_url,metadata_status) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/1", "now", "now", old_url, "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,?,?)",
                (item_id, old_url, "", "ok", "now"),
            )
        job_id, missing = create_image_restore_job(self.db_path, image_dir)
        html = f'<div class="article-content"><img src="{fresh_url}"></div><span>NAI</span>'
        with (
            patch.object(collector_module, "fetch_html", return_value=html) as fetch,
            patch.object(collector_module, "download_image", return_value=(b"png-bytes", "image/png")) as download,
        ):
            result = restore_arca_style_images(self.db_path, image_dir, job_id, missing)
        self.assertEqual(result, {"restored": 1, "failed": 0, "downloaded_bytes": 9, "skipped_existing": False})
        fetch.assert_called_once()
        self.assertEqual(download.call_args.args[1], fresh_url)
        with closing(sqlite3.connect(self.db_path)) as conn:
            image_url, image_path = conn.execute("SELECT image_url,image_path FROM arca_style_images").fetchone()
            representative = conn.execute("SELECT representative_image_path FROM arca_style_items").fetchone()[0]
        self.assertEqual(image_url, fresh_url)
        self.assertEqual(representative, image_path)
        self.assertEqual((image_dir / image_path).read_bytes(), b"png-bytes")

        estimate = get_image_restore_estimate(self.db_path, image_dir)
        self.assertEqual((estimate["total_images"], estimate["local_images"], estimate["missing_images"]), (1, 1, 0))
        self.assertEqual(estimate["local_bytes"], 9)

    def test_image_restore_retries_429_in_the_same_run(self):
        image_dir = Path(self.temp.name) / "images"
        old_url = "https://ac.namu.la/path/2.png?expires=1&key=old&type=orig"
        fresh_url = "https://ac.namu.la/path/2.png?expires=9999999999&key=fresh&type=orig"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,representative_image_url,metadata_status) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/2", "now", "now", old_url, "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,?,?)",
                (item_id, old_url, "", "ok", "now"),
            )
        job_id, missing = create_image_restore_job(self.db_path, image_dir)
        html = f'<div class="article-content"><img src="{fresh_url}"></div><span>NAI</span>'
        response = requests.Response()
        response.status_code = 429
        rate_limit_error = requests.HTTPError("rate limited", response=response)
        with (
            patch.object(collector_module, "IMAGE_DOWNLOAD_INTERVAL_SECONDS", 0),
            patch.object(collector_module, "TRANSIENT_RETRY_DELAYS", (0,) * 7),
            patch.object(collector_module, "fetch_html", return_value=html),
            patch.object(
                collector_module,
                "download_image",
                side_effect=[rate_limit_error, (b"retried", "image/png")],
            ) as download,
        ):
            result = restore_arca_style_images(self.db_path, image_dir, job_id, missing)
        self.assertEqual(result["restored"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(download.call_count, 2)

    def test_image_restore_reuses_still_valid_signed_url_without_refetching_post(self):
        image_dir = Path(self.temp.name) / "images"
        fresh_url = "https://ac.namu.la/path/3.png?expires=9999999999&key=fresh&type=orig"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,representative_image_url,metadata_status) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/3", "now", "now", fresh_url, "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,?,?)",
                (item_id, fresh_url, "", "ok", "now"),
            )
        job_id, missing = create_image_restore_job(self.db_path, image_dir)
        with (
            patch.object(collector_module, "fetch_html", side_effect=AssertionError("post must not be fetched")),
            patch.object(collector_module, "download_image", return_value=(b"cached-url", "image/png")) as download,
        ):
            result = restore_arca_style_images(self.db_path, image_dir, job_id, missing)
        self.assertEqual(result["restored"], 1)
        download.assert_called_once()

    def test_image_restore_requires_login_for_missing_r18_images(self):
        image_dir = Path(self.temp.name) / "images"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,board_tab,collected_at,updated_at,metadata_status) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/4", "R18_NAI", "now", "now", "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,?,?)",
                (item_id, "https://ac.namu.la/path/4.png?expires=1&key=old", "", "ok", "now"),
            )
        with self.assertRaises(ArcaBrowserSessionRequired):
            create_image_restore_job(self.db_path, image_dir)

    def test_image_url_refresh_replaces_expired_signature_without_losing_metadata(self):
        image_dir = Path(self.temp.name) / "images"
        old_url = "https://ac.namu.la/path/image.png?expires=1&key=old&type=orig"
        fresh_url = "https://ac.namu.la/path/image.png?expires=9999999999&key=fresh&type=orig"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,board_tab,collected_at,updated_at,representative_image_url,metadata_status) VALUES(?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/1", "NAI", "now", "now", old_url, "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,prompt,created_at) VALUES(?,?,?,?,?,?)",
                (item_id, old_url, "", "ok", "artist:kept", "now"),
            )
        job_id, items = create_image_url_refresh_job(self.db_path, image_dir)
        html = f'<div class="article-content"><img src="{fresh_url}"></div><span>NAI</span>'

        with patch.object(collector_module, "fetch_html", return_value=html):
            result = refresh_arca_style_image_urls(self.db_path, image_dir, job_id, items)

        self.assertEqual(result, {"refreshed_urls": 1, "failed_posts": 0, "skipped_existing": False})
        with closing(sqlite3.connect(self.db_path)) as conn:
            image = conn.execute("SELECT image_url,prompt,image_path FROM arca_style_images").fetchone()
            representative = conn.execute("SELECT representative_image_url FROM arca_style_items").fetchone()[0]
        self.assertEqual(image, (fresh_url, "artist:kept", ""))
        self.assertEqual(representative, fresh_url)

    def test_image_url_refresh_requires_login_when_r18_images_are_missing(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,board_tab,collected_at,updated_at,metadata_status) VALUES(?,?,?,?,?)",
                ("https://arca.live/b/aiart/2", "R18_NAI", "now", "now", "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,created_at) VALUES(?,?,?,?,?)",
                (item_id, "https://ac.namu.la/path/r18.png?expires=1&key=old", "", "ok", "now"),
            )

        with self.assertRaises(ArcaBrowserSessionRequired):
            create_image_url_refresh_job(self.db_path, Path(self.temp.name) / "images")
    def test_collects_one_article_url_without_date_search(self):
        article_url = "https://arca.live/b/aiart/174457459"
        image_url = "https://img.example/direct.png"
        html = f'''<html><head><title>direct style - AI 그림 채널</title></head><body>
        <span>R18_NAI</span><time>2026-06-21</time>
        <div class="article-content"><p>shared style</p><img src="{image_url}"></div>
        </body></html>'''
        png = png_with_text("Comment", json.dumps({"prompt": "artist:foo", "seed": 1, "sampler": "k_euler"}))

        class Response:
            def __init__(self, text="", data=b"", content_type="text/html"):
                self.text, self.data = text, data
                self.headers = {"Content-Type": content_type}
            def raise_for_status(self): pass
            def iter_content(self, _size): return [self.data]

        class Session:
            def get(self, url, **_kwargs):
                return Response(text=html) if url == article_url else Response(data=png, content_type="image/png")

        result = collect_arca_style_url(self.db_path, Path(self.temp.name) / "images", article_url, session=Session())
        self.assertEqual(result["saved"], 1)
        detail = get_arca_style_detail(self.db_path, result["item_id"])
        self.assertEqual(detail["source_url"], article_url)
        self.assertEqual(detail["images"][0]["base_prompt"], "artist:foo")

    def test_direct_url_reuses_complete_local_metadata_item_before_network(self):
        article_url = "https://arca.live/b/aiart/174457459"
        image_dir = Path(self.temp.name) / "images"
        image_dir.mkdir()
        (image_dir / "cached.png").write_bytes(b"cached")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,representative_image_path,metadata_status,prompt) VALUES(?,?,?,?,?,?)",
                (article_url, "now", "now", "cached.png", "ok", "artist:cached"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,content_type,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (item_id, "https://img.example/cached.png", "cached.png", "image/png", "ok", "artist:cached", "artist:cached", "now"),
            )
        job_id = create_url_collection_job(self.db_path, article_url)

        with patch("arca_style_collector.create_arca_session", side_effect=AssertionError("network session must not be created")) as create_session:
            result = collect_arca_style_url(self.db_path, image_dir, article_url, job_id=job_id)

        create_session.assert_not_called()
        self.assertEqual(result, {
            "ok": True, "item_id": item_id, "saved": 0, "updated": 0,
            "downloaded_images": 0, "skipped_existing": True,
        })
        job = get_collection_job(self.db_path, job_id)
        self.assertEqual((job["status"], job["skipped_existing"], job["downloaded_images"]), ("completed", 1, 0))

        delete_arca_style(self.db_path, image_dir, item_id)
        png = png_with_text("Comment", json.dumps({"prompt": "artist:new", "seed": 1, "sampler": "k_euler"}))
        html = '<div class="article-content"><img src="https://img.example/new.png"></div>'

        class Response:
            def __init__(self, text="", data=b"", content_type="text/html"):
                self.text, self.data = text, data
                self.headers = {"Content-Type": content_type}
            def raise_for_status(self): pass
            def iter_content(self, _size): return [self.data]

        class TrackingSession:
            def __init__(self): self.calls = []
            def get(self, url, **_kwargs):
                self.calls.append(url)
                return Response(text=html) if url == article_url else Response(data=png, content_type="image/png")

        session = TrackingSession()
        recollected = collect_arca_style_url(self.db_path, image_dir, article_url, session=session)
        self.assertEqual(recollected["saved"], 1)
        self.assertIn(article_url, session.calls)

    def test_direct_url_applies_imported_browser_cookies_to_its_own_session(self):
        article_url = "https://arca.live/b/aiart/174457460"
        jar = CookieJar()
        jar.set_cookie(self._cookie(".arca.live", "session", "direct-secret"))
        connect_arca_cookie_jar(
            jar, "Chrome", validator=lambda _session: {"R18_NAI": {"category": "r18"}},
        )

        class Session:
            def __init__(self): self.cookies = CookieJar()

        session = Session()
        article = {
            "source_url": article_url, "article_id": "174457460", "board_tab": "R18_NAI",
            "title": "style", "author": "", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": ["https://img.example/style.png"],
        }
        with patch("arca_style_collector.create_arca_session", return_value=session), \
                patch("arca_style_collector.fetch_html", return_value="<html></html>"), \
                patch("arca_style_collector.extract_article_data", return_value=article), \
                patch("arca_style_collector._save_article", return_value=(0, 7)):
            collect_arca_style_url(self.db_path, Path(self.temp.name) / "images", article_url)

        self.assertEqual([(cookie.name, cookie.value) for cookie in session.cookies], [("session", "direct-secret")])

    def test_schema_adds_jobs_prompt_parts_and_recollection_links(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            image_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_style_images)")}
            run_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_collection_runs)")}
        self.assertTrue({
            "arca_collection_jobs",
            "arca_collection_run_items",
            "arca_collection_invalidations",
        } <= tables)
        self.assertTrue({"base_prompt", "character_prompts_json"} <= image_columns)
        self.assertIn("job_id", run_columns)

    def test_job_progress_is_persisted_and_reports_eta(self):
        job_id = create_collection_job(self.db_path, {
            "keyword": "그림체 공유", "tabs": ["NAI"],
            "start_date": "2026-06-01", "end_date": "2026-06-02",
            "max_pages": 2, "max_posts": 3,
        })
        update_collection_job(
            self.db_path, job_id, status="running", stage="downloading",
            scanned_pages=1, total_posts=3, scanned_posts=2,
            downloaded_images=4, average_post_seconds=2.5,
        )
        status = get_collection_job(self.db_path, job_id)
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["progress"], {"pages": [1, 2], "posts": [2, 3], "images": 4})
        self.assertEqual(status["estimated_remaining_seconds"], 2)

    def test_job_total_pages_counts_each_selected_tab(self):
        job_id = create_collection_job(self.db_path, {
            "keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"],
            "start_date": "2026-06-01", "end_date": "2026-06-02",
            "max_pages": 3, "max_posts": 10,
        })
        self.assertEqual(get_collection_job(self.db_path, job_id)["total_pages"], 6)

    def test_unlimited_collection_job_has_unknown_totals(self):
        job_id = create_collection_job(self.db_path, {
            "tabs": ["NAI"], "start_date": "2026-06-01", "end_date": "2026-06-02",
        })
        job = get_collection_job(self.db_path, job_id)
        self.assertIsNone(job["total_pages"])
        self.assertIsNone(job["total_posts"])

    def test_collection_job_can_pause_resume_and_stop_in_place(self):
        job_id = create_collection_job(self.db_path, {
            "tabs": ["NAI"], "start_date": "2026-06-01", "end_date": "2026-06-02",
        })
        collector_module._register_collection_control(job_id)
        try:
            pause_collection_job(self.db_path, job_id)
            waiter = threading.Thread(
                target=collector_module._wait_for_collection_control,
                args=(self.db_path, job_id, "scanning"),
            )
            waiter.start()
            for _ in range(20):
                if get_collection_job(self.db_path, job_id)["status"] == "paused":
                    break
                time.sleep(0.01)
            self.assertEqual(get_collection_job(self.db_path, job_id)["status"], "paused")
            self.assertEqual(resume_collection_job(self.db_path, Path(self.temp.name), job_id), job_id)
            waiter.join(1)
            self.assertFalse(waiter.is_alive())
            self.assertEqual(get_collection_job(self.db_path, job_id)["status"], "running")
            stop_collection_job(self.db_path, job_id)
            with self.assertRaises(collector_module.ArcaCollectionStopped):
                collector_module._wait_for_collection_control(self.db_path, job_id, "scanning")
        finally:
            collector_module._remove_collection_control(job_id)

    def test_interrupted_job_resume_starts_recovery_job_with_saved_request(self):
        job_id = create_collection_job(self.db_path, {
            "tabs": ["NAI"], "start_date": "2026-06-01", "end_date": "2026-06-02",
        })
        update_collection_job(self.db_path, job_id, status="interrupted", stage="interrupted")
        self.assertEqual(get_latest_resumable_collection_job(self.db_path)["id"], job_id)
        with patch("arca_style_collector.start_collection_job", return_value=99) as start:
            self.assertEqual(resume_collection_job(self.db_path, Path(self.temp.name), job_id), 99)
        self.assertEqual(start.call_args.args[1], Path(self.temp.name))
        self.assertEqual(start.call_args.args[2]["start_date"], "2026-06-01")

    def test_user_agent_is_browser_compatible_for_public_board_requests(self):
        self.assertTrue(USER_AGENT.startswith("Mozilla/5.0"))
        self.assertNotIn("NAIStyleCollector", USER_AGENT)

    def test_session_retries_transient_cloudflare_failures(self):
        session = create_arca_session()
        retries = session.get_adapter("https://").max_retries
        self.assertEqual(retries.total, 3)
        self.assertTrue({429, 500, 502, 503, 504} <= set(retries.status_forcelist))

    def test_search_is_limited_to_titles(self):
        url = build_search_urls("그림체 공유", ["NAI"], 1)[0]
        self.assertIn("target=title", url)

    def test_list_hides_items_without_prompts(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt) VALUES(?,?,?,?,?,?)", ("https://arca.live/b/aiart/1", "now", "now", "그림체 하나 공유", "NAI", "artist prompt"))
            conn.execute("INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt) VALUES(?,?,?,?,?,?)", ("https://arca.live/b/aiart/2", "now", "now", "그림체 공유 빈값", "NAI", ""))
            conn.execute("INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt) VALUES(?,?,?,?,?,?)", ("https://arca.live/b/aiart/3", "now", "now", "정보 자료", "NAI", "not a style"))
            conn.execute("INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)", ("https://arca.live/b/aiart/4", "now", "now", "그림체 공유 본문", "NAI", "body fallback", "body_only"))
            conn.execute("UPDATE arca_style_items SET metadata_status='ok' WHERE source_url='https://arca.live/b/aiart/1'")
        self.assertEqual([item["title"] for item in list_arca_styles(self.db_path)], ["그림체 하나 공유"])

    def test_list_sorts_by_arca_post_date_with_missing_dates_last(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index, posted_at in enumerate(("2026-06-18", "2026-06-20", ""), 1):
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status,posted_at) VALUES(?,?,?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/sort-{index}", "now", "now", f"그림체 공유 {index}", "NAI", "artist prompt", "ok", posted_at),
                )
        newest = list_arca_styles(self.db_path, {"sort": "posted_desc"})
        oldest = list_arca_styles(self.db_path, {"sort": "posted_asc"})
        self.assertEqual([item["posted_at"] for item in newest], ["2026-06-20", "2026-06-18", ""])
        self.assertEqual([item["posted_at"] for item in oldest], ["2026-06-18", "2026-06-20", ""])

    def test_list_includes_direct_url_items_regardless_of_title(self):
        source_url = "https://arca.live/b/aiart/174495066"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                (source_url, "now", "now", "Unrelated article title", "NAI", "artist prompt", "ok"),
            )
            conn.execute(
                "INSERT INTO arca_collection_jobs(request_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?)",
                (json.dumps({"source_url": source_url}), "completed", "completed", "now", "now"),
            )

        self.assertEqual([item["source_url"] for item in list_arca_styles(self.db_path)], [source_url])

    def test_list_rejects_unknown_date_sort(self):
        with self.assertRaises(ArcaCollectorError):
            list_arca_styles(self.db_path, {"sort": "collected_desc"})

    def test_item_schema_supports_recommendation_and_view_counts(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_style_items)")}
        self.assertTrue({"recommendation_count", "view_count"} <= columns)

    def test_list_sorts_by_recommendations_and_views(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index, (recommendations, views) in enumerate(((2, 900), (20, 100), (5, 3000)), 1):
                source_url = f"https://arca.live/b/aiart/stats-{index}"
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status,recommendation_count,view_count) VALUES(?,?,?,?,?,?,?,?,?)",
                    (source_url, "now", "now", f"Stats {index}", "NAI", "artist prompt", "ok", recommendations, views),
                )
                conn.execute(
                    "INSERT INTO arca_collection_jobs(request_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (json.dumps({"source_url": source_url}), "completed", "completed", "now", "now"),
                )
        self.assertEqual([item["recommendation_count"] for item in list_arca_styles(self.db_path, {"sort": "recommend_desc"})], [20, 5, 2])
        self.assertEqual([item["view_count"] for item in list_arca_styles(self.db_path, {"sort": "views_desc"})], [3000, 900, 100])

    def test_list_page_reaches_all_rows_and_filters_minimum_recommendations(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index, recommendations in enumerate((1, 5, 10, 20), 1):
                conn.execute(
                    "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status,recommendation_count) VALUES(?,?,?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/page-{index}", "now", "now", f"그림체 공유 {index}", "NAI", "artist prompt", "ok", recommendations),
                )
        result = get_arca_style_page(self.db_path, {
            "page": 2, "per_page": 2, "recommendation_min": 5, "sort": "recommend_desc",
        })
        self.assertEqual((result["page"], result["per_page"], result["total"], result["total_pages"]), (2, 2, 3, 2))
        self.assertEqual([item["recommendation_count"] for item in result["items"]], [5])
        with self.assertRaises(ArcaCollectorError):
            get_arca_style_page(self.db_path, {"recommendation_min": -1})

    def test_list_loads_style_group_counts_with_one_database_connection(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index in range(2):
                item_id = conn.execute(
                    "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/bulk-{index}", "now", "now", f"그림체 공유 {index}", "NAI", "artist:foo", "ok"),
                ).lastrowid
                for image_index in range(2):
                    prompt = f"artist:foo, watercolor, {image_index + 1}girl"
                    conn.execute(
                        "INSERT INTO arca_style_images(item_id,image_url,prompt,base_prompt,created_at) VALUES(?,?,?,?,?)",
                        (item_id, f"https://img/{index}-{image_index}.png", prompt, prompt, "now"),
                    )

        with patch("arca_style_collector._connect", wraps=collector_module._connect) as connect:
            items = list_arca_styles(self.db_path)

        self.assertEqual(connect.call_count, 1)
        self.assertEqual([item["style_group_count"] for item in items], [1, 1])

    def test_statistics_separates_explicit_artists_and_quality_tags_for_shared_styles(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            shared_item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/shared", "now", "now", "그림체 공유", "NAI", "artist:foo", "ok"),
            ).lastrowid
            conn.execute("UPDATE arca_style_items SET recommendation_count=40 WHERE id=?", (shared_item_id,))
            prompts = [
                "artist: Foo, best quality, masterpiece, 1girl",
                "artists:foo, {{amazing quality, highres}}, watercolor",
                "artist:bar, 4::masterpiece, newest",
            ]
            for index, prompt in enumerate(prompts, 1):
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                    (shared_item_id, f"https://img/shared-{index}.png", "ok", prompt, prompt, "now"),
                )
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                (shared_item_id, "https://img/not-metadata.png", "no_metadata", "artist:hidden, best quality", "artist:hidden, best quality", "now"),
            )

            direct_url = "https://arca.live/b/aiart/direct"
            direct_item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                (direct_url, "now", "now", "직접 추가", "R18_NAI", "artist:direct", "ok"),
            ).lastrowid
            conn.execute("UPDATE arca_style_items SET recommendation_count=100 WHERE id=?", (direct_item_id,))
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                (direct_item_id, "https://img/direct.png", "ok", "artist:direct, very aesthetic", "artist:direct, very aesthetic", "now"),
            )
            conn.execute(
                "INSERT INTO arca_collection_jobs(request_json,status,stage,created_at,updated_at) VALUES(?,?,?,?,?)",
                (json.dumps({"source_url": direct_url}), "completed", "completed", "now", "now"),
            )

            misc_item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/misc", "now", "now", "일반 게시글", "NAI", "artist:hidden", "ok"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?)",
                (misc_item_id, "https://img/misc.png", "ok", "artist:hidden, best quality", "artist:hidden, best quality", "now"),
            )

        stats = get_arca_style_statistics(self.db_path)

        self.assertEqual({key: stats[key] for key in (
            "analyzed_image_count", "analyzed_post_count", "analyzed_tag_count",
            "images_with_artist", "images_with_quality",
        )}, {
            "analyzed_image_count": 4, "analyzed_post_count": 2, "analyzed_tag_count": 13,
            "images_with_artist": 4, "images_with_quality": 4,
        })
        self.assertEqual({entry["tag"]: entry["count"] for entry in stats["artists"]}, {
            "artist:foo": 2, "artist:bar": 1, "artist:direct": 1,
        })
        artist_foo = next(entry for entry in stats["artists"] if entry["tag"] == "artist:foo")
        self.assertEqual(artist_foo["representative_image"]["prompt"], prompts[0])
        self.assertEqual((artist_foo["average_recommendations"], artist_foo["max_recommendations"]), (40.0, 40))
        quality = {entry["tag"]: entry for entry in stats["quality_tags"]}
        self.assertEqual({tag: entry["count"] for tag, entry in quality.items()}, {
            "masterpiece": 2, "amazing quality": 1, "best quality": 1,
            "highres": 1, "newest": 1, "very aesthetic": 1,
        })
        self.assertEqual((quality["masterpiece"]["average_weight"], quality["masterpiece"]["max_weight"]), (2.5, 4.0))
        self.assertEqual(stats["quality_sequences"][0]["count"], 1)
        self.assertIn("representative_image", stats["quality_sequences"][0])
        self.assertTrue(all(entry["size"] == len(entry["tags"]) for entry in stats["quality_bundles"]))
        self.assertIn(
            {"source": "best quality", "target": "masterpiece", "count": 1, "percentage": 25.0},
            stats["quality_network"]["edges"],
        )
        quality_detail = get_arca_tag_statistics(self.db_path, "quality", "masterpiece")
        self.assertIn(
            {"tag": "best quality", "count": 1, "percentage": 50.0},
            quality_detail["related_tags"],
        )
        sequence_detail = get_arca_quality_sequence_statistics(self.db_path, ["best quality", "masterpiece"])
        self.assertEqual(sequence_detail["image_count"], 1)
        self.assertEqual(sequence_detail["images"][0]["prompt"], prompts[0])
        recommended = get_arca_style_statistics(self.db_path, {"recommendation_min": 80})
        self.assertEqual(recommended["analyzed_image_count"], 1)
        self.assertEqual([entry["tag"] for entry in recommended["artists"]], ["artist:direct"])

    def test_statistics_rejects_invalid_recommendation_ranges(self):
        with self.assertRaises(ArcaCollectorError):
            get_arca_style_statistics(self.db_path, {"recommendation_min": "bad"})
        with self.assertRaises(ArcaCollectorError):
            get_arca_style_statistics(self.db_path, {"recommendation_min": 20, "recommendation_max": 10})

    def test_weight_parser_preserves_explicit_groups_wrappers_and_negative_values(self):
        parsed = parse_weighted_prompt_tags(
            "1.2::artist:foo, masterpiece::, {{highres}}, [aesthetic], -2::artist:bar::"
        )
        self.assertEqual([(entry["tag"], entry["weight"]) for entry in parsed], [
            ("artist:foo", 1.2), ("masterpiece", 1.2), ("highres", 1.1025),
            ("aesthetic", 0.952381), ("artist:bar", -2.0),
        ])

    def test_tag_statistics_sorts_images_by_highest_weight_and_builds_ranges(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title,board_tab,prompt,metadata_status) VALUES(?,?,?,?,?,?,?)",
                ("https://arca.live/b/aiart/weighted", "now", "now", "그림체 공유", "NAI", "artist:foo", "ok"),
            ).lastrowid
            for index, prompt in enumerate(("0.8::artist:foo::, artist:bar", "1.8::artist:foo::", "artist:foo"), 1):
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,image_path,metadata_status,prompt,base_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                    (item_id, f"https://img/{index}.png", f"{index}.png", "ok", prompt, prompt, "now"),
                )
        detail = get_arca_tag_statistics(self.db_path, "artist", "artist:foo", 2)
        self.assertEqual((detail["image_count"], detail["occurrence_count"]), (3, 3))
        self.assertEqual([image["weight"] for image in detail["images"]], [1.8, 1.0])
        self.assertEqual(detail["images"][0]["prompt"], "1.8::artist:foo::")
        self.assertEqual(sum(entry["count"] for entry in detail["weights"]["bins"]), 3)
        self.assertEqual(detail["related_tags"], [{"tag": "artist:bar", "count": 1, "percentage": 33.3}])

    def test_statistics_returns_a_stable_empty_interface(self):
        self.assertEqual(get_arca_style_statistics(self.db_path), {
            "analyzed_image_count": 0,
            "analyzed_post_count": 0,
            "analyzed_tag_count": 0,
            "images_with_artist": 0,
            "images_with_quality": 0,
            "artists": [],
            "quality_tags": [],
            "quality_sequences": [],
            "quality_bundles": [],
            "quality_network": {"nodes": [], "edges": []},
            "collection_scope_note": "저장된 공유 그림체 이미지 기준이며, 수집은 선택한 날짜 범위의 검색 종료 지점까지 진행됩니다.",
        })

    def test_coverage_merges_and_subtracts_dates(self):
        merged = merge_date_intervals([
            (date(2026, 1, 1), date(2026, 1, 3)),
            (date(2026, 1, 4), date(2026, 1, 5)),
            (date(2026, 1, 8), date(2026, 1, 9)),
        ])
        self.assertEqual(merged, [(date(2026, 1, 1), date(2026, 1, 5)), (date(2026, 1, 8), date(2026, 1, 9))])
        self.assertEqual(
            uncovered_date_intervals(date(2026, 1, 1), date(2026, 1, 10), merged),
            [(date(2026, 1, 6), date(2026, 1, 7)), (date(2026, 1, 10), date(2026, 1, 10))],
        )

    def test_only_completed_runs_count_as_coverage(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for status, start, end in (("completed", "2026-01-01", "2026-01-03"), ("failed", "2026-01-04", "2026-01-05")):
                conn.execute(
                    "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    ("그림체 공유", "NAI,R18_NAI", start, end, 5, 80, status, SEARCH_SCOPE, "now", "now"),
                )
        coverage = get_completed_coverage(self.db_path, {"keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"], "max_pages": 5, "max_posts": 80})
        self.assertEqual(coverage, [(date(2026, 1, 1), date(2026, 1, 3))])

    def test_completed_coverage_skips_login_and_category_network(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "R18_NAI", "2026-06-01", "2026-06-02", 1, 5, "completed", SEARCH_SCOPE, "now", "now"),
            )
        payload = {
            "keyword": "그림체 공유", "tabs": ["R18_NAI"],
            "start_date": "2026-06-01", "end_date": "2026-06-02",
            "max_pages": 1, "max_posts": 5,
        }

        with patch("arca_style_collector.get_arca_browser_session_status", side_effect=AssertionError("login must not be checked")) as login_status, \
                patch("arca_style_collector.create_arca_session", side_effect=AssertionError("session must not be created")) as create_session, \
                patch("arca_style_collector.discover_category_params", side_effect=AssertionError("category must not be fetched")) as discover:
            result = collect_arca_styles(self.db_path, Path(self.temp.name) / "images", payload)

        self.assertTrue(result["skipped_existing"])
        login_status.assert_not_called()
        create_session.assert_not_called()
        discover.assert_not_called()

    def test_search_prefilters_rows_fetches_articles_in_parallel_and_stops_at_post_limit(self):
        def row(article_id, badge, posted_at):
            return (
                f'<a class="vrow column" href="/b/aiart/{article_id}">'
                f'<span class="badge">{badge}</span><span class="title">그림체 공유 {article_id}</span>'
                f'<time datetime="{posted_at}T12:00:00Z"></time></a>'
            )

        search_html = "".join([
            row(1, "NAI", "2026-06-01"),
            row(2, "🔞 NAI", "2026-06-11"),
            row(3, "NAI", "2026-06-11"),
            row(4, "NAI", "2026-06-11"),
            row(5, "NAI", "2026-06-11"),
            row(6, "NAI", "2026-06-11"),
            row(7, "NAI", "2026-06-11"),
        ])
        lock = threading.Lock()
        search_calls, article_calls, article_sessions = [], [], []
        active_articles = 0
        max_active_articles = 0
        session_instances = []

        class Session:
            def __init__(self):
                self.headers = {}
                self.cookies = CookieJar()
                session_instances.append(self)
            def close(self): pass

        def fake_fetch(session, url):
            nonlocal active_articles, max_active_articles
            if "keyword=" in url:
                search_calls.append(url)
                return search_html
            with lock:
                article_calls.append(url)
                article_sessions.append(session)
                active_articles += 1
                max_active_articles = max(max_active_articles, active_articles)
            time.sleep(0.03)
            with lock:
                active_articles -= 1
            return '<div class="article-content"><img src="https://img.example/style.png"></div>'

        saved_active = 0
        max_saved_active = 0

        def fake_save(_db_path, _image_dir, _session, article, summary, run_id=None):
            nonlocal saved_active, max_saved_active
            saved_active += 1
            max_saved_active = max(max_saved_active, saved_active)
            time.sleep(0.005)
            saved_active -= 1
            return 0, int(article["article_id"])

        payload = {
            "keyword": "그림체 공유", "tabs": ["NAI"],
            "start_date": "2026-06-10", "end_date": "2026-06-12",
            "max_pages": 2, "max_posts": 4,
        }
        with patch("arca_style_collector.create_arca_session", side_effect=Session), \
                patch("arca_style_collector.discover_category_params", return_value={"NAI": {"category": "nai"}}), \
                patch("arca_style_collector.fetch_html", side_effect=fake_fetch), \
                patch("arca_style_collector._save_article", side_effect=fake_save):
            result = collect_arca_styles(self.db_path, Path(self.temp.name) / "images", payload)

        self.assertEqual((result["scanned_pages"], result["scanned_posts"]), (1, 4))
        self.assertEqual(len(search_calls), 1)
        self.assertEqual(set(article_calls), {f"https://arca.live/b/aiart/{index}" for index in range(3, 7)})
        self.assertGreaterEqual(max_active_articles, 2)
        self.assertLessEqual(max_active_articles, 4)
        self.assertEqual(max_saved_active, 1)
        self.assertEqual(len({id(session) for session in article_sessions}), 4)
        self.assertNotIn(session_instances[0], article_sessions)

    def test_archive_search_locates_2025_before_scanning_target_window(self):
        def row(article_id, posted_at):
            return (
                f'<a class="vrow column" href="/b/aiart/{article_id}">'
                f'<span class="badge">NAI</span><span class="title">style</span>'
                f'<time datetime="{posted_at}T12:00:00Z"></time></a>'
            )

        search_pages = {
            1: row(1, "2026-06-01"),
            2: row(2, "2026-01-01"),
            3: row(3, "2025-06-15"),
            4: row(4, "2024-12-31"),
        }
        search_calls, article_calls, saved = [], [], []

        class Session:
            def __init__(self):
                self.headers = {}
                self.cookies = CookieJar()
            def close(self): pass

        def fake_fetch(_session, url):
            if "keyword=" in url:
                page = int(url.rsplit("p=", 1)[-1])
                search_calls.append(page)
                return search_pages.get(page, "")
            article_calls.append(url)
            return '<div class="article-content"></div>'

        def fake_save(_db_path, _image_dir, _session, article, _summary, run_id=None):
            saved.append(article["article_id"])
            return 0, int(article["article_id"])

        payload = {
            "keyword": "style", "tabs": ["NAI"],
            "start_date": "2025-01-01", "end_date": "2025-12-31",
        }
        with patch("arca_style_collector.create_arca_session", side_effect=Session), \
                patch("arca_style_collector.discover_category_params", return_value={"NAI": {"category": "nai"}}), \
                patch("arca_style_collector.fetch_html", side_effect=fake_fetch), \
                patch("arca_style_collector._save_article", side_effect=fake_save):
            result = collect_arca_styles(self.db_path, Path(self.temp.name) / "images", payload)

        self.assertFalse(result["partial"])
        self.assertEqual(search_calls, [1, 2, 4, 3])
        self.assertEqual(saved, ["3"])
        self.assertEqual(article_calls, ["https://arca.live/b/aiart/3"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            status = conn.execute("SELECT status FROM arca_collection_runs").fetchone()[0]
        self.assertEqual(status, "completed")

    def test_post_limit_marks_archive_range_partial_without_coverage(self):
        def row(article_id):
            return (
                f'<a class="vrow column" href="/b/aiart/{article_id}">'
                f'<span class="badge">NAI</span><span class="title">style</span>'
                f'<time datetime="2025-06-15T12:00:00Z"></time></a>'
            )

        class Session:
            def __init__(self):
                self.headers = {}
                self.cookies = CookieJar()
            def close(self): pass

        def fake_fetch(_session, url):
            if "keyword=" in url:
                return row(1) + row(2) if url.endswith("p=1") else ""
            return '<div class="article-content"></div>'

        payload = {
            "keyword": "style", "tabs": ["NAI"],
            "start_date": "2025-01-01", "end_date": "2025-12-31",
            "max_pages": 5, "max_posts": 1,
        }
        with patch("arca_style_collector.create_arca_session", side_effect=Session), \
                patch("arca_style_collector.discover_category_params", return_value={"NAI": {"category": "nai"}}), \
                patch("arca_style_collector.fetch_html", side_effect=fake_fetch), \
                patch("arca_style_collector._save_article", return_value=(0, 1)):
            result = collect_arca_styles(self.db_path, Path(self.temp.name) / "images", payload)

        self.assertTrue(result["partial"])
        self.assertTrue(result["warning"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            status = conn.execute("SELECT status FROM arca_collection_runs").fetchone()[0]
        self.assertEqual(status, "partial")
        params = normalize_collect_payload(payload)
        self.assertEqual(get_completed_coverage(self.db_path, params), [])
        self.assertEqual(
            uncovered_date_intervals(date(2025, 1, 1), date(2025, 12, 31), get_completed_coverage(self.db_path, params)),
            [(date(2025, 1, 1), date(2025, 12, 31))],
        )

    def test_delete_reopens_only_the_item_date_for_its_search(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,posted_at,collected_at,updated_at) VALUES(?,?,?,?)",
                ("https://arca.live/b/aiart/delete-me", "2026-06-10", "now", "now"),
            ).lastrowid
            run_id = conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,search_scope,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-06-01", "2026-06-30", 5, 80, SEARCH_SCOPE, "completed", "now", "now"),
            ).lastrowid
            conn.execute("INSERT INTO arca_collection_run_items(run_id,item_id) VALUES(?,?)", (run_id, item_id))
        result = delete_arca_style(self.db_path, Path(self.temp.name) / "images", item_id)
        self.assertEqual(result["recollect_date"], "2026-06-10")
        params = normalize_collect_payload({
            "keyword": "그림체 공유", "start_date": "2026-06-01", "end_date": "2026-06-30",
            "max_pages": 5, "max_posts": 80,
        })
        coverage = get_completed_coverage(self.db_path, params)
        self.assertEqual(uncovered_date_intervals(date(2026, 6, 1), date(2026, 6, 30), coverage), [
            (date(2026, 6, 10), date(2026, 6, 10)),
        ])

    def test_old_content_search_runs_do_not_cover_title_searches(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-01-01", "2026-01-03", 5, 80, "completed", "all", "now", "now"),
            )
        coverage = get_completed_coverage(self.db_path, {"keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"], "max_pages": 5, "max_posts": 80})
        self.assertEqual(coverage, [])

    def test_pre_archive_locator_runs_do_not_cover_new_searches(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-01-01", "2026-01-03", 5, 80, "completed", "title-category-session-v5", "now", "now"),
            )
        coverage = get_completed_coverage(self.db_path, {"keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"], "max_pages": 5, "max_posts": 80})
        self.assertEqual(coverage, [])

    def test_pre_stealth_title_runs_do_not_block_metadata_recollection(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-01-01", "2026-01-03", 5, 80, "completed", "title", "now", "now"),
            )
        coverage = get_completed_coverage(self.db_path, {"keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"], "max_pages": 5, "max_posts": 80})
        self.assertEqual(coverage, [])

    def test_pre_validation_stealth_runs_do_not_block_clean_recollection(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-01-01", "2026-01-03", 5, 80, "completed", "title-stealth-v1", "now", "now"),
            )
        coverage = get_completed_coverage(self.db_path, {"keyword": "그림체 공유", "tabs": ["NAI", "R18_NAI"], "max_pages": 5, "max_posts": 80})
        self.assertEqual(coverage, [])

    def test_html_candidates_and_metadata(self):
        html = '''<a href="/b/aiart/123?x=1"><img data-src="//img.example/a.png"></a>
        <img src="/thumb.jpg" data-original="https://img.example/original.png">
        <picture><source srcset="https://img.example/one.webp 1x, https://img.example/two.webp 2x"></picture>'''
        self.assertEqual(extract_article_links(html, "https://arca.live"), ["https://arca.live/b/aiart/123"])
        candidates = extract_image_candidates(html, "https://arca.live/b/aiart/123")
        self.assertIn("https://img.example/a.png", candidates)
        self.assertIn("https://img.example/original.png", candidates)
        self.assertIn("https://img.example/two.webp", candidates)
        meta = extract_novelai_metadata(png_with_text("Comment", json.dumps({"prompt": "artist style", "uc": "bad", "seed": 7, "sampler": "k_euler"})), "image/png")
        self.assertEqual(meta["metadata_status"], "ok")
        self.assertEqual(meta["prompt"], "artist style")
        self.assertEqual(meta["negative_prompt"], "bad")
        self.assertEqual(meta["seed"], "7")
        self.assertEqual(parse_body_prompt_fallback("Prompt: pretty\nUC: blurry"), {"prompt": "pretty", "negative_prompt": "blurry"})

    def test_rejects_generic_png_prompt_metadata(self):
        meta = extract_novelai_metadata(
            png_with_text("Comment", json.dumps({"prompt": "http://www.pdf-tools.com"})),
            "image/png",
        )
        self.assertEqual(meta["metadata_status"], "no_metadata")
        self.assertEqual(meta["base_prompt"], "")

    def test_revalidation_clears_existing_generic_prompt_rows(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at) VALUES(?,?,?)",
                ("https://arca.live/b/aiart/generic", "now", "now"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,raw_metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                (item_id, "https://img/generic.png", "ok", "Celsys Studio Tool", json.dumps({"prompt": "Celsys Studio Tool"}), "now"),
            )
        revalidate_stored_metadata(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute("SELECT metadata_status,prompt,base_prompt FROM arca_style_images WHERE item_id=?", (item_id,)).fetchone()
        self.assertEqual(row, ("no_metadata", "", ""))

    def test_extracts_v4_base_negative_and_character_prompts(self):
        payload = {
            "v4_prompt": {"caption": {
                "base_caption": "artist:foo, watercolor",
                "char_captions": [
                    {"char_caption": "1girl, blue hair", "centers": [{"x": 0.3, "y": 0.4}]},
                    {"char_caption": "1boy, black hair", "centers": [{"x": 0.7, "y": 0.4}]},
                ],
            }},
            "v4_negative_prompt": {"caption": {"base_caption": "lowres, blurry"}},
            "seed": 7,
        }
        meta = extract_novelai_metadata(png_with_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(meta["base_prompt"], "artist:foo, watercolor")
        self.assertEqual(meta["negative_prompt"], "lowres, blurry")
        self.assertEqual([entry["prompt"] for entry in meta["character_prompts"]], [
            "1girl, blue hair", "1boy, black hair",
        ])

    def test_extracts_numeric_ending_tags_with_safe_closing_space(self):
        payload = {
            "v4_prompt": {"caption": {
                "base_caption": "1.5::artist:matrix16::, 2::year 2025::",
                "char_captions": [{"char_caption": "1.2::character 2::"}],
            }},
            "v4_negative_prompt": {"caption": {"base_caption": "-2::bad 3::"}},
            "seed": 7,
        }
        meta = extract_novelai_metadata(png_with_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(meta["base_prompt"], "1.5::artist:matrix16 ::, 2::year 2025 ::")
        self.assertEqual(meta["negative_prompt"], "-2::bad 3 ::")
        self.assertEqual(meta["character_prompts"][0]["prompt"], "1.2::character 2 ::")

    def test_prompt_presets_keep_non_character_tags_and_full_negative(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index, (prompt, negative, recommendations) in enumerate((
                ("1.2::artist:alpha::, masterpiece, 1.1::best quality::, soft lighting, scenery, 1girl, blue_hair, full body", "lowres, bad hands", 2),
                ("artist:beta, amazing quality, scenery", "blurry, text", 100),
            ), 1):
                item_id = conn.execute(
                    "INSERT INTO arca_style_items(source_url,title,board_tab,metadata_status,prompt,negative_prompt,recommendation_count,collected_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/preset-{index}", "그림체 공유", "NAI", "ok", prompt, negative, recommendations, "now", "now"),
                ).lastrowid
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,negative_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                    (item_id, f"https://img/{index}.png", "ok", prompt, prompt, negative, "now"),
                )

        result = get_style_maker_prompt_presets(self.db_path, ["alpha"])

        self.assertEqual(result["selected_artist_count"], 1)
        self.assertEqual(
            result["presets"][0]["base_prompt"],
            "masterpiece, 1.1::best quality::, soft lighting, scenery",
        )
        self.assertEqual(result["presets"][0]["negative_prompt"], "lowres, bad hands")
        self.assertEqual(result["presets"][0]["match_count"], 1)
        self.assertEqual(
            result["presets"][0]["representative_image"]["remote_image_url"],
            "https://img/1.png",
        )
        self.assertEqual(
            [item["prompt"] for item in result["presets"][0]["excluded_tags"]],
            ["1girl", "blue_hair", "full body"],
        )
        self.assertNotIn("artist:alpha", result["presets"][0]["base_prompt"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_prompt_preset_index").fetchone()[0], 2)
        with patch("arca_style_collector._prompt_preset_parts", side_effect=AssertionError("cache miss")):
            cached = get_style_maker_prompt_presets(self.db_path, ["alpha"])
        self.assertEqual(cached, result)
        self.assertEqual(
            {item["artist"] for item in get_shared_style_artist_pool(self.db_path)},
            {"alpha", "beta"},
        )

    def test_prompt_presets_keep_quality_only_and_negative_only_candidates(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for index, (prompt, negative) in enumerate((
                ("artist:alpha, masterpiece, best quality", ""),
                ("artist:alpha", "lowres, bad hands"),
            ), 1):
                item_id = conn.execute(
                    "INSERT INTO arca_style_items(source_url,title,board_tab,metadata_status,prompt,negative_prompt,collected_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (f"https://arca.live/b/aiart/partial-{index}", "그림체 공유", "NAI", "ok", prompt, negative, "now", "now"),
                ).lastrowid
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,base_prompt,negative_prompt,created_at) VALUES(?,?,?,?,?,?,?)",
                    (item_id, f"https://img/partial-{index}.png", "ok", prompt, prompt, negative, "now"),
                )

        presets = get_style_maker_prompt_presets(self.db_path, ["alpha"], limit=1)["presets"]

        self.assertTrue(any(item["base_prompt"] == "masterpiece, best quality" for item in presets))
        self.assertTrue(any(item["negative_prompt"] == "lowres, bad hands" for item in presets))

    def test_namu_cdn_candidates_request_original_image_bytes(self):
        candidates = extract_image_candidates(
            '<img src="//ac.namu.la/path/image.png?expires=1&amp;key=abc">',
            "https://arca.live/b/aiart/2",
        )
        self.assertEqual(candidates, ["https://ac.namu.la/path/image.png?expires=1&key=abc&type=orig"])

    def test_search_results_exclude_notices_side_links_and_wrong_categories(self):
        html = '''
        <a class="vrow column notice notice-board" href="/b/aiart/1"><span class="badge">NAI</span><span class="title">그림체 공유 공지</span></a>
        <a class="vrow column" href="/b/aiart/2"><span class="badge badge-success">NAI</span><span class="title">4.5F 그림체 하나 공유</span><time datetime="2026-06-18T13:47:47.000Z"></time></a>
        <a class="vrow column" href="/b/aiart/3"><span class="badge">정보·자료</span><span class="title">그림체 공유 자료</span></a>
        <a class="vrow column" href="/b/aiart/4"><span class="badge">NAI</span><span class="title">일반 질문</span></a>
        <aside><a href="/b/aiart/99?mode=best">댓글 인기글</a></aside>
        '''
        self.assertEqual(extract_search_results(html, "https://arca.live", "그림체 공유"), [{
            "source_url": "https://arca.live/b/aiart/2",
            "title": "4.5F 그림체 하나 공유",
            "board_tab": "NAI",
            "posted_at": "2026-06-18",
        }])

    def test_article_data_uses_only_article_content_not_comments(self):
        html = '''
        <div class="article-body"><div class="fr-view article-content">
          <p>Prompt: body prompt</p><img src="https://img/body.png">
        </div></div>
        <section class="comments"><p>Prompt: comment prompt</p><img src="https://img/comment.png"></section>
        '''
        article = extract_article_data(html, "https://arca.live/b/aiart/2")
        self.assertIn("body prompt", article["body_text"])
        self.assertNotIn("comment prompt", article["body_text"])
        self.assertEqual(article["image_urls"], ["https://img/body.png"])

    def test_article_data_extracts_recommendation_and_view_counts(self):
        html = '''
        <div class="article-info article-info-section">
          <span class="head">\ucd94\ucc9c</span><span class="body">26</span>
          <span class="head">\uc870\ud68c\uc218</span><span class="body">3,531</span>
        </div>
        <div class="fr-view article-content"><img src="https://example.com/a.png"></div>
        '''
        article = extract_article_data(html, "https://arca.live/b/aiart/2")
        self.assertEqual(article["recommendation_count"], 26)
        self.assertEqual(article["view_count"], 3531)

    def test_detail_keeps_every_image_prompt(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute("INSERT INTO arca_style_items(source_url,collected_at,updated_at,prompt) VALUES(?,?,?,?)", ("https://arca.live/b/aiart/5", "now", "now", "first")).lastrowid
            for index, prompt in enumerate(("first", "second", ""), 1):
                conn.execute("INSERT INTO arca_style_images(item_id,image_url,prompt,created_at) VALUES(?,?,?,?)", (item_id, f"https://img/{index}.png", prompt, "now"))
        detail = get_arca_style_detail(self.db_path, item_id)
        self.assertEqual([entry["prompt"] for entry in detail["prompts"]], ["first", "second"])

    def test_groups_similar_style_prompts_and_keeps_singletons(self):
        images = [
            {"id": 1, "base_prompt": "artist:foo, watercolor, 1girl, blue hair", "negative_prompt": "lowres", "character_prompts": []},
            {"id": 2, "base_prompt": "watercolor, artist:foo, 1boy, black hair", "negative_prompt": "lowres, blurry", "character_prompts": []},
            {"id": 3, "base_prompt": "artist:bar, 3d render, robot", "negative_prompt": "bad hands", "character_prompts": []},
        ]
        groups = build_style_groups(images)
        self.assertEqual([[image["id"] for image in group["images"]] for group in groups], [[1, 2], [3]])
        self.assertEqual(groups[0]["common_base_tags"], ["artist:foo", "watercolor"])
        self.assertTrue(groups[1]["singleton"])

    def test_top_level_commas_preserve_emphasis_groups(self):
        self.assertEqual(split_prompt_tags("{artist:foo, watercolor}, 1girl"), [
            "{artist:foo, watercolor}", "1girl",
        ])

    def test_detail_exposes_structured_prompt_groups(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,prompt) VALUES(?,?,?,?)",
                ("https://arca.live/b/aiart/structured", "now", "now", "artist:foo"),
            ).lastrowid
            for index, prompt in enumerate((
                "artist:foo, watercolor, 1girl",
                "artist:foo, watercolor, 1boy",
            ), 1):
                conn.execute(
                    "INSERT INTO arca_style_images(item_id,image_url,prompt,base_prompt,negative_prompt,character_prompts_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (item_id, f"https://img/{index}.png", prompt, prompt, "lowres", json.dumps([{"prompt": f"char {index}"}]), "now"),
                )
        detail = get_arca_style_detail(self.db_path, item_id)
        self.assertEqual(len(detail["style_groups"]), 1)
        self.assertEqual(detail["style_groups"][0]["common_base_tags"], ["artist:foo", "watercolor"])
        self.assertEqual(detail["style_groups"][0]["images"][0]["character_prompts"][0]["prompt"], "char 1")
        self.assertEqual(count_style_groups_for_item(self.db_path, item_id), 1)

    def test_extracts_novelai_stealth_png_prompt(self):
        data = png_with_stealth({
            "prompt": "masterpiece, artist:foo",
            "uc": "lowres, bad anatomy",
            "seed": 1234,
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "scale": 5,
        })
        meta = extract_novelai_metadata(data, "image/png")
        self.assertEqual(meta["metadata_status"], "ok")
        self.assertEqual(meta["prompt"], "masterpiece, artist:foo")
        self.assertEqual(meta["negative_prompt"], "lowres, bad anatomy")
        self.assertEqual(meta["seed"], "1234")

    def test_extracts_outer_stealth_source_and_nested_character_prompt(self):
        nested = {
            "prompt": "artist:foo, masterpiece",
            "uc": "lowres",
            "seed": 77,
            "sampler": "k_euler",
            "v4_prompt": {"caption": {
                "base_caption": "artist:foo, masterpiece",
                "char_captions": [{"char_caption": "1girl, blue eyes", "centers": []}],
            }},
        }
        data = png_with_stealth({
            "Software": "NovelAI",
            "Source": "NovelAI Diffusion V4.5 4BDE2A90",
            "Comment": json.dumps(nested),
        })
        meta = extract_novelai_metadata(data, "image/png")
        self.assertEqual(meta["model"], "NovelAI Diffusion V4.5 4BDE2A90")
        self.assertEqual(meta["character_prompts"][0]["prompt"], "1girl, blue eyes")

    def test_extracts_uncompressed_stealth_description_without_comment(self):
        data = png_with_stealth({
            "Description": "artist:foo, watercolor",
            "Software": "NovelAI",
            "Source": "NovelAI Diffusion V4.5 4BDE2A90",
        }, compressed=False)
        meta = extract_novelai_metadata(data, "image/png")
        self.assertEqual(meta["metadata_status"], "ok")
        self.assertEqual(meta["prompt"], "artist:foo, watercolor")
        self.assertEqual(meta["model"], "NovelAI Diffusion V4.5 4BDE2A90")

    def test_extracts_novelai_webp_exif_user_comment(self):
        data = webp_with_exif_user_comment({
            "prompt": "masterpiece, artist:webp",
            "uc": "lowres, bad anatomy",
            "seed": 2468,
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "scale": 5,
            "source": "NovelAI Diffusion V4.5 Full",
        })

        meta = extract_novelai_metadata(data, "image/webp")

        self.assertEqual(meta["metadata_status"], "ok")
        self.assertEqual(meta["prompt"], "masterpiece, artist:webp")
        self.assertEqual(meta["negative_prompt"], "lowres, bad anatomy")
        self.assertEqual(meta["seed"], "2468")
        self.assertEqual(meta["model"], "NovelAI Diffusion V4.5 Full")

    def test_extracts_novelai_webp_stealth_prompt(self):
        data = webp_with_stealth({
            "prompt": "masterpiece, artist:stealth webp",
            "uc": "lowres, bad anatomy",
            "seed": 1357,
            "sampler": "k_euler_ancestral",
            "steps": 28,
        })

        meta = extract_novelai_metadata(data, "image/webp")

        self.assertEqual(meta["metadata_status"], "ok")
        self.assertEqual(meta["prompt"], "masterpiece, artist:stealth webp")
        self.assertEqual(meta["negative_prompt"], "lowres, bad anatomy")
        self.assertEqual(meta["seed"], "1357")

    def test_broken_stealth_compression_does_not_abort_collection(self):
        data = png_with_stealth({"prompt": "artist:foo", "seed": 1, "sampler": "k_euler"})
        with patch("arca_style_collector.gzip.decompress", side_effect=zlib.error("invalid distance")):
            meta = extract_novelai_metadata(data, "image/png")
        self.assertEqual(meta["metadata_status"], "no_metadata")
        self.assertEqual(meta["prompt"], "")

    def test_software_chunk_is_not_treated_as_a_prompt(self):
        meta = extract_novelai_metadata(
            png_with_text("Software", "http://www.pdf-tools.com"),
            "image/png",
        )
        self.assertEqual(meta["metadata_status"], "no_metadata")
        self.assertEqual(meta["prompt"], "")

    def test_update_allows_only_editable_fields(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at,title) VALUES(?,?,?,?)",
                ("https://arca.live/b/aiart/1", "now", "now", "original"),
            )
            item_id = cursor.lastrowid
        item = update_arca_style(self.db_path, item_id, {"prompt": "new", "negative_prompt": "uc", "memo": "note", "title": "hacked"})
        self.assertEqual((item["prompt"], item["negative_prompt"], item["memo"]), ("new", "uc", "note"))
        self.assertEqual(item["title"], "original")

    def test_save_article_reuses_existing_local_images_without_downloading(self):
        image_dir = Path(self.temp.name) / "images"
        image_dir.mkdir()
        (image_dir / "existing.png").write_bytes(b"cached")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at) VALUES(?,?,?)",
                ("https://arca.live/b/aiart/reuse", "now", "now"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,content_type,metadata_status,prompt,base_prompt,raw_metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, "https://ac.namu.la/path/existing.png?expires=1&key=old&type=orig", "existing.png", "image/png", "ok", "artist:foo", "artist:foo", json.dumps({"prompt": "artist:foo", "seed": 1, "sampler": "k_euler"}), "now"),
            )
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,content_type,metadata_status,prompt,base_prompt,raw_metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, "https://ac.namu.la/path/existing.png?expires=0&key=older&type=list", "existing.png", "image/png", "ok", "artist:foo", "artist:foo", json.dumps({"prompt": "artist:foo", "seed": 1, "sampler": "k_euler"}), "now"),
            )

        class NoNetworkSession:
            def get(self, *args, **kwargs):
                raise AssertionError("cached image must not be downloaded")

        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        network_count, _ = _save_article(self.db_path, image_dir, NoNetworkSession(), {
            "source_url": "https://arca.live/b/aiart/reuse", "article_id": "reuse", "board_tab": "NAI",
            "title": "style", "author": "a", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": ["https://ac.namu.la/path/existing.png?expires=2&key=new&type=list"],
        }, summary)
        self.assertEqual(network_count, 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_style_images WHERE item_id=?", (item_id,)).fetchone()[0], 1)

    def test_save_article_negative_caches_obvious_non_png_without_request(self):
        class NoNetworkSession:
            def get(self, *_args, **_kwargs):
                raise AssertionError("obvious non-PNG must not be requested")

        article = {
            "source_url": "https://arca.live/b/aiart/non-png", "article_id": "non-png", "board_tab": "NAI",
            "title": "style", "author": "a", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": ["https://img.example/sample.jpg"],
        }
        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        network_count, item_id = _save_article(
            self.db_path, Path(self.temp.name) / "images", NoNetworkSession(), article, summary,
        )
        self.assertEqual(network_count, 0)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT content_type,metadata_status,image_path FROM arca_style_images WHERE item_id=?",
                (item_id,),
            ).fetchone()
        self.assertEqual(row, ("image/jpeg", "no_metadata", ""))

        retry_summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        retry_count, _ = _save_article(
            self.db_path, Path(self.temp.name) / "images", NoNetworkSession(), article, retry_summary,
        )
        self.assertEqual(retry_count, 0)

    def test_save_article_downloads_webp_and_extracts_stealth_metadata(self):
        payload = webp_with_stealth({
            "prompt": "masterpiece, artist:archive webp",
            "uc": "lowres",
            "seed": 8642,
            "sampler": "k_euler_ancestral",
        })

        class Response:
            headers = {"Content-Type": "image/webp"}
            closed = False
            def raise_for_status(self): pass
            def iter_content(self, _size): return [payload]
            def close(self): self.closed = True

        response = Response()

        class Session:
            def get(self, *_args, **_kwargs): return response

        article = {
            "source_url": "https://arca.live/b/aiart/header-non-png", "article_id": "header-non-png", "board_tab": "NAI",
            "title": "style", "author": "a", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": ["https://img.example/resource.webp"],
        }
        image_dir = Path(self.temp.name) / "images"
        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        network_count, item_id = _save_article(
            self.db_path, image_dir, Session(), article, summary,
        )
        self.assertEqual(network_count, 1)
        self.assertTrue(response.closed)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT content_type,metadata_status,image_path,prompt FROM arca_style_images WHERE item_id=?",
                (item_id,),
            ).fetchone()
        self.assertEqual(row[:2], ("image/webp", "ok"))
        self.assertTrue(row[2].endswith(".webp"))
        self.assertEqual(row[3], "masterpiece, artist:archive webp")
        self.assertTrue((image_dir / row[2]).is_file())

    def test_save_article_retries_webp_previously_cached_without_metadata(self):
        image_url = "https://img.example/previously-skipped.webp"
        image_dir = Path(self.temp.name) / "images"
        image_dir.mkdir()
        (image_dir / "previously-skipped.webp").write_bytes(b"old webp without extracted metadata")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            item_id = conn.execute(
                "INSERT INTO arca_style_items(source_url,collected_at,updated_at) VALUES(?,?,?)",
                ("https://arca.live/b/aiart/retry-webp", "now", "now"),
            ).lastrowid
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,content_type,metadata_status,created_at) VALUES(?,?,?,?,?,?)",
                (item_id, image_url, "previously-skipped.webp", "image/webp", "no_metadata", "now"),
            )

        payload = webp_with_stealth({
            "prompt": "artist:recovered webp",
            "seed": 9753,
            "sampler": "k_euler",
        })

        class Response:
            headers = {"Content-Type": "image/webp"}
            def raise_for_status(self): pass
            def iter_content(self, _size): return [payload]
            def close(self): pass

        class Session:
            def __init__(self): self.calls = 0
            def get(self, *_args, **_kwargs):
                self.calls += 1
                return Response()

        session = Session()
        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        downloaded, _ = _save_article(self.db_path, image_dir, session, {
            "source_url": "https://arca.live/b/aiart/retry-webp", "article_id": "retry-webp",
            "board_tab": "NAI", "title": "style", "author": "a", "posted_at": "2026-06-01",
            "body_text": "", "image_urls": [image_url],
        }, summary)

        self.assertEqual((downloaded, session.calls), (1, 1))
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT metadata_status,prompt,image_path FROM arca_style_images WHERE item_id=?",
                (item_id,),
            ).fetchone()
        self.assertEqual(row[:2], ("ok", "artist:recovered webp"))
        self.assertTrue(row[2].endswith(".webp"))

    def test_save_article_negative_caches_png_without_novelai_metadata_without_file(self):
        payload = png_with_text("Software", "generic drawing tool")

        class Response:
            headers = {"Content-Type": "image/png"}
            def raise_for_status(self): pass
            def iter_content(self, _size): return [payload]

        class Session:
            def __init__(self): self.calls = 0
            def get(self, *_args, **_kwargs):
                self.calls += 1
                return Response()

        image_dir = Path(self.temp.name) / "images"
        article = {
            "source_url": "https://arca.live/b/aiart/plain-png", "article_id": "plain-png", "board_tab": "NAI",
            "title": "style", "author": "a", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": ["https://img.example/plain.png"],
        }
        session = Session()
        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        network_count, item_id = _save_article(self.db_path, image_dir, session, article, summary)
        self.assertEqual((network_count, session.calls), (0, 1))
        self.assertEqual(list(image_dir.glob("*")) if image_dir.exists() else [], [])
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT metadata_status,image_path FROM arca_style_images WHERE item_id=?",
                (item_id,),
            ).fetchone()
        self.assertEqual(row, ("no_metadata", ""))

        class NoNetworkSession:
            def get(self, *_args, **_kwargs):
                raise AssertionError("negative-cached PNG must not be requested again")

        retry_summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        retry_count, _ = _save_article(self.db_path, image_dir, NoNetworkSession(), article, retry_summary)
        self.assertEqual(retry_count, 0)

    def test_save_article_downloads_new_images_concurrently(self):
        payload = png_with_text("Comment", json.dumps({
            "prompt": "artist:foo", "seed": 1, "sampler": "k_euler",
        }))

        class Response:
            headers = {"Content-Type": "image/png"}
            def raise_for_status(self): pass
            def iter_content(self, _size): return [payload]

        class TrackingSession:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()
            def get(self, *args, **kwargs):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.03)
                with self.lock:
                    self.active -= 1
                return Response()

        session = TrackingSession()
        summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
        network_count, _ = _save_article(self.db_path, Path(self.temp.name) / "images", session, {
            "source_url": "https://arca.live/b/aiart/parallel", "article_id": "parallel", "board_tab": "NAI",
            "title": "style", "author": "a", "posted_at": "2026-06-01", "body_text": "",
            "image_urls": [f"https://img/{index}.png" for index in range(4)],
        }, summary)
        self.assertEqual(network_count, 4)
        self.assertGreaterEqual(session.max_active, 2)


if __name__ == "__main__":
    unittest.main()
