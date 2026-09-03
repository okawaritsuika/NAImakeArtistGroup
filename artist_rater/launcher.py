import json
import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    BooleanVar,
    Button,
    Checkbutton,
    Frame,
    Label,
    Listbox,
    Tk,
    Text,
    filedialog,
    messagebox,
)
from urllib.request import Request, urlopen


APP_URL = "http://127.0.0.1:5001"
CURRENT_VERSION = "v0.1.8"
GITHUB_LATEST_RELEASE_API = (
    "https://api.github.com/repos/okawaritsuika/NAImakeArtistGroup/releases/latest"
)
RELEASE_ASSET_NAME = "DanbooruArtistRater.exe"
LAUNCHER_SETTINGS_NAME = "launcher_settings.json"
LAUNCHER_THEME = {
    "window_bg": "#f5f5f7",
    "card_bg": "#ffffff",
    "card_border": "#d2d2d7",
    "text": "#1d1d1f",
    "muted": "#6e6e73",
    "primary": "#007aff",
    "primary_active": "#0062cc",
    "secondary": "#e8e8ed",
    "secondary_active": "#dcdce2",
    "success": "#34c759",
    "danger": "#ff3b30",
}


def launcher_button_specs():
    return [
        {"text": "서버 켜기", "command": "start_server", "style": "primary"},
        {"text": "웹사이트 열기", "command": "open_site", "style": "secondary"},
        {"text": "서버 끄기", "command": "stop_server", "style": "ghost"},
        {"text": "업데이트 확인", "command": "check_update", "style": "ghost"},
        {"text": "업데이트 받기", "command": "install_update", "style": "ghost"},
    ]


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    has_update: bool
    release_notes: str
    asset_url: str
    release_url: str


def resolve_launcher_paths(frozen=None, executable=None, module_file=None):
    frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    executable = Path(executable or sys.executable).resolve()
    module_file = Path(module_file or __file__).resolve()
    if frozen:
        app_dir = executable.parent
        data_dir = app_dir / "data"
    else:
        app_dir = module_file.parent
        data_dir = app_dir / "data"
    return app_dir, data_dir


def normalize_version(value):
    text = str(value or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = []
    for piece in text.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            break
    return tuple(parts or [0])


def independent_frozen_environment(environment=None):
    env = dict(os.environ if environment is None else environment)
    for key in tuple(env):
        if key.startswith("_PYI_") or key == "_MEIPASS2":
            env.pop(key, None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def parse_data_directory_options(argv=None, default_data_dir=None):
    """Parse repeatable source directories for source/frozen server startup."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir", action="append", dest="data_dirs")
    parser.add_argument("--primary-data-dir", dest="primary_data_dir")
    options, _ = parser.parse_known_args(argv)
    values = [Path(item).expanduser().resolve() for item in (options.data_dirs or [])]
    if not values:
        if options.primary_data_dir:
            values = [Path(options.primary_data_dir).expanduser().resolve()]
        elif default_data_dir is not None:
            values = [Path(default_data_dir).expanduser().resolve()]
    primary = (
        Path(options.primary_data_dir).expanduser().resolve()
        if options.primary_data_dir
        else (values[0] if values else None)
    )
    return values, primary


def has_data_directory_options(argv=None):
    """Return whether CLI data options explicitly override saved launcher settings."""

    return any(
        option in ("--data-dir", "--primary-data-dir")
        or option.startswith("--data-dir=")
        or option.startswith("--primary-data-dir=")
        for option in (argv or [])
    )


class LauncherController:
    def __init__(
        self,
        app_dir=None,
        data_dir=None,
        current_version=CURRENT_VERSION,
        popen=None,
        process_run=None,
        browser_open=None,
        urlopen=None,
        executable=None,
        frozen=None,
        data_dirs=None,
        primary_data_dir=None,
        launcher_settings_dir=None,
        settings_dir=None,
    ):
        resolved_app_dir, resolved_data_dir = resolve_launcher_paths(
            frozen=frozen,
            executable=executable,
        )
        self.app_dir = Path(app_dir or resolved_app_dir)
        self.settings_dir = Path(
            launcher_settings_dir
            or settings_dir
            or (data_dir if data_dir is not None and data_dirs is None else resolved_data_dir)
        ).expanduser().resolve()
        explicit_data_dirs = data_dirs is not None or data_dir is not None or primary_data_dir is not None
        saved_data_dirs = None
        saved_primary = None
        if not explicit_data_dirs:
            saved_data_dirs, saved_primary = self._load_saved_data_configuration()
        if data_dirs is None:
            data_dirs = saved_data_dirs or [data_dir or self.settings_dir]
        self.data_dirs = self._normalize_data_directories(data_dirs)
        if not self.data_dirs:
            self.data_dirs = [self.settings_dir]
        self.primary_data_dir = Path(primary_data_dir or saved_primary or self.data_dirs[0]).expanduser().resolve()
        if not any(
            os.path.normcase(str(item)) == os.path.normcase(str(self.primary_data_dir))
            for item in self.data_dirs
        ):
            raise ValueError("primary data 디렉터리는 data 디렉터리 목록에 포함되어야 합니다.")
        self.data_dir = self.primary_data_dir
        self._explicit_data_dirs = explicit_data_dirs or saved_data_dirs is not None
        self.current_version = current_version
        self.popen = popen or subprocess.Popen
        self.process_run = process_run or subprocess.run
        self.browser_open = browser_open or webbrowser.open
        self.urlopen = urlopen or globals()["urlopen"]
        self.executable = Path(executable or sys.executable).resolve()
        self.frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
        self.process = None

    def data_directory_arguments(self):
        if not self._explicit_data_dirs:
            return []
        arguments = []
        for value in self.data_dirs:
            arguments.extend(["--data-dir", str(value)])
        arguments.extend(["--primary-data-dir", str(self.primary_data_dir)])
        return arguments

    def _ensure_data_configuration_editable(self):
        if self.is_server_running():
            raise RuntimeError("서버 실행 중에는 데이터 폴더를 변경할 수 없습니다. 서버를 끈 뒤 다시 시도하세요.")

    @staticmethod
    def _resolved_data_directory(value):
        return Path(value).expanduser().resolve()

    @classmethod
    def _normalize_data_directories(cls, values):
        result = []
        seen = set()
        for value in values or []:
            if not isinstance(value, (str, os.PathLike)):
                continue
            directory = cls._resolved_data_directory(value)
            key = os.path.normcase(str(directory))
            if key not in seen:
                seen.add(key)
                result.append(directory)
        return result

    def _load_saved_data_configuration(self):
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None, None
        if not isinstance(value, dict) or "data_dirs" not in value or "primary_data_dir" not in value:
            return None, None
        directories = self._normalize_data_directories(value.get("data_dirs"))
        primary_value = value.get("primary_data_dir")
        if not directories or not isinstance(primary_value, (str, os.PathLike)):
            return None, None
        primary = self._resolved_data_directory(primary_value)
        if not any(os.path.normcase(str(item)) == os.path.normcase(str(primary)) for item in directories):
            return None, None
        return directories, primary

    def _read_settings_document(self):
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _save_settings_document(self, settings):
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_name(
            f".{self.settings_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.settings_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _save_data_configuration(self):
        settings = self._read_settings_document()
        settings["data_dirs"] = [str(value) for value in self.data_dirs]
        settings["primary_data_dir"] = str(self.primary_data_dir)
        self._save_settings_document(settings)

    def add_data_directory(self, value):
        self._ensure_data_configuration_editable()
        directory = self._resolved_data_directory(value)
        if any(os.path.normcase(str(item)) == os.path.normcase(str(directory)) for item in self.data_dirs):
            return False
        self.data_dirs.append(directory)
        self._explicit_data_dirs = True
        try:
            self._save_data_configuration()
        except OSError:
            self.data_dirs.pop()
            raise
        return True

    def set_primary_data_directory(self, value):
        self._ensure_data_configuration_editable()
        directory = self._resolved_data_directory(value)
        if not any(os.path.normcase(str(item)) == os.path.normcase(str(directory)) for item in self.data_dirs):
            raise ValueError("primary 데이터 폴더는 현재 목록에 있어야 합니다.")
        previous_primary = self.primary_data_dir
        self.primary_data_dir = directory
        self.data_dir = directory
        self._explicit_data_dirs = True
        try:
            self._save_data_configuration()
        except OSError:
            self.primary_data_dir = previous_primary
            self.data_dir = previous_primary
            raise
        return True

    def remove_data_directory(self, value):
        self._ensure_data_configuration_editable()
        directory = self._resolved_data_directory(value)
        index = next(
            (
                position
                for position, item in enumerate(self.data_dirs)
                if os.path.normcase(str(item)) == os.path.normcase(str(directory))
            ),
            None,
        )
        if index is None:
            return False
        if len(self.data_dirs) == 1:
            raise ValueError("데이터 폴더는 하나 이상 필요합니다.")
        removed = self.data_dirs.pop(index)
        previous_primary = self.primary_data_dir
        if os.path.normcase(str(removed)) == os.path.normcase(str(self.primary_data_dir)):
            self.primary_data_dir = self.data_dirs[0]
            self.data_dir = self.primary_data_dir
        self._explicit_data_dirs = True
        try:
            self._save_data_configuration()
        except OSError:
            self.data_dirs.insert(index, removed)
            self.primary_data_dir = previous_primary
            self.data_dir = previous_primary
            raise
        return True

    @property
    def settings_path(self):
        return self.settings_dir / LAUNCHER_SETTINGS_NAME

    def load_settings(self):
        value = self._read_settings_document()
        settings = {"auto_open_site": bool(value.get("auto_open_site"))}
        data_dirs, primary = self._load_saved_data_configuration()
        if data_dirs is not None:
            settings["data_dirs"] = [str(item) for item in data_dirs]
            settings["primary_data_dir"] = str(primary)
        return settings

    def set_auto_open_site(self, enabled):
        settings = self._read_settings_document()
        settings["auto_open_site"] = bool(enabled)
        self._save_settings_document(settings)
        return settings["auto_open_site"]

    def wait_for_server(self, interval_seconds=0.1):
        while self.is_server_running():
            try:
                with self.urlopen(Request(APP_URL), timeout=1):
                    return True
            except Exception:
                if not self.is_server_running():
                    return False
                time.sleep(interval_seconds)
        return False

    def is_server_running(self):
        return bool(self.process and self.process.poll() is None)

    def start_server(self):
        if self.is_server_running():
            return "서버가 이미 실행 중입니다."
        command = [str(self.executable), "--server"] if self.frozen else [sys.executable, "app.py"]
        command.extend(self.data_directory_arguments())
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs = {
            "cwd": str(self.app_dir),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "creationflags": creationflags,
        }
        if self.frozen:
            kwargs["env"] = independent_frozen_environment()
        self.process = self.popen(command, **kwargs)
        return "서버를 시작했습니다."

    def stop_server(self):
        if not self.is_server_running():
            return "실행 중인 서버가 없습니다."
        if os.name == "nt" and self.frozen:
            completed = self.process_run(
                ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode == 0:
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                self.process = None
                return "서버를 종료했습니다."
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None
        return "서버를 종료했습니다."

    def open_site(self):
        self.browser_open(APP_URL)
        return "웹사이트를 열었습니다."

    def check_update(self):
        request = Request(
            GITHUB_LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "DanbooruArtistRaterLauncher"},
        )
        with self.urlopen(request, timeout=12) as response:
            release = json.loads(response.read().decode("utf-8"))
        latest = str(release.get("tag_name") or "").strip()
        asset = next(
            (
                item
                for item in release.get("assets", [])
                if item.get("name") == RELEASE_ASSET_NAME and item.get("browser_download_url")
            ),
            {},
        )
        return UpdateInfo(
            current_version=self.current_version,
            latest_version=latest or self.current_version,
            has_update=normalize_version(latest) > normalize_version(self.current_version),
            release_notes=str(release.get("body") or ""),
            asset_url=str(asset.get("browser_download_url") or ""),
            release_url=str(release.get("html_url") or ""),
        )

    def download_update(self, update_info):
        if not update_info.has_update:
            raise ValueError("설치할 새 업데이트가 없습니다.")
        if not update_info.asset_url:
            raise ValueError("릴리스에서 실행 파일을 찾지 못했습니다.")
        updates_dir = self.data_dir / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        target = updates_dir / RELEASE_ASSET_NAME
        request = Request(
            update_info.asset_url,
            headers={"User-Agent": "DanbooruArtistRaterLauncher"},
        )
        with self.urlopen(request, timeout=60) as response:
            target.write_bytes(response.read())
        return target

    def prepare_update_install(self, downloaded_exe):
        if not self.frozen:
            return "업데이트 파일을 받았습니다. 소스 실행 중에는 자동 교체하지 않습니다."
        script = self.data_dir / "updates" / "install_update.bat"
        current_exe = self.executable
        lines = [
            "@echo off",
            'set "PYINSTALLER_RESET_ENVIRONMENT=1"',
            "ping 127.0.0.1 -n 2 >nul",
            "for /l %%i in (1,1,30) do (",
            f'  copy /y "{downloaded_exe}" "{current_exe}" >nul 2>nul && goto updated',
            "  ping 127.0.0.1 -n 2 >nul",
            ")",
            f'start "" "{current_exe}"',
            "exit /b 1",
            ":updated",
            f'start "" "{current_exe}"',
            f'del "{downloaded_exe}" >nul 2>nul',
            'del "%~f0" >nul 2>nul',
        ]
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        self.popen(
            ["cmd", "/c", str(script)],
            cwd=str(script.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=independent_frozen_environment(),
        )
        return "업데이트를 설치합니다. 리모콘을 종료합니다."


def download_and_prepare_update(controller, update_info):
    target = controller.download_update(update_info)
    controller.stop_server()
    return controller.prepare_update_install(target)


class LauncherApp:
    def __init__(self, controller=None):
        self.controller = controller or LauncherController()
        self.latest_update = None
        self.root = Tk()
        self.root.title("Danbooru Artist Rater 리모콘")
        self.root.geometry("520x700")
        self.root.minsize(500, 660)
        self.root.configure(bg=LAUNCHER_THEME["window_bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        shell = Frame(self.root, bg=LAUNCHER_THEME["window_bg"])
        shell.pack(fill=BOTH, expand=True, padx=22, pady=22)

        header = Frame(shell, bg=LAUNCHER_THEME["window_bg"])
        header.pack(fill="x", pady=(0, 18))
        Label(
            header,
            text="Danbooru Artist Rater",
            bg=LAUNCHER_THEME["window_bg"],
            fg=LAUNCHER_THEME["text"],
            font=("Segoe UI", 20, "bold"),
            anchor="w",
        ).pack(fill="x")
        Label(
            header,
            text="로컬 서버와 업데이트를 한 곳에서 관리합니다.",
            bg=LAUNCHER_THEME["window_bg"],
            fg=LAUNCHER_THEME["muted"],
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", pady=(4, 0))

        status_card = self.card(shell)
        status_card.pack(fill="x", pady=(0, 14))
        self.status_dot = Label(
            status_card,
            text="●",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["success"],
            font=("Segoe UI", 14),
        )
        self.status_dot.pack(side=LEFT, padx=(16, 8), pady=14)
        self.status = Label(
            status_card,
            text="준비됨",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["text"],
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.status.pack(fill="x", expand=True, padx=(0, 16), pady=14)

        if not self.controller.frozen:
            self.build_data_directory_card(shell)

        action_card = self.card(shell)
        action_card.pack(fill="x", pady=(0, 14))
        Label(
            action_card,
            text="빠른 실행",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["muted"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(15, 8))
        for index, spec in enumerate(launcher_button_specs()):
            button = self.action_button(action_card, spec)
            button.pack(fill="x", padx=16, pady=(0, 8 if index < 1 else 7))
            if index == 0:
                self.auto_open_site = BooleanVar(value=self.controller.load_settings()["auto_open_site"])
                Checkbutton(
                    action_card,
                    text="서버를 켜면 웹사이트 자동으로 열기",
                    variable=self.auto_open_site,
                    command=self.save_auto_open_site,
                    bg=LAUNCHER_THEME["card_bg"],
                    fg=LAUNCHER_THEME["text"],
                    activebackground=LAUNCHER_THEME["card_bg"],
                    activeforeground=LAUNCHER_THEME["text"],
                    selectcolor=LAUNCHER_THEME["card_bg"],
                    font=("Segoe UI", 10),
                    anchor="w",
                ).pack(fill="x", padx=16, pady=(0, 10))

        notes_card = self.card(shell)
        notes_card.pack(fill=BOTH, expand=True)
        Label(
            notes_card,
            text="릴리스 노트와 로그",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["muted"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(15, 8))
        self.output = Text(
            notes_card,
            height=10,
            wrap="word",
            relief="flat",
            borderwidth=0,
            bg="#fbfbfd",
            fg=LAUNCHER_THEME["text"],
            insertbackground=LAUNCHER_THEME["primary"],
            font=("Segoe UI", 10),
            padx=12,
            pady=10,
        )
        self.output.pack(fill=BOTH, expand=True, padx=16, pady=(0, 16))
        self.write("서버를 켠 뒤 웹사이트 열기를 누르세요.\n")

    def build_data_directory_card(self, parent):
        data_card = self.card(parent)
        data_card.pack(fill="x", pady=(0, 14))
        header = Frame(data_card, bg=LAUNCHER_THEME["card_bg"])
        header.pack(fill="x", padx=16, pady=8)
        Label(
            header,
            text="데이터 폴더",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["muted"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(side=LEFT, fill="x", expand=True)
        self.data_card_expanded = False
        self.data_toggle_button = Button(
            header,
            text="펼치기",
            command=self.toggle_data_directory_card,
            relief="flat",
            bd=0,
            cursor="hand2",
            bg=LAUNCHER_THEME["secondary"],
            fg=LAUNCHER_THEME["text"],
            activebackground=LAUNCHER_THEME["secondary_active"],
            activeforeground=LAUNCHER_THEME["text"],
            font=("Segoe UI", 9),
            padx=10,
            pady=3,
        )
        self.data_toggle_button.pack(side=LEFT)
        self.data_directory_body = Frame(data_card, bg=LAUNCHER_THEME["card_bg"])
        self.data_primary_label = Label(
            self.data_directory_body,
            text="",
            bg=LAUNCHER_THEME["card_bg"],
            fg=LAUNCHER_THEME["text"],
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.data_primary_label.pack(fill="x", padx=16, pady=(0, 7))
        self.data_list = Listbox(
            self.data_directory_body,
            height=3,
            exportselection=False,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=LAUNCHER_THEME["card_border"],
            bg="#fbfbfd",
            fg=LAUNCHER_THEME["text"],
            selectbackground="#dbeafe",
            selectforeground=LAUNCHER_THEME["text"],
            font=("Segoe UI", 9),
        )
        self.data_list.pack(fill="x", padx=16, pady=(0, 8))
        controls = Frame(self.data_directory_body, bg=LAUNCHER_THEME["card_bg"])
        controls.pack(fill="x", padx=16, pady=(0, 12))
        for text, command in (
            ("폴더 추가", self.add_data_directory),
            ("선택을 기준으로", self.set_primary_data_directory),
            ("선택 제거", self.remove_data_directory),
        ):
            Button(
                controls,
                text=text,
                command=command,
                relief="flat",
                bd=0,
                cursor="hand2",
                bg=LAUNCHER_THEME["secondary"],
                fg=LAUNCHER_THEME["text"],
                activebackground=LAUNCHER_THEME["secondary_active"],
                activeforeground=LAUNCHER_THEME["text"],
                font=("Segoe UI", 9),
                padx=8,
                pady=5,
            ).pack(side=LEFT, padx=(0, 6))
        self.refresh_data_directory_list()

    def toggle_data_directory_card(self):
        if not hasattr(self, "data_directory_body"):
            return
        self.data_card_expanded = not self.data_card_expanded
        if self.data_card_expanded:
            self.data_directory_body.pack(fill="x")
            self.data_toggle_button.config(text="접기")
        else:
            self.data_directory_body.pack_forget()
            self.data_toggle_button.config(text="펼치기")

    def refresh_data_directory_list(self):
        if not hasattr(self, "data_list"):
            return
        self.data_list.delete(0, END)
        primary_key = os.path.normcase(str(self.controller.primary_data_dir))
        primary_index = 0
        for index, directory in enumerate(self.controller.data_dirs):
            is_primary = os.path.normcase(str(directory)) == primary_key
            if is_primary:
                primary_index = index
            marker = "★ 설정·저장 기준" if is_primary else "보조"
            self.data_list.insert(END, f"{marker}  {directory}")
        if self.controller.data_dirs:
            self.data_list.selection_set(primary_index)
            self.data_list.see(primary_index)
        self.data_primary_label.config(
            text=f"설정·저장 기준: {self.controller.primary_data_dir}"
        )

    def _selected_data_directory(self):
        selected = self.data_list.curselection()
        if not selected:
            self.set_status("오류: 먼저 데이터 폴더를 선택하세요.")
            return None
        return self.controller.data_dirs[selected[0]]

    def add_data_directory(self):
        directory = filedialog.askdirectory(parent=self.root, title="추가할 데이터 폴더 선택")
        if not directory:
            return
        try:
            added = self.controller.add_data_directory(directory)
        except (RuntimeError, ValueError, OSError) as exc:
            self.set_status(f"오류: {exc}")
            return
        self.refresh_data_directory_list()
        self.set_status("데이터 폴더를 추가했습니다." if added else "이미 추가된 데이터 폴더입니다.")

    def set_primary_data_directory(self):
        directory = self._selected_data_directory()
        if directory is None:
            return
        try:
            self.controller.set_primary_data_directory(directory)
        except (RuntimeError, ValueError, OSError) as exc:
            self.set_status(f"오류: {exc}")
            return
        self.refresh_data_directory_list()
        self.set_status("설정·저장 기준 데이터 폴더를 변경했습니다.")

    def remove_data_directory(self):
        directory = self._selected_data_directory()
        if directory is None:
            return
        try:
            removed = self.controller.remove_data_directory(directory)
        except (RuntimeError, ValueError, OSError) as exc:
            self.set_status(f"오류: {exc}")
            return
        self.refresh_data_directory_list()
        if removed:
            self.set_status("데이터 폴더를 제거했습니다.")

    def card(self, parent):
        return Frame(
            parent,
            bg=LAUNCHER_THEME["card_bg"],
            highlightbackground=LAUNCHER_THEME["card_border"],
            highlightcolor=LAUNCHER_THEME["card_border"],
            highlightthickness=1,
            bd=0,
        )

    def action_button(self, parent, spec):
        colors = {
            "primary": {
                "bg": LAUNCHER_THEME["primary"],
                "fg": "#ffffff",
                "active": LAUNCHER_THEME["primary_active"],
            },
            "secondary": {
                "bg": LAUNCHER_THEME["secondary"],
                "fg": LAUNCHER_THEME["text"],
                "active": LAUNCHER_THEME["secondary_active"],
            },
            "ghost": {
                "bg": LAUNCHER_THEME["card_bg"],
                "fg": LAUNCHER_THEME["primary"],
                "active": "#f2f2f7",
            },
        }[spec["style"]]
        return Button(
            parent,
            text=spec["text"],
            command=getattr(self, spec["command"]),
            relief="flat",
            bd=0,
            cursor="hand2",
            bg=colors["bg"],
            fg=colors["fg"],
            activebackground=colors["active"],
            activeforeground=colors["fg"],
            font=("Segoe UI", 11, "bold" if spec["style"] == "primary" else "normal"),
            padx=16,
            pady=10,
        )

    def write(self, message):
        self.output.insert(END, message)
        self.output.see(END)

    def set_status(self, message):
        self.status.config(text=message)
        if message.startswith("오류"):
            self.status_dot.config(fg=LAUNCHER_THEME["danger"])
        elif "종료" in message or "없습니다" in message:
            self.status_dot.config(fg=LAUNCHER_THEME["muted"])
        else:
            self.status_dot.config(fg=LAUNCHER_THEME["success"])
        self.write(f"{message}\n")

    def run_background(self, action, on_success):
        def worker():
            try:
                result = action()
            except Exception as exc:
                self.root.after(0, lambda: self.set_status(f"오류: {exc}"))
                return
            self.root.after(0, lambda: on_success(result))

        threading.Thread(target=worker, daemon=True).start()

    def save_auto_open_site(self):
        try:
            self.controller.set_auto_open_site(self.auto_open_site.get())
        except OSError as exc:
            self.set_status(f"오류: 자동 열기 설정을 저장하지 못했습니다: {exc}")

    def start_server(self):
        auto_open = bool(self.auto_open_site.get())
        self.set_status("서버를 시작하는 중입니다...")

        def action():
            message = self.controller.start_server()
            if not auto_open:
                return message
            if not self.controller.wait_for_server():
                return f"{message} 웹사이트가 준비되지 않아 자동으로 열지 못했습니다."
            return f"{message} {self.controller.open_site()}"

        self.run_background(action, self.set_status)

    def stop_server(self):
        self.set_status(self.controller.stop_server())

    def close_app(self):
        try:
            self.controller.stop_server()
        finally:
            self.root.destroy()

    def open_site(self):
        self.set_status(self.controller.open_site())

    def check_update(self):
        self.set_status("업데이트를 확인하는 중입니다...")

        def on_success(info):
            self.latest_update = info
            status = (
                f"새 버전이 있습니다: {info.latest_version}"
                if info.has_update
                else f"최신 버전입니다: {info.current_version}"
            )
            self.set_status(status)
            if info.release_notes:
                self.write("\n릴리스 노트\n")
                self.write(info.release_notes.strip() + "\n\n")

        self.run_background(self.controller.check_update, on_success)

    def install_update(self):
        if not self.latest_update:
            messagebox.showinfo("업데이트", "먼저 업데이트 확인을 눌러주세요.")
            return
        self.set_status("업데이트 파일을 받는 중입니다...")

        def action():
            return download_and_prepare_update(self.controller, self.latest_update)

        def on_success(message):
            self.set_status(message)
            if self.controller.frozen:
                self.close_app()

        self.run_background(action, on_success)

    def mainloop(self):
        self.root.mainloop()


def main():
    default_app_dir, default_data_dir = resolve_launcher_paths()
    has_cli_data_configuration = has_data_directory_options(sys.argv[1:])
    data_dirs, primary_data_dir = parse_data_directory_options(
        sys.argv[1:], default_data_dir=default_data_dir
    )
    if "--server" in sys.argv:
        from app import app, configure_data_directories, init_db

        if has_cli_data_configuration:
            configure_data_directories(data_dirs, primary_data_dir)
        else:
            controller = LauncherController(
                app_dir=default_app_dir,
                launcher_settings_dir=default_data_dir,
            )
            configure_data_directories(controller.data_dirs, controller.primary_data_dir)
        init_db()
        print("Danbooru Artist Rater")
        print(f"Open {APP_URL}")
        app.run(host="127.0.0.1", port=5001, debug=False)
        return
    controller_options = {
        "app_dir": default_app_dir,
        "launcher_settings_dir": default_data_dir,
    }
    if has_cli_data_configuration:
        controller_options.update(
            data_dirs=data_dirs,
            primary_data_dir=primary_data_dir,
        )
    LauncherApp(controller=LauncherController(**controller_options)).mainloop()


if __name__ == "__main__":
    main()
