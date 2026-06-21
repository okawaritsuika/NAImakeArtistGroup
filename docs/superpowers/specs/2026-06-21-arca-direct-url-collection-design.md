# Arca Direct URL Collection Design

## Goal

Allow one public Arca Live AI-art post URL to be collected directly, independently of date-range search coverage.

## Design

- Accept one canonical `https://arca.live/b/aiart/<number>` URL at a time.
- Validate and canonicalize the URL server-side; reject other hosts, boards, paths, query-only links, and malformed IDs.
- Start a persisted background job so posts with many images do not block the request.
- Fetch and parse the article with the existing bounded session, image downloader, metadata extraction, duplicate reuse, and style grouping pipeline.
- Insert a new item or update the existing source URL. Direct collection does not create completed date coverage or clear unrelated invalidations.
- Reuse the existing job-status endpoint and progress UI. Refresh the archive list when the job completes.
- Show a single URL field and `링크로 추가` action in the collection panel.

## Verification

Tests cover URL validation, direct job lifecycle, upsert behavior, API status, frontend payload/polling, and the representative URL `https://arca.live/b/aiart/174457459`.
