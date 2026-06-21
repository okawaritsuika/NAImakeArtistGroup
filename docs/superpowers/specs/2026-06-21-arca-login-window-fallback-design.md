# Arca Login Window Fallback Design

## Goal

Chrome/Edge 쿠키 자동 추출이 실패하면 일반 사용자가 별도 Chrome 창에서 한 번 로그인하여 🔞 NAI 수집 세션을 연결할 수 있게 한다.

## User flow

1. 사용자가 `브라우저 로그인 가져오기`를 누른다.
2. 서버는 기존 방식대로 Chrome, Edge 순서로 `arca.live` 쿠키 자동 추출을 시도한다.
3. 추출한 세션에서 🔞 NAI 카테고리가 확인되면 즉시 연결 성공으로 끝난다.
4. 자동 추출이 실패하면 앱 전용 Chrome 프로필로 로그인 창을 연다.
5. 화면 상태는 `로그인 창에서 아카라이브에 로그인해 주세요`로 바뀐다.
6. 사용자가 열린 창에서 직접 로그인한다. 앱은 비밀번호 입력과 자동완성 내용을 읽지 않는다.
7. 백그라운드 작업은 동일 창에서 🔞 NAI 카테고리가 보이는지 확인한다.
8. 검증되면 `arca.live` 도메인의 쿠키만 기존 프로세스 메모리 세션으로 복사하고 로그인 창을 닫는다.
9. 화면은 `전용 Chrome 로그인 연결됨`으로 바뀐다.

## Browser profile and autofill

로그인 창은 설치된 Chrome 실행 파일과 앱 전용 user-data 디렉터리를 사용한다. 사용자의 기존 Chrome 프로필은 열거나 복사하지 않는다. 따라서 기존 Chrome 프로필에 저장된 자동완성은 공유되지 않지만, 전용 로그인 창에서 Chrome이 제공하는 저장 기능을 사용하면 다음 로그인부터 해당 전용 프로필 안에서 자동완성이 가능하다.

앱은 전용 프로필의 비밀번호 저장소를 직접 읽지 않는다. 자동완성 UI와 자격 증명 저장은 Chrome이 전적으로 담당한다.

## Architecture

### Login session manager

`arca_style_collector.py`의 기존 쿠키 메모리 상태와 별도로 로그인 창 작업 상태를 관리한다.

- 상태: `idle`, `opening`, `waiting`, `connected`, `failed`
- 공개 정보: 상태, 안전한 안내 문구, 시작 시각
- 비공개 정보: Playwright browser context와 worker thread 참조
- 동시 로그인 창은 하나만 허용한다.

전용 프로필 경로는 `artist_rater/data/arca_login_profile`로 고정한다. 이 디렉터리는 Chrome이 관리하며 앱 DB에는 쿠키, 비밀번호 또는 프로필 내용을 기록하지 않는다.

### Browser control

Python Playwright의 persistent context를 설치된 Chrome 채널로 실행한다. 번들 Chromium을 내려받지 않고 시스템 Chrome을 사용한다.

- visible window
- dedicated user-data directory
- initial URL: `https://arca.live/b/aiart`
- navigation and validation timeout: 5 minutes

worker는 주기적으로 현재 context의 `arca.live` 쿠키를 가져와 requests 세션에 복사하고 기존 `discover_category_params`로 검증한다. `R18_NAI`가 확인된 경우에만 성공이다.

### API

- `POST /api/arca-styles/browser-session/import`
  - 기존 자동 추출 성공: `200`, 연결 상태 반환
  - 자동 추출 실패 후 로그인 창 시작: `202`, `state: waiting` 반환
  - 이미 로그인 창이 열려 있음: `202`, 현재 상태 반환
- `GET /api/arca-styles/browser-session`
  - `connected`, `browser`, `error`, `state`, `message`만 반환

쿠키 값, 브라우저 프로필 경로, 예외 원문은 API나 로그에 포함하지 않는다.

### Frontend

기존 버튼을 그대로 사용한다. `202`를 받으면 상태 API를 1초마다 조회한다.

- opening: `로그인 창 여는 중…`
- waiting: `로그인 창에서 아카라이브에 로그인해 주세요`
- connected: `전용 Chrome 로그인 연결됨`
- failed: 안전한 실패 사유와 재시도 안내

로그인 작업이 끝나면 polling timer를 해제한다. 사용자가 창을 직접 닫았거나 5분이 지나면 실패 상태가 되고 버튼을 다시 사용할 수 있다.

## Error handling

- 시스템 Chrome을 찾지 못함: 설치 안내를 표시하고 로그인 창을 시작하지 않는다.
- Playwright 시작 실패: 세부 예외를 숨긴 안전한 오류를 표시한다.
- 로그인 창 직접 종료: `로그인 창이 닫혔습니다. 다시 시도해 주세요.`
- 시간 초과: `로그인 시간이 초과되었습니다. 다시 시도해 주세요.`
- 로그인했지만 R18 카테고리 없음: 로그인 또는 성인 콘텐츠 접근 설정을 확인하라는 안내를 표시한다.
- 앱 종료: 실행 중인 context를 닫고 worker가 종료되도록 한다.

실패한 로그인 작업은 수집 완료 이력을 생성하지 않는다. 직접 URL 추가는 로그인 창 상태와 무관하게 계속 사용할 수 있다.

## Security

- 기존 Chrome 프로필을 복사하거나 수정하지 않는다.
- 관리자 권한, 프로세스 주입, Chrome 강제 종료, 확장 프로그램 설치를 사용하지 않는다.
- 앱은 입력된 아이디, 비밀번호, 자동완성 값을 읽지 않는다.
- requests로 복사하는 쿠키는 `arca.live`와 그 하위 도메인으로 제한한다.
- requests 쿠키는 프로세스 메모리에만 존재한다.
- 전용 Chrome 프로필의 세션 및 자격 증명 저장 여부는 Chrome의 사용자 선택에 따른다.

## Dependencies

`playwright` Python 패키지를 고정 버전으로 추가한다. 시스템 Chrome 채널을 사용하므로 `playwright install chromium`은 실행하지 않는다.

## Testing

실제 비밀번호나 브라우저 프로필을 테스트에서 사용하지 않는다.

- 자동 추출 성공 시 로그인 창을 열지 않음
- 자동 추출 실패 시 worker가 한 번만 시작됨
- 합성 Playwright context의 Arca 쿠키만 필터링됨
- R18 카테고리 검증 후 메모리 세션 연결 및 context 종료
- 창 종료, timeout, Chrome 없음의 안전한 상태 전환
- API가 쿠키와 예외 원문을 노출하지 않음
- frontend가 `202` 후 polling하고 terminal state에서 중지함
- 기존 수집기/API/프론트 회귀 테스트 유지

수동 검증은 전용 Chrome 창에서 로그인하고 🔞 NAI 연결 상태가 표시되는 지점까지만 수행한다. 자격 증명 입력은 사용자가 직접 한다.
