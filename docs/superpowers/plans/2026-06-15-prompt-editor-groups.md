# Prompt Editor Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the style-generation workspace and add Canvas-inspired draggable prompt tokens with named ON/OFF groups persisted in the existing prompt draft snapshot.

**Architecture:** Keep prompt/group behavior in `style_maker.js` as small pure normalization and filtering helpers plus DOM renderers. The existing textareas remain the canonical editable text inputs, while token chips are derived views and group entries store normalized token references by prompt field and character ID. Generation builds effective prompts by filtering tokens referenced by disabled groups.

**Tech Stack:** Flask templates, plain JavaScript, CSS Grid, Node `assert` tests, Python frontend contract tests.

---

### Task 1: Prompt Group Data Model

**Files:**
- Modify: `artist_rater/tests/style_maker_behavior.test.js`
- Modify: `artist_rater/static/style_maker.js`

- [ ] Add failing tests for comma token parsing, legacy localStorage migration, duplicate group-reference prevention, stale reference cleanup, and disabled-group filtering.
- [ ] Run `node artist_rater/tests/style_maker_behavior.test.js` and confirm failures are caused by missing prompt-group helpers.
- [ ] Add pure helpers for token normalization, stored character IDs/groups, group-item normalization, stale cleanup, and effective prompt filtering.
- [ ] Re-run the JS behavior test and confirm it passes.

### Task 2: Token Editors And Drag Groups

**Files:**
- Modify: `artist_rater/tests/test_style_frontend_contract.py`
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/style_maker.js`

- [ ] Add failing frontend-contract assertions for prompt editor containers, group controls, and drop zones.
- [ ] Run `python -m unittest artist_rater.tests.test_style_frontend_contract` and confirm the new assertions fail.
- [ ] Replace the prompt field markup with base/negative token editor containers, retain textareas as editable sources, and add the named group list/add button.
- [ ] Render draggable chips from every prompt textarea, support drag payloads and group drops, and implement rename, expand, toggle, reference removal, and deletion.
- [ ] Save the extended prompt snapshot after every prompt/group mutation and use effective filtered prompts in generation requests.
- [ ] Re-run focused JS and frontend-contract tests.

### Task 3: Wide Responsive Layout

**Files:**
- Modify: `artist_rater/static/style.css`

- [ ] Add a failing frontend-contract assertion for the prompt workspace class used by the wider layout.
- [ ] Widen the right grid track, remove horizontal overflow from prompt controls, add responsive two-column prompt layout, and style chips/groups/drop states.
- [ ] Confirm the frontend-contract test passes.

### Task 4: Verification

**Files:**
- Verify all modified files.

- [ ] Run `node artist_rater/tests/style_maker_behavior.test.js`.
- [ ] Run `node artist_rater/tests/app_behavior.test.js`.
- [ ] Run `python -m unittest discover -s artist_rater/tests -p "test_*.py"`.
- [ ] Run JavaScript and Python syntax checks plus `git diff --check`.
- [ ] Start the app on its configured port and use the in-app browser to verify desktop layout, token drag/drop, group ON/OFF filtering, reload persistence, and no horizontal panel scrolling.

### Task 5: Base And Negative Prompt Tabs

**Files:**
- Modify: `artist_rater/tests/test_style_frontend_contract.py`
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/style_maker.js`
- Modify: `artist_rater/static/style.css`

- [ ] Add failing contract assertions for a two-button prompt tablist, active base tab, and hidden negative editor panel.
- [ ] Run the focused frontend contract test and confirm the tab elements are missing.
- [ ] Wrap both prompt editors in tab panels and add accessible buttons with `aria-selected` and `aria-controls`.
- [ ] Add a small tab-switch helper that updates active classes, hidden state, and ARIA state without changing prompt values.
- [ ] Replace the two-column prompt grid with one full-width editor panel and style the tab strip.
- [ ] Run focused tests, the complete suite, and browser verification for both tab directions.
