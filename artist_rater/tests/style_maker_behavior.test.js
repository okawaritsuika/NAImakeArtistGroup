const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const styleMakerSource = fs.readFileSync(path.join(__dirname, "../static/style_maker.js"), "utf8");

const {
  CUSTOM_RANGE_FIELDS,
  STYLE_FIXED_ARTISTS_STORAGE_KEY,
  applyStyleRerollResult,
  buildStyleRequestPayload,
  applySharedDependencyReference,
  normalizeStoredFixedStyleArtists,
  saveFixedStyleArtists,
  loadFixedStyleArtists,
  normalizeRandomTargets,
  pickRandomPreset,
  normalizeSelectedScores,
  reorderArtists,
  runLatestStyleRequest,
  sortArtistsByWeight,
  sortFixedArtistEntriesForTable,
  validateCustomRangeValues,
  interpolateWeightProfile,
  formatArtistPromptTag,
  hasProfileDragMoved,
  normalizeStoredPrompts,
  promptStoragePayload,
  combinePromptSections,
  currentPromptTagFragment,
  replaceCurrentPromptTagFragment,
  formatPromptAutocompleteTag,
  bindPromptTagAutocomplete,
  hidePromptTagAutocomplete,
  parsePromptTokens,
  appendUniquePromptToken,
  removePromptToken,
  parseStyleArtistNames,
  parseStyleArtistEntries,
  insertStyleArtistsAtPosition,
  updateStyleArtistAtIndex,
  moveStyleArtistToPosition,
  fixedStyleArtistEntries,
  limitArtistsToTotalCount,
  fixedArtistOverlayCoordinates,
  graphInsertionPositionFromRatio,
  openWeightGraphModal,
  moveSelectedArtistsToPosition,
  fixedArtistSlotEntries,
  chooseArtistsForPrompt,
  STYLE_REQUEST_CONTROL_IDS,
  addPromptGroupItem,
  cleanPromptGroups,
  buildEffectivePromptText,
  promptPresetFullText,
  toggleSelectedStyleId,
  managerCombinedPromptText,
  confirmedGeneratedSourceValues,
  normalizeConfirmedModelName,
  confirmedArtistPromptSignature,
  groupConfirmedImportItems,
  attachConfirmedStyleSuspects,
  filterStyleManagerItems,
  paginateStyleManagerItems,
  normalizeStyleManagerPageSize,
  normalizeRatingTagRules,
  validateRatingTagRules,
  ratingTagRuleCount,
  normalizeRatingExcludeTags,
  validateRatingExcludeTags,
  opusFreeGenerationIssues,
  normalizeComparisonCharacterPrompts,
  normalizeNumericPromptClosers,
  sharedDependencyParameterValue,
  normalizeSharedDependencyRatios,
  sharedDependencyControlsState,
  setSharedDependencyReferenceFromArca,
  clearSharedDependencyReference,
  normalizeStyleHistoryItem,
  styleHistoryArtistPrompt,
  styleHistoryPreviewMeta,
  deleteConfirmationEnabledFromSkip,
  skipDeleteConfirmationFromEnabled,
  normalizeNovelAiModel,
  novelAiModelDefinition,
  novelAiModelDisplayName,
  novelAiModelBadgeClass,
  normalizeNovelAiComplexity,
  novelAiModelFilterMatches,
  novelAiModelFilterMatchesItem,
  normalizeNovelAiUsage,
  formatNovelAiUsageCountdown,
  shouldRefreshNovelAiUsageAfterGeneration,
  normalizeArtistSourceDescriptors,
} = require("../static/style_maker.js");

test("NovelAI model definitions keep V5/V4.5 limits and complexity capability", () => {
  assert.equal(normalizeNovelAiModel("NAID4.5F"), "nai-diffusion-4-5-full");
  assert.equal(normalizeNovelAiModel("NovelAI Diffusion V5 Curated"), "nai-diffusion-5-curated");
  assert.equal(novelAiModelDefinition("nai-diffusion-5-full").maxCharacterPrompts, 22);
  assert.equal(novelAiModelDefinition("nai-diffusion-4-5-full").maxCharacterPrompts, 6);
  assert.equal(normalizeNovelAiComplexity("ultra", "nai-diffusion-5-full"), "ultra");
  assert.equal(normalizeNovelAiComplexity("ultra", "nai-diffusion-4-5-full"), "");
  assert.equal(novelAiModelDisplayName("nai-diffusion-4-5-curated"), "V4.5 Curated");
});

test("model filters distinguish exact, family, and unknown records", () => {
  assert.equal(novelAiModelFilterMatches("nai-diffusion-5-full", "v5"), true);
  assert.equal(novelAiModelFilterMatches("nai-diffusion-4-5-full", "v5"), false);
  assert.equal(novelAiModelFilterMatches("nai-diffusion-4-5-curated", "v4.5"), true);
  assert.equal(novelAiModelFilterMatches("nai-diffusion-4-full", "v4.5"), false);
  assert.equal(novelAiModelFilterMatches("nai-diffusion-3", "v4.5"), false);
  assert.equal(novelAiModelFilterMatches("old-model", "unknown"), true);
  assert.equal(novelAiModelFilterMatches("nai-diffusion-5-full", "nai-diffusion-5-curated"), false);
});

test("shared style manager uses normalized DB generation for V5 source builds", () => {
  const sourceBuild = {
    model: "NovelAI Diffusion V5 4BDE2A90",
    model_id: "",
    model_family: "v5",
    model_generation: "v5",
    model_variant: "unknown",
  };
  assert.equal(novelAiModelFilterMatchesItem(sourceBuild, "v5"), true);
  assert.equal(novelAiModelFilterMatchesItem(sourceBuild, "nai-diffusion-5-full"), false);
  assert.equal(
    novelAiModelFilterMatchesItem(
      { ...sourceBuild, model_id: "nai-diffusion-5-curated", model_variant: "curated" },
      "nai-diffusion-5-curated",
    ),
    true,
  );
});

test("model switching preserves V5 complexity while omitting it for V4.5 requests", () => {
  const selectedComplexity = "high";
  assert.equal(normalizeNovelAiComplexity(selectedComplexity, "nai-diffusion-4-5-full"), "");
  assert.equal(normalizeNovelAiComplexity(selectedComplexity, "nai-diffusion-5-full"), selectedComplexity);
});

test("generated history re-applies direct model, complexity, quality toggle, and optional UC preset fields", () => {
  const direct = normalizeStyleHistoryItem({
    id: 41,
    model: "nai-diffusion-5-full",
    complexity: "ultra",
    quality_toggle: true,
    uc_preset: 3,
  });
  assert.equal(direct.generation_settings.model, "nai-diffusion-5-full");
  assert.equal(direct.generation_settings.complexity, "ultra");
  assert.equal(direct.generation_settings.quality_toggle, true);
  assert.equal(direct.generation_settings.uc_preset, 3);
  assert.match(styleHistoryPreviewMeta(direct), /V5 Full · Complexity ultra/);

  const nested = normalizeStyleHistoryItem({
    id: 42,
    model: "nai-diffusion-4-5-full",
    complexity: "",
    quality_toggle: true,
    generation_settings: {
      model: "nai-diffusion-5-curated",
      complexity: "medium",
      quality_toggle: false,
      uc_preset: 1,
    },
  });
  assert.deepEqual(nested.generation_settings, {
    model: "nai-diffusion-5-curated",
    complexity: "medium",
    quality_toggle: false,
    uc_preset: 1,
  });
});

test("successful V5 generation refreshes usage only when response omits usage", () => {
  assert.equal(shouldRefreshNovelAiUsageAfterGeneration({ model: "nai-diffusion-5-full" }, { image_url: "/x.png" }), true);
  assert.equal(shouldRefreshNovelAiUsageAfterGeneration({ model: "nai-diffusion-5-full" }, { usage: { percent: 12 } }), false);
  assert.equal(shouldRefreshNovelAiUsageAfterGeneration({ model: "nai-diffusion-4-5-full" }, { image_url: "/x.png" }), false);
});

test("history, confirmed, and comparison surfaces attach model badges", () => {
  for (const marker of [
    "appendNovelAiModelBadge(meta, result.model)",
    "appendNovelAiModelBadge(select, item.generation_settings?.model || item.model)",
    "setConfirmedModelValue(source.model || \"\")",
    "appendNovelAiModelBadge(target, item.model)",
    "createNovelAiModelBadge(item.model)",
  ]) {
    assert.ok(styleMakerSource.includes(marker), `missing badge attachment: ${marker}`);
  }
  assert.equal(novelAiModelBadgeClass("nai-diffusion-5-full"), "model-badge-v5-full");
  assert.equal(novelAiModelBadgeClass("nai-diffusion-5-curated"), "model-badge-v5-curated");
  assert.equal(novelAiModelBadgeClass("nai-diffusion-4-5-full"), "model-badge-v4-5-full");
  assert.equal(novelAiModelBadgeClass("nai-diffusion-4-5-curated"), "model-badge-v4-5-curated");
});

test("confirmed and comparison surfaces preserve and expose V5 complexity", () => {
  for (const marker of [
    "styleElement(\"confirmedStyleComplexity\")",
    "confirmedFormValue(\"confirmedStyleComplexity\", source.complexity || \"\")",
    "complexity: normalizeNovelAiComplexity(",
    "comparisonDefaultComplexity",
    "settings.complexity || style.complexity",
  ]) {
    assert.ok(styleMakerSource.includes(marker), `missing complexity connection: ${marker}`);
  }
});

test("NovelAI usage normalizes nested response and formats a browser countdown", () => {
  assert.deepEqual(normalizeNovelAiUsage({ anlas: 321, usage: { percent: 42, timeUntilNextPercent: 3661, isNegative: false } }), {
    percent: 42, seconds: 3661, isNegative: false, available: true, anlas: 321,
  });
  assert.equal(formatNovelAiUsageCountdown(3661), "01:01:01");
});

test("delete confirmation settings use a positive UI value with legacy API inversion", () => {
  assert.equal(deleteConfirmationEnabledFromSkip(false), true);
  assert.equal(deleteConfirmationEnabledFromSkip(true), false);
  assert.equal(deleteConfirmationEnabledFromSkip(undefined), true);
  assert.equal(skipDeleteConfirmationFromEnabled(true), false);
  assert.equal(skipDeleteConfirmationFromEnabled(false), true);
});

test("numeric prompt closers keep weight openers and space numeric tag endings", () => {
  assert.equal(
    normalizeNumericPromptClosers("1.5::artist:matrix16::, 2::year 2025::, -3::clone::"),
    "1.5::artist:matrix16 ::, 2::year 2025 ::, -3::clone::",
  );
});

test("numeric prompt normalizes spaced openers and inserts missing group separators", () => {
  assert.equal(
    normalizeNumericPromptClosers("1.5 ::foo:: 2::bar::"),
    "1.5::foo::, 2::bar::",
  );
});

test("numeric prompt closers space unweighted non-artist numeric tags", () => {
  assert.equal(
    normalizeNumericPromptClosers("year 2025::, clone::"),
    "year 2025 ::, clone::",
  );
});

test("numeric prompt normalization is idempotent and preserves existing separators", () => {
  const prompt = "1.5::foo::, 2::year 2025 ::";
  assert.equal(normalizeNumericPromptClosers(prompt), prompt);
  assert.equal(normalizeNumericPromptClosers(prompt), normalizeNumericPromptClosers(prompt));
});

test("comparison character prompts allow none and normalize separate rows", () => {
  assert.deepEqual(normalizeComparisonCharacterPrompts(null), []);
  assert.deepEqual(
    normalizeComparisonCharacterPrompts([" sakuragi mano, cowboy shot ", "", "asuka langley"]),
    ["sakuragi mano, cowboy shot", "asuka langley"],
  );
});

test("rating tag rules normalize multiple tags and count reserved artists", () => {
  const rules = normalizeRatingTagRules([
    { tag: "dakimakura (medium)", count: 2 },
    { tag: "white_sheet", count: 1 },
  ]);
  assert.deepEqual(rules, [
    { tag: "dakimakura_(medium)", count: 2 },
    { tag: "white_sheet", count: 1 },
  ]);
  assert.equal(ratingTagRuleCount(rules), 3);
  assert.throws(
    () => validateRatingTagRules([...rules, { tag: "WHITE_SHEET", count: 1 }]),
    /같은 태그/,
  );
});

test("rating exclusion tags normalize spaces and reject duplicates", () => {
  assert.deepEqual(
    normalizeRatingExcludeTags(["monochrome", "white sheet"]),
    ["monochrome", "white_sheet"],
  );
  assert.throws(
    () => validateRatingExcludeTags(["white sheet", "WHITE_SHEET"]),
    /같은 태그/,
  );
});

test("Opus free generation warning checks steps and total pixels", () => {
  assert.deepEqual(opusFreeGenerationIssues({ width: 832, height: 1216, steps: 28 }), []);
  assert.equal(opusFreeGenerationIssues({ width: 1024, height: 1024, steps: 28 }).length, 0);
  assert.match(
    opusFreeGenerationIssues({ width: 1024, height: 1024, steps: 29 })[0],
    /28스텝/,
  );
  assert.match(
    opusFreeGenerationIssues({ width: 1280, height: 1024, steps: 28 })[0],
    /1,048,576픽셀/,
  );
});

test("style manager selection toggles ids without mutating the previous set", () => {
  const original = new Set([2]);
  const added = toggleSelectedStyleId(original, 5);
  const removed = toggleSelectedStyleId(added, 2);
  assert.deepEqual([...original], [2]);
  assert.deepEqual([...added], [2, 5]);
  assert.deepEqual([...removed], [5]);
});

test("style manager combines the weighted artist prompt before quality tags", () => {
  const image = {
    artist_prompt: "1.25::artist:sample artist::",
    artists: [{ artist: "sample_artist", weight: 1.25 }],
    base_prompt: "masterpiece, best quality",
    character_prompts: ["1girl", "blue eyes"],
    negative_prompt: "lowres",
  };
  assert.equal(
    managerCombinedPromptText(image),
    "1.25::artist:sample artist::, masterpiece, best quality",
  );
});

test("generated style confirmation keeps its image and generation settings", () => {
  const source = confirmedGeneratedSourceValues({
    id: 12,
    image_url: "/generated/4/sample.png",
    artists: [{ artist: "sample_artist", weight: 1.25 }],
    quality_prompt: "very aesthetic",
    negative_prompt: "lowres",
    sampler: "k_euler_ancestral",
    noise_schedule: "karras",
    steps: 28,
    scale: 5,
    cfg_rescale: 0.2,
    variety_plus: true,
    model: "nai-diffusion-4-5-full",
  });

  assert.equal(source.image_url, "/generated/4/sample.png");
  assert.equal(source.sampler, "k_euler_ancestral");
  assert.equal(source.noise_schedule, "karras");
  assert.equal(source.steps, 28);
  assert.equal(source.scale, 5);
  assert.equal(source.cfg_rescale, 0.2);
  assert.equal(source.variety_plus, true);
  assert.equal(source.model, "nai-diffusion-4-5-full");
  assert.equal(source.artist_prompt, "1.25::artist:sample artist::");
});

test("style history normalizes generated prompts and generation settings with legacy fallbacks", () => {
  const item = normalizeStyleHistoryItem({
    id: 7,
    image_url: "/generated/7/image.png",
    artist_prompt: "1.25::artist:sample artist::",
    base_prompt: "masterpiece",
    fixed_prompt: "upper body",
    character_prompts: [{ prompt: "1girl" }, "blue eyes"],
    width: 832,
    height: 1216,
    sampler: "karras",
    noise_schedule: "karras",
    steps: 28,
    scale: 5,
    cfg_rescale: 0,
  });
  assert.deepEqual(item.artists, [{ artist: "sample artist", weight: 1.25 }]);
  assert.equal(item.base_prompt, "masterpiece");
  assert.deepEqual(item.character_prompts, ["1girl", "blue eyes"]);
  assert.deepEqual(item.generation_settings, {
    width: 832,
    height: 1216,
    resolution_preset: "832x1216",
    sampler: "karras",
    scheduler: "karras",
    steps: 28,
    scale: 5,
    cfg_rescale: 0,
  });
});

test("style history prefers explicit generation settings and falls back from empty quality prompts", () => {
  const item = normalizeStyleHistoryItem({
    quality_prompt: "",
    base_prompt: "legacy quality",
    width: 1024,
    height: 1024,
    noise_schedule: "native",
    generation_settings: {
      width: 1216,
      height: 832,
      resolution_preset: "1216x832",
      scheduler: "karras",
      scale: 7,
    },
  });
  assert.equal(item.base_prompt, "legacy quality");
  assert.equal(item.generation_settings.width, 1216);
  assert.equal(item.generation_settings.height, 832);
  assert.equal(item.generation_settings.resolution_preset, "1216x832");
  assert.equal(item.generation_settings.scheduler, "karras");
  assert.equal(item.generation_settings.scale, 7);
});

test("style history preview metadata uses the generated image id and normalized settings", () => {
  const meta = styleHistoryPreviewMeta({
    id: 11,
    artists: [{ artist: "sample", weight: 1 }],
    width: 832,
    height: 1216,
    sampler: "k_euler_ancestral",
    noise_schedule: "karras",
    steps: 28,
    scale: 5,
    cfg_rescale: 0,
    seed: 123,
  });
  assert.match(meta, /생성 #11/);
  assert.match(meta, /작가 1명/);
  assert.match(meta, /832×1216/);
  assert.match(meta, /Seed 123/);
});

test("style history artist preview prefers the stored prompt and reconstructs a fallback", () => {
  assert.equal(
    styleHistoryArtistPrompt({
      artist_prompt: "  1.25::artist:stored artist::  ",
      artists: [{ artist: "ignored", weight: 1 }],
    }),
    "1.25::artist:stored artist::",
  );
  assert.equal(
    styleHistoryArtistPrompt(normalizeStyleHistoryItem({
      artists: [
        { artist: "first_artist", weight: 1.2 },
        { artist: "second", weight: 0.8 },
      ],
    })),
    "1.2::artist:first artist::, 0.8::artist:second::",
  );
  assert.equal(styleHistoryArtistPrompt(null), "");
});

test("shared dependency reference is sent only for weight rerolls", () => {
  const base = {
    weight_mode: "shared_dependency",
    shared_dependency_source_ratios: { fixed: 0, reference: 100, rated: 0, other_shared: 0 },
  };
  assert.deepEqual(
    applySharedDependencyReference(base, "weights", "shared_dependency", 17),
    { ...base, shared_dependency_reference_id: 17 },
  );
  for (const reroll of ["all", "artists"]) {
    assert.deepEqual(applySharedDependencyReference({ ...base, shared_dependency_reference_id: 17 }, reroll, "shared_dependency", 17), base);
  }
  assert.deepEqual(applySharedDependencyReference(base, "weights", "balanced", 17), base);
});

test("fixed shared dependency references are sent for artist and all rerolls while random mode omits them", () => {
  const base = { weight_mode: "shared_dependency" };
  assert.deepEqual(
    applySharedDependencyReference(base, "all", "shared_dependency", 21, "fixed"),
    { ...base, shared_dependency_reference_mode: "fixed", shared_dependency_reference_id: 21 },
  );
  assert.deepEqual(
    applySharedDependencyReference(base, "artists", "shared_dependency", 21, "fixed"),
    { ...base, shared_dependency_reference_mode: "fixed", shared_dependency_reference_id: 21 },
  );
  assert.deepEqual(
    applySharedDependencyReference(base, "all", "shared_dependency", 21, "random"),
    { ...base, shared_dependency_reference_mode: "random" },
  );
  assert.deepEqual(
    applySharedDependencyReference(base, "weights", "shared_dependency", 21, "random"),
    { ...base, shared_dependency_reference_mode: "random", shared_dependency_reference_id: 21 },
  );
});

test("arca reference confirmation provides a valid fixed reference", () => {
  assert.equal(
    setSharedDependencyReferenceFromArca(
      { id: 37, title: "selected", base_prompt: "artist:sample" },
      { title: "source" },
    ),
    true,
  );
});

test("clearing a fixed shared dependency reference returns to random without a stale payload id", () => {
  const cleared = clearSharedDependencyReference();
  assert.equal(cleared.shared_dependency_reference_mode, "random");
  assert.equal(cleared.shared_dependency_reference_id, null);
  assert.equal(cleared.shared_dependency_reference, null);
  assert.equal(cleared.shared_dependency_scale, null);
  assert.equal(cleared.shared_dependency_cfg_rescale, null);
  assert.deepEqual(
    applySharedDependencyReference(
      { weight_mode: "shared_dependency" },
      "all",
      "shared_dependency",
      cleared.shared_dependency_reference_id,
      cleared.shared_dependency_reference_mode,
    ),
    { weight_mode: "shared_dependency", shared_dependency_reference_mode: "random" },
  );
});

test("shared dependency ratios use one canonical four-source payload", () => {
  assert.deepEqual(normalizeSharedDependencyRatios({ fixed: 0, reference: 100, rated: 0, other_shared: 0 }), {
    fixed: 0, reference: 100, rated: 0, other_shared: 0,
  });
  assert.throws(() => normalizeSharedDependencyRatios({ fixed: 0, reference: 50, rated: 0, other_shared: 0 }), /합/);
  assert.throws(() => normalizeSharedDependencyRatios({ fixed: "50", reference: 50, rated: 0, other_shared: 0 }), /정수/);
});

test("shared dependency disables the user artist count and legacy shared range", () => {
  assert.deepEqual(sharedDependencyControlsState("shared_dependency"), {
    countDisabled: true,
    sharedMinMaxDisabled: true,
    countLabel: "기준 그림체 작가 수 사용",
  });
  assert.equal(sharedDependencyControlsState("balanced").countDisabled, false);
});

test("shared dependency generation metadata treats missing values as fallback but accepts zero", () => {
  assert.equal(sharedDependencyParameterValue(null, 0, 10), null);
  assert.equal(sharedDependencyParameterValue(undefined, 0, 1), null);
  assert.equal(sharedDependencyParameterValue("", 0, 1), null);
  assert.equal(sharedDependencyParameterValue(0, 0, 10), 0);
  assert.equal(sharedDependencyParameterValue("0", 0, 1), 0);
  assert.equal(sharedDependencyParameterValue("not-a-number", 0, 1), null);
});

test("confirmed imports group exact weighted artist prompts and separate unknown prompts", () => {
  assert.equal(
    confirmedArtistPromptSignature("1.20::artist:Same Artist::"),
    confirmedArtistPromptSignature("  1.2 :: artist:Same   Artist::  "),
  );
  const groups = groupConfirmedImportItems([
    { file: "a", metadata: { artist_prompt: "1.2::artist:same artist::" } },
    { file: "b", metadata: { artist_prompt: "1.2::artist:same   artist::" } },
    { file: "c", metadata: { artist_prompt: "0.8::artist:other::" } },
    { file: "d", metadata: { artist_prompt: "" } },
    { file: "e", metadata: { artist_prompt: "" } },
  ]);
  assert.deepEqual(groups.map((group) => group.items.map((item) => item.file)), [
    ["a", "b"], ["c"], ["d"], ["e"],
  ]);
});

test("confirmed style models preserve ambiguous NovelAI build labels", () => {
  assert.equal(
    normalizeConfirmedModelName("NovelAI Diffusion V4.5 4BDE2A90"),
    "NovelAI Diffusion V4.5 4BDE2A90"
  );

  assert.equal(
    normalizeConfirmedModelName("NovelAI Diffusion V4.5"),
    "NovelAI Diffusion V4.5"
  );

  assert.equal(
    normalizeConfirmedModelName("NovelAI Diffusion V4.5 Curated"),
    "NovelAI Diffusion V4.5 Curated"
  );

  assert.equal(
    normalizeConfirmedModelName("NovelAI Diffusion V5 4BDE2A90"),
    "NovelAI Diffusion V5 4BDE2A90"
  );

  assert.equal(
    normalizeConfirmedModelName("nai-diffusion-5-curated"),
    "NovelAI Diffusion V5 Curated"
  );
});

test("confirmed imports flag every existing style with the same weighted artist prompt", () => {
  const groups = groupConfirmedImportItems([
    { file: "new", metadata: { artist_prompt: "1.20::artist:same artist::" } },
    { file: "unknown", metadata: { artist_prompt: "" } },
  ]);
  const result = attachConfirmedStyleSuspects(groups, [
    { id: 7, artist_prompt: "1.2 :: artist:same   artist::" },
    { id: 8, artist_prompt: "1.20::artist:same artist::" },
    { id: 9, artist_prompt: "0.8::artist:other::" },
  ]);

  assert.deepEqual(result[0].suspectedStyles.map((style) => style.id), [7, 8]);
  assert.deepEqual(result[1].suspectedStyles, []);
});

test("style manager filters each gallery mode and sorts visible cards", () => {
  const generated = [
    { id: 1, created_at: "2026-01-01", confirmed: false, artists: [{ artist: "alpha" }] },
    { id: 2, created_at: "2026-01-02", confirmed: true, artists: [{ artist: "beta" }] },
  ];
  assert.deepEqual(
    filterStyleManagerItems(generated, "generated", { query: "beta", scope: "confirmed", sort: "newest" }).map((item) => item.id),
    [2],
  );
  const confirmed = [
    { id: 3, updated_at: "2026-01-03", source_type: "manual", name: "직접 보관" },
    { id: 4, updated_at: "2026-01-04", source_type: "shared", name: "공유 보관" },
  ];
  assert.deepEqual(
    filterStyleManagerItems(confirmed, "confirmed", { scope: "shared", sort: "oldest" }).map((item) => item.id),
    [4],
  );
});

test("style manager pagination slices generated and confirmed records", () => {
  assert.deepEqual(
    paginateStyleManagerItems([{ id: 1 }, { id: 2 }, { id: 3 }], 2, 2).map((item) => item.id),
    [3],
  );
});

test("style manager accepts only supported page sizes", () => {
  assert.equal(normalizeStyleManagerPageSize("48"), 48);
  assert.equal(normalizeStyleManagerPageSize("13"), 24);
});

test("continuous random targets migrate old settings and keep four independent toggles", () => {
  assert.deepEqual(normalizeRandomTargets(null, "weights"), ["weights"]);
  assert.deepEqual(normalizeRandomTargets(null, "artists_and_weights"), ["artists", "weights"]);
  assert.deepEqual(
    normalizeRandomTargets(["negative", "weights", "unknown", "quality"]),
    ["weights", "quality", "negative"],
  );
  const presets = [{ key: "a" }, { key: "b" }, { key: "c" }];
  assert.equal(pickRandomPreset(presets, 0).key, "a");
  assert.equal(pickRandomPreset(presets, 0.99).key, "c");
});

test("excluded prompt tags can be restored once without duplication", () => {
  assert.equal(
    appendUniquePromptToken("masterpiece, soft lighting", "1girl"),
    "masterpiece, soft lighting, 1girl",
  );
  assert.equal(
    appendUniquePromptToken("masterpiece, 1girl", "1girl"),
    "masterpiece, 1girl",
  );
});

test("base prompt tags can move to the excluded list without changing other tags", () => {
  assert.equal(
    removePromptToken("masterpiece, best quality, 1.2::amazing quality::", "best quality"),
    "masterpiece, 1.2::amazing quality::",
  );
  assert.equal(
    removePromptToken("masterpiece, MASTERPIECE, best quality", "masterpiece"),
    "best quality",
  );
});

test("prompt storage keeps one normalized snapshot", () => {
  assert.deepEqual(
    promptStoragePayload(" base ", " negative ", [" char one ", "", " char two "]),
    {
      base_prompt: " base ",
      fixed_prompt: "",
      leading_prompt: "",
      negative_prompt: " negative ",
      character_prompts: [" char one ", "", " char two "],
      character_prompt_ids: ["character-1", "character-2", "character-3"],
      prompt_groups: [],
      generation_settings: {},
    },
  );
  assert.deepEqual(
    normalizeStoredPrompts({ base_prompt: "base", negative_prompt: "neg", character_prompts: ["a", 3, "b"] }),
    {
      base_prompt: "base",
      fixed_prompt: "",
      leading_prompt: "",
      negative_prompt: "neg",
      character_prompts: ["a", "b"],
      character_prompt_ids: ["character-1", "character-2"],
      prompt_groups: [],
      generation_settings: {},
    },
  );
  assert.deepEqual(normalizeStoredPrompts(null), {
    base_prompt: "",
    fixed_prompt: "",
    leading_prompt: "",
    negative_prompt: "",
    character_prompts: [""],
    character_prompt_ids: ["character-1"],
    prompt_groups: [],
    generation_settings: {},
  });
});

test("fixed prompt tags persist separately and follow quality tags", () => {
  const stored = promptStoragePayload(
    "masterpiece",
    "lowres",
    ["1girl"],
    ["hero"],
    [],
    {},
    "upper body, white sheet",
  );

  assert.equal(stored.fixed_prompt, "upper body, white sheet");
  assert.equal(normalizeStoredPrompts(stored).fixed_prompt, "upper body, white sheet");
  assert.equal(
    combinePromptSections(stored.base_prompt, stored.fixed_prompt),
    "masterpiece, upper body, white sheet",
  );
  assert.equal(combinePromptSections("", "white sheet"), "white sheet");
});

test("artist source descriptors reject empty, duplicate, and unknown sources", () => {
  assert.deepEqual(
    normalizeArtistSourceDescriptors([], { allowEmpty: true }),
    [],
  );
  assert.throws(
    () => normalizeArtistSourceDescriptors([]),
    /하나 이상/,
  );
  assert.throws(
    () => normalizeArtistSourceDescriptors([
      { source_type: "nai_test", source_id: "12" },
      { source_type: "nai_test", source_id: "12" },
    ]),
    /중복/,
  );
  assert.throws(
    () => normalizeArtistSourceDescriptors([{ source_type: "unknown", source_id: "1" }]),
    /확인/,
  );
});

test("style maker request payload carries artist source descriptors", () => {
  const artistSources = [
    { source_type: "rating_management", source_id: "all" },
    { source_type: "style_group", source_id: "4" },
  ];
  const payload = buildStyleRequestPayload(
    { count: 1, artist_sources: artistSources },
    [],
    "all",
  );

  assert.deepEqual(payload.artist_sources, artistSources);
});

test("toggling a source loads its focused detail through the cached loader", () => {
  const start = styleMakerSource.indexOf("function toggleArtistSource");
  const end = styleMakerSource.indexOf("function focusArtistSource", start);
  const toggleSource = styleMakerSource.slice(start, end);
  assert.match(toggleSource, /loadArtistSourceDetail\(source\)/);
  assert.match(
    styleMakerSource.slice(end, styleMakerSource.indexOf("function renderArtistSourceList", end)),
    /if \(load\) void loadArtistSourceDetail\(source\)/,
  );
});

test("leading prompt persists and is placed before artist and base sections", () => {
  const stored = promptStoragePayload("quality", "negative", ["character"], [], [], {}, "fixed", "style prefix");
  assert.equal(stored.leading_prompt, "style prefix");
  assert.equal(normalizeStoredPrompts({ base_prompt: "quality" }).leading_prompt, "");
  assert.ok(styleMakerSource.includes("leading_prompt: leadingPrompt"));
});

test("fixed prompt autocomplete searches and replaces only the tag at the caret", () => {
  assert.equal(currentPromptTagFragment("upper_body, white sh", 20), "white_sh");
  assert.equal(currentPromptTagFragment("upper_body, wh sheet, solo", 14), "wh");
  assert.deepEqual(
    replaceCurrentPromptTagFragment("upper_body, wh sheet, solo", "white_sheet", 14),
    { value: "upper_body, white_sheet, solo", cursor: 23 },
  );
  assert.deepEqual(
    replaceCurrentPromptTagFragment("upper_body,\n  wh", "white_sheet", 16),
    { value: "upper_body,\n  white_sheet", cursor: 25 },
  );
});

test("prompt autocomplete prefixes artist tags only in prompt fields", () => {
  assert.equal(formatPromptAutocompleteTag({ name: "some_artist", category: 1 }), "artist:some artist");
  assert.equal(formatPromptAutocompleteTag({ name: "artist_123", category: 1 }), "artist:artist 123 ");
  assert.equal(formatPromptAutocompleteTag({ name: "white_sheet", category: 0 }), "white sheet");
  assert.equal(formatPromptAutocompleteTag({ name: "some_character", category: 4 }), "some character");
  assert.equal(formatPromptAutocompleteTag({ name: "some_artist", category: 1 }, false), "some artist");
});

test("prompt autocomplete exposes a reusable global API and category-aware query path", () => {
  assert.equal(globalThis.promptTagAutocomplete.bind, bindPromptTagAutocomplete);
  assert.equal(globalThis.promptTagAutocomplete.hide, hidePromptTagAutocomplete);
  assert.match(styleMakerSource, /input\.dataset\.autocompleteCategory/);
  assert.match(styleMakerSource, /\$\{categoryQuery\}/);
  assert.ok(styleMakerSource.includes("/^\\{\\{\\s*artist\\s*\\}\\}$/i"));
});

test("prompt storage preserves generation settings from the website", () => {
  const stored = promptStoragePayload(
    "base",
    "negative",
    ["character"],
    ["hero"],
    [],
    { scheduler: "karras", width: 832, height: 1216, seed_fixed: true },
  );

  assert.deepEqual(stored.generation_settings, {
    scheduler: "karras",
    width: 832,
    height: 1216,
    seed_fixed: true,
  });
  assert.equal(normalizeStoredPrompts(stored).generation_settings.scheduler, "karras");
});

test("prompt tokens preserve order and ignore empty comma entries", () => {
  assert.deepEqual(parsePromptTokens("masterpiece, best quality,, {blue eyes:1.2}"), [
    "masterpiece",
    "best quality",
    "{blue eyes:1.2}",
  ]);
});

test("prompt groups reject duplicate references and clean stale tokens", () => {
  const group = { id: "group-1", name: "quality", enabled: true, expanded: true, items: [] };
  const item = { field: "base", character_id: "", token: "masterpiece" };
  assert.equal(addPromptGroupItem(group, item), true);
  assert.equal(addPromptGroupItem(group, item), false);
  const cleaned = cleanPromptGroups([group], {
    base_prompt: "best quality",
    negative_prompt: "",
    character_prompts: [],
    character_prompt_ids: [],
  });
  assert.deepEqual(cleaned[0].items, []);
});

test("disabled groups remove referenced tokens without changing remaining order", () => {
  const groups = [{
    id: "group-1",
    name: "quality",
    enabled: false,
    expanded: true,
    items: [{ field: "base", character_id: "", token: "best quality" }],
  }];
  assert.equal(
    buildEffectivePromptText("masterpiece, best quality, solo", "base", "", groups),
    "masterpiece, solo",
  );
});

test("profile point interaction distinguishes a click from a drag", () => {
  assert.equal(hasProfileDragMoved(100, 100, 101, 102), false);
  assert.equal(hasProfileDragMoved(100, 100, 104, 100), true);
});

test("artist prompt tags replace underscores and separate numeric endings", () => {
  assert.equal(formatArtistPromptTag("some_artist"), "some artist");
  assert.equal(formatArtistPromptTag("artist_123"), "artist 123 ");
});

test("manual style artist entry accepts multiple names without duplicates", () => {
  assert.deepEqual(
    parseStyleArtistNames("alpha, beta\nalpha  \n  gamma"),
    ["alpha", "beta", "gamma"],
  );
});

test("manual style artist entry accepts weighted NovelAI artist prompt lists", () => {
  const entries = parseStyleArtistEntries(
    "0.1::artist:kittew::, 0.4::artist:patzzi::, 0.78::artist:kawacy::, 1.13::artist:chomikuplus::, 1.6::artist:miito (meeeeton333)::, 1.94::artist:weiyan (nbnbmwnl)::, 2.3::artist:sadamoto yoshiyuki::",
  );
  assert.deepEqual(entries, [
    { artist: "kittew", weight: 0.1 },
    { artist: "patzzi", weight: 0.4 },
    { artist: "kawacy", weight: 0.78 },
    { artist: "chomikuplus", weight: 1.13 },
    { artist: "miito (meeeeton333)", weight: 1.6 },
    { artist: "weiyan (nbnbmwnl)", weight: 1.94 },
    { artist: "sadamoto yoshiyuki", weight: 2.3 },
  ]);
  assert.deepEqual(
    insertStyleArtistsAtPosition([], entries, { position: 1, weight: 1 })
      .map(({ artist, weight, slot }) => ({ artist, weight, slot })),
    entries.map((entry, index) => ({ ...entry, slot: index + 1 })),
  );
  assert.equal(chooseArtistsForPrompt(insertStyleArtistsAtPosition([], entries, { position: 1 })).length, 7);
});

test("prompt preset detail shows edited quality followed by every excluded tag", () => {
  assert.equal(
    promptPresetFullText({
      base_prompt: "best quality",
      excluded_tags: [
        { tag: "1girl", prompt: "1girl" },
        { tag: "blue eyes", prompt: "1.2::blue eyes::" },
      ],
    }, "edited quality, cinematic lighting"),
    "edited quality, cinematic lighting, 1girl, 1.2::blue eyes::",
  );
});

test("manual artist parser handles grouped weights, spaced delimiters, and adjacent blocks", () => {
  const entries = parseStyleArtistEntries(
    "0.37::artist:yd (orange maru):: 1.8 ::artist:null (nyanpyoun), pottsness, ciloranko:: 0.7::artist:freng, wow (cor369), tianliang duohe fangdongye:: year 2024 ::, 0.55::artist:horikoshi kouhei::",
  );
  assert.deepEqual(entries, [
    { artist: "yd (orange maru)", weight: 0.37 },
    { artist: "null (nyanpyoun)", weight: 1.8 },
    { artist: "pottsness", weight: 1.8 },
    { artist: "ciloranko", weight: 1.8 },
    { artist: "freng", weight: 0.7 },
    { artist: "wow (cor369)", weight: 0.7 },
    { artist: "tianliang duohe fangdongye", weight: 0.7 },
    { artist: "horikoshi kouhei", weight: 0.55 },
  ]);
  assert.deepEqual(
    insertStyleArtistsAtPosition([], entries, { position: 2 }).map((item) => item.slot),
    [2, 3, 4, 5, 6, 7, 8, 9],
  );
});

test("manual style artists insert at a one-based prompt position", () => {
  const current = [
    { artist: "first", weight: 0.4 },
    { artist: "last", weight: 2.0 },
  ];
  const added = insertStyleArtistsAtPosition(current, ["new_a", "new_b"], {
    position: 2,
    weight: 1.25,
  });

  assert.deepEqual(added, [
    { artist: "first", weight: 0.4 },
    { artist: "new_a", weight: 1.25, fixed: true, slot: 2 },
    { artist: "new_b", weight: 1.25, fixed: true, slot: 3 },
    { artist: "last", weight: 2.0 },
  ]);
  assert.deepEqual(current.map((item) => item.artist), ["first", "last"]);
});

test("manual artists with the same slot stack and choose one prompt candidate", () => {
  const added = [
    { artist: "new_a", weight: 1.25, fixed: true, slot: 1 },
    { artist: "new_b", weight: 1.25, fixed: true, slot: 1 },
  ];

  assert.deepEqual(
    fixedArtistSlotEntries(added).map(({ artist, slot, stackIndex, stackSize }) => [artist.artist, slot, stackIndex, stackSize]),
    [["new_a", 1, 0, 2], ["new_b", 1, 1, 2]],
  );
  assert.deepEqual(
    chooseArtistsForPrompt(added, () => 0.1).map((item) => item.artist),
    ["new_a"],
  );
  assert.deepEqual(
    chooseArtistsForPrompt(added, () => 0.9).map((item) => item.artist),
    ["new_b"],
  );
});

test("manual artist random weight and zero position are resolved for each prompt", () => {
  const added = insertStyleArtistsAtPosition(
    [{ artist: "first", weight: 0.4 }, { artist: "last", weight: 2.0 }],
    ["random_fixed"],
    { position: 0, weight: 1.25, randomWeight: true },
  );
  assert.deepEqual(added[0], {
    artist: "random_fixed", weight: 1.25, fixed: true, slot: 0, random_weight: true,
  });

  const values = [0.9, 0.5];
  const promptArtists = chooseArtistsForPrompt(added, () => values.shift(), { minWeight: 0.1, maxWeight: 0.2 });
  assert.deepEqual(promptArtists.map((item) => item.artist), ["first", "last", "random_fixed"]);
  assert.equal(promptArtists[2].weight, 0.15);
  assert.equal(added[0].weight, 1.25);
});

test("profile weights follow the final randomized order for random and zero-slot artists", () => {
  const artists = [
    { artist: "random_a", weight: 0.4 },
    { artist: "zero_a", weight: 0.8, fixed: true, slot: 0 },
    { artist: "zero_b", weight: 1.2, fixed: true, slot: 0 },
  ];
  const profile = [
    { position: 0, weight: 0.2 },
    { position: 1, weight: 2.0 },
  ];
  const randomOrder = chooseArtistsForPrompt(artists, () => 0, { profile });
  const alternateOrder = chooseArtistsForPrompt(artists, () => 0.99, { profile });

  assert.deepEqual(randomOrder.map((item) => item.artist), ["zero_b", "zero_a", "random_a"]);
  assert.deepEqual(randomOrder.map((item) => item.weight), [0.2, 1.1, 2]);
  assert.notDeepEqual(alternateOrder.map((item) => item.artist), randomOrder.map((item) => item.artist));
  assert.deepEqual(artists, [
    { artist: "random_a", weight: 0.4 },
    { artist: "zero_a", weight: 0.8, fixed: true, slot: 0 },
    { artist: "zero_b", weight: 1.2, fixed: true, slot: 0 },
  ]);
});

test("profile prioritizes slot zero while positioned fixed random weights stay random", () => {
  const artists = [
    { artist: "random_a", weight: 0.4 },
    { artist: "fixed_a", weight: 1.4, fixed: true, slot: 1, random_weight: true },
    { artist: "random_fixed", weight: 1.1, fixed: true, slot: 0, random_weight: true },
  ];
  const profile = [
    { position: 0, weight: 0.2 },
    { position: 1, weight: 2.0 },
  ];
  const values = [0.5, 0.5, 0.5];
  const prompt = chooseArtistsForPrompt(artists, () => values.shift(), {
    profile,
    minWeight: 0.1,
    maxWeight: 0.3,
  });

  assert.deepEqual(prompt.map((item) => item.artist), ["random_a", "random_fixed", "fixed_a"]);
  assert.deepEqual(prompt.map((item) => item.weight), [0.2, 1.1, 0.2]);
  assert.equal(
    chooseArtistsForPrompt(
      [{ artist: "fixed_manual", weight: 1.4, fixed: true, slot: 1 }],
      () => 0.5,
      { profile },
    )[0].weight,
    1.4,
  );
});

test("profile prompt weights round interpolated positions to two decimals", () => {
  const prompt = chooseArtistsForPrompt([
    { artist: "artist_a", weight: 0.1 },
    { artist: "artist_b", weight: 0.2 },
    { artist: "artist_c", weight: 0.3 },
    { artist: "artist_d", weight: 0.4 },
  ], () => 0, {
    profile: [
      { position: 0, weight: 0.1 },
      { position: 1, weight: 2.3 },
    ],
  });

  assert.deepEqual(prompt.map((item) => item.weight), [0.1, 0.83, 1.57, 2.3]);
});

test("manual style artists promote existing random artists into fixed rows", () => {
  const current = [
    { artist: "first", score: 5, weight: 0.4 },
    { artist: "random_existing", score: 4, weight: 0.8 },
    { artist: "last", score: 3, weight: 2.0 },
  ];
  const added = insertStyleArtistsAtPosition(current, ["random_existing"], {
    position: 1,
    weight: 1.35,
  });

  assert.deepEqual(added, [
    { artist: "random_existing", score: 4, weight: 1.35, fixed: true, slot: 1 },
    { artist: "first", score: 5, weight: 0.4 },
    { artist: "last", score: 3, weight: 2.0 },
  ]);
  assert.deepEqual(
    fixedStyleArtistEntries(added).map((entry) => [entry.index, entry.artist.artist]),
    [[0, "random_existing"]],
  );
  assert.deepEqual(current.map((item) => item.artist), ["first", "random_existing", "last"]);
});

test("manual style artist rows expose only fixed artists with original indexes", () => {
  const artists = [
    { artist: "random_a", weight: 0.4 },
    { artist: "fixed_a", weight: 1.2, fixed: true },
    { artist: "random_b", weight: 0.8 },
    { artist: "fixed_b", weight: 1.5, fixed: true },
  ];

  assert.deepEqual(
    fixedStyleArtistEntries(artists).map((entry) => [entry.index, entry.artist.artist]),
    [[1, "fixed_a"], [3, "fixed_b"]],
  );
});

test("manual fixed artist controls stay usable while style requests are pending", () => {
  assert.equal(STYLE_REQUEST_CONTROL_IDS.includes("styleArtistSearch"), false);
  assert.equal(STYLE_REQUEST_CONTROL_IDS.includes("styleArtistSelect"), false);
  assert.equal(STYLE_REQUEST_CONTROL_IDS.includes("styleArtistPosition"), false);
  assert.equal(STYLE_REQUEST_CONTROL_IDS.includes("styleArtistWeight"), false);
  assert.equal(STYLE_REQUEST_CONTROL_IDS.includes("addStyleArtist"), false);
});

test("manual fixed style artist rows can edit artist, weight, and position", () => {
  const current = [
    { artist: "first", weight: 0.4 },
    { artist: "middle", weight: 1.0, fixed: true },
    { artist: "last", weight: 2.0 },
  ];

  assert.deepEqual(
    updateStyleArtistAtIndex(current, 1, { artist: "renamed", weight: 1.25 }),
    [
      { artist: "first", weight: 0.4 },
      { artist: "renamed", weight: 1.25, fixed: true },
      { artist: "last", weight: 2.0 },
    ],
  );
  assert.deepEqual(
    moveStyleArtistToPosition(current, 2, 1).map((item) => item.artist),
    ["last", "first", "middle"],
  );
  assert.deepEqual(current.map((item) => item.artist), ["first", "middle", "last"]);
});

test("fixed style artists round-trip through local storage with their table fields", () => {
  const originalStorage = global.localStorage;
  const values = new Map();
  global.localStorage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
  try {
    const stored = saveFixedStyleArtists([
      { artist: "random", weight: 0.4 },
      { artist: " saved_artist ", score: "5", weight: "1.356", fixed: true, slot: "2", random_weight: true },
    ]);
    assert.deepEqual(stored, [{ artist: "saved_artist", score: 5, weight: 1.36, slot: 2, random_weight: true }]);
    assert.deepEqual(loadFixedStyleArtists(), [{
      artist: "saved_artist", score: 5, weight: 1.36, fixed: true, slot: 2, random_weight: true,
    }]);
  } finally {
    if (originalStorage === undefined) delete global.localStorage;
    else global.localStorage = originalStorage;
  }
});

test("a fixed artist weight update can be persisted without the graph DOM", () => {
  const originalStorage = global.localStorage;
  const values = new Map();
  global.localStorage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
  try {
    const artists = updateStyleArtistAtIndex([
      { artist: "fixed_artist", score: 4, weight: 0.8, fixed: true, slot: 1 },
      { artist: "random_artist", weight: 1.2 },
    ], 0, { weight: 1.47 });
    saveFixedStyleArtists(artists);
    assert.deepEqual(loadFixedStyleArtists(), [{
      artist: "fixed_artist", score: 4, weight: 1.47, fixed: true, slot: 1,
    }]);
  } finally {
    if (originalStorage === undefined) delete global.localStorage;
    else global.localStorage = originalStorage;
  }
});

test("stored fixed style artists ignore malformed rows and normalize optional fields", () => {
  assert.deepEqual(normalizeStoredFixedStyleArtists([
    { artist: "not fixed", weight: 1, fixed: false },
    { artist: "missing weight" },
    { artist: "bad weight", weight: "nope" },
    { artist: "bad artist", weight: 1, artist: 123 },
    { artist: "valid", score: 9, weight: "0.905", slot: "not an integer", random_weight: false },
    { artist: "valid", score: 4, weight: 2, slot: 1 },
  ]), [{ artist: "valid", weight: 0.91, fixed: true }]);

  const originalStorage = global.localStorage;
  global.localStorage = {
    getItem() { return "{malformed"; },
    setItem() {},
  };
  try {
    assert.deepEqual(loadFixedStyleArtists(), []);
    assert.equal(STYLE_FIXED_ARTISTS_STORAGE_KEY, "naiArtistRater.styleFixedArtists.v1");
  } finally {
    if (originalStorage === undefined) delete global.localStorage;
    else global.localStorage = originalStorage;
  }
});

test("selected fixed artists move together into an insertion slot", () => {
  const current = [
    { artist: "a", weight: 0.4 },
    { artist: "b", weight: 1.0, fixed: true },
    { artist: "c", weight: 1.1 },
    { artist: "d", weight: 1.2, fixed: true },
    { artist: "e", weight: 1.3 },
  ];

  assert.deepEqual(
    moveSelectedArtistsToPosition(current, [1, 3], 5).map((item) => item.artist),
    ["a", "c", "b", "d", "e"],
  );
  assert.deepEqual(
    moveSelectedArtistsToPosition(current, [1, 3], 6).map((item) => item.artist),
    ["a", "c", "e", "b", "d"],
  );
  assert.deepEqual(current.map((item) => item.artist), ["a", "b", "c", "d", "e"]);
});

test("a fixed artist can move across the configured prompt slots", () => {
  const current = [{ artist: "fixed", weight: 1.0, fixed: true, slot: 1 }];

  assert.deepEqual(
    moveSelectedArtistsToPosition(current, [0], 12, 12),
    [{ artist: "fixed", weight: 1.0, fixed: true, slot: 12 }],
  );
  assert.deepEqual(
    moveStyleArtistToPosition(current, 0, 8, 12),
    [{ artist: "fixed", weight: 1.0, fixed: true, slot: 8 }],
  );
});

test("graph insertion position maps pointer ratio to visible between-item slots", () => {
  assert.equal(graphInsertionPositionFromRatio(-0.2, 5), 1);
  assert.equal(graphInsertionPositionFromRatio(0, 5), 1);
  assert.equal(graphInsertionPositionFromRatio(0.21, 5), 2);
  assert.equal(graphInsertionPositionFromRatio(0.99, 5), 5);
  assert.equal(graphInsertionPositionFromRatio(1, 5), 5);
});

test("fixed overlay positions use the same slot scale as insertion lines", () => {
  assert.equal(fixedArtistOverlayCoordinates({ slot: 1, stackIndex: 0 }, 0.4, 4, 0.1, 2.3).left, 6.44);
  assert.equal(fixedArtistOverlayCoordinates({ slot: 3, stackIndex: 0 }, 0.4, 4, 0.1, 2.3).left, 67.04);
  assert.equal(fixedArtistOverlayCoordinates({ slot: 5, stackIndex: 0 }, 0.4, 4, 0.1, 2.3).left, 97.33);
});

test("fixed overlay cards in the same slot stagger away from each other", () => {
  assert.equal(fixedArtistOverlayCoordinates({ slot: 1, stackIndex: 0 }, 0.1, 4, 0.1, 2.3).bottom, 8);
  assert.equal(fixedArtistOverlayCoordinates({ slot: 1, stackIndex: 1 }, 0.1, 4, 0.1, 2.3).bottom, 21);
  assert.equal(fixedArtistOverlayCoordinates({ slot: 4, stackIndex: 0 }, 2.3, 4, 0.1, 2.3).bottom, 76);
  assert.equal(fixedArtistOverlayCoordinates({ slot: 4, stackIndex: 1 }, 2.3, 4, 0.1, 2.3).bottom, 63);
});

test("fixed artist overlay cards stay anchored inside graph edges", () => {
  assert.deepEqual(
    fixedArtistOverlayCoordinates(0, 0.1, 12, 0.1, 2.3),
    { left: 8, bottom: 8, xOffset: "0%" },
  );
  assert.deepEqual(
    fixedArtistOverlayCoordinates(11, 2.3, 12, 0.1, 2.3),
    { left: 92, bottom: 76, xOffset: "-100%" },
  );
  assert.deepEqual(
    fixedArtistOverlayCoordinates(5, 1.2, 12, 0.1, 2.3).xOffset,
    "-50%",
  );
});

test("weight profile interpolates prompt positions between control points", () => {
  const profile = [
    { position: 0, weight: 0.2 },
    { position: 0.5, weight: 2.0 },
    { position: 1, weight: 0.6 },
  ];
  assert.deepEqual(
    [0, 0.25, 0.5, 0.75, 1].map((position) => interpolateWeightProfile(profile, position)),
    [0.2, 1.1, 2, 1.3, 0.6],
  );
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

test("custom ranges reject inclusive endpoint overlap", () => {
  assert.throws(
    () => validateCustomRangeValues(
      [
        { min: 0.1, max: 0.9, max_people: 1 },
        { min: 0.9, max: 1.2, max_people: 1 },
      ],
      { globalMin: 0.1, globalMax: 2.3, artistCount: 2 },
    ),
    /구간이 서로 겹칩니다/,
  );
});

test("custom ranges allow a one-cent gap and enforce capacity", () => {
  const ranges = [
    { min: 0.1, max: 0.9, max_people: 1 },
    { min: 0.91, max: 1.2, max_people: 2 },
  ];

  assert.deepEqual(
    validateCustomRangeValues(ranges, { globalMin: 0.1, globalMax: 2.3, artistCount: 3 }),
    ranges,
  );
  assert.throws(
    () => validateCustomRangeValues(ranges, { globalMin: 0.1, globalMax: 2.3, artistCount: 4 }),
    /총 인원\(3\).*작가 수\(4\)/,
  );
});

test("score selection requires valid scores and returns numeric order", () => {
  assert.deepEqual(normalizeSelectedScores(new Set([5, 2, 4])), [2, 4, 5]);
  assert.throws(() => normalizeSelectedScores(new Set()), /하나 이상 선택/);
  assert.throws(() => normalizeSelectedScores([1, 6]), /1부터 5/);
});

test("reroll payload uses one explicit mode without unused boolean flags", () => {
  const artists = [
    { artist: "third", score: 3, weight: 1.2 },
    { artist: "first", score: 5, weight: 0.8 },
    { artist: "second", score: 4, weight: 1.0 },
  ];
  const payload = buildStyleRequestPayload(
    { count: 3, scores: [3, 4, 5] },
    artists,
    "weights",
  );

  assert.deepEqual(payload.artists, [
    { artist: "third", score: 3, weight: 1.2 },
    { artist: "first", score: 5, weight: 0.8 },
    { artist: "second", score: 4, weight: 1.0 },
  ]);
  assert.equal(payload.reroll, "weights");
  assert.deepEqual(payload.fixed_artists, []);
  assert.equal("reroll_artists" in payload, false);
  assert.equal("reroll_weights" in payload, false);
});

test("reroll result ordering depends on the explicit action", () => {
  const current = [
    { artist: "old-a", score: 5, weight: 1.7 },
    { artist: "old-b", score: 4, weight: 0.4 },
  ];
  const fresh = [
    { artist: "old-a", score: 5, weight: 1.3 },
    { artist: "old-b", score: 4, weight: 0.6 },
  ];

  assert.deepEqual(
    applyStyleRerollResult(current, fresh, "all").map((item) => item.artist),
    ["old-b", "old-a"],
  );
  assert.deepEqual(
    applyStyleRerollResult(current, fresh, "weights"),
    fresh,
  );
  assert.deepEqual(
    applyStyleRerollResult(current, fresh, "artists"),
    fresh,
  );
  assert.deepEqual(
    applyStyleRerollResult(current, fresh, "all", true),
    fresh,
  );
});

test("fixed artists are included in the configured total artist count", () => {
  const artists = [
    { artist: "random-a", weight: 0.4 },
    { artist: "fixed-a", weight: 1.2, fixed: true },
    { artist: "random-b", weight: 0.8 },
    { artist: "fixed-b", weight: 1.6, fixed: true },
    { artist: "random-c", weight: 2.0 },
  ];
  assert.deepEqual(
    limitArtistsToTotalCount(artists, 3).map((item) => item.artist),
    ["random-a", "fixed-a", "fixed-b"],
  );
  assert.throws(() => limitArtistsToTotalCount(artists, 1), /고정 작가 2명.*전체 작가 수 1명/);

  const payload = buildStyleRequestPayload({ count: 3 }, artists, "all");
  assert.deepEqual(payload.fixed_artists, [
    { artist: "fixed-a", score: undefined, weight: 1.2 },
    { artist: "fixed-b", score: undefined, weight: 1.6 },
  ]);

  artists[1].slot = 2;
  assert.equal(buildStyleRequestPayload({ count: 3 }, artists, "all").fixed_artists[0].slot, 2);
  artists[1].slot = 0;
  artists[1].random_weight = true;
  assert.deepEqual(buildStyleRequestPayload({ count: 3 }, artists, "all").fixed_artists[0], {
    artist: "fixed-a", score: undefined, weight: 1.2, slot: 0, random_weight: true,
  });
});

test("opening the weight graph preserves the selected weight mode", () => {
  const originalDocument = global.document;
  const mode = { value: "" };
  const modal = { classList: { remove() {} } };
  const graph = {
    classList: { toggle() {} },
    replaceChildren() {},
  };
  global.document = {
    getElementById(id) {
      return { weightMode: mode, weightGraphModal: modal, weightGraph: graph }[id] || null;
    },
    querySelectorAll() {
      return [];
    },
  };
  try {
    for (const selectedMode of ["random", "balanced"]) {
      mode.value = selectedMode;
      openWeightGraphModal();
      assert.equal(mode.value, selectedMode);
    }
  } finally {
    if (originalDocument === undefined) delete global.document;
    else global.document = originalDocument;
  }
});

test("reroll all keeps manually fixed artists even when incoming result omits them", () => {
  const current = [
    { artist: "manual", score: undefined, weight: 1.4, fixed: true },
    { artist: "old-random", score: 4, weight: 0.5 },
  ];
  const fresh = [
    { artist: "new-random", score: 5, weight: 0.8 },
  ];

  assert.deepEqual(
    applyStyleRerollResult(current, fresh, "all").map(({ artist, fixed }) => ({ artist, fixed: Boolean(fixed) })),
    [
      { artist: "new-random", fixed: false },
      { artist: "manual", fixed: true },
    ],
  );
});

test("reroll preserves fixed artist slots when incoming result includes them", () => {
  const current = [
    { artist: "manual", weight: 1.4, fixed: true, slot: 2 },
  ];
  const fresh = [
    { artist: "manual", weight: 0.9 },
  ];

  assert.deepEqual(applyStyleRerollResult(current, fresh, "weights"), [
    { artist: "manual", weight: 0.9, fixed: true, slot: 2 },
  ]);
});

test("sort and reorder helpers return the requested artist order", () => {
  const artists = [
    { artist: "middle", weight: 1.0 },
    { artist: "high", weight: 1.8 },
    { artist: "low", weight: 0.4 },
  ];

  assert.deepEqual(sortArtistsByWeight(artists, "asc").map((item) => item.artist), ["low", "middle", "high"]);
  assert.deepEqual(sortArtistsByWeight(artists, "desc").map((item) => item.artist), ["high", "middle", "low"]);
  assert.deepEqual(reorderArtists(artists, 0, 2).map((item) => item.artist), ["high", "low", "middle"]);
  assert.deepEqual(artists.map((item) => item.artist), ["middle", "high", "low"]);
});

test("weight table display sorting cycles without changing prompt artist order", () => {
  const artists = [
    { artist: { artist: "middle", weight: 1.0 }, index: 0 },
    { artist: { artist: "high", weight: 1.8 }, index: 1 },
    { artist: { artist: "low", weight: 0.4 }, index: 2 },
  ];
  assert.deepEqual(sortFixedArtistEntriesForTable(artists, "asc").map((item) => item.artist.artist), ["low", "middle", "high"]);
  assert.deepEqual(sortFixedArtistEntriesForTable(artists, "desc").map((item) => item.artist.artist), ["high", "middle", "low"]);
  assert.deepEqual(sortFixedArtistEntriesForTable(artists, "default"), artists);
  assert.deepEqual(artists.map((item) => item.artist.artist), ["middle", "high", "low"]);
});

test("custom range fields expose only Korean visible and accessible labels", () => {
  assert.deepEqual(
    CUSTOM_RANGE_FIELDS.map(({ label, ariaLabel }) => [label, ariaLabel]),
    [
      ["최소 가중치", "최소 가중치"],
      ["최대 가중치", "최대 가중치"],
      ["최대 인원", "최대 인원"],
    ],
  );
});

test("only the latest style request can mutate state or clear pending controls", async () => {
  const requestState = { requestToken: 0, pending: false };
  const first = deferred();
  const second = deferred();
  const applied = [];
  const pending = [];
  const handlers = {
    onPending: (value) => pending.push(value),
    onSuccess: (value) => applied.push(value),
    onError: (error) => applied.push(error.message),
  };

  const firstRun = runLatestStyleRequest(requestState, () => first.promise, handlers);
  const secondRun = runLatestStyleRequest(requestState, () => second.promise, handlers);
  second.resolve("latest");
  await secondRun;
  first.reject(new Error("stale"));
  await firstRun;

  assert.deepEqual(applied, ["latest"]);
  assert.deepEqual(pending, [true, true, false]);
  assert.equal(requestState.requestToken, 2);
  assert.equal(requestState.pending, false);
});
