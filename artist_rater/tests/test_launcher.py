import io
import json
import tempfile
import unittest
from pathlib import Path

import launcher


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.waited = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


class FakeResponse:
    def __init__(self, payload=b""):
        self.payload = payload

    def __enter__(self):
        return io.BytesIO(self.payload)

    def __exit__(self, exc_type, exc, traceback):
        return False


class LauncherControllerTest(unittest.TestCase):
    def test_launcher_theme_uses_light_apple_style_tokens(self):
        self.assertEqual(launcher.LAUNCHER_THEME["window_bg"], "#f5f5f7")
        self.assertEqual(launcher.LAUNCHER_THEME["card_bg"], "#ffffff")
        self.assertEqual(launcher.LAUNCHER_THEME["primary"], "#007aff")
        self.assertEqual(launcher.LAUNCHER_THEME["text"], "#1d1d1f")

    def test_launcher_actions_prioritize_server_and_site_controls(self):
        actions = launcher.launcher_button_specs()

        self.assertEqual([item["text"] for item in actions[:2]], ["서버 켜기", "웹사이트 열기"])
        self.assertEqual(actions[0]["style"], "primary")
        self.assertEqual(actions[1]["style"], "secondary")
        self.assertIn("업데이트 확인", [item["text"] for item in actions])

    def test_start_stop_and_open_site_use_injected_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            launched = []
            opened = []
            process = FakeProcess()

            controller = launcher.LauncherController(
                app_dir=Path(temp_dir),
                popen=lambda command, **kwargs: launched.append((command, kwargs)) or process,
                browser_open=opened.append,
            )

            self.assertEqual(controller.start_server(), "서버를 시작했습니다.")
            self.assertEqual(controller.start_server(), "서버가 이미 실행 중입니다.")
            self.assertEqual(len(launched), 1)
            self.assertIn("app.py", launched[0][0])
            self.assertEqual(controller.open_site(), "웹사이트를 열었습니다.")
            self.assertEqual(opened, [launcher.APP_URL])
            self.assertEqual(controller.stop_server(), "서버를 종료했습니다.")
            self.assertTrue(process.terminated)
            self.assertTrue(process.waited)

    def test_frozen_start_uses_same_executable_server_mode(self):
        launched = []
        process = FakeProcess()
        controller = launcher.LauncherController(
            frozen=True,
            executable=Path("C:/App/DanbooruArtistRater.exe"),
            popen=lambda command, **kwargs: launched.append(command) or process,
        )

        controller.start_server()

        self.assertEqual(launched[0], [str(Path("C:/App/DanbooruArtistRater.exe")), "--server"])

    def test_auto_open_setting_is_saved_in_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            controller = launcher.LauncherController(data_dir=data_dir)

            self.assertEqual(controller.load_settings(), {"auto_open_site": False})
            self.assertTrue(controller.set_auto_open_site(True))
            self.assertEqual(controller.load_settings(), {"auto_open_site": True})
            self.assertEqual(json.loads((data_dir / launcher.LAUNCHER_SETTINGS_NAME).read_text(encoding="utf-8")), {"auto_open_site": True})

    def test_wait_for_server_uses_local_app_url(self):
        requested = []

        def open_local(request, timeout=0):
            requested.append(request.full_url)
            return FakeResponse(b"ok")

        controller = launcher.LauncherController(urlopen=open_local)
        self.assertTrue(controller.wait_for_server(timeout_seconds=1))
        self.assertEqual(requested, [launcher.APP_URL])

    def test_release_check_finds_newer_github_asset_and_notes(self):
        release = {
            "tag_name": "v0.2.0",
            "body": "새 리모콘을 추가했습니다.",
            "html_url": "https://github.test/releases/v0.2.0",
            "assets": [
                {
                    "name": "DanbooruArtistRater.exe",
                    "browser_download_url": "https://github.test/app.exe",
                    "size": 123,
                }
            ],
        }

        controller = launcher.LauncherController(
            current_version="v0.1.0",
            urlopen=lambda request, timeout=0: FakeResponse(json.dumps(release).encode("utf-8")),
        )

        info = controller.check_update()

        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "v0.2.0")
        self.assertEqual(info.asset_url, "https://github.test/app.exe")
        self.assertIn("새 리모콘", info.release_notes)

    def test_download_update_writes_asset_to_updates_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = launcher.LauncherController(
                data_dir=Path(temp_dir),
                urlopen=lambda request, timeout=0: FakeResponse(b"exe-bytes"),
            )
            info = launcher.UpdateInfo(
                current_version="v0.1.0",
                latest_version="v0.2.0",
                has_update=True,
                release_notes="notes",
                asset_url="https://github.test/app.exe",
                release_url="https://github.test/releases/v0.2.0",
            )

            target = controller.download_update(info)

            self.assertEqual(target.read_bytes(), b"exe-bytes")
            self.assertEqual(target.name, "DanbooruArtistRater.exe")


if __name__ == "__main__":
    unittest.main()
