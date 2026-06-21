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

    @patch("app.get_collection_job")
    def test_collection_job_status_and_missing(self, get_job):
        get_job.return_value = {"id": 17, "status": "running"}
        self.assertEqual(self.client.get("/api/arca-styles/collection-jobs/17").get_json()["status"], "running")
        get_job.return_value = None
        self.assertEqual(self.client.get("/api/arca-styles/collection-jobs/99").status_code, 404)

    @patch("app.list_arca_styles")
    def test_list_adds_local_image_url(self, list_items):
        list_items.return_value = [{"id": 1, "representative_image_path": "abc.png"}]
        data = self.client.get("/api/arca-styles?q=x").get_json()
        self.assertEqual(data[0]["representative_image_url"], "/arca-style-images/abc.png")

    @patch("app.list_arca_styles")
    def test_list_passes_arca_post_date_sort(self, list_items):
        list_items.return_value = []
        self.client.get("/api/arca-styles?sort=posted_asc")
        self.assertEqual(list_items.call_args.args[1]["sort"], "posted_asc")

    def test_list_rejects_unknown_date_sort(self):
        response = self.client.get("/api/arca-styles?sort=collected_desc")
        self.assertEqual(response.status_code, 400)

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
