# v0.1.14 · 아카라이브 계정 저장과 자동 로그인

아카라이브 아이디와 비밀번호를 저장하고, 앱 전용 Chrome 창에서 로그인 연결을 시작할 수 있습니다. 확장 프로그램은 선택해서 사용할 수 있습니다.

[**v0.1.14 EXE 다운로드**](https://github.com/okawaritsuika/NAImakeArtistGroup/releases/download/v0.1.14/DanbooruArtistRater.exe)

Windows에서 사용하며 Chrome 설치가 필요합니다. 업데이트할 때는 기존 EXE 옆의 `data` 폴더를 유지해 주세요.

## 달라진 점

- **계정 저장:** 아이디와 비밀번호 전체를 Windows DPAPI로 암호화합니다. 저장 정보는 같은 Windows 사용자 계정에서만 복원할 수 있습니다.
- **계정별 전용 Chrome:** 앱이 관리하는 계정별 창에서 로그인합니다. 아이디·비밀번호를 로그인 단계에 맞춰 한 번 자동 입력하며 반복 제출하지 않습니다.
- **확장 프로그램은 선택:** 저장 계정으로 로그인하거나, 기존 확장으로 평소 Chrome의 로그인을 연결할 수 있습니다.
- **전용 창 연결 보완:** 로컬 Chrome 제어 연결이 프록시 설정의 영향을 받지 않도록 수정하고, EXE에서 Chrome을 시작하는 환경을 정리했습니다. 창 준비 실패와 연결 종료도 구분해 표시합니다.

## 사용 순서

1. **공유 그림체 수집 → 🔞 게시판 로그인 → 계정 저장하고 자동 로그인**을 펼칩니다.
2. 아이디와 비밀번호를 입력하고 **저장하고 로그인**을 누릅니다.
3. 열린 Chrome에서 캡차·추가 인증을 직접 완료하고 앱의 연결 상태를 확인합니다.
4. 다음부터는 **저장된 계정으로 로그인**을 눌러 연결합니다.

![아카라이브 계정 저장과 자동 로그인 화면](https://raw.githubusercontent.com/okawaritsuika/NAImakeArtistGroup/v0.1.14/docs/assets/patch-notes-v0.1.14/login-account.png)

**R18 기간 수집**은 로그인이 필요하면 연결 후 대기 중인 수집을 자동으로 이어갑니다. **링크 추가·조회/추천 갱신**은 먼저 로그인을 연결한 뒤 실행해 주세요.

## 연결이 실패할 때

Chrome 로그인 성공과 앱의 게시판 접속 확인은 별도입니다. 계정 저장만으로 인증서·프록시·사이트 차단 같은 네트워크 문제가 모두 해결되지는 않습니다.

| 오류 표시 | 확인할 내용 |
| --- | --- |
| `ARCA_TLS` | 보안 인증서 확인 실패. PC 날짜·시간, 보안 프로그램의 HTTPS 검사 설정을 확인해 주세요. |
| `ARCA_PROXY` | 프록시 연결 실패. Windows 또는 네트워크의 프록시 설정을 확인해 주세요. |

오류 제보에는 **앱 버전, 누른 버튼, 화면의 오류 문구 전체, 전용 Chrome 창이 닫힌 시점**을 알려 주세요. **비밀번호나 쿠키 파일은 보내지 마세요.** 화면을 공유할 때는 아이디도 가려 주세요.

## 확인한 범위

관련 Python 테스트 217개와 화면 동작 테스트 236개를 통과했습니다. 배포 EXE에서 시험 계정의 암호화 저장·복원·삭제, 390·768·1280px 화면, 실제 Chrome의 시험용 단계별 로그인 폼을 확인했습니다. 실제 아카라이브 계정 로그인과 제보 PC에서의 재현은 아직 확인하지 못했습니다.

[디자인된 업데이트 안내 HTML](https://github.com/okawaritsuika/NAImakeArtistGroup/releases/download/v0.1.14/arca_patch_notes_v0.1.14.html)

[프로그램 소개 본글](https://arca.live/b/aiart/177316727) · [GitHub 릴리스](https://github.com/okawaritsuika/NAImakeArtistGroup/releases/tag/v0.1.14)
