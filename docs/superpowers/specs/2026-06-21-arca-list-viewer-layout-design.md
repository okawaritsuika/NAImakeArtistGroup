# Arca List Scroll, Date Sort, and Image Viewer Design

## Goal

수집 그림체가 많아져도 목록을 스크롤할 수 있게 하고, 아카라이브 게시글 작성일로 정렬하며, 수정·확대 화면에서 선택한 이미지를 크게 확인할 수 있게 한다.

## List scrolling

수집 탭이 활성화되면 전체 view가 사용 가능한 화면 높이를 사용한다. 왼쪽 수집 패널은 기존 위치를 유지하고 오른쪽 `.arca-style-main`만 내부 스크롤 영역을 갖는다. 필터와 목록 상태는 위에 유지하고 카드 목록이 남은 높이에서 스크롤된다.

좁은 화면에서는 전체 페이지 스크롤 방식으로 돌아가며 중첩 스크롤을 만들지 않는다.

## Arca post date sorting

필터 영역에 `아카라이브 날짜` select를 추가한다.

- `최신순` — 기본값
- `오래된순`

정렬 기준은 `arca_style_items.posted_at`이다. `collected_at`, `created_at`, DB id는 사용자에게 보이는 정렬 기준으로 사용하지 않는다. 날짜가 없는 항목은 두 정렬 모두 날짜가 있는 항목 뒤에 위치하고, 같은 날짜에서는 id 내림차순으로 안정적인 순서를 만든다.

목록 API는 `sort=posted_desc|posted_asc`만 허용한다. 누락 시 `posted_desc`, 잘못된 값은 400이다. 검색어나 메타데이터 필터가 바뀔 때와 동일하게 sort 변경도 목록을 다시 요청한다.

## Selected image viewer

수정·확대 모달의 각 그림체 그룹은 다음 구조를 사용한다.

- 위: 그룹 제목과 가로 썸네일 목록
- 아래: 선택 이미지 viewer grid
  - 왼쪽: 선택한 이미지의 큰 미리보기
  - 오른쪽: 베이스, 네거티브, 캐릭터 prompt textarea

썸네일 클릭 시 기존처럼 세 prompt를 바꾸면서 큰 이미지의 `src`와 접근 가능한 설명도 함께 바꾼다. 첫 이미지가 기본 선택된다.

큰 이미지는 영역 안에 맞춰 `object-fit: contain`으로 표시하고, 세로 화면에서도 모달을 넘지 않도록 최대 높이를 제한한다. 이미지 자체를 다시 클릭해 별도 전체화면 모달을 여는 기능은 이번 범위에서 제외한다.

모바일에서는 viewer grid를 한 열로 바꿔 큰 이미지가 위, prompt가 아래에 표시된다.

## Files

- `artist_rater/arca_style_collector.py`: sort 검증 및 SQL ORDER BY.
- `artist_rater/templates/index.html`: 날짜 정렬 select.
- `artist_rater/static/arca_style_collector.js`: sort query와 선택 이미지 미리보기.
- `artist_rater/static/style.css`: 목록 내부 스크롤과 viewer 반응형 layout.
- collector/API/frontend/JS tests: 정렬 계약, DOM 요소, 이미지 선택 projection.

## Testing

- 기본 최신순과 오래된순이 `posted_at` 기준으로 동작한다.
- 날짜 없는 항목이 뒤에 위치한다.
- 잘못된 sort는 거절된다.
- frontend 요청에 sort가 포함된다.
- viewer helper가 선택 이미지 URL과 세 prompt를 함께 반환한다.
- 큰 이미지 DOM과 sort select가 존재한다.
- desktop 내부 스크롤과 mobile 단일 스크롤 CSS 계약을 검증한다.
- 기존 Arca 수집, 로그인, prompt 그룹 테스트가 유지된다.
