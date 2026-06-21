# Danbooru Artist Rater

Danbooru 작가를 평가하고, 평가 결과로 NovelAI용 그림체 프롬프트를 구성하는 Windows 로컬 도구입니다. 아카라이브의 그림체 공유 게시글과 이미지 메타데이터도 수집·정리할 수 있습니다.

## 주요 기능

- Danbooru 작가 검색, 샘플 확인, 1~5점 평가
- 평가한 작가로 가중치 기반 그림체 프롬프트 제작
- NovelAI 이미지 생성과 생성 결과 관리
- 아카라이브 그림체 공유 게시글 기간 수집 및 링크 직접 추가
- 이미지별 베이스·네거티브·캐릭터 프롬프트 비교
- 추천·조회·게시일 기준 그림체 정렬

## EXE 사용

1. GitHub Releases에서 `DanbooruArtistRater.exe`를 받습니다.
2. EXE를 실행한 뒤 콘솔에 표시되는 `http://127.0.0.1:5001`을 브라우저에서 엽니다.
3. 설정, DB, 썸네일, 생성 이미지와 로그인 프로필은 EXE 옆 `data` 폴더에 저장됩니다.

아카라이브 성인 게시판 로그인 연결에는 로컬 Chrome이 필요합니다. NovelAI App Key는 GitHub나 EXE에 포함되지 않으며 사용자 PC의 `data/settings.json`에만 저장됩니다.

## 소스 실행

```powershell
cd artist_rater
python -m pip install -r requirements.txt
python app.py
```

## EXE 빌드

```powershell
python -m pip install pyinstaller
.\build_exe.ps1
```

빌드 결과는 `release/DanbooruArtistRater.exe`에 생성됩니다. 로컬 설정과 사용자 데이터는 빌드에 포함되지 않습니다.

