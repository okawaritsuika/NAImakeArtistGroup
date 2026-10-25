const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { splitConditions, safeSourceUrl, safeLocalImageUrl, roundLabel, availableSizes, canStart, previewParticipants, createController } = require("../static/style_worldcup.js");

// Minimal DOM implements the browser operations used by this controller. Layout is
// verified separately in the browser, while these tests exercise bound controls.
function fakeDocument() {
  const nodes = new Map();
  const doc = { activeElement: null, hitTarget: null, listeners: {}, elementFromPoint() { return this.hitTarget; }, addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }, async emit(name, event = {}) { await Promise.all((this.listeners[name] || []).map((fn) => fn({ preventDefault() {}, ...event }))); } };
  class Element {
    constructor(tag) {
      this.tagName = tag.toUpperCase(); this.children = []; this.listeners = {};
      this.dataset = {}; this.attributes = {}; this.value = ""; this.hidden = false; this.disabled = false; this._text = ""; this.scrollTop = 0;
      this.style = { setProperty(name, value) { this[name] = value; } };
      this.capturedPointers = new Set();
      this.rect = { left: 0, top: 0, right: 600, bottom: 600, width: 600, height: 600 };
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
    append(...items) { items.forEach((item) => { if (item.parentNode) item.parentNode.children = item.parentNode.children.filter((node) => node !== item); item.parentNode = this; this.children.push(item); }); }
    replaceChildren(...items) { this.children = []; this._text = ""; this.append(...items); }
    replaceWith(item) { const index = this.parentNode.children.indexOf(this); this.parentNode.children[index] = item; item.parentNode = this.parentNode; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
    async emit(name, options = {}) { if (this.disabled) return; await Promise.all((this.listeners[name] || []).map((fn) => fn({ target: this, preventDefault() {}, ...options }))); }
    setPointerCapture(pointerId) { this.capturedPointers.add(pointerId); }
    hasPointerCapture(pointerId) { return this.capturedPointers.has(pointerId); }
    releasePointerCapture(pointerId) { this.capturedPointers.delete(pointerId); }
    getBoundingClientRect() { return this.rect; }
    focus(options) { doc.activeElement = this; this.focusOptions = options; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    querySelectorAll(selector) {
      const tags = selector.split(",").map((tag) => tag.trim().toUpperCase());
      const found = [];
      const walk = (node) => node.children.forEach((child) => { if (tags.includes(child.tagName)) found.push(child); walk(child); });
      walk(this); return found;
    }
    reset() { nodes.forEach((node) => { node.value = node.defaultValue || ""; }); }
  }
  const template = fs.readFileSync(path.join(__dirname, "../templates/style_worldcup.html"), "utf8");
  for (const match of template.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const node = new Element(match[1]); node.id = match[2]; node.hidden = /\bhidden\b/.test(match[0]);
    node.value = node.defaultValue = /\bvalue="([^"]*)"/.exec(match[0])?.[1] || "";
    nodes.set(node.id, node);
  }
  const root = nodes.get("style-worldcup-tab");
  nodes.forEach((node) => { if (node !== root) root.append(node); });
  const picker = nodes.get("worldcupPicker");
  nodes.forEach((node) => {
    if ((node.id.startsWith("worldcupPicker") || ["worldcupName", "worldcupStart", "worldcupStartBottom", "worldcupAutoSelect", "worldcupSize", "worldcupModel", "worldcupIncludeTags", "worldcupExcludeTags", "worldcupRecommendation"].includes(node.id)) && node !== picker) {
      root.children = root.children.filter((child) => child !== node);
      picker.append(node);
    }
  });
  doc.createElement = (tag) => new Element(tag);
  doc.getElementById = (id) => nodes.get(id);
  doc.querySelector = () => null;
  return doc;
}
function response(body, status = 200) { return { ok: status >= 200 && status < 300, status, json: async () => body }; }
function participant(ordinal, extra = {}) {
  return { ordinal, title: "그림 " + ordinal, image_url: "/api/local-images/" + ordinal, available: true, source_url: "https://example.test/post/" + ordinal, base_prompt: "artist:test, watercolor", recommendation_count: 8, ...extra };
}
function detail(revision = 0, completed = false) {
  return { id: 9, name: "테스트 월드컵", size: 2, revision, status: completed ? "completed" : "playing", participants: [participant(0), participant(1)], current_match: completed ? null : { left: 0, right: 1, round_size: 2, match_number: 1, matches_in_round: 1 }, winner: completed ? 1 : null, history: completed ? [{ round_size: 2, left: 0, right: 1, winner: 1 }] : [] };
}
function queuedFetch(responses) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, payload: options.body ? JSON.parse(options.body) : undefined });
    assert.ok(responses.length, "unexpected request: " + url);
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return typeof next === "function" ? next() : next;
  };
  fetcher.calls = calls;
  return fetcher;
}
function descendants(node, tag) { return node.querySelectorAll(tag); }
function candidate(key, extra = {}) {
  const [image_source, id] = key.split(":");
  return { key, image_source, title: "후보 " + key, image_url: "/api/local-images/" + id, available: true, recommendation_count: image_source === "shared" ? 8 : null, ...extra };
}
function autoCandidates(count = 2) {
  const selection = Array.from({ length: count }, (_, index) => candidate("shared:" + (index + 1)));
  return { count, page: 1, per_page: 60, items: selection.slice(0, 60), selection };
}
function pickerCard(doc, key) { return descendants(doc.getElementById("worldcupPickerGrid"), "button").find((node) => node.dataset.candidateKey === key); }
function candidateDetailButton(doc, key) { return pickerCard(doc, key).parentNode.children[1]; }
async function creation(items, later = [], count = items.length) {
  const doc = fakeDocument(); const fetcher = queuedFetch([response({ count, counts: { shared: count, confirmed: 0 } }), response({ count, page: 1, items }), ...later]);
  const controller = createController(doc, fetcher); await controller.newWorldcup();
  assert.equal(fetcher.calls.length, 0);
  await doc.getElementById("worldcupPickerFilterApply").emit("click");
  return { doc, fetcher, controller, $: (id) => doc.getElementById(id) };
}
function setRect(node, left, top, width, height) { node.rect = { left, top, width, height, right: left + width, bottom: top + height }; }
function layoutCards(doc, keys) {
  const grid = doc.getElementById("worldcupPickerGrid"); setRect(grid, 100, 100, 340, 340);
  keys.forEach((key, index) => setRect(pickerCard(doc, key), 110 + (index % 3) * 110, 110 + Math.floor(index / 3) * 110, 100, 90));
  return grid;
}
function pointer(extra = {}) { return { pointerType: "mouse", button: 0, pointerId: 1, clientX: 105, clientY: 105, ...extra }; }

test("conditions preserve full tags and ignore blank comma/newline segments", () => {
  assert.deepEqual(splitConditions(" artist:a, soft lighting\nmonochrome,artist:a\r\n"), ["artist:a", "soft lighting", "monochrome"]);
  assert.equal(roundLabel(2), "결승"); assert.equal(roundLabel(16), "16강");
  assert.equal(canStart(null, 2, false), false);
  assert.equal(canStart(1, 2, false), false);
  assert.equal(canStart(2, 2, false), true);
  assert.equal(canStart(8, 2, true), false);
  assert.equal(canStart(5, "all", false), true);
  assert.equal(canStart(1, "all", false), false);
  assert.equal(canStart(5, 3, false), false);
  assert.equal(canStart(5, 8, false), false);
  assert.deepEqual(availableSizes(1), []);
  assert.deepEqual(availableSizes(5), [2, 4]);
  assert.deepEqual(availableSizes(300), [2, 4, 8, 16, 32, 64, 128, 256]);
});

test("source links allow only HTTP(S), and images remain on local relative routes", () => {
  assert.equal(safeSourceUrl("javascript:alert(1)"), "");
  assert.equal(safeSourceUrl("data:text/html,x"), "");
  assert.equal(safeSourceUrl("https://example.test/post/2"), "https://example.test/post/2");
  for (const unsafe of ["https://example.test/a.png", "//example.test/a.png", "/\\example.test/a.png", "/\n/example.test/a.png", "data:image/png,a"]) assert.equal(safeLocalImageUrl(unsafe), "");
  assert.equal(safeLocalImageUrl("/api/style-worldcups/2/images/0"), "/api/style-worldcups/2/images/0");
});

test("new waits for filter apply before fetching candidates, then starts the exact current selection", async () => {
  const items = [candidate("shared:1"), candidate("confirmed:2")];
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id);
  const fetcher = queuedFetch([response({ count: 2, counts: { shared: 1, confirmed: 1 } }), response({ count: 2, page: 1, items }), response(detail()), response(detail(1, true))]);
  const controller = createController(doc, fetcher); await controller.newWorldcup();
  assert.equal(controller.state.view, "picker"); assert.equal($("worldcupPicker").hidden, false);
  assert.equal($("worldcupHead").hidden, true); assert.equal($("worldcupStatus").hidden, true);
  assert.equal(fetcher.calls.length, 0); assert.equal(controller.state.count, null);
  assert.equal(descendants($("worldcupPickerGrid"), "img").length, 0);
  assert.match($("worldcupCandidateCount").textContent, /필터 적용 후/);
  assert.match($("worldcupPickerGrid").textContent, /필터 적용/);
  for (const id of ["worldcupPickerSharedSource", "worldcupPickerMode", "worldcupPickerSort", "worldcupAutoSelect", "worldcupStart"]) {
    assert.equal($(id).disabled, true); await $(id).emit("click");
  }
  $("worldcupModel").value = "nai-diffusion-5-full"; await $("worldcupModel").emit("change");
  $("worldcupIncludeTags").value = "artist:a"; await $("worldcupIncludeTags").emit("input");
  assert.equal(fetcher.calls.length, 0);
  await $("worldcupPickerFilterApply").emit("click");
  assert.equal(fetcher.calls[0].url, "/api/style-worldcups/preview"); assert.equal(fetcher.calls[1].payload.per_page, 60);
  for (const call of fetcher.calls) { assert.equal(call.payload.model, "nai-diffusion-5-full"); assert.deepEqual(call.payload.include_tags, ["artist:a"]); }
  assert.match($("worldcupCandidateCount").textContent, /총 2개.*공유 1개.*확정 1개/);
  assert.match($("worldcupPickerVisibleCount").textContent, /현재 목록 2개 · 이번 페이지 2개/);
  await pickerCard(doc, "shared:1").emit("click"); assert.equal(controller.state.selection.size, 1); assert.equal($("worldcupStart").disabled, true);
  await pickerCard(doc, "confirmed:2").emit("click"); assert.equal($("worldcupStart").disabled, false); assert.equal($("worldcupStartBottom").disabled, false);
  assert.match($("worldcupStart").textContent, /2개/);
  await $("worldcupForm").emit("submit");
  assert.deepEqual(fetcher.calls[2].payload.selected_candidates, ["shared:1", "confirmed:2"]); assert.equal(fetcher.calls[2].payload.selection_scope, "all");
  assert.equal(controller.state.view, "detail");
  await descendants($("worldcupMatch"), "button")[1].emit("click"); assert.equal(controller.state.detail.status, "completed");
  await controller.newWorldcup();
  assert.equal(fetcher.calls.length, 4); assert.equal(controller.state.selection.size, 0);
  assert.equal(descendants($("worldcupPickerGrid"), "img").length, 0); assert.equal(controller.state.count, null);
});

test("rectangle selects cards the pointer never touched, shrinking restores outside baseline, and Escape cancels in place", async () => {
  const items = Array.from({ length: 9 }, (_, index) => candidate("shared:" + (index + 1)));
  const { doc, $, controller } = await creation(items); const grid = layoutCards(doc, items.map((item) => item.key));
  await pickerCard(doc, "shared:9").emit("click");
  await grid.emit("pointerdown", pointer({ target: grid }));
  await grid.emit("pointermove", pointer({ clientX: 108, clientY: 105 })); assert.equal(controller.state.selection.size, 1);
  await grid.emit("pointermove", pointer({ clientX: 435, clientY: 315 }));
  assert.deepEqual([...controller.state.selection.keys()], ["shared:9", "shared:1", "shared:2", "shared:3", "shared:4", "shared:5", "shared:6"]);
  assert.equal($("worldcupPickerMarquee").hidden, false); assert.equal($("worldcupPickerMarquee").style.width, "330px");
  await grid.emit("pointermove", pointer({ clientX: 205, clientY: 195 }));
  assert.deepEqual([...controller.state.selection.keys()], ["shared:9", "shared:1"]);
  await doc.emit("keydown", { key: "Escape" });
  assert.deepEqual([...controller.state.selection.keys()], ["shared:9"]); assert.equal(controller.state.view, "picker");
  assert.equal(grid.hasPointerCapture(1), false); assert.equal($("worldcupPickerMarquee").hidden, true);
  await grid.emit("pointerup", pointer({ clientX: 205, clientY: 195 }));
  assert.equal(controller.state.selection.size, 1);
});

test("reverse rectangle and selected-card removal use the baseline, while pointercancel restores it", async () => {
  const items = Array.from({ length: 6 }, (_, index) => candidate("shared:" + (index + 1)));
  const { doc, controller } = await creation(items); const grid = layoutCards(doc, items.map((item) => item.key));
  await grid.emit("pointerdown", pointer({ target: grid, clientX: 435, clientY: 315 }));
  await grid.emit("pointermove", pointer({ clientX: 105, clientY: 105 })); await grid.emit("pointerup", pointer({ clientX: 105, clientY: 105 }));
  assert.equal(controller.state.selection.size, 6);
  await grid.emit("pointerdown", pointer({ target: pickerCard(doc, "shared:1"), clientX: 115, clientY: 115 }));
  await grid.emit("pointermove", pointer({ clientX: 435, clientY: 315 })); assert.equal(controller.state.selection.size, 0);
  await grid.emit("pointermove", pointer({ clientX: 205, clientY: 195 })); assert.equal(controller.state.selection.size, 5);
  await grid.emit("pointercancel", pointer()); assert.equal(controller.state.selection.size, 6); assert.equal(grid.hasPointerCapture(1), false);
});

test("marquee follows scroll offsets, stays inside grid bounds, and leaves selected-only card DOM until release", async () => {
  const items = Array.from({ length: 6 }, (_, index) => candidate("shared:" + (index + 1)));
  const { doc, $, controller } = await creation(items); let grid = layoutCards(doc, items.map((item) => item.key));
  await grid.emit("pointerdown", pointer({ target: grid }));
  await grid.emit("pointermove", pointer({ clientX: 205, clientY: 195 })); assert.equal(controller.state.selection.size, 1);
  grid.rect = { ...grid.rect, top: 0, bottom: 340 };
  items.forEach((item) => { const card = pickerCard(doc, item.key); card.rect = { ...card.rect, top: card.rect.top - 100, bottom: card.rect.bottom - 100 }; });
  await doc.emit("scroll"); assert.equal(controller.state.selection.size, 2);
  await grid.emit("pointermove", pointer({ clientX: 9999, clientY: 9999 }));
  assert.equal($("worldcupPickerMarquee").style.width, "335px"); assert.equal($("worldcupPickerMarquee").style.height, "335px");
  await grid.emit("pointerup", pointer({ clientX: 9999, clientY: 9999 }));
  $("worldcupPickerMode").value = "selected"; await $("worldcupPickerMode").emit("change");
  grid = layoutCards(doc, items.map((item) => item.key)); const first = pickerCard(doc, "shared:1");
  await grid.emit("pointerdown", pointer({ target: first, clientX: 115, clientY: 115 }));
  await grid.emit("pointermove", pointer({ clientX: 435, clientY: 315 }));
  assert.equal(controller.state.selection.size, 0); assert.equal(pickerCard(doc, "shared:1"), first);
  await grid.emit("pointerup", pointer({ clientX: 435, clientY: 315 })); assert.equal(pickerCard(doc, "shared:1"), undefined);
});

test("mouse click applies once, detail buttons do not start marquee, keyboard remains available and touch scroll does not select", async () => {
  const { doc, controller } = await creation([candidate("shared:1"), candidate("shared:2")]);
  const grid = layoutCards(doc, ["shared:1", "shared:2"]); const card = pickerCard(doc, "shared:1"); doc.hitTarget = card;
  await grid.emit("pointerdown", pointer({ target: card, clientX: 115, clientY: 115 }));
  await grid.emit("pointerup", pointer({ clientX: 115, clientY: 115 })); await card.emit("click", { detail: 1 }); assert.equal(controller.state.selection.size, 1);
  await card.emit("click", { detail: 0 }); assert.equal(controller.state.selection.size, 0);
  await grid.emit("pointerdown", pointer({ target: candidateDetailButton(doc, "shared:1") })); assert.equal(controller.state.picker.drag, null);
  await grid.emit("pointerdown", pointer({ target: card, pointerType: "touch" }));
  await grid.emit("pointermove", pointer({ pointerType: "touch", clientY: 300 })); assert.equal(controller.state.selection.size, 0);
  await card.emit("click", { detail: 1 }); assert.equal(controller.state.selection.size, 1);
});

test("thumbnail DOM and selection survive density changes without server requests", async () => {
  const item = candidate("shared:1", { thumbnail_url: "/style-manager-thumbnails/shared/1.png", model_label: "V5 Full Medium" });
  const { doc, $, fetcher, controller } = await creation([item]); const card = pickerCard(doc, item.key); const image = descendants(card, "img")[0];
  assert.equal(image.src, item.thumbnail_url); assert.equal(image.decoding, "async"); assert.equal(image.draggable, false);
  await card.emit("click");
  for (const size of [112, 240, 160]) { $("worldcupPickerCardSize").value = String(size); await $("worldcupPickerCardSize").emit("input"); assert.equal($("worldcupPickerGrid").style["--worldcup-card-size"], size + "px"); }
  assert.equal(descendants(card, "img")[0], image); assert.equal(pickerCard(doc, item.key), card); assert.equal(controller.state.selection.size, 1); assert.equal(fetcher.calls.length, 2);
});

test("filtering preserves actual group keys, summary totals update, and empty results still permit starting previous selections", async () => {
  const original = candidate("shared:1", { group_key: "shared:7" }); const second = candidate("confirmed:2", { group_key: "confirmed:8" });
  const replacement = candidate("shared:11", { group_key: "shared:7" });
  const { doc, $, fetcher, controller } = await creation([original, second], [response({ count: 1, counts: { shared: 1, confirmed: 0 } }), response({ count: 1, page: 1, items: [replacement] }), response({ count: 0 }), response({ count: 0, page: 1, items: [] }), response(detail())]);
  await pickerCard(doc, original.key).emit("click"); await pickerCard(doc, second.key).emit("click");
  $("worldcupModel").value = "v5"; await $("worldcupModel").emit("change"); $("worldcupIncludeTags").value = "artist:a"; await $("worldcupIncludeTags").emit("input");
  assert.equal(fetcher.calls.length, 2); await $("worldcupPickerFilterApply").emit("click");
  assert.equal(fetcher.calls[3].payload.model, "v5"); assert.deepEqual(fetcher.calls[3].payload.include_tags, ["artist:a"]);
  assert.equal(pickerCard(doc, replacement.key).attributes["aria-pressed"], "true"); assert.deepEqual([...controller.state.selection.keys()], [original.key, second.key]);
  $("worldcupExcludeTags").value = "monochrome"; await $("worldcupExcludeTags").emit("input"); await $("worldcupPickerFilterApply").emit("click");
  assert.match($("worldcupCandidateCount").textContent, /총 0개/); assert.equal($("worldcupStart").disabled, false);
  await controller.start(); assert.deepEqual(fetcher.calls[6].payload.selected_candidates, [original.key, second.key]); assert.equal(fetcher.calls[6].payload.selection_scope, "all");
});

test("automatic selection uses both sources, adds unique groups, and selected-only recommendation sorting stays local", async () => {
  const original = candidate("shared:1", { group_key: "shared:7", recommendation_count: 10 });
  const picked = [candidate("shared:11", { group_key: "shared:7" }), candidate("shared:3", { recommendation_count: 3 }), candidate("confirmed:2")];
  const { doc, $, fetcher, controller } = await creation([original], [response({ count: 1, page: 1, items: [original] }), response({ count: 3, page: 1, items: picked, selection: picked })], 3);
  await pickerCard(doc, original.key).emit("click"); await $("worldcupPickerSharedSource").emit("click"); await $("worldcupAutoSelect").emit("click");
  assert.deepEqual(fetcher.calls[3].payload.sources, ["shared", "confirmed"]); assert.deepEqual([...controller.state.selection.keys()], ["shared:1", "shared:3", "confirmed:2"]);
  $("worldcupPickerSort").value = "recommendation_asc"; await $("worldcupPickerSort").emit("change");
  const visible = descendants($("worldcupPickerGrid"), "button").filter((node) => node.dataset.candidateKey).map((node) => node.dataset.candidateKey);
  assert.deepEqual(visible, ["shared:3", "shared:1", "confirmed:2"]); assert.equal(fetcher.calls.length, 4);
});

test("failed start keeps name filters and selection and shows errors at both start buttons", async () => {
  const { doc, $, fetcher, controller } = await creation([candidate("shared:1"), candidate("shared:2")], [response({ error: "생성 실패" }, 503), response(detail())]);
  await pickerCard(doc, "shared:1").emit("click"); await pickerCard(doc, "shared:2").emit("click");
  $("worldcupName").value = "내 월드컵"; $("worldcupRecommendation").value = "-1";
  await controller.start();
  assert.equal(controller.state.view, "picker"); assert.equal(controller.state.selection.size, 2); assert.equal($("worldcupName").value, "내 월드컵");
  assert.match($("worldcupCreateStatus").textContent, /생성 실패/); assert.match($("worldcupCreateStatusBottom").textContent, /생성 실패/);
  assert.equal($("worldcupStartBottom").disabled, false); await controller.start(); assert.equal(fetcher.calls[3].payload.name, "내 월드컵");
});

test("recommendation Enter applies filters without starting and invalid pending input is validated only on apply", async () => {
  const { doc, $, fetcher } = await creation([candidate("shared:1"), candidate("shared:2")], [response({ count: 1 }), response({ count: 1, page: 1, items: [candidate("shared:1")] })]);
  await pickerCard(doc, "shared:1").emit("click"); await pickerCard(doc, "shared:2").emit("click");
  let prevented = false; $("worldcupRecommendation").value = "3";
  await $("worldcupPickerFilters").emit("keydown", { key: "Enter", target: $("worldcupRecommendation"), preventDefault() { prevented = true; } });
  assert.equal(prevented, true); assert.equal(fetcher.calls[2].url, "/api/style-worldcups/preview"); assert.equal(fetcher.calls.length, 4);
  $("worldcupRecommendation").value = "-1"; await $("worldcupPickerFilterApply").emit("click");
  assert.equal(fetcher.calls.length, 4); assert.match($("worldcupPickerStatus").textContent, /0 이상의 정수/); assert.equal($("worldcupStart").disabled, false);
});

test("initial preview failure allows retry and source controls cannot read uninitialized filters", async () => {
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id);
  const fetcher = queuedFetch([response({ error: "확인 실패" }, 503), response({ count: 0 }), response({ count: 0, page: 1, items: [] })]);
  const controller = createController(doc, fetcher); await controller.newWorldcup();
  await $("worldcupPickerFilterApply").emit("click");
  assert.equal($("worldcupPickerSharedSource").disabled, true); assert.equal($("worldcupPickerMode").disabled, true); assert.equal($("worldcupPickerFilterApply").disabled, false);
  await $("worldcupPickerSharedSource").emit("click"); assert.equal(fetcher.calls.length, 1);
  await $("worldcupPickerFilterApply").emit("click"); assert.equal(controller.state.count, 0); assert.equal($("worldcupPickerSharedSource").disabled, false);
});

test("closing a pending preview permits a fresh creation and ignores the old response", async () => {
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id); let resolveOld;
  const fetcher = queuedFetch([() => new Promise((resolve) => { resolveOld = resolve; }), response([]), response({ count: 1 }), response({ count: 1, page: 1, items: [candidate("shared:2")] })]);
  const controller = createController(doc, fetcher); await controller.newWorldcup();
  const pending = $("worldcupPickerFilterApply").emit("click");
  assert.equal($("worldcupPickerClose").disabled, false); await $("worldcupPickerClose").emit("click");
  await controller.newWorldcup(); await $("worldcupPickerFilterApply").emit("click"); await pickerCard(doc, "shared:2").emit("click");
  resolveOld(response({ count: 99 })); await pending;
  assert.equal(controller.state.count, 1); assert.equal(controller.state.selection.size, 1); assert.equal(controller.state.picker.busy, false); assert.equal(fetcher.calls.length, 4);
});

test("late candidate pages cannot replace a fresh creation after returning to the list", async () => {
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id); let resolveOld;
  const fetcher = queuedFetch([response({ count: 99 }), () => new Promise((resolve) => { resolveOld = resolve; }), response([]), response({ count: 1 }), response({ count: 1, page: 1, items: [candidate("confirmed:2")] })]);
  const controller = createController(doc, fetcher); await controller.newWorldcup();
  const pending = $("worldcupPickerFilterApply").emit("click");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(controller.state.picker.busy, true); await $("worldcupPickerClose").emit("click");
  await controller.newWorldcup(); await $("worldcupPickerFilterApply").emit("click"); await pickerCard(doc, "confirmed:2").emit("click");
  resolveOld(response({ count: 99, page: 1, items: [candidate("shared:99")] })); await pending;
  assert.equal(pickerCard(doc, "shared:99"), undefined); assert.ok(pickerCard(doc, "confirmed:2"));
  assert.deepEqual([...controller.state.selection.keys()], ["confirmed:2"]); assert.equal(controller.state.count, 1);
});

test("all selection beyond 128 uses local sixty-card pages and exact odd-size creation", async () => {
  const items = Array.from({ length: 129 }, (_, index) => candidate("shared:" + (index + 1)));
  const saved = { ...detail(), size: 129, current_match: { left: 0, right: 1, round_size: 256, match_number: 1, matches_in_round: 1, bye_count: 127 } };
  const { doc, $, fetcher, controller } = await creation(items.slice(0, 60), [response({ count: 129, page: 1, items: items.slice(0, 60), selection: items }), response(saved)], 129);
  assert.deepEqual($("worldcupSize").children.map((option) => option.value), ["all", "2", "4", "8", "16", "32", "64", "128"]);
  await $("worldcupAutoSelect").emit("click"); assert.equal(controller.state.selection.size, 129); assert.equal(controller.state.picker.cards.size, 60);
  await $("worldcupPickerNext").emit("click"); assert.equal(controller.state.picker.cards.size, 60); assert.equal(fetcher.calls.length, 3);
  await $("worldcupPickerNext").emit("click"); assert.equal(controller.state.picker.cards.size, 9);
  await controller.start(); assert.equal(fetcher.calls[3].payload.selected_candidates.length, 129); assert.equal(fetcher.calls[3].payload.size, "all");
  assert.match($("worldcupProgress").textContent, /129개 참가.*부전승 127개/);
});

test("candidate side panel keeps the gallery, resizes and navigates images without changing selection", async () => {
  const item = candidate("shared:1", { detail_url: "/api/arca-styles/7" });
  const data = { source_url: "https://example.test/post/7", images: [{ id: 1, image_url: "/arca-style-images/a #한%20.png", base_prompt: "<script>base</script>", character_prompts: [{ prompt: "character", uc: "negative" }] }, { id: 2, image_url: "/arca-style-images/two.png", base_prompt: "second" }] };
  const { doc, $, controller } = await creation([item], [response(data)]); await pickerCard(doc, item.key).emit("click"); $("worldcupName").value = "유지할 이름"; $("style-worldcup-tab").scrollTop = 420;
  const originalCard = pickerCard(doc, item.key);
  await candidateDetailButton(doc, item.key).emit("click"); assert.equal(controller.state.view, "picker");
  assert.equal($("worldcupPicker").hidden, false); assert.equal($("worldcupCandidateDetail").hidden, false);
  assert.equal($("worldcupGalleryLayout").dataset.detailOpen, "true"); assert.equal(pickerCard(doc, item.key), originalCard);
  assert.equal(descendants($("worldcupCandidateDetailImage"), "img")[0].src, "/arca-style-images/a%20%23%ED%95%9C%2520.png");
  assert.equal($("worldcupCandidateDetailBase").textContent, "<script>base</script>"); assert.match($("worldcupCandidateDetailCharacters").textContent, /네거티브: negative/);
  assert.equal($("worldcupCandidateDetailPrev").disabled, true); assert.equal($("worldcupCandidateDetailNext").disabled, false);
  const firstImage = descendants($("worldcupCandidateDetailImage"), "img")[0];
  $("worldcupCandidateDetailSize").value = "40"; await $("worldcupCandidateDetailSize").emit("input");
  assert.equal($("worldcupCandidateDetailSizeValue").textContent, "40%");
  assert.equal($("worldcupCandidateDetailImage").style["--worldcup-detail-image-size"], "40%");
  assert.equal(descendants($("worldcupCandidateDetailImage"), "img")[0], firstImage);
  for (const id of ["worldcupCandidateDetailSize", "worldcupIncludeTags", "worldcupModel"]) {
    let prevented = false;
    await doc.emit("keydown", { key: "ArrowRight", target: $(id), preventDefault() { prevented = true; } });
    assert.equal(prevented, false); assert.equal(controller.state.candidateDetail.index, 0);
  }
  await doc.emit("keydown", { key: "ArrowRight", target: $("worldcupCandidateDetailTitle") });
  assert.equal(controller.state.candidateDetail.index, 1); assert.equal($("worldcupCandidateDetailBase").textContent, "second");
  assert.equal($("worldcupCandidateDetailNext").disabled, true);
  const lastImage = descendants($("worldcupCandidateDetailImage"), "img")[0];
  await doc.emit("keydown", { key: "ArrowRight" }); assert.equal(descendants($("worldcupCandidateDetailImage"), "img")[0], lastImage);
  await $("worldcupCandidateDetailPrev").emit("click"); assert.equal(controller.state.candidateDetail.index, 0);
  await $("worldcupCandidateDetailThumbnails").children[1].emit("click"); assert.equal($("worldcupCandidateDetailBase").textContent, "second");
  await doc.emit("keydown", { key: "ArrowLeft" }); assert.equal(controller.state.candidateDetail.index, 0);
  await doc.emit("keydown", { key: "Escape" });
  assert.equal($("worldcupCandidateDetail").hidden, true); assert.equal($("worldcupGalleryLayout").dataset.detailOpen, "false");
  assert.equal(doc.activeElement, candidateDetailButton(doc, item.key));
  assert.equal($("worldcupName").value, "유지할 이름"); assert.equal($("style-worldcup-tab").scrollTop, 420); assert.equal(controller.state.selection.size, 1);
  await doc.emit("keydown", { key: "ArrowRight" }); assert.equal(controller.state.candidateDetail.index, 0);
});

test("late detail responses cannot replace another card or reopen a closed side panel", async () => {
  const items = [candidate("shared:1", { detail_url: "/api/arca-styles/1" }), candidate("shared:2", { detail_url: "/api/arca-styles/2" })];
  const data = (id) => ({ images: [{ id, image_url: "/arca-style-images/" + id + ".png", base_prompt: "image " + id }] });
  let resolveFirst; let resolveClosed;
  const { doc, $, controller } = await creation(items, [() => new Promise((resolve) => { resolveFirst = resolve; }), response(data(2)), () => new Promise((resolve) => { resolveClosed = resolve; })]);
  const pendingFirst = candidateDetailButton(doc, "shared:1").emit("click");
  await candidateDetailButton(doc, "shared:2").emit("click");
  resolveFirst(response(data(1))); await pendingFirst;
  assert.equal($("worldcupCandidateDetailBase").textContent, "image 2");
  const pendingClosed = candidateDetailButton(doc, "shared:1").emit("click");
  await $("worldcupCandidateDetailBack").emit("click");
  resolveClosed(response(data(1))); await pendingClosed;
  assert.equal($("worldcupCandidateDetail").hidden, true); assert.equal(controller.state.view, "picker");
  assert.equal(controller.state.selection.size, 0); assert.equal(controller.state.candidateDetail.images.length, 0);
});

test("failed save preserves current match and a double click sends only one request", async () => {
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id);
  let reject;
  const fetcher = queuedFetch([response(detail()), () => new Promise((_, fail) => { reject = fail; })]);
  const controller = createController(doc, fetcher); await controller.open(9);
  const previous = controller.state.detail;
  const firstCard = $("worldcupMatch").children[0];
  const pending = controller.choose(1);
  assert.equal(descendants($("worldcupMatch"), "button")[0].disabled, true);
  await controller.choose(0); assert.equal(fetcher.calls.length, 2);
  reject(new Error("연결이 끊겼습니다.")); await pending;
  assert.equal(controller.state.detail, previous);
  assert.equal($("worldcupMatch").children[0], firstCard);
  assert.equal(descendants($("worldcupMatch"), "button")[0].disabled, false);
  assert.match($("worldcupStatus").textContent, /연결이 끊겼습니다/);
});

test("revision conflict fetches saved latest state without replaying selection", async () => {
  const doc = fakeDocument();
  const latest = detail(1, true);
  const fetcher = queuedFetch([response(detail()), response({ error: "이전 상태" }, 409), response(latest)]);
  const controller = createController(doc, fetcher); await controller.open(9); await controller.choose(0);
  assert.deepEqual(fetcher.calls.map((call) => call.url), ["/api/style-worldcups/9", "/api/style-worldcups/9/choose", "/api/style-worldcups/9"]);
  assert.equal(controller.state.detail.winner, 1);
  assert.equal(controller.state.detail, latest);
  assert.equal(controller.state.detail.participants, latest.participants);
  assert.match(doc.getElementById("worldcupStatus").textContent, /최신 진행 상태/);
});

test("compact choices update next-match images and winner while retaining all historical participant titles", async () => {
  const doc = fakeDocument(); const $ = (id) => doc.getElementById(id);
  const initial = {
    ...detail(), size: 4, participants: [participant(0), participant(1), participant(2), participant(3)],
    current_match: { left: 0, right: 1, round_size: 4, match_number: 1, matches_in_round: 2 },
  };
  const firstHistory = [{ round_size: 4, left: 0, right: 1, winner: 0 }];
  const secondHistory = [...firstHistory, { round_size: 4, left: 2, right: 3, winner: 3 }];
  const compactNext = {
    ...initial, revision: 1, updated_at: "2026-10-18T01:00:00Z", participants_partial: true,
    participants: [participant(2, { available: false, image_url: null }), participant(3, { image_url: "/api/local-images/updated-3" })],
    current_match: { left: 2, right: 3, round_size: 4, match_number: 2, matches_in_round: 2 }, history: firstHistory,
  };
  const compactFinal = {
    ...compactNext, revision: 2, participants: [participant(0), participant(3, { image_url: "/api/local-images/updated-3" })],
    current_match: { left: 0, right: 3, round_size: 2, match_number: 1, matches_in_round: 1 }, history: secondHistory,
  };
  const compactCompleted = {
    ...compactFinal, revision: 3, status: "completed", current_match: null, winner: 3,
    participants: [participant(3, { image_url: "/api/local-images/winner-3", title: "최종 우승 그림" })],
    history: [...secondHistory, { round_size: 2, left: 0, right: 3, winner: 3 }],
  };
  const fetcher = queuedFetch([response(initial), response(compactNext), response(compactFinal), response(compactCompleted)]);
  const controller = createController(doc, fetcher); await controller.open(9);
  await descendants($("worldcupMatch"), "button")[0].emit("click");
  assert.deepEqual(fetcher.calls[1].payload, { revision: 0, winner: 0, compact: true });
  assert.equal(controller.state.detail.participants.length, 4);
  assert.equal(Object.hasOwn(controller.state.detail, "participants_partial"), false);
  assert.equal(controller.state.detail.updated_at, compactNext.updated_at);
  assert.equal(controller.state.detail.history, firstHistory);
  assert.equal(controller.state.detail.participants[0], initial.participants[0]);
  assert.equal(controller.state.detail.participants[2].available, false);
  assert.equal(descendants($("worldcupMatch"), "img").length, 1);
  assert.equal(descendants($("worldcupMatch"), "img")[0].src, "/api/local-images/updated-3");
  assert.match($("worldcupMatch").textContent, /이미지가 없습니다/);
  await descendants($("worldcupMatch"), "button")[1].emit("click");
  assert.equal(controller.state.detail.participants.length, 4);
  assert.equal(controller.state.detail.history, secondHistory);
  assert.equal(descendants($("worldcupMatch"), "img").length, 2);
  await descendants($("worldcupMatch"), "button")[1].emit("click");
  assert.deepEqual(fetcher.calls[3].payload, { revision: 2, winner: 3, compact: true });
  assert.equal(controller.state.detail.participants.length, 4);
  assert.equal(Object.hasOwn(controller.state.detail, "participants_partial"), false);
  assert.equal(controller.state.detail.status, "completed");
  assert.equal(controller.state.detail.history, compactCompleted.history);
  assert.equal(descendants($("worldcupResult"), "img")[0].src, "/api/local-images/winner-3");
  assert.match($("worldcupResult").textContent, /최종 우승 그림/);
  assert.match($("worldcupHistoryList").textContent, /그림 0 \/ 그림 1/);
  assert.match($("worldcupHistoryList").textContent, /그림 2 \/ 최종 우승 그림/);
  assert.equal($("worldcupHistoryList").children.length, 3);
});

test("a fresh controller can resume a saved cup, and missing images and unsafe links remain safe", async () => {
  const doc = fakeDocument(); const saved = detail();
  saved.participants[0] = participant(0, { available: false, source_url: "javascript:alert(1)", title: "<img onerror=alert(1)>" });
  saved.participants[1] = participant(1, { image_url: "https://example.test/remote.png" });
  const fetcher = queuedFetch([response([{ id: 9, name: "저장된 월드컵", size: 2, status: "playing" }]), response(saved)]);
  const controller = createController(doc, fetcher); await controller.load();
  await descendants(doc.getElementById("worldcupList"), "button")[0].emit("click");
  assert.equal(controller.state.detail.id, 9);
  assert.equal(descendants(doc.getElementById("worldcupMatch"), "img").length, 0);
  assert.equal(descendants(doc.getElementById("worldcupMatch"), "a").length, 1);
  assert.match(doc.getElementById("worldcupMatch").textContent, /<img onerror=alert\(1\)>/);
  assert.match(doc.getElementById("worldcupMatch").textContent, /이미지가 없습니다/);
});

test("folder gallery includes playing thumbnails, winner first, compact missing cells, and whole-folder controls", async () => {
  const doc = fakeDocument();
  const cups = [
    { id: 1, name: "진행 중 폴더", size: 5, status: "playing", preview_participants: [participant(0), participant(1), participant(2), participant(3)] },
    { id: 2, name: "완료 폴더", size: 5, status: "completed", winner: participant(3), preview_participants: [participant(0), participant(1), participant(2), participant(3)] },
    { id: 3, name: "누락 폴더", size: 2, status: "playing", preview_participants: [participant(0, { available: false })] },
    { id: 4, name: "빈 미리보기", size: 2, status: "playing", preview_participants: [] },
  ];
  assert.deepEqual(previewParticipants(cups[1]).map((item) => item.ordinal), [3, 0, 1, 2]);
  const fetcher = queuedFetch([response(cups), response(detail())]);
  const controller = createController(doc, fetcher); await controller.load();
  const cards = doc.getElementById("worldcupList").children;
  assert.equal(descendants(cards[0], "img").length, 4);
  assert.equal(descendants(cards[1], "img")[0].src, "/api/local-images/3");
  assert.equal(descendants(cards[1], "img").length, 4);
  assert.match(cards[0].textContent, /5개 참가/);
  assert.doesNotMatch(cards[0].textContent, /5강/);
  assert.match(cards[2].textContent, /이미지 없음/);
  assert.match(cards[3].textContent, /이미지 없음/);
  for (const card of cards) {
    const button = descendants(card, "button")[0];
    assert.equal(button.className, "worldcup-folder-open");
    assert.equal(descendants(button, "button,a").length, 0);
  }
  await descendants(cards[0], "button")[0].emit("click");
  assert.equal(fetcher.calls[1].url, "/api/style-worldcups/1");
  assert.equal(controller.state.view, "detail");
});
