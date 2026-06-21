const styleState = {
  artists: [],
  allowedScores: new Set([1, 2, 3, 4, 5]),
  customRanges: [],
  ratedArtists: [],
  initialized: false,
  draggingIndex: null,
  requestToken: 0,
  pending: false,
  generating: false,
  running: false,
  paused: false,
  stopRequested: false,
  completed: 0,
  managerDirty: true,
  managerImages: [],
  managerImageIndex: 0,
  promptGroups: [],
  weightProfile: [
    { position: 0, weight: 0.1 },
    { position: 1, weight: 2.3 },
  ],
};

const PROMPT_STORAGE_KEY = "naiArtistRater.prompts.v1";

const STYLE_REQUEST_CONTROL_IDS = [
  "rerollStyleArtists",
  "rerollStyleWeights",
  "rerollStyleAll",
  "sortStyleAsc",
  "sortStyleDesc",
  "styleArtistCount",
  "styleScoreAll",
  "weightMode",
  "styleMinWeight",
  "styleMaxWeight",
  "preferHighScores",
  "addWeightRange",
  "styleArtistSearch",
  "styleArtistSelect",
  "addStyleArtist",
];

const CUSTOM_RANGE_FIELDS = [
  { key: "min", label: "최소 가중치", ariaLabel: "최소 가중치", step: 0.01 },
  { key: "max", label: "최대 가중치", ariaLabel: "최대 가중치", step: 0.01 },
  { key: "max_people", label: "최대 인원", ariaLabel: "최대 인원", step: 1 },
];

function validateCustomRangeValues(ranges, { globalMin, globalMax, artistCount }) {
  let capacity = 0;
  const normalized = ranges.map((range, index) => {
    const min = Number(range.min);
    const max = Number(range.max);
    const maxPeople = Number(range.max_people);
    if (![min, max, maxPeople].every(Number.isFinite)) {
      throw new Error(`${index + 1}번 구간은 숫자로 입력하세요.`);
    }
    if (min <= 0 || max <= 0 || min > max) {
      throw new Error(`${index + 1}번 구간의 최소값과 최대값을 확인하세요.`);
    }
    if (min < globalMin || max > globalMax) {
      throw new Error(`${index + 1}번 구간은 전체 가중치 범위 안에 있어야 합니다.`);
    }
    if (!Number.isInteger(maxPeople) || maxPeople < 1) {
      throw new Error(`${index + 1}번 구간의 최대 인원은 1 이상의 정수여야 합니다.`);
    }
    capacity += maxPeople;
    return { min, max, max_people: maxPeople };
  });

  for (let left = 0; left < normalized.length; left += 1) {
    for (let right = left + 1; right < normalized.length; right += 1) {
      const leftMin = Math.round(normalized[left].min * 100);
      const leftMax = Math.round(normalized[left].max * 100);
      const rightMin = Math.round(normalized[right].min * 100);
      const rightMax = Math.round(normalized[right].max * 100);
      if (leftMin <= rightMax && rightMin <= leftMax) {
        throw new Error(`${left + 1}번과 ${right + 1}번 가중치 구간이 서로 겹칩니다.`);
      }
    }
  }

  if (capacity < artistCount) {
    throw new Error(`구간의 총 인원(${capacity})이 작가 수(${artistCount})보다 적습니다.`);
  }
  return normalized;
}

function normalizeSelectedScores(scores) {
  const normalized = Array.from(new Set(scores)).map(Number).sort((a, b) => a - b);
  if (normalized.length === 0) throw new Error("허용 평점을 하나 이상 선택하세요.");
  if (!normalized.every((score) => Number.isInteger(score) && score >= 1 && score <= 5)) {
    throw new Error("허용 평점은 1부터 5 사이의 정수여야 합니다.");
  }
  return normalized;
}

function buildStyleRequestPayload(options, artists, reroll) {
  const payload = { ...options, reroll };
  if (reroll !== "all") {
    payload.artists = artists.map(({ artist, score, weight }) => ({ artist, score, weight }));
  }
  return payload;
}

function applyStyleRerollResult(currentArtists, incomingArtists, reroll, preserveOrder = false) {
  if (reroll !== "all" || preserveOrder) return [...incomingArtists];
  return sortArtistsByWeight(incomingArtists, "asc");
}

function sortArtistsByWeight(artists, direction) {
  const factor = direction === "asc" ? 1 : -1;
  return [...artists].sort((a, b) => factor * (Number(a.weight) - Number(b.weight)));
}

function reorderArtists(artists, source, target) {
  if (!Number.isInteger(source) || !Number.isInteger(target) || !artists[source] || !artists[target]) {
    return [...artists];
  }
  const reordered = [...artists];
  const [moved] = reordered.splice(source, 1);
  reordered.splice(target, 0, moved);
  return reordered;
}

async function runLatestStyleRequest(requestState, request, handlers = {}) {
  const token = requestState.requestToken + 1;
  requestState.requestToken = token;
  requestState.pending = true;
  handlers.onPending?.(true);
  try {
    const result = await request();
    if (token !== requestState.requestToken) return false;
    handlers.onSuccess?.(result);
    return true;
  } catch (error) {
    if (token === requestState.requestToken) handlers.onError?.(error);
    return false;
  } finally {
    if (token === requestState.requestToken) {
      requestState.pending = false;
      handlers.onPending?.(false);
    }
  }
}

function styleElement(id) {
  return typeof document === "undefined" ? null : document.getElementById(id);
}

function styleNumber(id, fallback) {
  const value = Number(styleElement(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function clampStyleWeight(value) {
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);
  const numeric = Number(value);
  return Math.min(max, Math.max(min, Number.isFinite(numeric) ? numeric : min));
}

function formatStyleWeight(value) {
  return Number(value).toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function formatArtistPromptTag(artist) {
  const normalized = String(artist || "").replaceAll("_", " ");
  return /\d$/.test(normalized) ? `${normalized} ` : normalized;
}

function hasProfileDragMoved(startX, startY, currentX, currentY) {
  return Math.hypot(currentX - startX, currentY - startY) >= 3;
}

function parsePromptTokens(text) {
  return String(text || "")
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
}

function normalizePromptToken(token) {
  return String(token || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function promptGroupItemKey(item) {
  const field = item?.field === "negative" || item?.field === "character" ? item.field : "base";
  const characterId = field === "character" ? String(item?.character_id || "") : "";
  return `${field}:${characterId}:${normalizePromptToken(item?.token)}`;
}

function normalizePromptGroup(group, index = 0) {
  const items = Array.isArray(group?.items) ? group.items : [];
  const normalizedItems = [];
  const seen = new Set();
  items.forEach((item) => {
    const normalized = {
      field: item?.field === "negative" || item?.field === "character" ? item.field : "base",
      character_id: item?.field === "character" ? String(item.character_id || "") : "",
      token: String(item?.token || "").trim(),
    };
    const key = promptGroupItemKey(normalized);
    if (!normalized.token || seen.has(key)) return;
    seen.add(key);
    normalizedItems.push(normalized);
  });
  return {
    id: String(group?.id || `group-${index + 1}`),
    name: String(group?.name || `그룹 ${index + 1}`),
    enabled: group?.enabled !== false,
    expanded: group?.expanded !== false,
    items: normalizedItems,
  };
}

function promptStoragePayload(basePrompt, negativePrompt, characterPrompts, characterPromptIds = [], promptGroups = []) {
  const prompts = Array.isArray(characterPrompts)
    ? characterPrompts.map((value) => (typeof value === "string" ? value : ""))
    : [""];
  const ids = prompts.map((_, index) => String(characterPromptIds[index] || `character-${index + 1}`));
  return {
    base_prompt: typeof basePrompt === "string" ? basePrompt : "",
    negative_prompt: typeof negativePrompt === "string" ? negativePrompt : "",
    character_prompts: prompts,
    character_prompt_ids: ids,
    prompt_groups: Array.isArray(promptGroups) ? promptGroups.map(normalizePromptGroup) : [],
  };
}

function normalizeStoredPrompts(value) {
  if (!value || typeof value !== "object") return promptStoragePayload("", "", [""]);
  const characters = Array.isArray(value.character_prompts)
    ? value.character_prompts.filter((item) => typeof item === "string")
    : [""];
  return promptStoragePayload(
    typeof value.base_prompt === "string" ? value.base_prompt : "",
    typeof value.negative_prompt === "string" ? value.negative_prompt : "",
    characters.length ? characters : [""],
    Array.isArray(value.character_prompt_ids) ? value.character_prompt_ids : [],
    Array.isArray(value.prompt_groups) ? value.prompt_groups : [],
  );
}

function addPromptGroupItem(group, item) {
  if (!group || !String(item?.token || "").trim()) return false;
  group.items = Array.isArray(group.items) ? group.items : [];
  const normalized = normalizePromptGroup({ items: [item] }).items[0];
  if (!normalized) return false;
  const key = promptGroupItemKey(normalized);
  if (group.items.some((existing) => promptGroupItemKey(existing) === key)) return false;
  group.items.push(normalized);
  return true;
}

function availablePromptItemKeys(prompts) {
  const keys = new Set();
  parsePromptTokens(prompts?.base_prompt).forEach((token) => keys.add(promptGroupItemKey({ field: "base", token })));
  parsePromptTokens(prompts?.negative_prompt).forEach((token) => keys.add(promptGroupItemKey({ field: "negative", token })));
  (prompts?.character_prompts || []).forEach((text, index) => {
    const characterId = String(prompts?.character_prompt_ids?.[index] || `character-${index + 1}`);
    parsePromptTokens(text).forEach((token) => keys.add(promptGroupItemKey({ field: "character", character_id: characterId, token })));
  });
  return keys;
}

function cleanPromptGroups(groups, prompts) {
  const available = availablePromptItemKeys(prompts);
  return (Array.isArray(groups) ? groups : []).map((group, index) => {
    const normalized = normalizePromptGroup(group, index);
    normalized.items = normalized.items.filter((item) => available.has(promptGroupItemKey(item)));
    return normalized;
  });
}

function buildEffectivePromptText(text, field, characterId, groups) {
  const disabled = new Set();
  (Array.isArray(groups) ? groups : []).forEach((group) => {
    if (group?.enabled !== false) return;
    (group.items || []).forEach((item) => disabled.add(promptGroupItemKey(item)));
  });
  return parsePromptTokens(text)
    .filter((token) => !disabled.has(promptGroupItemKey({ field, character_id: characterId, token })))
    .join(", ");
}

function savePromptDraft() {
  if (typeof localStorage === "undefined") return;
  const rows = typeof document === "undefined" ? [] : [...document.querySelectorAll("#characterPromptList .character-prompt-row")];
  const characters = rows.map((row) => row.querySelector("textarea")?.value || "");
  const characterIds = rows.map((row, index) => row.dataset.characterId || `character-${index + 1}`);
  const draft = {
    base_prompt: styleElement("basePrompt")?.value || "",
    negative_prompt: styleElement("negativePrompt")?.value || "",
    character_prompts: characters,
    character_prompt_ids: characterIds,
  };
  styleState.promptGroups = cleanPromptGroups(styleState.promptGroups, draft);
  const payload = promptStoragePayload(
    draft.base_prompt,
    draft.negative_prompt,
    characters,
    characterIds,
    styleState.promptGroups,
  );
  try { localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(payload)); } catch (_) { /* Storage can be disabled. */ }
}

function loadPromptDraft() {
  if (typeof localStorage === "undefined") return normalizeStoredPrompts(null);
  try { return normalizeStoredPrompts(JSON.parse(localStorage.getItem(PROMPT_STORAGE_KEY) || "null")); }
  catch (_) { return normalizeStoredPrompts(null); }
}

function isPromptItemDisabled(item) {
  const key = promptGroupItemKey(item);
  return styleState.promptGroups.some((group) => (
    group.enabled === false && group.items.some((candidate) => promptGroupItemKey(candidate) === key)
  ));
}

function setPromptDragData(event, item) {
  event.dataTransfer.effectAllowed = "copy";
  event.dataTransfer.setData("application/x-style-prompt-token", JSON.stringify(item));
  event.dataTransfer.setData("text/plain", item.token);
}

function renderPromptTokens(surface, text, field, characterId = "") {
  if (!surface) return;
  surface.replaceChildren();
  const tokens = parsePromptTokens(text);
  if (!tokens.length) {
    const empty = document.createElement("span");
    empty.className = "prompt-token-empty";
    empty.textContent = "쉼표로 태그를 나누면 여기에 토큰이 표시됩니다.";
    surface.append(empty);
    return;
  }
  tokens.forEach((token) => {
    const item = { field, character_id: field === "character" ? characterId : "", token };
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `prompt-token-chip ${field}${isPromptItemDisabled(item) ? " disabled-by-group" : ""}`;
    chip.draggable = true;
    chip.textContent = token;
    chip.title = "그룹으로 드래그";
    chip.addEventListener("dragstart", (event) => setPromptDragData(event, item));
    surface.append(chip);
  });
}

function renderAllPromptTokens() {
  renderPromptTokens(styleElement("basePromptTokens"), styleElement("basePrompt")?.value, "base");
  renderPromptTokens(styleElement("negativePromptTokens"), styleElement("negativePrompt")?.value, "negative");
  document.querySelectorAll("#characterPromptList .character-prompt-row").forEach((row) => {
    renderPromptTokens(
      row.querySelector(".prompt-token-surface"),
      row.querySelector("textarea")?.value,
      "character",
      row.dataset.characterId,
    );
  });
}

function persistAndRenderPromptControls() {
  savePromptDraft();
  renderAllPromptTokens();
  renderPromptGroups();
}

function selectPromptTab(tabName) {
  const selected = tabName === "negative" ? "negative" : "base";
  document.querySelectorAll("[data-prompt-tab]").forEach((button) => {
    const active = button.dataset.promptTab === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  styleElement("basePromptPanel")?.classList.toggle("hidden", selected !== "base");
  styleElement("negativePromptPanel")?.classList.toggle("hidden", selected !== "negative");
}

function addPromptGroup() {
  styleState.promptGroups.push({
    id: createRequestId(),
    name: `그룹 ${styleState.promptGroups.length + 1}`,
    enabled: true,
    expanded: true,
    items: [],
  });
  persistAndRenderPromptControls();
}

function fieldLabelForPromptItem(item) {
  if (item.field === "negative") return "NEG";
  if (item.field === "character") return "CHAR";
  return "BASE";
}

function renderPromptGroups() {
  const list = styleElement("promptGroupList");
  if (!list) return;
  list.replaceChildren();
  if (!styleState.promptGroups.length) {
    const empty = document.createElement("p");
    empty.className = "prompt-group-empty";
    empty.textContent = "그룹을 추가한 뒤 위 토큰을 끌어다 놓으세요.";
    list.append(empty);
    return;
  }
  styleState.promptGroups.forEach((group) => {
    const wrapper = document.createElement("section");
    wrapper.className = `prompt-control-group${group.enabled ? "" : " off"}${group.expanded ? " expanded" : ""}`;

    const header = document.createElement("div");
    header.className = "prompt-control-group-header";
    const name = document.createElement("strong");
    name.className = "prompt-control-group-name";
    name.textContent = group.name;
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "icon-button small";
    rename.title = "그룹 이름 변경";
    rename.textContent = "✎";
    rename.addEventListener("click", () => {
      const next = prompt("그룹 이름", group.name);
      if (!next?.trim()) return;
      group.name = next.trim();
      persistAndRenderPromptControls();
    });
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = `prompt-group-toggle${group.enabled ? " on" : ""}`;
    toggle.textContent = group.enabled ? "ON" : "OFF";
    toggle.title = "생성 프롬프트 포함 여부";
    toggle.addEventListener("click", () => {
      group.enabled = !group.enabled;
      persistAndRenderPromptControls();
    });
    const expand = document.createElement("button");
    expand.type = "button";
    expand.className = "icon-button small";
    expand.title = group.expanded ? "그룹 접기" : "그룹 펼치기";
    expand.textContent = group.expanded ? "▴" : "▾";
    expand.addEventListener("click", () => {
      group.expanded = !group.expanded;
      persistAndRenderPromptControls();
    });
    const removeGroup = document.createElement("button");
    removeGroup.type = "button";
    removeGroup.className = "icon-button small danger-button";
    removeGroup.title = "그룹 삭제";
    removeGroup.textContent = "×";
    removeGroup.addEventListener("click", () => {
      styleState.promptGroups = styleState.promptGroups.filter((candidate) => candidate.id !== group.id);
      persistAndRenderPromptControls();
    });
    header.append(name, rename, toggle, expand, removeGroup);

    const dropZone = document.createElement("div");
    dropZone.className = "prompt-group-drop-zone";
    dropZone.addEventListener("dragover", (event) => {
      if (![...event.dataTransfer.types].includes("application/x-style-prompt-token")) return;
      event.preventDefault();
      dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("drag-over");
      try {
        const item = JSON.parse(event.dataTransfer.getData("application/x-style-prompt-token"));
        if (addPromptGroupItem(group, item)) persistAndRenderPromptControls();
      } catch (_) { /* Ignore invalid external drag data. */ }
    });
    if (!group.items.length) {
      const empty = document.createElement("span");
      empty.className = "prompt-group-empty";
      empty.textContent = "토큰을 여기에 놓기";
      dropZone.append(empty);
    } else {
      group.items.forEach((item, itemIndex) => {
        const chip = document.createElement("span");
        chip.className = `prompt-group-item ${item.field}`;
        const label = document.createElement("span");
        label.textContent = `${fieldLabelForPromptItem(item)} · ${item.token}`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.title = "그룹에서 제거";
        remove.textContent = "×";
        remove.addEventListener("click", () => {
          group.items.splice(itemIndex, 1);
          persistAndRenderPromptControls();
        });
        chip.append(label, remove);
        dropZone.append(chip);
      });
    }
    wrapper.append(header, dropZone);
    list.append(wrapper);
  });
}

function interpolateWeightProfile(profile, position) {
  const points = [...profile].sort((a, b) => a.position - b.position);
  for (let index = 0; index < points.length - 1; index += 1) {
    const left = points[index];
    const right = points[index + 1];
    if (position <= right.position) {
      const ratio = (position - left.position) / (right.position - left.position);
      return Number((left.weight + ((right.weight - left.weight) * ratio)).toFixed(4));
    }
  }
  return points.at(-1)?.weight ?? 0;
}

function showStyleStatus(message, type = "") {
  const target = styleElement("styleMakerStatus");
  if (!target) return;
  target.textContent = message || "";
  target.className = `status ${type}`;
}

function showStyleError(message = "") {
  const target = styleElement("styleSettingsError");
  if (!target) return;
  target.textContent = message;
  target.className = `status ${message ? "error" : ""}`;
}

function setStyleRequestPending(pending) {
  styleState.pending = pending;
  STYLE_REQUEST_CONTROL_IDS.forEach((id) => {
    const control = styleElement(id);
    if (control) control.disabled = pending;
  });
  if (typeof document === "undefined") return;
  document.querySelectorAll("#styleScoreButtons [data-score], #customRangeList input, #customRangeList button, #weightGraph input, #weightGraph select, #weightGraph button")
    .forEach((control) => { control.disabled = pending; });
  document.querySelectorAll("#weightGraph .weight-column")
    .forEach((column) => { column.draggable = !pending; });
}

function validateCustomRanges() {
  if (styleElement("weightMode")?.value !== "custom" || styleState.customRanges.length === 0) {
    showStyleError();
    return [];
  }

  const globalMin = styleNumber("styleMinWeight", 0.1);
  const globalMax = styleNumber("styleMaxWeight", 2.3);
  const artistCount = Math.max(1, Math.trunc(styleNumber("styleArtistCount", 12)));
  const ranges = validateCustomRangeValues(styleState.customRanges, { globalMin, globalMax, artistCount });
  showStyleError();
  return ranges;
}

function readStyleOptions() {
  const count = Number(styleElement("styleArtistCount")?.value);
  const minWeight = Number(styleElement("styleMinWeight")?.value);
  const maxWeight = Number(styleElement("styleMaxWeight")?.value);
  if (!Number.isInteger(count) || count < 1) throw new Error("작가 수는 1 이상의 정수여야 합니다.");
  if (![minWeight, maxWeight].every(Number.isFinite) || minWeight <= 0 || minWeight > maxWeight) {
    throw new Error("전체 가중치 범위를 확인하세요.");
  }

  const mode = styleElement("weightMode")?.value || "balanced";
  return {
    count,
    scores: normalizeSelectedScores(styleState.allowedScores),
    weight_mode: mode,
    min_weight: minWeight,
    max_weight: maxWeight,
    prefer_high_scores: Boolean(styleElement("preferHighScores")?.checked),
    ranges: validateCustomRanges(),
    weight_profile: mode === "profile" ? styleState.weightProfile : undefined,
  };
}

async function loadStyleArtists(reroll = "all") {
  let payload;
  try {
    showStyleStatus("그림체를 구성하는 중입니다...");
    payload = buildStyleRequestPayload(readStyleOptions(), styleState.artists, reroll);
  } catch (error) {
    showStyleError(error.message);
    showStyleStatus(error.message, "error");
    return false;
  }

  return runLatestStyleRequest(styleState, () => apiFetch("/api/style-maker/artists", {
      method: "POST",
      body: JSON.stringify(payload),
    }), {
      onPending: setStyleRequestPending,
      onSuccess: (data) => {
        const preserveOrder = styleElement("weightMode")?.value === "profile";
        styleState.artists = applyStyleRerollResult(styleState.artists, data.artists || [], reroll, preserveOrder);
        renderWeightGraph();
        showStyleStatus(`${styleState.artists.length}명의 작가를 불러왔습니다.`, "ok");
      },
      onError: (error) => {
        showStyleError(error.message);
        showStyleStatus(error.message, "error");
      },
    });
}

function updateArtistPrompt() {
  const preview = styleElement("artistPromptPreview");
  if (!preview) return;
  preview.value = styleState.artists
    .map((item) => `${formatStyleWeight(item.weight)}::artist:${formatArtistPromptTag(item.artist)}::`)
    .join(", ");
}

function renderWeightProfilePreview() {
  const preview = styleElement("weightGraphPreview");
  if (!preview) return;
  const ns = "http://www.w3.org/2000/svg";
  preview.replaceChildren();
  for (let index = 1; index < 4; index += 1) {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", "8");
    line.setAttribute("x2", "232");
    line.setAttribute("y1", String(index * 25));
    line.setAttribute("y2", String(index * 25));
    line.classList.add("preview-grid-line");
    preview.append(line);
  }
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);
  const points = styleState.weightProfile.map((point) => {
    const x = 8 + point.position * 224;
    const y = 8 + ((max - point.weight) / Math.max(0.01, max - min)) * 84;
    return `${x},${y}`;
  });
  const polyline = document.createElementNS(ns, "polyline");
  polyline.setAttribute("points", points.join(" "));
  polyline.classList.add("preview-profile-line");
  preview.append(polyline);
}

function openWeightGraphModal() {
  const mode = styleElement("weightMode");
  if (mode) mode.value = "profile";
  styleElement("weightGraphModal")?.classList.remove("hidden");
  renderWeightGraph();
}

function closeWeightGraphModal() {
  styleElement("weightGraphModal")?.classList.add("hidden");
}

function renderWeightProfileGraph(graph) {
  const ns = "http://www.w3.org/2000/svg";
  const width = 900;
  const height = 430;
  const pad = { left: 58, right: 24, top: 24, bottom: 44 };
  const plotWidth = width - pad.left - pad.right;
  const plotHeight = height - pad.top - pad.bottom;
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);
  styleState.weightProfile = styleState.weightProfile.map((point) => ({
    position: point.position,
    weight: Math.min(max, Math.max(min, point.weight)),
  }));
  const x = (position) => pad.left + (position * plotWidth);
  const y = (weight) => pad.top + ((max - weight) / Math.max(0.01, max - min)) * plotHeight;
  const svg = document.createElementNS(ns, "svg");
  svg.classList.add("weight-profile-svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("aria-label", "자리 순서별 가중치 그래프");

  for (let index = 0; index <= 10; index += 1) {
    const line = document.createElementNS(ns, "line");
    const lineY = pad.top + (plotHeight * index / 10);
    line.setAttribute("x1", pad.left);
    line.setAttribute("x2", width - pad.right);
    line.setAttribute("y1", lineY);
    line.setAttribute("y2", lineY);
    line.classList.add("profile-grid-line");
    svg.append(line);
    if (index % 2 === 0) {
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", pad.left - 10);
      label.setAttribute("y", lineY + 4);
      label.setAttribute("text-anchor", "end");
      label.classList.add("profile-axis-label");
      label.textContent = (max - ((max - min) * index / 10)).toFixed(1);
      svg.append(label);
    }
  }
  const count = Math.max(2, Math.trunc(styleNumber("styleArtistCount", 12)));
  for (let index = 0; index < count; index += 1) {
    const line = document.createElementNS(ns, "line");
    const lineX = x(index / (count - 1));
    line.setAttribute("x1", lineX);
    line.setAttribute("x2", lineX);
    line.setAttribute("y1", pad.top);
    line.setAttribute("y2", height - pad.bottom);
    line.classList.add("profile-grid-line", "profile-slot-line");
    svg.append(line);
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", lineX);
    label.setAttribute("y", height - 17);
    label.setAttribute("text-anchor", "middle");
    label.classList.add("profile-axis-label");
    label.textContent = String(index + 1);
    svg.append(label);
  }
  const polyline = document.createElementNS(ns, "polyline");
  polyline.setAttribute("points", styleState.weightProfile.map((point) => `${x(point.position)},${y(point.weight)}`).join(" "));
  polyline.classList.add("profile-line");
  svg.append(polyline);

  const pointFromEvent = (event) => {
    const rect = svg.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * width;
    const svgY = ((event.clientY - rect.top) / rect.height) * height;
    return {
      position: Math.min(0.99, Math.max(0.01, (svgX - pad.left) / plotWidth)),
      weight: Math.min(max, Math.max(min, max - ((svgY - pad.top) / plotHeight) * (max - min))),
    };
  };
  styleState.weightProfile.forEach((point) => {
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", x(point.position));
    circle.setAttribute("cy", y(point.weight));
    circle.setAttribute("r", 8);
    circle.classList.add("profile-point");
    circle.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      circle.setPointerCapture(event.pointerId);
      const startX = event.clientX;
      const startY = event.clientY;
      let moved = false;
      const move = (moveEvent) => {
        if (!hasProfileDragMoved(startX, startY, moveEvent.clientX, moveEvent.clientY)) return;
        moved = true;
        const next = pointFromEvent(moveEvent);
        if (point.position !== 0 && point.position !== 1) point.position = Number(next.position.toFixed(3));
        point.weight = Number(next.weight.toFixed(2));
        styleState.weightProfile.sort((a, b) => a.position - b.position);
        circle.setAttribute("cx", x(point.position));
        circle.setAttribute("cy", y(point.weight));
        polyline.setAttribute("points", styleState.weightProfile.map((item) => `${x(item.position)},${y(item.weight)}`).join(" "));
      };
      circle.addEventListener("pointermove", move);
      circle.addEventListener("pointerup", () => {
        circle.removeEventListener("pointermove", move);
        if (moved) renderWeightGraph();
      }, { once: true });
    });
    circle.addEventListener("dblclick", (event) => {
      event.stopPropagation();
      if (point.position === 0 || point.position === 1) return;
      styleState.weightProfile = styleState.weightProfile.filter((item) => item !== point);
      renderWeightGraph();
    });
    svg.append(circle);
  });
  svg.addEventListener("click", (event) => {
    if (event.target !== svg && !event.target.classList.contains("profile-grid-line") && event.target !== polyline) return;
    const point = pointFromEvent(event);
    styleState.weightProfile.push({ position: Number(point.position.toFixed(3)), weight: Number(point.weight.toFixed(2)) });
    styleState.weightProfile.sort((a, b) => a.position - b.position);
    renderWeightGraph();
  });
  const hint = document.createElement("p");
  hint.className = "profile-hint";
  hint.textContent = "가로는 자리 순서, 세로는 가중치입니다. 클릭해 점을 추가하고 끌어서 흐름을 만드세요. 점을 두 번 누르면 삭제됩니다.";
  graph.append(svg, hint);
}

function removeStyleArtist(index) {
  styleState.artists.splice(index, 1);
  const count = styleElement("styleArtistCount");
  if (count) count.value = String(Math.max(1, styleState.artists.length));
  renderWeightGraph();
  renderRatedArtistSelect();
}

function swapStyleArtists(a, b) {
  if (a === b || !styleState.artists[a] || !styleState.artists[b]) return;
  [styleState.artists[a], styleState.artists[b]] = [styleState.artists[b], styleState.artists[a]];
  renderWeightGraph();
}

function sortStyleArtists(direction) {
  styleState.artists = sortArtistsByWeight(styleState.artists, direction);
  renderWeightGraph();
}

function renderWeightGraph() {
  const graph = styleElement("weightGraph");
  if (!graph) return;
  graph.replaceChildren();
  const profileMode = styleElement("weightMode")?.value === "profile";
  graph.classList.toggle("profile-mode", profileMode);
  if (profileMode) {
    renderWeightProfileGraph(graph);
    renderWeightProfilePreview();
    updateArtistPrompt();
    return;
  }
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);

  styleState.artists.forEach((item, index) => {
    item.weight = clampStyleWeight(item.weight);
    const column = document.createElement("article");
    column.className = "weight-column";
    column.draggable = !styleState.pending;
    column.dataset.index = String(index);

    const drag = document.createElement("span");
    drag.className = "drag-handle icon-button ghost";
    drag.title = "끌어서 순서 변경";
    drag.setAttribute("aria-hidden", "true");
    drag.textContent = "⋮⋮";

    const slider = document.createElement("input");
    slider.className = "vertical-weight";
    slider.type = "range";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = "0.01";
    slider.value = String(item.weight);
    slider.setAttribute("aria-label", `${item.artist} 가중치`);

    const number = document.createElement("input");
    number.className = "weight-number";
    number.type = "number";
    number.min = String(min);
    number.max = String(max);
    number.step = "0.01";
    number.value = Number(item.weight).toFixed(2);
    number.setAttribute("aria-label", `${item.artist} 정확한 가중치`);

    const syncWeight = (value) => {
      item.weight = clampStyleWeight(value);
      slider.value = String(item.weight);
      number.value = Number(item.weight).toFixed(2);
      updateArtistPrompt();
    };
    slider.addEventListener("input", () => syncWeight(slider.value));
    number.addEventListener("change", () => syncWeight(number.value));

    const label = document.createElement("strong");
    label.className = "weight-artist-label";
    label.title = item.artist;
    label.textContent = item.artist;

    const score = document.createElement("span");
    score.className = "weight-score";
    score.textContent = `평점 ${item.score}`;

    const swap = document.createElement("select");
    swap.className = "weight-swap";
    swap.title = "다른 작가와 위치 바꾸기";
    swap.setAttribute("aria-label", `${item.artist} 위치 바꾸기`);
    swap.add(new Option("교체", ""));
    styleState.artists.forEach((other, otherIndex) => {
      if (otherIndex !== index) swap.add(new Option(String(otherIndex + 1), String(otherIndex)));
    });
    swap.addEventListener("change", () => swapStyleArtists(index, Number(swap.value)));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button danger-button";
    remove.title = "작가 삭제";
    remove.setAttribute("aria-label", `${item.artist} 삭제`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeStyleArtist(index));

    column.addEventListener("dragstart", (event) => {
      if (styleState.pending) {
        event.preventDefault();
        return;
      }
      styleState.draggingIndex = index;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
      column.classList.add("dragging");
    });
    column.addEventListener("dragend", () => {
      styleState.draggingIndex = null;
      column.classList.remove("dragging");
    });
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });
    column.addEventListener("drop", (event) => {
      event.preventDefault();
      if (styleState.pending) return;
      const source = Number(event.dataTransfer.getData("text/plain"));
      if (!Number.isInteger(source) || source === index) return;
      styleState.artists = reorderArtists(styleState.artists, source, index);
      renderWeightGraph();
    });

    column.append(drag, slider, number, label, score, swap, remove);
    graph.append(column);
  });
  updateArtistPrompt();
}

function filteredRatedArtists() {
  const query = (styleElement("styleArtistSearch")?.value || "").trim().toLowerCase();
  return styleState.ratedArtists.filter((item) => !query || item.artist.toLowerCase().includes(query));
}

function renderRatedArtistSelect() {
  const select = styleElement("styleArtistSelect");
  if (!select) return;
  const selectedArtists = new Set(styleState.artists.map((item) => item.artist));
  const options = filteredRatedArtists().filter((item) => !selectedArtists.has(item.artist));
  select.replaceChildren();
  if (!options.length) {
    select.add(new Option("추가할 작가가 없습니다", ""));
    return;
  }
  options.forEach((item) => select.add(new Option(`${item.artist} (평점 ${item.score})`, item.artist)));
}

function addStyleArtist() {
  const artist = styleElement("styleArtistSelect")?.value;
  const rated = styleState.ratedArtists.find((item) => item.artist === artist);
  if (!rated || styleState.artists.some((item) => item.artist === artist)) return;
  styleState.artists.push({ artist: rated.artist, score: rated.score, weight: clampStyleWeight(1) });
  styleElement("styleArtistCount").value = String(styleState.artists.length);
  renderWeightGraph();
  renderRatedArtistSelect();
}

async function loadRatedStyleArtists() {
  try {
    const ratings = await apiFetch("/api/ratings?sort=artist");
    styleState.ratedArtists = ratings.map((item) => ({ artist: item.artist_tag, score: Number(item.score) }));
    renderRatedArtistSelect();
  } catch (error) {
    showStyleStatus(error.message, "error");
  }
}

function renderCustomRanges() {
  const list = styleElement("customRangeList");
  if (!list) return;
  list.replaceChildren();
  styleState.customRanges.forEach((range, index) => {
    const row = document.createElement("div");
    row.className = "custom-range-row";
    CUSTOM_RANGE_FIELDS.forEach(({ key, label, ariaLabel, step }) => {
      const field = document.createElement("label");
      field.className = "custom-range-field";
      const fieldLabel = document.createElement("span");
      fieldLabel.textContent = label;
      const input = document.createElement("input");
      input.type = "number";
      input.step = String(step);
      input.min = key === "max_people" ? "1" : "0.01";
      input.value = String(range[key]);
      input.setAttribute("aria-label", `${index + 1}번 구간 ${ariaLabel}`);
      input.addEventListener("input", () => {
        range[key] = Number(input.value);
        try { validateCustomRanges(); } catch (error) { showStyleError(error.message); }
      });
      field.append(fieldLabel, input);
      row.append(field);
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button danger-button";
    remove.title = "가중치 구간 삭제";
    remove.setAttribute("aria-label", `${index + 1}번 가중치 구간 삭제`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      styleState.customRanges.splice(index, 1);
      renderCustomRanges();
    });
    row.append(remove);
    list.append(row);
  });
}

function addWeightRange() {
  styleState.customRanges.push({ min: 0.1, max: 0.9, max_people: 1 });
  renderCustomRanges();
}

function addCharacterPrompt(value = "", characterId = createRequestId()) {
  const list = styleElement("characterPromptList");
  if (!list) return;
  const row = document.createElement("div");
  row.className = "character-prompt-row";
  row.dataset.characterId = characterId;
  const editor = document.createElement("label");
  editor.className = "field prompt-editor character";
  const input = document.createElement("textarea");
  input.placeholder = "캐릭터 프롬프트";
  input.value = value;
  const tokens = document.createElement("div");
  tokens.className = "prompt-token-surface";
  tokens.dataset.promptField = "character";
  tokens.setAttribute("aria-label", "캐릭터 프롬프트 토큰");
  input.addEventListener("input", persistAndRenderPromptControls);
  editor.append(input, tokens);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "icon-button danger-button";
  remove.title = "캐릭터 프롬프트 삭제";
  remove.setAttribute("aria-label", "캐릭터 프롬프트 삭제");
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    row.remove();
    if (!styleElement("characterPromptList")?.children.length) addCharacterPrompt();
    persistAndRenderPromptControls();
  });
  row.append(editor, remove);
  list.append(row);
  renderPromptTokens(tokens, value, "character", characterId);
}

function createRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `style-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function generationNumber(id, fallback) {
  const value = Number(styleElement(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function readCharacterPrompts() {
  if (typeof document === "undefined") return [];
  return [...document.querySelectorAll("#characterPromptList .character-prompt-row")]
    .map((row) => buildEffectivePromptText(
      row.querySelector("textarea")?.value,
      "character",
      row.dataset.characterId,
      styleState.promptGroups,
    ))
    .filter(Boolean);
}

function buildGenerationRequest(requestId = createRequestId()) {
  if (!styleState.artists.length) throw new Error("먼저 그림체 작가를 구성하세요.");
  const width = generationNumber("generationWidth", 832);
  const height = generationNumber("generationHeight", 1216);
  const steps = generationNumber("generationSteps", 28);
  const scale = generationNumber("generationScale", 5);
  const cfgRescale = generationNumber("generationCfgRescale", 0);
  if (![width, height].every((value) => Number.isInteger(value) && value > 0 && value % 64 === 0)) {
    throw new Error("너비와 높이는 64 단위의 양수여야 합니다.");
  }
  if (!Number.isInteger(steps) || steps < 1 || steps > 50) throw new Error("스텝은 1~50이어야 합니다.");
  if (scale < 0 || scale > 10 || cfgRescale < 0 || cfgRescale > 1) throw new Error("생성 수치 범위를 확인하세요.");
  const seedFixed = Boolean(styleElement("generationSeedFixed")?.checked);
  const seed = Number(styleElement("generationSeed")?.value);
  if (seedFixed && (!Number.isInteger(seed) || seed < 1 || seed > 4294967295)) throw new Error("고정 시드를 확인하세요.");
  const payload = {
    request_id: requestId,
    artists: styleState.artists.map(({ artist, score, weight }) => ({ artist, score, weight })),
    base_prompt: buildEffectivePromptText(styleElement("basePrompt")?.value, "base", "", styleState.promptGroups),
    negative_prompt: buildEffectivePromptText(styleElement("negativePrompt")?.value, "negative", "", styleState.promptGroups),
    character_prompts: readCharacterPrompts(),
    width,
    height,
    sampler: styleElement("generationSampler")?.value || "k_euler_ancestral",
    noise_schedule: styleElement("generationScheduler")?.value || "native",
    steps,
    scale,
    cfg_rescale: cfgRescale,
  };
  if (seedFixed) payload.seed = seed;
  return payload;
}

function setGenerationBusy(busy) {
  styleState.generating = busy;
  ["generateOne", "startContinuous"].forEach((id) => {
    const button = styleElement(id);
    if (button) button.disabled = busy || styleState.running;
  });
}

function renderGenerationResult(result) {
  const target = styleElement("latestStyleResult");
  if (!target) return;
  target.replaceChildren();
  const image = document.createElement("img");
  image.src = result.image_url;
  image.alt = `그림체 ${result.style_id} 생성 결과`;
  const meta = document.createElement("div");
  meta.className = "latest-result-meta";
  meta.textContent = `그림체 #${result.style_id} · ${result.width}×${result.height} · ${result.sampler} / ${result.noise_schedule} · ${result.steps} steps · Scale ${result.scale} · CFG Rescale ${result.cfg_rescale} · Seed ${result.seed}`;
  target.append(image, meta);
}

async function generateCurrentStyle() {
  if (styleState.generating) throw new Error("이미 생성 중입니다.");
  let payload;
  try {
    payload = buildGenerationRequest();
  } catch (error) {
    showStyleStatus(error.message, "error");
    throw error;
  }
  setGenerationBusy(true);
  showStyleStatus("NovelAI에서 이미지를 생성하는 중입니다...");
  try {
    const result = await apiFetch("/api/style-maker/generate", { method: "POST", body: JSON.stringify(payload) });
    renderGenerationResult(result);
    styleState.managerDirty = true;
    showStyleStatus("이미지를 생성하고 자동 저장했습니다.", "ok");
    return result;
  } catch (error) {
    showStyleStatus(error.message, "error");
    throw error;
  } finally {
    setGenerationBusy(false);
  }
}

function reachedGenerationLimit() {
  if (styleElement("generationLimitMode")?.value === "unlimited") return false;
  return styleState.completed >= Math.max(1, Math.trunc(generationNumber("generationCount", 1)));
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function renderQueueState() {
  const status = styleElement("generationStatus");
  const pause = styleElement("pauseContinuous");
  const stop = styleElement("stopContinuous");
  if (status) status.textContent = styleState.running
    ? `${styleState.completed}장 완료${styleState.paused ? " · 일시정지" : ""}`
    : styleState.completed ? `${styleState.completed}장 생성 완료` : "";
  if (pause) {
    pause.disabled = !styleState.running;
    pause.textContent = styleState.paused ? "계속" : "일시정지";
  }
  if (stop) stop.disabled = !styleState.running;
  const start = styleElement("startContinuous");
  if (start) start.disabled = styleState.running || styleState.generating;
}

async function runContinuousGeneration() {
  if (styleState.running || styleState.generating) return;
  styleState.running = true;
  styleState.paused = false;
  styleState.stopRequested = false;
  styleState.completed = 0;
  renderQueueState();
  try {
    while (!styleState.stopRequested && !reachedGenerationLimit()) {
      while (styleState.paused && !styleState.stopRequested) await wait(150);
      if (styleState.stopRequested) break;
      const changeMode = styleElement("styleChangeMode")?.value || "weights";
      const rerolled = await loadStyleArtists(changeMode === "artists_and_weights" ? "all" : "weights");
      if (!rerolled) throw new Error("그림체를 다시 구성하지 못했습니다.");
      await generateCurrentStyle();
      styleState.completed += 1;
      renderQueueState();
    }
  } catch (error) {
    styleState.paused = true;
    showStyleStatus(error.message, "error");
  } finally {
    styleState.running = false;
    renderQueueState();
  }
}

async function openSettingsModal() {
  styleElement("settingsModal")?.classList.remove("hidden");
  const status = styleElement("novelAiSettingsStatus");
  try {
    const data = await apiFetch("/api/settings/novelai");
    if (status) status.textContent = data.configured ? "저장된 키가 있습니다." : "저장된 키가 없습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function closeSettingsModal() {
  styleElement("settingsModal")?.classList.add("hidden");
  const input = styleElement("novelAiAppKey");
  if (input) input.value = "";
}

async function saveNovelAiKey() {
  const key = styleElement("novelAiAppKey")?.value || "";
  const status = styleElement("novelAiSettingsStatus");
  try {
    await apiFetch("/api/settings/novelai", { method: "PUT", body: JSON.stringify({ app_key: key }) });
    if (styleElement("novelAiAppKey")) styleElement("novelAiAppKey").value = "";
    if (status) status.textContent = "App Key를 저장했습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function testNovelAiKey() {
  const status = styleElement("novelAiSettingsStatus");
  try {
    const data = await apiFetch("/api/settings/novelai/test", { method: "POST" });
    if (status) status.textContent = `연결 성공 · Anlas ${data.anlas}`;
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function deleteNovelAiKey() {
  if (!confirm("저장된 NovelAI App Key를 삭제할까요?")) return;
  const status = styleElement("novelAiSettingsStatus");
  try {
    await apiFetch("/api/settings/novelai", { method: "DELETE" });
    if (status) status.textContent = "저장된 키를 삭제했습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function renderStyleManagerList(styles) {
  const list = styleElement("styleManagerList");
  if (!list) return;
  list.replaceChildren();
  styles.forEach((style) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "style-manager-item";
    if (style.representative_image_url) {
      const image = document.createElement("img");
      image.src = style.representative_image_url;
      image.alt = "그림체 대표 이미지";
      image.loading = "lazy";
      button.append(image);
    }
    const body = document.createElement("span");
    body.className = "style-manager-item-body";
    const title = document.createElement("strong");
    title.textContent = `그림체 #${style.id}`;
    const info = document.createElement("span");
    info.textContent = `작가 ${style.artists.length}명 · 이미지 ${style.image_count}장`;
    body.append(title, info);
    button.append(body);
    button.addEventListener("click", () => loadStyleDetail(style.id));
    list.append(button);
  });
}

async function loadStyleManager() {
  const status = styleElement("styleManagerStatus");
  try {
    const styles = await apiFetch("/api/art-styles");
    renderStyleManagerList(styles);
    styleState.managerDirty = false;
    if (status) status.textContent = styles.length ? `${styles.length}개 그림체` : "저장된 그림체가 없습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function appendMetaRow(parent, label, value) {
  const row = document.createElement("div");
  const term = document.createElement("strong");
  term.textContent = label;
  const text = document.createElement("span");
  text.textContent = value || "없음";
  row.append(term, text);
  parent.append(row);
}

function resetStyleManagerDetail() {
  const target = styleElement("styleManagerDetail");
  if (!target) return;
  target.replaceChildren();
  const placeholder = document.createElement("div");
  placeholder.className = "latest-result-placeholder";
  placeholder.textContent = "확인할 그림체를 선택하세요.";
  target.append(placeholder);
  styleState.managerImages = [];
  styleState.managerImageIndex = 0;
  closeGeneratedImage();
}

async function deleteManagedStyle(styleId) {
  if (!confirm("그림체를 삭제할까요? 생성 이미지도 함께 삭제됩니다.")) return;
  const status = styleElement("styleManagerStatus");
  try {
    await apiFetch(`/api/art-styles/${styleId}`, { method: "DELETE" });
    resetStyleManagerDetail();
    await loadStyleManager();
    if (status) status.textContent = "그림체와 생성 이미지를 삭제했습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

async function loadStyleDetail(styleId) {
  const detail = await apiFetch(`/api/art-styles/${styleId}`);
  const target = styleElement("styleManagerDetail");
  if (!target) return;
  target.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = `그림체 #${detail.id}`;
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "danger-button";
  deleteButton.textContent = "그림체 삭제";
  deleteButton.addEventListener("click", () => deleteManagedStyle(detail.id));
  const prompt = document.createElement("textarea");
  prompt.readOnly = true;
  prompt.value = detail.artist_prompt;
  prompt.className = "manager-prompt";
  const artists = document.createElement("div");
  artists.className = "manager-artists";
  detail.artists.forEach((item, index) => {
    const row = document.createElement("span");
    row.textContent = `${index + 1}. ${item.artist} · ${formatStyleWeight(item.weight)}`;
    artists.append(row);
  });
  const gallery = document.createElement("div");
  gallery.className = "manager-gallery";
  detail.images.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    const image = document.createElement("img");
    image.src = item.image_url;
    image.alt = `생성 이미지 ${index + 1}`;
    image.loading = "lazy";
    button.append(image);
    button.addEventListener("click", () => openGeneratedImage(detail.images, index));
    gallery.append(button);
  });
  target.append(heading, deleteButton, artists, prompt, gallery);
}

function openGeneratedImage(images, index) {
  styleState.managerImages = images;
  styleState.managerImageIndex = index;
  styleElement("generatedImageModal")?.classList.remove("hidden");
  renderGeneratedImageModal();
}

function closeGeneratedImage() {
  styleElement("generatedImageModal")?.classList.add("hidden");
}

function moveGeneratedImage(delta) {
  const length = styleState.managerImages.length;
  if (!length) return;
  styleState.managerImageIndex = (styleState.managerImageIndex + delta + length) % length;
  renderGeneratedImageModal();
}

function renderGeneratedImageModal() {
  const item = styleState.managerImages[styleState.managerImageIndex];
  if (!item) return;
  const image = styleElement("generatedImageFull");
  if (image) image.src = item.image_url;
  const meta = styleElement("generatedImageMeta");
  if (!meta) return;
  meta.replaceChildren();
  appendMetaRow(meta, "기본 프롬프트", item.base_prompt);
  appendMetaRow(meta, "네거티브", item.negative_prompt);
  appendMetaRow(meta, "캐릭터", (item.character_prompts || []).join(" / "));
  appendMetaRow(meta, "생성 설정", `${item.width}×${item.height} · ${item.sampler} / ${item.noise_schedule || "native"} · ${item.steps} steps · CFG ${item.scale} · Rescale ${item.cfg_rescale} · Seed ${item.seed}`);
}

function toggleStyleSettings() {
  const layout = styleElement("styleMakerLayout");
  const button = styleElement("toggleStyleSettings");
  if (!layout || !button) return;
  const collapsed = layout.classList.toggle("settings-collapsed");
  button.textContent = collapsed ? "›" : "‹";
  button.title = collapsed ? "설정 패널 열기" : "설정 패널 닫기";
  button.setAttribute("aria-label", button.title);
}

function syncScoreControls() {
  document.querySelectorAll("#styleScoreButtons [data-score]").forEach((button) => {
    const selected = styleState.allowedScores.has(Number(button.dataset.score));
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  const all = styleElement("styleScoreAll");
  if (all) {
    all.checked = styleState.allowedScores.size === 5;
    all.indeterminate = styleState.allowedScores.size > 0 && styleState.allowedScores.size < 5;
  }
}

function initializeStyleMaker() {
  if (styleState.initialized || !styleElement("styleMakerLayout")) return;
  styleState.initialized = true;

  document.querySelectorAll("#styleScoreButtons [data-score]").forEach((button) => {
    button.addEventListener("click", () => {
      const score = Number(button.dataset.score);
      if (styleState.allowedScores.has(score)) styleState.allowedScores.delete(score);
      else styleState.allowedScores.add(score);
      syncScoreControls();
    });
  });
  styleElement("styleScoreAll")?.addEventListener("change", (event) => {
    styleState.allowedScores = event.target.checked ? new Set([1, 2, 3, 4, 5]) : new Set();
    syncScoreControls();
  });
  styleElement("weightMode")?.addEventListener("change", (event) => {
    styleElement("customRangeSection")?.classList.toggle("hidden", event.target.value !== "custom");
    renderWeightGraph();
    renderWeightProfilePreview();
  });
  styleElement("addWeightRange")?.addEventListener("click", addWeightRange);
  styleElement("toggleStyleSettings")?.addEventListener("click", toggleStyleSettings);
  styleElement("rerollStyleArtists")?.addEventListener("click", () => loadStyleArtists("artists"));
  styleElement("rerollStyleWeights")?.addEventListener("click", () => loadStyleArtists("weights"));
  styleElement("rerollStyleAll")?.addEventListener("click", () => loadStyleArtists("all"));
  styleElement("sortStyleAsc")?.addEventListener("click", () => sortStyleArtists("asc"));
  styleElement("sortStyleDesc")?.addEventListener("click", () => sortStyleArtists("desc"));
  styleElement("styleArtistSearch")?.addEventListener("input", renderRatedArtistSelect);
  styleElement("addStyleArtist")?.addEventListener("click", addStyleArtist);
  styleElement("addCharacterPrompt")?.addEventListener("click", () => {
    addCharacterPrompt();
    persistAndRenderPromptControls();
  });
  styleElement("addPromptGroup")?.addEventListener("click", addPromptGroup);
  document.querySelectorAll("[data-prompt-tab]").forEach((button) => {
    button.addEventListener("click", () => selectPromptTab(button.dataset.promptTab));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      const next = button.dataset.promptTab === "base" ? "negative" : "base";
      selectPromptTab(next);
      styleElement(next === "base" ? "basePromptTab" : "negativePromptTab")?.focus();
    });
  });
  ["basePrompt", "negativePrompt"].forEach((id) => styleElement(id)?.addEventListener("input", persistAndRenderPromptControls));
  styleElement("toggleGenerationParameters")?.addEventListener("click", () => {
    const panel = styleElement("generationParameters");
    const button = styleElement("toggleGenerationParameters");
    const collapsed = panel?.classList.toggle("collapsed");
    if (button) {
      button.setAttribute("aria-expanded", String(!collapsed));
      button.textContent = collapsed ? "▶ 생성 파라미터 열기" : "▼ 생성 파라미터 닫기";
    }
  });
  styleElement("generationResolutionPreset")?.addEventListener("change", (event) => {
    if (event.target.value === "custom") return;
    const [width, height] = event.target.value.split("x");
    styleElement("generationWidth").value = width;
    styleElement("generationHeight").value = height;
  });
  [["generationScaleRange", "generationScale"], ["generationCfgRescaleRange", "generationCfgRescale"]].forEach(([rangeId, numberId]) => {
    const range = styleElement(rangeId);
    const number = styleElement(numberId);
    range?.addEventListener("input", () => { number.value = range.value; });
    number?.addEventListener("input", () => { range.value = number.value; });
  });
  styleElement("generateOne")?.addEventListener("click", () => generateCurrentStyle().catch(() => {}));
  styleElement("startContinuous")?.addEventListener("click", runContinuousGeneration);
  styleElement("pauseContinuous")?.addEventListener("click", () => {
    styleState.paused = !styleState.paused;
    renderQueueState();
  });
  styleElement("stopContinuous")?.addEventListener("click", () => {
    styleState.stopRequested = true;
    styleState.paused = false;
    renderQueueState();
  });
  styleElement("generationLimitMode")?.addEventListener("change", (event) => {
    const count = styleElement("generationCount");
    if (count) count.disabled = event.target.value === "unlimited";
  });
  ["styleMinWeight", "styleMaxWeight"].forEach((id) => styleElement(id)?.addEventListener("change", renderWeightGraph));
  styleElement("openWeightGraph")?.addEventListener("click", openWeightGraphModal);
  styleElement("closeWeightGraph")?.addEventListener("click", closeWeightGraphModal);
  document.querySelectorAll("[data-close-weight-graph]").forEach((item) => item.addEventListener("click", closeWeightGraphModal));

  const storedPrompts = loadPromptDraft();
  styleState.promptGroups = storedPrompts.prompt_groups;
  styleElement("basePrompt").value = storedPrompts.base_prompt;
  styleElement("negativePrompt").value = storedPrompts.negative_prompt;
  storedPrompts.character_prompts.forEach((value, index) => addCharacterPrompt(value, storedPrompts.character_prompt_ids[index]));
  styleState.promptGroups = cleanPromptGroups(styleState.promptGroups, storedPrompts);
  renderAllPromptTokens();
  renderPromptGroups();
  addWeightRange();
  syncScoreControls();
  renderWeightProfilePreview();
  loadRatedStyleArtists();
  loadStyleArtists();
}

if (typeof document !== "undefined") {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      const isStyleMaker = button.dataset.tab === "style-maker";
      document.body.classList.toggle("style-maker-active", isStyleMaker);
      if (isStyleMaker) initializeStyleMaker();
      if (button.dataset.tab === "style-manager" && styleState.managerDirty) loadStyleManager();
    });
  });

  styleElement("openSettings")?.addEventListener("click", openSettingsModal);
  styleElement("closeSettings")?.addEventListener("click", closeSettingsModal);
  document.querySelectorAll("[data-close-settings]").forEach((item) => item.addEventListener("click", closeSettingsModal));
  styleElement("saveNovelAiKey")?.addEventListener("click", saveNovelAiKey);
  styleElement("testNovelAiKey")?.addEventListener("click", testNovelAiKey);
  styleElement("deleteNovelAiKey")?.addEventListener("click", deleteNovelAiKey);
  styleElement("refreshStyleManager")?.addEventListener("click", loadStyleManager);
  styleElement("generatedImageClose")?.addEventListener("click", closeGeneratedImage);
  document.querySelectorAll("[data-close-generated-image]").forEach((item) => item.addEventListener("click", closeGeneratedImage));
  styleElement("generatedImagePrev")?.addEventListener("click", () => moveGeneratedImage(-1));
  styleElement("generatedImageNext")?.addEventListener("click", () => moveGeneratedImage(1));
  document.addEventListener("keydown", (event) => {
    const modal = styleElement("generatedImageModal");
    if (!modal || modal.classList.contains("hidden")) return;
    if (event.key === "Escape") closeGeneratedImage();
    if (event.key === "ArrowLeft") moveGeneratedImage(-1);
    if (event.key === "ArrowRight") moveGeneratedImage(1);
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    CUSTOM_RANGE_FIELDS,
    applyStyleRerollResult,
    buildStyleRequestPayload,
    normalizeSelectedScores,
    reorderArtists,
    runLatestStyleRequest,
    sortArtistsByWeight,
    validateCustomRangeValues,
    interpolateWeightProfile,
    formatArtistPromptTag,
    hasProfileDragMoved,
    normalizeStoredPrompts,
    promptStoragePayload,
    parsePromptTokens,
    addPromptGroupItem,
    cleanPromptGroups,
    buildEffectivePromptText,
    reachedGenerationLimit,
  };
}
