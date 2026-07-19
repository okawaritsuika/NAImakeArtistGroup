const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CUSTOM_RANGE_FIELDS,
  applyStyleRerollResult,
  buildStyleRequestPayload,
  normalizeRandomTargets,
  pickRandomPreset,
  normalizeSelectedScores,
  reorderArtists,
  runLatestStyleRequest,
  sortArtistsByWeight,
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
  moveSelectedArtistsToPosition,
  fixedArtistSlotEntries,
  chooseArtistsForPrompt,
  STYLE_REQUEST_CONTROL_IDS,
  addPromptGroupItem,
  cleanPromptGroups,
  buildEffectivePromptText,
  toggleSelectedStyleId,
  managerCombinedPromptText,
  confirmedGeneratedSourceValues,
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
} = require("../static/style_maker.js");

test("numeric prompt closers keep weight openers and space numeric tag endings", () => {
  assert.equal(
    normalizeNumericPromptClosers("1.5::artist:matrix16::, 2::year 2025::, -3::clone::"),
    "1.5::artist:matrix16 ::, 2::year 2025 ::, -3::clone::",
  );
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
    { artist: "new_b", weight: 1.25, fixed: true, slot: 2 },
    { artist: "last", weight: 2.0 },
  ]);
  assert.deepEqual(current.map((item) => item.artist), ["first", "last"]);
});

test("manual artists with the same slot stack and choose one prompt candidate", () => {
  const added = insertStyleArtistsAtPosition([], ["new_a", "new_b"], {
    position: 1,
    weight: 1.25,
  });

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
