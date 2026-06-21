const test = require("node:test");
const assert = require("node:assert/strict");
const {
  normalizeArcaPayload, arcaSummaryText, collectionProgress, durationText,
  etaText, collectionCountsText, groupTitle, promptSection,
  promptKindClass,
  imagePromptFields,
  normalizeArcaUrlPayload,
  arcaBrowserSessionText,
  isArcaBrowserSessionPending,
  arcaListQuery,
} = require("../static/arca_style_collector.js");

test("collection payload normalizes checked tabs and limits", () => {
  assert.deepEqual(normalizeArcaPayload({ keyword: " x ", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: "5", max_posts: "80" }), {
    keyword: "x", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: 5, max_posts: 80,
  });
});

test("list query uses Arca post date sort", () => {
  assert.equal(arcaListQuery({ q: "x", metadata: "all", sort: "posted_asc" }).get("sort"), "posted_asc");
  assert.equal(arcaListQuery({}).get("sort"), "posted_desc");
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
});

test("collection payload keeps fixed search and hidden safety limits", () => {
  assert.deepEqual(normalizeArcaPayload({ tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02" }), {
    keyword: "그림체 공유", tabs: ["NAI"], start_date: "2026-01-01", end_date: "2026-01-02", max_pages: 5, max_posts: 80,
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
