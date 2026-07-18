import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ArcaStyleApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        self.old_images = app.ARCA_STYLE_IMAGE_DIR
        app.DB_PATH = Path(self.temp.name) / "test.sqlite"
        app.ARCA_STYLE_IMAGE_DIR = Path(self.temp.name) / "images"
        app.init_db()
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

    def tearDown(self):
        app.DB_PATH = self.old_db
        app.ARCA_STYLE_IMAGE_DIR = self.old_images
        self.temp.cleanup()

    @patch("app.start_collection_job")
    def test_collect_route(self, start_job):
        start_job.return_value = 17
        response = self.client.post("/api/arca-styles/collect", json={"start_date": "2026-01-01", "end_date": "2026-01-02"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"job_id": 17, "status": "queued"})

    @patch("app.start_url_collection_job")
    def test_collect_one_url_route(self, start_job):
        start_job.return_value = 23
        response = self.client.post("/api/arca-styles/collect-url", json={
            "source_url": "https://arca.live/b/aiart/174457459",
        })
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"job_id": 23, "status": "queued"})
        start_job.assert_called_once_with(
            app.DB_PATH, app.ARCA_STYLE_IMAGE_DIR, "https://arca.live/b/aiart/174457459",
        )

    def test_collect_one_url_rejects_invalid_payload(self):
        response = self.client.post("/api/arca-styles/collect-url", json={"source_url": "https://example.com/x"})
        self.assertEqual(response.status_code, 400)

    @patch("app.get_arca_browser_session_status")
    def test_browser_session_status_exposes_only_safe_fields(self, get_status):
        get_status.return_value = {"connected": True, "browser": "Chrome", "error": ""}
        response = self.client.get("/api/arca-styles/browser-session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "connected": True, "browser": "Chrome", "error": "",
            "state": "connected", "message": "Chrome 로그인 연결됨",
        })

    @patch("app.import_arca_browser_session")
    @patch("app.ARCA_LOGIN_MANAGER")
    def test_browser_session_import_starts_login_window_without_exposing_cookie_values(self, manager, import_session):
        import_session.return_value = {"connected": False, "browser": "", "error": "로그인이 필요합니다."}
        manager.start.return_value = {
            "connected": False, "browser": "", "error": "", "state": "waiting",
            "message": "로그인 창에서 아카라이브에 로그인해 주세요.",
        }
        response = self.client.post("/api/arca-styles/browser-session/import")
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("secret-cookie", response.get_data(as_text=True))
        self.assertEqual(set(response.get_json()), {"connected", "browser", "error", "state", "message"})
        manager.start.assert_called_once_with()

    @patch("app.import_arca_browser_session")
    @patch("app.ARCA_LOGIN_MANAGER")
    def test_browser_session_import_does_not_open_window_when_auto_import_succeeds(self, manager, import_session):
        import_session.return_value = {"connected": True, "browser": "Edge", "error": ""}
        response = self.client.post("/api/arca-styles/browser-session/import")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"], "connected")
        manager.start.assert_not_called()

    @patch("app.connect_arca_cookie_jar")
    def test_browser_extension_connects_only_filtered_arca_cookies_without_echoing_values(self, connect):
        connect.return_value = {"connected": True, "browser": "현재 Chrome", "error": ""}
        response = self.client.post(
            "/api/arca-styles/browser-session/extension",
            headers={"X-Arca-Session-Bridge": "1"},
            json={"cookies": [
                {"name": "arca-session", "value": "secret-cookie", "domain": ".arca.live", "path": "/", "secure": True},
                {"name": "unrelated", "value": "other-secret", "domain": ".example.com", "path": "/", "secure": True},
            ]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["browser"], "현재 Chrome")
        self.assertNotIn("secret-cookie", response.get_data(as_text=True))
        cookie_jar, browser = connect.call_args.args
        self.assertEqual(browser, "현재 Chrome")
        self.assertEqual([(cookie.name, cookie.domain) for cookie in cookie_jar], [("arca-session", ".arca.live")])

    @patch("app.connect_arca_cookie_jar")
    def test_browser_extension_rejects_requests_without_bridge_header(self, connect):
        response = self.client.post(
            "/api/arca-styles/browser-session/extension",
            json={"cookies": [{"name": "session", "value": "x", "domain": ".arca.live", "path": "/"}]},
        )
        self.assertEqual(response.status_code, 403)
        connect.assert_not_called()

    @patch("app.install_arca_session_bridge")
    def test_browser_extension_setup_opens_persistent_install_folder(self, install):
        install.return_value = Path(self.temp.name) / "arca_session_bridge"
        response = self.client.post("/api/arca-styles/browser-session/extension/setup", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["path"], str(install.return_value))
        install.assert_called_once_with(app.DATA_DIR, source_dir=app.ARCA_SESSION_BRIDGE_SOURCE_DIR)

    @patch("app.get_collection_job")
    def test_collection_job_status_and_missing(self, get_job):
        get_job.return_value = {"id": 17, "status": "running"}
        self.assertEqual(self.client.get("/api/arca-styles/collection-jobs/17").get_json()["status"], "running")
        get_job.return_value = None
        self.assertEqual(self.client.get("/api/arca-styles/collection-jobs/99").status_code, 404)

    @patch("app.get_arca_style_page")
    def test_list_adds_local_image_url(self, get_page):
        get_page.return_value = {"items": [{"id": 1, "representative_image_path": "abc.png"}], "page": 1, "per_page": 50, "total": 1, "total_pages": 1}
        data = self.client.get("/api/arca-styles?q=x").get_json()
        self.assertEqual(data["items"][0]["representative_image_url"], "/arca-style-images/abc.png")

    @patch("app.get_arca_style_page")
    def test_list_hides_remote_image_until_local_file_is_restored(self, get_page):
        get_page.return_value = {"items": [{"id": 1, "representative_image_url": "https://remote/adult.png", "representative_image_path": ""}], "page": 1, "per_page": 50, "total": 1, "total_pages": 1}
        data = self.client.get("/api/arca-styles").get_json()
        self.assertEqual(data["items"][0]["representative_image_url"], "")
        self.assertFalse(data["items"][0]["representative_image_available"])

    @patch("app.start_image_restore_job")
    def test_restore_images_route_starts_background_job(self, start_job):
        start_job.return_value = 31
        response = self.client.post("/api/arca-styles/restore-images", json={})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"job_id": 31, "status": "queued"})
        start_job.assert_called_once_with(app.DB_PATH, app.ARCA_STYLE_IMAGE_DIR)

    @patch("app.start_image_url_refresh_job")
    def test_prepare_image_restore_starts_url_refresh_job(self, start_job):
        start_job.return_value = 32
        response = self.client.post("/api/arca-styles/restore-images/prepare", json={})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"job_id": 32, "status": "queued"})
        start_job.assert_called_once_with(app.DB_PATH, app.ARCA_STYLE_IMAGE_DIR)

    @patch("app.get_arca_style_page")
    def test_list_passes_paging_sort_and_recommendation_filter(self, get_page):
        get_page.return_value = {"items": [], "page": 3, "per_page": 20, "total": 0, "total_pages": 1}
        self.client.get("/api/arca-styles?sort=posted_asc&page=3&per_page=20&recommendation_min=10")
        self.assertEqual(get_page.call_args.args[1], {
            "sort": "posted_asc", "page": "3", "per_page": "20", "recommendation_min": "10",
        })

    def test_list_rejects_unknown_date_sort(self):
        response = self.client.get("/api/arca-styles?sort=collected_desc")
        self.assertEqual(response.status_code, 400)

    @patch("app.get_arca_style_statistics")
    def test_statistics_returns_shared_style_prompt_breakdown(self, get_statistics):
        get_statistics.return_value = {
            "analyzed_image_count": 2,
            "analyzed_post_count": 1,
            "analyzed_tag_count": 5,
            "images_with_artist": 2,
            "images_with_quality": 2,
            "artists": [{"tag": "artist:foo", "count": 2, "percentage": 100.0, "representative_image": {"image_path": "artist.png", "image_url": "https://remote/artist.png"}}],
            "quality_tags": [{"tag": "masterpiece", "count": 2, "percentage": 100.0}],
        }
        response = self.client.get("/api/arca-styles/statistics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), get_statistics.return_value)
        self.assertEqual(response.get_json()["artists"][0]["representative_image"]["image_url"], "/arca-style-images/artist.png")
        get_statistics.assert_called_once_with(app.DB_PATH, {})

    @patch("app.get_arca_style_statistics")
    def test_statistics_forwards_recommendation_range(self, get_statistics):
        get_statistics.return_value = {"artists": [], "quality_tags": [], "quality_sequences": []}
        response = self.client.get("/api/arca-styles/statistics?recommendation_min=30&recommendation_max=100")
        self.assertEqual(response.status_code, 200)
        get_statistics.assert_called_once_with(app.DB_PATH, {"recommendation_min": "30", "recommendation_max": "100"})

    @patch("app.get_arca_tag_statistics")
    def test_tag_statistics_adds_local_image_urls(self, get_statistics):
        get_statistics.return_value = {
            "kind": "artist", "tag": "artist:foo", "images": [
                {"id": 1, "image_path": "weighted.png", "image_url": "https://remote/image.png", "weight": 1.8},
            ],
        }
        response = self.client.get("/api/arca-styles/statistics/tag?kind=artist&tag=artist%3Afoo&limit=12")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["images"][0]["image_url"], "/arca-style-images/weighted.png")
        get_statistics.assert_called_once_with(app.DB_PATH, "artist", "artist:foo", "12", {})

    @patch("app.get_arca_quality_sequence_statistics")
    def test_quality_sequence_statistics_keeps_tag_order_and_adds_image_urls(self, get_statistics):
        get_statistics.return_value = {
            "tags": ["masterpiece", "best quality"], "image_count": 1,
            "images": [{"image_path": "sequence.png", "image_url": "https://remote/image.png", "prompt": "masterpiece, best quality"}],
        }
        response = self.client.get("/api/arca-styles/statistics/sequence?tag=masterpiece&tag=best%20quality&limit=30")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["images"][0]["image_url"], "/arca-style-images/sequence.png")
        get_statistics.assert_called_once_with(app.DB_PATH, ["masterpiece", "best quality"], "30", {})

    @patch("app.get_latest_resumable_collection_job")
    def test_current_collection_job_returns_resumable_work(self, current_job):
        current_job.return_value = {"id": 7, "status": "paused"}
        response = self.client.get("/api/arca-styles/collection-jobs/current")
        self.assertEqual(response.get_json(), {"id": 7, "status": "paused"})

    @patch("app.pause_collection_job")
    def test_collection_job_pause_route(self, pause_job):
        pause_job.return_value = {"id": 7, "status": "pause_requested"}
        response = self.client.post("/api/arca-styles/collection-jobs/7/pause")
        self.assertEqual(response.get_json()["status"], "pause_requested")
        pause_job.assert_called_once_with(app.DB_PATH, 7)

    @patch("app.resume_collection_job")
    def test_collection_job_resume_route_can_return_recovery_job(self, resume_job):
        resume_job.return_value = 9
        response = self.client.post("/api/arca-styles/collection-jobs/7/resume")
        self.assertEqual(response.get_json(), {"job_id": 9, "status": "running"})
        resume_job.assert_called_once_with(app.DB_PATH, app.ARCA_STYLE_IMAGE_DIR, 7)

    @patch("app.update_arca_style")
    def test_patch_and_missing(self, update):
        update.return_value = {"id": 1, "prompt": "new", "images": []}
        self.assertEqual(self.client.patch("/api/arca-styles/1", json={"prompt": "new"}).status_code, 200)
        update.return_value = None
        self.assertEqual(self.client.patch("/api/arca-styles/9", json={"prompt": "new"}).status_code, 404)

    @patch("app.delete_arca_style")
    def test_delete(self, delete):
        delete.return_value = {"deleted": True, "recollect_date": "2026-06-10"}
        self.assertEqual(self.client.delete("/api/arca-styles/1").get_json(), {"deleted": True, "recollect_date": "2026-06-10"})


if __name__ == "__main__":
    unittest.main()
