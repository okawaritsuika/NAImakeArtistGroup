# Arca Captcha-Safe Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자동화 Chrome 실행을 일반 Chrome 프로세스 + localhost CDP 연결로 교체하여 Arca 로그인 캡챠 실패를 줄인다.

**Architecture:** `ArcaLoginWindowManager`의 public contract와 worker loop는 유지한다. context factory만 Chrome executable 탐색, 임시 localhost 포트, subprocess 실행, CDP readiness 대기, `connect_over_cdp` 연결로 교체하고 resource cleanup에 Chrome process를 포함한다.

**Tech Stack:** Python 3, subprocess, socket, urllib, Playwright Python CDP, unittest

---

### Task 1: 일반 Chrome CDP resource

**Files:**
- Modify: `artist_rater/tests/test_arca_login_window.py`
- Modify: `artist_rater/arca_login_window.py`

- [ ] **Step 1: 실패 테스트 작성**

주입한 process launcher와 CDP connector를 사용해 Chrome command를 검증한다.

```python
resource = open_chrome_cdp(profile_dir, chrome_path, 43123, launcher, connector, readiness)
self.assertIn("--remote-debugging-address=127.0.0.1", launcher.command)
self.assertIn("--remote-debugging-port=43123", launcher.command)
self.assertNotIn("--enable-automation", launcher.command)
self.assertEqual(connector.endpoint, "http://127.0.0.1:43123")
```

resource cleanup이 CDP browser, Playwright, Chrome process를 모두 종료하는 테스트도 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: `open_chrome_cdp` 미정의로 실패.

- [ ] **Step 3: 최소 구현**

`find_chrome_executable()`은 Program Files와 LocalAppData의 표준 Chrome 경로만 검사한다. `reserve_local_port()`는 `127.0.0.1:0` bind 결과를 사용한다. `open_chrome_cdp()`는 command list로 `subprocess.Popen`을 호출하고 readiness 성공 후 `sync_playwright().start().chromium.connect_over_cdp(endpoint)`를 실행하여 `(context, playwright, browser, process)` resource를 반환한다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: 전체 PASS.

### Task 2: Manager lifecycle 교체

**Files:**
- Modify: `artist_rater/arca_login_window.py`
- Modify: `artist_rater/tests/test_arca_login_window.py`

- [ ] **Step 1: 실패 테스트 작성**

manager의 factory가 4개 resource tuple을 반환할 때 성공, timeout, 창 종료 모두 browser close와 process terminate를 수행하는 테스트를 추가한다.

- [ ] **Step 2: RED 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: 기존 `_close`가 2개 tuple만 처리하여 실패.

- [ ] **Step 3: 최소 구현**

기본 `_open_chrome`은 `open_chrome_cdp`를 호출한다. `_close`는 context, browser, playwright, process를 순서대로 안전하게 정리하고 이미 종료된 process에는 terminate를 호출하지 않는다. worker는 tuple 길이에 관계없이 context를 첫 원소로 사용한다.

- [ ] **Step 4: GREEN 확인**

Run: `python -m unittest tests.test_arca_login_window -v`

Expected: 전체 PASS.

### Task 3: 회귀 및 실제 검증

**Files:**
- Verify only

- [ ] **Step 1: 전체 테스트**

Run: `python -m unittest discover -s tests -v`

Expected: 기존 skip 외 전체 PASS.

Run: `Get-ChildItem tests -Filter *.test.js | ForEach-Object { node --test $_.FullName }`

Expected: 전체 PASS.

- [ ] **Step 2: 실제 process 검증**

서버를 하나만 재시작하고 import API를 호출한다. 상태가 `opening → waiting`인지 확인하고 로그인 창 Chrome command line에 localhost debugging flags가 있으며 `--enable-automation`이 없는지 확인한다. 캡챠와 로그인 제출은 사용자가 직접 수행한다.
