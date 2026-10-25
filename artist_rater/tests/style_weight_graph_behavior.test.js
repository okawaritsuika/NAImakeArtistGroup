const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../static/style_maker.js"), "utf8");

function graphSession(mode = "profile", count = 20) {
  let focusReturns = 0;
  const fields = {
    weightMode: { value: mode }, styleArtistCount: { value: String(count) },
    styleMinWeight: { value: "0.1" }, styleMaxWeight: { value: "2.3" },
    weightGraphModal: { classList: { add() {}, remove() {} } },
  };
  const context = vm.createContext({});
  vm.runInContext(source, context);
  context.document = {
    getElementById: (id) => fields[id] || null,
    activeElement: { focus() { focusReturns += 1; } },
  };
  // Isolate editor transactions from rendering/network refresh; browser QA covers the DOM.
  vm.runInContext("renderWeightGraph = () => {};", context);
  const api = vm.runInContext(`({
    state: styleState, open: openWeightGraphModal, close: closeWeightGraphModal,
    apply: applyWeightGraphModal, edit: editWeightGraphValue, stroke: editWeightGraphStroke, values: weightGraphValues,
    slots: weightProfileSlotValues, interpolate: interpolateWeightProfile,
  })`, context);
  return { ...api, fields, focusReturns: () => focusReturns };
}

function plain(value) { return JSON.parse(JSON.stringify(value)); }

test("20-artist profile editing keeps all other slot targets and the existing payload format", () => {
  const graph = graphSession();
  const profile = [{ position: 0, weight: 2 }, { position: 0.4, weight: 1.4 }, { position: 1, weight: 0.2 }];
  graph.state.weightProfile = profile;
  graph.open();
  const before = plain(graph.values());
  assert.equal(before.length, 20);
  assert.equal(before[0], 2);
  assert.equal(before[19], 0.2);
  assert.equal(graph.edit(19, 1.7), true);
  assert.deepEqual(plain(graph.values()).slice(0, 19), before.slice(0, 19));
  assert.equal(graph.values()[19], 1.7);
  assert.deepEqual(graph.state.weightProfile, profile, "draft must not change generation settings");
  graph.apply();
  assert.equal(graph.fields.weightMode.value, "profile");
  assert.equal(graph.state.weightProfile.length, 20);
  assert.deepEqual(Object.keys(graph.state.weightProfile[0]), ["position", "weight"]);
  assert.equal(graph.state.weightProfile[0].position, 0);
  assert.equal(graph.state.weightProfile.at(-1).position, 1);
  assert.equal(graph.interpolate(graph.state.weightProfile, 1), 1.7);
  assert.equal(graph.focusReturns(), 1);
});

test("cancel discards graph edits and the next opening uses the committed profile", () => {
  const graph = graphSession();
  const before = plain(graph.state.weightProfile);
  graph.open();
  graph.edit(8, 2.3);
  graph.close();
  assert.deepEqual(plain(graph.state.weightProfile), before);
  graph.open();
  assert.deepEqual(plain(graph.values()), plain(graph.slots(before, 20, 0.1, 2.3)));
});

test("a fast graph stroke edits skipped slots in both directions without committing the draft", () => {
  const graph = graphSession();
  const committed = plain(graph.state.weightProfile);
  graph.open();
  graph.stroke(null, { index: 0, weight: 2.1 });
  graph.stroke({ index: 0, weight: 2.1 }, { index: 19, weight: 0.2 });
  assert.deepEqual(plain(graph.values()), Array.from({ length: 20 }, (_, i) => Number((2.1 - i / 10).toFixed(2))));
  graph.stroke({ index: 19, weight: 0.2 }, { index: 15, weight: 1.8 });
  assert.deepEqual(plain(graph.values()).slice(15), [1.8, 1.4, 1, 0.6, 0.2]);
  graph.stroke({ index: 15, weight: 1.8 }, { index: 15, weight: 1.33 });
  assert.equal(graph.values()[15], 1.33);
  assert.deepEqual(plain(graph.state.weightProfile), committed);
  graph.close();
  graph.open();
  assert.deepEqual(plain(graph.values()), plain(graph.slots(committed, 20, 0.1, 2.3)));
});

test("graph strokes apply only traversed artist weights and are blocked while generating", () => {
  const graph = graphSession("balanced");
  const artists = Array.from({ length: 4 }, (_, index) => ({ artist: `sample_${index}`, weight: 1, fixed: true, random_weight: false, slot: index }));
  graph.state.artists = plain(artists);
  graph.open();
  graph.stroke({ index: 1, weight: 0.1 }, { index: 2, weight: 2.3 });
  graph.state.pending = true;
  graph.stroke({ index: 0, weight: 2 }, { index: 3, weight: 0.3 });
  assert.deepEqual(plain(graph.values()), [1, 0.1, 2.3, 1]);
  graph.state.pending = false;
  graph.apply();
  assert.deepEqual(plain(graph.state.artists), artists.map((artist, index) => ({ ...artist, weight: [1, 0.1, 2.3, 1][index] })));
});

test("a single artist retains two valid profile endpoints and no division by zero", () => {
  const graph = graphSession("profile", 1);
  graph.open();
  assert.equal(graph.values().length, 1);
  assert.equal(Number.isFinite(graph.values()[0]), true);
  graph.edit(0, 1.23);
  graph.apply();
  assert.deepEqual(plain(graph.state.weightProfile), [
    { position: 0, weight: 1.23 }, { position: 1, weight: 1.23 },
  ]);
});

test("non-profile apply changes only edited artists and preserves fixed/random/slot metadata", () => {
  const graph = graphSession("balanced");
  graph.state.artists = [
    { artist: "sample_a", weight: 1.2, fixed: true, random_weight: true, slot: 0 },
    { artist: "sample_b", weight: 0.8, fixed: false },
  ];
  graph.open();
  assert.equal(graph.edit(0, 1.75), true);
  assert.equal(graph.state.artists[0].weight, 1.2);
  graph.state.artists[1].weight = 1.05;
  graph.state.artists.push({ artist: "sample_c", weight: 0.4 });
  graph.apply();
  assert.equal(graph.fields.weightMode.value, "balanced");
  assert.deepEqual(plain(graph.state.artists), [
    { artist: "sample_a", weight: 1.75, fixed: true, random_weight: true, slot: 0 },
    { artist: "sample_b", weight: 1.05, fixed: false },
    { artist: "sample_c", weight: 0.4 },
  ]);
});

test("invalid values, missing artists and pending requests cannot alter a graph draft", () => {
  const graph = graphSession();
  graph.open();
  const before = plain(graph.values());
  for (const value of [NaN, Infinity, "", -1, 2.31]) assert.equal(graph.edit(0, value), false);
  assert.equal(graph.edit(20, 1), false);
  graph.state.pending = true;
  assert.equal(graph.edit(0, 1.1), false);
  assert.deepEqual(plain(graph.values()), before);
  graph.close();
  graph.fields.weightMode.value = "random";
  graph.open();
  assert.deepEqual(plain(graph.values()), []);
  assert.equal(graph.edit(0, 1), false);
});
