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
  parsePromptTokens,
  appendUniquePromptToken,
  removePromptToken,
  parseStyleArtistNames,
  insertStyleArtistsAtPosition,
  updateStyleArtistAtIndex,
  moveStyleArtistToPosition,
  fixedStyleArtistEntries,
  fixedArtistOverlayCoordinates,
  graphInsertionPositionFromRatio,
  moveSelectedArtistsToPosition,
  fixedArtistSlotEntries,
  chooseArtistsForPrompt,
  STYLE_REQUEST_CONTROL_IDS,
  addPromptGroupItem,
  cleanPromptGroups,
  buildEffectivePromptText,
} = require("../static/style_maker.js");

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
      negative_prompt: "neg",
      character_prompts: ["a", "b"],
      character_prompt_ids: ["character-1", "character-2"],
      prompt_groups: [],
      generation_settings: {},
    },
  );
  assert.deepEqual(normalizeStoredPrompts(null), {
    base_prompt: "",
    negative_prompt: "",
    character_prompts: [""],
    character_prompt_ids: ["character-1"],
    prompt_groups: [],
    generation_settings: {},
  });
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
