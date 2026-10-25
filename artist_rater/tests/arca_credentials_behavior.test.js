const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function fixture() {
  const nodes = new Map();
  function element(id) {
    if (!nodes.has(id)) nodes.set(id, { value: "", disabled: false, textContent: "" });
    return nodes.get(id);
  }
  const context = vm.createContext({ URLSearchParams, setTimeout: () => 1, clearTimeout() {},
    document: { addEventListener() {}, getElementById: element },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../static/arca_style_collector.js"), "utf8"), context);
  context.arcaSetStatus = (id, text) => { element(id).textContent = text; };
  return { context, element };
}

test("save clears the password immediately and logs in only after storage succeeds", async () => {
  const { context, element } = fixture();
  element("arcaLoginUsername").value = " fixture-user ";
  element("arcaLoginPassword").value = " fixture-password ";
  let resolveSave, request, loggedIn = 0;
  context.arcaFetch = (url, options) => {
    request = { url, options };
    return new Promise(resolve => { resolveSave = resolve; });
  };
  context.importArcaBrowserSession = async () => { loggedIn += 1; };
  const saving = context.saveArcaCredentials();
  assert.equal(element("arcaLoginPassword").value, "");
  assert.equal(element("saveArcaCredentials").disabled, true);
  assert.equal(loggedIn, 0);
  assert.deepEqual(JSON.parse(request.options.body), { username: "fixture-user", password: " fixture-password " });
  assert.equal(request.options.headers["X-Arca-Local-Request"], "1");
  assert.equal(request.options.cache, "no-store");
  resolveSave({ saved: true, username: "fixture-user" });
  await saving;
  assert.equal(loggedIn, 1);
  assert.equal(element("importArcaBrowserSession").textContent, "저장된 계정으로 로그인");
  assert.equal(element("saveArcaCredentials").disabled, false);
});

test("failed saving clears password and does not start login", async () => {
  const { context, element } = fixture();
  element("arcaLoginUsername").value = "fixture-user";
  element("arcaLoginPassword").value = "fixture-password";
  context.arcaFetch = async () => { throw new Error("저장 실패"); };
  context.importArcaBrowserSession = async () => { assert.fail("unexpected login"); };
  await context.saveArcaCredentials();
  assert.equal(element("arcaLoginPassword").value, "");
  assert.equal(element("arcaCredentialsStatus").textContent, "저장 실패");
  assert.equal(element("saveArcaCredentials").disabled, false);
});

test("loading status never places password in UI and preserves an unfinished edit", async () => {
  const { context, element } = fixture();
  element("arcaLoginUsername").value = "new-account";
  context.arcaFetch = async () => ({ saved: true, username: "old-account", password: "must-not-render" });
  await context.loadArcaCredentials();
  assert.equal(element("arcaLoginUsername").value, "new-account");
  assert.equal(element("arcaLoginPassword").value, "");
  assert.ok(!element("arcaCredentialsStatus").textContent.includes("must-not-render"));
});

test("pending login prevents account edits or deletion", async () => {
  const { context, element } = fixture();
  context.renderArcaBrowserSession({ state: "waiting" });
  context.arcaFetch = async () => { assert.fail("unexpected mutation"); };
  await context.saveArcaCredentials();
  await context.deleteArcaCredentials();
  assert.equal(element("deleteArcaCredentials").disabled, true);
  context.renderArcaBrowserSession({ state: "failed", error: "로그인 실패" });
  assert.equal(element("deleteArcaCredentials").disabled, false);
});

test("deletion removes saved username and does not claim the active session was logged out", async () => {
  const { context, element } = fixture();
  element("arcaLoginUsername").value = "fixture-user";
  context.arcaFetch = async (url, options) => {
    assert.equal(options.method, "DELETE");
    assert.equal(options.headers["X-Arca-Local-Request"], "1");
    return { saved: false, username: "" };
  };
  await context.deleteArcaCredentials();
  assert.equal(element("arcaLoginUsername").value, "");
  assert.match(element("arcaCredentialsStatus").textContent, /현재 연결된 로그인은 유지/);
});

test("automatic collection login uses the protected local request header", async () => {
  const { context } = fixture();
  context.arcaFetch = async (url, options) => {
    assert.equal(url, "/api/arca-styles/browser-session/import");
    assert.equal(options.headers["X-Arca-Local-Request"], "1");
    return { connected: false, state: "opening" };
  };
  await context.importArcaBrowserSession();
});
