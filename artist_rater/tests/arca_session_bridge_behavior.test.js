const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../static/arca_session_bridge/popup.js"), "utf8");

function popup({ cookies = [{ name: "session", value: "test-secret", domain: ".arca.live", path: "/", secure: true }], response, fetchError, cookieError, fetchImpl } = {}) {
  const status = { textContent: "", dataset: {} };
  const button = { disabled: false, addEventListener(_event, handler) { this.click = handler; } };
  const requests = [];
  const timers = new Map();
  const context = vm.createContext({
    AbortController,
    setTimeout: (callback, milliseconds) => { timers.set(callback, milliseconds); return callback; },
    clearTimeout: callback => timers.delete(callback),
    document: { getElementById: id => id === "connectSession" ? button : status },
    chrome: { cookies: { getAll: async () => { if (cookieError) throw cookieError; return cookies; } } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (fetchImpl) return fetchImpl(url, options);
      if (fetchError) throw fetchError;
      return response;
    },
  });
  vm.runInContext(script, context);
  return { button, status, requests, timers };
}

test("bridge shows the server's login validation failure", async () => {
  const message = "로그인했지만 🔞 NAI 접근을 확인하지 못했습니다.";
  const ui = popup({ response: { ok: false, status: 401, json: async () => ({ connected: false, error: message }) } });
  await ui.button.click();
  assert.equal(ui.status.textContent, message);
  assert.equal(ui.status.dataset.state, "error");
  assert.equal(ui.button.disabled, false);
});

test("bridge distinguishes a missing endpoint from a login failure", async () => {
  const ui = popup({ response: { ok: false, status: 404, json: async () => { throw new SyntaxError(); } } });
  await ui.button.click();
  assert.match(ui.status.textContent, /앱.*업데이트/);
  assert.equal(ui.button.disabled, false);
});

test("bridge identifies unexpected server responses without displaying their body", async () => {
  for (const result of [null, {}, { error: { value: "test-secret" } }]) {
    const ui = popup({ response: { ok: false, status: 500, json: async () => result } });
    await ui.button.click();
    assert.match(ui.status.textContent, /HTTP 500/);
    assert.doesNotMatch(ui.status.textContent, /test-secret/);
    assert.equal(ui.button.disabled, false);
  }
});

test("bridge keeps successful cookie transfer and releases the button", async () => {
  const ui = popup({ response: { ok: true, status: 200, json: async () => ({ connected: true }) } });
  const pending = ui.button.click();
  assert.equal(ui.button.disabled, true);
  await pending;
  assert.equal(ui.status.dataset.state, "success");
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.requests[0].url, "http://127.0.0.1:5001/api/arca-styles/browser-session/extension");
  assert.equal(ui.requests[0].options.headers["X-Arca-Session-Bridge"], "1");
  assert.equal(JSON.parse(ui.requests[0].options.body).cookies[0].value, "test-secret");
  assert.doesNotMatch(ui.status.textContent, /test-secret/);
  assert.equal(ui.timers.size, 0);
});

test("bridge stops waiting when login validation never returns", async () => {
  let aborted = false;
  const ui = popup({ fetchImpl: (_url, options) => new Promise((_resolve, reject) => {
    options.signal?.addEventListener("abort", () => {
      aborted = true;
      reject(new Error("test-secret"));
    });
  }) });
  const pending = ui.button.click();
  await new Promise(setImmediate);
  assert.equal(ui.timers.size, 1);
  const [timeout, milliseconds] = [...ui.timers][0];
  assert.equal(milliseconds, 20000);
  timeout();
  await pending;
  assert.equal(aborted, true);
  assert.match(ui.status.textContent, /시간.*초과/);
  assert.doesNotMatch(ui.status.textContent, /test-secret/);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.timers.size, 0);
});

test("bridge timeout also covers a stalled response body", async () => {
  const ui = popup({ fetchImpl: async (_url, { signal }) => ({
    ok: true, status: 200,
    json: () => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("test-secret")));
    }),
  }) });
  const pending = ui.button.click();
  await new Promise(setImmediate);
  assert.equal(ui.timers.size, 1);
  [...ui.timers.keys()][0]();
  await pending;
  assert.match(ui.status.textContent, /시간.*초과/);
  assert.equal(ui.button.disabled, false);
  assert.equal(ui.timers.size, 0);
});

test("bridge handles missing cookies and an unreachable app separately", async () => {
  const empty = popup({ cookies: [] });
  await empty.button.click();
  assert.match(empty.status.textContent, /로그인을 찾지 못했습니다/);
  assert.equal(empty.requests.length, 0);
  assert.equal(empty.button.disabled, false);
  const offline = popup({ fetchError: new Error("test-secret") });
  await offline.button.click();
  assert.match(offline.status.textContent, /앱이 실행 중인지/);
  assert.doesNotMatch(offline.status.textContent, /test-secret/);
  assert.equal(offline.button.disabled, false);
});

test("cookie API failures point to extension permissions without leaking details", async () => {
  const ui = popup({ cookieError: new Error("test-secret") });
  await ui.button.click();
  assert.match(ui.status.textContent, /쿠키.*권한/);
  assert.doesNotMatch(ui.status.textContent, /test-secret/);
  assert.equal(ui.requests.length, 0);
  assert.equal(ui.button.disabled, false);
});
