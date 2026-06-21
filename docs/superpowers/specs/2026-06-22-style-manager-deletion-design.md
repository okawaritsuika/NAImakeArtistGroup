# Style Manager Deletion Design

## Goal

Allow a saved art style to be deleted from the `그림체 관리` view. Deleting a style also deletes every generated-image record and generated image file owned by that style.

## Scope

- Add whole-style deletion only; do not add per-image deletion.
- Keep existing style generation, listing, detail, and Arca archive behavior unchanged.
- Keep the existing `v0.1.0` GitHub release and replace only its `DanbooruArtistRater.exe` asset after verification.

## Backend behavior

Add a store operation that loads all generated image paths for a style, deletes related generation requests, generated-image rows, and the style row in one database transaction, then removes the now-unreferenced files and empty style directory. Database deletion is authoritative; file cleanup is best effort after commit.

Every resolved image path must remain below the configured generated-image root. Missing files are accepted. Paths outside the generated-image root are ignored and never removed. Deleting a missing style returns a not-found result.

Expose the operation as `DELETE /api/art-styles/<style_id>`. A successful response identifies the deleted style, and a missing style returns HTTP 404.

## User interface

Add a `그림체 삭제` button to the selected style detail. Before sending the request, show a confirmation explaining that the generated image is also deleted. On success, reload the style list and reset the detail pane to its empty state. On failure, retain the detail and show the error in the style-manager status area.

## Testing and release

Tests are written before implementation and cover database cascading behavior, safe file cleanup, missing styles, the DELETE API contract, and the style-manager delete interaction. Verification includes the full Python and JavaScript suites, syntax checks, packaging tests, `git diff --check`, and a fresh PyInstaller build.

After verification, commit and push the change, delete the old `DanbooruArtistRater.exe` asset from GitHub release `v0.1.0`, and upload the newly built executable under the same filename.
