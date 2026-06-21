# Arca Collection Progress and Prompt Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add observable background collection jobs, trustworthy NovelAI prompt extraction, per-post style grouping, and deletion-triggered recollection eligibility.

**Architecture:** Keep `arca_style_collector.py` responsible for archive persistence, metadata parsing, grouping, coverage, and job execution. Add a persisted parent job around the existing per-interval run records, expose narrow Flask job endpoints, and keep rendering/polling isolated in `arca_style_collector.js`. Compute image groups from structured per-image prompts when details are requested; do not persist derived groups.

**Tech Stack:** Python 3.10, Flask, SQLite, requests, Pillow, `threading.Thread`, vanilla JavaScript, CSS, `unittest`, Node `assert`.

---

## File structure

- Modify `artist_rater/arca_style_collector.py`: schema migrations, structured metadata, grouping, job progress, coverage invalidation, and deletion semantics.
- Modify `artist_rater/app.py`: start/status routes and startup recovery for interrupted jobs.
- Modify `artist_rater/templates/index.html`: progress elements and grouped-detail containers.
- Modify `artist_rater/static/arca_style_collector.js`: polling, progress rendering, prompt tabs, and style-group rendering.
- Modify `artist_rater/static/style.css`: progress and group presentation.
- Modify `artist_rater/tests/test_arca_style_collector.py`: persistence, parsing, grouping, job, and deletion unit tests.
- Modify `artist_rater/tests/test_arca_style_api.py`: asynchronous API contracts and compatibility tests.
- Modify `artist_rater/tests/test_arca_style_frontend_contract.py`: required DOM/CSS contract.
- Modify `artist_rater/tests/arca_style_collector_behavior.test.js`: pure progress/group rendering helpers.

### Task 1: Persist collection jobs and structured image prompts

**Files:**
- Modify: `artist_rater/arca_style_collector.py:65-106`
- Test: `artist_rater/tests/test_arca_style_collector.py:63-90`

- [ ] **Step 1: Write failing migration tests**

Add a test that initializes both a new database and a legacy three-table database. Assert `arca_collection_jobs`, `arca_collection_run_items`, and `arca_collection_invalidations` exist; `arca_style_images` contains `base_prompt` and `character_prompts_json`; and `arca_collection_runs` contains `job_id`.

```python
def test_schema_adds_jobs_prompt_parts_and_recollection_links(self):
    with closing(sqlite3.connect(self.db_path)) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        image_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_style_images)")}
        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(arca_collection_runs)")}
    self.assertTrue({
        "arca_collection_jobs", "arca_collection_run_items",
        "arca_collection_invalidations",
    } <= tables)
    self.assertTrue({"base_prompt", "character_prompts_json"} <= image_columns)
    self.assertIn("job_id", run_columns)
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_schema_adds_jobs_prompt_parts_and_recollection_links`

Expected: FAIL because the new tables/columns do not exist.

- [ ] **Step 3: Add idempotent schema and migrations**

Create `arca_collection_jobs` with request JSON, status, stage, page/post/image totals, saved/updated counters, timing fields, ETA inputs, error, and timestamps. Create run-item links and invalidations with normalized search-key columns and a unique `(keyword,tabs,max_pages,max_posts,search_scope,invalidated_date)` constraint. Add columns only when absent.

```python
def _ensure_column(conn, table, name, declaration):
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

# inside init_arca_style_tables
conn.executescript("""
CREATE TABLE IF NOT EXISTS arca_collection_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'queued',
    total_pages INTEGER,
    scanned_pages INTEGER NOT NULL DEFAULT 0,
    total_posts INTEGER,
    scanned_posts INTEGER NOT NULL DEFAULT 0,
    downloaded_images INTEGER NOT NULL DEFAULT 0,
    saved INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    average_post_seconds REAL,
    skipped_existing INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS arca_collection_run_items (
    run_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    PRIMARY KEY(run_id,item_id),
    FOREIGN KEY(run_id) REFERENCES arca_collection_runs(id) ON DELETE CASCADE,
    FOREIGN KEY(item_id) REFERENCES arca_style_items(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS arca_collection_invalidations (
    keyword TEXT NOT NULL, tabs TEXT NOT NULL,
    max_pages INTEGER NOT NULL, max_posts INTEGER NOT NULL,
    search_scope TEXT NOT NULL, invalidated_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(keyword,tabs,max_pages,max_posts,search_scope,invalidated_date)
);
""")
_ensure_column(conn, "arca_collection_runs", "job_id", "INTEGER REFERENCES arca_collection_jobs(id)")
_ensure_column(conn, "arca_style_images", "base_prompt", "TEXT NOT NULL DEFAULT ''")
_ensure_column(conn, "arca_style_images", "character_prompts_json", "TEXT NOT NULL DEFAULT '[]'")
```

- [ ] **Step 4: Run schema tests**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_schema_adds_jobs_prompt_parts_and_recollection_links artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_schema_and_payload_validation`

Expected: both PASS.

- [ ] **Step 5: Commit schema changes**

```powershell
git add artist_rater/arca_style_collector.py artist_rater/tests/test_arca_style_collector.py
git commit -m "feat: add persisted Arca collection jobs"
```

### Task 2: Validate NovelAI metadata and split prompt sections

**Files:**
- Modify: `artist_rater/arca_style_collector.py:342-446,593-613`
- Test: `artist_rater/tests/test_arca_style_collector.py:180-300`

- [ ] **Step 1: Add failing legacy, V4, and generic-PNG tests**

```python
def test_rejects_generic_png_prompt_metadata(self):
    meta = extract_novelai_metadata(
        png_with_text("Comment", json.dumps({"prompt": "http://www.pdf-tools.com"})),
        "image/png",
    )
    self.assertEqual(meta["metadata_status"], "no_metadata")
    self.assertEqual(meta["base_prompt"], "")

def test_extracts_v4_base_negative_and_character_prompts(self):
    payload = {
        "v4_prompt": {"caption": {
            "base_caption": "artist:foo, watercolor",
            "char_captions": [
                {"char_caption": "1girl, blue hair", "centers": [{"x": 0.3, "y": 0.4}]},
                {"char_caption": "1boy, black hair", "centers": [{"x": 0.7, "y": 0.4}]},
            ],
        }},
        "v4_negative_prompt": {"caption": {"base_caption": "lowres, blurry"}},
        "seed": 7, "sampler": "k_euler", "steps": 28,
    }
    meta = extract_novelai_metadata(png_with_text("Comment", json.dumps(payload)), "image/png")
    self.assertEqual(meta["base_prompt"], "artist:foo, watercolor")
    self.assertEqual(meta["negative_prompt"], "lowres, blurry")
    self.assertEqual([c["prompt"] for c in meta["character_prompts"]], [
        "1girl, blue hair", "1boy, black hair",
    ])
```

- [ ] **Step 2: Run metadata tests and confirm failure**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_rejects_generic_png_prompt_metadata artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_extracts_v4_base_negative_and_character_prompts`

Expected: FAIL because generic prompt text is accepted and structured fields are absent.

- [ ] **Step 3: Implement strict recognition and structured extraction**

Add `_is_novelai_metadata(values)` that accepts V4 structures or a legacy prompt accompanied by at least two generation keys from `seed`, `sampler`, `steps`, `scale`, `noise_schedule`, `model`, `width`, and `height`. Return `base_prompt`, `negative_prompt`, and `character_prompts`; retain `prompt` as a compatibility alias for `base_prompt`.

```python
GENERATION_KEYS = {"seed", "sampler", "steps", "scale", "noise_schedule", "model", "width", "height"}

def _is_novelai_metadata(values):
    if not isinstance(values, dict):
        return False
    if isinstance(values.get("v4_prompt"), dict):
        return True
    return bool(values.get("prompt")) and len(GENERATION_KEYS.intersection(values)) >= 2

def _extract_prompt_parts(values):
    v4_prompt = values.get("v4_prompt") if isinstance(values.get("v4_prompt"), dict) else {}
    caption = v4_prompt.get("caption") if isinstance(v4_prompt.get("caption"), dict) else {}
    base_prompt = str(caption.get("base_caption") or values.get("prompt") or "")
    characters = []
    for entry in caption.get("char_captions", []):
        if isinstance(entry, dict) and entry.get("char_caption"):
            characters.append({
                "prompt": str(entry["char_caption"]),
                "centers": entry.get("centers") if isinstance(entry.get("centers"), list) else [],
            })
    negative_block = values.get("v4_negative_prompt")
    negative_caption = negative_block.get("caption", {}) if isinstance(negative_block, dict) else {}
    negative_prompt = str(negative_caption.get("base_caption") or values.get("uc") or values.get("negative_prompt") or "")
    return base_prompt, negative_prompt, characters
```

Persist structured fields in `_save_article` and serialize character prompts with `json.dumps(..., ensure_ascii=False)`. Add `revalidate_stored_metadata(db_path)` to parse each existing `raw_metadata_json`: backfill structured prompt fields for valid NovelAI rows and clear false-positive `metadata_status`, `prompt`, and `negative_prompt` values for generic metadata. Call it once at startup after schema initialization. Keep downloaded post images available in the gallery, but exclude rejected metadata from representative-prompt selection and similarity grouping.

- [ ] **Step 4: Run all metadata and persistence tests**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -k metadata`

Expected: PASS, including existing stealth PNG extraction.

- [ ] **Step 5: Commit metadata changes**

```powershell
git add artist_rater/arca_style_collector.py artist_rater/tests/test_arca_style_collector.py
git commit -m "fix: validate and split NovelAI prompts"
```

### Task 3: Compute style groups from normalized prompt tags

**Files:**
- Modify: `artist_rater/arca_style_collector.py:495-525`
- Test: `artist_rater/tests/test_arca_style_collector.py`

- [ ] **Step 1: Add failing tokenization and grouping tests**

```python
def test_groups_similar_style_prompts_and_keeps_singletons(self):
    images = [
        {"id": 1, "base_prompt": "artist:foo, watercolor, 1girl, blue hair", "negative_prompt": "lowres", "character_prompts": []},
        {"id": 2, "base_prompt": "watercolor, artist:foo, 1boy, black hair", "negative_prompt": "lowres, blurry", "character_prompts": []},
        {"id": 3, "base_prompt": "artist:bar, 3d render, robot", "negative_prompt": "bad hands", "character_prompts": []},
    ]
    groups = build_style_groups(images)
    self.assertEqual([[image["id"] for image in group["images"]] for group in groups], [[1, 2], [3]])
    self.assertEqual(groups[0]["common_base_tags"], ["artist:foo", "watercolor"])
    self.assertTrue(groups[1]["singleton"])

def test_top_level_commas_preserve_emphasis_groups(self):
    self.assertEqual(split_prompt_tags("{artist:foo, watercolor}, 1girl"), [
        "{artist:foo, watercolor}", "1girl",
    ])
```

- [ ] **Step 2: Run grouping tests and confirm missing functions**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_groups_similar_style_prompts_and_keeps_singletons artist_rater.tests.test_arca_style_collector.ArcaCollectorTest.test_top_level_commas_preserve_emphasis_groups`

Expected: FAIL with import/name errors.

- [ ] **Step 3: Implement deterministic weighted grouping**

Add top-level comma parsing, normalization, transient-tag weighting, weighted Jaccard similarity, and connected components with `STYLE_SIMILARITY_THRESHOLD = 0.55`. Preserve original tag order in output.

```python
STYLE_SIMILARITY_THRESHOLD = 0.55
TRANSIENT_TAG = re.compile(r"^(?:\d+(?:girl|boy)s?|solo|multiple girls|portrait|upper body|full body|looking at|smile|open mouth|.*hair|.*eyes)$", re.I)

def weighted_tag_similarity(left, right):
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    weight = lambda tag: 0.25 if TRANSIENT_TAG.match(tag) else 1.0
    shared = sum(weight(tag) for tag in set(left) & set(right))
    total = sum(weight(tag) for tag in keys)
    return shared / total
```

`build_style_groups` must return `images`, `singleton`, `representative_image_id`, `common_base_tags`, `common_negative_tags`, and each image's `different_base_tags`, `different_negative_tags`, and `character_prompts`.

- [ ] **Step 4: Add groups to item details and run tests**

Deserialize `character_prompts_json` in `get_arca_style_detail`, call `build_style_groups(images)`, and expose `style_groups` while preserving `images` and `prompts` compatibility fields. Reuse the same helper in `list_arca_styles` to add `style_group_count`; do not return full group payloads in list responses.

Run: `python -m unittest artist_rater.tests.test_arca_style_collector`

Expected: all collector tests PASS.

- [ ] **Step 5: Commit grouping changes**

```powershell
git add artist_rater/arca_style_collector.py artist_rater/tests/test_arca_style_collector.py
git commit -m "feat: group Arca images by style prompts"
```

### Task 4: Run collection as an observable background job

**Files:**
- Modify: `artist_rater/arca_style_collector.py:554-613`
- Test: `artist_rater/tests/test_arca_style_collector.py`

- [ ] **Step 1: Add failing job lifecycle and progress tests**

Use a fake executor so tests remain deterministic. Assert queued creation, incremental page/post/image updates, rolling ETA readiness, completed state, failed state, and startup interruption recovery.

```python
def test_job_progress_is_persisted_after_each_post(self):
    job_id = create_collection_job(self.db_path, {
        "keyword": "그림체 공유", "tabs": ["NAI"],
        "start_date": "2026-06-01", "end_date": "2026-06-02",
        "max_pages": 2, "max_posts": 3,
    })
    update_collection_job(self.db_path, job_id, stage="downloading", scanned_pages=1,
                          total_posts=3, scanned_posts=2, downloaded_images=4,
                          average_post_seconds=2.5)
    status = get_collection_job(self.db_path, job_id)
    self.assertEqual(status["progress"], {"pages": [1, 2], "posts": [2, 3], "images": 4})
    self.assertEqual(status["estimated_remaining_seconds"], 2)
```

- [ ] **Step 2: Run job tests and confirm failure**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -k job`

Expected: FAIL because job helpers do not exist.

- [ ] **Step 3: Implement job helpers and interruption recovery**

Implement `create_collection_job`, `update_collection_job`, `get_collection_job`, and `mark_interrupted_collection_jobs`. Use short independent SQLite transactions so polling sees updates.

```python
def mark_interrupted_collection_jobs(db_path):
    now = datetime.now().isoformat(timespec="seconds")
    with closing(_connect(db_path)) as conn, conn:
        conn.execute("""
            UPDATE arca_collection_jobs
            SET status='interrupted', stage='interrupted',
                error='앱이 종료되어 수집이 중단되었습니다.', finished_at=?, updated_at=?
            WHERE status IN ('queued','running')
        """, (now, now))
```

`get_collection_job` computes elapsed time from timestamps and ETA as `round(average_post_seconds * max(total_posts - scanned_posts, 0))`; return `None` when the job does not exist.

- [ ] **Step 4: Refactor collection orchestration to report progress**

Change `collect_arca_styles(..., job_id=None)` to update the parent job at discovery, page scan, post fetch, image download, save, completion, and failure boundaries. Add a `progress` callback to `_save_article` rather than coupling image download code to SQL job updates. Keep direct synchronous calls valid for existing tests.

Run: `python -m unittest artist_rater.tests.test_arca_style_collector`

Expected: all collector tests PASS.

- [ ] **Step 5: Commit job orchestration**

```powershell
git add artist_rater/arca_style_collector.py artist_rater/tests/test_arca_style_collector.py
git commit -m "feat: report live Arca collection progress"
```

### Task 5: Invalidate coverage when a collected post is deleted

**Files:**
- Modify: `artist_rater/arca_style_collector.py:164-168,541-553,593-613`
- Test: `artist_rater/tests/test_arca_style_collector.py`

- [ ] **Step 1: Add failing deletion and coverage tests**

Create a completed run linked to an item dated `2026-06-10`. Delete it, assert that only June 10 becomes uncovered, then simulate a successful recollection and assert the invalidation is cleared.

```python
def test_delete_reopens_only_the_items_date_for_associated_search(self):
    item_id, run_id = self._insert_completed_run_item("2026-06-01", "2026-06-30", "2026-06-10")
    result = delete_arca_style(self.db_path, Path(self.temp.name) / "images", item_id)
    self.assertTrue(result["deleted"])
    params = normalize_collect_payload({
        "start_date": "2026-06-01", "end_date": "2026-06-30",
        "tabs": ["NAI", "R18_NAI"],
    })
    coverage = get_completed_coverage(self.db_path, params)
    self.assertEqual(uncovered_date_intervals(
        date(2026, 6, 1), date(2026, 6, 30), coverage,
    ), [
        (date(2026, 6, 10), date(2026, 6, 10)),
    ])
```

- [ ] **Step 2: Run deletion tests and confirm failure**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -k reopen`

Expected: FAIL because deletion returns a boolean and coverage ignores invalidations.

- [ ] **Step 3: Record run-item links and subtract invalidated dates**

After each upsert, insert `(run_id,item_id)` into `arca_collection_run_items`. During deletion, query associated normalized run keys before deleting the item and insert one invalidation per key/date in the same transaction. Rename the current completed-run query to `_get_completed_coverage_intervals`; make public `get_completed_coverage` subtract invalidated single-day intervals.

```python
def get_effective_coverage(db_path, params):
    completed = _get_completed_coverage_intervals(db_path, params)
    invalid = get_invalidated_dates(db_path, params)
    days = []
    for start, end in completed:
        cursor = start
        while cursor <= end:
            if cursor not in invalid:
                days.append((cursor, cursor))
            cursor += timedelta(days=1)
    return merge_date_intervals(days)
```

On successful completion of an uncovered interval, delete matching invalidations within that interval. Return `{"deleted": True, "recollect_date": posted_at or None}` from deletion.

- [ ] **Step 4: Run collector coverage/deletion tests**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector`

Expected: all PASS, including existing full and partial coverage behavior.

- [ ] **Step 5: Commit recollection behavior**

```powershell
git add artist_rater/arca_style_collector.py artist_rater/tests/test_arca_style_collector.py
git commit -m "feat: recollect deleted Arca posts"
```

### Task 6: Expose asynchronous collection APIs

**Files:**
- Modify: `artist_rater/app.py:16-25,190-193,1152-1204`
- Test: `artist_rater/tests/test_arca_style_api.py`

- [ ] **Step 1: Add failing API tests**

Patch `Thread` with an inline fake and collection helpers with mocks. Assert `POST /api/arca-styles/collect` returns 202 and a job ID, `GET /api/arca-styles/collection-jobs/<id>` returns progress, missing jobs return 404, DELETE returns the recollection date, and legacy list/detail routes still work.

```python
def test_collect_starts_background_job(self):
    with patch.object(app_module, "start_collection_job", return_value=17):
        response = self.client.post("/api/arca-styles/collect", json={
            "start_date": "2026-06-01", "end_date": "2026-06-30",
        })
    self.assertEqual(response.status_code, 202)
    self.assertEqual(response.get_json(), {"job_id": 17, "status": "queued"})

def test_job_status_returns_not_found(self):
    with patch.object(app_module, "get_collection_job", return_value=None):
        response = self.client.get("/api/arca-styles/collection-jobs/999")
    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run API tests and confirm failure**

Run: `python -m unittest artist_rater.tests.test_arca_style_api`

Expected: FAIL on synchronous 200 response and missing job route.

- [ ] **Step 3: Implement start/status routes**

Add `start_collection_job` in the collector module: normalize, persist, and start a daemon `Thread` whose target calls `collect_arca_styles(..., job_id=job_id)`. The Flask POST returns 202 without waiting. Add the status GET route and call `mark_interrupted_collection_jobs(DB_PATH)` once during startup after schema initialization.

```python
@app.route("/api/arca-styles/collection-jobs/<int:job_id>")
def api_arca_collection_job(job_id):
    job = get_collection_job(DB_PATH, job_id)
    if job is None:
        return json_response({"error": "수집 작업을 찾을 수 없습니다."}, 404)
    return json_response(job)
```

Update DELETE to return the collector result, including `recollect_date`.

- [ ] **Step 4: Run API and regression tests**

Run: `python -m unittest artist_rater.tests.test_arca_style_api artist_rater.tests.test_style_api`

Expected: all PASS.

- [ ] **Step 5: Commit API changes**

```powershell
git add artist_rater/app.py artist_rater/tests/test_arca_style_api.py
git commit -m "feat: add Arca collection job API"
```

### Task 7: Show live progress and ETA without blocking the archive

**Files:**
- Modify: `artist_rater/templates/index.html:373-385`
- Modify: `artist_rater/static/arca_style_collector.js:1-16`
- Modify: `artist_rater/static/style.css:1152-1172`
- Test: `artist_rater/tests/test_arca_style_frontend_contract.py`
- Test: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] **Step 1: Add failing DOM and helper tests**

Require `arcaCollectionState`, `arcaCollectionProgress`, `arcaCollectionCounts`, `arcaCollectionElapsed`, and `arcaCollectionEta`. Add Node tests for unknown totals, determinate percentages, ETA text, terminal states, and summary text.

```javascript
assert.deepEqual(collectionProgress({scanned_posts: 2, total_posts: 5}), {
  determinate: true, percent: 40
});
assert.deepEqual(collectionProgress({scanned_posts: 0, total_posts: null}), {
  determinate: false, percent: 0
});
assert.equal(durationText(65), "1분 5초");
assert.equal(etaText(null), "계산 중");
```

- [ ] **Step 2: Run frontend tests and confirm failure**

Run `python -m unittest artist_rater.tests.test_arca_style_frontend_contract`, then run `node artist_rater/tests/arca_style_collector_behavior.test.js`.

Expected: FAIL because progress elements/helpers are absent.

- [ ] **Step 3: Add progress markup and pure helpers**

Add an accessible `<progress>` element and text nodes for state, counts, elapsed time, and ETA. Implement `collectionProgress`, `durationText`, `etaText`, and `collectionCountsText`; export them under CommonJS.

```javascript
function collectionProgress(job) {
  const total = Number(job?.progress?.posts?.[1] ?? job?.total_posts);
  const done = Number(job?.progress?.posts?.[0] ?? job?.scanned_posts ?? 0);
  return Number.isFinite(total) && total > 0
    ? { determinate: true, percent: Math.min(100, Math.round(done * 100 / total)) }
    : { determinate: false, percent: 0 };
}
```

- [ ] **Step 4: Poll jobs while leaving list actions enabled**

After POST, save `job_id`, poll every second, update progress, and stop only on `completed`, `failed`, or `interrupted`. Disable only collection form controls. Refresh the list after completion; always clear the timer on terminal state.

```javascript
async function pollArcaCollectionJob(jobId) {
  const job = await arcaFetch(`/api/arca-styles/collection-jobs/${jobId}`);
  renderArcaCollectionProgress(job);
  if (["completed", "failed", "interrupted"].includes(job.status)) {
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    if (job.status === "completed") await loadArcaStyles();
    return;
  }
  arcaState.pollTimer = setTimeout(() => pollArcaCollectionJob(jobId), 1000);
}
```

- [ ] **Step 5: Style and verify progress UI**

Add state badge colors, full-width progress styling, compact metric rows, and mobile wrapping. Run:

Run `python -m unittest artist_rater.tests.test_arca_style_frontend_contract`, then run `node artist_rater/tests/arca_style_collector_behavior.test.js`.

Expected: both PASS.

- [ ] **Step 6: Commit progress UI**

```powershell
git add artist_rater/templates/index.html artist_rater/static/arca_style_collector.js artist_rater/static/style.css artist_rater/tests/test_arca_style_frontend_contract.py artist_rater/tests/arca_style_collector_behavior.test.js
git commit -m "feat: show Arca collection progress"
```

### Task 8: Render grouped base, negative, and character prompts

**Files:**
- Modify: `artist_rater/templates/index.html:385`
- Modify: `artist_rater/static/arca_style_collector.js:9-15`
- Modify: `artist_rater/static/style.css:1165-1172`
- Test: `artist_rater/tests/test_arca_style_frontend_contract.py`
- Test: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] **Step 1: Add failing group-view tests**

Assert card summaries include group/image counts. Require prompt-tab controls and test pure model helpers that distinguish common tags, image differences, characters, and singleton labels.

```javascript
const group = {
  singleton: false,
  common_base_tags: ["artist:foo", "watercolor"],
  common_negative_tags: ["lowres"],
  images: [{id: 1, different_base_tags: ["blue hair"], character_prompts: [{prompt: "1girl"}]}],
};
assert.equal(groupTitle(group, 0), "그림체 그룹 1 · 이미지 1장");
assert.deepEqual(promptSection(group, "base").common, ["artist:foo", "watercolor"]);
assert.equal(groupTitle({...group, singleton: true}, 0), "개별 이미지");
```

- [ ] **Step 2: Run group frontend tests and confirm failure**

Run `python -m unittest artist_rater.tests.test_arca_style_frontend_contract`, then run `node artist_rater/tests/arca_style_collector_behavior.test.js`.

Expected: FAIL because group helpers and controls are absent.

- [ ] **Step 3: Render group summaries and safe tag chips**

Update cards to show `style_group_count` and `image_count`. In the dialog, render one section per `style_groups` entry using `createElement` and `textContent`. Render group members, common chips, per-image differences, character prompts with optional positions, and a collapsed original-prompt section.

```javascript
function appendTagList(parent, tags, className) {
  const list = document.createElement("div");
  list.className = className;
  for (const value of tags || []) {
    const chip = document.createElement("span");
    chip.className = "arca-prompt-tag";
    chip.textContent = value;
    list.append(chip);
  }
  parent.append(list);
}
```

Each group owns three buttons (`베이스`, `네거티브`, `캐릭터`) with `aria-selected` and associated panels. Copy actions copy the original structured section, never reconstructed normalized tags.

- [ ] **Step 4: Update deletion feedback**

After DELETE, show `삭제했습니다. YYYY-MM-DD은 다음 수집 때 다시 검색됩니다.` when `recollect_date` is present; otherwise show a concise deletion-only message.

- [ ] **Step 5: Style groups and run frontend tests**

Add clear group borders, a highlighted common-tag area, muted per-image differences, a responsive thumbnail strip, and horizontally scrollable prompt tabs on narrow screens.

Run `python -m unittest artist_rater.tests.test_arca_style_frontend_contract`, then run `node artist_rater/tests/arca_style_collector_behavior.test.js`.

Expected: both PASS.

- [ ] **Step 6: Commit grouped prompt UI**

```powershell
git add artist_rater/templates/index.html artist_rater/static/arca_style_collector.js artist_rater/static/style.css artist_rater/tests/test_arca_style_frontend_contract.py artist_rater/tests/arca_style_collector_behavior.test.js
git commit -m "feat: display grouped Arca prompts"
```

### Task 9: Full verification and browser acceptance

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run syntax checks**

Run: `python -m py_compile artist_rater/app.py artist_rater/arca_style_collector.py`

Expected: exit code 0.

- [ ] **Step 2: Run JavaScript behavior tests**

Run these separately:

```powershell
node artist_rater/tests/arca_style_collector_behavior.test.js
node artist_rater/tests/style_maker_behavior.test.js
node artist_rater/tests/app_behavior.test.js
```

Expected: all scripts exit 0 and print their passing summaries.

- [ ] **Step 3: Run the full Python suite**

Run: `python -m unittest discover -s artist_rater/tests -p "test_*.py"`

Expected: all tests PASS with no errors or failures.

- [ ] **Step 4: Check patch hygiene**

Run: `git diff --check`

Expected: no output.

- [ ] **Step 5: Verify the user flow in the in-app browser**

Start `artist_rater/run.bat`, open the configured local URL, and verify:

1. A month-long collection returns immediately and displays a changing stage and counters.
2. ETA starts at `계산 중` and becomes a duration after enough posts.
3. Archive list/detail/copy/delete actions remain usable during collection.
4. A multi-style post shows multiple groups, common base tags, per-image differences, negative tags, and character prompts.
5. Generic PDF/Celsys PNG metadata does not appear as a NovelAI prompt.
6. Deleting an item reports its recollection date; the coverage hint marks that date as needing collection.
7. Recollecting the overlapping range restores the deleted item without duplicating existing neighbors.

- [ ] **Step 6: Commit any verification-only fixes**

If verification required code changes, rerun the affected focused test and the full suite, then commit only those fixes:

```powershell
git add artist_rater
git commit -m "fix: complete Arca grouping verification"
```
