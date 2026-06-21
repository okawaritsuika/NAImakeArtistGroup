# Style Manager Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe whole-style deletion to the style manager and replace the existing `v0.1.0` release executable with the verified build.

**Architecture:** `style_store.py` owns transactional database deletion and bounded filesystem cleanup. `app.py` exposes that operation through the existing art-style detail route, while `style_maker.js` adds the confirmation and post-delete UI refresh without changing the template structure.

**Tech Stack:** Python 3, Flask, SQLite, vanilla JavaScript, Node test runner, unittest, PyInstaller, GitHub CLI

---

### Task 1: Store-level style deletion

**Files:**
- Modify: `artist_rater/tests/test_style_api.py`
- Modify: `artist_rater/style_store.py`

- [ ] Add a failing test that generates a style, calls `style_store.delete_style(db_path, generated_dir, style_id)`, and asserts the style row, generated-image rows, generation-request rows, PNG file, and empty style directory are gone.
- [ ] Add a failing test that asserts an unknown style returns `None`, a missing owned file does not fail deletion, and a forged path outside `generated_dir` is never unlinked.
- [ ] Run `python -m unittest artist_rater.tests.test_style_api.StyleApiTest.test_delete_style_removes_database_records_and_files artist_rater.tests.test_style_api.StyleApiTest.test_delete_style_is_bounded_and_handles_missing_data` and confirm failure because `delete_style` does not exist.
- [ ] Implement `delete_style(db_path, generated_dir, style_id)` in `style_store.py`: select the style and image paths, delete matching `generation_requests`, `generated_images`, and `art_styles` inside one transaction, then unlink only resolved paths whose parent chain contains the resolved generated root and remove the empty `<generated_dir>/<style_id>` directory. Return `{"style_id": int(style_id), "deleted": True}` or `None`.
- [ ] Re-run the two focused tests and confirm both pass.
- [ ] Commit `style_store.py` and its tests with `feat: delete stored art styles`.

### Task 2: DELETE API

**Files:**
- Modify: `artist_rater/tests/test_style_api.py`
- Modify: `artist_rater/app.py`

- [ ] Add a failing API test that generates a style, sends `DELETE /api/art-styles/<id>`, expects `200` and `{"deleted": true, "style_id": id}`, then confirms GET returns 404 and the PNG is absent. Extend the unknown-style test to assert DELETE returns 404.
- [ ] Run the focused API tests and confirm DELETE currently returns 405.
- [ ] Import `delete_style` and change `/api/art-styles/<int:style_id>` to accept `GET` and `DELETE`; on DELETE call `delete_style(DB_PATH, GENERATED_DIR, style_id)` and return 404 with `{"error": "Art style not found."}` when it returns `None`.
- [ ] Re-run the focused API tests and `python -m unittest artist_rater.tests.test_style_api`.
- [ ] Commit the API and tests with `feat: expose art style deletion API`.

### Task 3: Style-manager delete action

**Files:**
- Modify: `artist_rater/tests/test_style_frontend_contract.py`
- Modify: `artist_rater/static/style_maker.js`

- [ ] Add a failing frontend contract test requiring the strings `그림체 삭제`, `생성 이미지도 함께 삭제됩니다`, `method: "DELETE"`, and a `deleteManagedStyle` function in `style_maker.js`.
- [ ] Run `python -m unittest artist_rater.tests.test_style_frontend_contract.StyleFrontendContractTest.test_style_manager_supports_whole_style_deletion` and confirm the markers are absent.
- [ ] Add a danger-styled button to `loadStyleDetail`; add `resetStyleManagerDetail()` and `deleteManagedStyle(styleId)` that confirms destructive deletion, calls the DELETE endpoint, reloads the list, resets the detail placeholder, and writes failures to `styleManagerStatus`.
- [ ] Re-run the focused frontend contract test, `python -m unittest artist_rater.tests.test_style_frontend_contract`, and `node artist_rater/tests/style_maker_behavior.test.js`.
- [ ] Commit the UI and tests with `feat: delete styles from style manager`.

### Task 4: Verification, packaging, push, and release replacement

**Files:**
- Verify: all modified source and test files
- Build: `release/DanbooruArtistRater.exe`

- [ ] Run `python -m py_compile artist_rater/app.py artist_rater/style_store.py`.
- [ ] Run `python -m unittest discover -s artist_rater/tests -p "test_*.py"` and all three JavaScript suites under `artist_rater/tests`.
- [ ] Run `git diff --check`, `git status --short`, and inspect the final diff and commit list.
- [ ] Run `powershell -ExecutionPolicy Bypass -File build_exe.ps1`, confirm exit code 0, and record the new executable SHA-256 hash.
- [ ] Run the packaging test against the fresh executable where supported, then confirm the file exists and has nonzero size.
- [ ] Push the current branch to `origin/main` as requested, without force.
- [ ] Run `gh release delete-asset v0.1.0 DanbooruArtistRater.exe --yes`, then `gh release upload v0.1.0 release/DanbooruArtistRater.exe --clobber`.
- [ ] Query `gh release view v0.1.0 --json assets,url` and confirm the published asset name, size, and digest match the local executable.
