import io
import json
import tempfile
import unittest
from pathlib import Path

import launcher


class FakeProcess:
    def __init__(self):
        self.pid = 1234
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
    def test_data_directory_options_allow_repeated_sources_and_primary_selection(self):
        data_dirs, primary = launcher.parse_data_directory_options(
            ["--data-dir", "C:/one", "--data-dir", "C:/two", "--primary-data-dir", "C:/two"]
        )
        self.assertEqual(data_dirs, [Path("C:/one").resolve(), Path("C:/two").resolve()])
        self.assertEqual(primary, Path("C:/two").resolve())
        self.assertTrue(
            launcher.has_data_directory_options(
                ["--data-dir=C:/one", "--primary-data-dir=C:/two"]
            )
        )

    def test_source_launcher_command_passes_selected_data_directories_to_server(self):
        launched = []
        controller = launcher.LauncherController(
            app_dir=Path("C:/App"),
            data_dirs=[Path("C:/one"), Path("C:/two")],
            primary_data_dir=Path("C:/two"),
            popen=lambda command, **kwargs: launched.append(command) or FakeProcess(),
        )
        controller.start_server()
        self.assertEqual(
            launched[0][2:],
            ["--data-dir", str(Path("C:/one").resolve()), "--data-dir", str(Path("C:/two").resolve()), "--primary-data-dir", str(Path("C:/two").resolve())],
        )

    def test_data_directory_controller_adds_without_duplicates_and_sets_primary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = launcher.LauncherController(
                data_dirs=[Path("C:/one"), Path("C:/two")],
                primary_data_dir=Path("C:/one"),
                launcher_settings_dir=Path(temp_dir),
            )

            self.assertFalse(controller.add_data_directory("C:/ONE"))
            self.assertTrue(controller.add_data_directory("C:/three"))
            self.assertTrue(controller.set_primary_data_directory("C:/three"))
            self.assertEqual(controller.data_dir, Path("C:/three").resolve())
            self.assertEqual(controller.primary_data_dir, Path("C:/three").resolve())
            self.assertEqual(len(controller.data_dirs), 3)

    def test_data_directory_controller_removes_primary_by_promoting_another(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = launcher.LauncherController(
                data_dirs=[Path("C:/one"), Path("C:/two")],
                primary_data_dir=Path("C:/one"),
                launcher_settings_dir=Path(temp_dir),
            )

            self.assertTrue(controller.remove_data_directory("C:/one"))
            self.assertEqual(controller.data_dirs, [Path("C:/two").resolve()])
            self.assertEqual(controller.primary_data_dir, Path("C:/two").resolve())
            self.assertEqual(controller.data_dir, Path("C:/two").resolve())
            with self.assertRaises(ValueError):
                controller.remove_data_directory("C:/two")

    def test_data_directory_mutations_roll_back_when_settings_save_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = launcher.LauncherController(
                data_dirs=[Path("C:/one"), Path("C:/two")],
                primary_data_dir=Path("C:/one"),
                launcher_settings_dir=Path(temp_dir),
            )
            controller._save_data_configuration = lambda: (_ for _ in ()).throw(OSError("read-only"))

            with self.assertRaises(OSError):
                controller.add_data_directory("C:/three")
            self.assertEqual(controller.data_dirs, [Path("C:/one").resolve(), Path("C:/two").resolve()])

            with self.assertRaises(OSError):
                controller.set_primary_data_directory("C:/two")
            self.assertEqual(controller.primary_data_dir, Path("C:/one").resolve())

            with self.assertRaises(OSError):
                controller.remove_data_directory("C:/two")
            self.assertEqual(controller.data_dirs, [Path("C:/one").resolve(), Path("C:/two").resolve()])

    def test_data_directory_controller_blocks_changes_while_server_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = launcher.LauncherController(
                data_dirs=[Path("C:/one")],
                launcher_settings_dir=Path(temp_dir),
                popen=lambda command, **kwargs: FakeProcess(),
            )
            controller.start_server()

            with self.assertRaises(RuntimeError):
                controller.add_data_directory("C:/two")
            with self.assertRaises(RuntimeError):
                controller.set_primary_data_directory("C:/one")
            with self.assertRaises(RuntimeError):
                controller.remove_data_directory("C:/one")

    def test_packaged_version_matches_next_release(self):
        self.assertEqual(launcher.CURRENT_VERSION, "v0.1.8")

    def test_independent_frozen_environment_removes_parent_bootloader_state(self):
        env = launcher.independent_frozen_environment({
            "PATH": "C:/Windows",
            "_PYI_APPLICATION_HOME_DIR": "C:/Temp/_MEI123",
            "_PYI_PARENT_PROCESS_LEVEL": "1",
            "_MEIPASS2": "C:/Temp/_MEI123",
        })

        self.assertEqual(env["PATH"], "C:/Windows")
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertNotIn("_PYI_APPLICATION_HOME_DIR", env)
        self.assertNotIn("_PYI_PARENT_PROCESS_LEVEL", env)
        self.assertNotIn("_MEIPASS2", env)

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

    def test_frozen_server_starts_with_an_independent_bootloader_environment(self):
        launched = []
        controller = launcher.LauncherController(
            frozen=True,
            executable=Path("C:/App/DanbooruArtistRater.exe"),
            popen=lambda command, **kwargs: launched.append((command, kwargs)) or FakeProcess(),
        )

        controller.start_server()

        env = launched[0][1]["env"]
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertFalse(any(key.startswith("_PYI_") for key in env))

    def test_frozen_stop_terminates_the_whole_server_process_tree(self):
        calls = []
        process = FakeProcess()

        class Completed:
            returncode = 0

        controller = launcher.LauncherController(
            frozen=True,
            executable=Path("C:/App/DanbooruArtistRater.exe"),
            process_run=lambda command, **kwargs: calls.append((command, kwargs)) or Completed(),
        )
        controller.process = process

        self.assertEqual(controller.stop_server(), "서버를 종료했습니다.")
        self.assertEqual(calls[0][0], ["taskkill", "/PID", "1234", "/T", "/F"])
        self.assertIsNone(controller.process)

    def test_auto_open_setting_is_saved_in_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            controller = launcher.LauncherController(data_dir=data_dir)

            self.assertEqual(controller.load_settings(), {"auto_open_site": False})
            self.assertTrue(controller.set_auto_open_site(True))
            self.assertEqual(controller.load_settings(), {"auto_open_site": True})
            self.assertEqual(json.loads((data_dir / launcher.LAUNCHER_SETTINGS_NAME).read_text(encoding="utf-8")), {"auto_open_site": True})

    def test_data_configuration_roundtrip_keeps_auto_open_setting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_dir = root / "default-data"
            first = root / "one"
            second = root / "two"
            controller = launcher.LauncherController(
                data_dir=first,
                launcher_settings_dir=settings_dir,
            )

            controller.set_auto_open_site(True)
            self.assertTrue(controller.add_data_directory(second))
            self.assertTrue(controller.set_primary_data_directory(second))

            saved = json.loads((settings_dir / launcher.LAUNCHER_SETTINGS_NAME).read_text(encoding="utf-8"))
            self.assertEqual(saved["auto_open_site"], True)
            self.assertEqual(saved["data_dirs"], [str(first.resolve()), str(second.resolve())])
            self.assertEqual(saved["primary_data_dir"], str(second.resolve()))

            restarted = launcher.LauncherController(launcher_settings_dir=settings_dir)
            self.assertEqual(restarted.data_dirs, [first.resolve(), second.resolve()])
            self.assertEqual(restarted.primary_data_dir, second.resolve())
            self.assertTrue(restarted.load_settings()["auto_open_site"])

    def test_explicit_cli_style_configuration_takes_precedence_over_saved_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_dir = root / "default-data"
            saved = root / "saved"
            override = root / "override"
            settings_dir.mkdir()
            (settings_dir / launcher.LAUNCHER_SETTINGS_NAME).write_text(
                json.dumps({
                    "auto_open_site": True,
                    "data_dirs": [str(saved)],
                    "primary_data_dir": str(saved),
                }),
                encoding="utf-8",
            )
            data_dirs, primary = launcher.parse_data_directory_options(
                ["--data-dir", str(override), "--primary-data-dir", str(override)],
                default_data_dir=settings_dir,
            )
            controller = launcher.LauncherController(
                data_dirs=data_dirs,
                primary_data_dir=primary,
                launcher_settings_dir=settings_dir,
            )
            self.assertEqual(controller.data_dirs, [override.resolve()])
            self.assertEqual(controller.primary_data_dir, override.resolve())

    def test_invalid_saved_data_configuration_falls_back_to_default_without_deleting_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_dir = root / "default-data"
            settings_dir.mkdir()
            settings_path = settings_dir / launcher.LAUNCHER_SETTINGS_NAME
            settings_path.write_text(
                json.dumps({
                    "auto_open_site": True,
                    "data_dirs": [str(root / "missing"), str(root / "missing")],
                    "primary_data_dir": str(root / "other"),
                }),
                encoding="utf-8",
            )
            controller = launcher.LauncherController(launcher_settings_dir=settings_dir)
            self.assertEqual(controller.data_dirs, [settings_dir.resolve()])
            self.assertEqual(controller.primary_data_dir, settings_dir.resolve())
            self.assertTrue(settings_path.exists())

    def test_data_directory_ui_is_collapsed_by_default_and_has_toggle(self):
        source = Path(launcher.__file__).read_text(encoding="utf-8")
        self.assertIn('self.data_card_expanded = False', source)
        self.assertIn('text="펼치기"', source)
        self.assertIn('def toggle_data_directory_card(self):', source)

    def test_wait_for_server_uses_local_app_url(self):
        requested = []

        def open_local(request, timeout=0):
            requested.append(request.full_url)
            return FakeResponse(b"ok")

        controller = launcher.LauncherController(urlopen=open_local)
        controller.process = FakeProcess()
        self.assertTrue(controller.wait_for_server())
        self.assertEqual(requested, [launcher.APP_URL])

    def test_wait_for_server_retries_until_server_is_ready(self):
        attempts = []

        def open_local(request, timeout=0):
            attempts.append(request.full_url)
            if len(attempts) < 3:
                raise OSError("server is still starting")
            return FakeResponse(b"ok")

        controller = launcher.LauncherController(urlopen=open_local)
        controller.process = FakeProcess()
        self.assertTrue(controller.wait_for_server(interval_seconds=0))
        self.assertEqual(attempts, [launcher.APP_URL, launcher.APP_URL, launcher.APP_URL])

    def test_wait_for_server_stops_retrying_when_server_process_exits(self):
        attempts = []
        process = FakeProcess()

        def open_local(request, timeout=0):
            attempts.append(request.full_url)
            process.returncode = 1
            raise OSError("server stopped while starting")

        controller = launcher.LauncherController(urlopen=open_local)
        controller.process = process

        self.assertFalse(controller.wait_for_server(interval_seconds=0))
        self.assertEqual(attempts, [launcher.APP_URL])

    def test_window_close_stops_server_before_destroying_root(self):
        events = []

        class Controller:
            def stop_server(self):
                events.append("stop")

        class Root:
            def destroy(self):
                events.append("destroy")

        app = launcher.LauncherApp.__new__(launcher.LauncherApp)
        app.controller = Controller()
        app.root = Root()

        app.close_app()

        self.assertEqual(events, ["stop", "destroy"])

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

    def test_update_install_stops_server_before_preparing_replacement(self):
        events = []

        class Controller:
            def download_update(self, update_info):
                events.append("download")
                return Path("C:/App/data/updates/DanbooruArtistRater.exe")

            def stop_server(self):
                events.append("stop")

            def prepare_update_install(self, target):
                events.append(("prepare", target.name))
                return "ready"

        self.assertEqual(launcher.download_and_prepare_update(Controller(), object()), "ready")
        self.assertEqual(events, ["download", "stop", ("prepare", "DanbooruArtistRater.exe")])

    def test_frozen_update_script_retries_copy_before_restarting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            downloaded = data_dir / "updates" / launcher.RELEASE_ASSET_NAME
            downloaded.parent.mkdir(parents=True)
            downloaded.write_bytes(b"new-exe")
            launched = []
            controller = launcher.LauncherController(
                data_dir=data_dir,
                frozen=True,
                executable=Path(temp_dir) / launcher.RELEASE_ASSET_NAME,
                popen=lambda command, **kwargs: launched.append((command, kwargs)) or FakeProcess(),
            )

            controller.prepare_update_install(downloaded)

            script = (data_dir / "updates" / "install_update.bat").read_text(encoding="utf-8")
            self.assertIn("for /l %%i in (1,1,30)", script)
            self.assertIn("copy /y", script)
            self.assertIn("&& goto updated", script)
            self.assertIn("ping 127.0.0.1 -n 2", script)
            self.assertNotIn("timeout /t", script)
            self.assertIn('set "PYINSTALLER_RESET_ENVIRONMENT=1"', script)
            self.assertLess(script.index(":updated"), script.index(f'start "" "{controller.executable}"', script.index(":updated")))
            self.assertEqual(launched[0][0][:2], ["cmd", "/c"])
            self.assertEqual(launched[0][1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_successful_frozen_update_closes_launcher_normally(self):
        events = []

        class Controller:
            frozen = True

            def download_update(self, update_info):
                events.append("download")
                return Path("C:/App/data/updates/DanbooruArtistRater.exe")

            def stop_server(self):
                events.append("stop")

            def prepare_update_install(self, target):
                events.append("prepare")
                return "ready"

        app = launcher.LauncherApp.__new__(launcher.LauncherApp)
        app.controller = Controller()
        app.latest_update = object()
        app.set_status = lambda message: events.append(("status", message))
        app.close_app = lambda: events.append("close")
        app.run_background = lambda action, on_success: on_success(action())

        app.install_update()

        self.assertEqual(events[-1], "close")


if __name__ == "__main__":
    unittest.main()
