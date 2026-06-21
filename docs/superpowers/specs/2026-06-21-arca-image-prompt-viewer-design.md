# Arca Image Prompt Viewer Design

## Goal

Let users click an image to inspect that image's prompts without tab buttons, while keeping the archive dialog fully reachable within the viewport.

## Design

- Each style group shows a horizontal row of clickable image thumbnails with a visible selected state.
- The selected image drives three stacked read-only textareas: base, negative, and character prompts.
- Character captions are joined with clear separators and preserve their original text.
- Prompt-type tab buttons and tag-chip comparison panels are removed from the group viewer.
- The dialog header remains fixed; all content below it lives in one vertically scrollable body.
- Existing item editing, delete, save, safe DOM rendering, and responsive behavior remain unchanged.

## Verification

Node tests cover selected-image prompt projection. Frontend contract tests cover the viewer and scroll-body classes. Full existing suites must remain green.
