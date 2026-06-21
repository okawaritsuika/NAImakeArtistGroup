const arcaState = { loaded: false, collecting: false, selectedId: null, timer: null, pollTimer: null, loginPollTimer: null, activeJobId: null, browserConnected: false };
const arcaEl = (id) => typeof document === "undefined" ? null : document.getElementById(id);

function normalizeArcaPayload(value) {
  return {
    keyword: String(value.keyword || "그림체 공유").trim(),
    tabs: value.tabs || [],
    start_date: value.start_date || "",
    end_date: value.end_date || "",
    max_pages: Number(value.max_pages || 5),
    max_posts: Number(value.max_posts || 80),
  };
}

function normalizeArcaUrlPayload(value) {
  return { source_url: String(value || "").trim() };
}

function arcaListQuery(value = {}) {
  return new URLSearchParams({
    q: String(value.q || ""),
    metadata: String(value.metadata || "all"),
    sort: String(value.sort || "posted_desc"),
  });
}

function arcaBrowserSessionText(status) {
  if (status?.connected) return `${status.browser || "브라우저"} 로그인 연결됨`;
  return status?.message || status?.error || "브라우저 로그인 연결 안 됨";
}

function isArcaBrowserSessionPending(status) {
  return ["opening", "waiting"].includes(status?.state);
}

function arcaSummaryText(result) {
  return result.skipped_existing
    ? "이미 검색한 범위입니다. 저장된 목록을 표시합니다."
    : `페이지 ${result.scanned_pages || 0} · 글 ${result.scanned_posts || 0} · 신규 ${result.saved || 0} · 갱신 ${result.updated || 0}`;
}

function collectionProgress(job) {
  if (job?.status === "completed" && job?.skipped_existing) {
    return { determinate: true, percent: 100 };
  }
  const posts = job?.progress?.posts || [job?.scanned_posts || 0, job?.total_posts ?? null];
  const done = Number(posts[0] || 0);
  const total = posts[1] == null ? null : Number(posts[1]);
  return total && Number.isFinite(total)
    ? { determinate: true, percent: Math.min(100, Math.round(done * 100 / total)) }
    : { determinate: false, percent: 0 };
}

function durationText(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  return minutes ? `${minutes}분 ${rest}초` : `${rest}초`;
}

function etaText(seconds) {
  return seconds == null ? "계산 중" : durationText(seconds);
}

function collectionCountsText(job) {
  if (job?.status === "completed" && job?.skipped_existing) {
    return "이미 수집한 기간 · 새 요청 없음";
  }
  const progress = job?.progress || {};
  const pages = progress.pages || [0, null];
  const posts = progress.posts || [0, null];
  const total = (pair) => pair[1] == null ? "?" : pair[1];
  return `페이지 ${pages[0] || 0}/${total(pages)} · 게시글 ${posts[0] || 0}/${total(posts)} · 이미지 ${progress.images || 0}개`;
}

function groupTitle(group, index) {
  return group.singleton ? "개별 이미지" : `그림체 그룹 ${index + 1} · 이미지 ${(group.images || []).length}장`;
}

function promptSection(group, kind) {
  if (kind === "base") {
    return { common: group.common_base_tags || [], images: (group.images || []).map((image) => ({ image, tags: image.different_base_tags || [] })) };
  }
  if (kind === "negative") {
    return { common: group.common_negative_tags || [], images: (group.images || []).map((image) => ({ image, tags: image.different_negative_tags || [] })) };
  }
  return {
    common: [],
    images: (group.images || []).map((image) => ({ image, tags: (image.character_prompts || []).map((entry) => entry.prompt).filter(Boolean) })),
  };
}

function promptKindClass(kind) {
  return `is-${kind}`;
}

function imagePromptFields(image) {
  return {
    image_url: image?.image_url || "",
    base: image?.base_prompt || image?.prompt || "",
    negative: image?.negative_prompt || "",
    character: (image?.character_prompts || []).map((entry) => entry.prompt).filter(Boolean).join("\n\n"),
  };
}

function arcaPayload() {
  return normalizeArcaPayload({
    tabs: [arcaEl("arcaTabNai").checked && "NAI", arcaEl("arcaTabR18Nai").checked && "R18_NAI"].filter(Boolean),
    start_date: arcaEl("arcaStartDate").value,
    end_date: arcaEl("arcaEndDate").value,
  });
}

function arcaSetStatus(id, message, type = "") {
  const element = arcaEl(id);
  if (element) {
    element.textContent = message || "";
    element.className = `status ${type}`;
  }
}

async function arcaFetch(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function arcaButton(label, handler, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.className = className;
  button.addEventListener("click", handler);
  return button;
}

function renderArcaCollectionProgress(job) {
  const labels = { queued: "대기", running: "수집 중", completed: "완료", failed: "실패", interrupted: "중단됨" };
  const progress = collectionProgress(job);
  const bar = arcaEl("arcaCollectionProgress");
  arcaEl("arcaCollectionState").textContent = labels[job.status] || job.status;
  arcaEl("arcaCollectionState").dataset.state = job.status;
  arcaEl("arcaCollectionCounts").textContent = collectionCountsText(job);
  arcaEl("arcaCollectionElapsed").textContent = `경과 ${durationText(job.elapsed_seconds)}`;
  arcaEl("arcaCollectionEta").textContent = job.status === "completed" ? "완료" : `남은 시간 ${etaText(job.estimated_remaining_seconds)}`;
  if (progress.determinate) {
    bar.max = 100;
    bar.value = progress.percent;
  } else {
    bar.removeAttribute("value");
  }
  if (job.error) arcaSetStatus("arcaCollectorStatus", job.error, "error");
}

function setArcaCollectionControlsDisabled(disabled) {
  for (const id of ["collectArcaStyles", "arcaTabNai", "arcaTabR18Nai", "arcaStartDate", "arcaEndDate", "collectArcaUrl", "arcaDirectUrl", "importArcaBrowserSession"]) {
    const element = arcaEl(id);
    if (element) element.disabled = disabled;
  }
}

function renderArcaBrowserSession(status) {
  arcaState.browserConnected = Boolean(status?.connected);
  arcaSetStatus("arcaBrowserSessionState", arcaBrowserSessionText(status), status?.connected ? "ok" : status?.error ? "error" : "");
}

async function loadArcaBrowserSession() {
  try {
    const status = await arcaFetch("/api/arca-styles/browser-session");
    renderArcaBrowserSession(status);
    if (isArcaBrowserSessionPending(status)) scheduleArcaBrowserSessionPoll();
  } catch (error) {
    clearTimeout(arcaState.loginPollTimer);
    arcaState.loginPollTimer = null;
    renderArcaBrowserSession({ connected: false, error: error.message });
  }
}

function scheduleArcaBrowserSessionPoll() {
  clearTimeout(arcaState.loginPollTimer);
  arcaState.loginPollTimer = setTimeout(async () => {
    arcaState.loginPollTimer = null;
    await loadArcaBrowserSession();
  }, 1000);
}

async function importArcaBrowserSession() {
  const button = arcaEl("importArcaBrowserSession");
  if (button) button.disabled = true;
  arcaSetStatus("arcaBrowserSessionState", "Chrome과 Edge에서 로그인 확인 중…");
  try {
    const status = await arcaFetch("/api/arca-styles/browser-session/import", { method: "POST" });
    renderArcaBrowserSession(status);
    if (isArcaBrowserSessionPending(status)) scheduleArcaBrowserSessionPoll();
  } catch (error) {
    renderArcaBrowserSession({ connected: false, error: error.message });
  } finally {
    if (button) button.disabled = arcaState.collecting;
  }
}

async function pollArcaCollectionJob(jobId) {
  if (arcaState.activeJobId !== jobId) return;
  try {
    const job = await arcaFetch(`/api/arca-styles/collection-jobs/${jobId}`);
    renderArcaCollectionProgress(job);
    if (["completed", "failed", "interrupted"].includes(job.status)) {
      clearTimeout(arcaState.pollTimer);
      arcaState.pollTimer = null;
      arcaState.activeJobId = null;
      arcaState.collecting = false;
      setArcaCollectionControlsDisabled(false);
      if (job.status === "completed") {
        arcaSetStatus("arcaCollectorStatus", arcaSummaryText(job), "success");
        await loadArcaStyles();
      }
      return;
    }
    arcaState.pollTimer = setTimeout(() => pollArcaCollectionJob(jobId), 1000);
  } catch (error) {
    clearTimeout(arcaState.pollTimer);
    arcaState.pollTimer = null;
    arcaState.activeJobId = null;
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  }
}

function renderArcaCard(item) {
  const card = document.createElement("article");
  card.className = "arca-style-card";
  if (item.representative_image_url) {
    const image = document.createElement("img");
    image.className = "arca-style-thumb";
    image.src = item.representative_image_url;
    image.alt = "";
    card.append(image);
  } else {
    const empty = document.createElement("div");
    empty.className = "arca-style-thumb empty";
    empty.textContent = "이미지 없음";
    card.append(empty);
  }
  const body = document.createElement("div");
  body.className = "arca-style-body";
  const title = document.createElement("h3");
  title.textContent = item.title || "제목 없음";
  const meta = document.createElement("div");
  meta.className = "arca-style-meta";
  const recommendations = item.recommendation_count == null ? "추천 -" : `추천 ${Number(item.recommendation_count).toLocaleString()}`;
  const views = item.view_count == null ? "조회 -" : `조회 ${Number(item.view_count).toLocaleString()}`;
  [item.board_tab, item.posted_at, recommendations, views, `그룹 ${item.style_group_count || 0}`, `이미지 ${item.image_count || 0}`].filter(Boolean).forEach((value) => {
    const badge = document.createElement("span");
    badge.textContent = value;
    meta.append(badge);
  });
  const prompt = document.createElement("p");
  prompt.className = "arca-style-prompt-preview";
  prompt.textContent = item.prompt || "";
  const actions = document.createElement("div");
  actions.className = "arca-style-actions";
  const source = document.createElement("a");
  source.href = item.source_url;
  source.target = "_blank";
  source.rel = "noreferrer";
  source.textContent = "출처 열기";
  actions.append(source, arcaButton("확인 및 수정", () => openArcaStyle(item.id)), arcaButton("삭제", () => deleteArcaStyle(item.id)));
  body.append(title, meta, prompt, actions);
  card.append(body);
  return card;
}

function renderArcaList(items) {
  const list = arcaEl("arcaStyleList");
  if (!list) return;
  list.replaceChildren(...items.map(renderArcaCard));
  if (!items.length) {
    const empty = document.createElement("p");
    empty.textContent = "수집된 그림체가 없습니다.";
    list.append(empty);
  }
}

function appendTagList(parent, tags, className) {
  const list = document.createElement("div");
  list.className = className;
  for (const value of tags || []) {
    const chip = document.createElement("span");
    chip.className = "arca-prompt-tag";
    chip.textContent = value;
    list.append(chip);
  }
  if (!(tags || []).length) {
    const empty = document.createElement("span");
    empty.className = "arca-prompt-empty";
    empty.textContent = "없음";
    list.append(empty);
  }
  parent.append(list);
}

function renderGroupPromptPanel(group, kind) {
  const model = promptSection(group, kind);
  const panel = document.createElement("div");
  panel.className = `arca-group-prompt-panel ${promptKindClass(kind)}`;
  const commonBlock = document.createElement("section");
  commonBlock.className = "arca-common-block";
  const commonHeading = document.createElement("h4");
  commonHeading.textContent = kind === "character" ? "캐릭터 프롬프트" : "공통 태그";
  commonBlock.append(commonHeading);
  appendTagList(commonBlock, model.common, "arca-common-tags");
  panel.append(commonBlock);
  const differenceBlock = document.createElement("section");
  differenceBlock.className = "arca-difference-block";
  model.images.forEach((entry, index) => {
    const row = document.createElement("div");
    row.className = "arca-image-prompt-card";
    const heading = document.createElement("strong");
    heading.textContent = `이미지 ${index + 1} 차이`;
    row.append(heading);
    appendTagList(row, entry.tags, "arca-different-tags");
    differenceBlock.append(row);
  });
  panel.append(differenceBlock);
  return panel;
}

function renderArcaStyleGroupsLegacy(groups) {
  const root = document.createElement("div");
  root.className = "arca-style-groups";
  (groups || []).forEach((group, index) => {
    const section = document.createElement("section");
    section.className = "arca-style-group arca-unified-surface";
    const heading = document.createElement("h3");
    heading.textContent = groupTitle(group, index);
    const thumbs = document.createElement("div");
    thumbs.className = "arca-group-thumbnails";
    for (const image of group.images || []) {
      const img = document.createElement("img");
      img.src = image.image_url;
      img.alt = "";
      thumbs.append(img);
    }
    const tabs = document.createElement("div");
    tabs.className = "arca-group-tabs";
    const panels = document.createElement("div");
    const kinds = [["base", "베이스"], ["negative", "네거티브"], ["character", "캐릭터"]];
    kinds.forEach(([kind, label], tabIndex) => {
      const panel = renderGroupPromptPanel(group, kind);
      panel.classList.toggle("hidden", tabIndex !== 0);
      const button = arcaButton(label, () => {
        [...tabs.children].forEach((child) => child.setAttribute("aria-selected", "false"));
        [...panels.children].forEach((child) => child.classList.add("hidden"));
        button.setAttribute("aria-selected", "true");
        panel.classList.remove("hidden");
      });
      button.classList.add("arca-prompt-kind-tab", promptKindClass(kind));
      button.setAttribute("aria-selected", tabIndex === 0 ? "true" : "false");
      tabs.append(button);
      panels.append(panel);
    });
    const originals = document.createElement("details");
    originals.className = "arca-original-prompt";
    const summary = document.createElement("summary");
    summary.textContent = "원본 프롬프트 보기";
    originals.append(summary);
    for (const image of group.images || []) {
      const pre = document.createElement("pre");
      pre.textContent = image.base_prompt || image.prompt || "프롬프트 없음";
      originals.append(pre);
    }
    section.append(heading, thumbs, tabs, panels, originals);
    root.append(section);
  });
  return root;
}

function createImagePromptField(labelText, className) {
  const label = document.createElement("label");
  label.className = `arca-prompt-textarea ${className}`;
  const title = document.createElement("span");
  title.textContent = labelText;
  const textarea = document.createElement("textarea");
  textarea.readOnly = true;
  textarea.rows = 4;
  label.append(title, textarea);
  return { label, textarea };
}

function renderArcaStyleGroups(groups) {
  const root = document.createElement("div");
  root.className = "arca-style-groups";
  (groups || []).forEach((group, groupIndex) => {
    const section = document.createElement("section");
    section.className = "arca-style-group arca-unified-surface arca-image-prompt-viewer";
    const heading = document.createElement("h3");
    heading.textContent = groupTitle(group, groupIndex);
    const thumbnails = document.createElement("div");
    thumbnails.className = "arca-group-thumbnails";
    const fields = document.createElement("div");
    fields.className = "arca-selected-prompt-fields";
    const selectedLayout = document.createElement("div");
    selectedLayout.className = "arca-selected-image-layout";
    const previewFrame = document.createElement("div");
    previewFrame.className = "arca-selected-image-frame";
    const preview = document.createElement("img");
    preview.className = "arca-selected-image-preview";
    preview.alt = "";
    previewFrame.append(preview);
    const base = createImagePromptField("베이스 프롬프트", "is-base");
    const negative = createImagePromptField("네거티브 프롬프트", "is-negative");
    const character = createImagePromptField("캐릭터 프롬프트", "is-character");
    fields.append(base.label, negative.label, character.label);
    const buttons = [];
    const selectImage = (image, selectedIndex) => {
      const values = imagePromptFields(image);
      if (values.image_url) preview.src = values.image_url;
      else preview.removeAttribute("src");
      preview.alt = `선택 이미지 ${selectedIndex + 1}`;
      base.textarea.value = values.base;
      negative.textarea.value = values.negative;
      character.textarea.value = values.character;
      buttons.forEach((button, index) => {
        const selected = index === selectedIndex;
        button.classList.toggle("selected", selected);
        button.setAttribute("aria-pressed", selected ? "true" : "false");
      });
    };
    (group.images || []).forEach((image, imageIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "arca-image-choice";
      button.setAttribute("aria-label", `이미지 ${imageIndex + 1} 프롬프트 보기`);
      const thumbnail = document.createElement("img");
      thumbnail.src = image.image_url;
      thumbnail.alt = "";
      button.append(thumbnail);
      button.addEventListener("click", () => selectImage(image, imageIndex));
      buttons.push(button);
      thumbnails.append(button);
    });
    selectedLayout.append(previewFrame, fields);
    section.append(heading, thumbnails, selectedLayout);
    root.append(section);
    if ((group.images || []).length) selectImage(group.images[0], 0);
  });
  return root;
}

async function loadArcaStyles() {
  try {
    const query = arcaListQuery({ q: arcaEl("arcaStyleSearch")?.value, metadata: arcaEl("arcaMetadataFilter")?.value, sort: arcaEl("arcaStyleSort")?.value });
    const items = await arcaFetch(`/api/arca-styles?${query}`);
    renderArcaList(items);
    arcaSetStatus("arcaStyleListStatus", `${items.length}개 항목`);
    arcaState.loaded = true;
  } catch (error) {
    arcaSetStatus("arcaStyleListStatus", error.message, "error");
  }
}

async function collectArcaStyles() {
  if (arcaState.collecting) return;
  if (arcaEl("arcaTabR18Nai")?.checked && !arcaState.browserConnected) {
    arcaSetStatus("arcaBrowserSessionState", "🔞 NAI 수집 전에 브라우저 로그인을 가져와 주세요.", "error");
    return;
  }
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  try {
    const result = await arcaFetch("/api/arca-styles/collect", { method: "POST", body: JSON.stringify(arcaPayload()) });
    arcaState.activeJobId = result.job_id;
    await pollArcaCollectionJob(result.job_id);
  } catch (error) {
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  }
}

async function collectArcaUrl() {
  if (arcaState.collecting) return;
  const payload = normalizeArcaUrlPayload(arcaEl("arcaDirectUrl")?.value);
  if (!payload.source_url) {
    arcaSetStatus("arcaCollectorStatus", "추가할 게시글 링크를 입력해 주세요.", "error");
    return;
  }
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  try {
    const result = await arcaFetch("/api/arca-styles/collect-url", { method: "POST", body: JSON.stringify(payload) });
    arcaState.activeJobId = result.job_id;
    await pollArcaCollectionJob(result.job_id);
    arcaEl("arcaDirectUrl").value = "";
  } catch (error) {
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  }
}

async function openArcaStyle(id) {
  try {
    const item = await arcaFetch(`/api/arca-styles/${id}`);
    arcaState.selectedId = id;
    arcaEl("arcaStyleDialogTitle").textContent = item.title || "수집 그림체";
    arcaEl("arcaStyleSourceLink").href = item.source_url;
    arcaEl("arcaEditPrompt").value = item.prompt || "";
    arcaEl("arcaEditNegativePrompt").value = item.negative_prompt || "";
    arcaEl("arcaEditMemo").value = item.memo || "";
    arcaEl("arcaStyleImages").replaceChildren(renderArcaStyleGroups(item.style_groups || []));
    const dialog = arcaEl("arcaStyleDialog");
    dialog.querySelectorAll(".arca-dialog-scroll > label.field").forEach((field) => field.classList.add("arca-detail-edit"));
    dialog.querySelector(".modal-actions")?.classList.add("arca-dialog-actions");
    arcaEl("closeArcaStyle")?.classList.add("arca-dialog-close");
    dialog.classList.remove("hidden");
  } catch (error) {
    arcaSetStatus("arcaStyleListStatus", error.message, "error");
  }
}

async function saveArcaStyle() {
  if (!arcaState.selectedId) return;
  try {
    await arcaFetch(`/api/arca-styles/${arcaState.selectedId}`, { method: "PATCH", body: JSON.stringify({ prompt: arcaEl("arcaEditPrompt").value, negative_prompt: arcaEl("arcaEditNegativePrompt").value, memo: arcaEl("arcaEditMemo").value }) });
    arcaSetStatus("arcaStyleDialogStatus", "저장했습니다.", "success");
    await loadArcaStyles();
  } catch (error) {
    arcaSetStatus("arcaStyleDialogStatus", error.message, "error");
  }
}

async function deleteArcaStyle(id = arcaState.selectedId) {
  if (!id || !confirm("이 수집 항목을 삭제할까요?")) return;
  try {
    const result = await arcaFetch(`/api/arca-styles/${id}`, { method: "DELETE" });
    if (arcaState.selectedId === id) {
      arcaEl("arcaStyleDialog").classList.add("hidden");
      arcaState.selectedId = null;
    }
    const message = result.recollect_date
      ? `삭제했습니다. ${result.recollect_date}은 다음 수집 때 다시 검색됩니다.`
      : "삭제했습니다.";
    arcaSetStatus("arcaStyleListStatus", message, "success");
    await loadArcaStyles();
  } catch (error) {
    arcaSetStatus(arcaState.selectedId === id ? "arcaStyleDialogStatus" : "arcaStyleListStatus", error.message, "error");
  }
}

function bindArcaCollector() {
  document.querySelector('[data-tab="arca-style-collector"]')?.addEventListener("click", () => { if (!arcaState.loaded) loadArcaStyles(); });
  arcaEl("collectArcaStyles")?.addEventListener("click", collectArcaStyles);
  arcaEl("collectArcaUrl")?.addEventListener("click", collectArcaUrl);
  arcaEl("importArcaBrowserSession")?.addEventListener("click", importArcaBrowserSession);
  arcaEl("refreshArcaStyles")?.addEventListener("click", loadArcaStyles);
  arcaEl("saveArcaStyle")?.addEventListener("click", saveArcaStyle);
  arcaEl("deleteArcaStyle")?.addEventListener("click", deleteArcaStyle);
  arcaEl("closeArcaStyle")?.addEventListener("click", () => arcaEl("arcaStyleDialog").classList.add("hidden"));
  for (const id of ["arcaStyleSearch", "arcaMetadataFilter", "arcaStyleSort"]) {
    arcaEl(id)?.addEventListener("input", () => {
      clearTimeout(arcaState.timer);
      arcaState.timer = setTimeout(loadArcaStyles, 250);
    });
  }
  loadArcaBrowserSession();
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", bindArcaCollector);
if (typeof module !== "undefined") module.exports = {
  normalizeArcaPayload, normalizeArcaUrlPayload, arcaSummaryText, collectionProgress, durationText,
  etaText, collectionCountsText, groupTitle, promptSection, promptKindClass, imagePromptFields,
  arcaBrowserSessionText, isArcaBrowserSessionPending,
  arcaListQuery,
};
