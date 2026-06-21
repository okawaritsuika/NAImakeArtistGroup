# Arca Direct URL Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-at-a-time direct Arca post collection with background progress and duplicate-safe upserts.

**Architecture:** Add URL normalization and a direct-job worker in `arca_style_collector.py`, expose one Flask endpoint, and reuse the existing job polling UI. Direct runs call `_save_article` without date-coverage records.

**Tech Stack:** Python, Flask, SQLite, requests, vanilla JavaScript, unittest, Node tests.

---

### Task 1: Direct URL collector

**Files:**
- Modify: `artist_rater/arca_style_collector.py`
- Modify: `artist_rater/tests/test_arca_style_collector.py`

- [ ] Add failing tests for valid canonicalization, invalid hosts/paths, successful article upsert, and failed job status.
- [ ] Implement `normalize_arca_article_url`, direct job creation, and a worker that fetches one article and calls `_save_article`.
- [ ] Update job counters at fetch, download, save, completion, and failure boundaries.
- [ ] Run collector tests.

### Task 2: API and interface

**Files:**
- Modify: `artist_rater/app.py`
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/static/style.css`
- Modify: `artist_rater/tests/test_arca_style_api.py`
- Modify: `artist_rater/tests/test_arca_style_frontend_contract.py`
- Modify: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] Add failing API tests for `POST /api/arca-styles/collect-url` returning a job ID and validation errors.
- [ ] Add a URL input, action button, pure payload helper, request handler, and existing-job polling reuse.
- [ ] Keep date collection controls independent while a direct URL job runs.
- [ ] Run focused tests, full Python/JavaScript suites, syntax checks, local HTTP checks, and `git diff --check`.
