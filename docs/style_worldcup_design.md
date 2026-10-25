# 그림체 이상형 월드컵

## 참가 선택과 화면

- 헤더의 이상형 월드컵은 저장된 대회를 폴더 갤러리로 표시한다. 진행 중 대회는 이어하기, 완료 대회는 우승 결과와 기록을 연다. 새로 만들기는 별도 대회를 만든다.
- 새로 만들기는 이름·자동 선택·필터·참가 갤러리가 함께 있는 한 페이지를 바로 연다. `section#worldcupPicker.worldcup-picker-page` 안에 `form#worldcupForm`을 두고 시작까지 한 번에 진행한다. 별도 생성 view나 선택 완료 단계는 없다. 목록·생성 갤러리·경기는 상호 배타적이며 그림체 상세는 생성 갤러리 옆 패널로 연다.
- 같은 공유 게시글(item_id) 또는 확정 항목(style_id)당 조건을 만족하는 대표 이미지 하나만 표시한다. 공유는 이미지 ID, 확정은 position·이미지 ID 순으로 첫 정상 로컬 이미지를 고른다. 서로 다른 항목은 프롬프트가 같아도 합치지 않는다.
- 필터는 항상 보이는 `section#worldcupPickerFilters` 안에 한 벌만 둔다. 제목 “그림체 필터”는13px의 짧은 캡션이다. 입력 중인 조건과 마지막 적용 조건을 분리하며 필터는 보이는 목록만 바꾼다. 구체적인 밀도·배치는 아래 생성 화면 계약을 따른다.
- 모델은 전체, V5 전체(Medium 포함), V5 Full Medium, V5 Full, V5 Curated, V4.5 전체, V4.5 Full, V4.5 Curated, Unknown을 제공한다. 수집기의 모델 분류·필터 함수를 재사용한다.
- 작가와 일반 태그는 같은 포함/제외 입력을 쓴다. 포함은 모두 일치, 제외는 하나라도 일치하면 해당 이미지가 후보에서 빠진다. 베이스 프롬프트의 완전한 태그만 검사하고 가중치·대소문자·밑줄/공백 차이를 정규화한다. 네거티브·캐릭터 프롬프트는 검사하지 않는다. 확정 항목의 베이스는 현재 artist_prompt + quality_prompt + fixed_prompt다.
- 두 태그 입력은 기존 promptTagAutocomplete.bind/hide를 재사용한다. 두 글자 이상 자동완성, 방향키/Enter, 작가의 artist: 접두사, 쉼표·줄바꿈으로 구분한 현재 태그 교체를 유지한다. 제안 목록은 문서 흐름 안에서 max-height:min(220px,40dvh), 긴 태그 줄바꿈과44px 버튼을 보장한다.
- 추천수 N 이하 제외는 공유의 추천수>N이며 미상도 제외한다. 비우면 제한이 없고 확정에는 적용하지 않는다. `worldcupPickerSort`는 기본순/default, 추천 많은 순/recommendation_desc, 추천 적은 순/recommendation_asc다. 전체 후보를 정렬한 다음 페이지를 나누고, 미상·확정의 추천수 없음은 양방향 모두 뒤에 둔다.
- 출처 전체/공유/확정, 전체 후보/선택한 그림만 보기는 명단을 보존한다. 선택한 그림만 화면은 필터에 가려진 선택도 확인·해제할 수 있다. 다른 필터로 같은 항목의 대표 이미지가 달라져도 group_key로 중복을 막고 이미 선택한 실제 image key는 임의 교체하지 않는다.
- 수동 선택과 자동 선택은 하나의 참가 명단을 즉시 갱신한다. 같은 페이지에서 2개 이상 고르면 “월드컵 시작”으로 바로 생성한다. 선택 완료 버튼이나 별도 확정 명단은 없다. 자동 선택은 현재 필터의 공유·확정 전체 후보에서 뽑아 기존 명단에 그룹 중복 없이 추가한다. 생성 실패 시 이름·필터·명단을 유지하며 다시 시작할 수 있다. 목록으로 돌아가면 생성 화면을 닫고, 새로 만들기는 새 명단으로 시작한다.
- 후보 수를 확인한 후 가능한2·4·8강 등의 규모 또는 전부 참가를 제공한다. 전부 참가에128개 제한은 없다. 최종 참가 인원은 검토한 명단 수이며 2의 거듭제곱이 아니면 첫 라운드 부전승을 배정한다. 실제 경기 수는 N-1이다.

## 갤러리 크기와 조작

- 페이지는 width100%, height:auto, overflow:visible이며 별도 고정높이·중첩스크롤을 만들지 않는다. 데스크톱은 기존 worldcup view,1320px 이하는 문서가 세로 스크롤을 소유한다. 생성 form은 하나의 세로 흐름이며 간격10px다. 모든 조작44px, 본문12~14px, 제목20px를 유지한다. 1440×900에서 첫 카드 top은540px 이내를 목표로 실제 렌더에서 확인한다.
- form 첫 행 `.worldcup-create-head`에 제목/이름/시작/목록을 모두 둔다. 데스크톱 grid는 auto minmax(200px,420px) minmax(0,1fr) auto auto이며 이름 label은 “이름”+input의 가로 배치다.700px 이하에서는 제목+목록 첫 행, 이름 전체 폭 둘째 행, 시작 전체 폭 셋째 행으로 배치한다. 이름을 페이지 끝까지 늘리지 않는다. 상단과 하단 시작 버튼은 선택 개수를 표시하며 2개 미만 또는 조회/저장 중 비활성화한다.
- 둘째 행 `.worldcup-selection-bar`에는 총/공유/확정 개수와 선택수 badge를 왼쪽에 붙이고 자동 선택 규모(160px)·자동 선택 버튼·선택 안내를 오른쪽에 배치한다. 별도 넓은 배경박스·테두리·분리행을 만들지 않는다. flex-wrap과 gap8px로 좁은 폭에서 자연스럽게 감싸고 모바일 자동 선택은 한 행에 select+button, 안내는 다음 행으로 배치한다. 안내를 열 때만 상세 설명이 추가된다.
- 필터 패널 padding10px,gap8px,border1px,radius8px. 캡션 아래 한 줄에 모델/추천수/포함 태그/제외 태그/적용/조건 안내를 배치한다. grid는 minmax(150px,.85fr) minmax(140px,.75fr) minmax(160px,1.25fr) minmax(160px,1.25fr) auto auto.900px 이하에서는 동일한 두 열로 모델/추천,포함/제외,적용/안내가 세 행으로 놓인다. 라벨12px,gap4px,textarea rows=1,min-height=44px,height=44px이며 필요하면 사용자가 세로로 늘릴 수 있다. 긴 추천수·태그 설명은 조건 안내 details 안에 두고 기존 aria-describedby ID를 유지한다. 적용 버튼과 안내 summary는 입력과 같은 높이에 정렬한다. 안내가 열리면 전체 열을 차지하며 overlay를 만들지 않는다. 자동완성도 기존 문서 흐름을 유지한다.
- 갤러리 도구는 출처/보기/추천수 정렬/크기 조절 4열을 유지한다.900px 이하에서는 출처 전체 폭,보기+정렬 두 열,크기 전체 폭의 세 행으로 배치한다.700px 이하에서도 보기·정렬을 한 열씩 따로 늘어놓지 않는다. 현재 목록 개수/짧은 드래그 도움말/적용모델은 하나의 wrapping 행으로 표시한다. 필터 변경 안내는 실제 입력 변경 시에만 보인다. 카드 제목·이미지·선택·상세 버튼과 상단 설정에 불필요한 고정 빈 높이를 추가하지 않는다.
- 후보는 한 페이지60개. 기존384px style-manager 썸네일을 우선 사용하고 async decoding을 적용한다. 선택만 바뀌면 카드 이미지 DOM을 다시 만들지 않는다. 경기·결과는 원본을 유지한다.
- `worldcupPickerCardSize` range는112~240px,step16,기본160이다. 크기 변경은 CSS 변수만 갱신하며 서버 요청이나 선택 초기화가 없다. grid는 repeat(auto-fill,minmax(min(100%,var(--worldcup-card-size,160px)),1fr)),gap10px다.
- 카드 `.worldcup-picker-item` 안에 `.worldcup-picker-card` 선택 버튼과 `.worldcup-picker-detail` 상세 버튼을 독립 배치한다. 선택 카드 행은 image/title/metadata/selection의 auto 4행이며 제목의 고정 두 줄 높이를 없앤다. 이미지3:4 contain,제목13px 최대 두 줄 말줄임. `.worldcup-picker-card-meta`는 auto minmax(0,1fr) auto의 3열로 출처/모델/추천수 `.worldcup-picker-chip`을 한 줄에 배치한다. chip은 border1px,radius4px,padding2px 4px,font11px,line-height16px이며 모델은 말줄임+title로 전체 표시를 보완한다. 선택 문구13px,조작 높이44px와 전체 제목 title/aria-label을 유지하고 버튼을 중첩하지 않는다.
- 마우스로 카드나 갤러리 빈틈에서 드래그하면 반투명 사각형을 표시하고 그 영역과 겹친 선택 카드들을 선택한다. 이미 선택된 카드에서 시작하면 영역 내 선택을 해제한다. 시작 시 명단을 기준으로 매 이동마다 교집합을 다시 계산하므로 사각형을 줄이면 빠져나간 카드는 원래 상태로 돌아간다. 영역 밖 기존 선택은 유지한다. 상세 버튼에서 드래그를 시작하지 않는다. 갤러리 안 `worldcupPickerMarquee`는 position:absolute,pointer-events:none,aria-hidden이며 그리드 행·열에 영향을 주지 않는다. 그리드에 position:relative를 두고 스크롤 변화를 포함한 콘텐츠 좌표로 계산한다.5px 임계값,pointer capture,모든 방향 드래그,클릭 후 중복 토글 방지를 유지한다. 터치는 스크롤과 탭을 사용한다.
- pointercancel/Escape는 드래그 전 명단을 복원하고 캡처·사각형을 정리한다. 드래그 중 Escape는 생성 페이지를 떠나지 않는다. 출처·페이지 전환 시에도 드래그를 정리한다. 선택한 그림만 보기에서 드래그 중에는 카드를 제거하지 않고 종료 후 갱신한다. 클릭/Enter/Space,focus-visible,aria-pressed와 체크 표시를 유지한다.
- 새로 만들기 직후에는 개수·후보·이미지를 조회하지 않고 필터 적용 안내만 표시한다. 필터 적용(추천수 입력의 Enter 포함) 후 처음으로 개수·후보를 조회한다. 적용 전 출처/보기/정렬/자동 선택/시작은 비활성화한다. 로딩·빈 상태·오류는 짧게 표시하며 조회 중에는 필터/선택/시작을 비활성화하고 목록으로 버튼은 유지한다. 실패 시 필터 적용으로 재시도하며 기존 명단은 보존한다. 닫힌 화면·새 페이지·필터 변경 후 도착한 응답은 요청 token으로 무시한다.

## 게시글·확정 항목 상세

- `div#worldcupGalleryLayout.worldcup-gallery-layout`은 `div.worldcup-gallery-results`(기존 grid+pages)와 `aside#worldcupCandidateDetail.worldcup-candidate-detail`을 가진다. 상세가 닫히면 1열, data-detail-open=true이면 minmax(0,1fr) minmax(320px,38%)의 두 열/gap14px다. 필터·출처·총 개수는 이 레이아웃 위에 유지한다. 상세는 별도 페이지 view로 전환하지 않고 갤러리 DOM·이름·필터·참가 명단을 유지한다. `worldcupCandidateDetailBack`은 “상세 닫기”로 표시하며 열기 전 스크롤·마지막 상세 버튼 focus를 복원한다.
- 상세 패널은 padding12px,border1px,radius10px,내용 간격10px,높이 auto이며 데스크톱은 기존 페이지 세로 스크롤을 쓴다. 제목은16px·최대두줄·title 전체텍스트로 표시한다.900px 이하에서는 오른쪽 고정 패널 width:min(100%,420px),height:100dvh,z-index80,overflow-y:auto로 표시한다. 패널 header는 sticky top:-12px,margin:-12px -12px 0,padding12px로 부모 padding을 상쇄해 상단·양옆을 배경으로 덮고 닫기를 유지한다. 갤러리는 배경에 유지하며 패널 전체 가로 overflow를 만들지 않는다.
- `worldcupCandidateDetailContent` 안은 단일 열로 toolbar/image/thumbnails/prompts를 배치한다. toolbar에는 `worldcupCandidateDetailPrev`/`worldcupCandidateDetailNext` 44px 버튼, `worldcupCandidateDetailImageModel` 이미지 번호·모델, `worldcupCandidateDetailSize` range40~100 step10 default100 및 `worldcupCandidateDetailSizeValue` output을 둔다. slider는 `--worldcup-detail-image-size` 퍼센트 폭을 바꾸며 이미지 wrapper는 가운데 정렬,이미지는 height:auto,max-height:60dvh,object-fit:contain이다. thumbnails는 repeat(auto-fill,minmax(64px,1fr)),이미지높이72px이며 프롬프트 details는 기본 접힘이다.
- 좌우 방향키는 상세가 열려 있고 입력/textarea/select/contenteditable이 아닌 곳에 focus가 있을 때 같은 게시물/확정항목의 이전·다음 이미지로 이동한다. 처음/끝에서는 멈추고 대응 버튼을 비활성화한다. range의 방향키는 크기 조절을 유지한다. Escape는 상세를 닫되 기존 드래그 취소가 우선한다. 열림·오류·빈 이미지 상태에서 갤러리와 닫기는 계속 사용 가능하다.
- 후보의 detail_url로 기존 GET /api/arca-styles/{id} 또는 /api/confirmed-styles/{id}를 재사용한다. 경로를 정확히 검증하고 제목·추천수·모델·원문 주소·현재 필터와 무관한 전체 이미지 목록을 표시한다.
- 이미지 썸네일을 누르면 큰 원본과 베이스·네거티브·캐릭터 프롬프트를 보여준다. 확정 이미지는 저장 항목의 현재 프롬프트를 사용한다. 사용자 텍스트는 textContent로 렌더한다.
- 로컬 이미지 URL만 허용하며 원문 링크는 http(s),noopener noreferrer를 사용한다. 공백·한글 경로는 안전하게 인코딩한다. 누락 이미지는 안내하고 오류에도 뒤로 버튼을 유지한다. 늦은 상세 응답은 token으로 폐기한다.

## API와 저장 호환성

- sources는 shared/confirmed 배열이며 생략하면 기존 shared다. 빈 배열·알 수 없는 출처는 거절한다. preview는 count와 counts.shared/counts.confirmed를 반환한다.
- POST /api/style-worldcups/candidates는 기존 필터,model(기본all),sort,page(기본1),per_page(기본24,최대60),선택적auto_size를 받는다. count/counts/page/per_page/items,자동선택 요청만selection을 반환한다. 후보는 key(출처:이미지ID),group_key(출처:항목ID),detail_url,title,image_source,image_url,thumbnail_url,model_label,available,recommendation_count를 포함한다.
- 생성의 selected_candidates는 사용자가 확인한 실제 image key 목록이다. UI는 size=all,selection_scope=all을 보내 현재 보기 필터와 독립적으로 정확한 명단을 생성한다. 서버는 존재하는 출처·정상 메타데이터·안전한 로컬 파일·같은 그룹 중복·최소2개를 검증한다. 유실된 이미지를 다른 대표로 대체하지 않는다.
- selection_scope 기본filtered는 기존처럼 현재 필터의 대표 후보만 허용한다. all은 명시 selected_candidates를 요구하며 filters_json에도 적용 범위를 기록한다. 기존 명단 없는 API 생성은 유지한다. 기존 저장 대회의 참가자·대진·결과는 바꾸지 않는다.
- 월드컵과 참가자 스냅샷을 SQLite에 저장한다. 매 선택은 revision을 검사하는 트랜잭션으로 처리하고 오래된 요청은409다. 참가자의 image_source·경로·프롬프트를 보관하고 대진 JSON에는 월드컵 내부 ordinal을 사용한다.
- 선택 요청 compact:true는 다음 경기 두 참가자(완료 시 우승자)만 반환하고 participants_partial:true로 표시한다. UI는 ordinal로 기존 참가자 목록과 병합한다. 생성·조회·기존 선택 요청은 전체 응답을 유지한다.
- 원본 파일 삭제 후에도 결과 텍스트·프롬프트·대결 기록은 남는다. 복수 데이터 병합은 UUID와 FK 및 출처별 이미지 경로를 매핑한다. 이번 갤러리 개선에는 스키마 변경이나 사용자 DB·시드 변환이 없다.

## 담당 파일과 검증

- 데이터와 후보/선택 검증은 style_worldcup_store.py,라우트는 app.py,UI는 templates/style_worldcup.html 및 static/style_worldcup.js/css다. 기존 API·썸네일을 재사용한다.
- 임시 SQLite/합성 이미지로 그룹 중복,모델·태그·추천 필터,정렬 전 페이지 분할,안전 경로,명단 보존·유실 거절,대회 저장/재개/409/부전승/병합을 검증한다. 100게시글×10이미지에서 대표100개에 파일 검사100회만 수행하는 회귀를 둔다.
- Node 행동,Python DOM/CSS 계약,관련 store/API/data_merge,변경 Python/JS 문법 검사를 실행한다. 공용 초기화·스키마 변경이 없으면 전체 suite나 EXE 빌드는 기본 검증으로 실행하지 않는다.
- 실제 Chrome:1440×900,1024×768,901/900/701/700×760,390×844,390×500. 60개·긴 제목·112/160/240크기·빈 목록·오류,44px 액션/overflow,마우스 드래그/키보드,필터·정렬 변경 시 선택 보존,같은 항목 대표 변경,상세 모든 이미지와 돌아오기,정확한 명단 저장·재개를 확인한다.
