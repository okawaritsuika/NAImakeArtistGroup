# Arca Prompt Visual Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the collected-style prompt dialog one consistent visual system without changing its data or behavior.

**Architecture:** Keep the existing safe DOM rendering and grouping model. Add semantic modifier classes in `arca_style_collector.js`, then style groups, tabs, tag types, detail editing, and actions through the existing archive CSS block.

**Tech Stack:** Vanilla JavaScript, CSS, Python contract tests, Node test runner.

---

### Task 1: Unify the archive prompt dialog

**Files:**
- Modify: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/static/style.css`
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/tests/test_arca_style_frontend_contract.py`
- Modify: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] **Step 1: Write failing visual contract tests**

Require semantic classes for the shared card surface, prompt-type tabs, common/difference areas, secondary editing section, and aligned actions. Extend the Node helper test to assert the selected prompt kind maps to a stable modifier class.

```javascript
assert.equal(promptKindClass("base"), "is-base");
assert.equal(promptKindClass("negative"), "is-negative");
assert.equal(promptKindClass("character"), "is-character");
```

- [ ] **Step 2: Run tests and verify expected failure**

Run `python -m unittest tests.test_arca_style_frontend_contract`, then `node tests/arca_style_collector_behavior.test.js` from `artist_rater`.

Expected: FAIL because the modifier helper and unified classes do not exist.

- [ ] **Step 3: Add minimal semantic classes**

Add `promptKindClass(kind)` and apply its result to tab buttons and panels. Add `arca-common-block`, `arca-difference-block`, `arca-detail-edit`, and `arca-dialog-actions` without changing text insertion or click behavior.

```javascript
function promptKindClass(kind) {
  return `is-${kind}`;
}
```

- [ ] **Step 4: Apply one visual system**

Use a single surface color, `1px` border, `10px` radius, and 8/12/16px spacing scale. Use restrained blue/red/violet modifiers for base/negative/character, quieter image-difference rows, consistent textarea focus states, and equal-height close/delete/save buttons.

- [ ] **Step 5: Verify focused and full suites**

Run:

```powershell
python -m unittest tests.test_arca_style_frontend_contract
node tests/arca_style_collector_behavior.test.js
python -m unittest discover -s tests -p "test_*.py"
node tests/style_maker_behavior.test.js
node tests/app_behavior.test.js
git diff --check
```

Expected: all tests pass and `git diff --check` prints no errors.
