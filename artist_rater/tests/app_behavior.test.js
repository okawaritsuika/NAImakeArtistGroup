const assert = require("node:assert/strict");
const test = require("node:test");

class FakeClassList {
  constructor(element) {
    this.element = element;
  }

  toggle(name) {
    const classes = new Set(this.element.className.split(/\s+/).filter(Boolean));
    if (classes.has(name)) classes.delete(name);
    else classes.add(name);
    this.element.className = [...classes].join(" ");
  }

  add(name) {
    if (!this.element.className.split(/\s+/).includes(name)) this.element.className = `${this.element.className} ${name}`.trim();
  }

  remove(name) {
    this.element.className = this.element.className.split(/\s+/).filter((item) => item && item !== name).join(" ");
  }
}

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.listeners = {};
    this.classList = new FakeClassList(this);
  }

  append(...children) {
    this.children.push(...children);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners[name] = listener;
  }

  querySelector(selector) {
    const match = (element) => {
      if (selector.startsWith(".")) return element.className.split(/\s+/).includes(selector.slice(1));
      const dataMatch = selector.match(/^\[data-(action|edit)="([^"]+)"\]$/);
      if (dataMatch) return element.dataset[dataMatch[1]] === dataMatch[2];
      return element.tagName === selector.toUpperCase();
    };
    const visit = (element) => {
      if (match(element)) return element;
      for (const child of element.children) {
        const found = visit(child);
        if (found) return found;
      }
      return null;
    };
    return visit(this);
  }
}

global.document = {
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};
global.window = { location: { origin: "http://localhost" } };

const {
  renderRatingCard,
  manualPreviewRatingFields,
  calculateTooltipPosition,
  buildDanbooruSearchUrl,
  buildDanbooruPostUrl,
  buildRatingRepresentativeSample,
  openRatingSampleViewer,
  loadMoreManualPreviewSamples,
  normalizeStoredRatingExample,
  combineRatingSamples,
  mergePreviewSamples,
} = require("../static/app.js");

test("tooltip positions stay within the viewport and move below a clipped top anchor", () => {
  const position = calculateTooltipPosition(
    { left: 390, top: 4, right: 410, bottom: 24 },
    { width: 180, height: 60 },
    { width: 420, height: 240 },
  );
  assert.deepEqual(position, { left: 228, top: 32 });
});

test("rating cards render hostile stored data as inert text and reject unsafe image URLs", () => {
  const hostile = '<img src=x onerror="globalThis.xss = true">';
  const card = renderRatingCard({
    id: 7,
    artist_tag: hostile,
    score: 5,
    memo: `memo ${hostile}`,
    mode: hostile,
    query_tags: [hostile],
    artist_post_count: 12,
    matched_post_count: 3,
    created_at: hostile,
    query_text: hostile,
    prompt_text: hostile,
    thumbnail_url: "javascript:alert(1)",
  });

  assert.equal(card.querySelector("img"), null);
  assert.equal(card.querySelector("h3").textContent, hostile);
  assert.equal(card.querySelector(".memo-preview").textContent, `memo ${hostile}`);
  assert.equal(card.querySelector('[data-edit="memo"]').value, `memo ${hostile}`);
  assert.equal(card.querySelector('[data-edit="query-text"]').value, hostile);
  for (const action of ["copy", "edit", "delete", "apply"]) {
    assert.equal(typeof card.querySelector(`[data-action="${action}"]`).listeners.click, "function");
  }
  assert.equal(typeof card.querySelector('[data-action="find-thumbnail"]').listeners.click, "function");
  assert.equal(card.querySelector('[data-action="find-thumbnail"]').textContent, "WebP 썸네일 받기");
});

test("rating cards expose an encoded Danbooru search and accessible sample viewer actions", () => {
  const searchUrl = buildDanbooruSearchUrl("artist name", ["solo", "a&b"]);
  assert.equal(
    searchUrl,
    "https://danbooru.donmai.us/posts?tags=artist+name+solo+a%26b",
  );
  const card = renderRatingCard({
    id: 8,
    artist_tag: "artist name",
    score: 4,
    query_tags: ["solo"],
    thumbnail_url: "https://example.test/thumb.jpg",
  });
  const searchLink = card.querySelector('[data-action="danbooru-search"]');
  assert.equal(searchLink.attributes.href, "https://danbooru.donmai.us/posts?tags=artist+name+solo");
  assert.equal(searchLink.attributes.target, "_blank");
  assert.equal(typeof card.querySelector('[data-action="open-samples"]').listeners.click, "function");
  assert.equal(typeof card.querySelector('[data-action="view-samples"]').listeners.click, "function");
  assert.equal(card.querySelector('[data-action="find-thumbnail"]').textContent, "WebP 썸네일 갱신");
});

test("sample merging filters unsafe URLs and keeps the representative first", () => {
  const merged = mergePreviewSamples(
    [{ id: 1, preview_url: "https://example.test/representative.jpg" }],
    [
      { id: 2, preview_url: "javascript:alert(1)" },
      { id: 3, preview_url: "https://example.test/extra.jpg" },
      { id: 1, preview_url: "https://example.test/duplicate.jpg" },
    ],
  );
  assert.deepEqual(merged.map((sample) => sample.id), [1, 3]);
});

test("rating representative prefers the source preview and links only numeric posts", () => {
  assert.equal(buildDanbooruPostUrl(123), "https://danbooru.donmai.us/posts/123");
  assert.equal(buildDanbooruPostUrl("123/evil"), "");
  const sample = buildRatingRepresentativeSample({
    representative_post_id: 123,
    representative_preview_url: "https://example.test/source-preview.jpg",
    thumbnail_url: "/thumbnails/local.jpg",
  });
  assert.equal(sample.large_url, "https://example.test/source-preview.jpg");
  assert.equal(sample.post_url, "https://danbooru.donmai.us/posts/123");
});

test("rating viewer loads stored examples when opened without collecting transient samples", async () => {
  const originalGetElementById = global.document.getElementById;
  const originalFetch = global.fetch;
  const ids = [
    "manualPreviewModal",
    "manualPreviewViewer",
    "manualPreviewStatus",
    "manualPreviewArtist",
    "manualPreviewImage",
    "manualPreviewLink",
    "manualPreviewCounter",
    "manualPreviewLoadMore",
    "manualPreviewRepresentativeBadge",
    "manualPreviewSetThumbnail",
    "manualPreviewDeleteExample",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement("div")]));
  const calls = [];
  global.document.getElementById = (id) => elements.get(id) || null;
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        ok: true,
        rating: { id: 7, artist_tag: "artist_a", representative_preview_url: "", thumbnail_url: "" },
        examples: [{ id: 41, post_id: 99, image_url: "https://example.test/stored.webp", post_url: "https://danbooru.donmai.us/posts/99" }],
      }),
    };
  };
  try {
    await openRatingSampleViewer({ id: 7, artist_tag: "artist_a", query_tags: ["solo"] });
  } finally {
    global.document.getElementById = originalGetElementById;
    if (originalFetch) global.fetch = originalFetch;
    else delete global.fetch;
  }
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/ratings/7/examples");
  assert.equal(elements.get("manualPreviewImage").src, "https://example.test/stored.webp");
  assert.equal(elements.get("manualPreviewSetThumbnail").hidden, false);
  assert.equal(elements.get("manualPreviewSetThumbnail").disabled, false);
  assert.equal(elements.get("manualPreviewDeleteExample").hidden, false);
});

test("rating viewer collects stored examples through the rating endpoint", async () => {
  const originalGetElementById = global.document.getElementById;
  const originalFetch = global.fetch;
  const ids = [
    "manualPreviewModal",
    "manualPreviewViewer",
    "manualPreviewStatus",
    "manualPreviewArtist",
    "manualPreviewImage",
    "manualPreviewLink",
    "manualPreviewCounter",
    "manualPreviewLoadMore",
    "manualPreviewRepresentativeBadge",
    "manualPreviewSetThumbnail",
    "manualPreviewDeleteExample",
    "ratingsList",
    "ratingsStatus",
  ];
  const elements = new Map(ids.map((id) => [id, new FakeElement("div")]));
  const calls = [];
  let listResponse = {
    rating: { id: 9, artist_tag: "artist_b", representative_preview_url: "", thumbnail_url: "" },
    examples: [{ id: 51, post_id: 201, image_url: "https://example.test/201.webp" }],
  };
  global.document.getElementById = (id) => elements.get(id) || null;
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url === "/api/ratings/9/examples/collect") {
      listResponse = {
        ...listResponse,
        examples: [
          ...listResponse.examples,
          { id: 52, post_id: 202, image_url: "https://example.test/202.webp" },
        ],
      };
      return { ok: true, json: async () => ({ ok: true, saved_count: 1 }) };
    }
    if (url === "/api/ratings/9/examples") {
      return { ok: true, json: async () => ({ ok: true, ...listResponse }) };
    }
    if (url.startsWith("/api/ratings?")) {
      return { ok: true, json: async () => [] };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };
  try {
    await openRatingSampleViewer({ id: 9, artist_tag: "artist_b", query_tags: [] });
    const collected = await loadMoreManualPreviewSamples();
    assert.equal(collected, true);
  } finally {
    global.document.getElementById = originalGetElementById;
    if (originalFetch) global.fetch = originalFetch;
    else delete global.fetch;
  }
  assert.deepEqual(calls.map((call) => call.url), [
    "/api/ratings/9/examples",
    "/api/ratings/9/examples/collect",
    "/api/ratings/9/examples",
    "/api/ratings?sort=recent",
  ]);
  assert.equal(elements.get("manualPreviewCounter").textContent, "1 / 2");
});

test("stored rating examples preserve ownership metadata and representative ordering", () => {
  const stored = normalizeStoredRatingExample({
    id: 41,
    post_id: 99,
    image_url: "https://example.test/stored.webp",
    is_thumbnail: true,
  });
  const combined = combineRatingSamples(
    { id: 99, large_url: "https://example.test/remote.jpg", preview_url: "https://example.test/remote.jpg" },
    [stored],
  );
  assert.equal(combined.length, 1);
  assert.equal(combined[0].example_id, 41);
  assert.equal(combined[0].is_representative, true);
});

test("manual ratings reuse the selected preview only for the same artist and tags", () => {
  const preview = {
    artist: "artist_a",
    queryTags: ["solo"],
    sample: { id: 123, preview_url: "https://example.test/preview.jpg" },
    sampleIds: [123, 456],
  };
  assert.deepEqual(manualPreviewRatingFields("artist_a", ["solo"], preview), {
    representative_post_id: 123,
    representative_preview_url: "https://example.test/preview.jpg",
    sample_post_ids: [123, 456],
  });
  assert.deepEqual(manualPreviewRatingFields("artist_b", ["solo"], preview), {});
});

test("manual and candidate saves prefer the large sample URL for the representative thumbnail source", () => {
  const fields = manualPreviewRatingFields("artist_a", ["solo"], {
    artist: "artist_a",
    queryTags: ["solo"],
    sample: {
      id: 456,
      preview_url: "https://example.test/preview.jpg",
      large_url: "https://example.test/large.jpg",
    },
  });
  assert.equal(fields.representative_preview_url, "https://example.test/large.jpg");
});
