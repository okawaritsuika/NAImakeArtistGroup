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

const { renderRatingCard, manualPreviewRatingFields } = require("../static/app.js");

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
