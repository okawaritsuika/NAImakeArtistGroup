# Arca Login Window Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 브라우저 쿠키 자동 추출 실패 시 앱 전용 Chrome 로그인 창을 열고, 사용자가 직접 로그인하면 Arca R18 세션을 안전하게 연결한다.

**Architecture:** 기존 Chrome/Edge 자동 추출은 그대로 첫 단계로 유지한다. 실패하면 단일 worker thread가 Playwright persistent Chrome context를 열고, `arca.live` 쿠키만 requests 세션으로 변환해 R18 카테고리를 검증한 뒤 메모리에 연결한다. API는 안전한 상태만 반환하고 프론트는 `202` 응답 후 terminal state까지 polling한다.

**Tech Stack:** Python 3, Flask, requests, Playwright Python 1.60.0, unittest, vanilla JavaScript

---

## File map

- `artist_rater/arca_login_window.py`: Playwright context lifecycle, cookie 변환, timeout 및 안전한 상태 관리.
- `artist_rater/arca_style_collector.py`: 기존 메모리 쿠키 저장소에 검증된 로그인 창 쿠키를 연결하는 공개 함수.
- `artist_rater/app.py`: import API의 200/202 상태와 login worker 시작 연결.
- `artist_rater/static/arca_style_collector.js`: waiting 상태 polling과 terminal state 처리.
- `artist_rater/requirements.txt`: `playwright==1.60.0` 고정.
- `artist_rater/tests/test_arca_login_window.py`: 합성 context 기반 worker 단위 테스트.
- `artist_rater/tests/test_arca_style_api.py`: 202 및 안전한 응답 테스트.
- `artist_rater/tests/arca_style_collector_behavior.test.js`: 상태 문구 및 polling 판정 테스트.

### Task 1: 로그인 창 상태 관리자

**Files:**
- Create: `artist_rater/arca_login_window.py`
- Test: `artist_rater/tests/test_arca_login_window.py`

- [ ] **Step 1: 실패 테스트 작성**

합성 context factory와 clock을 주입해 한 worker만 시작되고 공개 상태가 다음 형태인지 검증한다.

```python
status = manager.start()
self.assertEqual(status["state"], "waiting")
self.assertFalse(status["connected"])
self.assertEqual(factory.calls, 1)
self.assertEqual(manager.start()["state"], "waiting")
self.assertEqual(factory.calls, 1)
```

합성 쿠키 중 `arca.live` 계열만 validator로 전달되는지, 성공 시 context가 닫히는지, 창 종료와 timeout이 각각 안전한 `failed` 상태가 되는지도 별도 테스트한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: `arca_login_window` 모듈이 없어 실패.

- [ ] **Step 3: 최소 구현**

`ArcaLoginWindowManager`는 lock, worker thread, 공개 상태 dict를 가진다. 기본 factory는 worker 내부에서 `sync_playwright()`를 시작하고 아래 context를 반환한다.

```python
playwright.chromium.launch_persistent_context(
    str(profile_dir),
    channel="chrome",
    headless=False,
)
```

worker는 `context.cookies(["https://arca.live"])` 결과를 `CookieJar`로 변환하고 주입된 validator를 호출한다. 5분 내 성공하면 connector를 호출하고 context를 닫는다. 예외 원문, 쿠키, 프로필 경로는 공개 상태에 넣지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: 전체 PASS.

### Task 2: 기존 메모리 세션과 연결

**Files:**
- Modify: `artist_rater/arca_style_collector.py`
- Test: `artist_rater/tests/test_arca_style_collector.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
status = connect_arca_cookie_jar(jar, "전용 Chrome", validator=fake_validator)
self.assertEqual(status, {"connected": True, "browser": "전용 Chrome", "error": ""})
self.assertEqual(len(snapshot_imported_arca_cookies()), 1)
```

validator가 R18 카테고리를 찾지 못하면 기존 메모리 쿠키가 지워지는 테스트도 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_style_collector.ArcaCollectorTest.test_connects_validated_login_window_cookie_jar -v`

Expected: `connect_arca_cookie_jar` 미정의로 실패.

- [ ] **Step 3: 최소 구현**

기존 domain filter와 메모리 lock을 재사용하는 `connect_arca_cookie_jar(cookie_jar, browser, validator=None)`를 추가한다. R18 검증 성공 후에만 `_ARCA_BROWSER_COOKIES`와 상태를 교체한다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_style_collector -v`

Expected: 전체 PASS.

### Task 3: 자동 추출에서 로그인 창 fallback API

**Files:**
- Modify: `artist_rater/app.py`
- Modify: `artist_rater/requirements.txt`
- Test: `artist_rater/tests/test_arca_style_api.py`

- [ ] **Step 1: 실패 테스트 작성**

자동 추출 성공은 기존 200을 유지하고, 실패 시 manager `start()` 결과를 202로 반환하며 상태 조회에 `state`와 `message`가 포함되는 테스트를 추가한다. 응답 전체에 합성 쿠키 값과 예외 원문이 없음을 검증한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_style_api -v`

Expected: 실패 응답이 400이라 새 기대값에서 실패.

- [ ] **Step 3: 최소 구현**

앱 전역 manager를 `ARCA_STYLE_IMAGE_DIR.parent / "arca_login_profile"`로 구성한다. import route는 자동 추출 결과가 disconnected이면 manager를 시작하고 202를 반환한다. status route는 연결 세션과 manager 상태를 병합하되 키를 `connected`, `browser`, `error`, `state`, `message`로 제한한다.

`requirements.txt`에는 다음을 추가한다.

```text
playwright==1.60.0
```

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_style_api -v`

Expected: 전체 PASS.

### Task 4: 로그인 대기 UI

**Files:**
- Modify: `artist_rater/static/arca_style_collector.js`
- Test: `artist_rater/tests/arca_style_collector_behavior.test.js`

- [ ] **Step 1: 실패 테스트 작성**

`arcaBrowserSessionText`가 opening/waiting/failed/connected 문구를 반환하고 `isArcaBrowserSessionPending`가 opening/waiting만 true로 판정하는 테스트를 추가한다.

```javascript
assert.equal(isArcaBrowserSessionPending({ state: "waiting" }), true);
assert.equal(isArcaBrowserSessionPending({ state: "connected" }), false);
```

- [ ] **Step 2: RED 확인**

Run: `node --test tests/arca_style_collector_behavior.test.js`

Expected: `isArcaBrowserSessionPending` 미정의로 실패.

- [ ] **Step 3: 최소 구현**

import API가 pending 상태를 반환하면 1초 간격으로 status API를 조회한다. terminal state 또는 네트워크 오류에서 timer를 반드시 해제한다. 중복 클릭은 기존 pending 작업 상태만 표시한다.

- [ ] **Step 4: GREEN 확인**

Run: `node --test tests/arca_style_collector_behavior.test.js`

Expected: 전체 PASS.

### Task 5: 설치 및 전체 검증

**Files:**
- Verify only

- [ ] **Step 1: 의존성 설치**

Run: `python -m pip install playwright==1.60.0`

Expected: 설치 성공. `playwright install`은 실행하지 않는다.

- [ ] **Step 2: 전체 자동 테스트**

Run: `python -m unittest discover -s tests -v`

Expected: 기존 skip 외 전체 PASS.

Run: `Get-ChildItem tests -Filter *.test.js | ForEach-Object { node --test $_.FullName }`

Expected: 전체 PASS.

- [ ] **Step 3: 실제 로그인 창 검증**

서버를 재시작하고 import 버튼을 누른다. 자동 추출 실패 후 설치된 Chrome의 앱 전용 프로필 창이 열리고 UI가 waiting으로 바뀌는지 확인한다. 자격 증명은 사용자가 직접 입력해야 하므로 로그인 제출은 자동화하지 않는다. 창을 닫으면 failed 상태와 재시도 버튼이 나타나는지 확인한다.

