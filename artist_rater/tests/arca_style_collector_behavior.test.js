const test = require("node:test");
const assert = require("node:assert/strict");
const {
  normalizeArcaPayload, arcaSummaryText, collectionProgress, durationText,
  etaText, collectionCountsText, groupTitle, promptSection,
  formatBytes, imageRestoreEstimateText,
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
} = require("../static/arca_style_collector.js");

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

test("coverage query keeps repeated tabs and explains completed ranges", () => {
  const query = arcaCoverageQuery({
    tabs: ["NAI", "R18_NAI"], start_date: "2026-07-01", end_date: "2026-07-12",
    max_pages: 5, max_posts: 80,
  });
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

test("direct URL payload trims one article link", () => {
  assert.deepEqual(normalizeArcaUrlPayload("  https://arca.live/b/aiart/174457459  "), {
    source_url: "https://arca.live/b/aiart/174457459",
  });
});

test("summary explains when an existing search was skipped", () => {
  assert.equal(arcaSummaryText({ skipped_existing: true }), "이미 검색한 범위입니다. 저장된 목록을 표시합니다.");
  assert.equal(arcaSummaryText({ error: "partial collection" }), "partial collection");
});

test("collection payload keeps fixed search without page or post limits", () => {
  assert.deepEqual(normalizeArcaPayload({ tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02" }), {
    keyword: "그림체 공유", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: 0, max_posts: 0,
  });
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
