import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

import arca_style_collector as collector


class ArcaCollectionFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "archive.sqlite"
        self.image_dir = Path(self.temp.name) / "images"
        collector.init_arca_style_tables(self.db_path)
        self.params = collector.normalize_collect_payload({
            "keyword": "style", "tabs": ["NAI"],
            "start_date": "2026-10-24", "end_date": "2026-10-24",
        })
        date_patch = patch.object(collector, "date", wraps=date)
        datetime_patch = patch.object(collector, "datetime", wraps=datetime)
        self.clock_date = date_patch.start()
        self.clock_datetime = datetime_patch.start()
        self.addCleanup(date_patch.stop)
        self.addCleanup(datetime_patch.stop)
        self.set_clock(24)

    def set_clock(self, day):
        self.clock_date.today.return_value = date(2026, 10, day)
        self.clock_datetime.now.return_value = datetime(2026, 10, day, 10)

    def add_run(self, start, end, created_at, *, updated_at=None, status="completed"):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO arca_collection_runs("
                "keyword,tabs,start_date,end_date,max_pages,max_posts,status,"
                "search_scope,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("style", "NAI", start, end, 0, 0, status, collector.SEARCH_SCOPE,
                 created_at, updated_at or created_at),
            )

    def coverage(self):
        return collector.get_completed_coverage(self.db_path, self.params)

    def test_same_day_completion_leaves_today_open_and_preserves_previous_days(self):
        self.add_run("2026-10-20", "2026-10-24", "2026-10-24T09:00:00")
        self.assertEqual(self.coverage(), [(date(2026, 10, 20), date(2026, 10, 23))])
        self.assertEqual(
            collector.uncovered_date_intervals(date(2026, 10, 20), date(2026, 10, 24), self.coverage()),
            [(date(2026, 10, 24), date(2026, 10, 24))],
        )

    def test_creation_day_stays_open_next_day_until_collected_after_midnight(self):
        self.add_run("2026-10-24", "2026-10-24", "2026-10-24T09:00:00")
        self.set_clock(25)
        self.assertEqual(self.coverage(), [])

        self.add_run("2026-10-24", "2026-10-24", "2026-10-25T09:00:00")
        self.assertEqual(self.coverage(), [(date(2026, 10, 24), date(2026, 10, 24))])
        with patch.object(collector, "create_arca_session", side_effect=AssertionError("network forbidden")):
            result = collector.collect_arca_styles(self.db_path, self.image_dir, self.params)
        self.assertTrue(result["skipped_existing"])
        self.assertEqual(result["scanned_pages"], 0)

    def test_run_crossing_midnight_uses_start_time_instead_of_finish_time(self):
        self.add_run(
            "2026-10-23", "2026-10-24", "2026-10-24T23:59:00",
            updated_at="2026-10-25T00:05:00",
        )
        self.set_clock(25)
        self.assertEqual(self.coverage(), [(date(2026, 10, 23), date(2026, 10, 23))])

    def test_legacy_timestamp_keeps_history_but_never_closes_today_or_future(self):
        self.add_run("2026-10-20", "2026-10-30", "now")
        self.assertEqual(self.coverage(), [(date(2026, 10, 20), date(2026, 10, 23))])

    def test_future_dated_run_cannot_close_today_or_future(self):
        self.add_run("2026-10-20", "2026-10-30", "2026-11-01T09:00:00")
        self.assertEqual(self.coverage(), [(date(2026, 10, 20), date(2026, 10, 23))])

    def test_completed_history_unions_without_including_partial_or_live_dates(self):
        self.add_run("2026-10-20", "2026-10-21", "2026-10-22T09:00:00")
        self.add_run("2026-10-21", "2026-10-24", "2026-10-24T09:00:00")
        self.add_run("2026-10-19", "2026-10-24", "2026-10-24T09:00:00", status="partial")
        self.assertEqual(self.coverage(), [(date(2026, 10, 20), date(2026, 10, 23))])

    def test_same_day_rerun_collects_new_post_and_reuses_existing_image(self):
        class Session:
            def get(self, *_args, **_kwargs):
                raise AssertionError("live network forbidden")

            def close(self):
                pass

        def row(article_id, posted_at="2026-10-24"):
            return (
                f'<a class="vrow column" href="/b/aiart/{article_id}">'
                f'<span class="badge">NAI</span><span class="title">style {article_id}</span>'
                f'<time datetime="{posted_at}T09:00:00Z"></time></a>'
            )

        latest_ids = [101]
        article_requests = []

        def fetch_html(_session, url):
            if "keyword=" in url:
                return "".join(row(article_id) for article_id in latest_ids) + row(99, "2026-10-23")
            article_requests.append(url)
            article_id = url.rsplit("/", 1)[-1]
            return (
                '<span>NAI</span><time>2026-10-24</time>'
                f'<div class="article-content"><img src="https://img.example/{article_id}.png"></div>'
            )

        png_metadata = PngImagePlugin.PngInfo()
        png_metadata.add_text("Comment", json.dumps({"prompt": "artist:test", "seed": 1, "sampler": "k_euler"}))
        output = io.BytesIO()
        with Image.new("RGB", (1, 1)) as image:
            image.save(output, "PNG", pnginfo=png_metadata)

        with patch.object(collector, "create_arca_session", side_effect=Session), \
                patch.object(collector, "get_arca_browser_session_status", return_value={"connected": False}), \
                patch.object(collector, "discover_category_params", return_value={"NAI": {"category": "nai"}}), \
                patch.object(collector, "fetch_html", side_effect=fetch_html), \
                patch.object(collector, "download_image", return_value=(output.getvalue(), "image/png")) as download:
            first = collector.collect_arca_styles(self.db_path, self.image_dir, self.params)
            self.assertEqual(first["saved"], 1)
            self.assertFalse(first["partial"])
            self.assertEqual(download.call_count, 1)
            latest_ids.insert(0, 102)
            second = collector.collect_arca_styles(self.db_path, self.image_dir, self.params)

        self.assertFalse(second["skipped_existing"])
        self.assertEqual((second["saved"], second["updated"]), (1, 1))
        self.assertEqual(download.call_count, 2)
        self.assertEqual(
            [call.args[1] for call in download.call_args_list],
            ["https://img.example/101.png", "https://img.example/102.png"],
        )
        self.assertEqual(article_requests.count("https://arca.live/b/aiart/101"), 2)
        self.assertEqual(article_requests.count("https://arca.live/b/aiart/102"), 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_style_items").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_style_images").fetchone()[0], 2)
        self.assertEqual(len(list(self.image_dir.glob("*.png"))), 2)


if __name__ == "__main__":
    unittest.main()
