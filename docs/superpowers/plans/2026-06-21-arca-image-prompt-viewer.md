# Arca Image Prompt Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace prompt tabs and tag chips with an image-selected three-textarea viewer and fix archive modal overflow.

**Architecture:** Keep group data unchanged. Add a pure selected-image projection helper, render one viewer per group with clickable thumbnails, and wrap existing modal content in a dedicated scroll body.

**Tech Stack:** Vanilla JavaScript, CSS, HTML, Node tests, Python contract tests.

---

### Task 1: Add image-selected prompt projection

**Files:**
- Modify: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] Add a failing test for `imagePromptFields(image)` returning base, negative, and joined character text.
- [ ] Run the Node test and confirm the helper is missing.
- [ ] Implement the helper and render clickable thumbnails with `aria-pressed` selection.
- [ ] Render three labeled read-only textareas and update their values on thumbnail click.
- [ ] Run the Node tests and confirm they pass.

### Task 2: Fix modal overflow and visual states

**Files:**
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/style.css`
- Modify: `artist_rater/tests/test_arca_style_frontend_contract.py`

- [ ] Add failing contract checks for `arca-dialog-scroll`, `arca-image-prompt-viewer`, and `arca-prompt-textarea`.
- [ ] Wrap all archive content below the header in `arca-dialog-scroll`.
- [ ] Make the dialog a bounded flex/grid container, set the body to `overflow-y:auto`, and style selected thumbnails and textarea rows.
- [ ] Run focused frontend tests, the full Python/JavaScript suites, syntax checks, and `git diff --check`.
