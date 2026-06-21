# Arca Style Collection Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded Arca Live style collection with completed-search deduplication and an archive UI that supports inspection, prompt editing, and deletion.

**Architecture:** Keep persistence, parsing, metadata extraction, search coverage, and collection orchestration in a new `arca_style_collector.py` module, exposed through narrow Flask routes. Keep the new UI in an independent JavaScript file and dedicated template/CSS section so existing style-maker behavior remains unchanged.

**Tech Stack:** Python 3, Flask, SQLite, requests, standard-library HTML/PNG parsing, vanilla JavaScript, CSS, unittest, Node assert.

---

### Task 1: Archive schema, validation, and search coverage

**Files:**
- Create: `artist_rater/arca_style_collector.py`
- Create: `artist_rater/tests/test_arca_style_collector.py`

- [ ] Write failing unit tests that initialize a temporary database and assert the three archive tables exist; validate defaults and bounds; and verify completed intervals are merged and subtracted from a requested date range.
- [ ] Run `python -m unittest artist_rater.tests.test_arca_style_collector.ArchiveSchemaTest artist_rater.tests.test_arca_style_collector.CollectionCoverageTest` and confirm failures are caused by the missing module.
- [ ] Add constants, `ArcaCollectorError`, `init_arca_style_tables`, `normalize_collect_payload`, `merge_date_intervals`, `get_completed_coverage`, and `uncovered_date_intervals`. Use ISO dates and normalize tabs to a sorted unique subset of `NAI` and `R18_NAI`.
- [ ] Add `arca_style_items`, `arca_style_images`, and `arca_collection_runs`; enable foreign keys for each connection and index posted date, tab, metadata status, image item ID, and run lookup fields.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Resilient HTML/image parsing and NovelAI metadata

**Files:**
- Modify: `artist_rater/arca_style_collector.py`
- Modify: `artist_rater/tests/test_arca_style_collector.py`

- [ ] Add failing tests with representative HTML for category discovery, canonical `/b/aiart/<number>` links, article title/date/tab/body extraction, and image candidates from `src`, `data-src`, `data-original`, `srcset`, and enclosing anchors.
- [ ] Add failing PNG fixtures containing `tEXt`, compressed `zTXt`, and international `iTXt` JSON metadata; assert prompt, UC, seed, sampler, steps, scale, CFG rescale, scheduler, model, width, and height extraction plus body fallback behavior.
- [ ] Run the focused parser tests and confirm they fail on missing functions.
- [ ] Implement an `HTMLParser`-based collector, URL normalization restricted to HTTP(S), `discover_category_params`, `build_search_urls`, `extract_article_links`, `extract_article_data`, `extract_image_candidates`, `extract_png_text_chunks`, `extract_novelai_metadata`, and `parse_body_prompt_fallback`.
- [ ] Re-run the focused parser tests and confirm they pass.

### Task 3: Bounded collection, upsert, editing, and deletion

**Files:**
- Modify: `artist_rater/arca_style_collector.py`
- Modify: `artist_rater/tests/test_arca_style_collector.py`

- [ ] Add failing tests using a fake requests session to assert request timeouts/User-Agent, streamed maximum image size, rejected non-image responses, deterministic SHA-256 filenames, date/tab filtering, source/image upserts, representative-image selection, and completed versus failed run coverage.
- [ ] Add failing tests for `list_arca_styles`, `get_arca_style_detail`, `update_arca_style`, and `delete_arca_style`; assert PATCH fields are allowlisted and bounded, child rows cascade, referenced files survive, and unreferenced files are removed only under the archive root.
- [ ] Run `python -m unittest artist_rater.tests.test_arca_style_collector` and confirm failures identify the missing behaviors.
- [ ] Implement `fetch_html`, `download_image`, `save_image_bytes`, collection-run status updates, `_collect_interval`, `collect_arca_styles`, list/detail/update/delete operations, and safe orphan cleanup. A fully covered request must return `skipped_existing: true` before creating a session or fetching HTML.
- [ ] Re-run the collector test module and confirm it passes.

### Task 4: Flask integration and API contracts

**Files:**
- Modify: `artist_rater/app.py`
- Create: `artist_rater/tests/test_arca_style_api.py`

- [ ] Add failing Flask client tests that patch archive module calls and assert init, collect, list, detail, PATCH, DELETE, search-status, 404s, safe error responses, generated image URLs, and traversal-safe `/arca-style-images/<path>` behavior. Include regression assertions for `/api/art-styles` and `/generated/<path>`.
- [ ] Run `python -m unittest artist_rater.tests.test_arca_style_api` and confirm route-not-found failures.
- [ ] Import archive operations, define `ARCA_STYLE_IMAGE_DIR`, initialize its directory/tables after existing database setup, and add the seven archive routes. Validate JSON objects at the route boundary and log unexpected exceptions with `app.logger.exception`.
- [ ] Re-run API tests and the existing `artist_rater.tests.test_style_api` module; confirm both pass.

### Task 5: Independent archive UI

**Files:**
- Modify: `artist_rater/templates/index.html`
- Create: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/static/style.css`
- Create: `artist_rater/tests/arca_style_collector_behavior.test.js`
- Create: `artist_rater/tests/test_arca_style_frontend_contract.py`

- [ ] Add failing contract tests for the new tab, collection form, coverage status, filters, card list, edit dialog, delete action, and script include. Add Node tests for payload normalization, query building, coverage messages, editable PATCH payloads, and summary formatting.
- [ ] Run `python -m unittest artist_rater.tests.test_arca_style_frontend_contract` and `node artist_rater/tests/arca_style_collector_behavior.test.js`; confirm failures are caused by missing UI assets.
- [ ] Add the `공유 그림체 수집` section and accessible edit dialog to the template, loading `arca_style_collector.js` after existing scripts.
- [ ] Implement isolated state and DOM helpers; first-tab load; debounced list/status requests; collection; safe card rendering via `textContent`; copy/source/detail actions; PATCH save; confirmed DELETE; and dialog image gallery. Export pure helpers under CommonJS for Node tests.
- [ ] Add desktop 320px/list-grid styles and a one-column mobile layout without changing existing style-manager selectors.
- [ ] Re-run frontend tests and confirm they pass.

### Task 6: Full verification

**Files:**
- Verify all modified files.

- [ ] Run `python -m py_compile artist_rater/app.py artist_rater/arca_style_collector.py artist_rater/novelai.py artist_rater/style_store.py artist_rater/style_logic.py` and expect exit code 0.
- [ ] Run `node artist_rater/tests/arca_style_collector_behavior.test.js`, `node artist_rater/tests/style_maker_behavior.test.js`, and `node artist_rater/tests/app_behavior.test.js`; expect all tests to pass.
- [ ] Run `python -m unittest discover -s artist_rater/tests -p "test_*.py"`; expect all tests to pass.
- [ ] Run `git diff --check`; expect no whitespace errors.
- [ ] Start the Flask app on its configured local port and verify in the in-app browser that the four existing tabs still open, the archive list loads, covered searches do not make a collection request, prompts save, and confirmed deletion removes a card.
