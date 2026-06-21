# Arca Captcha-Safe Login Window Design

## Problem

Playwright의 `launch_persistent_context`로 실행한 Chrome에서 Arca 로그인 캡챠가 실패한다. 로그인 세션 worker 자체는 정상적으로 opening과 waiting 상태를 거쳤지만, 자동화 브라우저 환경이 캡챠 검증에 영향을 주는 것이 원인으로 판단된다.

## Goal

Chrome을 일반 프로세스로 실행하여 사용자가 로그인과 캡챠를 직접 완료하게 하고, 앱은 localhost Chrome DevTools Protocol(CDP) 연결로 Arca 쿠키만 읽는다.

## Selected approach

1. 설치된 `chrome.exe` 경로를 Windows의 표준 설치 위치에서 찾는다.
2. 사용 가능한 임시 TCP 포트를 `127.0.0.1`에서 예약한다.
3. `subprocess.Popen`으로 일반 Chrome을 실행한다.

```text
chrome.exe
--remote-debugging-address=127.0.0.1
--remote-debugging-port=<temporary-port>
--user-data-dir=<app-dedicated-profile>
--no-first-run
https://arca.live/b/aiart
```

4. `/json/version`이 응답할 때까지 짧게 기다린다.
5. Playwright는 `connect_over_cdp(http://127.0.0.1:<port>)`만 사용한다. Playwright가 Chrome을 직접 실행하지 않는다.
6. 기존 worker가 context의 `arca.live` 쿠키를 검사하고 R18 카테고리를 검증한다.
7. 성공하면 Arca 쿠키만 프로세스 메모리 세션으로 복사하고 CDP 연결 및 전용 Chrome 프로세스를 종료한다.

## Profile and credentials

기존 `artist_rater/data/arca_login_profile`을 그대로 사용한다. 사용자가 앞서 입력한 로그인 상태나 Chrome이 저장한 자동완성 데이터가 있으면 일반 Chrome 창에서 재사용할 수 있다.

앱은 비밀번호, 자동완성 데이터, 캡챠 응답을 읽지 않는다. 기존 일반 Chrome 프로필은 열거나 복사하지 않는다.

## Security boundaries

- 디버그 서버는 `127.0.0.1`에만 바인딩한다.
- 임시 포트 번호는 API와 UI에 노출하지 않는다.
- Chrome 프로세스 command line이나 프로필 경로를 로그에 남기지 않는다.
- 앱이 읽는 쿠키는 `arca.live`와 그 하위 도메인으로 제한한다.
- 관리자 권한, 프로세스 주입, 확장 프로그램, 캡챠 우회를 사용하지 않는다.
- 캡챠는 사용자가 브라우저 화면에서 직접 완료한다.

## Lifecycle and errors

- Chrome 실행 실패: `Chrome 로그인 창을 열지 못했습니다.`
- CDP 시작 지연 또는 연결 실패: Chrome 프로세스를 종료하고 안전한 재시도 메시지를 표시한다.
- 사용자가 창을 닫음: 기존 `로그인 창이 닫혔습니다.` 상태를 사용한다.
- 5분 timeout: CDP 연결과 Chrome 프로세스를 모두 종료한다.
- 성공: CDP browser 연결을 닫고 Chrome 프로세스가 남아 있으면 종료한다.

동시 로그인 작업은 기존 manager lock으로 하나만 허용한다.

## Code changes

- `artist_rater/arca_login_window.py`
  - Chrome 경로 탐색
  - localhost 임시 포트 선택
  - 일반 Chrome process 시작
  - CDP readiness 대기
  - Playwright `connect_over_cdp` 연결
  - context, playwright, process를 하나의 resource로 정리
- `artist_rater/tests/test_arca_login_window.py`
  - Chrome command에 `--enable-automation`이 없음을 검증
  - debugging address가 localhost인지 검증
  - CDP readiness와 연결 흐름을 합성 객체로 검증
  - 성공, 창 종료, timeout에서 process 정리를 검증

API와 frontend 상태 계약은 변경하지 않는다.

## Verification

- 로그인 window 단위 테스트 RED→GREEN
- Python 및 JavaScript 전체 회귀 테스트
- 서버 재시작 후 import 요청이 `opening → waiting`으로 전환되는지 확인
- 실제 창의 Chrome process command line에 `--enable-automation`이 없는지 확인
- 사용자가 직접 캡챠를 완료하기 전에는 로그인 성공을 주장하지 않는다.
