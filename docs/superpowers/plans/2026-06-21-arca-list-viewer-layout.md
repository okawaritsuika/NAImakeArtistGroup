# Arca List Scroll, Date Sort, and Image Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arca 목록을 화면 안에서 스크롤하고 게시글 날짜로 정렬하며 수정 화면에 선택 이미지 큰 미리보기를 추가한다.

**Architecture:** 정렬은 API가 `posted_at` 기준으로 수행하고 frontend select가 query를 전달한다. 목록 스크롤과 viewer layout은 기존 Arca 전용 CSS에 한정하며, 썸네일 선택 함수가 이미지 URL과 세 prompt를 한 번에 갱신한다.

**Tech Stack:** Python, SQLite, Flask, unittest, vanilla JavaScript/CSS

---

### Task 1: 게시글 날짜 정렬 API

**Files:**
- Modify: `artist_rater/arca_style_collector.py`
- Modify: `artist_rater/app.py`
- Test: `artist_rater/tests/test_arca_style_collector.py`
- Test: `artist_rater/tests/test_arca_style_api.py`

- [ ] **Step 1: 실패 테스트 작성**

날짜가 있는 세 항목과 없는 한 항목을 저장하고 `posted_desc`, `posted_asc` 결과를 검증한다. 날짜 없는 항목은 양쪽 모두 마지막이어야 한다. API에 잘못된 sort를 보내면 400을 기대한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_style_collector tests.test_arca_style_api -v`

Expected: sort가 무시되어 오래된순과 잘못된 값 테스트가 실패.

- [ ] **Step 3: 최소 구현**

`list_arca_styles`에서 sort를 `posted_desc|posted_asc`로 검증한다. SQL은 날짜 없음 여부를 먼저 정렬하고, 날짜 방향을 적용하며 id는 내림차순으로 고정한다. app의 허용 query key에 `sort`를 추가한다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_style_collector tests.test_arca_style_api -v`

Expected: 전체 PASS.

### Task 2: 정렬 UI와 목록 스크롤

**Files:**
- Modify: `artist_rater/templates/index.html`
- Modify: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/static/style.css`
- Test: `artist_rater/tests/test_arca_style_frontend_contract.py`
- Test: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] **Step 1: 실패 테스트 작성**

HTML에 `arcaStyleSort`를 요구하고 query helper가 기본 `posted_desc`와 선택한 `posted_asc`를 반환하도록 기대한다. CSS 계약은 desktop list의 `overflow-y: auto`, mobile의 `overflow: visible`을 요구한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_style_frontend_contract -v; node --test tests/arca_style_collector_behavior.test.js`

Expected: 새 select/helper/CSS가 없어 실패.

- [ ] **Step 3: 최소 구현**

필터에 최신순/오래된순 select를 추가하고 `loadArcaStyles` query에 sort를 포함한다. desktop view와 main에 min-height/overflow 제약을 주고 `.arca-style-list`를 남은 높이의 scroll container로 만든다. 900px 이하에서는 height와 overflow를 원래 page scroll로 되돌린다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_style_frontend_contract -v; node --test tests/arca_style_collector_behavior.test.js`

Expected: 전체 PASS.

### Task 3: 선택 이미지 큰 viewer

**Files:**
- Modify: `artist_rater/static/arca_style_collector.js`
- Modify: `artist_rater/static/style.css`
- Test: `artist_rater/tests/arca_style_collector_behavior.test.js`
- Test: `artist_rater/tests/test_arca_style_frontend_contract.py`

- [ ] **Step 1: 실패 테스트 작성**

`imagePromptFields` 결과에 `image_url`이 포함되는지 검증하고 frontend contract가 `arca-selected-image-preview` class를 요구하게 한다.

- [ ] **Step 2: RED 확인**

Run: `node --test tests/arca_style_collector_behavior.test.js; python -m unittest tests.test_arca_style_frontend_contract -v`

Expected: image URL과 preview class가 없어 실패.

- [ ] **Step 3: 최소 구현**

각 그룹 viewer body에 큰 `img`와 기존 prompt fields를 넣는다. `selectImage`는 큰 img src/alt와 textareas를 함께 갱신한다. CSS desktop은 이미지/필드 2열, mobile은 1열이며 이미지에는 `object-fit: contain`과 max-height를 적용한다.

- [ ] **Step 4: GREEN 확인**

Run: `node --test tests/arca_style_collector_behavior.test.js; python -m unittest tests.test_arca_style_frontend_contract -v`

Expected: 전체 PASS.

### Task 4: 전체 검증

- [ ] Run: `python -m unittest discover -s tests -v`
- [ ] Run: `Get-ChildItem tests -Filter *.test.js | ForEach-Object { node --test $_.FullName }`
- [ ] 서버 재시작 후 16개 목록 스크롤, 날짜 정렬, 썸네일 선택 preview 변경을 확인한다.
