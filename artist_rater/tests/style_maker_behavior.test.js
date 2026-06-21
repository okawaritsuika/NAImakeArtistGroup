const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CUSTOM_RANGE_FIELDS,
  applyStyleRerollResult,
  buildStyleRequestPayload,
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
  addPromptGroupItem,
  cleanPromptGroups,
  buildEffectivePromptText,
} = require("../static/style_maker.js");

test("prompt storage keeps one normalized snapshot", () => {
  assert.deepEqual(
    promptStoragePayload(" base ", " negative ", [" char one ", "", " char two "]),
    {
      base_prompt: " base ",
      negative_prompt: " negative ",
      character_prompts: [" char one ", "", " char two "],
      character_prompt_ids: ["character-1", "character-2", "character-3"],
      prompt_groups: [],
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
    },
  );
  assert.deepEqual(normalizeStoredPrompts(null), {
    base_prompt: "",
    negative_prompt: "",
    character_prompts: [""],
    character_prompt_ids: ["character-1"],
    prompt_groups: [],
  });
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
