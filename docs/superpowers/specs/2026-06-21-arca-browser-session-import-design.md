# Arca Browser Session Import Design

## Goal

Let non-technical users import their existing Arca Live browser login with one button so NAI and R18 NAI searches can be collected accurately.

## Browser session import

The collection panel exposes `브라우저 로그인 가져오기`. The server attempts Chrome first and Edge second, reading cookies only for `arca.live`. It never requests, returns, logs, or persists cookies for any other domain.

Imported cookie values live only in process memory. They are not written to SQLite, settings files, logs, API responses, HTML, or browser storage. Restarting the app clears the session. A second import replaces the in-memory Arca cookie jar. The UI receives only connection state, browser name, and a safe validation message.

If automatic import fails because no supported browser profile exists, cookie decryption is unavailable, or the profile is locked, the UI gives a concise retry message. It does not fall back to asking for a raw Cookie header.

## Session validation

After import, the server requests the public AI-art board with the imported Arca cookies. Validation succeeds only when the response exposes the R18 NAI category/search capability, not merely when a generic sensitive-media flag exists. Invalid or expired sessions are discarded from memory.

The interface shows one of `연결 안 됨`, `Chrome 연결됨`, `Edge 연결됨`, or `연결 실패`. No account name or cookie value is displayed.

## Category-aware collection

The collector discovers category links from the validated board response and maps requested tabs to their real server query parameters. NAI and R18 NAI are searched independently for every page, then canonical article URLs are deduplicated before article fetching.

When R18 NAI is requested without a validated browser session, the request fails before creating completed coverage and explains that browser login import is required. NAI-only collection remains available without login.

Completed coverage uses a new search-scope version so previous runs that combined tabs while receiving no R18 rows no longer block recollection. A run is completed only after every requested category was available and searched successfully. Direct URL collection remains independent of search coverage and login import.

## Security and failure handling

- Cookie access is restricted to the local machine and the exact Arca Live domain.
- Cookie values are never included in exceptions or structured logs.
- Browser import and validation endpoints are local POST operations.
- Failed imports clear any prior in-memory session to avoid stale connection state.
- Collection sessions copy only the imported Arca cookies into the existing bounded requests session.
- Existing request timeouts, retries, image limits, and safe parsing remain in force.

## User interface

The collection panel places the import action and connection badge above the NAI/R18 selectors. Selecting R18 NAI while disconnected shows an inline explanation. Successful import updates the badge without reloading the page. Date collection and direct URL collection continue to use the existing job progress display.

## Testing

Tests use temporary synthetic cookie jars and mocked browser loaders; real browser cookies never enter test output. Coverage includes domain filtering, memory-only storage, Chrome-to-Edge fallback, validation success/failure, category discovery, separate category URLs, R18 rejection while disconnected, invalidation of old combined coverage, API safety, and frontend connection states.
