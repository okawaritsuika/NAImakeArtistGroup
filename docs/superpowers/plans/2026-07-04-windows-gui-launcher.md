# Windows GUI Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Python-based Windows GUI launcher that can start/stop the local Flask server, open the website, check GitHub releases, show release notes, and prepare EXE updates.

**Architecture:** `artist_rater/launcher.py` owns launcher state, subprocess control, browser opening, GitHub release checks, and a small `tkinter` GUI. The Flask server remains in `app.py`; packaging switches the EXE entry point from `app.py` to `launcher.py` while still bundling templates/static files. Tests cover pure launcher behavior with injected process/browser/network dependencies.

**Tech Stack:** Python 3 standard library (`tkinter`, `subprocess`, `webbrowser`, `urllib`, `json`, `pathlib`, `threading`), Flask app entry point, PyInstaller, `unittest`.

---

### Task 1: Launcher Core

**Files:**
- Create: `artist_rater/launcher.py`
- Test: `artist_rater/tests/test_launcher.py`

- [ ] Write failing tests for `LauncherController.start_server`, `stop_server`, `open_site`, and release comparison.
- [ ] Implement `LauncherController` with injected `popen`, `browser_open`, `urlopen`, and paths.
- [ ] Ensure `start_server` is idempotent when a tracked process is still running.
- [ ] Ensure `stop_server` terminates only the tracked process.

### Task 2: GUI Remote

**Files:**
- Modify: `artist_rater/launcher.py`
- Test: `artist_rater/tests/test_launcher.py`

- [ ] Add `LauncherApp` using `tkinter` with buttons for start, stop, open site, check update, and update.
- [ ] Keep network and update actions off the UI thread with `threading.Thread`.
- [ ] Display latest version and release notes in the GUI text area.

### Task 3: Update Preparation

**Files:**
- Modify: `artist_rater/launcher.py`
- Test: `artist_rater/tests/test_launcher.py`

- [ ] Fetch `https://api.github.com/repos/okawaritsuika/NAImakeArtistGroup/releases/latest`.
- [ ] Find `DanbooruArtistRater.exe` in release assets.
- [ ] Download the asset to `data/updates/DanbooruArtistRater.exe`.
- [ ] If running frozen, write an update command script that waits for the current process to exit and replaces the executable.
- [ ] If running from source, report that update download is prepared but EXE replacement applies only to packaged builds.

### Task 4: Packaging and Run Script

**Files:**
- Modify: `artist_rater/run.bat`
- Modify: `build_exe.ps1`
- Modify: `README.md`
- Test: `artist_rater/tests/test_run_script.py`
- Test: `artist_rater/tests/test_packaging.py`

- [ ] Change `run.bat` to call `python launcher.py`.
- [ ] Change PyInstaller entry point to `launcher.py`.
- [ ] Keep existing data exclusion behavior.
- [ ] Update README to describe the GUI launcher.

### Task 5: Verification

**Commands:**
- `python -m unittest tests.test_launcher`
- `python -m unittest tests.test_run_script tests.test_packaging`
- `python -m unittest discover -s tests`
