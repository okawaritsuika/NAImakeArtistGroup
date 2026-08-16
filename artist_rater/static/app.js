const state = {
  candidatePool: [],
  candidateMeta: { mode: "global_random", query_tags: [], candidate_count: 0 },
  seenArtists: new Set(),
  currentPick: null,
  sampleIndex: 0,
  selectedScore: null,
  activeFilter: "all",
  loadingCandidates: false,
  loadingSamples: false,
  savingRating: false,
  autocompleteItems: [],
  autocompleteIndex: -1,
  excludeAutocompleteItems: [],
  excludeAutocompleteIndex: -1,
  manualArtistItems: [],
  manualArtistIndex: -1,
  manualPreviewSamples: [],
  manualPreviewIndex: 0,
  manualPreviewArtist: "",
  manualPreviewQueryTags: [],
  manualPreviewMode: "manual",
  manualPreviewLoading: false,
  manualPreviewRatingId: null,
  manualPreviewRatingItem: null,
};

const $ = (id) => document.getElementById(id);

function valueOf(id, fallback = "") {
  const element = $(id);
  return element ? element.value : fallback;
}

function setText(id, text) {
  const element = $(id);
  if (element) element.textContent = text;
}

function bindClick(id, handler) {
  const element = $(id);
  if (element) {
    element.addEventListener("click", handler);
  }
  return element;
}

function calculateTooltipPosition(buttonRect, tooltipRect, viewport, gap = 8, margin = 12) {
  const viewportWidth = Math.max(0, Number(viewport?.width) || 0);
  const viewportHeight = Math.max(0, Number(viewport?.height) || 0);
  const tooltipWidth = Math.max(0, Number(tooltipRect?.width) || 0);
  const tooltipHeight = Math.max(0, Number(tooltipRect?.height) || 0);
  const anchorLeft = Number(buttonRect?.left) || 0;
  const anchorTop = Number(buttonRect?.top) || 0;
  const anchorBottom = Number(buttonRect?.bottom) || anchorTop;
  const maxLeft = Math.max(margin, viewportWidth - tooltipWidth - margin);
  const left = Math.min(Math.max(margin, anchorLeft), maxLeft);
  let top = anchorTop - tooltipHeight - gap;
  if (top < margin) top = anchorBottom + gap;
  if (top + tooltipHeight > viewportHeight - margin) {
    top = Math.max(margin, viewportHeight - tooltipHeight - margin);
  }
  return { left, top };
}

function initializeHelpTooltips() {
  if (typeof document === "undefined" || typeof window === "undefined") return;
  const buttons = Array.from(document.querySelectorAll(".help-tooltip-button"));
  if (!buttons.length || !document.body) return;
  let active = null;
  let closeTimer = null;

  const viewport = () => ({
    width: window.innerWidth || document.documentElement?.clientWidth || 0,
    height: window.innerHeight || document.documentElement?.clientHeight || 0,
  });

  const clearTooltipPosition = (content) => {
    ["position", "left", "top", "right", "bottom", "transform", "z-index"].forEach((property) => {
      content.style.removeProperty(property);
    });
  };

  const positionTooltip = (entry) => {
    if (!entry.open) return;
    const buttonRect = entry.button.getBoundingClientRect();
    const tooltipRect = entry.content.getBoundingClientRect();
    const point = calculateTooltipPosition(buttonRect, tooltipRect, viewport());
    entry.content.style.left = `${Math.round(point.left)}px`;
    entry.content.style.top = `${Math.round(point.top)}px`;
  };

  const restoreTooltip = (entry) => {
    if (!entry.moved) return;
    if (entry.nextSibling && entry.nextSibling.parentNode === entry.originalParent) {
      entry.originalParent.insertBefore(entry.content, entry.nextSibling);
    } else {
      entry.originalParent.appendChild(entry.content);
    }
    entry.moved = false;
  };

  const closeTooltip = (entry) => {
    if (!entry?.open) return;
    entry.open = false;
    if (entry.usingPopover) {
      try {
        entry.content.hidePopover();
      } catch {
        // The browser may have closed the popover during navigation.
      }
      entry.content.removeAttribute("popover");
      entry.usingPopover = false;
    }
    entry.content.classList.remove("is-open");
    restoreTooltip(entry);
    clearTooltipPosition(entry.content);
    entry.button.setAttribute("aria-expanded", "false");
    if (active === entry) active = null;
  };

  const scheduleClose = (entry) => {
    clearTimeout(closeTimer);
    if (document.activeElement === entry.button) return;
    closeTimer = setTimeout(() => {
      if (!entry.content.matches(":hover") && document.activeElement !== entry.button) closeTooltip(entry);
    }, 140);
  };

  const openTooltip = (entry) => {
    clearTimeout(closeTimer);
    if (active && active !== entry) closeTooltip(active);
    if (entry.open) {
      positionTooltip(entry);
      return;
    }
    entry.open = true;
    active = entry;
    entry.button.setAttribute("aria-expanded", "true");
    entry.content.classList.add("is-open");
    const supportsPopover = typeof entry.content.showPopover === "function" && typeof entry.content.hidePopover === "function";
    if (supportsPopover) {
      entry.content.setAttribute("popover", "manual");
      try {
        entry.content.showPopover();
        entry.usingPopover = true;
      } catch {
        entry.content.removeAttribute("popover");
      }
    }
    if (!entry.usingPopover) {
      entry.originalParent = entry.content.parentNode;
      entry.nextSibling = entry.content.nextSibling;
      document.body.appendChild(entry.content);
      entry.moved = true;
    }
    entry.content.style.position = "fixed";
    entry.content.style.zIndex = "2147483647";
    positionTooltip(entry);
  };

  buttons.forEach((button) => {
    if (button.dataset.helpTooltipInitialized) return;
    const wrap = button.closest(".help-tooltip-wrap");
    const content = wrap?.querySelector(".help-tooltip-content");
    if (!content) return;
    const entry = {
      button,
      content,
      originalParent: content.parentNode,
      nextSibling: content.nextSibling,
      moved: false,
      usingPopover: false,
      open: false,
    };
    button.dataset.helpTooltipInitialized = "true";
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("mouseenter", () => openTooltip(entry));
    button.addEventListener("mouseleave", () => scheduleClose(entry));
    button.addEventListener("focus", () => openTooltip(entry));
    button.addEventListener("blur", () => scheduleClose(entry));
    content.addEventListener("mouseenter", () => clearTimeout(closeTimer));
    content.addEventListener("mouseleave", () => scheduleClose(entry));
  });

  document.addEventListener("pointerdown", (event) => {
    if (!active) return;
    if (!active.button.contains(event.target) && !active.content.contains(event.target)) closeTooltip(active);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeTooltip(active);
  });
  window.addEventListener("resize", () => active && positionTooltip(active));
  window.addEventListener("scroll", () => active && positionTooltip(active), true);
}

function showStatus(target, message, type = "") {
  if (!target) return;
  target.textContent = message || "";
  target.className = `status ${type}`;
}

async function apiFetch(url, options = {}) {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const response = await fetch(url, {
    headers: { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || data.reason || `HTTP ${response.status}`);
  }
  return data;
}

function copyText(text) {
  navigator.clipboard.writeText(text || "");
}

function lastTagFragment(text) {
  const match = text.match(/([^,\s\n\r]+)$/);
  return match ? match[1] : "";
}

function replaceLastFragment(text, replacement) {
  return text.replace(/([^,\s\n\r]+)$/, replacement);
}

function normalizeTags(text) {
  return String(text || "")
    .split(/[\s,\n\r]+/)
    .map((tag) => tag.trim().replace(/\s+/g, "_"))
    .filter((tag, index, tags) => tag && tags.indexOf(tag) === index);
}

function selectedCandidateCutoffDate() {
  const preset = valueOf("candidateCutoffPreset", "2025-01-31");
  if (preset !== "custom") return preset;
  const custom = valueOf("candidateCutoffDate").trim();
  if (!custom) throw new Error("직접 지정 기준일을 입력하세요.");
  return custom;
}

function syncCandidateCutoffDateControl() {
  const preset = $("candidateCutoffPreset");
  const custom = $("candidateCutoffDate");
  const active = preset?.value === "custom";
  if (custom) {
    custom.hidden = !active;
    custom.disabled = !active;
  }
}

function requestPayload() {
  return {
    query_text: valueOf("queryText"),
    min_artist_post_count: Number(valueOf("minArtistPostCount", 1000) || 1000),
    min_match_count: Number(valueOf("minMatchCount", 3) || 3),
    fetch_pages: Number(valueOf("fetchPages", 5) || 5),
    candidate_limit: Number(valueOf("candidateLimit", 12) || 12),
    sample_limit: Number(valueOf("sampleLimit", 10) || 10),
    random_mode: valueOf("randomMode", "soft_weighted"),
    exclude_query_text: valueOf("excludeQueryText"),
    latest_samples: Boolean($("latestSamples")?.checked),
    cutoff_date: selectedCandidateCutoffDate(),
    exclude_artist_tags: Array.from(state.seenArtists),
  };
}

function updatePoolStatus() {
  const poolStatus = $("poolStatus");
  if (!poolStatus) return;
  poolStatus.textContent = state.candidatePool.length
    ? `남은 후보 ${state.candidatePool.length}명 / 이번 세션 제외 ${state.seenArtists.size}명`
    : "후보 없음";
}

function candidateButtonElement() {
  return $("candidateButton") || $("pickButton");
}

function formatFilterStats(stats) {
  if (!stats) return "";
  const parts = [];
  if (stats.fetched_post_count) parts.push(`게시물 ${stats.fetched_post_count}개`);
  if (stats.unique_artist_count) parts.push(`고유 작가 ${stats.unique_artist_count}명`);
  if (stats.min_match_candidate_count) parts.push(`최소 출현 통과 ${stats.min_match_candidate_count}명`);
  if (stats.post_count_filtered_count) parts.push(`게시물 수 필터 제외 ${stats.post_count_filtered_count}명`);
  if (stats.exclude_prompt_filtered_count) parts.push(`제외 프롬프트 일치 ${stats.exclude_prompt_filtered_count}명`);
  parts.push(`최종 ${stats.final_candidate_count || 0}명`);
  return parts.join(" · ");
}

function autocompleteConfig(kind = "query") {
  return kind === "exclude"
    ? { inputId: "excludeQueryText", boxId: "excludeAutocomplete", itemsKey: "excludeAutocompleteItems", indexKey: "excludeAutocompleteIndex" }
    : { inputId: "queryText", boxId: "autocomplete", itemsKey: "autocompleteItems", indexKey: "autocompleteIndex" };
}

async function updateAutocomplete(kind = "query") {
  const config = autocompleteConfig(kind);
  const box = $(config.boxId);
  const textarea = $(config.inputId);
  if (!box || !textarea) return;
  const q = lastTagFragment(textarea.value);
  if (!q || q.length < 2) {
    box.classList.add("hidden");
    state[config.itemsKey] = [];
    state[config.indexKey] = -1;
    return;
  }
  try {
    const items = await apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(q)}`);
    if (!Array.isArray(items) || !items.length) {
      box.classList.add("hidden");
      state[config.itemsKey] = [];
      state[config.indexKey] = -1;
      return;
    }
    state[config.itemsKey] = items;
    state[config.indexKey] = -1;
    box.innerHTML = "";
    items.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.index = String(index);
      button.innerHTML = `<span>${item.name}</span><span>${item.category_name} · ${item.post_count}</span>`;
      button.addEventListener("mouseenter", () => setAutocompleteIndex(index, kind));
      button.addEventListener("click", () => applyAutocompleteItem(index, kind));
      box.appendChild(button);
    });
    box.classList.remove("hidden");
  } catch {
    box.classList.add("hidden");
    state[config.itemsKey] = [];
    state[config.indexKey] = -1;
  }
}

function setAutocompleteIndex(index, kind = "query") {
  const config = autocompleteConfig(kind);
  const box = $(config.boxId);
  const items = state[config.itemsKey];
  if (!box || !items.length) return;
  state[config.indexKey] = (index + items.length) % items.length;
  box.querySelectorAll("button").forEach((button, buttonIndex) => {
    button.classList.toggle("active", buttonIndex === state[config.indexKey]);
  });
}

function applyAutocompleteItem(index, kind = "query") {
  const config = autocompleteConfig(kind);
  const textarea = $(config.inputId);
  const box = $(config.boxId);
  const resolvedIndex = index ?? state[config.indexKey];
  const item = state[config.itemsKey][resolvedIndex];
  if (!textarea || !box || !item) return;
  textarea.value = replaceLastFragment(textarea.value, item.name);
  box.classList.add("hidden");
  state[config.itemsKey] = [];
  state[config.indexKey] = -1;
  textarea.focus();
}

function handleAutocompleteKeydown(event, kind = "query") {
  const config = autocompleteConfig(kind);
  const box = $(config.boxId);
  const items = state[config.itemsKey];
  if (!box || box.classList.contains("hidden") || !items.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setAutocompleteIndex(state[config.indexKey] + 1, kind);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setAutocompleteIndex(state[config.indexKey] <= 0 ? items.length - 1 : state[config.indexKey] - 1, kind);
  } else if (event.key === "Enter") {
    if (state[config.indexKey] >= 0) {
      event.preventDefault();
      applyAutocompleteItem(undefined, kind);
    }
  } else if (event.key === "Escape") {
    box.classList.add("hidden");
    state[config.indexKey] = -1;
  }
}

async function updateManualArtistAutocomplete() {
  const input = $("manualArtist");
  const box = $("manualArtistAutocomplete");
  if (!input || !box) return;
  const query = input.value.trim();
  if (query.length < 2) {
    box.classList.add("hidden");
    state.manualArtistItems = [];
    state.manualArtistIndex = -1;
    return;
  }
  try {
    const items = await apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}&category=1`);
    state.manualArtistItems = Array.isArray(items) ? items : [];
    state.manualArtistIndex = -1;
    box.innerHTML = "";
    state.manualArtistItems.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<span>${item.name}</span><span>${item.post_count}</span>`;
      button.addEventListener("mouseenter", () => setManualArtistIndex(index));
      button.addEventListener("click", () => applyManualArtist(index));
      box.appendChild(button);
    });
    box.classList.toggle("hidden", !state.manualArtistItems.length);
  } catch {
    box.classList.add("hidden");
  }
}

function setManualArtistIndex(index) {
  const box = $("manualArtistAutocomplete");
  if (!box || !state.manualArtistItems.length) return;
  state.manualArtistIndex = (index + state.manualArtistItems.length) % state.manualArtistItems.length;
  box.querySelectorAll("button").forEach((button, buttonIndex) => {
    button.classList.toggle("active", buttonIndex === state.manualArtistIndex);
  });
}

function applyManualArtist(index = state.manualArtistIndex) {
  const input = $("manualArtist");
  const box = $("manualArtistAutocomplete");
  const item = state.manualArtistItems[index];
  if (!input || !box || !item) return;
  input.value = item.name;
  input.dataset.postCount = String(item.post_count || 0);
  box.classList.add("hidden");
  state.manualArtistItems = [];
  state.manualArtistIndex = -1;
  input.focus();
}

function handleManualArtistKeydown(event) {
  const box = $("manualArtistAutocomplete");
  if (!box || box.classList.contains("hidden") || !state.manualArtistItems.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setManualArtistIndex(state.manualArtistIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setManualArtistIndex(state.manualArtistIndex <= 0 ? state.manualArtistItems.length - 1 : state.manualArtistIndex - 1);
  } else if (event.key === "Enter") {
    if (state.manualArtistIndex >= 0) {
      event.preventDefault();
      applyManualArtist();
    }
  } else if (event.key === "Escape") {
    box.classList.add("hidden");
  }
}

async function addManualRating() {
  const artist = valueOf("manualArtist").trim();
  const tags = normalizeTags(valueOf("manualTags"));
  if (!artist) {
    showStatus($("ratingsStatus"), "작가 태그를 입력하세요.", "error");
    return;
  }
  try {
    await apiFetch("/api/ratings", {
      method: "POST",
      body: JSON.stringify({
        artist_tag: artist,
        score: Number(valueOf("manualScore", 3) || 3),
        memo: valueOf("manualMemo"),
        mode: "manual",
        query_text: valueOf("manualTags"),
        query_tags: tags,
        artist_post_count: Number($("manualArtist")?.dataset.postCount || 0),
        prompt_text: `${artist}, masterpiece, best quality, very aesthetic`,
        ...manualPreviewRatingFields(artist, tags, {
          artist: state.manualPreviewArtist,
          queryTags: state.manualPreviewQueryTags,
          sample: state.manualPreviewSamples[state.manualPreviewIndex],
          sampleIds: state.manualPreviewSamples.map((item) => item.id),
        }),
      }),
    });
    $("manualArtist").value = "";
    $("manualArtist").dataset.postCount = "0";
    $("manualTags").value = "";
    $("manualMemo").value = "";
    state.manualPreviewSamples = [];
    state.manualPreviewIndex = 0;
    state.manualPreviewArtist = "";
    state.manualPreviewQueryTags = [];
    state.manualPreviewMode = "manual";
    state.manualPreviewRatingId = null;
    state.manualPreviewRatingItem = null;
    showStatus($("ratingsStatus"), `${artist} 작가를 추가했습니다.`, "ok");
    await loadRatings();
  } catch (error) {
    showStatus($("ratingsStatus"), error.message, "error");
  }
}

let appDialogResolve = null;
const DELETE_CONFIRMATION_CATEGORIES = [
  "rating_example",
  "rating",
  "generated",
  "style",
  "arca_style",
  "comparison_group",
  "comparison_result",
  "novelai_key",
];
const defaultDeleteConfirmationPreferences = () => Object.fromEntries(
  DELETE_CONFIRMATION_CATEGORIES.map((category) => [category, false]),
);
let appPreferences = { skip_delete_confirmation: defaultDeleteConfirmationPreferences() };

function normalizeDeleteConfirmationPreferences(value) {
  if (typeof value === "boolean") {
    return Object.fromEntries(DELETE_CONFIRMATION_CATEGORIES.map((category) => [category, value]));
  }
  if (!value || typeof value !== "object") return defaultDeleteConfirmationPreferences();
  return Object.fromEntries(DELETE_CONFIRMATION_CATEGORIES.map((category) => [
    category,
    value[category] === true,
  ]));
}

function setAppPreferences(preferences = {}) {
  appPreferences = {
    ...appPreferences,
    skip_delete_confirmation: normalizeDeleteConfirmationPreferences(preferences.skip_delete_confirmation),
  };
  return { ...appPreferences };
}

function closeAppDialog(value) {
  const modal = $("appDialog");
  if (!modal || !appDialogResolve) return;
  modal.classList.add("hidden");
  const resolve = appDialogResolve;
  appDialogResolve = null;
  resolve(value);
}

function openAppDialog(options = {}) {
  const modal = $("appDialog");
  if (!modal) return Promise.resolve(options.input ? null : false);
  if (appDialogResolve) closeAppDialog(options.input ? null : false);
  const isInput = options.input === true;
  const title = $("appDialogTitle");
  const message = $("appDialogMessage");
  const icon = $("appDialogIcon");
  const details = $("appDialogDetails");
  const inputField = $("appDialogInputField");
  const inputLabel = $("appDialogInputLabel");
  const input = $("appDialogInput");
  const cancel = $("appDialogCancel");
  const confirm = $("appDialogConfirm");
  modal.dataset.tone = options.tone || "warning";
  if (title) title.textContent = options.title || "확인";
  if (message) message.textContent = options.message || "계속 진행할까요?";
  if (icon) icon.textContent = options.icon || (modal.dataset.tone === "danger" ? "×" : modal.dataset.tone === "info" ? "i" : "!");
  if (details) {
    details.replaceChildren();
    (Array.isArray(options.details) ? options.details : []).forEach((item) => {
      const row = document.createElement("li");
      row.textContent = String(item);
      details.append(row);
    });
    details.classList.toggle("hidden", !details.children.length);
  }
  inputField?.classList.toggle("hidden", !isInput);
  if (inputLabel) inputLabel.textContent = options.inputLabel || "입력";
  if (input) input.value = isInput ? String(options.defaultValue || "") : "";
  if (cancel) cancel.textContent = options.cancelLabel || "취소";
  if (confirm) confirm.textContent = options.confirmLabel || "확인";
  modal.classList.remove("hidden");
  requestAnimationFrame(() => (isInput ? input : confirm)?.focus());
  if (isInput && input) input.select();
  return new Promise((resolve) => { appDialogResolve = resolve; });
}

function appConfirm(options) {
  const normalized = typeof options === "string" ? { message: options } : options;
  const category = normalized?.delete_category;
  if (
    normalized?.delete === true
    && DELETE_CONFIRMATION_CATEGORIES.includes(category)
    && appPreferences.skip_delete_confirmation[category] === true
  ) return Promise.resolve(true);
  return openAppDialog(normalized).then(Boolean);
}

function appPrompt(options) {
  const normalized = typeof options === "string" ? { title: options } : options;
  return openAppDialog({ ...normalized, input: true });
}

globalThis.appDialog = {
  confirm: appConfirm,
  prompt: appPrompt,
  setPreferences: setAppPreferences,
  getPreferences: () => ({ ...appPreferences }),
};

async function loadAppPreferences() {
  if (typeof fetch !== "function") return appPreferences;
  try {
    const response = await apiFetch("/api/settings/preferences");
    return setAppPreferences(response);
  } catch (_) {
    return appPreferences;
  }
}


function manualPreviewRatingFields(artist, queryTags, preview) {
  const sameArtist = String(preview?.artist || "") === String(artist || "");
  const sameTags = JSON.stringify(preview?.queryTags || []) === JSON.stringify(queryTags || []);
  if (!sameArtist || !sameTags || !preview?.sample) return {};
  return {
    representative_post_id: preview.sample.id,
    representative_preview_url: preview.sample.large_url || preview.sample.preview_url || "",
    sample_post_ids: preview.sampleIds || [],
  };
}

function sampleKey(sample) {
  if (sample?.id !== undefined && sample?.id !== null) return `id:${sample.id}`;
  return `url:${sample?.large_url || sample?.preview_url || ""}`;
}

function normalizePreviewSample(sample) {
  if (!sample || typeof sample !== "object") return null;
  const imageUrl = validatedImageUrl(sample.large_url) || validatedImageUrl(sample.preview_url);
  if (!imageUrl) return null;
  return {
    ...sample,
    large_url: imageUrl,
    preview_url: validatedImageUrl(sample.preview_url) || imageUrl,
    post_url: validatedImageUrl(sample.post_url),
  };
}

function mergePreviewSamples(existing, incoming) {
  const merged = Array.isArray(existing) ? [...existing] : [];
  const seen = new Set(merged.map(sampleKey));
  for (const sample of Array.isArray(incoming) ? incoming : []) {
    const safeSample = normalizePreviewSample(sample);
    if (!safeSample) continue;
    const key = sampleKey(safeSample);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(safeSample);
  }
  return merged;
}

function normalizeStoredRatingExample(example) {
  if (!example || typeof example !== "object") return null;
  const sample = normalizePreviewSample({
    ...example,
    id: example.post_id ?? example.id,
    example_id: example.example_id ?? example.id,
    large_url: example.image_url,
    preview_url: example.image_url,
    post_url: example.post_url,
  });
  if (!sample) return null;
  sample.example_id = example.example_id ?? example.id;
  sample.post_id = example.post_id ?? example.id;
  sample.source_url = validatedImageUrl(example.source_url);
  sample.is_thumbnail = example.is_thumbnail === true;
  sample.is_stored_example = true;
  return sample;
}

function combineRatingSamples(representative, storedExamples) {
  const stored = (Array.isArray(storedExamples) ? storedExamples : [])
    .map(normalizeStoredRatingExample)
    .filter(Boolean);
  const representativeKey = representative ? sampleKey(representative) : "";
  const storedRepresentative = stored.find((sample) => (
    sample.is_thumbnail || (representativeKey && sampleKey(sample) === representativeKey)
  ));
  const first = storedRepresentative || representative;
  if (first) first.is_representative = true;
  const seen = new Set(first ? [sampleKey(first)] : []);
  const samples = first ? [first] : [];
  for (const sample of stored) {
    const key = sampleKey(sample);
    if (seen.has(key)) continue;
    seen.add(key);
    samples.push(sample);
  }
  return samples;
}

function renderManualPreviewSample() {
  const sample = state.manualPreviewSamples[state.manualPreviewIndex];
  if (!sample) return;
  const image = $("manualPreviewImage");
  const link = $("manualPreviewLink");
  const setThumbnail = $("manualPreviewSetThumbnail");
  const deleteExample = $("manualPreviewDeleteExample");
  const representativeBadge = $("manualPreviewRepresentativeBadge");
  const imageUrl = validatedImageUrl(sample.large_url) || validatedImageUrl(sample.preview_url);
  const postUrl = validatedImageUrl(sample.post_url);
  if (image) {
    image.src = imageUrl;
    image.hidden = !imageUrl;
  }
  if (link) {
    link.href = postUrl || "#";
    link.hidden = !postUrl;
  }
  const isRepresentative = sample.is_representative === true || sample.is_thumbnail === true;
  if (representativeBadge) representativeBadge.hidden = !isRepresentative;
  if (setThumbnail) {
    setThumbnail.hidden = state.manualPreviewMode !== "rating" || !sample.example_id;
    setThumbnail.disabled = isRepresentative || !sample.example_id;
  }
  if (deleteExample) {
    deleteExample.hidden = state.manualPreviewMode !== "rating" || !sample.example_id;
    deleteExample.disabled = state.manualPreviewMode !== "rating" || !sample.example_id;
  }
  setText("manualPreviewCounter", `${state.manualPreviewIndex + 1} / ${state.manualPreviewSamples.length}`);
}

function moveManualPreview(delta) {
  if (!state.manualPreviewSamples.length) return;
  state.manualPreviewIndex = (
    state.manualPreviewIndex + delta + state.manualPreviewSamples.length
  ) % state.manualPreviewSamples.length;
  renderManualPreviewSample();
}

function closeManualPreview() {
  $("manualPreviewModal")?.classList.add("hidden");
}

async function loadManualPreviewSamples({ append = false } = {}) {
  const artist = state.manualPreviewArtist;
  if (!artist || state.manualPreviewLoading) return false;
  state.manualPreviewLoading = true;
  const loadMore = $("manualPreviewLoadMore");
  if (loadMore) loadMore.disabled = true;
  showStatus($("manualPreviewStatus"), append ? "추가 예제 그림을 가져오는 중입니다..." : "샘플 이미지 10장을 가져오는 중입니다...");
  try {
    const data = await apiFetch("/api/artist_samples", {
      method: "POST",
      body: JSON.stringify({
        artist_tag: artist,
        query_tags: state.manualPreviewQueryTags,
        sample_limit: 10,
        mode: state.manualPreviewMode === "rating" ? "rating_preview" : "manual_preview",
      }),
    });
    const nextSamples = data.ok === false
      ? []
      : mergePreviewSamples(state.manualPreviewSamples, data.samples);
    if (!nextSamples.length) {
      showStatus($("manualPreviewStatus"), data.reason || "표시할 그림이 없습니다.", "error");
      return false;
    }
    const previousCount = state.manualPreviewSamples.length;
    state.manualPreviewSamples = nextSamples;
    state.manualPreviewIndex = append && nextSamples.length > previousCount
      ? previousCount
      : Math.min(state.manualPreviewIndex, nextSamples.length - 1);
    $("manualPreviewViewer")?.classList.remove("hidden");
    showStatus(
      $("manualPreviewStatus"),
      append && nextSamples.length === previousCount
        ? "새로 추가된 예제가 없습니다."
        : `${nextSamples.length}장을 확인할 수 있습니다.`,
      "ok",
    );
    renderManualPreviewSample();
    return true;
  } catch (error) {
    showStatus($("manualPreviewStatus"), error.message, "error");
    return false;
  } finally {
    state.manualPreviewLoading = false;
    if (loadMore) loadMore.disabled = false;
  }
}

async function loadStoredRatingExamples(preserveKey = "") {
  const ratingId = state.manualPreviewRatingId;
  if (!ratingId) return false;
  try {
    const data = await apiFetch(`/api/ratings/${ratingId}/examples`);
    const rating = data.rating || {};
    state.manualPreviewRatingItem = { ...(state.manualPreviewRatingItem || {}), ...rating };
    const representative = buildRatingRepresentativeSample(state.manualPreviewRatingItem);
    const samples = combineRatingSamples(representative, data.examples);
    state.manualPreviewSamples = samples;
    const nextIndex = preserveKey
      ? samples.findIndex((sample) => sampleKey(sample) === preserveKey)
      : -1;
    state.manualPreviewIndex = nextIndex >= 0
      ? nextIndex
      : Math.min(state.manualPreviewIndex, Math.max(0, samples.length - 1));
    $("manualPreviewViewer")?.classList.toggle("hidden", !samples.length);
    renderManualPreviewSample();
    showStatus($("manualPreviewStatus"), `저장된 예제 ${data.examples?.length || 0}장`, "ok");
    return true;
  } catch (error) {
    showStatus($("manualPreviewStatus"), error.message, "error");
    return false;
  }
}

async function collectRatingExamples() {
  if (state.manualPreviewMode !== "rating" || !state.manualPreviewRatingId || state.manualPreviewLoading) return false;
  const current = state.manualPreviewSamples[state.manualPreviewIndex];
  const loadMore = $("manualPreviewLoadMore");
  state.manualPreviewLoading = true;
  if (loadMore) loadMore.disabled = true;
  showStatus($("manualPreviewStatus"), "추가 예제를 수집하는 중입니다...");
  try {
    const data = await apiFetch(`/api/ratings/${state.manualPreviewRatingId}/examples/collect`, {
      method: "POST",
      body: JSON.stringify({ sample_limit: 10 }),
    });
    await loadStoredRatingExamples(current ? sampleKey(current) : "");
    await loadRatings();
    showStatus($("manualPreviewStatus"), `추가 예제 ${data.saved_count || 0}장을 저장했습니다.`, "ok");
    return true;
  } catch (error) {
    showStatus($("manualPreviewStatus"), error.message, "error");
    return false;
  } finally {
    state.manualPreviewLoading = false;
    if (loadMore) loadMore.disabled = false;
    renderManualPreviewSample();
  }
}

async function setRatingExampleThumbnail() {
  const sample = state.manualPreviewSamples[state.manualPreviewIndex];
  if (state.manualPreviewMode !== "rating" || !state.manualPreviewRatingId || !sample?.example_id) return false;
  const currentKey = sampleKey(sample);
  showStatus($("manualPreviewStatus"), "대표 썸네일을 지정하는 중입니다...");
  try {
    await apiFetch(`/api/ratings/${state.manualPreviewRatingId}/examples/${sample.example_id}/thumbnail`, { method: "POST" });
    await loadStoredRatingExamples(currentKey);
    await loadRatings();
    showStatus($("manualPreviewStatus"), "대표 썸네일로 지정했습니다.", "ok");
    return true;
  } catch (error) {
    showStatus($("manualPreviewStatus"), error.message, "error");
    return false;
  }
}

async function deleteRatingExample() {
  const sample = state.manualPreviewSamples[state.manualPreviewIndex];
  if (state.manualPreviewMode !== "rating" || !state.manualPreviewRatingId || !sample?.example_id) return false;
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "rating_example",
    title: "예제 그림 삭제",
    message: "현재 예제 그림을 삭제할까요? 대표 썸네일이면 대표 지정도 해제됩니다.",
    confirmLabel: "삭제",
    tone: "danger",
  })) return false;
  const currentKey = sampleKey(sample);
  showStatus($("manualPreviewStatus"), "예제를 삭제하는 중입니다...");
  try {
    await apiFetch(`/api/ratings/${state.manualPreviewRatingId}/examples/${sample.example_id}`, { method: "DELETE" });
    await loadStoredRatingExamples(currentKey);
    await loadRatings();
    showStatus($("manualPreviewStatus"), "예제를 삭제했습니다.", "ok");
    return true;
  } catch (error) {
    showStatus($("manualPreviewStatus"), error.message, "error");
    return false;
  }
}

function loadMoreManualPreviewSamples() {
  if (state.manualPreviewMode === "rating") return collectRatingExamples();
  return loadManualPreviewSamples({ append: true });
}

function buildRatingRepresentativeSample(item) {
  const representativeUrl = validatedImageUrl(item.representative_preview_url) || validatedImageUrl(item.thumbnail_url);
  return normalizePreviewSample({
    id: item.representative_post_id,
    preview_url: representativeUrl,
    large_url: representativeUrl,
    post_url: buildDanbooruPostUrl(item.representative_post_id) || item.representative_post_url,
  });
}

async function openRatingSampleViewer(item) {
  const modal = $("manualPreviewModal");
  const viewer = $("manualPreviewViewer");
  const representative = buildRatingRepresentativeSample(item);
  state.manualPreviewMode = "rating";
  state.manualPreviewRatingId = item.id;
  state.manualPreviewRatingItem = { ...item };
  state.manualPreviewArtist = String(item.artist_tag || "").trim();
  state.manualPreviewQueryTags = Array.isArray(item.query_tags) ? item.query_tags : [];
  state.manualPreviewSamples = representative ? [representative] : [];
  state.manualPreviewIndex = 0;
  modal?.classList.remove("hidden");
  viewer?.classList.toggle("hidden", !state.manualPreviewSamples.length);
  setText("manualPreviewLoadMore", "추가 예제 수집");
  setText("manualPreviewTitle", "평가 작가 예제 그림");
  setText("manualPreviewArtist", state.manualPreviewArtist);
  showStatus(
    $("manualPreviewStatus"),
    representative ? "저장된 대표 썸네일입니다. 추가 예제를 조회할 수 있습니다." : "저장된 썸네일이 없습니다. 추가 예제를 조회하세요.",
    representative ? "ok" : "",
  );
  renderManualPreviewSample();
  await loadStoredRatingExamples();
}

function resetManualPreviewState() {
  state.manualPreviewSamples = [];
  state.manualPreviewIndex = 0;
  state.manualPreviewArtist = "";
  state.manualPreviewQueryTags = [];
  state.manualPreviewMode = "manual";
  state.manualPreviewRatingId = null;
  state.manualPreviewRatingItem = null;
}

async function openManualPreview() {
  const artist = valueOf("manualArtist").trim();
  const queryTags = normalizeTags(valueOf("manualTags"));
  if (!artist) {
    showStatus($("ratingsStatus"), "그림을 볼 작가 태그를 먼저 입력하세요.", "error");
    return;
  }
  const modal = $("manualPreviewModal");
  const viewer = $("manualPreviewViewer");
  resetManualPreviewState();
  state.manualPreviewArtist = artist;
  state.manualPreviewQueryTags = queryTags;
  modal?.classList.remove("hidden");
  viewer?.classList.add("hidden");
  setText("manualPreviewTitle", "작가 그림 보기");
  setText("manualPreviewArtist", artist);
  setText("manualPreviewLoadMore", "추가 예제 조회");
  await loadManualPreviewSamples();
}

async function loadCandidatePool(force = false) {
  if (state.candidatePool.length && !force) return true;
  if (state.loadingCandidates) return false;
  const button = candidateButtonElement();
  state.loadingCandidates = true;
  if (button) button.disabled = true;
  showStatus($("status"), "작가 후보를 검색하는 중입니다...");
  try {
    const data = await apiFetch("/api/candidates", {
      method: "POST",
      body: JSON.stringify(requestPayload()),
    });
    if (!data.ok) {
      state.candidatePool = [];
      updatePoolStatus();
      $("result")?.classList.add("hidden");
      showStatus($("status"), data.reason || "후보가 없습니다.", "error");
      return false;
    }
    state.candidatePool = data.candidates || [];
    state.candidateMeta = {
      mode: data.mode,
      query_tags: data.query_tags || [],
      cutoff_date: data.cutoff_date || "2025-01-31",
      candidate_count: data.candidate_count || state.candidatePool.length,
      requested_count: Number(valueOf("candidateLimit", 12) || 12),
      latest_samples: data.latest_samples === true,
      filter_stats: data.filter_stats || null,
    };
    updatePoolStatus();
    showStatus(
      $("status"),
      `후보 ${state.candidatePool.length}명을 준비했습니다. ${formatFilterStats(data.filter_stats)}`,
      "ok",
    );
    return state.candidatePool.length > 0;
  } catch (error) {
    showStatus($("status"), error.message, "error");
    return false;
  } finally {
    state.loadingCandidates = false;
    if (button) button.disabled = false;
  }
}

async function showNextArtist() {
  if (state.loadingSamples) return;
  if (!state.candidatePool.length) {
    const shouldCollect = await globalThis.appDialog.confirm({
      title: "후보를 모두 확인했습니다",
      message: "새 후보 작가를 다시 수집할까요?",
      confirmLabel: "새 후보 수집",
      tone: "info",
    });
    if (!shouldCollect) {
      showStatus($("status"), "후보 수집을 멈췄습니다. 새 후보 검색을 누르면 다시 수집할 수 있습니다.");
      return;
    }
    const loaded = await loadCandidatePool(true);
    if (!loaded) return;
  }

  const candidate = state.candidatePool.shift();
  state.seenArtists.add(candidate.artist_tag || candidate.artist);
  updatePoolStatus();
  state.loadingSamples = true;
  const nextButton = $("nextArtist");
  if (nextButton) nextButton.disabled = true;
  showStatus($("status"), `${candidate.artist} 샘플 이미지를 가져오는 중입니다...`);
  try {
    const data = await apiFetch("/api/artist_samples", {
      method: "POST",
      body: JSON.stringify({
        ...candidate,
        mode: state.candidateMeta.mode,
        query_tags: state.candidateMeta.query_tags,
        sample_limit: Number(valueOf("sampleLimit", 10) || 10),
        latest_samples: state.candidateMeta.latest_samples === true,
        cutoff_date: state.candidateMeta.cutoff_date || "2025-01-31",
      }),
    });
    if (!data.ok) {
      showStatus($("status"), data.reason || "샘플 이미지가 없습니다.", "error");
      return;
    }
    renderPick({
      ...candidate,
      ...data,
      candidate_count: state.candidateMeta.candidate_count,
    });
    showStatus($("status"), "작가를 표시했습니다.", "ok");
  } catch (error) {
    showStatus($("status"), error.message, "error");
  } finally {
    state.loadingSamples = false;
    if (nextButton) nextButton.disabled = false;
  }
}

function renderCurrentSample() {
  const pick = state.currentPick;
  if (!pick || !pick.samples.length) return;
  const sample = pick.samples[state.sampleIndex];
  const image = $("sampleImage");
  const postLink = $("postLink");
  if (image) image.src = sample.large_url || sample.preview_url;
  setText("sampleCounter", `${state.sampleIndex + 1} / ${pick.samples.length}`);
  if (postLink) postLink.href = sample.post_url || "#";
}

function moveSample(delta) {
  const samples = state.currentPick?.samples || [];
  if (!samples.length) return;
  state.sampleIndex = (state.sampleIndex + delta + samples.length) % samples.length;
  renderCurrentSample();
}

function renderPick(data) {
  state.currentPick = data;
  state.sampleIndex = 0;
  state.selectedScore = null;
  $("result")?.classList.remove("hidden");
  setText("artistName", data.artist);
  setText("promptText", data.prompt_text);
  setText("modeBadge", `mode: ${data.mode}`);
  setText("queryTagsBadge", `query: ${data.query_tags.length ? data.query_tags.join(", ") : "전체"}`);
  setText("matchedCount", `matched: ${data.matched_post_count}`);
  setText("artistPostCount", `artist posts: ${data.artist_post_count}`);
  setText("candidateCount", `pool left: ${state.candidatePool.length}`);
  const memo = $("memo");
  if (memo) memo.value = "";
  document.querySelectorAll("#scoreButtons button").forEach((button) => button.classList.remove("active"));
  renderCurrentSample();
}

function setScoreButtonsDisabled(disabled) {
  document.querySelectorAll("#scoreButtons button").forEach((button) => {
    button.disabled = disabled;
  });
}

async function saveRating(nextAfter, scoreOverride = null) {
  if (!state.currentPick) {
    showStatus($("status"), "저장할 추천 결과가 없습니다.", "error");
    return;
  }
  const score = scoreOverride || state.selectedScore;
  if (!score) {
    showStatus($("status"), "점수를 먼저 선택하세요.", "error");
    return;
  }
  if (state.savingRating) return;
  const sample = state.currentPick.samples[state.sampleIndex] || state.currentPick.samples[0];
  state.savingRating = true;
  setScoreButtonsDisabled(true);
  try {
    await apiFetch("/api/ratings", {
      method: "POST",
      body: JSON.stringify({
        artist_tag: state.currentPick.artist,
        score,
        memo: valueOf("memo"),
        mode: state.currentPick.mode,
        query_text: valueOf("queryText"),
        query_tags: state.currentPick.query_tags,
        matched_post_count: state.currentPick.matched_post_count,
        artist_post_count: state.currentPick.artist_post_count,
        representative_post_id: sample?.id,
        representative_preview_url: sample?.large_url || sample?.preview_url || "",
        sample_post_ids: state.currentPick.samples.map((item) => item.id),
        prompt_text: state.currentPick.prompt_text,
      }),
    });
    state.seenArtists.add(state.currentPick.artist);
    showStatus($("status"), "저장했습니다.", "ok");
    loadRatings();
    if (nextAfter) {
      await showNextArtist();
    }
  } catch (error) {
    showStatus($("status"), error.message, "error");
  } finally {
    state.savingRating = false;
    setScoreButtonsDisabled(false);
  }
}

function ratingParams() {
  const params = new URLSearchParams();
  const filter = state.activeFilter;
  if (filter === "score5") params.set("score_min", "5");
  if (filter === "score4") params.set("score_min", "4");
  if (filter === "score3") params.set("score_max", "3");
  const ratingSearch = valueOf("ratingSearch").trim();
  if (ratingSearch) params.set("q", ratingSearch);
  params.set("sort", valueOf("ratingSort", "recent"));
  return params.toString();
}

function scoreText(score) {
  return "★".repeat(score) + "☆".repeat(5 - score);
}

function validatedImageUrl(value) {
  if (!value) return "";
  try {
    const base = typeof window !== "undefined" && window.location?.origin
      ? window.location.origin
      : "http://localhost";
    const parsed = new URL(String(value), base);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? String(value) : "";
  } catch {
    return "";
  }
}

function buildDanbooruSearchUrl(artistTag, queryTags = []) {
  const tags = [
    String(artistTag || "").trim(),
    ...(Array.isArray(queryTags) ? queryTags : []),
  ]
    .map((tag) => String(tag || "").trim())
    .filter(Boolean);
  const params = new URLSearchParams();
  params.set("tags", tags.join(" "));
  return `https://danbooru.donmai.us/posts?${params.toString()}`;
}

function buildDanbooruPostUrl(postId) {
  const normalized = String(postId ?? "").trim();
  return /^\d+$/.test(normalized)
    ? `https://danbooru.donmai.us/posts/${normalized}`
    : "";
}

function renderRatingCard(item) {
  const card = document.createElement("article");
  card.className = "card";
  const thumb = validatedImageUrl(item.thumbnail_url) || validatedImageUrl(item.representative_preview_url);
  if (thumb) {
    const thumbButton = document.createElement("button");
    thumbButton.type = "button";
    thumbButton.className = "thumb-button";
    thumbButton.dataset.action = "open-samples";
    thumbButton.setAttribute("aria-label", `${String(item.artist_tag || "작가")} 예제 그림 크게 보기`);
    const image = document.createElement("img");
    image.className = "thumb";
    image.src = thumb;
    image.alt = String(item.artist_tag || "");
    image.loading = "lazy";
    thumbButton.append(image);
    card.append(thumbButton);
  } else {
    const empty = document.createElement("div");
    empty.className = "thumb thumb-empty";
    empty.textContent = "썸네일 없음";
    card.append(empty);
  }

  const body = document.createElement("div");
  body.className = "card-body";
  const heading = document.createElement("h3");
  heading.textContent = String(item.artist_tag || "");
  const score = document.createElement("strong");
  score.textContent = `${scoreText(item.score)} (${item.score})`;
  const memoPreview = document.createElement("p");
  memoPreview.className = "memo-preview";
  memoPreview.textContent = String(item.memo || "");

  const meta = document.createElement("div");
  meta.className = "card-meta";
  [
    String(item.mode || ""),
    `query: ${(item.query_tags || []).join(", ") || "전체"}`,
    `artist posts: ${item.artist_post_count} · matched: ${item.matched_post_count}`,
    String(item.created_at || ""),
  ].forEach((text) => {
    const line = document.createElement("span");
    line.textContent = text;
    meta.append(line);
  });

  const actions = document.createElement("div");
  actions.className = "card-actions";
  const searchLink = document.createElement("a");
  searchLink.className = "card-link";
  searchLink.dataset.action = "danbooru-search";
  searchLink.textContent = "Danbooru 검색";
  searchLink.href = buildDanbooruSearchUrl(item.artist_tag, item.query_tags);
  searchLink.setAttribute("href", searchLink.href);
  searchLink.target = "_blank";
  searchLink.rel = "noreferrer";
  searchLink.setAttribute("target", "_blank");
  searchLink.setAttribute("rel", "noreferrer");
  actions.append(searchLink);
  const viewSamples = document.createElement("button");
  viewSamples.type = "button";
  viewSamples.dataset.action = "view-samples";
  viewSamples.textContent = thumb ? "예제 그림 보기" : "예제 그림 조회";
  actions.append(viewSamples);
  [["copy", "프롬프트 복사"], ["edit", "수정"], ["delete", "삭제"]].forEach(([action, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = action;
    button.textContent = label;
    actions.append(button);
  });
  const findThumbnail = document.createElement("button");
  findThumbnail.type = "button";
  findThumbnail.dataset.action = "find-thumbnail";
  findThumbnail.textContent = thumb ? "WebP 썸네일 갱신" : "WebP 썸네일 받기";
  actions.append(findThumbnail);

  const editor = document.createElement("div");
  editor.className = "inline-edit hidden";
  const scoreSelect = document.createElement("select");
  scoreSelect.dataset.edit = "score";
  [1, 2, 3, 4, 5].forEach((value) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = String(value);
    option.selected = value === Number(item.score);
    scoreSelect.append(option);
  });
  const memoInput = document.createElement("textarea");
  memoInput.dataset.edit = "memo";
  memoInput.value = String(item.memo || "");
  const queryInput = document.createElement("textarea");
  queryInput.dataset.edit = "query-text";
  queryInput.setAttribute("aria-label", "쿼리 프롬프트");
  queryInput.placeholder = "비우면 전체 작가 수집으로 변경됩니다.";
  queryInput.value = String(item.query_text || (item.query_tags || []).join(", "));
  const apply = document.createElement("button");
  apply.type = "button";
  apply.dataset.action = "apply";
  apply.textContent = "적용";
  const queryLabel = document.createElement("span");
  queryLabel.className = "inline-edit-label";
  queryLabel.textContent = "쿼리 프롬프트";
  editor.append(scoreSelect, memoInput, queryLabel, queryInput, apply);
  body.append(heading, score, memoPreview, meta, actions, editor);
  card.append(body);

  card.querySelector('[data-action="open-samples"]')?.addEventListener("click", () => openRatingSampleViewer(item));
  card.querySelector('[data-action="view-samples"]')?.addEventListener("click", () => openRatingSampleViewer(item));
  card.querySelector('[data-action="copy"]').addEventListener("click", () => copyText(item.prompt_text));
  card.querySelector('[data-action="edit"]').addEventListener("click", () => card.querySelector(".inline-edit").classList.toggle("hidden"));
  card.querySelector('[data-action="delete"]').addEventListener("click", () => deleteRating(item.id));
  card.querySelector('[data-action="find-thumbnail"]')?.addEventListener("click", () => findRatingThumbnail(item.id));
  card.querySelector('[data-action="apply"]').addEventListener("click", () => {
    patchRating(item.id, {
      score: Number(card.querySelector('[data-edit="score"]').value),
      memo: card.querySelector('[data-edit="memo"]').value,
      query_text: card.querySelector('[data-edit="query-text"]').value,
    });
  });
  return card;
}

async function findRatingThumbnail(id) {
  showStatus($("ratingsStatus"), "고화질 WebP 썸네일을 준비하는 중입니다...");
  try {
    await apiFetch(`/api/ratings/${id}/thumbnail`, { method: "POST" });
    await loadRatings();
  } catch (error) {
    showStatus($("ratingsStatus"), error.message, "error");
  }
}

async function loadRatings() {
  showStatus($("ratingsStatus"), "평가 목록을 불러오는 중입니다...");
  try {
    const items = await apiFetch(`/api/ratings?${ratingParams()}`);
    const list = $("ratingsList");
    list.innerHTML = "";
    items.forEach((item) => list.appendChild(renderRatingCard(item)));
    showStatus($("ratingsStatus"), items.length ? `${items.length}개 평가` : "저장된 평가가 없습니다.", items.length ? "ok" : "");
  } catch (error) {
    showStatus($("ratingsStatus"), error.message, "error");
  }
}

async function patchRating(id, payload) {
  try {
    await apiFetch(`/api/ratings/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
    await loadRatings();
  } catch (error) {
    showStatus($("ratingsStatus"), error.message, "error");
  }
}

async function deleteRating(id) {
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "rating",
    title: "평가 기록 삭제",
    message: "선택한 작가의 평가 기록을 삭제할까요?",
    confirmLabel: "삭제",
    tone: "danger",
  })) return;
  try {
    await apiFetch(`/api/ratings/${id}`, { method: "DELETE" });
    await loadRatings();
  } catch (error) {
    showStatus($("ratingsStatus"), error.message, "error");
  }
}

if (typeof document !== "undefined" && !(typeof module !== "undefined" && module.exports)) {
void loadAppPreferences();
initializeHelpTooltips();
bindClick("appDialogCancel", () => closeAppDialog(null));
bindClick("appDialogConfirm", () => {
  const inputVisible = !$("appDialogInputField")?.classList.contains("hidden");
  closeAppDialog(inputVisible ? valueOf("appDialogInput") : true);
});
document.querySelectorAll("[data-app-dialog-cancel]").forEach((element) => {
  element.addEventListener("click", () => closeAppDialog(null));
});
$("appDialogInput")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    closeAppDialog(valueOf("appDialogInput"));
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("appDialog")?.classList.contains("hidden")) closeAppDialog(null);
});
document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab, .view").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    $(`${button.dataset.tab}-tab`).classList.add("active");
    if (button.dataset.tab === "ratings") loadRatings();
  });
});

document.querySelectorAll("#scoreButtons button").forEach((button) => {
  button.addEventListener("click", async () => {
    state.selectedScore = Number(button.dataset.score);
    document.querySelectorAll("#scoreButtons button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    await saveRating(true, state.selectedScore);
  });
});

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    state.activeFilter = button.dataset.filter;
    document.querySelectorAll(".filter").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    loadRatings();
  });
});

const queryText = $("queryText");
if (queryText) {
  queryText.addEventListener("input", () => {
    clearTimeout(window.autocompleteTimer);
    window.autocompleteTimer = setTimeout(updateAutocomplete, 250);
  });
  queryText.addEventListener("keydown", handleAutocompleteKeydown);
}
const excludeQueryText = $("excludeQueryText");
if (excludeQueryText) {
  excludeQueryText.addEventListener("input", () => {
    clearTimeout(window.excludeAutocompleteTimer);
    window.excludeAutocompleteTimer = setTimeout(() => updateAutocomplete("exclude"), 250);
  });
  excludeQueryText.addEventListener("keydown", (event) => handleAutocompleteKeydown(event, "exclude"));
}
syncCandidateCutoffDateControl();
$("candidateCutoffPreset")?.addEventListener("change", syncCandidateCutoffDateControl);
bindClick("candidateButton", async () => {
  const loaded = await loadCandidatePool(true);
  if (loaded) await showNextArtist();
}) || bindClick("pickButton", async () => {
  const loaded = await loadCandidatePool(true);
  if (loaded) await showNextArtist();
});
bindClick("nextArtist", showNextArtist);
bindClick("prevSample", () => moveSample(-1));
bindClick("nextSample", () => moveSample(1));
bindClick("copyPrompt", () => copyText(state.currentPick?.prompt_text));
bindClick("skipArtist", showNextArtist);
const ratingSearch = $("ratingSearch");
if (ratingSearch) {
  ratingSearch.addEventListener("input", () => {
    clearTimeout(window.ratingTimer);
    window.ratingTimer = setTimeout(loadRatings, 250);
  });
}
const ratingSort = $("ratingSort");
if (ratingSort) {
  ratingSort.addEventListener("change", loadRatings);
}
const manualArtist = $("manualArtist");
if (manualArtist) {
  manualArtist.addEventListener("input", () => {
    manualArtist.dataset.postCount = "0";
    clearTimeout(window.manualArtistTimer);
    window.manualArtistTimer = setTimeout(updateManualArtistAutocomplete, 250);
  });
  manualArtist.addEventListener("keydown", handleManualArtistKeydown);
}
bindClick("manualAddButton", addManualRating);
bindClick("manualPreviewButton", openManualPreview);
bindClick("manualPreviewPrev", () => moveManualPreview(-1));
bindClick("manualPreviewNext", () => moveManualPreview(1));
bindClick("manualPreviewLoadMore", loadMoreManualPreviewSamples);
bindClick("manualPreviewSetThumbnail", setRatingExampleThumbnail);
bindClick("manualPreviewDeleteExample", deleteRatingExample);
bindClick("manualPreviewClose", closeManualPreview);
document.querySelectorAll("[data-close-manual-preview]").forEach((element) => {
  element.addEventListener("click", closeManualPreview);
});
document.addEventListener("keydown", (event) => {
  const modal = $("manualPreviewModal");
  if (!modal || modal.classList.contains("hidden")) return;
  if (event.key === "Escape") closeManualPreview();
  if (event.key === "ArrowLeft") moveManualPreview(-1);
  if (event.key === "ArrowRight") moveManualPreview(1);
});
bindClick("closeConditions", () => {
  $("conditionPanel")?.classList.add("hidden");
  $("openConditions")?.classList.remove("hidden");
});
bindClick("openConditions", () => {
  $("conditionPanel")?.classList.remove("hidden");
  $("openConditions")?.classList.add("hidden");
});

updatePoolStatus();
loadRatings();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    renderRatingCard,
    validatedImageUrl,
    manualPreviewRatingFields,
    calculateTooltipPosition,
    buildDanbooruSearchUrl,
    buildDanbooruPostUrl,
    buildRatingRepresentativeSample,
    openRatingSampleViewer,
    loadMoreManualPreviewSamples,
    normalizeStoredRatingExample,
    combineRatingSamples,
    normalizePreviewSample,
    mergePreviewSamples,
  };
}
