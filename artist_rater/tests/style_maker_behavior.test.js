const assert = require("node:assert/strict");
const test = require("node:test");

const {
  CUSTOM_RANGE_FIELDS,
  buildStyleRequestPayload,
  normalizeSelectedScores,
  reorderArtists,
  sortArtistsByWeight,
  validateCustomRangeValues,
} = require("../static/style_maker.js");

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

test("weight-only payload preserves the current artist order", () => {
  const artists = [
    { artist: "third", score: 3, weight: 1.2 },
    { artist: "first", score: 5, weight: 0.8 },
    { artist: "second", score: 4, weight: 1.0 },
  ];
  const payload = buildStyleRequestPayload(
    { count: 3, scores: [3, 4, 5] },
    artists,
    { rerollArtists: false, rerollWeights: true },
  );

  assert.deepEqual(payload.artists, [
    { artist: "third", score: 3 },
    { artist: "first", score: 5 },
    { artist: "second", score: 4 },
  ]);
  assert.equal(payload.reroll_artists, false);
  assert.equal(payload.reroll_weights, true);
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
