# Art Style Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NovelAI-backed art-style generation, browser-driven continuous generation, automatic image/metadata storage, and art-style browsing to the existing artist rater.

**Architecture:** Keep the existing Flask entry point and rating UI intact, but put new domain logic in focused Python modules and the new frontend behavior in `style_maker.js`. Flask owns validation, NovelAI calls, style identity, file persistence, and SQLite writes; the browser owns the one-request-at-a-time repeat loop. A style is identified only by the ordered artist/weight array, while every generated image stores its own base, negative, character, and generation settings.

**Tech Stack:** Python 3, Flask, SQLite, `urllib.request`, standard-library ZIP/JSON/hash utilities, plain JavaScript, HTML, CSS, `unittest`.

---

## File Map

- Create `artist_rater/style_logic.py`: artist sampling, weight assignment, prompt formatting, and stable style hashing.
- Create `artist_rater/novelai.py`: NovelAI payload construction, subscription test, ZIP response extraction, and sanitized errors.
- Create `artist_rater/style_store.py`: JSON settings access, generated PNG persistence, and style/image database operations.
- Create `artist_rater/static/style_maker.js`: style editor state, graph interactions, generation controls, repeat loop, settings modal, and style manager rendering.
- Create `artist_rater/tests/test_style_logic.py`: deterministic domain tests for sampling, ranges, ordering, and hashing.
- Create `artist_rater/tests/test_style_api.py`: settings, generation, persistence, listing, and secret-leak tests.
- Create `artist_rater/tests/test_style_frontend_contract.py`: required UI and repeat-loop contract tests.
- Modify `artist_rater/app.py`: initialize new tables/directories and expose focused API routes that delegate to new modules.
- Modify `artist_rater/templates/index.html`: add two tabs, maker/manager views, settings modal, result viewer, and script include.
- Modify `artist_rater/static/style.css`: add compact workspace, graph, queue, gallery, modal, and responsive styles.
- Modify `artist_rater/.gitignore`: exclude local settings and generated outputs while retaining directories through `.gitkeep` if needed.

### Task 1: Style Identity and Persistence Schema

**Files:**
- Create: `artist_rater/style_logic.py`
- Create: `artist_rater/style_store.py`
- Create: `artist_rater/tests/test_style_logic.py`
- Modify: `artist_rater/app.py:37-82`
- Modify: `artist_rater/.gitignore`

- [ ] **Step 1: Write failing style identity tests**

```python
# artist_rater/tests/test_style_logic.py
import unittest

from style_logic import build_artist_prompt, style_hash


class StyleIdentityTest(unittest.TestCase):
    def test_prompt_preserves_artist_order(self):
        artists = [
            {"artist": "artist_b", "weight": 0.5, "score": 3},
            {"artist": "artist_a", "weight": 2.1, "score": 5},
        ]
        self.assertEqual(
            build_artist_prompt(artists),
            "0.5::artist_b::, 2.1::artist_a::",
        )

    def test_hash_changes_when_order_or_weight_changes(self):
        original = [
            {"artist": "artist_a", "weight": 1.0},
            {"artist": "artist_b", "weight": 1.5},
        ]
        reversed_order = list(reversed(original))
        changed_weight = [original[0], {"artist": "artist_b", "weight": 1.6}]
        self.assertNotEqual(style_hash(original), style_hash(reversed_order))
        self.assertNotEqual(style_hash(original), style_hash(changed_weight))

    def test_hash_ignores_image_prompts_by_signature(self):
        artists = [{"artist": "artist_a", "weight": 1.25}]
        self.assertEqual(style_hash(artists), style_hash(artists))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and confirm module import failure**

Run: `cd artist_rater; python -m unittest tests.test_style_logic -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'style_logic'`.

- [ ] **Step 3: Implement normalization, prompt formatting, and hashing**

```python
# artist_rater/style_logic.py
import hashlib
import json


def normalize_style_artists(artists):
    normalized = []
    for item in artists or []:
        artist = str(item.get("artist") or "").strip()
        if not artist:
            raise ValueError("작가 태그가 비어 있습니다.")
        weight = round(float(item.get("weight")), 2)
        if weight <= 0:
            raise ValueError("가중치는 0보다 커야 합니다.")
        normalized.append({
            "artist": artist,
            "weight": weight,
            "score": int(item.get("score") or 0),
        })
    if not normalized:
        raise ValueError("작가를 한 명 이상 선택하세요.")
    if len({item["artist"] for item in normalized}) != len(normalized):
        raise ValueError("같은 작가를 중복해서 사용할 수 없습니다.")
    return normalized


def format_weight(value):
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def build_artist_prompt(artists):
    return ", ".join(
        f'{format_weight(item["weight"])}::{item["artist"]}::'
        for item in normalize_style_artists(artists)
    )


def style_hash(artists):
    identity = [
        {"artist": item["artist"], "weight": item["weight"]}
        for item in normalize_style_artists(artists)
    ]
    canonical = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Add persistence tables and directory helpers**

Add these constants and `init_db()` table creations in `app.py`, delegating store operations to `style_store.py`:

```python
GENERATED_DIR = DATA_DIR / "generated"
SETTINGS_JSON_PATH = DATA_DIR / "settings.json"

# init_db()
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
conn.execute("""
    CREATE TABLE IF NOT EXISTS art_styles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        style_hash TEXT NOT NULL UNIQUE,
        artists_json TEXT NOT NULL,
        artist_prompt TEXT NOT NULL,
        representative_image_path TEXT DEFAULT '',
        image_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS generated_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id TEXT NOT NULL UNIQUE,
        style_id INTEGER NOT NULL,
        image_path TEXT NOT NULL,
        base_prompt TEXT DEFAULT '',
        negative_prompt TEXT DEFAULT '',
        character_prompts_json TEXT DEFAULT '[]',
        combined_prompt TEXT NOT NULL,
        artist_prompt TEXT NOT NULL,
        artists_json TEXT NOT NULL,
        seed INTEGER NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        sampler TEXT NOT NULL,
        steps INTEGER NOT NULL,
        scale REAL NOT NULL,
        cfg_rescale REAL NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(style_id) REFERENCES art_styles(id)
    )
""")
```

Create `style_store.py` with `connect_db(db_path)`, `save_generated_result(...)`, `list_styles(...)`, `get_style_detail(...)`, and `generated_file_path(...)`. Use a transaction for style upsert and image insert, write PNG to a temporary sibling file first, then `Path.replace()` it after validation; delete the temporary file on exceptions.

- [ ] **Step 5: Exclude local secrets and generated files**

```gitignore
# artist_rater/.gitignore
data/settings.json
data/generated/
data/artist_rater.sqlite
data/thumbnails/
server.err.log
server.out.log
__pycache__/
```

- [ ] **Step 6: Run style tests and the existing suite**

Run: `cd artist_rater; python -m unittest tests.test_style_logic tests.test_candidate_flow tests.test_frontend_contract -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit the schema and identity layer**

```powershell
git add artist_rater/app.py artist_rater/style_logic.py artist_rater/style_store.py artist_rater/tests/test_style_logic.py artist_rater/.gitignore
git commit -m "feat: add art style identity and storage schema"
```

### Task 2: Artist Selection and Weight Assignment Engine

**Files:**
- Modify: `artist_rater/style_logic.py`
- Modify: `artist_rater/tests/test_style_logic.py`
- Modify: `artist_rater/app.py`

- [ ] **Step 1: Add failing tests for unique selection and all three modes**

```python
from unittest.mock import patch

from style_logic import assign_weights, select_artists


class WeightEngineTest(unittest.TestCase):
    def setUp(self):
        self.pool = [
            {"artist": f"artist_{index}", "score": score}
            for index, score in enumerate([1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 5, 4], start=1)
        ]

    def test_selection_has_no_duplicate_artist(self):
        selected = select_artists(self.pool, 8, [1, 2, 3, 4, 5], rng_seed=7)
        self.assertEqual(len(selected), 8)
        self.assertEqual(len({item["artist"] for item in selected}), 8)

    def test_balanced_mode_caps_high_tier_for_twelve(self):
        weighted = assign_weights(self.pool, "balanced", 0.1, 2.3, True, [], rng_seed=9)
        self.assertLessEqual(sum(item["weight"] >= 1.5 for item in weighted), 3)
        self.assertEqual(sum(1.0 <= item["weight"] < 1.5 for item in weighted), 4)
        self.assertEqual(sum(item["weight"] < 1.0 for item in weighted), 5)

    def test_custom_mode_rejects_insufficient_capacity(self):
        with self.assertRaisesRegex(ValueError, "수용 인원"):
            assign_weights(
                self.pool[:4], "custom", 0.1, 2.3, False,
                [{"min": 0.1, "max": 0.9, "max_people": 3}], rng_seed=1,
            )

    def test_empty_custom_ranges_fall_back_to_full_random(self):
        weighted = assign_weights(self.pool[:3], "custom", 0.1, 2.3, False, [], rng_seed=2)
        self.assertEqual(len(weighted), 3)
        self.assertTrue(all(0.1 <= item["weight"] <= 2.3 for item in weighted))
```

- [ ] **Step 2: Run the focused tests and confirm missing function failures**

Run: `cd artist_rater; python -m unittest tests.test_style_logic.WeightEngineTest -v`

Expected: FAIL because `assign_weights` and `select_artists` are not defined.

- [ ] **Step 3: Implement deterministic weighted-without-replacement selection**

Use `random.Random(rng_seed)` and this score chance map:

```python
SCORE_SELECTION_WEIGHT = {1: 0.08, 2: 0.2, 3: 0.55, 4: 1.0, 5: 1.6}


def select_artists(pool, count, allowed_scores, rng_seed=None):
    rng = random.Random(rng_seed)
    remaining = [
        {"artist": str(item["artist"]), "score": int(item["score"])}
        for item in pool
        if int(item.get("score") or 0) in set(allowed_scores)
    ]
    if count < 1 or count > len(remaining):
        raise ValueError("선택 가능한 작가 수를 확인하세요.")
    selected = []
    while len(selected) < count:
        weights = [SCORE_SELECTION_WEIGHT[item["score"]] for item in remaining]
        chosen = rng.choices(remaining, weights=weights, k=1)[0]
        selected.append(chosen)
        remaining.remove(chosen)
    rng.shuffle(selected)
    return selected
```

- [ ] **Step 4: Implement full random, balanced, and custom range assignment**

Use two decimals and preserve input order. For score-priority tier assignment, compute `score + rng.random() * 4`; this keeps 1-2 unlikely but allows rare promotion. Balanced counts use `round(count * 0.25)` for high capped at `count // 4`, `round(count * 0.33)` for middle, and the remainder for low. Custom ranges are filled in user order up to `max_people`, then artist assignments are shuffled.

```python
def random_weight(rng, low, high):
    return round(rng.uniform(float(low), float(high)), 2)


def assign_weights(artists, mode, minimum, maximum, prefer_high_scores, ranges, rng_seed=None):
    rng = random.Random(rng_seed)
    items = [dict(item) for item in artists]
    minimum, maximum = float(minimum), float(maximum)
    if minimum <= 0 or maximum < minimum:
        raise ValueError("가중치 범위를 확인하세요.")
    if mode == "random" or (mode == "custom" and not ranges):
        return [{**item, "weight": random_weight(rng, minimum, maximum)} for item in items]
    tiers = build_balanced_tiers(len(items), minimum, maximum) if mode == "balanced" else validate_custom_ranges(ranges, len(items))
    ranked = sorted(items, key=lambda item: item.get("score", 0) + rng.random() * 4, reverse=True) if prefer_high_scores else rng.sample(items, len(items))
    assigned = assign_items_to_tiers(ranked, tiers, rng)
    by_artist = {item["artist"]: item["weight"] for item in assigned}
    return [{**item, "weight": by_artist[item["artist"]]} for item in items]
```

- [ ] **Step 5: Add `POST /api/style-maker/artists`**

Query rated artists by selected scores, call `select_artists`, then `assign_weights`, and return ordered items plus `artist_prompt` and `style_hash`. The endpoint accepts `count`, `scores`, `weight_mode`, `min_weight`, `max_weight`, `prefer_high_scores`, and `ranges`.

- [ ] **Step 6: Run domain and endpoint tests**

Run: `cd artist_rater; python -m unittest tests.test_style_logic -v`

Expected: all style logic tests PASS.

- [ ] **Step 7: Commit the selection engine**

```powershell
git add artist_rater/style_logic.py artist_rater/app.py artist_rater/tests/test_style_logic.py
git commit -m "feat: add weighted artist style generation"
```

### Task 3: JSON App Key Settings and Connection Test

**Files:**
- Create: `artist_rater/novelai.py`
- Create: `artist_rater/tests/test_style_api.py`
- Modify: `artist_rater/style_store.py`
- Modify: `artist_rater/app.py`

- [ ] **Step 1: Write failing settings API tests**

```python
# artist_rater/tests/test_style_api.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class StyleApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        app.DATA_DIR = self.tmp
        app.THUMBNAIL_DIR = self.tmp / "thumbnails"
        app.GENERATED_DIR = self.tmp / "generated"
        app.SETTINGS_JSON_PATH = self.tmp / "settings.json"
        app.DB_PATH = self.tmp / "artist_rater.sqlite"
        app.init_db()
        self.client = app.app.test_client()

    def test_settings_never_returns_saved_key(self):
        response = self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        self.assertEqual(response.status_code, 200)
        data = self.client.get("/api/settings/novelai").get_json()
        self.assertEqual(data, {"configured": True})
        self.assertNotIn("secret-key", response.get_data(as_text=True))

    @patch("app.test_novelai_subscription", return_value={"anlas": 1234})
    def test_connection_uses_server_saved_key(self, test_subscription):
        self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        response = self.client.post("/api/settings/novelai/test")
        self.assertEqual(response.get_json()["anlas"], 1234)
        test_subscription.assert_called_once_with("secret-key")

    def test_delete_removes_key_file(self):
        self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        self.client.delete("/api/settings/novelai")
        self.assertFalse(app.SETTINGS_JSON_PATH.exists())
```

- [ ] **Step 2: Run settings tests and confirm route failures**

Run: `cd artist_rater; python -m unittest tests.test_style_api.StyleApiTest.test_settings_never_returns_saved_key -v`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement atomic JSON setting access**

```python
# style_store.py
def load_app_key(settings_path):
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    return str(data.get("novelai_app_key") or "").strip()


def save_app_key(settings_path, app_key):
    value = str(app_key or "").strip()
    if not value:
        raise ValueError("App Key를 입력하세요.")
    path = Path(settings_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"novelai_app_key": value}, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def delete_app_key(settings_path):
    Path(settings_path).unlink(missing_ok=True)
```

- [ ] **Step 4: Implement NovelAI subscription test**

```python
# novelai.py
def test_novelai_subscription(app_key, opener=urllib.request.urlopen):
    request = urllib.request.Request("https://api.novelai.net/user/subscription", method="GET")
    request.add_header("Authorization", f"Bearer {app_key}")
    request.add_header("User-Agent", USER_AGENT)
    with opener(request, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    steps = data.get("trainingStepsLeft") or {}
    return {"anlas": int(steps.get("fixedTrainingStepsLeft", 0)) + int(steps.get("purchasedTrainingSteps", 0))}
```

- [ ] **Step 5: Add four settings routes**

Add `GET`, `PUT`, `DELETE /api/settings/novelai` and `POST /api/settings/novelai/test`. Return only `{configured: bool}` on reads and writes. Translate HTTP 401/403 into `NovelAI App Key 인증에 실패했습니다.` and never include the key in logs or responses.

- [ ] **Step 6: Run settings and regression tests**

Run: `cd artist_rater; python -m unittest tests.test_style_api tests.test_candidate_flow tests.test_frontend_contract -v`

Expected: all tests PASS.

- [ ] **Step 7: Commit key settings**

```powershell
git add artist_rater/novelai.py artist_rater/style_store.py artist_rater/app.py artist_rater/tests/test_style_api.py
git commit -m "feat: add local NovelAI key settings"
```

### Task 4: NovelAI Generation and Automatic Storage API

**Files:**
- Modify: `artist_rater/novelai.py`
- Modify: `artist_rater/style_store.py`
- Modify: `artist_rater/app.py`
- Modify: `artist_rater/tests/test_style_api.py`

- [ ] **Step 1: Write failing payload and persistence tests**

```python
import io
import zipfile


def png_zip(payload=b"fake-png"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("image_0.png", payload)
    return output.getvalue()


class GenerationApiTest(StyleApiTest):
    def request_payload(self, request_id="req-1"):
        return {
            "request_id": request_id,
            "artists": [
                {"artist": "artist_b", "weight": 0.5, "score": 3},
                {"artist": "artist_a", "weight": 2.1, "score": 5},
            ],
            "base_prompt": "1girl, masterpiece",
            "negative_prompt": "lowres",
            "character_prompts": ["blue hair", "red eyes"],
            "width": 832,
            "height": 1216,
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "scale": 5.0,
            "cfg_rescale": 0.4,
        }

    @patch("app.generate_novelai_png", return_value=(b"fake-png", 123456))
    def test_generation_saves_image_and_metadata(self, generate):
        self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        response = self.client.post("/api/style-maker/generate", json=self.request_payload())
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["seed"], 123456)
        self.assertTrue((self.tmp / data["image_path"]).exists())
        detail = self.client.get(f'/api/art-styles/{data["style_id"]}').get_json()
        self.assertEqual(detail["artists"][0]["artist"], "artist_b")
        self.assertEqual(detail["images"][0]["negative_prompt"], "lowres")
        self.assertNotIn("secret-key", response.get_data(as_text=True))

    @patch("app.generate_novelai_png", return_value=(b"fake-png", 123456))
    def test_duplicate_request_id_is_idempotent(self, generate):
        self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        first = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        second = self.client.post("/api/style-maker/generate", json=self.request_payload()).get_json()
        self.assertEqual(first["image_id"], second["image_id"])
        self.assertEqual(generate.call_count, 1)
```

- [ ] **Step 2: Run the generation test and verify HTTP 404**

Run: `cd artist_rater; python -m unittest tests.test_style_api.GenerationApiTest.test_generation_saves_image_and_metadata -v`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement strict request validation and prompt combination**

In `novelai.py`, validate width/height are positive multiples of 64, steps are 1-50, scale is 0-10, cfg_rescale is 0-1, and character prompts are a list of non-empty strings. Combine prompts without dangling commas:

```python
def combine_base_prompt(base_prompt, artist_prompt):
    return ", ".join(part for part in [str(base_prompt).strip(), str(artist_prompt).strip()] if part)
```

- [ ] **Step 4: Build the V4.5 Full payload and extract the PNG**

```python
def build_generation_payload(data, artist_prompt, seed):
    combined = combine_base_prompt(data.get("base_prompt"), artist_prompt)
    character_prompts = [str(value).strip() for value in data.get("character_prompts", []) if str(value).strip()]
    char_captions = [
        {"char_caption": prompt, "centers": [{"x": 0.5, "y": 0.5}]}
        for prompt in character_prompts
    ]
    negative = str(data.get("negative_prompt") or "").strip()
    return {
        "input": combined,
        "model": "nai-diffusion-4-5-full",
        "action": "generate",
        "parameters": {
            "width": int(data["width"]), "height": int(data["height"]), "n_samples": 1,
            "seed": seed, "extra_noise_seed": seed,
            "sampler": data.get("sampler") or "k_euler_ancestral",
            "steps": int(data.get("steps") or 28), "scale": float(data.get("scale") or 5.0),
            "negative_prompt": negative, "cfg_rescale": float(data.get("cfg_rescale") or 0.4),
            "noise_schedule": "native", "params_version": 3, "legacy": False,
            "legacy_v3_extend": False, "add_original_image": True, "prefer_brownian": True,
            "use_coords": False,
            "v4_negative_prompt": {"caption": {"base_caption": negative, "char_captions": []}, "legacy_uc": False},
            "v4_prompt": {"caption": {"base_caption": combined, "char_captions": char_captions}, "use_coords": False, "use_order": True},
        },
    }
```

`generate_novelai_png` chooses a random seed in `1..4294967295`, POSTs JSON with Bearer authentication, opens the ZIP response, and returns the first `.png` bytes plus the actual seed. Raise a sanitized `NovelAIError(status_code, message)` for HTTP errors.

- [ ] **Step 5: Add idempotent `POST /api/style-maker/generate`**

Before calling NovelAI, query `generated_images.request_id`; if found, return the existing response. Otherwise load the server-side key, normalize artists, build prompt/hash, generate PNG, and call `save_generated_result`. The JSON response contains `style_id`, `image_id`, `image_url`, relative `image_path`, `artist_prompt`, and `seed`.

- [ ] **Step 6: Serve stored generated images and list style data**

Add:

```python
@app.route("/generated/<path:filename>")
def generated(filename):
    return send_from_directory(GENERATED_DIR, filename)

@app.route("/api/art-styles")
def api_art_styles(): ...

@app.route("/api/art-styles/<int:style_id>")
def api_art_style_detail(style_id): ...
```

Return 404 for unknown styles. Image URLs use `/generated/...`; filesystem paths remain relative to `DATA_DIR` in API results.

- [ ] **Step 7: Run API tests and full backend suite**

Run: `cd artist_rater; python -m unittest tests.test_style_api tests.test_style_logic tests.test_candidate_flow -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit generation and storage**

```powershell
git add artist_rater/novelai.py artist_rater/style_store.py artist_rater/app.py artist_rater/tests/test_style_api.py
git commit -m "feat: generate and store NovelAI style images"
```

### Task 5: Art Style Maker Workspace and Weight Graph

**Files:**
- Modify: `artist_rater/templates/index.html`
- Create: `artist_rater/static/style_maker.js`
- Modify: `artist_rater/static/style.css`
- Create: `artist_rater/tests/test_style_frontend_contract.py`

- [ ] **Step 1: Write failing maker UI contract tests**

```python
# artist_rater/tests/test_style_frontend_contract.py
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "style_maker.js")


class StyleFrontendContractTest(unittest.TestCase):
    def test_maker_controls_and_graph_exist(self):
        for marker in [
            'data-tab="style-maker"', 'id="styleArtistCount"', 'id="styleScoreButtons"',
            'id="weightMode"', 'id="weightGraph"', 'id="basePrompt"',
            'id="negativePrompt"', 'id="characterPromptList"', 'id="generateOne"',
        ]:
            self.assertIn(marker, HTML)

    def test_style_script_is_loaded(self):
        self.assertTrue(JS.exists())
        self.assertIn("style_maker.js", HTML)
```

- [ ] **Step 2: Run the contract tests and confirm failure**

Run: `cd artist_rater; python -m unittest tests.test_style_frontend_contract -v`

Expected: FAIL because the tab and script do not exist.

- [ ] **Step 3: Add the maker tab and compact three-column workspace**

Add a `그림체 제작` tab with:

- Left collapsible settings panel: artist count, score 1-5 segmented buttons, all toggle, three weight modes, min/max inputs, score-priority checkbox, and custom range rows.
- Center editor: graph toolbar, ordered weight bars, exact numeric controls, add/delete/swap and sort buttons.
- Right generation panel: base/negative prompt tabs, repeatable character prompts, width/height, sampler, steps, scale, cfg rescale, generation mode and latest image.

Use semantic button IDs from the contract test, `type="button"`, and icon buttons with `title`/`aria-label` for reorder, delete, add, pause, stop, and viewer navigation.

- [ ] **Step 4: Add maker state and API loading**

```javascript
// static/style_maker.js
const styleState = {
  artists: [],
  allowedScores: new Set([1, 2, 3, 4, 5]),
  customRanges: [],
  running: false,
  paused: false,
  stopRequested: false,
  completed: 0,
  targetCount: null,
  latestResult: null,
};

async function loadStyleArtists({ rerollArtists = true, rerollWeights = true } = {}) {
  const payload = readStyleOptions();
  if (!rerollArtists) payload.artists = styleState.artists.map(({ artist, score }) => ({ artist, score }));
  const data = await apiFetch("/api/style-maker/artists", {
    method: "POST",
    body: JSON.stringify({ ...payload, reroll_artists: rerollArtists, reroll_weights: rerollWeights }),
  });
  styleState.artists = data.artists;
  renderWeightGraph();
}
```

Make the backend endpoint accept an optional `artists` array for weight-only rerolls, so the browser does not need to reproduce Python weighting rules.

- [ ] **Step 5: Implement graph editing without external dependencies**

Render each artist as a fixed-width column with a vertical range input, number input, label, drag handle, and delete button. HTML5 drag events reorder `styleState.artists`; input events clamp weights to min/max and update the prompt preview. `sortStyleArtists(direction)`, `swapStyleArtists(a, b)`, `addStyleArtist()`, and `removeStyleArtist(index)` mutate state then rerender.

- [ ] **Step 6: Add custom range controls and validation**

`addWeightRange()` inserts `{min: 0.1, max: 0.9, max_people: 1}`. Each row has three number inputs and a trash icon. Before reroll or generation, show an inline error when ranges overlap incorrectly, min exceeds max, or total capacity is below artist count.

- [ ] **Step 7: Style the maker workspace**

Add stable grid tracks such as `grid-template-columns: minmax(220px, 300px) minmax(420px, 1fr) minmax(300px, 380px)`, internal `overflow: auto`, graph bars with constrained heights, and a single-column mobile layout. Keep radius at 8px or less and avoid nested cards.

- [ ] **Step 8: Run frontend and regression tests**

Run: `cd artist_rater; python -m unittest tests.test_style_frontend_contract tests.test_frontend_contract -v`

Expected: all frontend contract tests PASS.

- [ ] **Step 9: Commit the maker workspace**

```powershell
git add artist_rater/templates/index.html artist_rater/static/style_maker.js artist_rater/static/style.css artist_rater/tests/test_style_frontend_contract.py artist_rater/app.py
git commit -m "feat: add interactive art style maker"
```

### Task 6: Settings Modal, Single Generation, and Browser Repeat Loop

**Files:**
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/style_maker.js`
- Modify: `artist_rater/static/style.css`
- Modify: `artist_rater/tests/test_style_frontend_contract.py`

- [ ] **Step 1: Add failing contracts for settings and repeat behavior**

```python
def test_settings_and_repeat_controls_exist(self):
    for marker in [
        'id="openSettings"', 'id="settingsModal"', 'id="novelAiAppKey"',
        'id="testNovelAiKey"', 'id="saveNovelAiKey"', 'id="deleteNovelAiKey"',
        'id="generationLimitMode"', 'id="generationCount"', 'id="styleChangeMode"',
        'id="startContinuous"', 'id="pauseContinuous"', 'id="stopContinuous"',
    ]:
        self.assertIn(marker, HTML)

def test_repeat_loop_is_serial_and_has_two_style_modes(self):
    source = JS.read_text(encoding="utf-8")
    self.assertIn("async function runContinuousGeneration()", source)
    self.assertIn('styleChangeMode === "weights"', source)
    self.assertIn('styleChangeMode === "artists_and_weights"', source)
    self.assertIn("await generateCurrentStyle()", source)
```

- [ ] **Step 2: Run the focused contracts and confirm failure**

Run: `cd artist_rater; python -m unittest tests.test_style_frontend_contract -v`

Expected: FAIL for missing settings and repeat controls.

- [ ] **Step 3: Add settings modal behavior**

On open, call `GET /api/settings/novelai` and show `저장된 키 있음` without populating the password input. Save uses `PUT`, test uses `POST /test`, and delete requires confirmation. Clear the input after successful save so the key does not remain in the DOM.

- [ ] **Step 4: Implement request construction and one-image generation**

```javascript
function buildGenerationRequest(requestId) {
  return {
    request_id: requestId,
    artists: styleState.artists.map(({ artist, weight, score }) => ({ artist, weight, score })),
    base_prompt: valueOf("basePrompt").trim(),
    negative_prompt: valueOf("negativePrompt").trim(),
    character_prompts: [...document.querySelectorAll("#characterPromptList textarea")]
      .map((node) => node.value.trim()).filter(Boolean),
    width: Number(valueOf("generationWidth", "832")),
    height: Number(valueOf("generationHeight", "1216")),
    sampler: valueOf("generationSampler", "k_euler_ancestral"),
    steps: Number(valueOf("generationSteps", "28")),
    scale: Number(valueOf("generationScale", "5")),
    cfg_rescale: Number(valueOf("generationCfgRescale", "0.4")),
  };
}

async function generateCurrentStyle() {
  validateGenerationForm();
  const requestId = crypto.randomUUID();
  const result = await apiFetch("/api/style-maker/generate", {
    method: "POST",
    body: JSON.stringify(buildGenerationRequest(requestId)),
  });
  styleState.latestResult = result;
  renderGenerationResult(result);
  return result;
}
```

- [ ] **Step 5: Implement the serial repeat loop**

```javascript
async function runContinuousGeneration() {
  styleState.running = true;
  styleState.paused = false;
  styleState.stopRequested = false;
  styleState.completed = 0;
  renderQueueState();
  try {
    while (!styleState.stopRequested && !reachedGenerationLimit()) {
      while (styleState.paused && !styleState.stopRequested) await wait(150);
      if (styleState.stopRequested) break;
      const styleChangeMode = valueOf("styleChangeMode", "weights");
      await loadStyleArtists({
        rerollArtists: styleChangeMode === "artists_and_weights",
        rerollWeights: true,
      });
      await generateCurrentStyle();
      styleState.completed += 1;
      renderQueueState();
    }
  } catch (error) {
    styleState.paused = true;
    showStatus($("generationStatus"), error.message, "error");
  } finally {
    styleState.running = false;
    renderQueueState();
  }
}
```

`reachedGenerationLimit()` returns false in unlimited mode and compares `completed >= targetCount` in count mode. Pause toggles only the next iteration; stop sets `stopRequested = true`. Disable conflicting editor controls while a request is active.

- [ ] **Step 6: Add result rendering and character prompt editors**

Show the latest image at a stable aspect ratio with style ID, seed, completed count, and generation status. Character prompt rows support add/delete and preserve existing values when other controls rerender.

- [ ] **Step 7: Run frontend and backend suites**

Run: `cd artist_rater; python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit generation controls**

```powershell
git add artist_rater/templates/index.html artist_rater/static/style_maker.js artist_rater/static/style.css artist_rater/tests/test_style_frontend_contract.py
git commit -m "feat: add continuous NovelAI generation controls"
```

### Task 7: Art Style Manager and Image Viewer

**Files:**
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/style_maker.js`
- Modify: `artist_rater/static/style.css`
- Modify: `artist_rater/style_store.py`
- Modify: `artist_rater/app.py`
- Modify: `artist_rater/tests/test_style_api.py`
- Modify: `artist_rater/tests/test_style_frontend_contract.py`

- [ ] **Step 1: Write failing manager API and UI tests**

```python
def test_style_manager_markup_exists(self):
    for marker in [
        'data-tab="style-manager"', 'id="styleManagerList"',
        'id="styleManagerDetail"', 'id="generatedImageModal"',
        'id="generatedImagePrev"', 'id="generatedImageNext"',
    ]:
        self.assertIn(marker, HTML)

def test_style_list_groups_images_by_style_hash(self):
    # Generate twice with identical ordered artists/weights but different base prompts.
    first = self.request_payload("req-a")
    second = self.request_payload("req-b")
    second["base_prompt"] = "2girls, outdoors"
    with patch("app.generate_novelai_png", side_effect=[(b"one", 1), (b"two", 2)]):
        self.client.put("/api/settings/novelai", json={"app_key": "secret-key"})
        self.client.post("/api/style-maker/generate", json=first)
        self.client.post("/api/style-maker/generate", json=second)
    styles = self.client.get("/api/art-styles").get_json()
    self.assertEqual(len(styles), 1)
    self.assertEqual(styles[0]["image_count"], 2)
```

- [ ] **Step 2: Run manager tests and confirm markup failure**

Run: `cd artist_rater; python -m unittest tests.test_style_frontend_contract tests.test_style_api.GenerationApiTest.test_style_list_groups_images_by_style_hash -v`

Expected: frontend test FAIL until manager markup exists; backend grouping test should guide any remaining store changes.

- [ ] **Step 3: Complete list/detail queries**

`list_styles` returns newest-updated first with `id`, `artists`, `artist_prompt`, `representative_image_url`, `image_count`, `created_at`, and `updated_at`. `get_style_detail` returns the same style fields plus newest-first images with all image prompts/settings and `image_url`. Parse JSON fields before returning them.

- [ ] **Step 4: Add manager view and rendering**

Add the `그림체 관리` tab. Render a compact, un-nested grid of style items showing representative image, artist count, image count, and recent timestamp. Selecting one opens an unframed detail pane with ordered artist/weight rows and its image thumbnails.

- [ ] **Step 5: Add generated image modal navigation**

Store the selected detail image array and index in `styleState`. Modal open displays full image, base/negative/character prompts, seed, dimensions, sampler, steps, scale, cfg rescale, and creation time. Arrow buttons and keyboard ArrowLeft/ArrowRight wrap around; Escape closes.

- [ ] **Step 6: Refresh manager after every successful generation**

If the manager tab is active, call `loadStyleManager()` after `generateCurrentStyle()`. Otherwise set a dirty flag and refresh on the next tab activation.

- [ ] **Step 7: Run all automated tests**

Run: `cd artist_rater; python -m unittest discover -s tests -v`

Expected: all tests PASS.

- [ ] **Step 8: Commit the manager**

```powershell
git add artist_rater/templates/index.html artist_rater/static/style_maker.js artist_rater/static/style.css artist_rater/style_store.py artist_rater/app.py artist_rater/tests/test_style_api.py artist_rater/tests/test_style_frontend_contract.py
git commit -m "feat: add generated art style manager"
```

### Task 8: End-to-End Verification and UI Polish

**Files:**
- Modify: `artist_rater/static/style.css` only for layout defects found in desktop/mobile verification
- Modify: `artist_rater/static/style_maker.js` only for interaction defects reproduced during verification
- Modify: `artist_rater/templates/index.html` only for missing accessibility labels or incorrect control wiring
- Modify: the specific existing test file that reproduces each discovered regression before applying its fix

- [ ] **Step 1: Run the full test suite from a clean process**

Run: `cd artist_rater; python -m unittest discover -s tests -v`

Expected: all tests PASS with no warnings or leaked temporary files.

- [ ] **Step 2: Start the Flask app**

Run: `cd artist_rater; python app.py`

Expected: Flask starts on the configured local URL and `GET /` returns 200. Keep this process running for browser verification.

- [ ] **Step 3: Verify desktop layout with the in-app browser**

Open the local URL at approximately 1440x900 and verify:

- All four tabs are reachable.
- The maker fits without body scrolling; its panels scroll internally.
- Closing the settings panel expands the graph/result workspace.
- Twelve graph bars fit and labels do not overlap.
- Custom ranges add/delete correctly.
- Prompt fields and generated image remain visible during repeat generation.
- Settings modal masks the key and never repopulates it.
- Manager images open and navigate in the modal.

- [ ] **Step 4: Verify mobile layout**

At approximately 390x844, verify the maker becomes one column, controls remain readable, graph has horizontal internal scrolling, and modal content fits without overlap.

- [ ] **Step 5: Verify API failure states without spending Anlas**

Use an empty or deliberately invalid key to confirm missing-key and authentication messages. Mock `generate_novelai_png` in automated tests for successful storage; do not make a paid generation call during routine verification unless the user explicitly provides and authorizes use of a valid key.

- [ ] **Step 6: Inspect local secret and output tracking**

Run: `git status --short --ignored`

Expected: `artist_rater/data/settings.json`, generated PNGs, SQLite, thumbnails, logs, and `__pycache__` are ignored; source and tests are not ignored.

- [ ] **Step 7: Commit final responsive fixes**

```powershell
git add artist_rater/templates/index.html artist_rater/static/style_maker.js artist_rater/static/style.css artist_rater/tests
git commit -m "fix: polish art style generation workflow"
```

- [ ] **Step 8: Record final verification evidence**

Run:

```powershell
cd artist_rater
python -m unittest discover -s tests -v
```

Expected: all tests PASS. Capture desktop and mobile screenshots through the in-app browser and report the local URL, test count, and any verification intentionally skipped because it would consume NovelAI credits.
