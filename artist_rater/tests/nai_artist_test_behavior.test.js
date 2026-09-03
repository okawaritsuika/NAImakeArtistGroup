const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
  artistMarkerCount,
  normalizeDelay,
  sortArtistCandidates,
  artistSelectionPayload,
  toggleArtistSelection,
  mergeArtistSelections,
  marqueeAutoScrollDelta,
  isMarqueeDrag,
  marqueeSelectedArtistKeys,
  uniquePreviewImages,
  cyclePreviewIndex,
  cycleResultViewerIndex,
  filterNaiArtistTestResults,
  normalizeHistoryCardSize,
  promptVariantTotal,
  hasPendingGeneration,
  generationEvaluationReady,
  isEvaluationPending,
  settingsExpanded,
  remainingDelayMs,
  activeAwaitingItem,
  preferredInteractiveItem,
  averageScores,
  FULL_CAPACITY_IMAGES,
  isV5Model,
  pendingGenerationCount,
  appendTargetArtists,
  estimateV5Usage,
  usageEstimateForConfig,
  v5AnlasRisk,
  generationControlState,
  startConfirmationPlan,
  naiArtistTestViews,
  deleteConfirmationMessage,
  promptVariantTabs,
  startWarningSummary,
  bindNaiArtistTestPromptAutocomplete,
  isNaiArtistMarkerCursor,
} = require("../static/nai_artist_test.js");

test("NAI artist marker must be exactly one and delay accepts zero or larger finite values", () => {
  assert.equal(artistMarkerCount("{{artist}}, 1girl"), 1);
  assert.equal(artistMarkerCount("{{artist}}, {{artist}}"), 2);
  assert.equal(normalizeDelay("2"), 2);
  assert.equal(normalizeDelay(0), 0);
  assert.equal(normalizeDelay("Infinity"), null);
  assert.equal(normalizeDelay(-1), null);
});

test("NAI prompt fields delegate autocomplete to the shared optional hook", () => {
  const previous = globalThis.promptTagAutocomplete;
  let boundInput = null;
  globalThis.promptTagAutocomplete = { bind(input) { boundInput = input; } };
  const input = {};
  bindNaiArtistTestPromptAutocomplete(input);
  assert.equal(boundInput, input);
  if (previous === undefined) delete globalThis.promptTagAutocomplete;
  else globalThis.promptTagAutocomplete = previous;
});

test("NAI prompt autocomplete treats the artist marker as protected text", () => {
  const input = { value: "before, {{artist}}, after", selectionStart: 13 };
  assert.equal(isNaiArtistMarkerCursor(input), true);
  assert.equal(isNaiArtistMarkerCursor({ ...input, selectionStart: 5 }), false);
  assert.equal(isNaiArtistMarkerCursor({ ...input, selectionStart: 22 }), false);
});

test("NAI dynamic prompt variants keep a field-local autocomplete box and bind immediately", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  const dynamicStart = source.indexOf("function addPromptVariantRow");
  const dynamicEnd = source.indexOf("function readPromptVariants", dynamicStart);
  assert.ok(dynamicStart >= 0 && dynamicEnd > dynamicStart);
  const dynamic = source.slice(dynamicStart, dynamicEnd);
  assert.match(dynamic, /autocomplete\.className = "autocomplete prompt-tag-autocomplete hidden"/);
  assert.match(dynamic, /promptLabel\.append\(promptName, prompt, autocomplete\)/);
  assert.match(dynamic, /bindNaiArtistTestPromptAutocomplete\(prompt\)/);
  assert.match(dynamic, /hideNaiArtistTestPromptAutocomplete\(\)/);
  assert.match(source, /bindNaiArtistTestPromptInputs\(\)/);
  assert.match(source, /naiArtistTestBasePrompt.*naiArtistTestNegativePrompt.*naiArtistTestCharacterPrompts.*naiArtistTestAppendPrompt/s);
});

test("list, editor, and detail are mutually exclusive and selection survives filtering", () => {
  assert.deepEqual(naiArtistTestViews("editor"), { list: false, editor: true, detail: false });
  const candidates = [
    { artist_tag: "zeta", danbooru_score: 3 },
    { artist_tag: "alpha", danbooru_score: 5 },
  ];
  assert.deepEqual(sortArtistCandidates(candidates, "score_desc").map((item) => item.artist_tag), ["alpha", "zeta"]);
  const selected = [{ artist_tag: "zeta", danbooru_score: 3 }];
  assert.deepEqual(artistSelectionPayload(selected), [{ artist_tag: "zeta" }]);
  assert.deepEqual(selected.map((item) => item.artist_tag), ["zeta"]);
});

test("artist cards toggle without losing selected artists outside the current filter", () => {
  const zeta = { artist_tag: "zeta", danbooru_score: 3 };
  const alpha = { artist_tag: "alpha", danbooru_score: 5 };
  const selected = toggleArtistSelection([zeta], alpha);
  assert.deepEqual(selected.map((item) => item.artist_tag), ["zeta", "alpha"]);
  assert.deepEqual(toggleArtistSelection(selected, alpha).map((item) => item.artist_tag), ["zeta"]);
});

test("select all merges the current filtered artists without duplicates", () => {
  const selected = mergeArtistSelections([{ artist_tag: "outside" }, { artist_tag: "alpha" }], [{ artist_tag: "alpha" }, { artist_tag: "beta" }]);
  assert.deepEqual(selected.map((item) => item.artist_tag), ["outside", "alpha", "beta"]);
  assert.deepEqual(mergeArtistSelections(selected, []).map((item) => item.artist_tag), ["outside", "alpha", "beta"]);
});

test("test batch deletion warns about scope and uses a separate card action", () => {
  const message = deleteConfirmationMessage();
  assert.match(message, /테스트 기록·항목·평가가 삭제되며 되돌릴 수 없습니다/);
  assert.match(message, /생성된 이미지 파일과 일반 생성 기록은 삭제되지 않습니다/);
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /event\.stopPropagation\(\)/);
  assert.match(source, /naiArtistTestDeleteDetail/);
});

test("collapsing the generation workspace also minimizes its persistent header", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "../static/style.css"), "utf8");
  assert.match(source, /const workspaceHead = \$\("naiArtistTestWorkspaceHead"\)/);
  assert.match(source, /document\.querySelector\("#naiArtistTestDetailView \.nai-artist-test-workspace-head"\)/);
  assert.match(source, /workspaceHead\.classList\.toggle\("is-collapsed", !expanded\)/);
  assert.match(source, /const detailView = \$\("naiArtistTestDetailView"\)/);
  assert.match(source, /detailView\?\.classList\.toggle\("is-workspace-collapsed", !expanded\)/);
  assert.match(source, /\["naiArtistTestDetailStatus", "naiArtistTestCurrent", "naiArtistTestUsagePreflight"\]/);
  assert.match(source, /summary\.hidden = !expanded/);
  assert.match(source, /summary\.classList\.toggle\("is-workspace-collapsed", !expanded\)/);
  assert.match(css, /\.nai-artist-test-workspace-head\.is-collapsed\s*\{[^}]*height: auto;[^}]*min-height: 44px;/s);
  assert.doesNotMatch(css, /\.nai-artist-test-workspace-head\.is-collapsed\s*\{[^}]*height: 0;/s);
  assert.match(css, /\.nai-artist-test-workspace-head\.is-collapsed button\s*\{[^}]*position: static;/s);
  assert.doesNotMatch(css, /\.nai-artist-test-workspace-head\.is-collapsed button\s*\{[^}]*position: absolute;/s);
  assert.match(css, /\.nai-artist-test-workspace-head\.is-collapsed > div/);
  assert.match(css, /\.nai-artist-test-workspace\.is-collapsed \+ \.nai-artist-test-history-head/);
  assert.match(css, /#naiArtistTestDetailStatus\.is-workspace-collapsed[\s\S]*display: none !important;/);
  assert.match(css, /#naiArtistTestCurrent\.is-workspace-collapsed/);
  assert.match(css, /#naiArtistTestUsagePreflight\.is-workspace-collapsed/);
  assert.match(css, /#naiArtistTestDetailView\.is-workspace-collapsed \.nai-artist-test-results[\s\S]*max-height: none;[\s\S]*overflow: visible;/);
  assert.match(css, /\.nai-artist-test-workspace-head\.is-collapsed h3\s*\{\s*display: none;/);
  assert.match(css, /\.nai-artist-test-workspace-head\.is-collapsed button/);
});

test("marquee selects intersecting cards while preserving the prior selection", () => {
  const cards = [
    { artist_key: "alpha", left: 0, top: 0, right: 50, bottom: 50 },
    { artist_key: "beta", left: 60, top: 0, right: 110, bottom: 50 },
    { artist_key: "gamma", left: 120, top: 0, right: 170, bottom: 50 },
  ];
  assert.equal(isMarqueeDrag(4), false);
  assert.equal(isMarqueeDrag(5), true);
  assert.deepEqual(marqueeSelectedArtistKeys(cards, { left: 45, top: 5, right: 70, bottom: 45 }, ["outside"]), ["outside", "alpha", "beta"]);
});

test("marquee auto-scroll speed supports both viewport edges and stops in the safe zone", () => {
  assert.ok(marqueeAutoScrollDelta(10, 800) < 0);
  assert.ok(marqueeAutoScrollDelta(790, 800) > 0);
  assert.equal(marqueeAutoScrollDelta(400, 800), 0);
});

test("drag completion suppresses its synthetic click", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  assert.match(source, /state\.suppressGalleryClick = true/);
  assert.match(source, /if \(state\.suppressGalleryClick\)/);
});

test("preview images are deduplicated and navigation wraps at both ends", () => {
  const images = uniquePreviewImages({ thumbnail_url: "/thumbnails/artist.png" }, [
    { image_url: "/thumbnails/artist.png" },
    { image_url: "/thumbnails/example.png" },
    { image_url: "/thumbnails/example.png" },
  ]);
  assert.deepEqual(images, ["/thumbnails/artist.png", "/thumbnails/example.png"]);
  assert.equal(cyclePreviewIndex(0, 2, -1), 1);
  assert.equal(cyclePreviewIndex(1, 2, 1), 0);
  assert.equal(cyclePreviewIndex(0, 0, 1), 0);
});

test("image history filters complete images and viewer navigation wraps", () => {
  const items = [
    { id: 1, status: "complete", image_path: "alpha.png", artist_tag: "Alpha", image_score: null },
    { id: 2, status: "complete", image_path: "beta.png", artist_tag: "Beta", image_score: 4 },
    { id: 3, status: "pending", image_path: "pending.png", artist_tag: "Beta", image_score: null },
  ];
  assert.deepEqual(filterNaiArtistTestResults(items).map((item) => item.id), [1, 2]);
  assert.deepEqual(filterNaiArtistTestResults(items, "beta").map((item) => item.id), [2]);
  assert.deepEqual(filterNaiArtistTestResults(items, "", "unrated").map((item) => item.id), [1]);
  assert.deepEqual(filterNaiArtistTestResults(items, "", "4").map((item) => item.id), [2]);
  assert.deepEqual(filterNaiArtistTestResults(items, "", "1"), []);
  assert.equal(cycleResultViewerIndex(0, 2, -1), 1);
  assert.equal(cycleResultViewerIndex(1, 2, 1), 0);
});

test("image history card size accepts the three options and falls back to medium", () => {
  assert.equal(normalizeHistoryCardSize("small"), "small");
  assert.equal(normalizeHistoryCardSize("medium"), "medium");
  assert.equal(normalizeHistoryCardSize("large"), "large");
  assert.equal(normalizeHistoryCardSize("invalid"), "medium");
  assert.equal(normalizeHistoryCardSize(null), "medium");
});

test("prompt tabs and result filters combine prompt, artist, and score criteria", () => {
  const testBatch = { images_per_artist: 1, config: { base_prompt: "{{artist}}", prompt_variants: [{ prompt: "{{artist}}, one" }, { prompt: "{{artist}}, two" }] } };
  assert.deepEqual(promptVariantTabs(testBatch).map((tab) => tab.label), ["전체", "프롬프트 1", "프롬프트 2"]);
  const items = [
    { id: 1, status: "complete", image_path: "a.png", artist_tag: "Alpha", image_score: 4, prompt_index: 0 },
    { id: 2, status: "complete", image_path: "b.png", artist_tag: "Alpha", image_score: 5, prompt_index: 1 },
    { id: 3, status: "complete", image_path: "c.png", artist_tag: "Beta", image_score: 5, prompt_index: 1 },
  ];
  assert.deepEqual(filterNaiArtistTestResults(items, "alpha", "5", 1).map((item) => item.id), [2]);
  assert.deepEqual(filterNaiArtistTestResults(items, "alpha", "all", 0).map((item) => item.id), [1]);
});

test("prompt variant totals multiply per artist and generation phase ignores unrated items", () => {
  assert.equal(promptVariantTotal([{ images_per_artist: 2 }, { images_per_artist: 3 }], 2), 10);
  assert.equal(hasPendingGeneration({ items: [{ status: "complete", image_score: null }, { status: "pending" }] }), true);
  assert.equal(hasPendingGeneration({ items: [{ status: "complete", image_score: null }] }), false);
  assert.equal(generationEvaluationReady({ items: [{ status: "complete", image_score: null }] }), true);
  assert.equal(generationEvaluationReady({ items: [{ status: "complete", image_score: null }, { status: "pending" }] }), false);
  assert.equal(isEvaluationPending({ total_count: 4, generated_count: 4, rated_count: 2 }), true);
  assert.equal(isEvaluationPending({ total_count: 4, generated_count: 4, rated_count: 4 }), false);
  assert.equal(isEvaluationPending({ total_count: 4, generated_count: 3, rated_count: 2 }), false);
});

test("settings expansion helper is reversible", () => {
  assert.equal(settingsExpanded(true), false);
  assert.equal(settingsExpanded(false), true);
  assert.equal(settingsExpanded(false, "expand"), true);
  assert.equal(settingsExpanded(true, "collapse"), false);
});

test("interactive rating helpers find the unrated image and honor generation delay", () => {
  const requested = "2026-08-24T00:00:00.000Z";
  const testBatch = { items: [{ id: 1, status: "complete", image_score: null }, { id: 2, status: "complete", image_score: 4 }] };
  assert.equal(activeAwaitingItem(testBatch).id, 1);
  assert.equal(remainingDelayMs(2, requested, Date.parse(requested) + 500), 1500);
  assert.equal(remainingDelayMs(2, requested, Date.parse(requested) + 2500), 0);
  assert.equal(averageScores([3, 4, "bad"]), 3.5);
});

test("interactive item survives reload and prefers the latest complete image after completion", () => {
  const completed = { status: "completed", items: [
    { id: 11, ordinal: 1, status: "complete", image_score: 3 },
    { id: 12, ordinal: 2, status: "complete", image_score: 4 },
  ] };
  assert.equal(preferredInteractiveItem(completed, 11).id, 11);
  assert.equal(preferredInteractiveItem(completed, null).id, 12);
  const withAwaiting = { ...completed, items: [...completed.items, { id: 13, ordinal: 3, status: "complete", image_score: null }] };
  assert.equal(preferredInteractiveItem(withAwaiting, 11).id, 13);
});

test("V5 usage estimate and Anlas risk remain explicit while V4.5 is not estimated", () => {
  assert.equal(FULL_CAPACITY_IMAGES, 1728);
  assert.equal(isV5Model("nai-diffusion-5-full"), true);
  assert.equal(isV5Model("nai-diffusion-4-5-full"), false);
  const estimate = estimateV5Usage({ usage: { percent: 50 } }, 172, "nai-diffusion-5-full");
  assert.equal(estimate.current_remaining_images, 864);
  assert.equal(estimate.expected_percent, 172 / 1728 * 100);
  assert.equal(estimate.expected_remaining_percent, 50 - (172 / 1728 * 100));
  assert.equal(estimate.expected_remaining_images, 864 - 172);
  assert.equal(estimateV5Usage({ usage: { percent: 50 } }, 172, "nai-diffusion-4-5-full").eligible, false);
  assert.equal(v5AnlasRisk({ model: "nai-diffusion-5-full", steps: 29, width: 832, height: 1216 }), true);
  assert.equal(v5AnlasRisk({ model: "nai-diffusion-5-full", steps: 28, width: 1024, height: 1024 }), false);
});

test("append targets and status controls distinguish resumable cancellation and evaluation phase", () => {
  const items = [{ artist_tag: "a", status: "complete" }, { artist_tag: "b", status: "pending" }, { artist_tag: "b", status: "processing" }];
  assert.deepEqual(appendTargetArtists(items, "all"), ["a", "b"]);
  assert.deepEqual(appendTargetArtists(items, "remaining"), ["b"]);
  assert.equal(pendingGenerationCount({ items }), 2);
  assert.equal(generationControlState({ status: "cancelled", items }).startLabel, "중단된 일괄 생성 재개");
  assert.equal(generationControlState({ status: "cancelled", items }).singleDisabled, false);
  assert.equal(generationControlState({ status: "cancelled", items }).batchDisabled, false);
  assert.equal(generationControlState({ status: "cancelled", items }).startDisabled, false);
  assert.equal(generationControlState({ status: "running", items }).pauseDisabled, false);
  assert.equal(generationControlState({ status: "running", total_count: 1, generated_count: 1, rated_count: 0, items: [{ status: "complete" }] }).startDisabled, true);
});

test("V5 Anlas-risk start requires a second final confirmation", () => {
  const config = { model: "nai-diffusion-5-full", steps: 30, width: 832, height: 1216 };
  const riskEstimate = usageEstimateForConfig({ usage: { percent: 50 } }, 3, config);
  assert.equal(riskEstimate.anlasRisk, true);
  assert.equal(riskEstimate.usageConversion, false);
  assert.match(riskEstimate.message, /Usage 환산 대상 아님/);
  assert.match(riskEstimate.message, /Anlas가 사용될 수 있음/);
  assert.equal(riskEstimate.expected_percent, undefined);
  const plan = startConfirmationPlan(config, riskEstimate, 3);
  assert.equal(plan.requiresFirstConfirm, true);
  assert.equal(plan.requiresFinalConfirm, true);
  assert.match(plan.firstMessage, /Anlas가 사용될 수 있습니다/);
  assert.match(plan.firstMessage, /3장의/);
  assert.match(plan.finalMessage, /최종적으로/);
  assert.equal(startConfirmationPlan({ model: "nai-diffusion-5-full", steps: 28, width: 832, height: 1216 }, {}, 3).requiresFinalConfirm, false);
});

test("batch start warning explains delay, pending work, and usage scope", () => {
  const normal = startWarningSummary({ model: "nai-diffusion-5-full" }, {
    eligible: true, available: true, current_percent: 40, current_remaining_images: 691.2,
    expected_percent: 2 / 1728 * 100, expected_remaining_percent: 40 - 2 / 1728 * 100, expected_remaining_images: 689.2,
  }, 2, 2);
  assert.match(normal, /남은 생성 2장/);
  assert.match(normal, /요청 사이에 2초 딜레이/);
  assert.match(normal, /추정치/);
  const anlas = startWarningSummary({ model: "nai-diffusion-5-full", steps: 29, width: 832, height: 1216 }, { anlasRisk: true, message: "Usage 환산 대상 아님 · Anlas가 사용될 수 있음" }, 3, 1);
  assert.match(anlas, /Anlas가 사용될 수 있음/);
  assert.match(anlas, /3장의 남은 이미지/);
});

test("status controls use one emphasized action for each generation phase", () => {
  const pending = { status: "pending", items: [{ status: "pending" }] };
  const paused = { status: "paused", items: [{ status: "pending" }] };
  const running = { status: "running", items: [{ status: "processing" }] };
  const evaluation = { status: "running", total_count: 1, generated_count: 1, rated_count: 0, items: [{ status: "complete" }] };
  assert.equal(generationControlState(pending).startActive, true);
  assert.equal(generationControlState(pending).pauseActive, false);
  assert.equal(generationControlState(paused).startActive, true);
  assert.equal(generationControlState({ status: "cancelled", items: [{ status: "pending" }] }).startActive, true);
  assert.equal(generationControlState(running).startActive, false);
  assert.equal(generationControlState(running).pauseActive, true);
  assert.equal(generationControlState(evaluation).startActive, false);
  assert.equal(generationControlState(evaluation).pauseActive, false);
  assert.equal(generationControlState(evaluation).statusState, "evaluation");
  assert.equal(generationControlState(pending).singleDisabled, false);
  assert.equal(generationControlState(paused).batchDisabled, false);
  assert.equal(generationControlState(running).singleDisabled, true);
  assert.equal(generationControlState(evaluation).batchDisabled, true);
  assert.equal(generationControlState({ status: "completed", items: [{ status: "complete" }] }).singleDisabled, true);
});

test("single generation uses exactly one next request and pauses remaining work", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  const singleStart = source.indexOf("async function runSingleGeneration");
  const singleEnd = source.indexOf("async function runGenerationLoop", singleStart);
  assert.ok(singleStart >= 0 && singleEnd > singleStart);
  const single = source.slice(singleStart, singleEnd);
  assert.match(single, /confirmGenerationWithUsage\("single"\)/);
  assert.equal((single.match(/const result = await generateNextOnce\(\)/g) || []).length, 1);
  assert.match(single, /\/pause`/);
  assert.doesNotMatch(single, /runGenerationLoop\(/);
  assert.match(source, /naiArtistTestGenerateOne/);
});

test("Anlas and deletion flows use custom modal resolvers instead of native confirm", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/nai_artist_test.js"), "utf8");
  const confirmStart = source.indexOf("async function confirmGenerationWithUsage");
  const confirmEnd = source.indexOf("function renderDetailControls", confirmStart);
  assert.doesNotMatch(source.slice(confirmStart, confirmEnd), /window\.confirm/);
  const deleteStart = source.indexOf("async function deleteTestById");
  const deleteEnd = source.indexOf("function renderListMode", deleteStart);
  assert.doesNotMatch(source.slice(deleteStart, deleteEnd), /window\.confirm/);
  assert.match(source, /openAnlasWarning/);
  assert.match(source, /naiArtistTestAnlasModal/);
  assert.match(source, /naiArtistTestDeleteModal/);
});
