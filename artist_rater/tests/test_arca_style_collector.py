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
    snapshot_imported_arca_cookies,
    build_style_groups,
    count_style_groups_for_item,
    create_collection_job,
    delete_arca_style,
    get_collection_job,
    list_arca_styles,
    split_prompt_tags,
    update_collection_job,
    _save_article,
    collect_arca_style_url,
    collect_arca_styles,
)


def png_with_text(key, value):
    def chunk(kind, payload):
        crc = zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", key.encode() + b"\0" + value.encode()) + chunk(b"IEND", b"")


def png_with_stealth(metadata):
    compressed = gzip.compress(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
    bit_text = "".join(f"{byte:08b}" for byte in b"stealth_pngcomp")
    bit_text += f"{len(compressed) * 8:032b}"
    bit_text += "".join(f"{byte:08b}" for byte in compressed)
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

    def test_pre_session_category_runs_do_not_cover_new_searches(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("그림체 공유", "NAI,R18_NAI", "2026-01-01", "2026-01-03", 5, 80, "completed", "title-row-stealth-v4", "now", "now"),
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
