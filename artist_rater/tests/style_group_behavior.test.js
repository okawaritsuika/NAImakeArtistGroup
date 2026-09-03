const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  canStartGroupReview,
  filterArtistGalleryImages,
  keyboardAction,
  normalizeArtistTag,
  sourceHasArtist,
  visibleSourcesForArtist,
  newTargetsOnly,
  setTargetSelection,
  sourceGalleryHelp,
  targetCardKeyboardAction,
  nextSourceIndex,
  sourceKey,
  targetPriority,
  baseSourceIndex,
  shouldCloseModalOnBackdrop,
  reviewFocusExpanded,
  artistGallerySizeValue,
  galleryImageLabel,
} = require("../static/style_groups.js");

test("new target selection hides existing source keys without changing ordering", () => {
  const targets = [
    { source_type: "danbooru", source_id: 1 },
    { source_type: "nai_test", source_id: 2 },
  ];
  assert.deepEqual(newTargetsOnly(targets, [{ source_type: "danbooru", source_id: 1 }]), [targets[1]]);
  assert.equal(sourceKey("nai_test", 2), "nai_test:2");
  assert.equal(targetPriority("nai_test", 2, ["danbooru:1", "nai_test:2"]), 2);
});

test("target card selection is deduplicated and reference gestures are explicit", () => {
  const target = { source_type: "nai_test", source_id: 2, label: "긴 테스트 이름" };
  const selected = setTargetSelection([{ source_type: "nai_test", source_id: 1 }], target, true);
  assert.deepEqual(selected.map((item) => item.source_id), [1, 2]);
  assert.deepEqual(setTargetSelection(selected, target, true).map((item) => item.source_id), [1, 2]);
  assert.deepEqual(setTargetSelection(selected, target, false).map((item) => item.source_id), [1]);
  assert.equal(sourceGalleryHelp("reference"), "한 번 클릭하면 옆 큰 미리보기 갱신 · 더블 클릭 기준 선택");
  assert.equal(sourceGalleryHelp("view"), "그림을 클릭하면 옆 큰 미리보기가 갱신됩니다.");
  assert.equal(targetCardKeyboardAction({ key: "Enter" }), "toggle");
  assert.equal(targetCardKeyboardAction({ key: " " }), "toggle");
  assert.equal(targetCardKeyboardAction({ key: "ArrowDown" }), null);
});

test("included artist gallery size is clamped to the card width range", () => {
  assert.equal(artistGallerySizeValue(100), 180);
  assert.equal(artistGallerySizeValue(280), 280);
  assert.equal(artistGallerySizeValue(500), 360);
  assert.equal(galleryImageLabel({ artist_tag: "artist" }, "fallback"), "artist");
  assert.equal(galleryImageLabel({}, "fallback"), "fallback");
});

test("existing groups accept a new source, a new reference, or both but not neither", () => {
  assert.equal(canStartGroupReview({ addingTo: true, selectedSources: [], referenceSelected: false }), false);
  assert.equal(canStartGroupReview({ addingTo: true, selectedSources: [{ source_id: 2 }], referenceSelected: false }), true);
  assert.equal(canStartGroupReview({ addingTo: true, selectedSources: [], referenceSelected: true }), true);
  assert.equal(canStartGroupReview({ addingTo: false, selectedSources: [], referenceSelected: true }), false);
  assert.equal(canStartGroupReview({ addingTo: true, selectedSources: [], referenceSelected: false, baseChanged: true }), true);
});

test("artist matching is normalized and only sources with that artist remain visible", () => {
  assert.equal(normalizeArtistTag("Some__Artist"), "some artist");
  const sources = [
    { source_type: "rating_management", artists: [{ artist_tag: "Some Artist" }], images: [] },
    { source_type: "nai_test", artists: [], images: [{ artist_key: "some artist" }] },
    { source_type: "nai_test", artists: [{ artist_tag: "Other" }], images: [] },
  ];
  assert.equal(sourceHasArtist(sources[0], "some artist"), true);
  assert.deepEqual(visibleSourcesForArtist(sources, "some artist"), [sources[0], sources[1]]);
});

test("current source gallery only contains the current artist", () => {
  const images = [
    { artist_key: "same artist", image_url: "/one" },
    { artist_key: "other artist", image_url: "/two" },
    { artist_tag: "Same_Artist", image_url: "/three" },
  ];
  assert.deepEqual(filterArtistGalleryImages(images, "same_artist").map((image) => image.image_url), ["/one", "/three"]);
});

test("source navigation wraps and backdrop close does not close from panel clicks", () => {
  assert.equal(nextSourceIndex(3, 0, -1), 2);
  assert.equal(nextSourceIndex(3, 2, 1), 0);
  const backdrop = {};
  assert.equal(shouldCloseModalOnBackdrop({ target: backdrop, currentTarget: backdrop }), true);
  assert.equal(shouldCloseModalOnBackdrop({ target: {}, currentTarget: backdrop }), false);
});

test("review starts at the base source even when the API source order differs", () => {
  const sources = [
    { source_type: "nai_test", source_id: 4 },
    { source_type: "rating_management", source_id: "all" },
  ];
  assert.equal(baseSourceIndex(sources, { source_type: "rating_management", source_id: "all" }), 1);
  assert.equal(baseSourceIndex(sources, { source_type: "nai_test", source_id: 99 }), 0);
});

test("review focus uses the workflow default until the user chooses a state", () => {
  assert.equal(reviewFocusExpanded(true, null), true);
  assert.equal(reviewFocusExpanded(false, null), false);
  assert.equal(reviewFocusExpanded(true, false), false);
  assert.equal(reviewFocusExpanded(false, true), true);
});

test("reference selection is not limited to currently selected sources", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/style_groups.js"), "utf8");
  assert.equal(source.includes("if (referenceMode && state.selectedSources.length"), false);
  assert.ok(source.includes('"/api/style-groups/" + group_id + "/reference"') || source.includes("/reference"));
});

test("NAI generation preflight hook is placed before the style-group POST", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/style_groups.js"), "utf8");
  const preflight = source.indexOf("naiArtistTestGenerationPreflight");
  const post = source.indexOf("/generate-first");
  assert.ok(preflight >= 0);
  assert.ok(post > preflight);
});

test("gallery selection updates the same modal preview without a second image modal", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/style_groups.js"), "utf8");
  assert.ok(source.includes("renderGalleryImages"));
  assert.ok(source.includes("updateGalleryPreview"));
  assert.ok(source.includes('setAttribute("aria-pressed", String(selected))'));
  assert.equal(source.includes("styleGroupImageModal"), false);
  assert.equal(source.includes("openLargeImage"), false);
});

test("classification keyboard actions ignore form controls, editable content, and dialogs", () => {
  const ordinary = { tagName: "main", closest: () => null };
  assert.equal(keyboardAction({ key: "ArrowLeft", target: ordinary }), "include");
  assert.equal(keyboardAction({ key: "ArrowDown", target: ordinary }), "next");
  for (const tagName of ["input", "textarea", "select"]) {
    assert.equal(keyboardAction({ key: "ArrowLeft", target: { tagName, closest: () => null } }), null);
  }
  assert.equal(keyboardAction({ key: "ArrowRight", target: { tagName: "div", isContentEditable: true, closest: () => null } }), null);
  assert.equal(keyboardAction({ key: "ArrowRight", target: { tagName: "div", closest: (selector) => selector.includes("role=dialog") } }), null);
});

test("style-group direct artist autocomplete and empty review stages are wired in source", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/style_groups.js"), "utf8");
  assert.ok(source.includes('const directArtist = $("styleGroupDirectArtist");'));
  assert.ok(source.includes("globalThis.promptTagAutocomplete?.bind?.(directArtist)"));
  assert.ok(source.includes('classList.toggle("is-empty", !referenceSrc)'));
  assert.ok(source.includes('classList.toggle("is-empty", !candidateSrc)'));
});
