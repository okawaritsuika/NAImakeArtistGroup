# Arca Style Collection Management Design

## Goal

Add an isolated Arca Live style archive to the existing Danbooru Artist Rater / NovelAI style maker. The archive collects public NAI and R18 NAI style-sharing posts for a requested date range, avoids repeating completed searches, and lets the user inspect, edit, and delete collected style records.

## Scope and constraints

- Keep `art_styles`, `generated_images`, `/api/art-styles`, and `/generated/<path>` unchanged in behavior.
- Store archive posts, images, and search history in dedicated tables.
- Keep archive frontend behavior in `static/arca_style_collector.js`.
- Access only publicly available HTML and images. Do not bypass robots controls, authentication, captchas, or permissions.
- Bound network access by timeout, User-Agent, maximum pages, maximum posts, and maximum image bytes.
- Preserve all existing uncommitted prompt-editor work while adding this feature.

## Data model

`arca_style_items` stores one row per canonical `source_url`, including post identity, tab, title, author, timestamps, representative image, extraction status, editable prompt, editable negative prompt, extracted generation parameters, original metadata JSON, fallback body text, and memo.

`arca_style_images` stores downloaded image candidates. `(item_id, image_url)` is unique and rows are removed through `ON DELETE CASCADE` when their parent item is deleted.

`arca_collection_runs` records normalized search requests and their outcome. It contains the keyword, normalized tab set, requested start/end dates, page/post limits, status (`running`, `completed`, or `failed`), counters, and timestamps. Only completed runs count as searched coverage; failed or interrupted runs may be retried.

Search deduplication uses the normalized key `(keyword, tabs, max_pages, max_posts)`. Before collection, completed date intervals for that key are merged. A request fully covered by those intervals returns a successful `skipped_existing` result without making an external request. A partially covered request is split into uncovered date intervals and only those intervals are collected. Successful intervals are recorded independently so later overlapping requests can reuse them.

## Collection flow

1. Validate and normalize keyword, tabs, dates, page limit, and post limit.
2. Compare the requested dates with completed collection coverage.
3. Return immediately when the whole request is already covered; otherwise create a running record for each uncovered interval.
4. Discover NAI category parameters from the board HTML when possible, falling back to an unfiltered search whose post results are filtered by tab.
5. Fetch bounded result pages, extract canonical article links, and ignore duplicates within the run.
6. Fetch each article, validate its date and tab, then gather resilient image candidates from `img` source attributes, `source[srcset]`, and enclosing links.
7. Stream-download bounded image responses, persist files under `data/arca_style_images`, and extract NovelAI metadata from PNG text chunks.
8. Upsert the post by `source_url` and images by `(item_id, image_url)`. Prefer the first metadata-bearing image as representative; otherwise use the first downloaded image. Use body prompt fallback only when extracted prompt fields are empty.
9. Mark each interval completed only after its collection finishes. Mark errors as failed and retain enough status information for a retry.

Repeating a collection may update an existing post but never creates duplicate cards or image rows.

## API

- `POST /api/arca-styles/collect` validates the request, applies coverage deduplication, collects uncovered intervals, and returns counters plus skipped/covered interval information.
- `GET /api/arca-styles` lists compact cards with text, tab, metadata, and date filters.
- `GET /api/arca-styles/<id>` returns full post and image details.
- `PATCH /api/arca-styles/<id>` accepts only editable `prompt`, `negative_prompt`, and `memo` strings. Extracted raw metadata and source identity remain immutable through this endpoint.
- `DELETE /api/arca-styles/<id>` deletes the item and dependent image rows, then safely removes image files that are no longer referenced by another archive row.
- `GET /api/arca-styles/search-status` returns normalized completed coverage for the current collection form so the UI can explain whether a request will be skipped or partially searched.
- `GET /arca-style-images/<path>` serves files only from the archive image directory with traversal protection.

Malformed requests return 400, missing items return 404, and expected upstream collection failures return a safe 502 message. Unexpected failures are logged server-side and return a generic collection error.

## User interface

The new `공유 그림체 수집` tab uses a 320-pixel collection panel and responsive card list. The form shows a coverage hint as its inputs change. When the exact request is covered, the collection button reads `검색 완료 · 목록 보기` and loading the list requires no external request. Partial coverage states which date ranges remain.

Each card shows the representative image, title, tab, post date, extraction badge, prompt preview, and actions for source, prompt copy, UC copy, detail/edit, and delete. Detail/edit opens a focused dialog containing all downloaded images and editable prompt, UC, and memo fields. Saving updates the card immediately. Delete requires confirmation and removes the card after the server succeeds.

All post-derived text is assigned through DOM `textContent`; it is never interpolated into `innerHTML`.

## Error handling and file safety

- Collection controls are disabled while a request is active and always restored afterward.
- A failed collection displays a concise message and remains retryable because failed coverage is not treated as complete.
- PATCH validation rejects non-string or oversized editable fields.
- DELETE resolves every candidate file path beneath the archive image root before removal, ignores already-missing files, and does not remove files still referenced by another row.
- Database deletion is committed before best-effort orphan file cleanup; cleanup failures are logged without restoring a deleted record.

## Testing

Tests are written before production changes and cover:

- payload normalization and invalid bounds;
- interval merge/subtraction and fully/partially covered searches;
- resilient article/image parsing and PNG metadata extraction;
- post/image upserts without duplicate rows;
- prompt/UC/memo patch allowlisting;
- cascading item deletion and safe orphan-file cleanup;
- Flask route responses and legacy route contracts;
- frontend contracts and JavaScript behavior for status, editing, deletion, and safe DOM rendering.

Verification includes Python and JavaScript test suites, syntax compilation, `git diff --check`, and browser checks of all existing tabs plus collection, skip, edit, and delete flows.
