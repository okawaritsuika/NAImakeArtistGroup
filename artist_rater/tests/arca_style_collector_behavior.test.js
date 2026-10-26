const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

test("statistics model tabs ignore late responses from the previous model", async () => {
  const pending = [], rendered = [], filter = { value: "v5" };
  const tabs = ["v4.5", "v5", "all"].map(model => ({
    dataset: { arcaStatisticsModel: model }, classList: { toggle() {} },
    setAttribute(name, value) { this[name] = value; },
  }));
  const context = vm.createContext({ URLSearchParams, setInterval: () => 1, clearInterval() {}, document: {
    addEventListener() {}, querySelectorAll: () => tabs,
    getElementById: id => id === "arcaStatisticsModelFilter" ? filter : null,
  }});
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/arca_style_collector.js"), "utf8"), context);
  context.arcaFetch = url => new Promise(resolve => pending.push({ url, resolve }));
  context.renderArcaStyleStatistics = result => rendered.push(result);
  context.arcaSetStatus = () => {};
  const old = context.selectArcaStatisticsModel("v4.5");
  const latest = context.selectArcaStatisticsModel("v5");
  assert.match(pending[0].url, /model=v4.5/);
  assert.match(pending[1].url, /model=v5/);
  pending[1].resolve({ model: "v5" });
  await latest;
  pending[0].resolve({ model: "v4.5" });
  await old;
  assert.deepEqual(rendered.filter(row => row.model), [{ model: "v5" }]);
  assert.equal(tabs[1]["aria-selected"], "true");
  assert.equal(tabs[0].tabIndex, -1);
});

test("statistics loading, failure and retry do not render a false empty result", async () => {
  const nodes = new Map(), timers = new Map(), rendered = [], pending = [];
  let timerId = 0;
  function element(id) {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, { value: id === "arcaStatisticsModelFilter" ? "v5" : "", textContent: "", classes,
        classList: { toggle(name, active) { active ? classes.add(name) : classes.delete(name); } },
        setAttribute(name, value) { this[name] = value; },
      });
    }
    return nodes.get(id);
  }
  const context = vm.createContext({ URLSearchParams,
    setInterval: fn => { timers.set(++timerId, fn); return timerId; },
    clearInterval: id => timers.delete(id),
    document: { addEventListener() {}, getElementById: element },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/arca_style_collector.js"), "utf8"), context);
  context.arcaFetch = () => new Promise((resolve, reject) => pending.push({ resolve, reject }));
  context.renderArcaStyleStatistics = result => rendered.push(result);
  context.arcaSetStatus = (id, text) => { element(id).textContent = text; };
  const loading = context.loadArcaStyleStatistics();
  assert.equal(rendered.length, 0);
  assert.equal(element("arcaStatisticsFeedbackTitle").textContent, "V5 통계 집계 중");
  assert.equal(element("arcaStatisticsContent").classes.has("hidden"), true);
  assert.equal(element("arcaStyleStatistics")["aria-busy"], "true");
  [...timers.values()][0]();
  assert.match(element("arcaStatisticsElapsed").textContent, /초 경과/);
  pending[0].reject(new Error("연결 실패"));
  await loading;
  assert.equal(rendered.length, 0);
  assert.equal(element("retryArcaStatistics").classes.has("hidden"), false);
  assert.equal(element("arcaStyleStatistics")["aria-busy"], "false");
  assert.equal(timers.size, 0);
  const retry = context.loadArcaStyleStatistics();
  pending[1].resolve({ analyzed_image_count: 0 });
  await retry;
  assert.equal(rendered.length, 1);
  assert.equal(element("arcaStatisticsContent").classes.has("hidden"), false);
  assert.equal(element("arcaStatisticsFeedback").classes.has("hidden"), true);
  assert.equal(timers.size, 0);
});
const {
  normalizeArcaPayload, arcaSummaryText, collectionProgress, durationText,
  etaText, collectionCountsText, groupTitle, promptSection,
  formatBytes, imageRestoreEstimateText, imageDownloadSummary,
  promptKindClass,
  imagePromptFields,
  normalizeArcaUrlPayload,
  arcaBrowserSessionText,
  isArcaBrowserSessionPending,
  arcaListQuery,
  formatArcaLocalDate,
  fillMissingArcaDates,
  arcaBrowserSessionAction,
  isArcaCollectionBusy,
  shouldRefreshArcaBrowserSession,
  arcaCoverageQuery,
  arcaCoverageText,
  normalizeArcaStatisticRows,
  arcaStatisticsSummary,
  arcaStatisticEntryText,
  formatArcaWeight,
  filterArcaStatisticRows,
  filterAndSortArcaStatisticRows,
  paginateArcaStatisticRows,
  arcaTagDetailQuery,
  arcaSequenceDetailQuery,
  arcaStatisticsQuery,
  arcaRecommendationPreset,
  randomArcaStatisticsSamples,
  formatArcaRecommendation,
  hasArcaDependencyArtists,
  normalizeArcaModel,
  arcaModelDisplayName,
  shouldOpenArcaCollectionPanel,
  imageGenerationSettingsText,
  arcaStyleDetailQuery,
} = require("../static/arca_style_collector.js");

test("Arca list query sends image-model filters without changing the all default", () => {
  assert.equal(arcaListQuery({ model: "all" }).has("model"), false);
  assert.equal(arcaListQuery({ model: "v5" }).get("model"), "v5");
  assert.equal(arcaListQuery({ model: "v4.5" }).get("model"), "v4.5");
  assert.equal(arcaListQuery({ model: "nai-diffusion-4-5-curated" }).get("model"), "nai-diffusion-4-5-curated");
  assert.equal(arcaStyleDetailQuery("all").has("model"), false);
  assert.equal(arcaStyleDetailQuery("unknown").get("model"), "unknown");
  assert.equal(normalizeArcaModel("NovelAI Diffusion V5 Full"), "nai-diffusion-5-full");
  assert.equal(arcaModelDisplayName("nai-diffusion-5-curated"), "V5 Curated");
});

test("Arca model badges collapse NovelAI source build suffixes without mixing generations", () => {
  for (const value of ["NovelAI Diffusion V5 70AB5786", "NovelAI Diffusion V5 93F4BD30", "NovelAI Diffusion V5 Full Medium", "nai-diffusion-5-full-medium"]) {
    assert.equal(normalizeArcaModel(value), "nai-diffusion-5-full-medium");
    assert.equal(arcaModelDisplayName(value), "V5 Full Medium");
  }
  assert.equal(normalizeArcaModel("NovelAI Diffusion V4.5 4BDE2A90"), "nai-diffusion-4-5-full");
  assert.equal(normalizeArcaModel("NovelAI Diffusion V4.5 Curated 4BDE2A90"), "nai-diffusion-4-5-curated");
  assert.equal(normalizeArcaModel("NovelAI Diffusion V5 4BDE2A90"), "nai-diffusion-5-full");
  assert.equal(normalizeArcaModel("NovelAI Diffusion V5 Curated 4BDE2A90"), "nai-diffusion-5-curated");
  assert.notEqual(normalizeArcaModel("NovelAI Diffusion V4.5 4BDE2A90"), "nai-diffusion-5-full");
  assert.notEqual(normalizeArcaModel("NovelAI Diffusion V5 4BDE2A90"), "nai-diffusion-4-5-full");
});

test("empty collection dates default to the local calendar day", () => {
  const localDate = new Date(2026, 0, 2, 23, 59, 59);
  assert.equal(formatArcaLocalDate(localDate), "2026-01-02");
  assert.deepEqual(fillMissingArcaDates({ start_date: "", end_date: "" }, "2026-01-02"), {
    start_date: "2026-01-02",
    end_date: "2026-01-02",
  });
  assert.deepEqual(fillMissingArcaDates({ start_date: "2025-12-30", end_date: "" }, "2026-01-02"), {
    start_date: "2025-12-30",
    end_date: "2026-01-02",
  });
});

test("browser login transition resumes one pending collection and clears failures", () => {
  assert.equal(arcaBrowserSessionAction({ state: "opening" }, true), "poll");
  assert.equal(arcaBrowserSessionAction({ state: "waiting" }, true), "poll");
  assert.equal(arcaBrowserSessionAction({ connected: true }, true), "resume");
  assert.equal(arcaBrowserSessionAction({ connected: true }, false), "settled");
  assert.equal(arcaBrowserSessionAction({ state: "failed" }, true), "clear");
  assert.equal(arcaBrowserSessionAction({ state: "cancelled" }, true), "clear");
  assert.equal(isArcaCollectionBusy({ collecting: false, pendingCollectionPayload: { tabs: ["R18_NAI"] } }), true);
  assert.equal(isArcaCollectionBusy({ collecting: true, pendingCollectionPayload: null }), true);
  assert.equal(isArcaCollectionBusy({ collecting: false, pendingCollectionPayload: null }), false);
});

test("browser session refreshes when the app becomes visible again", () => {
  assert.equal(shouldRefreshArcaBrowserSession("focus", "visible"), true);
  assert.equal(shouldRefreshArcaBrowserSession("visibilitychange", "visible"), true);
  assert.equal(shouldRefreshArcaBrowserSession("visibilitychange", "hidden"), false);
});

test("collection payload normalizes checked tabs and limits", () => {
  assert.deepEqual(normalizeArcaPayload({ keyword: " x ", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: "5", max_posts: "80" }), {
    keyword: "x", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: 5, max_posts: 80,
  });
});

test("list query keeps paging size and minimum recommendations", () => {
  const query = arcaListQuery({ q: "x", metadata: "all", sort: "posted_asc", page: 3, per_page: 20, recommendation_min: 10 });
  assert.equal(query.get("sort"), "posted_asc");
  assert.equal(query.get("page"), "3");
  assert.equal(query.get("per_page"), "20");
  assert.equal(query.get("recommendation_min"), "10");
  assert.equal(arcaListQuery({}).toString(), "q=&metadata=all&sort=posted_desc&page=1&per_page=50");
});

test("coverage query keeps the selected keyword and repeated tabs", () => {
  const query = arcaCoverageQuery({
    keyword: "  artist style ", tabs: ["NAI", "R18_NAI"], start_date: "2026-07-01", end_date: "2026-07-12",
    max_pages: 5, max_posts: 80,
  });
  assert.equal(query.get("keyword"), "artist style");
  assert.deepEqual(query.getAll("tabs"), ["NAI", "R18_NAI"]);
  assert.equal(query.get("start_date"), "2026-07-01");
  assert.equal(arcaCoverageText({ coverage: [] }), "이 조건으로 완료한 수집 기록이 없습니다.");
  assert.equal(arcaCoverageText({ coverage: [
    { start_date: "2026-07-01", end_date: "2026-07-03" },
    { start_date: "2026-07-12", end_date: "2026-07-12" },
  ] }), "완료한 범위: 2026-07-01 ~ 2026-07-03, 2026-07-12");
});

test("statistics helpers keep every valid artist and describe their sources", () => {
  const rows = normalizeArcaStatisticRows([
    { tag: "artist:foo", count: "8", percentage: "40" },
    { tag: "", count: 99, percentage: 99 },
    ...Array.from({ length: 10 }, (_value, index) => ({ tag: `tag-${index}`, count: index + 1, percentage: index + 0.25 })),
  ]);
  assert.equal(rows.length, 11);
  assert.deepEqual(rows[0], {
    tag: "artist:foo", count: 8, percentage: 40,
    average_weight: null, median_weight: null, max_weight: null, dominant_weight_range: "",
    representative_image: null,
    average_recommendations: null, median_recommendations: null, max_recommendations: null,
  });
  assert.equal(rows[rows.length - 1].tag, "tag-9");
  assert.equal(filterArcaStatisticRows(rows, "TAG-2")[0].tag, "tag-2");
  assert.equal(formatArcaWeight(1.23456), "1.235");
  assert.equal(arcaTagDetailQuery("artist", "artist:foo", 12).toString(), "kind=artist&tag=artist%3Afoo&limit=12");
  assert.equal(
    arcaTagDetailQuery("artist", "artist:foo", 12, { recommendation_min: 30 }).get("recommendation_min"),
    "30",
  );
  assert.equal(arcaStatisticsSummary({ analyzed_image_count: 12, analyzed_post_count: 4 }), "이미지 프롬프트 12개 · 게시글 4개 분석");
  assert.equal(arcaStatisticsSummary({ analyzed_image_count: 0, analyzed_post_count: 0 }), "집계할 이미지 프롬프트가 없습니다.");
  assert.equal(arcaStatisticEntryText({ count: 3, percentage: 12.5 }), "이미지 3개 · 12.5%");
});

test("statistics can filter dominant ranges and sort weights", () => {
  const entries = [
    { tag: "artist:low", count: 10, average_weight: 0.8, dominant_weight_range: "0.80–0.99" },
    { tag: "artist:high", count: 2, average_weight: 1.8, dominant_weight_range: "1.50–1.99" },
    { tag: "artist:mid", count: 5, average_weight: 1.1, dominant_weight_range: "1.01–1.19" },
  ];
  assert.deepEqual(
    filterAndSortArcaStatisticRows(entries, { range: "1.50–1.99", sort: "range_desc" }).map((entry) => entry.tag),
    ["artist:high"],
  );
  assert.deepEqual(
    filterAndSortArcaStatisticRows(entries, { sort: "weight_desc" }).map((entry) => entry.tag),
    ["artist:high", "artist:mid", "artist:low"],
  );
  assert.deepEqual(
    filterAndSortArcaStatisticRows(entries, { sort: "tag_desc" }).map((entry) => entry.tag),
    ["artist:mid", "artist:low", "artist:high"],
  );
  assert.deepEqual(paginateArcaStatisticRows(entries, 2, 2), {
    rows: [entries[2]], page: 2, perPage: 2, total: 3, totalPages: 2,
  });
});

test("statistics recommendation filters and sorting keep direct ranges", () => {
  assert.equal(arcaStatisticsQuery({ recommendation_min: 30, recommendation_max: 100 }).toString(), "recommendation_min=30&recommendation_max=100");
  assert.deepEqual(arcaRecommendationPreset("50"), { recommendation_min: "50", recommendation_max: "" });
  assert.deepEqual(arcaRecommendationPreset("all"), { recommendation_min: "", recommendation_max: "" });
  assert.equal(formatArcaRecommendation(12.34), "12.3");
  const rows = filterAndSortArcaStatisticRows([
    { tag: "artist:common", count: 20, average_recommendations: 10 },
    { tag: "artist:popular", count: 2, average_recommendations: 80 },
  ], { sort: "recommendation_desc" });
  assert.deepEqual(rows.map((entry) => entry.tag), ["artist:popular", "artist:common"]);
});

test("statistics model filters are omitted for all and passed to every statistics detail query", () => {
  assert.equal(arcaStatisticsQuery({ model: "all" }).has("model"), false);
  assert.equal(arcaStatisticsQuery({ model: "v5" }).get("model"), "v5");
  assert.equal(arcaStatisticsQuery({ model: "v4.5" }).get("model"), "v4.5");
  assert.equal(arcaTagDetailQuery("artist", "artist:foo", 12, { model: "v5" }).get("model"), "v5");
  assert.equal(arcaSequenceDetailQuery(["masterpiece"], 30, { model: "v4.5" }).get("model"), "v4.5");
});

test("quality sequence detail query preserves tag order", () => {
  const query = arcaSequenceDetailQuery(["masterpiece", "best quality"], 30);
  assert.deepEqual(query.getAll("tag"), ["masterpiece", "best quality"]);
  assert.equal(query.get("limit"), "30");
});

test("random statistics samples only return entries with representative images", () => {
  const entries = [
    { tag: "a", representative_image: { image_url: "/a.png" } },
    { tag: "missing" },
    { tag: "b", representative_image: { image_url: "/b.png" } },
  ];
  assert.deepEqual(randomArcaStatisticsSamples(entries, 1, () => 0).map((entry) => entry.tag), ["b"]);
});

test("browser session status is readable without exposing details", () => {
  assert.equal(arcaBrowserSessionText({ connected: false }), "브라우저 로그인 연결 안 됨");
  assert.equal(arcaBrowserSessionText({ connected: true, browser: "Chrome" }), "Chrome 로그인 연결됨");
  assert.equal(arcaBrowserSessionText({ connected: false, error: "가져오기 실패" }), "가져오기 실패");
  assert.equal(arcaBrowserSessionText({ state: "opening", message: "로그인 창 여는 중…" }), "로그인 창 여는 중…");
  assert.equal(arcaBrowserSessionText({ state: "waiting", message: "로그인해 주세요" }), "로그인해 주세요");
  assert.equal(isArcaBrowserSessionPending({ state: "opening" }), true);
  assert.equal(isArcaBrowserSessionPending({ state: "waiting" }), true);
  assert.equal(isArcaBrowserSessionPending({ state: "connected" }), false);
  assert.equal(isArcaBrowserSessionPending({ state: "failed" }), false);
});

test("selected image projects into three readable prompt fields", () => {
  assert.deepEqual(imagePromptFields({
    image_url: "/arca-style-images/example.png",
    base_prompt: "artist:foo, watercolor",
    negative_prompt: "lowres, blurry",
    character_prompts: [{ prompt: "1girl, blue hair" }, { prompt: "1boy, black hair" }],
  }), {
    image_url: "/arca-style-images/example.png",
    base: "artist:foo, watercolor",
    negative: "lowres, blurry",
    character: "1girl, blue hair\n\n1boy, black hair",
  });
});

test("selected image generation settings stay readable when metadata is incomplete", () => {
  assert.equal(imageGenerationSettingsText({ sampler: "k_euler_ancestral", steps: 28, scale: 5, cfg_rescale: 0.3 }), "Sampler: k_euler_ancestral · Steps: 28 · CFG Scale: 5 · CFG Rescale: 0.3");
  assert.equal(imageGenerationSettingsText({ sampler: "", steps: null, scale: null, cfg_rescale: "" }), "Sampler: Unknown · Steps: ? · CFG Scale: ? · CFG Rescale: ?");
  assert.equal(imageGenerationSettingsText({ sampler: "euler", steps: 0, scale: 0, cfg_rescale: 0 }), "Sampler: euler · Steps: 0 · CFG Scale: 0 · CFG Rescale: 0");
});

test("direct URL payload trims one article link", () => {
  assert.deepEqual(normalizeArcaUrlPayload("  https://arca.live/b/aiart/174457459  "), {
    source_url: "https://arca.live/b/aiart/174457459",
  });
});

test("WebP compression is opt-in for search and direct-link collection", () => {
  assert.equal(normalizeArcaPayload({}).webp_compress, undefined);
  assert.equal(normalizeArcaPayload({ webp_compress: true }).webp_compress, true);
  assert.equal(normalizeArcaUrlPayload('https://arca.live/b/aiart/123', true).webp_compress, true);
  assert.equal(normalizeArcaUrlPayload('https://arca.live/b/aiart/123', false).webp_compress, undefined);
});

test("summary explains when an existing search was skipped", () => {
  assert.equal(arcaSummaryText({ skipped_existing: true }), "이미 검색한 범위입니다. 저장된 목록을 표시합니다.");
  assert.equal(arcaSummaryText({ error: "partial collection" }), "partial collection");
});

function statsRefreshContext() {
  const nodes = new Map();
  const modalControls = ["closeArcaStatsRefresh", "arcaStatsRefreshModel", "cancelArcaStatsRefresh", "startArcaStatsRefresh"];
  const document = {
    activeElement: null, addEventListener() {}, querySelector: () => null,
    querySelectorAll: selector => selector === "[data-close-arca-stats-refresh]" ? [nodes.get("statsBackdrop")] : [],
    getElementById: id => nodes.get(id) || null,
  };
  for (const id of ["refreshArcaStats", "collectArcaStyles", "arcaCollectorStatus", "arcaCollectionProgressPanel",
    "arcaCollectionState", "arcaCollectionProgress", "arcaCollectionCounts", "arcaCollectionElapsed", "arcaCollectionEta",
    "pauseArcaCollection", "resumeArcaCollection", "stopArcaCollection", "arcaStatsRefreshModal", "arcaStatsRefreshStatus",
    "statsBackdrop", ...modalControls]) {
    const classes = new Set(id === "arcaStatsRefreshModal" ? ["hidden"] : []);
    nodes.set(id, { id, value: id === "arcaStatsRefreshModel" ? "v5" : "", disabled: false, textContent: "", dataset: {}, listeners: {}, classes,
      addEventListener(name, callback) { this.listeners[name] = callback; },
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
      focus() { if (!this.disabled) document.activeElement = this; },
      contains(element) { return this === element || (id === "arcaStatsRefreshModal" && modalControls.includes(element?.id)); },
      classList: { toggle(name, active) { active ? classes.add(name) : classes.delete(name); },
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); }, contains(name) { return classes.has(name); } },
    });
  }
  const context = vm.createContext({ URLSearchParams, setTimeout: () => 1, clearTimeout() {}, document });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/arca_style_collector.js"), "utf8"), context);
  context.loadArcaBrowserSession = async () => {};
  context.loadArcaSearchCoverage = async () => {};
  context.loadCurrentArcaCollectionJob = async () => {};
  context.applyArcaCardSize = () => {};
  context.bindArcaCollector();
  return { context, nodes, document };
}

function statsModalKey(key, shiftKey = false) {
  return { key, shiftKey, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } };
}

test("stats refresh opens with V5 and all cancel paths retain the model without making a request", () => {
  const { context, nodes, document } = statsRefreshContext();
  context.arcaFetch = () => assert.fail("opening or cancelling must not make a request");
  const modal = nodes.get("arcaStatsRefreshModal"), model = nodes.get("arcaStatsRefreshModel");
  const trigger = nodes.get("refreshArcaStats");
  trigger.listeners.click();
  assert.equal(modal.classes.has("hidden"), false);
  assert.equal(model.value, "v5");
  assert.equal(document.activeElement, model);
  model.value = "v4.5";
  model.listeners.change({ target: model });
  for (const closeId of ["cancelArcaStatsRefresh", "closeArcaStatsRefresh", "statsBackdrop"]) {
    nodes.get(closeId).listeners.click();
    assert.equal(modal.classes.has("hidden"), true);
    assert.equal(document.activeElement, trigger);
    trigger.listeners.click();
    assert.equal(model.value, "v4.5");
  }
  const escape = statsModalKey("Escape");
  modal.listeners.keydown(escape);
  assert.equal(escape.prevented, true);
  assert.equal(escape.stopped, true);
  assert.equal(modal.classes.has("hidden"), true);
  assert.equal(document.activeElement, trigger);
});

test("stats refresh modal traps Tab and Shift Tab within its controls", () => {
  const { nodes, document } = statsRefreshContext();
  nodes.get("refreshArcaStats").listeners.click();
  const modal = nodes.get("arcaStatsRefreshModal");
  const first = nodes.get("closeArcaStatsRefresh"), last = nodes.get("startArcaStatsRefresh");
  last.focus();
  const forward = statsModalKey("Tab");
  modal.listeners.keydown(forward);
  assert.equal(forward.prevented, true);
  assert.equal(document.activeElement, first);
  const backward = statsModalKey("Tab", true);
  modal.listeners.keydown(backward);
  assert.equal(backward.prevented, true);
  assert.equal(document.activeElement, last);
});

test("stats refresh confirmation sends the selected model once and locks closing during the request", async () => {
  const { context, nodes, document } = statsRefreshContext();
  const requests = [], polled = [];
  let finishRequest;
  context.arcaFetch = (url, options) => {
    requests.push({ url, ...options });
    return new Promise(resolve => { finishRequest = resolve; });
  };
  context.pollArcaCollectionJob = async id => polled.push(id);
  context.importArcaBrowserSession = async () => assert.fail("public-only refresh must not require login");
  const refreshButton = nodes.get("refreshArcaStats");
  const modal = nodes.get("arcaStatsRefreshModal");
  refreshButton.listeners.click();
  assert.equal(requests.length, 0);
  nodes.get("arcaStatsRefreshModel").value = "nai-diffusion-5-full-medium";
  const started = nodes.get("startArcaStatsRefresh").listeners.click();
  assert.equal(refreshButton.disabled, true);
  assert.equal(nodes.get("collectArcaStyles").disabled, true);
  assert.equal(vm.runInContext("arcaState.collecting", context), true);
  assert.equal(nodes.get("arcaStatsRefreshStatus").textContent, "선택한 모델의 저장된 글을 확인하는 중…");
  assert.equal(modal["aria-busy"], "true");
  assert.equal(nodes.get("arcaStatsRefreshModel").disabled, true);
  assert.equal(document.activeElement, modal);
  await refreshButton.listeners.click();
  await nodes.get("startArcaStatsRefresh").listeners.click();
  for (const id of ["closeArcaStatsRefresh", "cancelArcaStatsRefresh", "statsBackdrop"]) nodes.get(id).listeners.click();
  modal.listeners.keydown(statsModalKey("Escape"));
  assert.equal(modal.classes.has("hidden"), false);
  const tab = statsModalKey("Tab");
  modal.listeners.keydown(tab);
  assert.equal(tab.prevented, true);
  assert.equal(document.activeElement, modal);
  assert.deepEqual(requests, [{ url: "/api/arca-styles/refresh-stats", method: "POST", body: '{"model":"nai-diffusion-5-full-medium"}' }]);
  finishRequest({ job_id: 73, status: "queued" });
  await started;
  assert.deepEqual(polled, [73]);
  assert.equal(vm.runInContext("arcaState.activeJobId", context), 73);
  assert.equal(modal.classes.has("hidden"), true);
  assert.equal(document.activeElement, nodes.get("arcaCollectionProgressPanel"));
});

test("stats refresh respects pending collection and keeps a failed model selection ready for retry", async () => {
  const { context, nodes, document } = statsRefreshContext();
  let requests = 0;
  context.arcaFetch = async (url, options) => {
    requests++;
    assert.equal(JSON.parse(options.body).model, "all");
    if (requests === 1) throw new Error("Chrome 로그인을 연결해 주세요.");
    return { job_id: 76, status: "queued" };
  };
  context.pollArcaCollectionJob = async () => {};
  vm.runInContext("arcaState.pendingCollectionPayload = { tabs: ['R18_NAI'] }", context);
  await nodes.get("refreshArcaStats").listeners.click();
  assert.equal(requests, 0);
  assert.equal(nodes.get("arcaStatsRefreshModal").classes.has("hidden"), true);
  vm.runInContext("arcaState.pendingCollectionPayload = null", context);
  await nodes.get("refreshArcaStats").listeners.click();
  nodes.get("arcaStatsRefreshModel").value = "all";
  await nodes.get("startArcaStatsRefresh").listeners.click();
  assert.equal(requests, 1);
  assert.equal(vm.runInContext("arcaState.collecting", context), false);
  assert.equal(nodes.get("refreshArcaStats").disabled, false);
  assert.equal(nodes.get("collectArcaStyles").disabled, false);
  assert.equal(nodes.get("arcaStatsRefreshStatus").textContent, "Chrome 로그인을 연결해 주세요.");
  assert.equal(nodes.get("arcaStatsRefreshStatus").className, "status error");
  assert.equal(nodes.get("arcaStatsRefreshModal").classes.has("hidden"), false);
  assert.equal(nodes.get("arcaStatsRefreshModel").value, "all");
  assert.equal(nodes.get("startArcaStatsRefresh").disabled, false);
  assert.equal(document.activeElement, nodes.get("startArcaStatsRefresh"));
  await nodes.get("startArcaStatsRefresh").listeners.click();
  assert.equal(requests, 2);
  assert.equal(nodes.get("arcaStatsRefreshModal").classes.has("hidden"), true);
});

test("stats refresh progress reports search pages and unconfirmed posts and handles an empty archive", () => {
  const running = { job_type: "stats_refresh", status: "running", stage: "refreshing_stats", scanned_posts: 2, total_posts: 5, updated: 2,
    scanned_pages: 4, progress: { posts: [2, 5], pages: [4, null] } };
  assert.equal(collectionCountsText(running), "목록 4페이지 · 게시글 2/5 · 갱신 2개 · 미확인 0개");
  assert.deepEqual(collectionProgress(running), { determinate: true, percent: 40 });
  const completed = { ...running, status: "completed", scanned_posts: 5, progress: { posts: [5, 5], pages: [8, null] },
    error: "3개 게시글의 조회·추천을 확인하지 못했습니다." };
  assert.equal(collectionCountsText(completed), "목록 8페이지 · 게시글 5/5 · 갱신 2개 · 미확인 3개");
  assert.equal(arcaSummaryText(completed),
    "조회·추천 갱신 완료 · 갱신 2개 · 미확인 3개. 3개 게시글의 조회·추천을 확인하지 못했습니다.");
  const empty = { job_type: "stats_refresh", status: "completed", skipped_existing: 1, scanned_posts: 0, updated: 0 };
  assert.equal(collectionCountsText(empty), "갱신할 저장된 글 없음 · 새 요청 없음");
  assert.equal(arcaSummaryText(empty), "선택한 모델에 해당하는 저장된 글이 없습니다.");
  assert.deepEqual(collectionProgress(empty), { determinate: true, percent: 100 });
  const { context, nodes } = statsRefreshContext();
  context.renderArcaCollectionProgress(running);
  assert.equal(nodes.get("arcaCollectionState").textContent, "검색 목록에서 조회·추천 갱신 중");
  assert.equal(nodes.get("arcaCollectionProgress").value, 40);
  assert.equal(nodes.get("pauseArcaCollection").classes.has("hidden"), false);
  assert.equal(nodes.get("stopArcaCollection").classes.has("hidden"), false);
  context.renderArcaCollectionProgress({ ...running, stage: "refreshing_stats_posts" });
  assert.equal(nodes.get("arcaCollectionState").textContent, "남은 게시글 조회·추천 확인 중");
  assert.equal(nodes.get("arcaCollectionCounts").textContent, "목록 4페이지 · 게시글 2/5 · 갱신 2개 · 미확인 0개");
});

test("completed stats refresh reloads saved lists and statistics and returns focus from progress", async () => {
  const { context, nodes, document } = statsRefreshContext();
  const requests = [], reloads = [];
  context.arcaFetch = async (url, options) => {
    requests.push({ url, method: options?.method || "GET" });
    return url.endsWith("refresh-stats") ? { job_id: 74, status: "queued" } : {
      id: 74, job_type: "stats_refresh", status: "completed", scanned_posts: 5, total_posts: 5, updated: 5,
      progress: { posts: [5, 5] },
    };
  };
  context.loadArcaStyles = async () => reloads.push("list");
  context.loadArcaStyleStatistics = async () => reloads.push("statistics");
  context.loadArcaImageRestoreEstimate = async () => reloads.push("local-estimate");
  await nodes.get("refreshArcaStats").listeners.click();
  await nodes.get("startArcaStatsRefresh").listeners.click();
  assert.deepEqual(requests, [
    { url: "/api/arca-styles/refresh-stats", method: "POST" },
    { url: "/api/arca-styles/collection-jobs/74", method: "GET" },
  ]);
  assert.deepEqual(reloads, ["list", "statistics", "local-estimate"]);
  assert.equal(nodes.get("refreshArcaStats").disabled, false);
  assert.equal(vm.runInContext("arcaState.collecting", context), false);
  assert.equal(vm.runInContext("arcaState.activeJobId", context), null);
  assert.equal(nodes.get("arcaCollectorStatus").textContent, "조회·추천 갱신 완료 · 갱신 5개 · 미확인 0개");
  assert.equal(document.activeElement, nodes.get("refreshArcaStats"));
});

test("stats refresh completion leaves focus alone after the user moves away from progress", async () => {
  const { context, nodes, document } = statsRefreshContext();
  context.arcaFetch = async () => ({ id: 77, job_type: "stats_refresh", status: "completed", scanned_posts: 1, updated: 1 });
  context.loadArcaStyles = async () => {};
  context.loadArcaStyleStatistics = async () => {};
  context.loadArcaImageRestoreEstimate = async () => {};
  vm.runInContext("arcaState.collecting = true; arcaState.activeJobId = 77", context);
  nodes.get("collectArcaStyles").focus();
  await context.pollArcaCollectionJob(77);
  assert.equal(document.activeElement, nodes.get("collectArcaStyles"));
});

test("failed, stopped and interrupted stats refreshes reload updates already saved", async () => {
  for (const status of ["failed", "stopped", "interrupted"]) {
    const { context, nodes } = statsRefreshContext();
    const reloads = [];
    context.arcaFetch = async () => ({
      id: 75, job_type: "stats_refresh", status, scanned_posts: 2, total_posts: 5, updated: 2,
      scanned_pages: 4, progress: { posts: [2, 5], pages: [4, null] }, error: "갱신이 중단되었습니다.",
    });
    context.loadArcaStyles = async () => reloads.push("list");
    context.loadArcaStyleStatistics = async () => reloads.push("statistics");
    context.loadArcaImageRestoreEstimate = async () => assert.fail("stats interruption must not check image restoration");
    vm.runInContext("arcaState.collecting = true; arcaState.activeJobId = 75", context);
    await context.pollArcaCollectionJob(75);
    assert.deepEqual(reloads, ["list", "statistics"], status);
    assert.equal(nodes.get("refreshArcaStats").disabled, false, status);
    assert.equal(vm.runInContext("arcaState.activeJobId", context), 75, status);
    assert.equal(nodes.get("arcaCollectorStatus").textContent, "갱신이 중단되었습니다.", status);
    assert.equal(nodes.get("resumeArcaCollection").classes.has("hidden"), false, status);
  }
});

test("collection payload defaults and preserves the user search without page or post limits", () => {
  assert.deepEqual(normalizeArcaPayload({ tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02" }), {
    keyword: "그림체 공유", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: 0, max_posts: 0,
  });
  assert.equal(normalizeArcaPayload({ keyword: "  artist style ", tabs: ["NAI"] }).keyword, "artist style");
  assert.equal(normalizeArcaPayload({ keyword: "   ", tabs: ["NAI"] }).keyword, "그림체 공유");
});

test("collection progress handles known and unknown totals", () => {
  assert.deepEqual(collectionProgress({ progress: { posts: [2, 5] } }), { determinate: true, percent: 40 });
  assert.deepEqual(collectionProgress({ progress: { posts: [0, null] } }), { determinate: false, percent: 0 });
  assert.equal(durationText(65), "1분 5초");
  assert.equal(etaText(null), "계산 중");
  assert.equal(collectionCountsText({ progress: { pages: [1, 5], posts: [2, 8], images: 4 } }), "페이지 1/5 · 게시글 2/8 · 이미지 4개");
  assert.deepEqual(collectionProgress({ status: "completed", skipped_existing: 1, progress: { posts: [0, null] } }), { determinate: true, percent: 100 });
  assert.equal(collectionCountsText({ status: "completed", skipped_existing: 1 }), "이미 수집한 기간 · 새 요청 없음");
  assert.equal(formatBytes(1536), "1.50 KB");
  assert.deepEqual(imageDownloadSummary({ total_images: 1687, local_images: 1687, missing_images: 0 }), { completed: true, text: "이미지 1,687장 준비됨 · 필요할 때 열기" });
  assert.deepEqual(imageDownloadSummary({ total_images: 1687, local_images: 4, missing_images: 1683 }), { completed: false, text: "누락 1,683장 · 설치 방법 보기" });
  assert.equal(imageRestoreEstimateText({ missing_images: 2, local_images: 1, estimated_download_bytes: 8 * 1024 * 1024, estimated_seconds: 65, estimate_source: "default_average" }), "누락 2장 · 예상 8.00 MB · 약 1분 5초 (이미지당 4 MB 기준, 사이트 제한·인터넷 속도에 따라 달라짐)");
  assert.equal(collectionCountsText({ job_type: "image_restore", progress: { posts: [12, 30], images: 10, bytes: [1024, 2048] } }), "이미지 확인 12/30 · 복원 10장 · 1.00 KB/2.00 KB");
  assert.equal(arcaSummaryText({ job_type: "image_restore", downloaded_images: 30 }), "이미지 30개를 복원했습니다.");
  assert.equal(collectionCountsText({ job_type: "image_url_refresh", updated: 25, progress: { posts: [3, 10] } }), "게시글 주소 갱신 3/10 · 이미지 URL 25개");
  assert.equal(arcaSummaryText({ job_type: "image_url_refresh", scanned_posts: 10, updated: 25 }), "게시글 10개를 확인하고 이미지 URL 25개를 갱신했습니다.");
  assert.deepEqual(collectionProgress({ job_type: "image_archive", stage: "downloading_archive", progress: { bytes: [25, 100], posts: [0, 1687] } }), { determinate: true, percent: 25 });
  assert.equal(collectionCountsText({ job_type: "image_archive", stage: "downloading_archive", progress: { bytes: [1024, 2048], posts: [0, 1687] } }), "ZIP 다운로드 1.00 KB/2.00 KB");
  assert.equal(collectionCountsText({ job_type: "image_archive", stage: "extracting_archive", progress: { posts: [500, 1687], images: 499 } }), "압축 해제 500/1687 · 준비 499장");
  assert.equal(arcaSummaryText({ job_type: "image_archive", downloaded_images: 1687 }), "공유 그림체 이미지 1687장을 ZIP에서 설치했습니다.");
});

test("failed and stopped archive downloads keep byte progress instead of extraction counts", () => {
  for (const stage of ["failed", "stopped", "interrupted"]) {
    const job = { job_type: "image_archive", status: stage, stage,
      progress: { bytes: [0, 2048], posts: [0, 4425], images: 0 } };
    assert.equal(collectionCountsText(job), "ZIP 다운로드 0 B/2.00 KB");
    assert.deepEqual(collectionProgress(job), { determinate: true, percent: 0 });
    job.progress.bytes[0] = 1024;
    assert.equal(collectionCountsText(job), "ZIP 다운로드 1.00 KB/2.00 KB");
    assert.deepEqual(collectionProgress(job), { determinate: true, percent: 50 });
  }
  const rawJob = { job_type: "image_archive", stage: "failed", downloaded_bytes: 1024, estimated_bytes: 2048 };
  assert.equal(collectionCountsText(rawJob), "ZIP 다운로드 1.00 KB/2.00 KB");
  assert.deepEqual(collectionProgress(rawJob), { determinate: true, percent: 50 });
});

test("archive failures after downloading do not claim extraction has started", () => {
  const job = { job_type: "image_archive", status: "failed", stage: "failed",
    progress: { bytes: [2048, 2048], posts: [0, 4425], images: 0 } };
  assert.equal(collectionCountsText(job), "ZIP 다운로드 완료 · 설치 준비");
  assert.deepEqual(collectionProgress(job), { determinate: false, percent: 0 });
  job.progress.posts = [100, 200];
  job.progress.images = 95;
  assert.equal(collectionCountsText(job), "압축 해제 100/200 · 준비 95장");
  assert.deepEqual(collectionProgress(job), { determinate: true, percent: 50 });
});

test("collection panel stays open while active and can close after completion", () => {
  for (const status of ["queued", "running", "pause_requested", "paused", "stop_requested"]) {
    assert.equal(shouldOpenArcaCollectionPanel(status), true);
  }
  for (const status of ["completed", "failed", "interrupted", "stopped", "idle"]) {
    assert.equal(shouldOpenArcaCollectionPanel(status), false);
  }
});

test("Arca prompt editors bind only editable prompt fields to the shared autocomplete", () => {
  const source = fs.readFileSync(path.join(__dirname, "../static/arca_style_collector.js"), "utf8");
  assert.ok(source.includes('["arcaEditPrompt", "arcaEditNegativePrompt"]'));
  assert.ok(source.includes("globalThis.promptTagAutocomplete?.bind?.(input)"));
  assert.ok(source.includes("globalThis.promptTagAutocomplete?.hide?.()"));
});

test("style group helpers separate prompt sections", () => {
  const group = {
    singleton: false,
    common_base_tags: ["artist:foo", "watercolor"],
    common_negative_tags: ["lowres"],
    images: [{ id: 1, different_base_tags: ["blue hair"], different_negative_tags: ["blurry"], character_prompts: [{ prompt: "1girl" }] }],
  };
  assert.equal(groupTitle(group, 0), "그림체 그룹 1 · 이미지 1장");
  assert.deepEqual(promptSection(group, "base").common, ["artist:foo", "watercolor"]);
  assert.deepEqual(promptSection(group, "character").images[0].tags, ["1girl"]);
  assert.equal(groupTitle({ ...group, singleton: true }, 0), "개별 이미지");
  assert.equal(promptKindClass("base"), "is-base");
  assert.equal(promptKindClass("negative"), "is-negative");
  assert.equal(promptKindClass("character"), "is-character");
});

test("shared dependency confirmation only accepts prompts with artist tags", () => {
  assert.equal(hasArcaDependencyArtists({ base_prompt: "1.2::artist:sample::, masterpiece" }), true);
  assert.equal(hasArcaDependencyArtists({ base_prompt: "masterpiece, quality" }), false);
});
