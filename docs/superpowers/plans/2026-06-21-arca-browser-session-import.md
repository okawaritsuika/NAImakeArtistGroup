# Arca Browser Session Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일반 사용자가 버튼 한 번으로 Chrome 또는 Edge의 Arca Live 로그인 세션을 가져와 NAI와 🔞 NAI 게시글을 빠짐없이 별도 검색하게 한다.

**Architecture:** `browser-cookie3`가 읽은 `arca.live` 쿠키만 프로세스 메모리에 보관하고, R18 카테고리 링크가 실제 응답에 나타날 때만 연결을 인정한다. 수집기는 검증된 카테고리별 검색 URL을 각각 순회하며, 세션이 없는 R18 요청은 완료 이력을 만들기 전에 거절한다. API와 화면에는 브라우저명·연결 여부·안전한 오류만 노출한다.

**Tech Stack:** Python 3, Flask, requests, browser-cookie3 0.20.1, unittest, vanilla JavaScript/CSS

---

## File map

- `artist_rater/requirements.txt`: 브라우저 쿠키 읽기 의존성 고정.
- `artist_rater/arca_style_collector.py`: 메모리 세션, 쿠키 필터, 로그인 검증, 카테고리별 검색과 coverage 범위 관리.
- `artist_rater/app.py`: 세션 상태 조회와 가져오기 API.
- `artist_rater/templates/index.html`: 원클릭 가져오기 버튼과 상태 표시.
- `artist_rater/static/arca_style_collector.js`: 상태 조회·가져오기·R18 사전 안내.
- `artist_rater/static/style.css`: 기존 수집 패널에 맞춘 작은 상태 행.
- `artist_rater/tests/test_arca_style_collector.py`: 세션 및 검색 동작 단위 테스트.
- `artist_rater/tests/test_arca_style_api.py`: 쿠키 비노출 API 테스트.
- `artist_rater/tests/test_arca_style_frontend_contract.py`: 필수 UI 요소 계약 테스트.
- `artist_rater/tests/arca_style_collector_behavior.test.js`: 상태 문구와 요청 동작 테스트.

### Task 1: 메모리 전용 브라우저 세션

- [ ] **Step 1: 실패 테스트 작성**

`test_arca_style_collector.py`에 합성 `CookieJar`를 사용해 다음을 검증한다.

```python
def test_import_browser_session_tries_edge_after_chrome_and_filters_domains(self):
    result = import_arca_browser_session(
        loaders=[("Chrome", failing_loader), ("Edge", mixed_domain_loader)],
        validator=lambda session: {"NAI": {"category": "NAI"}, "R18_NAI": {"category": "NAI_R18"}},
    )
    self.assertEqual(result, {"connected": True, "browser": "Edge", "error": ""})
    self.assertEqual(sorted(cookie.domain for cookie in snapshot_imported_arca_cookies()), [".arca.live"])
```

만료·검증 실패 시 이전 쿠키가 지워지고 오류에 쿠키 값이 포함되지 않는 테스트도 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -v`

Expected: `import_arca_browser_session` 미정의로 실패.

- [ ] **Step 3: 최소 구현**

`arca_style_collector.py`에 lock으로 보호되는 메모리 `CookieJar`, `import_arca_browser_session`, `clear_arca_browser_session`, `get_arca_browser_session_status`, `_apply_imported_arca_cookies`를 추가한다. loader는 기본값으로 아래 순서를 사용한다.

```python
loaders = loaders or [
    ("Chrome", lambda: browser_cookie3.chrome(domain_name="arca.live")),
    ("Edge", lambda: browser_cookie3.edge(domain_name="arca.live")),
]
```

허용 도메인은 `arca.live`와 `.arca.live` suffix뿐이며 예외 문자열은 외부 응답에 전달하지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -v`

Expected: 세션 테스트 포함 전체 PASS.

- [ ] **Step 5: 의존성 추가**

`requirements.txt`에 `browser-cookie3==0.20.1`을 추가하고 `python -m pip install -r artist_rater/requirements.txt`가 성공하는지 확인한다.

### Task 2: NAI/R18 카테고리 분리와 잘못된 coverage 무효화

- [ ] **Step 1: 실패 테스트 작성**

보드 HTML의 `NAI`, `🔞 NAI` 앵커를 각각 `NAI`, `R18_NAI`로 파싱하고, 두 탭의 URL이 서로 다른 category query를 사용하며, 연결 없는 R18 수집은 실행 이력 생성 전에 `ArcaBrowserSessionRequired`를 발생시키는 테스트를 추가한다. `title-row-stealth-v4` 완료 이력이 새 요청을 덮지 않는 테스트도 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -v`

Expected: 카테고리 매핑/세션 예외/새 scope 기대값으로 실패.

- [ ] **Step 3: 최소 구현**

`SEARCH_SCOPE`를 `title-category-session-v5`로 변경한다. `discover_category_params`는 앵커 텍스트와 URL query를 함께 읽어 `{ "NAI": params, "R18_NAI": params }`를 반환한다. `build_search_urls`는 요청 탭별 URL을 만들고, `collect_arca_styles`는 검증된 세션과 카테고리를 준비한 다음에만 run을 생성하며 각 URL을 독립 순회한다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_collector -v`

Expected: 전체 PASS.

### Task 3: 안전한 로컬 API

- [ ] **Step 1: 실패 테스트 작성**

`test_arca_style_api.py`에 GET `/api/arca-styles/browser-session`과 POST `/api/arca-styles/browser-session/import` 테스트를 추가한다. 응답 키는 `connected`, `browser`, `error`만 허용하고 합성 쿠키 값이 JSON에 없는지 검증한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_api -v`

Expected: 두 route가 404로 실패.

- [ ] **Step 3: 최소 구현**

`app.py`에 상태 조회와 가져오기 route를 추가한다. 성공은 200, 가져오기 실패는 사용자 메시지를 담은 400으로 응답하며 collector의 안전한 상태 dict 외 정보는 직렬화하지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_api -v`

Expected: 전체 PASS.

### Task 4: 원클릭 UI

- [ ] **Step 1: 실패 테스트 작성**

프론트 계약 테스트에 `arcaBrowserSessionState`, `importArcaBrowserSession`을 요구하고 JS 테스트에 disconnected/Chrome/Edge/failure 문구와 POST 요청을 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_frontend_contract -v; node --test artist_rater/tests/arca_style_collector_behavior.test.js`

Expected: 새 DOM ID와 함수가 없어 실패.

- [ ] **Step 3: 최소 구현**

수집 패널에 `브라우저 로그인 가져오기` 버튼과 한 줄 상태를 추가한다. JS는 페이지 로드시 상태를 조회하고 버튼 클릭 시 POST 후 갱신하며, 쿠키나 상세 예외는 표시·저장하지 않는다. R18 체크 상태에서 미연결이면 해당 상태 행에 연결 필요를 알린다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest artist_rater.tests.test_arca_style_frontend_contract -v; node --test artist_rater/tests/arca_style_collector_behavior.test.js`

Expected: 전체 PASS.

### Task 5: 회귀 및 실제 로컬 검증

- [ ] **Step 1: 전체 자동 테스트**

Run: `python -m unittest discover -s artist_rater/tests -v`

Expected: 기존 skip 외 전체 PASS.

Run: `node --test artist_rater/tests/*.test.js`

Expected: 전체 PASS.

- [ ] **Step 2: 실제 가져오기 안전 검증**

로컬 서버를 재시작하고 POST `/api/arca-styles/browser-session/import`를 한 번 호출한다. 출력은 HTTP 상태와 `connected/browser/error`만 확인하며 CookieJar, request headers, cookie DB 경로는 출력하지 않는다.

- [ ] **Step 3: 브라우저 동작 검증**

화면에서 버튼과 연결 상태, R18 수집 시작 시 즉시 작업 상태로 전환되는지 확인한다. 실제 브라우저 암호화 정책 때문에 가져오기가 실패할 경우에도 UI가 멈추지 않고 재시도 가능한 안전한 오류를 표시해야 한다.

