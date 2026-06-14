const styleState = {
  artists: [],
  allowedScores: new Set([1, 2, 3, 4, 5]),
  customRanges: [],
  ratedArtists: [],
  initialized: false,
  draggingIndex: null,
};

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

function buildStyleRequestPayload(options, artists, { rerollArtists, rerollWeights }) {
  const payload = {
    ...options,
    reroll_artists: rerollArtists,
    reroll_weights: rerollWeights,
  };
  if (!rerollArtists) {
    payload.artists = artists.map(({ artist, score }) => ({ artist, score }));
  }
  return payload;
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

function styleElement(id) {
  return document.getElementById(id);
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

  return {
    count,
    scores: normalizeSelectedScores(styleState.allowedScores),
    weight_mode: styleElement("weightMode")?.value || "balanced",
    min_weight: minWeight,
    max_weight: maxWeight,
    prefer_high_scores: Boolean(styleElement("preferHighScores")?.checked),
    ranges: validateCustomRanges(),
  };
}

async function loadStyleArtists({ rerollArtists = true, rerollWeights = true } = {}) {
  try {
    showStyleStatus("그림체를 구성하는 중입니다...");
    const payload = buildStyleRequestPayload(readStyleOptions(), styleState.artists, { rerollArtists, rerollWeights });
    const data = await apiFetch("/api/style-maker/artists", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    styleState.artists = data.artists || [];
    renderWeightGraph();
    showStyleStatus(`${styleState.artists.length}명의 작가를 불러왔습니다.`, "ok");
  } catch (error) {
    showStyleError(error.message);
    showStyleStatus(error.message, "error");
  }
}

function updateArtistPrompt() {
  const preview = styleElement("artistPromptPreview");
  if (!preview) return;
  preview.value = styleState.artists
    .map((item) => `${formatStyleWeight(item.weight)}::${item.artist}::`)
    .join(", ");
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
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);

  styleState.artists.forEach((item, index) => {
    item.weight = clampStyleWeight(item.weight);
    const column = document.createElement("article");
    column.className = "weight-column";
    column.draggable = true;
    column.dataset.index = String(index);

    const drag = document.createElement("button");
    drag.type = "button";
    drag.className = "drag-handle icon-button ghost";
    drag.title = "끌어서 순서 변경";
    drag.setAttribute("aria-label", `${item.artist} 순서 변경`);
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

function addCharacterPrompt(value = "") {
  const list = styleElement("characterPromptList");
  if (!list) return;
  const row = document.createElement("div");
  row.className = "character-prompt-row";
  const input = document.createElement("textarea");
  input.placeholder = "캐릭터 프롬프트";
  input.value = value;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "icon-button danger-button";
  remove.title = "캐릭터 프롬프트 삭제";
  remove.setAttribute("aria-label", "캐릭터 프롬프트 삭제");
  remove.textContent = "×";
  remove.addEventListener("click", () => row.remove());
  row.append(input, remove);
  list.append(row);
}

function toggleStyleSettings() {
  const layout = styleElement("styleMakerLayout");
  const button = styleElement("toggleStyleSettings");
  const collapsed = layout.classList.toggle("settings-collapsed");
  button.textContent = collapsed ? "›" : "‹";
  button.title = collapsed ? "설정 패널 열기" : "설정 패널 닫기";
  button.setAttribute("aria-label", button.title);
}

function syncScoreControls() {
  document.querySelectorAll("#styleScoreButtons [data-score]").forEach((button) => {
    button.classList.toggle("active", styleState.allowedScores.has(Number(button.dataset.score)));
  });
  const all = styleElement("styleScoreAll");
  if (all) all.checked = styleState.allowedScores.size === 5;
}

function initializeStyleMaker() {
  if (styleState.initialized) return;
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
  });
  styleElement("addWeightRange")?.addEventListener("click", addWeightRange);
  styleElement("toggleStyleSettings")?.addEventListener("click", toggleStyleSettings);
  styleElement("rerollStyleArtists")?.addEventListener("click", () => loadStyleArtists({ rerollArtists: true, rerollWeights: false }));
  styleElement("rerollStyleWeights")?.addEventListener("click", () => loadStyleArtists({ rerollArtists: false, rerollWeights: true }));
  styleElement("rerollStyleAll")?.addEventListener("click", () => loadStyleArtists({ rerollArtists: true, rerollWeights: true }));
  styleElement("sortStyleAsc")?.addEventListener("click", () => sortStyleArtists("asc"));
  styleElement("sortStyleDesc")?.addEventListener("click", () => sortStyleArtists("desc"));
  styleElement("styleArtistSearch")?.addEventListener("input", renderRatedArtistSelect);
  styleElement("addStyleArtist")?.addEventListener("click", addStyleArtist);
  styleElement("addCharacterPrompt")?.addEventListener("click", () => addCharacterPrompt());
  styleElement("generateOne")?.addEventListener("click", () => showStyleStatus("이미지 생성 연결은 다음 작업에서 활성화됩니다."));
  ["styleMinWeight", "styleMaxWeight"].forEach((id) => styleElement(id)?.addEventListener("change", renderWeightGraph));

  addCharacterPrompt();
  addWeightRange();
  loadRatedStyleArtists();
  loadStyleArtists();
}

if (typeof document !== "undefined") {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      const isStyleMaker = button.dataset.tab === "style-maker";
      document.body.classList.toggle("style-maker-active", isStyleMaker);
      if (isStyleMaker) initializeStyleMaker();
    });
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    CUSTOM_RANGE_FIELDS,
    buildStyleRequestPayload,
    normalizeSelectedScores,
    reorderArtists,
    sortArtistsByWeight,
    validateCustomRangeValues,
  };
}
