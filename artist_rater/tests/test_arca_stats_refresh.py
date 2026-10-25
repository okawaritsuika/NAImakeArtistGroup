import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests

import arca_style_collector as collector


class ArcaStatsRefreshTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "archive.sqlite"
        collector.init_arca_style_tables(self.db_path)
        self.addCleanup(collector.clear_arca_browser_session)
        for target, options in (
            ("ARTICLE_REFRESH_INTERVAL_SECONDS", {"new": 0}),
            ("TRANSIENT_RETRY_DELAYS", {"new": (0,) * 7}),
            ("get_arca_browser_session_status", {"return_value": {"connected": False}}),
            ("download_image", {"side_effect": AssertionError("stats must not download images")}),
            ("_save_article", {"side_effect": AssertionError("stats must not rewrite article metadata")}),
            ("extract_article_data", {"side_effect": AssertionError("stats must not parse full article content")}),
        ):
            patcher = patch.object(collector, target, **options)
            patcher.start()
            self.addCleanup(patcher.stop)
        no_network = patch.object(requests.Session, "get", side_effect=AssertionError("unexpected real network request"))
        no_network.start()
        self.addCleanup(no_network.stop)

    def add_item(self, article_id, *, tab="NAI", recommendations=8, views=100, source_url=None):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            return conn.execute(
                "INSERT INTO arca_style_items(source_url,article_id,board_tab,title,collected_at,updated_at,"
                "prompt,negative_prompt,memo,metadata_status,recommendation_count,view_count) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_url or f"https://arca.live/b/aiart/{article_id}", str(article_id), tab,
                    "saved title", "2026-01-01T08:00:00", "2026-01-01T08:00:00",
                    "artist:example, edited prompt", "edited negative", "saved memo", "ok",
                    recommendations, views,
                ),
            ).lastrowid

    def item_row(self, item_id):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            return dict(conn.execute("SELECT * FROM arca_style_items WHERE id=?", (item_id,)).fetchone())

    def add_run(self, keyword, item_ids=()):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            run_id = conn.execute(
                "INSERT INTO arca_collection_runs(keyword,tabs,start_date,end_date,max_pages,max_posts,"
                "status,search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (keyword, "NAI", "2026-01-01", "2026-01-01", 0, 0, "completed", collector.SEARCH_SCOPE,
                 "2026-01-02T10:00:00", "2026-01-02T10:00:00"),
            ).lastrowid
            conn.executemany("INSERT INTO arca_collection_run_items(run_id,item_id) VALUES(?,?)",
                             [(run_id, item_id) for item_id in item_ids])
        return run_id

    def add_model_image(self, item_id, model_id):
        family = "v5" if model_id.startswith("nai-diffusion-5-") else (
            "v4.5" if model_id.startswith("nai-diffusion-4-5-") else "unknown"
        )
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            image_index = conn.execute("SELECT COUNT(*) FROM arca_style_images WHERE item_id=?", (item_id,)).fetchone()[0]
            return conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,metadata_status,prompt,model,model_id,"
                "model_family,model_generation,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, f"https://example.com/{item_id}-{image_index}.png", "ok", "saved image prompt",
                 model_id, model_id, family, family, "2026-01-01T08:00:00"),
            ).lastrowid

    @staticmethod
    def search_row(article_id, recommendations=26, views="3,531", *, tab="NAI", href=None, notice=False):
        pairs = (("col-rate", recommendations), ("col-view", views))
        fields = "".join(
            f'<span class="vcol {column}">{value}</span>'
            for column, value in pairs if value is not None
        )
        return (
            f'<a class="vrow column{" notice" if notice else ""}" href="{href or f"/b/aiart/{article_id}"}">'
            f'<span class="vcol col-id">{article_id}</span><span class="vcol col-title">'
            f'<span class="badge">{tab}</span><span class="title">그림체 공유 [99]</span></span>'
            f'<span class="vcol col-author">example 88</span>{fields}</a>'
        )

    @staticmethod
    def article_html(recommendations=26, views="3,531"):
        fields = "".join(
            f'<span class="head">{label}</span><span class="body">{value}</span>'
            for label, value in (("추천", recommendations), ("조회수", views)) if value is not None
        )
        return (f'<div class="article-info article-info-section">{fields}</div>'
                '<div class="fr-view article-content">changed prompt'
                '<img src="https://example.com/never-download.png"></div>')

    def search_pages(self, pages, articles=None):
        keywords = {collector.DEFAULT_KEYWORD} | {key[0] for key in pages if isinstance(key, tuple)}

        def fetch(_session, url):
            parsed = urlparse(url)
            self.assertEqual((parsed.scheme, parsed.netloc), ("https", "arca.live"))
            if parsed.path != "/b/aiart":
                self.assertIsNotNone(articles, f"unexpected individual article request: {url}")
                self.assertEqual(parsed.query, "")
                article_id = int(parsed.path.rsplit("/", 1)[-1])
                self.assertEqual(parsed.path, f"/b/aiart/{article_id}")
                self.assertIn(article_id, articles)
                value = articles[article_id]
                if isinstance(value, Exception):
                    raise value
                return value
            query = parse_qs(parsed.query)
            self.assertEqual(set(query), {"target", "keyword", "p"})
            self.assertEqual(query["target"], ["title"])
            self.assertIn(query["keyword"][0], keywords)
            page = int(query["p"][0])
            value = pages.get((query["keyword"][0], page), pages.get(page, ""))
            if isinstance(value, Exception):
                raise value
            return value
        return fetch

    def test_search_statistics_read_only_exact_count_columns_and_valid_article_links(self):
        html = "".join((
            self.search_row(901, 0, "1,234"),
            self.search_row(902, 6, 382, tab="🔞 NAI", href="/b/aiart/902?p=1"),
            self.search_row(903, "1.2k", None),
            self.search_row(904, 999, 999, notice=True),
            self.search_row(905, 999, 999, href="/b/otherboard/905"),
            self.search_row(906, 999, 999, href="https://example.com/b/aiart/906"),
        ))
        rows = collector.extract_search_statistics(html)
        self.assertEqual(rows, [
            {"source_url": "https://arca.live/b/aiart/901", "recommendation_count": 0, "view_count": 1234},
            {"source_url": "https://arca.live/b/aiart/902", "recommendation_count": 6, "view_count": 382},
            {"source_url": "https://arca.live/b/aiart/903", "recommendation_count": None, "view_count": None},
        ])

    def test_self_closing_void_tags_never_join_neighboring_post_counts(self):
        for tag in ("img", "br", "input", "source", "wbr"):
            with self.subTest(tag=tag):
                first = self.search_row(123, 72, 12717, tab="🔞 NAI")
                first = first.replace('<span class="title">', f'<{tag} /><span class="title">')
                html = first + self.search_row(122, 33, 4506)
                self.assertEqual(collector.extract_search_statistics(html), [
                    {"source_url": "https://arca.live/b/aiart/123", "recommendation_count": 72, "view_count": 12717},
                    {"source_url": "https://arca.live/b/aiart/122", "recommendation_count": 33, "view_count": 4506},
                ])
                found = collector.extract_search_results(html)
                self.assertEqual([item["source_url"] for item in found], [
                    "https://arca.live/b/aiart/123", "https://arca.live/b/aiart/122",
                ])

    def test_new_row_discards_unclosed_previous_row_instead_of_joining_counts(self):
        broken = self.search_row(123, 72, 12717).removesuffix('</a>')
        for notice in (False, True):
            with self.subTest(notice=notice):
                middle = self.search_row(124, 999, 999, notice=True) if notice else ""
                html = broken + middle + self.search_row(122, 33, 4506)
                self.assertEqual(collector.extract_search_statistics(html), [
                    {"source_url": "https://arca.live/b/aiart/122", "recommendation_count": 33, "view_count": 4506},
                ])

    def test_list_refresh_corrects_concatenated_counts_without_changing_other_fields(self):
        first = self.add_item(123, recommendations=7233, views=127174506)
        second = self.add_item(122, recommendations=8, views=100)
        before = {item_id: self.item_row(item_id) for item_id in (first, second)}
        first_row = self.search_row(123, 72, 12717).replace('<span class="title">', '<img src="/badge.png" /><span class="title">')
        html = first_row + self.search_row(122, 33, 4506)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()
        self.assertEqual(result["updated"], 2)
        for item_id, expected in ((first, (72, 12717)), (second, (33, 4506))):
            row = self.item_row(item_id)
            self.assertEqual((row["recommendation_count"], row["view_count"]), expected)
            for field in row:
                if field not in {"recommendation_count", "view_count", "updated_at"}:
                    self.assertEqual(row[field], before[item_id][field], field)

    def test_refreshes_all_stored_posts_without_changing_images_or_edited_fields(self):
        first = self.add_item(101)
        second = self.add_item(102, recommendations=2, views=30)
        image = Path(self.temp.name) / "saved.png"
        image.write_bytes(b"saved-image-bytes")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE arca_style_items SET representative_image_path=?,image_count=1 WHERE id=?",
                (image.name, first),
            )
            conn.execute(
                "INSERT INTO arca_style_images(item_id,image_url,image_path,prompt,metadata_status,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (first, "https://example.com/saved.png", image.name, "saved image prompt", "ok", "old"),
            )
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        before = {item_id: self.item_row(item_id) for item_id in (first, second)}
        with closing(sqlite3.connect(self.db_path)) as conn:
            images_before = conn.execute("SELECT * FROM arca_style_images").fetchall()
        html = self.search_row(102) + self.search_row(101) + self.search_row(100)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)

        self.assertEqual(result, {"updated": 2, "failed_posts": 0, "skipped_existing": False})
        fetch.assert_called_once()
        for item_id in (first, second):
            row = self.item_row(item_id)
            self.assertEqual((row["recommendation_count"], row["view_count"]), (26, 3531))
            self.assertNotEqual(row["updated_at"], before[item_id]["updated_at"])
            for field in row:
                if field not in {"recommendation_count", "view_count", "updated_at"}:
                    self.assertEqual(row[field], before[item_id][field], field)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT * FROM arca_style_images").fetchall(), images_before)
        self.assertEqual(image.read_bytes(), b"saved-image-bytes")
        job = collector.get_collection_job(self.db_path, job_id)
        self.assertEqual((job["job_type"], job["status"], job["updated"]), ("stats_refresh", "completed", 2))
        self.assertEqual(job["progress"]["posts"], [2, 2])
        self.assertEqual(job["scanned_pages"], 1)
        self.assertEqual(job["downloaded_images"], 0)

    def test_thirty_stored_posts_are_refreshed_with_one_list_request(self):
        item_ids = [self.add_item(article_id) for article_id in range(1001, 1031)]
        html = "".join(self.search_row(article_id, 20, 400) for article_id in range(1030, 1000, -1))
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()
        self.assertEqual(result["updated"], 30)
        self.assertEqual(result["failed_posts"], 0)
        self.assertTrue(all(self.item_row(item_id)["view_count"] == 400 for item_id in item_ids))

    def test_model_scope_uses_any_matching_image_and_deduplicates_posts(self):
        mixed = self.add_item(1101)
        repeated = self.add_item(1102)
        representative_only = self.add_item(1103)
        no_image = self.add_item(1104)
        self.add_model_image(mixed, "nai-diffusion-4-5-full")
        self.add_model_image(mixed, "nai-diffusion-5-full")
        self.add_model_image(repeated, "nai-diffusion-5-full")
        self.add_model_image(repeated, "nai-diffusion-5-curated")
        self.add_model_image(representative_only, "nai-diffusion-4-5-full")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE arca_style_items SET model_id=?,model_family=? WHERE id IN (?,?)",
                         ("nai-diffusion-5-full", "v5", representative_only, no_image))
            conn.execute("UPDATE arca_style_items SET model_id=?,model_family=? WHERE id=?",
                         ("nai-diffusion-4-5-full", "v4.5", mixed))
        rows = collector._stats_refresh_items(self.db_path, model="v5")
        self.assertEqual([row["id"] for row in rows], [mixed, repeated])
        self.assertEqual({row["id"] for row in collector._stats_refresh_items(self.db_path)},
                         {mixed, repeated, representative_only, no_image})

    def test_model_scope_supports_specific_variants_and_unknown_images(self):
        model_ids = ("nai-diffusion-5-full", "nai-diffusion-5-full-medium", "nai-diffusion-5-curated", "")
        items = {}
        for number, model_id in enumerate(model_ids, 1201):
            item_id = self.add_item(number)
            self.add_model_image(item_id, model_id)
            items[model_id] = item_id
        for token, model_id in (("v5-full", model_ids[0]), ("V5 Full Medium", model_ids[1]),
                                ("nai-diffusion-5-curated", model_ids[2]), ("unknown", "")):
            with self.subTest(model=token):
                self.assertEqual([row["id"] for row in collector._stats_refresh_items(self.db_path, model=token)],
                                 [items[model_id]])

    def test_selected_model_is_normalized_and_saved_without_login_for_excluded_r18(self):
        selected = self.add_item(1301)
        excluded = self.add_item(1302, tab="R18_NAI")
        self.add_model_image(selected, "nai-diffusion-5-full")
        self.add_model_image(excluded, "nai-diffusion-4-5-full")
        job_id, items = collector.create_stats_refresh_job(self.db_path, model=" V5 ")
        self.assertEqual([item["id"] for item in items], [selected])
        job = collector.get_collection_job(self.db_path, job_id)
        self.assertEqual(json.loads(job["request_json"]), {"mode": "stats_refresh", "model": "v5"})
        self.assertEqual(job["total_posts"], 1)

    def test_direct_refresh_restores_saved_model_scope_and_leaves_excluded_posts_unchanged(self):
        selected = self.add_item(1401)
        excluded = self.add_item(1402)
        self.add_model_image(selected, "nai-diffusion-5-full")
        self.add_model_image(excluded, "nai-diffusion-4-5-full")
        job_id, _ = collector.create_stats_refresh_job(self.db_path, model="v5")
        before = self.item_row(excluded)
        html = self.search_row(1402, 500, 5000) + self.search_row(1401, 7, 700)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id)
        fetch.assert_called_once()
        self.assertEqual(result, {"updated": 1, "failed_posts": 0, "skipped_existing": False})
        self.assertEqual(self.item_row(selected)["view_count"], 700)
        self.assertEqual(self.item_row(excluded), before)
        self.assertEqual(collector.get_collection_job(self.db_path, job_id)["progress"]["posts"], [1, 1])

    def test_empty_selected_model_does_not_open_a_session_or_require_excluded_r18_login(self):
        excluded = self.add_item(1501, tab="R18_NAI")
        self.add_model_image(excluded, "nai-diffusion-4-5-full")
        with patch.object(collector, "create_arca_session", side_effect=AssertionError("empty scope must not connect")):
            job_id, items = collector.create_stats_refresh_job(self.db_path, model="v5")
            self.assertEqual(items, [])
            result = collector.refresh_arca_style_stats(self.db_path, job_id)
        self.assertEqual(result, {"updated": 0, "failed_posts": 0, "skipped_existing": True})
        self.assertEqual(collector.get_collection_job(self.db_path, job_id)["total_posts"], 0)

    def test_invalid_model_is_rejected_before_a_job_or_worker_is_created(self):
        with patch.object(collector, "Thread") as worker:
            for operation in (collector._stats_refresh_items, collector.create_stats_refresh_job, collector.start_stats_refresh_job):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaises(collector.ArcaCollectorError):
                        operation(self.db_path, model="unsupported-model")
            worker.assert_not_called()
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_collection_jobs").fetchone()[0], 0)

    def test_origin_search_is_reused_and_unlinked_or_invalid_keywords_are_ignored(self):
        first = self.add_item(202)
        second = self.add_item(101)
        self.add_run("스타일 공유", [second])
        self.add_run("사용하지 않는 검색어")
        self.add_run("   ", [second])
        self.add_run("???", [second])
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        searches = collector._stats_refresh_searches(self.db_path, items)
        self.assertEqual(searches, [("그림체 공유", {first, second}), ("스타일 공유", {second})])
        pages = {
            ("그림체 공유", 1): self.search_row(202, 20, 200) + self.search_row(100),
            ("스타일 공유", 1): self.search_row(101, 30, 300),
        }
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result["updated"], 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([parse_qs(urlparse(call.args[1]).query)["keyword"][0] for call in fetch.call_args_list],
                         ["그림체 공유", "스타일 공유"])
        self.assertEqual(self.item_row(second)["view_count"], 300)

    def test_broader_origin_keyword_replaces_default_search_for_all_targets(self):
        first = self.add_item(302)
        second = self.add_item(301)
        self.add_run("그림체", [first])
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        self.assertEqual(collector._stats_refresh_searches(self.db_path, items), [("그림체", {first, second})])
        pages = {("그림체", 1): self.search_row(302) + self.search_row(301)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()
        self.assertEqual(parse_qs(urlparse(fetch.call_args.args[1]).query)["keyword"], ["그림체"])
        self.assertEqual(result["updated"], 2)

    def test_resolved_origin_search_is_not_requested_again(self):
        item_id = self.add_item(401)
        self.add_run("스타일 공유", [item_id])
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(401)})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()
        self.assertEqual(result["updated"], 1)

    def test_failed_search_tries_linked_keyword_before_individual_fallback(self):
        item_id = self.add_item(402)
        self.add_run("스타일 공유", [item_id])
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        response = requests.Response()
        response.status_code = 404
        pages = {("그림체 공유", 1): requests.HTTPError("not found", response=response),
                 ("스타일 공유", 1): self.search_row(402)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result["updated"], 1)

    def test_unexpected_parser_error_is_not_hidden_by_fallback(self):
        self.add_item(403)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(403)})) as fetch, \
                patch.object(collector, "extract_search_statistics", side_effect=RuntimeError("parser bug")):
            with self.assertRaisesRegex(RuntimeError, "parser bug"):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()

    def test_direct_post_uses_fallback_while_listed_post_never_opens_individually(self):
        listed = self.add_item(502)
        direct = self.add_item(501)
        before = self.item_row(direct)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        pages = {1: self.search_row(502, 7, 700) + self.search_row(500)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages, {501: self.article_html(0, 1200)})) as fetch, \
                patch.object(collector, "update_collection_job", wraps=collector.update_collection_job) as update:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result, {"updated": 2, "failed_posts": 0, "skipped_existing": False})
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[-1].args[1], "https://arca.live/b/aiart/501")
        self.assertTrue(any(call.kwargs.get("stage") == "refreshing_stats_posts" for call in update.call_args_list))
        self.assertEqual(self.item_row(listed)["view_count"], 700)
        row = self.item_row(direct)
        self.assertEqual((row["recommendation_count"], row["view_count"]), (0, 1200))
        for field in row:
            if field not in {"recommendation_count", "view_count", "updated_at"}:
                self.assertEqual(row[field], before[field], field)
        job = collector.get_collection_job(self.db_path, job_id)
        self.assertEqual(job["scanned_pages"], 1)
        self.assertEqual(job["progress"]["posts"], [2, 2])

    def test_fallback_statistics_parser_returns_only_counts(self):
        self.assertEqual(collector.extract_article_statistics(self.article_html(0, "1,234")),
                         {"recommendation_count": 0, "view_count": 1234})
        self.assertEqual(collector.extract_article_statistics(self.article_html(None, 55)),
                         {"recommendation_count": None, "view_count": 55})
        self.assertEqual(collector.extract_article_statistics('<div class="article-content">추천 999 조회수 999</div>'),
                         {"recommendation_count": None, "view_count": None})
        for value in ("1.2k", ",", "12foo", "1,23"):
            with self.subTest(value=value):
                self.assertEqual(collector.extract_article_statistics(self.article_html(value, value)),
                                 {"recommendation_count": None, "view_count": None})

    def test_malformed_fallback_counts_preserve_existing_numbers(self):
        articles, unchanged, partial = {}, {}, []
        for index, value in enumerate(("1.2k", ",", "12foo", "1,23")):
            article_id = 1600 + index * 2
            item_id = self.add_item(article_id)
            unchanged[item_id] = self.item_row(item_id)
            articles[article_id] = self.article_html(value, value)
            item_id = self.add_item(article_id + 1)
            partial.append(item_id)
            articles[article_id + 1] = self.article_html(value, 250)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)):
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result, {"updated": 4, "failed_posts": 4, "skipped_existing": False})
        for item_id, snapshot in unchanged.items():
            self.assertEqual(self.item_row(item_id), snapshot)
        for item_id in partial:
            row = self.item_row(item_id)
            self.assertEqual((row["recommendation_count"], row["view_count"]), (8, 250))

    def test_failed_and_unreadable_fallbacks_preserve_values_and_continue(self):
        missing = self.add_item(601)
        unreadable = self.add_item(602)
        forbidden = self.add_item(603)
        good = self.add_item(604)
        before = {item_id: self.item_row(item_id) for item_id in (missing, unreadable, forbidden)}
        not_found_response = requests.Response()
        not_found_response.status_code = 404
        forbidden_response = requests.Response()
        forbidden_response.status_code = 403
        articles = {
            601: requests.HTTPError("not found", response=not_found_response),
            602: self.article_html(None, None),
            603: requests.HTTPError("forbidden", response=forbidden_response),
            604: self.article_html(0, 500),
        }
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result, {"updated": 1, "failed_posts": 3, "skipped_existing": False})
        self.assertEqual(fetch.call_count, 5)
        for item_id, snapshot in before.items():
            self.assertEqual(self.item_row(item_id), snapshot)
        self.assertEqual(self.item_row(good)["view_count"], 500)
        self.assertEqual(collector.get_collection_job(self.db_path, job_id)["progress"]["posts"], [4, 4])

    def test_fallback_rate_limit_stops_before_requesting_remaining_articles(self):
        first = self.add_item(701)
        second = self.add_item(702)
        before = {item_id: self.item_row(item_id) for item_id in (first, second)}
        response = requests.Response()
        response.status_code = 429
        articles = {701: requests.HTTPError("rate limit", response=response), 702: self.article_html()}
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)) as fetch:
            with self.assertRaises(collector.ArcaCollectorError):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[-1].args[1], "https://arca.live/b/aiart/701")
        for item_id, snapshot in before.items():
            self.assertEqual(self.item_row(item_id), snapshot)

    def test_zero_and_decreased_values_replace_previous_counts(self):
        item_id = self.add_item(201, recommendations=30, views=800)
        job_id, _ = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(201, 0, 20)})):
            collector.refresh_arca_style_stats(self.db_path, job_id)
        row = self.item_row(item_id)
        self.assertEqual((row["recommendation_count"], row["view_count"]), (0, 20))

    def test_missing_count_preserves_its_previous_value(self):
        first = self.add_item(301)
        second = self.add_item(302)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        html = self.search_row(302, 0, None) + self.search_row(301, None, 250)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})):
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result["updated"], 2)
        self.assertEqual((self.item_row(first)["recommendation_count"], self.item_row(first)["view_count"]), (8, 250))
        self.assertEqual((self.item_row(second)["recommendation_count"], self.item_row(second)["view_count"]), (0, 100))

    def test_unlisted_and_unreadable_posts_preserve_values_while_other_posts_update(self):
        unlisted = self.add_item(401)
        missing = self.add_item(402)
        good = self.add_item(403)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        before = {item_id: self.item_row(item_id) for item_id in (unlisted, missing)}
        html = self.search_row(403, 12, 500) + self.search_row(402, None, None) + self.search_row(400)
        articles = {401: self.article_html(None, None), 402: self.article_html(None, None)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html}, articles)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result, {"updated": 1, "failed_posts": 2, "skipped_existing": False})
        self.assertEqual(fetch.call_count, 3)
        for item_id in (unlisted, missing):
            self.assertEqual(self.item_row(item_id), before[item_id])
        self.assertEqual(self.item_row(good)["view_count"], 500)
        job = collector.get_collection_job(self.db_path, job_id)
        self.assertEqual(job["progress"]["posts"], [3, 3])
        self.assertEqual(job["status"], "completed")
        self.assertIn("2", job["error"])

    def test_refresh_follows_search_pages_and_stops_when_all_targets_are_found(self):
        older = self.add_item(201)
        newer = self.add_item(302)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        pages = {1: self.search_row(302, 3, 300), 2: self.search_row(201, 2, 200)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([parse_qs(urlparse(call.args[1]).query)["p"][0] for call in fetch.call_args_list], ["1", "2"])
        self.assertEqual(result["updated"], 2)
        self.assertEqual((self.item_row(older)["view_count"], self.item_row(newer)["view_count"]), (200, 300))

    def test_duplicate_search_page_terminates_before_fallback(self):
        item_id = self.add_item(101)
        before = self.item_row(item_id)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        html = self.search_row(400)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html, 2: html}, {101: self.article_html(None, None)})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(fetch.call_args_list[-1].args[1], "https://arca.live/b/aiart/101")
        self.assertEqual(result["failed_posts"], 1)
        self.assertEqual(self.item_row(item_id), before)

    def test_empty_search_page_terminates_with_unmatched_values_preserved(self):
        item_id = self.add_item(101)
        before = self.item_row(item_id)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(400), 2: ""}, {101: self.article_html(None, None)})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result["failed_posts"], 1)
        self.assertEqual(self.item_row(item_id), before)

    def test_page_limit_bounds_search_when_target_is_not_found(self):
        self.add_item(101)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "MAX_ARCHIVE_SEARCH_PAGE", 2), \
                patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(400), 2: self.search_row(300)}, {101: self.article_html(None, None)})) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(result["failed_posts"], 1)

    def test_rate_limit_stops_after_one_attempt_without_requesting_another_page(self):
        item_id = self.add_item(101)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        before = self.item_row(item_id)
        response = requests.Response()
        response.status_code = 429
        with patch.object(collector, "fetch_html", side_effect=requests.HTTPError("rate limit", response=response)) as fetch:
            with self.assertRaises(collector.ArcaCollectorError):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_called_once()
        self.assertEqual(self.item_row(item_id), before)

    def test_other_server_errors_also_stop_before_individual_requests(self):
        self.add_item(101)
        self.add_item(102)
        for status in (501, 505, 520, 522):
            with self.subTest(status=status):
                job_id, items = collector.create_stats_refresh_job(self.db_path)
                response = requests.Response()
                response.status_code = status
                with patch.object(collector, "fetch_html", side_effect=requests.HTTPError("server error", response=response)) as fetch:
                    with self.assertRaises(collector.ArcaCollectorError):
                        collector.refresh_arca_style_stats(self.db_path, job_id, items)
                fetch.assert_called_once()

    def test_transient_failure_is_limited_to_two_attempts(self):
        self.add_item(101)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        response = requests.Response()
        response.status_code = 503
        pages = {1: requests.HTTPError("unavailable", response=response)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
            with self.assertRaises(collector.ArcaCollectorError):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args[1], fetch.call_args_list[1].args[1])

    def test_connection_failures_stop_instead_of_retrying_each_remaining_post(self):
        item_ids = [self.add_item(article_id) for article_id in range(201, 211)]
        before = {item_id: self.item_row(item_id) for item_id in item_ids}
        for failure in (requests.ConnectionError, requests.Timeout):
            with self.subTest(failure=failure.__name__):
                job_id, items = collector.create_stats_refresh_job(self.db_path)
                articles = {201: failure("connection unavailable")}
                with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)) as fetch:
                    with self.assertRaises(collector.ArcaCollectorError):
                        collector.refresh_arca_style_stats(self.db_path, job_id, items)
                self.assertEqual(fetch.call_count, 3)
                self.assertEqual([call.args[1] for call in fetch.call_args_list[1:]],
                                 ["https://arca.live/b/aiart/201"] * 2)
        for item_id, snapshot in before.items():
            self.assertEqual(self.item_row(item_id), snapshot)

    def test_list_authentication_errors_stop_before_other_searches_or_fallback(self):
        item_id = self.add_item(301)
        self.add_run("스타일 공유", [item_id])
        for status in (401, 403):
            with self.subTest(status=status):
                job_id, items = collector.create_stats_refresh_job(self.db_path)
                response = requests.Response()
                response.status_code = status
                pages = {1: requests.HTTPError("login required", response=response)}
                with patch.object(collector, "fetch_html", side_effect=self.search_pages(pages)) as fetch:
                    with self.assertRaises(collector.ArcaCollectorError):
                        collector.refresh_arca_style_stats(self.db_path, job_id, items)
                fetch.assert_called_once()

    def test_three_consecutive_forbidden_articles_stop_remaining_fallback_requests(self):
        for article_id in range(401, 405):
            self.add_item(article_id)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        response = requests.Response()
        response.status_code = 403
        articles = {article_id: requests.HTTPError("forbidden", response=response) for article_id in range(401, 404)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)) as fetch:
            with self.assertRaises(collector.ArcaCollectorError):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 4)
        self.assertEqual([call.args[1] for call in fetch.call_args_list[1:]],
                         [f"https://arca.live/b/aiart/{article_id}" for article_id in range(401, 404)])

    def test_successful_article_resets_consecutive_authentication_failure_count(self):
        for article_id in range(501, 507):
            self.add_item(article_id)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        response = requests.Response()
        response.status_code = 403
        articles = {article_id: self.article_html() if article_id in (503, 506)
                    else requests.HTTPError("forbidden", response=response) for article_id in range(501, 507)}
        with patch.object(collector, "fetch_html", side_effect=self.search_pages({1: ""}, articles)) as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(fetch.call_count, 7)
        self.assertEqual(result, {"updated": 2, "failed_posts": 4, "skipped_existing": False})

    def test_invalid_stored_source_is_not_requested(self):
        item_id = self.add_item(501, source_url="https://example.com/private")
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        before = self.item_row(item_id)
        with patch.object(collector, "fetch_html") as fetch:
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_not_called()
        self.assertEqual(result["failed_posts"], 1)
        self.assertEqual(self.item_row(item_id), before)

    def test_r18_requires_session_before_creating_a_job(self):
        self.add_item(601, tab="R18_NAI")
        with self.assertRaises(collector.ArcaBrowserSessionRequired):
            collector.create_stats_refresh_job(self.db_path)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_collection_jobs").fetchone()[0], 0)

    def test_connected_session_matches_nai_and_r18_rows_on_the_same_search_page(self):
        item_id = self.add_item(602, tab="R18_NAI")
        public_id = self.add_item(603)
        html = self.search_row(603, 2, 200) + self.search_row(602, 6, 3531, tab="🔞 NAI")
        with patch.object(collector, "get_arca_browser_session_status", return_value={"connected": True}), \
                patch.object(collector, "_apply_imported_arca_cookies") as apply_cookies, \
                patch.object(collector, "fetch_html", side_effect=self.search_pages({1: html})) as fetch:
            job_id, items = collector.create_stats_refresh_job(self.db_path)
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result["updated"], 2)
        fetch.assert_called_once()
        self.assertTrue(apply_cookies.called)
        self.assertEqual(self.item_row(item_id)["view_count"], 3531)
        self.assertEqual(self.item_row(public_id)["view_count"], 200)

    def test_empty_archive_completes_without_network_session(self):
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        with patch.object(collector, "create_arca_session", side_effect=AssertionError("empty archive must not connect")):
            result = collector.refresh_arca_style_stats(self.db_path, job_id, items)
        self.assertEqual(result, {"updated": 0, "failed_posts": 0, "skipped_existing": True})
        job = collector.get_collection_job(self.db_path, job_id)
        self.assertEqual((job["status"], job["skipped_existing"], job["total_posts"]), ("completed", 1, 0))

    def test_stop_prevents_the_next_search_page_request(self):
        self.add_item(701)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        control = collector._register_collection_control(job_id)
        self.addCleanup(collector._remove_collection_control, job_id)
        control["stop"].set()
        with patch.object(collector, "fetch_html") as fetch:
            with self.assertRaises(collector.ArcaCollectionStopped):
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
        fetch.assert_not_called()

    def test_paused_refresh_waits_then_resumes_without_early_request(self):
        self.add_item(702)
        job_id, items = collector.create_stats_refresh_job(self.db_path)
        control = collector._register_collection_control(job_id)
        self.addCleanup(collector._remove_collection_control, job_id)
        control["pause"].set()
        paused = threading.Event()
        failures = []
        original_update = collector.update_collection_job

        def update(*args, **kwargs):
            original_update(*args, **kwargs)
            if kwargs.get("status") == "paused":
                paused.set()

        def run():
            try:
                collector.refresh_arca_style_stats(self.db_path, job_id, items)
            except Exception as exc:
                failures.append(exc)

        with patch.object(collector, "update_collection_job", side_effect=update), \
                patch.object(collector, "fetch_html", side_effect=self.search_pages({1: self.search_row(702)})) as fetch:
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                self.assertTrue(paused.wait(3), "refresh did not enter paused state")
                fetch.assert_not_called()
            finally:
                control["pause"].clear()
                worker.join(3)
            self.assertFalse(worker.is_alive(), "refresh did not finish after resuming")
            self.assertEqual(failures, [])
            fetch.assert_called_once()
        self.assertEqual(collector.get_collection_job(self.db_path, job_id)["status"], "completed")

    def test_resume_dispatches_statistics_job_instead_of_image_collection(self):
        job_id, _ = collector.create_stats_refresh_job(self.db_path)
        collector.update_collection_job(self.db_path, job_id, status="interrupted")
        with patch.object(collector, "start_stats_refresh_job", return_value=99) as start:
            result = collector.resume_collection_job(self.db_path, Path(self.temp.name) / "images", job_id)
        self.assertEqual(result, 99)
        start.assert_called_once_with(self.db_path, model="all")

    def test_resume_preserves_selected_model_and_supports_legacy_jobs_without_model(self):
        for token in ("v5", "nai-diffusion-5-full-medium", None):
            with self.subTest(model=token):
                job_id, _ = collector.create_stats_refresh_job(self.db_path, model=token or "all")
                if token is None:
                    with closing(sqlite3.connect(self.db_path)) as conn, conn:
                        conn.execute("UPDATE arca_collection_jobs SET request_json=? WHERE id=?",
                                     (json.dumps({"mode": "stats_refresh"}), job_id))
                collector.update_collection_job(self.db_path, job_id, status="interrupted")
                with patch.object(collector, "start_stats_refresh_job", return_value=99) as start:
                    result = collector.resume_collection_job(self.db_path, Path(self.temp.name) / "images", job_id)
                self.assertEqual(result, 99)
                start.assert_called_once_with(self.db_path, model=token or "all")


if __name__ == "__main__":
    unittest.main()
