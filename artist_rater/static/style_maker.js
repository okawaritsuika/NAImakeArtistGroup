const styleState = {
  artists: [],
  allowedScores: new Set([1, 2, 3, 4, 5]),
  customRanges: [],
  ratedArtists: [],
  styleArtistAutocompleteItems: [],
  styleArtistAutocompleteIndex: -1,
  styleArtistAutocompleteTimer: null,
  styleArtistAutocompleteRequestToken: 0,
  styleArtistAutocompleteContext: "main",
  promptTagAutocompleteItems: [],
  promptTagAutocompleteIndex: -1,
  promptTagAutocompleteTimer: null,
  promptTagAutocompleteInput: null,
  promptTagAutocompleteBox: null,
  promptTagAutocompleteRequestToken: 0,
  selectedFixedArtistNames: new Set(),
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
  managerStyles: [],
  managerDetail: null,
  managerSelectionMode: false,
  selectedStyleIds: new Set(),
  managerNegativeExpanded: false,
  managerMode: "generated",
  managerRequestToken: 0,
  managerPage: 1,
  managerPageSize: 24,
  managerTotal: 0,
  managerPageCount: 1,
  managerDescriptions: false,
  managerFilterTimer: null,
  managerImageLoadToken: 0,
  historyItems: [],
  historySelectedId: null,
  historyDirty: true,
  historyRequestToken: 0,
  generationRemoteCollapsed: false,
  generationRemoteClosed: false,
  generationRemoteDragging: false,
  confirmedModalSource: null,
  confirmedModalFile: null,
  confirmedModalObjectUrl: "",
  confirmedModalPreviewData: null,
  confirmedImportGroups: [],
  confirmedImportGroupIndex: 0,
  confirmedImportImageIndex: 0,
  confirmedImportBusy: false,
  confirmedDuplicatePanelOpen: false,
  confirmedDuplicateStyleIndex: 0,
  confirmedDuplicateImageIndex: 0,
  confirmedFolderFiles: [],
  confirmedFolderPreviewUrls: [],
  confirmedFolderPending: false,
  confirmedModalExcludedTags: [],
  confirmedModalOriginalQualityPrompt: "",
  confirmedModalEditId: null,
  ratingTagRules: [],
  ratingTagRuleDraft: [],
  ratingExcludeTags: [],
  ratingExcludeTagDraft: [],
  sharedDependencyReferenceId: null,
  sharedDependencyReference: null,
  sharedDependencyReferenceMode: "random",
  sharedDependencyArtistPolicy: "highest",
  sharedDependencyScale: null,
  sharedDependencyCfgRescale: null,
  sharedDependencyPickerItems: [],
  sharedDependencyPickerPage: 1,
  sharedDependencyPickerTotalPages: 1,
  sharedDependencyPickerSelected: null,
  sharedDependencyPickerRequestToken: 0,
  promptGroups: [],
  promptPresets: [],
  selectedPromptPresetKey: "",
  promptPresetRequestToken: 0,
  promptPresetModalIndex: 0,
  lastPromptPresetArtistSignature: "",
  excludedPromptTags: [],
  suppressAutomaticPromptPreset: false,
  weightProfile: [
    { position: 0, weight: 0.1 },
    { position: 1, weight: 2.3 },
  ],
  weightTableSortMode: "default",
};

const PROMPT_STORAGE_KEY = "naiArtistRater.prompts.v1";
const PROMPT_PRESET_STORAGE_KEY = "naiArtistRater.promptPreset.v1";
const STYLE_MANAGER_DESCRIPTION_KEY = "naiArtistRater.styleManagerDescriptions.v1";
const STYLE_MANAGER_CARD_SIZE_KEY = "naiArtistRater.styleManagerCardSize.v1";
const STYLE_MANAGER_PAGE_SIZE_KEY = "naiArtistRater.styleManagerPageSize.v1";
const STYLE_FIXED_ARTISTS_STORAGE_KEY = "naiArtistRater.styleFixedArtists.v1";
const GENERATION_REMOTE_POSITION_KEY = "naiArtistRater.generationRemotePosition.v1";
const STYLE_MANAGER_PAGE_SIZES = [12, 24, 48, 96];
const RANDOM_STYLE_TARGETS = ["artists", "weights", "quality", "negative"];
const OPUS_FREE_MAX_STEPS = 28;
const OPUS_FREE_MAX_PIXELS = 1024 * 1024;

function normalizeSharedDependencyArtistPolicy(value) {
  return value === "random" ? "random" : "highest";
}

const STYLE_REQUEST_CONTROL_IDS = [
  "rerollStyleArtists",
  "rerollStyleWeights",
  "rerollStyleAll",
  "styleArtistCount",
  "sharedStyleArtistMin",
  "sharedStyleArtistMax",
  "sharedDependencyFixedRatio",
  "sharedDependencyReferenceRatio",
  "sharedDependencyRatedRatio",
  "sharedDependencyOtherRatio",
  "sharedDependencyArtistPolicy",
  "openRatingTagRules",
  "styleScoreAll",
  "weightMode",
  "styleMinWeight",
  "styleMaxWeight",
  "preferHighScores",
  "addWeightRange",
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
  payload.fixed_artists = artists
    .filter((item) => item.fixed === true)
    .map(({ artist, score, weight, slot, random_weight }) => ({
      artist,
      score,
      weight,
      ...(Number.isInteger(Number(slot)) ? { slot: Number(slot) } : {}),
      ...(random_weight === true ? { random_weight: true } : {}),
    }));
  if (reroll !== "all") {
    payload.artists = artists.map(({ artist, score, weight }) => ({ artist, score, weight }));
  }
  return payload;
}

function normalizeSharedDependencyRatios(values = {}) {
  const names = ["fixed", "reference", "rated", "other_shared"];
  const ratios = Object.fromEntries(names.map((name) => [name, values[name] ?? 0]));
  if (!names.every((name) => typeof ratios[name] === "number" && Number.isInteger(ratios[name]) && ratios[name] >= 0 && ratios[name] <= 100)) {
    throw new Error("공유 그림체 의존 공급원 비율은 0~100 정수여야 합니다.");
  }
  if (names.reduce((sum, name) => sum + ratios[name], 0) !== 100) {
    throw new Error("공유 그림체 의존 공급원 비율의 합은 100이어야 합니다.");
  }
  return ratios;
}

function sharedDependencyControlsState(mode) {
  const active = mode === "shared_dependency";
  return { countDisabled: active, sharedMinMaxDisabled: active, countLabel: active ? "기준 그림체 작가 수 사용" : "작가 수" };
}

function applySharedDependencyReference(payload, reroll, weightMode, referenceId, referenceMode) {
  const next = { ...(payload || {}) };
  delete next.shared_dependency_reference_id;
  delete next.shared_dependency_reference_mode;
  if (weightMode === "shared_dependency" && (referenceMode === "random" || referenceMode === "fixed")) {
    next.shared_dependency_reference_mode = referenceMode;
  }
  if (
    weightMode === "shared_dependency"
    && referenceId
    && (reroll === "weights" || referenceMode === "fixed")
  ) {
    next.shared_dependency_reference_id = referenceId;
  }
  return next;
}

function normalizeStoredFixedStyleArtists(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || item.fixed === false || typeof item.artist !== "string") return [];
    const artist = item.artist.trim();
    if (!artist || seen.has(artist)) return [];
    const rawWeight = item.weight;
    const weight = typeof rawWeight === "boolean" ? NaN : Number(rawWeight);
    if (!Number.isFinite(weight) || weight <= 0) return [];
    const normalizedWeight = Number(weight.toFixed(2));
    if (!Number.isFinite(normalizedWeight) || normalizedWeight <= 0) return [];
    const normalized = { artist, weight: normalizedWeight, fixed: true };
    const rawScore = item.score;
    const score = typeof rawScore === "boolean" ? NaN : Number(rawScore);
    if (Number.isInteger(score) && score >= 1 && score <= 5) normalized.score = score;
    const rawSlot = item.slot;
    const slot = typeof rawSlot === "boolean" ? NaN : Number(rawSlot);
    if (Number.isInteger(slot) && slot >= 0) normalized.slot = slot;
    if (item.random_weight === true) normalized.random_weight = true;
    seen.add(artist);
    return [normalized];
  });
}

function saveFixedStyleArtists(artists) {
  const stored = normalizeStoredFixedStyleArtists(
    (Array.isArray(artists) ? artists : []).filter((item) => item?.fixed === true),
  ).map(({ fixed, ...item }) => item);
  if (typeof localStorage === "undefined") return stored;
  try { localStorage.setItem(STYLE_FIXED_ARTISTS_STORAGE_KEY, JSON.stringify(stored)); } catch (_) { /* Storage can be disabled. */ }
  return stored;
}

function loadFixedStyleArtists() {
  if (typeof localStorage === "undefined") return [];
  try {
    return normalizeStoredFixedStyleArtists(JSON.parse(localStorage.getItem(STYLE_FIXED_ARTISTS_STORAGE_KEY) || "null"));
  } catch (_) {
    return [];
  }
}

function applyStyleRerollResult(currentArtists, incomingArtists, reroll, preserveOrder = false) {
  const fixedByArtist = new Map((currentArtists || [])
    .map((item) => [item.artist, item.fixed === true
      ? { fixed: true, score: item.score, slot: item.slot, random_weight: item.random_weight === true }
      : { fixed: false }]));
  const incomingNames = new Set((incomingArtists || []).map((item) => item.artist));
  const fixedAdditions = (currentArtists || [])
    .filter((item) => item.fixed === true && !incomingNames.has(item.artist))
    .map((item) => ({ ...item }));
  const merged = (incomingArtists || []).map((item) => {
    const fixed = fixedByArtist.get(item.artist);
    if (!fixed?.fixed) return { ...item };
    return {
      ...item,
      fixed: true,
      ...(item.score === undefined && fixed.score !== undefined ? { score: fixed.score } : {}),
      ...(Number.isInteger(Number(fixed.slot)) ? { slot: Number(fixed.slot) } : {}),
      ...(fixed.random_weight ? { random_weight: true } : {}),
    };
  }).concat(fixedAdditions);
  if (reroll !== "all" || preserveOrder) return merged;
  return sortArtistsByWeight(merged, "asc");
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

function parseStyleArtistNames(text) {
  return parseStyleArtistEntries(text).map((item) => item.artist);
}

function parseStyleArtistEntries(text) {
  const names = [];
  const seen = new Set();
  const source = String(text || "");
  const weightedBlocks = [...source.matchAll(/(\d+(?:\.\d+)?)\s*::\s*artist:\s*(.*?)::/gis)];
  const values = weightedBlocks.length
    ? weightedBlocks.flatMap((match) => String(match[2] || "")
      .split(/[,\n;]+/)
      .map((artist) => ({ artist: artist.trim(), weight: Number(match[1]) })))
    : source
      .split(/[,\n;]+/)
      .map((item) => item.trim())
      .filter(Boolean)
      .map((value) => {
        const match = value.match(/^(?:(\d+(?:\.\d+)?)\s*::\s*)?(?:artist:\s*)?(.+?)(?:::)?$/i);
        return {
          artist: (match?.[2] || "").trim(),
          weight: match?.[1] === undefined ? undefined : Number(match[1]),
        };
      });
  values.forEach(({ artist, weight }) => {
    if (!artist || seen.has(artist)) return;
    names.push(Number.isFinite(weight) && weight > 0 ? { artist, weight } : { artist });
    seen.add(artist);
  });
  return names;
}

function insertStyleArtistsAtPosition(currentArtists, artistNames, options = {}) {
  const current = Array.isArray(currentArtists) ? currentArtists : [];
  const weight = Number(options.weight);
  const normalizedWeight = Number.isFinite(weight) && weight > 0 ? Number(weight.toFixed(2)) : 1;
  const requestedPosition = Number(options.position);
  const slot = Number.isInteger(requestedPosition)
    ? Math.max(0, requestedPosition)
    : current.length + 1;
  const randomWeight = options.randomWeight === true;
  const remaining = current.map((item) => ({ ...item }));
  const additions = [];
  const requestedArtists = (Array.isArray(artistNames) ? artistNames : [artistNames]).flatMap((item) => (
    item && typeof item === "object"
      ? [{ artist: String(item.artist || "").trim(), weight: item.weight }]
      : parseStyleArtistEntries(item)
  ));
  const sequentialSlots = requestedArtists.length > 1;
  requestedArtists.forEach((entry, entryIndex) => {
    const artist = entry.artist;
    if (!artist) return;
    const artistSlot = slot === 0 ? 0 : (sequentialSlots ? slot + entryIndex : slot);
    const entryWeight = Number(entry.weight);
    const artistWeight = Number.isFinite(entryWeight) && entryWeight > 0
      ? Number(entryWeight.toFixed(2))
      : normalizedWeight;
    const existingIndex = remaining.findIndex((item) => item.artist === artist);
    if (existingIndex >= 0) {
      const [existing] = remaining.splice(existingIndex, 1);
      if (existing.fixed === true) {
        remaining.splice(existingIndex, 0, existing);
        return;
      }
      additions.push({
        ...existing, weight: artistWeight, fixed: true, slot: artistSlot,
        ...(randomWeight ? { random_weight: true } : {}),
      });
      return;
    }
    additions.push({
      artist, weight: artistWeight, fixed: true, slot: artistSlot,
      ...(randomWeight ? { random_weight: true } : {}),
    });
  });
  const insertAt = Number.isInteger(requestedPosition)
    ? Math.min(remaining.length, Math.max(0, requestedPosition - 1))
    : remaining.length;
  return [
    ...remaining.slice(0, insertAt),
    ...additions,
    ...remaining.slice(insertAt),
  ];
}

function updateStyleArtistAtIndex(currentArtists, index, changes = {}) {
  return (Array.isArray(currentArtists) ? currentArtists : []).map((item, itemIndex) => {
    if (itemIndex !== index) return { ...item };
    const next = { ...item };
    if (Object.prototype.hasOwnProperty.call(changes, "artist")) {
      const artist = String(changes.artist || "").trim();
      if (artist) next.artist = artist;
    }
    if (Object.prototype.hasOwnProperty.call(changes, "weight")) {
      const weight = Number(changes.weight);
      if (Number.isFinite(weight) && weight > 0) next.weight = Number(weight.toFixed(2));
    }
    if (Object.prototype.hasOwnProperty.call(changes, "random_weight")) {
      next.random_weight = changes.random_weight === true;
    }
    return next;
  });
}

function normalizeFixedArtistSlot(item, fallbackSlot) {
  const slot = Number(item?.slot);
  return Number.isInteger(slot) && slot >= 0 ? slot : fallbackSlot;
}

function moveStyleArtistToPosition(currentArtists, sourceIndex, oneBasedPosition, maxPosition = null) {
  const artists = Array.isArray(currentArtists) ? currentArtists : [];
  if (!artists[sourceIndex]) return artists.map((item) => ({ ...item }));
  const requested = Math.trunc(Number(oneBasedPosition));
  if (requested === 0) {
    return artists.map((item, index) => (
      index === sourceIndex && item.fixed === true ? { ...item, slot: 0 } : { ...item }
    ));
  }
  const slotLimit = Number.isInteger(maxPosition) && maxPosition >= 1
    ? maxPosition
    : artists.length + 1;
  const slot = Math.min(slotLimit, Math.max(1, Number.isInteger(requested) ? requested : 1));
  const target = Math.min(artists.length - 1, slot - 1);
  return reorderArtists(artists, sourceIndex, target).map((item, index) => (
    item.fixed === true && item.artist === artists[sourceIndex].artist
      ? { ...item, slot }
      : { ...item }
  ));
}

function graphInsertionPositionFromRatio(ratio, artistCount) {
  const count = Math.max(1, Math.trunc(Number(artistCount)));
  const normalized = Math.min(1, Math.max(0, Number(ratio)));
  return Math.min(count, Math.max(1, Math.round(normalized * (count - 1)) + 1));
}

function moveSelectedArtistsToPosition(currentArtists, sourceIndexes, oneBasedInsertionPosition, maxPosition = null) {
  const artists = Array.isArray(currentArtists) ? currentArtists : [];
  const selected = Array.from(new Set(sourceIndexes.map(Number)))
    .filter((index) => Number.isInteger(index) && artists[index])
    .sort((a, b) => a - b);
  if (!selected.length) return artists.map((item) => ({ ...item }));
  const selectedSet = new Set(selected);
  const requested = Math.trunc(Number(oneBasedInsertionPosition));
  const normalizedPosition = Number.isInteger(requested) ? requested : 1;
  if (normalizedPosition === 0) {
    return artists.map((item, index) => (
      selectedSet.has(index) && item.fixed === true ? { ...item, slot: 0 } : { ...item }
    ));
  }
  const insertBefore = Math.min(artists.length + 1, Math.max(1, normalizedPosition));
  const slotLimit = Number.isInteger(maxPosition) && maxPosition >= 1
    ? maxPosition
    : artists.length + 1;
  const slot = Math.min(slotLimit, Math.max(1, normalizedPosition));
  const moved = selected.map((index) => (
    artists[index]?.fixed === true ? { ...artists[index], slot } : { ...artists[index] }
  ));
  const remaining = artists
    .filter((_, index) => !selectedSet.has(index))
    .map((item) => ({ ...item }));
  const removedBeforeTarget = selected.filter((index) => index < insertBefore - 1).length;
  const insertAt = Math.min(remaining.length, Math.max(0, insertBefore - 1 - removedBeforeTarget));
  return [
    ...remaining.slice(0, insertAt),
    ...moved,
    ...remaining.slice(insertAt),
  ];
}

function fixedStyleArtistEntries(artists) {
  return (Array.isArray(artists) ? artists : [])
    .map((artist, index) => ({ artist, index }))
    .filter((entry) => entry.artist.fixed === true);
}

function limitArtistsToTotalCount(artists, totalCount) {
  const source = Array.isArray(artists) ? artists : [];
  const count = Math.max(1, Math.trunc(Number(totalCount)));
  const fixedCount = source.filter((item) => item.fixed === true).length;
  if (fixedCount > count) {
    throw new Error(`고정 작가 ${fixedCount}명이 전체 작가 수 ${count}명보다 많습니다.`);
  }
  let remainingRandom = count - fixedCount;
  return source.filter((item) => {
    if (item.fixed === true) return true;
    if (remainingRandom < 1) return false;
    remainingRandom -= 1;
    return true;
  });
}

function fixedArtistSlotEntries(artists) {
  const counters = new Map();
  const fixed = fixedStyleArtistEntries(artists).map((entry) => {
    const slot = normalizeFixedArtistSlot(entry.artist, entry.index + 1);
    const stackIndex = counters.get(slot) || 0;
    counters.set(slot, stackIndex + 1);
    return { ...entry, slot, stackIndex };
  });
  const sizes = new Map();
  fixed.forEach((entry) => sizes.set(entry.slot, (sizes.get(entry.slot) || 0) + 1));
  return fixed.map((entry) => ({ ...entry, stackSize: sizes.get(entry.slot) || 1 }));
}

function chooseArtistsForPrompt(artists, randomFn = Math.random, options = {}) {
  const source = Array.isArray(artists) ? artists : [];
  const fixedBySlot = new Map();
  fixedArtistSlotEntries(source).forEach((entry) => {
    if (entry.slot === 0) return;
    if (!fixedBySlot.has(entry.slot)) fixedBySlot.set(entry.slot, []);
    fixedBySlot.get(entry.slot).push(entry.artist);
  });
  const usedSlots = new Set();
  const selected = source.flatMap((item, index) => {
    if (item.fixed !== true) return [{ ...item }];
    const slot = normalizeFixedArtistSlot(item, index + 1);
    if (slot === 0) return [{ ...item }];
    if (usedSlots.has(slot)) return [];
    usedSlots.add(slot);
    const group = fixedBySlot.get(slot) || [item];
    const chosenIndex = Math.min(group.length - 1, Math.max(0, Math.floor(randomFn() * group.length)));
    return [{ ...group[chosenIndex] }];
  });
  const randomOrder = selected.filter((item) => item.fixed === true && normalizeFixedArtistSlot(item, 1) === 0);
  const ordered = selected.filter((item) => !(item.fixed === true && normalizeFixedArtistSlot(item, 1) === 0));
  randomOrder.forEach((item) => {
    const target = Math.min(ordered.length, Math.max(0, Math.floor(randomFn() * (ordered.length + 1))));
    ordered.splice(target, 0, item);
  });
  const minimum = Number.isFinite(Number(options.minWeight)) ? Number(options.minWeight) : styleNumber("styleMinWeight", 0.1);
  const maximum = Number.isFinite(Number(options.maxWeight)) ? Number(options.maxWeight) : styleNumber("styleMaxWeight", 2.3);
  const minCents = Math.max(1, Math.ceil(Math.min(minimum, maximum) * 100));
  const maxCents = Math.max(minCents, Math.floor(Math.max(minimum, maximum) * 100));
  const profile = Array.isArray(options.profile) ? options.profile : null;
  const lastIndex = Math.max(1, ordered.length - 1);
  return ordered.map((item, index) => {
    const isProfileTarget = item.fixed !== true || normalizeFixedArtistSlot(item, 1) === 0;
    if (profile && isProfileTarget) {
      return {
        ...item,
        weight: Number(interpolateWeightProfile(profile, index / lastIndex).toFixed(2)),
      };
    }
    if (item.random_weight === true) {
      return {
        ...item,
        weight: (minCents + Math.floor(randomFn() * (maxCents - minCents + 1))) / 100,
      };
    }
    return { ...item };
  });
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

function appendUniquePromptToken(text, token) {
  const prompt = String(token || "").trim();
  const existing = parsePromptTokens(text);
  if (!prompt || existing.some((item) => normalizePromptToken(item) === normalizePromptToken(prompt))) {
    return existing.join(", ");
  }
  return [...existing, prompt].join(", ");
}

function removePromptToken(text, token) {
  const target = normalizePromptToken(token);
  return parsePromptTokens(text)
    .filter((item) => normalizePromptToken(item) !== target)
    .join(", ");
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

function promptStoragePayload(basePrompt, negativePrompt, characterPrompts, characterPromptIds = [], promptGroups = [], generationSettings = {}, fixedPrompt = "") {
  const prompts = Array.isArray(characterPrompts)
    ? characterPrompts.map((value) => (typeof value === "string" ? value : ""))
    : [""];
  const ids = prompts.map((_, index) => String(characterPromptIds[index] || `character-${index + 1}`));
  return {
    base_prompt: typeof basePrompt === "string" ? basePrompt : "",
    fixed_prompt: typeof fixedPrompt === "string" ? fixedPrompt : "",
    negative_prompt: typeof negativePrompt === "string" ? negativePrompt : "",
    character_prompts: prompts,
    character_prompt_ids: ids,
    prompt_groups: Array.isArray(promptGroups) ? promptGroups.map(normalizePromptGroup) : [],
    generation_settings: generationSettings && typeof generationSettings === "object" ? { ...generationSettings } : {},
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
    value.generation_settings && typeof value.generation_settings === "object" ? value.generation_settings : {},
    typeof value.fixed_prompt === "string" ? value.fixed_prompt : "",
  );
}

function normalizeNumericPromptClosers(prompt) {
  let text = String(prompt || "");
  text = text.replace(/([+-]?[0-9]+(?:\.[0-9]+)?)\s*::([\s\S]*?)::/g, (group, weight, rawBody, offset) => {
    const prefix = text.slice(0, offset).trimEnd();
    if (prefix && !prefix.endsWith(",") && !prefix.endsWith("::")) return group;
    const body = rawBody.trimEnd();
    return `${weight}::${body}${/[0-9]$/.test(body) ? " " : ""}::`;
  });
  const weightedSpans = [];
  const weightedGroupPattern = /([+-]?[0-9]+(?:\.[0-9]+)?)\s*::([\s\S]*?)::/g;
  let weightedMatch;
  while ((weightedMatch = weightedGroupPattern.exec(text))) {
    const prefix = text.slice(0, weightedMatch.index).trimEnd();
    if (!prefix || prefix.endsWith(",") || prefix.endsWith("::")) weightedSpans.push([weightedMatch.index, weightedGroupPattern.lastIndex]);
  }
  text = text.replace(/(?<![0-9.])([+-]?[0-9]+(?:\.[0-9]+)?)\s*::/g, (marker, number, offset) => {
    if (weightedSpans.some(([start, end]) => start <= offset && offset < end)) return marker;
    const prefix = text.slice(0, offset).trimEnd();
    return !prefix || prefix.endsWith(",") || prefix.endsWith("::") ? `${number}::` : `${number} ::`;
  });
  return text.replace(/::\s*(?=[+-]?[0-9]+(?:\.[0-9]+)?\s*::)/g, "::, ");
}

function combinePromptSections(...sections) {
  return sections
    .map((value) => (typeof value === "string" ? normalizeNumericPromptClosers(value).trim() : ""))
    .filter(Boolean)
    .join(", ");
}

function normalizeRatingTagRules(rules) {
  if (!Array.isArray(rules)) return [];
  return rules.map((rule) => ({
    tag: String(rule?.tag || "").trim().replace(/\s+/g, "_"),
    count: Number(rule?.count),
  })).filter((rule) => rule.tag && Number.isInteger(rule.count) && rule.count > 0);
}

function normalizeRatingExcludeTags(tags) {
  if (!Array.isArray(tags)) return [];
  const seen = new Set();
  return tags.map((tag) => String(tag || "").trim().replace(/\s+/g, "_"))
    .filter((tag) => {
      const key = tag.toLowerCase();
      if (!tag || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function validateRatingExcludeTags(tags) {
  if (!Array.isArray(tags)) throw new Error("제외 태그 설정을 확인하세요.");
  if (tags.length > 20) throw new Error("제외 태그는 최대 20개까지 지정할 수 있습니다.");
  const normalized = normalizeRatingExcludeTags(tags);
  if (normalized.length !== tags.length) {
    throw new Error("제외 태그를 비우거나 같은 태그를 두 번 지정할 수 없습니다.");
  }
  return normalized;
}

function validateRatingTagRules(rules) {
  if (!Array.isArray(rules)) throw new Error("태그별 인원 설정을 확인하세요.");
  const normalized = [];
  const seen = new Set();
  rules.forEach((rule) => {
    const tag = String(rule?.tag || "").trim().replace(/\s+/g, "_");
    const count = Number(rule?.count);
    if (!tag) throw new Error("태그를 입력하세요.");
    if (!Number.isInteger(count) || count < 1 || count > 50) {
      throw new Error("태그별 인원은 1명부터 50명 사이의 정수여야 합니다.");
    }
    const key = tag.toLowerCase();
    if (seen.has(key)) throw new Error(`같은 태그를 두 번 지정할 수 없습니다: ${tag}`);
    seen.add(key);
    normalized.push({ tag, count });
  });
  return normalized;
}

function ratingTagRuleCount(rules) {
  return normalizeRatingTagRules(rules).reduce((sum, rule) => sum + rule.count, 0);
}

function promptTagFragmentBounds(value, cursorPosition = String(value || "").length) {
  const text = String(value || "");
  const cursor = Math.max(0, Math.min(text.length, Number(cursorPosition) || 0));
  const before = text.slice(0, cursor);
  const separatorIndex = Math.max(before.lastIndexOf(","), before.lastIndexOf("\n"));
  const segmentStart = separatorIndex + 1;
  const nextComma = text.indexOf(",", cursor);
  const nextNewline = text.indexOf("\n", cursor);
  const endings = [nextComma, nextNewline].filter((index) => index >= 0);
  const segmentEnd = endings.length ? Math.min(...endings) : text.length;
  const leadingWhitespace = text.slice(segmentStart, cursor).match(/^\s*/)?.[0].length || 0;
  const trailingWhitespace = text.slice(cursor, segmentEnd).match(/\s*$/)?.[0].length || 0;
  return {
    start: segmentStart + leadingWhitespace,
    end: segmentEnd - trailingWhitespace,
    cursor,
  };
}

function currentPromptTagFragment(value, cursorPosition) {
  const text = String(value || "");
  const bounds = promptTagFragmentBounds(text, cursorPosition);
  return text.slice(bounds.start, bounds.cursor).trim().replace(/\s+/g, "_");
}

function replaceCurrentPromptTagFragment(value, replacement, cursorPosition) {
  const text = String(value || "");
  const bounds = promptTagFragmentBounds(text, cursorPosition);
  const inserted = String(replacement || "");
  return {
    value: `${text.slice(0, bounds.start)}${inserted}${text.slice(bounds.end)}`,
    cursor: bounds.start + inserted.length,
  };
}

function formatPromptAutocompleteTag(item, prefixArtist = true) {
  const name = String(item?.name || "").replaceAll("_", " ");
  if (Number(item?.category) !== 1 || !prefixArtist) return name;
  return `artist:${/\d$/.test(name) ? `${name} ` : name}`;
}

function readGenerationSettings() {
  return {
    resolution_preset: styleElement("generationResolutionPreset")?.value || "832x1216",
    width: Number(styleElement("generationWidth")?.value || 832),
    height: Number(styleElement("generationHeight")?.value || 1216),
    sampler: styleElement("generationSampler")?.value || "k_euler_ancestral",
    scheduler: styleElement("generationScheduler")?.value || "karras",
    steps: Number(styleElement("generationSteps")?.value || 28),
    scale: Number(styleElement("generationScale")?.value || 5),
    cfg_rescale: Number(styleElement("generationCfgRescale")?.value || 0),
    variety_plus: Boolean(styleElement("generationVarietyPlus")?.checked),
    seed: styleElement("generationSeed")?.value || "",
    seed_fixed: Boolean(styleElement("generationSeedFixed")?.checked),
    limit_mode: styleElement("generationLimitMode")?.value || "count",
    generation_count: Number(styleElement("generationCount")?.value || 10),
    shared_artist_min: Number(styleElement("sharedStyleArtistMin")?.value || 0),
    shared_artist_max: Number(styleElement("sharedStyleArtistMax")?.value || 0),
    shared_dependency_source_ratios: {
      fixed: Number(styleElement("sharedDependencyFixedRatio")?.value || 0),
      reference: Number(styleElement("sharedDependencyReferenceRatio")?.value || 100),
      rated: Number(styleElement("sharedDependencyRatedRatio")?.value || 0),
      other_shared: Number(styleElement("sharedDependencyOtherRatio")?.value || 0),
    },
    shared_dependency_artist_policy: normalizeSharedDependencyArtistPolicy(
      styleElement("sharedDependencyArtistPolicy")?.value,
    ),
    weight_mode: styleElement("weightMode")?.value || "balanced",
    rating_tag_rules: styleState.ratingTagRules.map((rule) => ({ ...rule })),
    rating_exclude_tags: [...styleState.ratingExcludeTags],
    random_targets: [...selectedRandomTargets()],
  };
}

function applyGenerationSettings(settings = {}) {
  const setValue = (id, value) => {
    const element = styleElement(id);
    if (element && value !== undefined && value !== null) element.value = String(value);
  };
  setValue("generationResolutionPreset", settings.resolution_preset);
  setValue("generationWidth", settings.width);
  setValue("generationHeight", settings.height);
  setValue("generationSampler", settings.sampler);
  setValue("generationScheduler", settings.scheduler || "karras");
  setValue("generationSteps", settings.steps);
  setValue("generationScale", settings.scale);
  setValue("generationScaleRange", settings.scale);
  setValue("generationCfgRescale", settings.cfg_rescale);
  setValue("generationCfgRescaleRange", settings.cfg_rescale);
  setValue("generationSeed", settings.seed);
  setValue("generationLimitMode", settings.limit_mode);
  setValue("generationCount", settings.generation_count);
  setValue("sharedStyleArtistMin", settings.shared_artist_min ?? 0);
  setValue("sharedStyleArtistMax", settings.shared_artist_max);
  setValue("weightMode", settings.weight_mode);
  const sourceRatios = settings.shared_dependency_source_ratios || {};
  setValue("sharedDependencyFixedRatio", sourceRatios.fixed ?? 0);
  setValue("sharedDependencyReferenceRatio", sourceRatios.reference ?? 100);
  setValue("sharedDependencyRatedRatio", sourceRatios.rated ?? 0);
  setValue("sharedDependencyOtherRatio", sourceRatios.other_shared ?? 0);
  const artistPolicy = settings.shared_dependency_artist_policy
    ?? settings.shared_dependency_reference_artist_policy
    ?? settings.shared_dependency_artist_selection
    ?? settings.shared_dependency_reference_artist_selection
    ?? settings.shared_dependency_artist_mode;
  setValue("sharedDependencyArtistPolicy", normalizeSharedDependencyArtistPolicy(artistPolicy));
  styleState.sharedDependencyArtistPolicy = normalizeSharedDependencyArtistPolicy(artistPolicy);
  if (settings.shared_dependency_reference_id !== undefined) {
    styleState.sharedDependencyReferenceId = settings.shared_dependency_reference_id;
    styleState.sharedDependencyReference = settings.shared_dependency_reference || null;
    styleState.sharedDependencyReferenceMode = settings.shared_dependency_reference_mode === "fixed" ? "fixed" : "random";
    styleState.sharedDependencyScale = settings.shared_dependency_scale ?? settings.shared_dependency_reference?.scale ?? null;
    styleState.sharedDependencyCfgRescale = settings.shared_dependency_cfg_rescale ?? settings.shared_dependency_reference?.cfg_rescale ?? null;
  }
  styleState.ratingTagRules = normalizeRatingTagRules(
    Array.isArray(settings.rating_tag_rules)
      ? settings.rating_tag_rules
      : (settings.rating_tag_filter ? [{ tag: settings.rating_tag_filter, count: 1 }] : []),
  );
  styleState.ratingExcludeTags = normalizeRatingExcludeTags(settings.rating_exclude_tags);
  renderRatingTagRulesSummary();
  setRandomTargets(settings.random_targets, settings.style_change_mode);
  const fixed = styleElement("generationSeedFixed");
  if (fixed && typeof settings.seed_fixed === "boolean") fixed.checked = settings.seed_fixed;
  const variety = styleElement("generationVarietyPlus");
  if (variety && typeof settings.variety_plus === "boolean") variety.checked = settings.variety_plus;
  const count = styleElement("generationCount");
  if (count) count.disabled = styleElement("generationLimitMode")?.value === "unlimited";
  styleElement("customRangeSection")?.classList.toggle("hidden", styleElement("weightMode")?.value !== "custom");
  syncSharedDependencyControls();
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
    fixed_prompt: styleElement("fixedPrompt")?.value || "",
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
    readGenerationSettings(),
    draft.fixed_prompt,
  );
  try { localStorage.setItem(PROMPT_STORAGE_KEY, JSON.stringify(payload)); } catch (_) { /* Storage can be disabled. */ }
}

function loadPromptDraft() {
  if (typeof localStorage === "undefined") return normalizeStoredPrompts(null);
  try { return normalizeStoredPrompts(JSON.parse(localStorage.getItem(PROMPT_STORAGE_KEY) || "null")); }
  catch (_) { return normalizeStoredPrompts(null); }
}

function savePromptPresetSettings() {
  if (typeof localStorage === "undefined") return;
  const payload = {
    selected_key: styleState.selectedPromptPresetKey || "",
  };
  try { localStorage.setItem(PROMPT_PRESET_STORAGE_KEY, JSON.stringify(payload)); } catch (_) { /* Storage can be disabled. */ }
}

function loadPromptPresetSettings() {
  if (typeof localStorage === "undefined") return { selected_key: "" };
  try {
    const value = JSON.parse(localStorage.getItem(PROMPT_PRESET_STORAGE_KEY) || "null");
    return {
      selected_key: typeof value?.selected_key === "string" ? value.selected_key : "",
    };
  } catch (_) {
    return { selected_key: "" };
  }
}

function setPromptPresetStatus(message, state = "") {
  const status = styleElement("promptPresetStatus");
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}

function renderExcludedPromptTags() {
  const container = styleElement("excludedPromptTags");
  const list = styleElement("excludedPromptTagList");
  if (!container || !list) return;
  const tags = Array.isArray(styleState.excludedPromptTags) ? styleState.excludedPromptTags : [];
  container.classList.toggle("hidden", tags.length === 0);
  list.replaceChildren(...tags.map((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "excluded-prompt-tag";
    button.textContent = `↩ ${item.prompt || item.tag}`;
    button.title = "기본 프롬프트에 다시 넣기";
    button.addEventListener("click", () => restoreExcludedPromptTag(index));
    return button;
  }));
}

function restoreExcludedPromptTag(index) {
  const item = styleState.excludedPromptTags[index];
  const prompt = String(item?.prompt || "").trim();
  if (!prompt) return false;
  const input = styleElement("basePrompt");
  input.value = appendUniquePromptToken(input?.value, prompt);
  styleState.excludedPromptTags.splice(index, 1);
  fixPromptPresetAfterManualEdit();
  persistAndRenderPromptControls();
  renderExcludedPromptTags();
  setPromptPresetStatus(`제외했던 ${item.tag || prompt} 태그를 복원했습니다. 랜덤 대상이 꺼져 있으면 그대로 유지됩니다.`, "ok");
  return true;
}

function excludeBasePromptToken(token) {
  const prompt = String(token || "").trim();
  const input = styleElement("basePrompt");
  if (!prompt || !input) return false;
  const nextValue = removePromptToken(input.value, prompt);
  if (nextValue === parsePromptTokens(input.value).join(", ")) return false;
  input.value = nextValue;
  if (!styleState.excludedPromptTags.some((item) => (
    normalizePromptToken(item?.prompt) === normalizePromptToken(prompt)
  ))) {
    styleState.excludedPromptTags.push({ tag: prompt, prompt });
  }
  fixPromptPresetAfterManualEdit();
  persistAndRenderPromptControls();
  renderExcludedPromptTags();
  setPromptPresetStatus(`${prompt} 태그를 제외 목록으로 옮겼습니다. 제외 목록에서 누르면 복원됩니다.`, "ok");
  return true;
}

function renderPromptPresetOptions() {
  const button = styleElement("openPromptPresetModal");
  const text = styleElement("promptPresetButtonText");
  if (!styleState.promptPresets.length) {
    if (text) text.textContent = "사용 가능한 수집 세트가 없습니다.";
    if (button) button.disabled = true;
    return;
  }
  const selectedExists = styleState.promptPresets.some((preset) => preset.key === styleState.selectedPromptPresetKey);
  if (!selectedExists) styleState.selectedPromptPresetKey = styleState.promptPresets[0].key;
  const selected = styleState.promptPresets.find((preset) => preset.key === styleState.selectedPromptPresetKey);
  if (text) {
    const modified = selected?.modified ? " · 수정됨" : "";
    text.textContent = `수집 프롬프트 갤러리 열기 · ${styleState.promptPresets.length}개${modified}`;
  }
  if (button) button.disabled = false;
}

function applyPromptPreset(preset) {
  if (!preset) return false;
  styleElement("basePrompt").value = preset.base_prompt || preset.quality_prompt || "";
  styleElement("negativePrompt").value = preset.negative_prompt || "";
  styleState.excludedPromptTags = Array.isArray(preset.excluded_tags)
    ? preset.excluded_tags.map((item) => ({ tag: String(item?.tag || ""), prompt: String(item?.prompt || "") })).filter((item) => item.prompt)
    : [];
  styleState.selectedPromptPresetKey = preset.key || "";
  renderPromptPresetOptions();
  persistAndRenderPromptControls();
  renderExcludedPromptTags();
  savePromptPresetSettings();
  const match = preset.match_count ? `선택 작가 ${preset.match_count}명과 일치` : "전체 수집본 기준";
  const excluded = styleState.excludedPromptTags.length ? ` · 인물 태그 ${styleState.excludedPromptTags.length}개 제외` : "";
  setPromptPresetStatus(`수집 포지티브와 네거티브 전체를 적용했습니다. (${match}${excluded})`, "ok");
  return true;
}

function promptPresetFullText(preset, qualityPrompt = null) {
  const quality = qualityPrompt === null
    ? String(preset?.base_prompt || preset?.quality_prompt || "").trim()
    : String(qualityPrompt || "").trim();
  const excluded = Array.isArray(preset?.excluded_tags)
    ? preset.excluded_tags.map((item) => String(item?.prompt || "").trim()).filter(Boolean)
    : [];
  return combinePromptSections(quality, ...excluded);
}

function currentPromptPresetModalItem() {
  return styleState.promptPresets[styleState.promptPresetModalIndex] || null;
}

function updatePromptPresetFullPreview() {
  const preview = styleElement("promptPresetFullPreview");
  if (!preview) return;
  preview.textContent = promptPresetFullText(
    currentPromptPresetModalItem(),
    styleElement("promptPresetQualityEditor")?.value || "",
  ) || "프롬프트 없음";
}

function renderPromptPresetDetail() {
  const preset = currentPromptPresetModalItem();
  const editor = styleElement("promptPresetQualityEditor");
  if (editor) editor.value = preset?.base_prompt || preset?.quality_prompt || "";
  const title = styleElement("promptPresetDetailTitle");
  if (title) title.textContent = preset?.representative_image?.title || `수집 프롬프트 ${styleState.promptPresetModalIndex + 1}`;
  const meta = styleElement("promptPresetDetailMeta");
  if (meta) meta.textContent = preset
    ? `${styleState.promptPresetModalIndex + 1}/${styleState.promptPresets.length} · 표본 ${preset.sample_count || 1}${preset.modified ? " · 수정본" : ""}`
    : "";
  const excludedList = styleElement("promptPresetExcludedList");
  if (excludedList) {
    const excluded = Array.isArray(preset?.excluded_tags) ? preset.excluded_tags : [];
    excludedList.replaceChildren(...excluded.map((item) => {
      const tag = document.createElement("span");
      tag.textContent = item.prompt || item.tag || "";
      return tag;
    }));
    if (!excluded.length) excludedList.textContent = "제외된 태그 없음";
  }
  const applyButton = styleElement("saveAndApplyPromptPreset");
  if (applyButton) applyButton.disabled = !preset;
  const status = styleElement("promptPresetModalStatus");
  if (status) status.textContent = "";
  updatePromptPresetFullPreview();
}

function renderPromptPresetModal() {
  const gallery = styleElement("promptPresetGallery");
  if (!gallery) return;
  gallery.replaceChildren();
  styleState.promptPresets.forEach((preset, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "prompt-preset-card";
    button.classList.toggle("active", index === styleState.promptPresetModalIndex);
    const representative = preset.representative_image || {};
    const imageUrl = representative.thumbnail_url || representative.image_url || "";
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = imageUrl;
      image.loading = "lazy";
      image.decoding = "async";
      image.alt = representative.title || `수집 프롬프트 ${index + 1}`;
      button.append(image);
    } else {
      const empty = document.createElement("span");
      empty.className = "prompt-preset-card-empty";
      empty.textContent = "이미지 없음";
      button.append(empty);
    }
    const label = document.createElement("span");
    label.textContent = `${index + 1}${preset.modified ? " · 수정됨" : ""}`;
    const count = document.createElement("small");
    count.textContent = `표본 ${preset.sample_count || 1}${preset.match_count ? ` · 작가 ${preset.match_count}명 일치` : ""}`;
    button.append(label, count);
    button.addEventListener("click", () => {
      styleState.promptPresetModalIndex = index;
      [...gallery.children].forEach((card, cardIndex) => card.classList.toggle("active", cardIndex === index));
      renderPromptPresetDetail();
    });
    button.addEventListener("dblclick", () => {
      applyPromptPreset(preset);
      closePromptPresetModal();
    });
    gallery.append(button);
  });
  renderPromptPresetDetail();
}

function openPromptPresetModal() {
  if (!styleState.promptPresets.length) return;
  const selectedIndex = styleState.promptPresets.findIndex((preset) => preset.key === styleState.selectedPromptPresetKey);
  styleState.promptPresetModalIndex = selectedIndex >= 0 ? selectedIndex : 0;
  renderPromptPresetModal();
  styleElement("promptPresetModal")?.classList.remove("hidden");
}

function closePromptPresetModal() {
  styleElement("promptPresetModal")?.classList.add("hidden");
}

async function saveAndApplyPromptPreset() {
  const preset = currentPromptPresetModalItem();
  const qualityPrompt = styleElement("promptPresetQualityEditor")?.value.trim() || "";
  const status = styleElement("promptPresetModalStatus");
  if (!preset || !qualityPrompt) {
    if (status) status.textContent = "적용할 퀄리티 프롬프트를 입력해 주세요.";
    return false;
  }
  try {
    if (qualityPrompt !== String(preset.base_prompt || preset.quality_prompt || "").trim()) {
      if (status) status.textContent = "수정한 프롬프트를 저장하는 중입니다...";
      await apiFetch(`/api/style-maker/prompt-presets/${preset.key}`, {
        method: "PATCH",
        body: JSON.stringify({ quality_prompt: qualityPrompt }),
      });
      preset.base_prompt = qualityPrompt;
      preset.quality_prompt = qualityPrompt;
      preset.modified = true;
    }
    applyPromptPreset(preset);
    closePromptPresetModal();
    return true;
  } catch (error) {
    if (status) status.textContent = error.message;
    return false;
  }
}

async function loadPromptPresets({ force = false } = {}) {
  if (!styleState.artists.length) return false;
  const artists = chooseArtistsForPrompt(styleState.artists).map((item) => item.artist);
  const signature = [...artists].sort().join("\n");
  if (!force && signature === styleState.lastPromptPresetArtistSignature) return false;
  styleState.lastPromptPresetArtistSignature = signature;
  const token = ++styleState.promptPresetRequestToken;
  setPromptPresetStatus("수집한 그림체에서 프롬프트 세트를 고르는 중입니다...");
  try {
    const result = await apiFetch("/api/style-maker/prompt-presets", {
      method: "POST",
      body: JSON.stringify({ artists, limit: 30 }),
    });
    if (token !== styleState.promptPresetRequestToken) return false;
    styleState.promptPresets = Array.isArray(result.presets) ? result.presets : [];
    renderPromptPresetOptions();
    if (!styleState.promptPresets.length) {
      styleState.excludedPromptTags = [];
      renderExcludedPromptTags();
      setPromptPresetStatus("랜덤으로 사용할 수집 프롬프트가 없습니다.", "error");
      return false;
    }
    setPromptPresetStatus("세트를 직접 적용하거나, 아래 랜덤 대상에서 퀄리티·네거 프롬을 켜세요.");
    return true;
  } catch (error) {
    if (token === styleState.promptPresetRequestToken) {
      styleState.promptPresets = [];
      renderPromptPresetOptions();
      setPromptPresetStatus(error.message, "error");
    }
    return false;
  }
}

function refreshPromptPresetsForArtists() {
  if (styleState.suppressAutomaticPromptPreset) return;
  void loadPromptPresets();
}

function fixPromptPresetAfterManualEdit() {
  setPromptPresetStatus("직접 수정한 프롬프트를 유지합니다. 아래 랜덤 대상이 켜진 항목만 생성할 때 바뀝니다.");
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
    chip.draggable = field !== "artist";
    chip.textContent = token;
    if (field === "base") {
      chip.title = "클릭해서 제외 목록으로 이동";
      chip.addEventListener("click", () => excludeBasePromptToken(token));
    } else if (field === "artist") {
      chip.title = "작가 태그";
    } else {
      chip.title = "그룹으로 드래그";
    }
    if (field !== "artist") {
      chip.addEventListener("dragstart", (event) => setPromptDragData(event, item));
    }
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
  hidePromptTagAutocomplete();
  document.querySelectorAll("[data-prompt-tab]").forEach((button) => {
    const active = button.dataset.promptTab === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  styleElement("basePromptPanel")?.classList.toggle("hidden", selected !== "base");
  styleElement("negativePromptPanel")?.classList.toggle("hidden", selected !== "negative");
}

function setPromptViewMode(mode) {
  const textMode = mode === "text";
  if (!textMode) hidePromptTagAutocomplete();
  document.querySelector(".prompt-workspace")?.classList.toggle("prompt-text-mode", textMode);
  const button = styleElement("togglePromptView");
  if (button) {
    button.dataset.mode = textMode ? "text" : "buttons";
    button.setAttribute("aria-pressed", String(textMode));
    button.textContent = textMode ? "버튼 보기" : "텍스트 편집";
  }
  if (!textMode) renderAllPromptTokens();
  return textMode ? "text" : "buttons";
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
    rename.addEventListener("click", async () => {
      const next = await globalThis.appDialog.prompt({
        title: "프롬프트 그룹 이름 변경",
        message: "그룹을 구분할 새 이름을 입력하세요.",
        inputLabel: "그룹 이름",
        defaultValue: group.name,
        confirmLabel: "변경",
        tone: "info",
      });
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
  document.querySelectorAll("#styleScoreButtons [data-score], #customRangeList input, #customRangeList button, #weightGraph input, #weightGraph select, #weightGraph button, .weight-fixed-artist-card input, .weight-fixed-artist-card button")
    .forEach((control) => { control.disabled = pending; });
  document.querySelectorAll("#weightGraph .weight-column")
    .forEach((column) => { column.draggable = !pending; });
  syncSharedDependencyControls();
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

function ratingTagComposition(rules = styleState.ratingTagRules) {
  const total = Number(styleElement("styleArtistCount")?.value || 0);
  const fixed = fixedStyleArtistEntries(styleState.artists).length;
  const tagged = ratingTagRuleCount(rules);
  const sharedMin = Number(styleElement("sharedStyleArtistMin")?.value || 0);
  const sharedMax = Number(styleElement("sharedStyleArtistMax")?.value || 0);
  return {
    total,
    fixed,
    tagged,
    sharedMin,
    sharedMax,
    unrestrictedMin: Math.max(0, total - fixed - tagged - sharedMax),
    unrestrictedMax: Math.max(0, total - fixed - tagged - sharedMin),
  };
}

function renderRatingTagRulesSummary() {
  const summary = styleElement("ratingTagRulesSummary");
  if (!summary) return;
  const rules = normalizeRatingTagRules(styleState.ratingTagRules);
  const exclusions = normalizeRatingExcludeTags(styleState.ratingExcludeTags);
  const ruleText = rules.length
    ? rules.map((rule) => `${rule.tag} ${rule.count}명`).join(" · ")
    : "태그별 인원 설정 없음 · 남은 자리는 전체 평가 작가에서 선택";
  const exclusionText = exclusions.length ? ` · 제외 ${exclusions.join(", ")}` : "";
  summary.textContent = `${ruleText}${exclusionText}`;
}

function renderRatingTagRuleCountSummary() {
  const target = styleElement("ratingTagRulesCountSummary");
  if (!target) return;
  const counts = ratingTagComposition(styleState.ratingTagRuleDraft);
  const unrestricted = counts.unrestrictedMin === counts.unrestrictedMax
    ? `${counts.unrestrictedMax}명`
    : `${counts.unrestrictedMin}~${counts.unrestrictedMax}명`;
  target.textContent = `전체 ${counts.total}명 · 고정 ${counts.fixed}명 · 태그 지정 ${counts.tagged}명 · 공유 ${counts.sharedMin}~${counts.sharedMax}명 · 전체 평가 작가 ${unrestricted}`;
}

function renderRatingTagRuleRows() {
  const list = styleElement("ratingTagRulesList");
  if (!list) return;
  list.replaceChildren();
  if (!styleState.ratingTagRuleDraft.length) {
    const empty = document.createElement("p");
    empty.className = "help-text";
    empty.textContent = "태그 조건이 없습니다. 모든 남은 자리를 전체 평가 작가에서 뽑습니다.";
    list.append(empty);
  }
  styleState.ratingTagRuleDraft.forEach((rule, index) => {
    const row = document.createElement("div");
    row.className = "rating-tag-rule-row";
    const tagField = document.createElement("label");
    tagField.className = "field";
    const tagLabel = document.createElement("span");
    tagLabel.textContent = "평가 태그";
    const tagInput = document.createElement("input");
    tagInput.type = "text";
    tagInput.autocomplete = "off";
    tagInput.dataset.prefixArtist = "false";
    tagInput.dataset.ratingTagAutocomplete = "true";
    tagInput.setAttribute("aria-label", `평가 태그 ${index + 1}`);
    tagInput.placeholder = "예: dakimakura_(medium)";
    tagInput.value = rule.tag || "";
    const autocomplete = document.createElement("div");
    autocomplete.className = "autocomplete prompt-tag-autocomplete hidden";
    tagInput.addEventListener("input", () => {
      styleState.ratingTagRuleDraft[index].tag = tagInput.value;
      renderRatingTagRuleCountSummary();
    });
    tagField.append(tagLabel, tagInput, autocomplete);
    const countField = document.createElement("label");
    countField.className = "field";
    const countLabel = document.createElement("span");
    countLabel.textContent = "인원";
    const countInput = document.createElement("input");
    countInput.type = "number";
    countInput.min = "1";
    countInput.max = "50";
    countInput.step = "1";
    countInput.value = String(rule.count || 1);
    countInput.addEventListener("input", () => {
      styleState.ratingTagRuleDraft[index].count = Number(countInput.value);
      renderRatingTagRuleCountSummary();
    });
    countField.append(countLabel, countInput);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "rating-tag-rule-remove danger-button";
    remove.title = "태그 조건 삭제";
    remove.setAttribute("aria-label", "태그 조건 삭제");
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      styleState.ratingTagRuleDraft.splice(index, 1);
      hidePromptTagAutocomplete();
      renderRatingTagRuleRows();
      renderRatingTagRuleCountSummary();
    });
    row.append(tagField, countField, remove);
    list.append(row);
    bindPromptTagAutocomplete(tagInput);
  });
  renderRatingTagRuleCountSummary();
}

function renderRatingTagExclusionRows() {
  const list = styleElement("ratingTagExclusionsList");
  if (!list) return;
  list.replaceChildren();
  if (!styleState.ratingExcludeTagDraft.length) {
    const empty = document.createElement("p");
    empty.className = "help-text";
    empty.textContent = "제외 태그가 없습니다.";
    list.append(empty);
  }
  styleState.ratingExcludeTagDraft.forEach((tag, index) => {
    const row = document.createElement("div");
    row.className = "rating-tag-rule-row rating-tag-exclusion-row";
    const field = document.createElement("label");
    field.className = "field";
    const label = document.createElement("span");
    label.textContent = "제외할 수집 태그";
    const input = document.createElement("input");
    input.type = "text";
    input.autocomplete = "off";
    input.dataset.prefixArtist = "false";
    input.placeholder = "예: monochrome";
    input.value = tag || "";
    const autocomplete = document.createElement("div");
    autocomplete.className = "autocomplete prompt-tag-autocomplete hidden";
    input.addEventListener("input", () => {
      styleState.ratingExcludeTagDraft[index] = input.value;
    });
    field.append(label, input, autocomplete);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "rating-tag-rule-remove danger-button";
    remove.title = "제외 태그 삭제";
    remove.setAttribute("aria-label", "제외 태그 삭제");
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      styleState.ratingExcludeTagDraft.splice(index, 1);
      hidePromptTagAutocomplete();
      renderRatingTagExclusionRows();
    });
    row.append(field, remove);
    list.append(row);
    bindPromptTagAutocomplete(input);
  });
}

function openRatingTagRulesModal() {
  styleState.ratingTagRuleDraft = styleState.ratingTagRules.length
    ? styleState.ratingTagRules.map((rule) => ({ ...rule }))
    : [{ tag: "", count: 1 }];
  styleState.ratingExcludeTagDraft = [...styleState.ratingExcludeTags];
  const status = styleElement("ratingTagRulesStatus");
  if (status) status.textContent = "";
  renderRatingTagRuleRows();
  renderRatingTagExclusionRows();
  styleElement("ratingTagRulesModal")?.classList.remove("hidden");
}

function closeRatingTagRulesModal() {
  hidePromptTagAutocomplete();
  styleElement("ratingTagRulesModal")?.classList.add("hidden");
  styleState.ratingTagRuleDraft = [];
  styleState.ratingExcludeTagDraft = [];
}

function addRatingTagRule() {
  styleState.ratingTagRuleDraft.push({ tag: "", count: 1 });
  renderRatingTagRuleRows();
}

function addRatingTagExclusion() {
  styleState.ratingExcludeTagDraft.push("");
  renderRatingTagExclusionRows();
}

function saveRatingTagRules() {
  const status = styleElement("ratingTagRulesStatus");
  try {
    const rules = validateRatingTagRules(styleState.ratingTagRuleDraft);
    const exclusions = validateRatingExcludeTags(styleState.ratingExcludeTagDraft);
    const counts = ratingTagComposition(rules);
    if (styleElement("weightMode")?.value !== "shared_dependency" && counts.fixed + counts.tagged + counts.sharedMin > counts.total) {
      throw new Error("고정 작가, 태그 지정 인원, 공유 작가 최소 인원의 합이 전체 작가 수를 넘습니다.");
    }
    styleState.ratingTagRules = rules;
    styleState.ratingExcludeTags = exclusions;
    renderRatingTagRulesSummary();
    savePromptDraft();
    closeRatingTagRulesModal();
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function renderSharedDependencyRatioSummary() {
  const target = styleElement("sharedDependencyRatioSummary");
  if (!target) return;
  const values = [
    "sharedDependencyFixedRatio",
    "sharedDependencyReferenceRatio",
    "sharedDependencyRatedRatio",
    "sharedDependencyOtherRatio",
  ].map((id) => Number(styleElement(id)?.value));
  const total = values.every(Number.isFinite) ? values.reduce((sum, value) => sum + value, 0) : NaN;
  target.textContent = Number.isInteger(total) && total === 100
    ? "합계 100% · 후보가 부족하면 0%가 아닌 공급원으로 재분배합니다."
    : `합계 ${Number.isFinite(total) ? total : "-"}% · 100%가 되도록 입력하세요.`;
  target.classList.toggle("error", total !== 100);
}

function sharedDependencyReferenceTitle(reference) {
  const title = String(reference?.title || "").trim();
  const id = Number(reference?.id);
  return title || (Number.isInteger(id) && id > 0 ? `공유 이미지 #${id}` : "기준 그림체");
}

function renderSharedDependencyReferenceSummary() {
  const target = styleElement("sharedDependencyReferenceSummary");
  if (!target) return;
  const active = styleElement("weightMode")?.value === "shared_dependency";
  const reference = styleState.sharedDependencyReference;
  const id = Number(styleState.sharedDependencyReferenceId || reference?.id);
  const modeLabel = styleState.sharedDependencyReferenceMode === "fixed" ? "고정 기준" : "랜덤 기준";
  target.textContent = Number.isInteger(id) && id > 0
    ? `${modeLabel} · ${sharedDependencyReferenceTitle({ ...reference, id })} (#${id})`
    : `${modeLabel} · 아직 선택하지 않음`;
  target.classList.toggle("is-fixed", styleState.sharedDependencyReferenceMode === "fixed");
  const openButton = styleElement("openSharedDependencyReference");
  if (openButton) openButton.disabled = !active || styleState.pending;
  const randomButton = styleElement("randomizeSharedDependencyReference");
  if (randomButton) randomButton.disabled = !active || styleState.pending;
  const clearButton = styleElement("clearSharedDependencyReference");
  if (clearButton) {
    clearButton.disabled = !active
      || styleState.pending
      || styleState.sharedDependencyReferenceMode !== "fixed";
  }
}

function normalizeSharedDependencyReferenceItem(item) {
  if (!item || typeof item !== "object") return null;
  const id = Number(item.id);
  if (!Number.isInteger(id) || id < 1) return null;
  const artists = Array.isArray(item.shared_dependency_artists)
    ? item.shared_dependency_artists
    : Array.isArray(item.artists) ? item.artists : [];
  return {
    ...item,
    id,
    title: String(item.title || "").trim(),
    image_url: String(item.image_url || item.thumbnail_url || "").trim(),
    thumbnail_url: String(item.thumbnail_url || item.image_url || "").trim(),
    shared_dependency_eligible: item.shared_dependency_eligible === true || artists.length > 0,
    shared_dependency_artists: artists,
  };
}

function sharedDependencyReferenceQuery(page = 1) {
  const query = new URLSearchParams({
    offset: String(Math.max(0, (Math.max(1, Number(page) || 1) - 1) * 24)),
    limit: "24",
    q: String(styleElement("sharedDependencyReferenceSearch")?.value || "").trim(),
    metadata: "all",
    sort: "posted_desc",
  });
  return query;
}

function renderSharedDependencyReferenceDetail(item) {
  const target = styleElement("sharedDependencyReferenceDetail");
  if (!target) return;
  target.replaceChildren();
  if (!item) {
    const empty = document.createElement("p");
    empty.className = "latest-result-placeholder";
    empty.textContent = "그림을 선택해 주세요.";
    target.append(empty);
    return;
  }
  const heading = document.createElement("h3");
  heading.textContent = sharedDependencyReferenceTitle(item);
  const meta = document.createElement("p");
  meta.className = "shared-dependency-reference-meta";
  const artistCount = item.shared_dependency_artists?.length || 0;
  meta.textContent = item.shared_dependency_eligible
    ? `작가 ${artistCount}명 · ${item.board_tab || "공유 그림체"}`
    : "작가를 인식할 수 없어 기준으로 확정할 수 없습니다.";
  if (item.image_url) {
    const image = document.createElement("img");
    image.className = "shared-dependency-reference-large-image";
    image.src = item.image_url;
    image.alt = `${sharedDependencyReferenceTitle(item)} 미리보기`;
    target.append(image);
  }
  const prompt = document.createElement("pre");
  prompt.className = "shared-dependency-reference-prompt";
  prompt.textContent = item.base_prompt || item.prompt || "프롬프트 없음";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "primary";
  confirm.textContent = "이 그림체를 기준으로 확정";
  confirm.disabled = !item.shared_dependency_eligible;
  confirm.addEventListener("click", () => confirmSharedDependencyReference(item));
  target.append(heading, meta, prompt, confirm);
}

function renderSharedDependencyReferenceList(items) {
  const target = styleElement("sharedDependencyReferenceList");
  if (!target) return;
  target.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "latest-result-placeholder";
    empty.textContent = "표시할 공유 그림체 이미지가 없습니다.";
    target.append(empty);
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "shared-dependency-reference-card";
    card.classList.toggle("is-selected", item.id === styleState.sharedDependencyPickerSelected?.id);
    card.classList.toggle("is-ineligible", !item.shared_dependency_eligible);
    card.setAttribute("aria-label", `${sharedDependencyReferenceTitle(item)} 상세 보기`);
    if (item.thumbnail_url) {
      const image = document.createElement("img");
      image.src = item.thumbnail_url;
      image.alt = "";
      card.append(image);
    }
    const title = document.createElement("strong");
    title.textContent = sharedDependencyReferenceTitle(item);
    const badge = document.createElement("span");
    badge.textContent = item.shared_dependency_eligible ? "기준 가능" : "작가 없음";
    card.append(title, badge);
    card.addEventListener("click", () => {
      styleState.sharedDependencyPickerSelected = item;
      renderSharedDependencyReferenceList(styleState.sharedDependencyPickerItems);
      renderSharedDependencyReferenceDetail(item);
    });
    target.append(card);
  });
}

async function loadSharedDependencyReferencePage(page = styleState.sharedDependencyPickerPage) {
  const token = styleState.sharedDependencyPickerRequestToken + 1;
  styleState.sharedDependencyPickerRequestToken = token;
  showStyleStatus("기준 그림체 목록을 불러오는 중입니다...");
  try {
    const result = await apiFetch(`/api/style-manager/shared?${sharedDependencyReferenceQuery(page)}`);
    if (token !== styleState.sharedDependencyPickerRequestToken) return;
    styleState.sharedDependencyPickerItems = (Array.isArray(result?.items) ? result.items : [])
      .map(normalizeSharedDependencyReferenceItem).filter(Boolean);
    styleState.sharedDependencyPickerPage = Math.max(1, Number(result?.offset || 0) / 24 + 1);
    styleState.sharedDependencyPickerTotalPages = Math.max(1, Math.ceil(Number(result?.total || 0) / 24));
    renderSharedDependencyReferenceList(styleState.sharedDependencyPickerItems);
    const current = styleState.sharedDependencyPickerItems.find((item) => item.id === Number(styleState.sharedDependencyReferenceId));
    if (current) styleState.sharedDependencyPickerSelected = current;
    renderSharedDependencyReferenceDetail(styleState.sharedDependencyPickerSelected || current || null);
    const summary = styleElement("sharedDependencyReferencePageSummary");
    if (summary) summary.textContent = `${styleState.sharedDependencyPickerPage} / ${styleState.sharedDependencyPickerTotalPages} 페이지`;
    const previous = styleElement("sharedDependencyReferencePrev");
    const next = styleElement("sharedDependencyReferenceNext");
    if (previous) previous.disabled = styleState.sharedDependencyPickerPage <= 1;
    if (next) next.disabled = styleState.sharedDependencyPickerPage >= styleState.sharedDependencyPickerTotalPages;
    showStyleStatus("");
  } catch (error) {
    if (token === styleState.sharedDependencyPickerRequestToken) {
      showStyleError(error.message);
      const status = styleElement("sharedDependencyReferenceStatus");
      if (status) status.textContent = error.message;
    }
  }
}

function setSharedDependencyReference(reference, mode = "fixed") {
  const normalized = normalizeSharedDependencyReferenceItem(reference);
  if (!normalized || !normalized.shared_dependency_eligible) return false;
  styleState.sharedDependencyReferenceId = normalized.id;
  styleState.sharedDependencyReference = normalized;
  styleState.sharedDependencyReferenceMode = mode === "fixed" ? "fixed" : "random";
  styleState.sharedDependencyScale = normalized.scale ?? null;
  styleState.sharedDependencyCfgRescale = normalized.cfg_rescale ?? null;
  renderSharedDependencyReferenceSummary();
  return true;
}

function clearSharedDependencyReference() {
  styleState.sharedDependencyReferenceMode = "random";
  styleState.sharedDependencyReferenceId = null;
  styleState.sharedDependencyReference = null;
  styleState.sharedDependencyScale = null;
  styleState.sharedDependencyCfgRescale = null;
  styleState.sharedDependencyPickerSelected = null;
  renderSharedDependencyReferenceSummary();
  return {
    shared_dependency_reference_mode: styleState.sharedDependencyReferenceMode,
    shared_dependency_reference_id: styleState.sharedDependencyReferenceId,
    shared_dependency_reference: styleState.sharedDependencyReference,
    shared_dependency_scale: styleState.sharedDependencyScale,
    shared_dependency_cfg_rescale: styleState.sharedDependencyCfgRescale,
  };
}

function confirmSharedDependencyReference(item) {
  if (!setSharedDependencyReference(item, "fixed")) return;
  styleElement("sharedDependencyReferenceModal")?.classList.add("hidden");
  const status = styleElement("sharedDependencyReferenceStatus");
  if (status) status.textContent = "기준 그림체를 고정했습니다.";
}

async function randomizeSharedDependencyReference() {
  styleState.sharedDependencyReferenceMode = "random";
  const eligible = styleState.sharedDependencyPickerItems.filter((item) => item.shared_dependency_eligible);
  if (!eligible.length) {
    await loadSharedDependencyReferencePage(1);
  }
  const pool = styleState.sharedDependencyPickerItems.filter((item) => item.shared_dependency_eligible);
  if (pool.length) {
    const currentId = Number(styleState.sharedDependencyReferenceId);
    const candidates = pool.filter((item) => item.id !== currentId);
    setSharedDependencyReference((candidates.length ? candidates : pool)[Math.floor(Math.random() * (candidates.length ? candidates.length : pool.length))], "random");
    styleState.sharedDependencyPickerSelected = styleState.sharedDependencyReference;
    renderSharedDependencyReferenceList(styleState.sharedDependencyPickerItems);
    renderSharedDependencyReferenceDetail(styleState.sharedDependencyReference);
  }
  renderSharedDependencyReferenceSummary();
}

function openSharedDependencyReferenceModal() {
  styleElement("sharedDependencyReferenceModal")?.classList.remove("hidden");
  void loadSharedDependencyReferencePage(styleState.sharedDependencyPickerPage);
}

function closeSharedDependencyReferenceModal() {
  styleElement("sharedDependencyReferenceModal")?.classList.add("hidden");
}

function setSharedDependencyReferenceFromArca(image, item = {}) {
  const reference = {
    ...image,
    id: image?.id,
    title: item.title || image?.title,
    source_url: item.source_url || image?.source_url,
    shared_dependency_eligible: true,
    shared_dependency_artists: image?.shared_dependency_artists || [{ artist: "parsed" }],
  };
  if (!setSharedDependencyReference(reference, "fixed")) return false;
  closeSharedDependencyReferenceModal();
  const weightMode = styleElement("weightMode");
  if (weightMode) {
    weightMode.value = "shared_dependency";
    if (typeof Event !== "undefined") weightMode.dispatchEvent(new Event("change", { bubbles: true }));
    else syncSharedDependencyControls();
  }
  styleElement("arcaStyleDialog")?.classList.add("hidden");
  if (typeof document !== "undefined") document.querySelector('[data-tab="style-maker"]')?.click();
  return true;
}

if (typeof globalThis !== "undefined") globalThis.setSharedDependencyReferenceFromArca = setSharedDependencyReferenceFromArca;

function syncSharedDependencyControls() {
  const active = styleElement("weightMode")?.value === "shared_dependency";
  const state = sharedDependencyControlsState(styleElement("weightMode")?.value);
  styleElement("sharedDependencySettings")?.classList.toggle("hidden", !active);
  const count = styleElement("styleArtistCount");
  if (count) count.disabled = state.countDisabled || styleState.pending;
  const countStatus = styleElement("sharedDependencyCountStatus");
  if (countStatus) {
    countStatus.classList.toggle("hidden", !active);
    countStatus.textContent = state.countLabel;
  }
  renderSharedDependencyRatioSummary();
  renderSharedDependencyReferenceSummary();
  ["sharedStyleArtistMin", "sharedStyleArtistMax"].forEach((id) => {
    const input = styleElement(id);
    if (input) input.disabled = active || styleState.pending;
  });
  return active;
}

function readStyleOptions() {
  const mode = styleElement("weightMode")?.value || "balanced";
  const count = Number(styleElement("styleArtistCount")?.value);
  const minWeight = Number(styleElement("styleMinWeight")?.value);
  const maxWeight = Number(styleElement("styleMaxWeight")?.value);
  const sharedArtistMin = Number(styleElement("sharedStyleArtistMin")?.value || 0);
  const sharedArtistMax = Number(styleElement("sharedStyleArtistMax")?.value || 0);
  if (mode !== "shared_dependency" && (!Number.isInteger(count) || count < 1)) throw new Error("작가 수는 1 이상의 정수여야 합니다.");
  if (![minWeight, maxWeight].every(Number.isFinite) || minWeight <= 0 || minWeight > maxWeight) {
    throw new Error("전체 가중치 범위를 확인하세요.");
  }
  if (
    !Number.isInteger(sharedArtistMin)
    || !Number.isInteger(sharedArtistMax)
    || sharedArtistMin < 0
    || sharedArtistMax < 0
    || sharedArtistMax > 50
  ) {
    throw new Error("공유 그림체 작가 인원은 0부터 50 사이의 정수여야 합니다.");
  }
  if (sharedArtistMin > sharedArtistMax && mode !== "shared_dependency") {
    throw new Error("공유 그림체 작가 최소 인원은 최대 인원보다 클 수 없습니다.");
  }
  if (sharedArtistMin > count && mode !== "shared_dependency") {
    throw new Error("공유 그림체 작가 최소 인원은 전체 작가 수보다 클 수 없습니다.");
  }
  const fixedArtistCount = fixedStyleArtistEntries(styleState.artists).length;
  if (mode !== "shared_dependency" && fixedArtistCount > count) {
    throw new Error(`고정 작가 ${fixedArtistCount}명이 전체 작가 수 ${count}명보다 많습니다.`);
  }
  if (sharedArtistMin > count - fixedArtistCount && mode !== "shared_dependency") {
    throw new Error("공유 그림체 작가 최소 인원은 고정 작가를 제외한 남은 자리보다 클 수 없습니다.");
  }
  const ratingTagRules = validateRatingTagRules(styleState.ratingTagRules);
  const ratingExcludeTags = validateRatingExcludeTags(styleState.ratingExcludeTags);
  const taggedArtistCount = ratingTagRuleCount(ratingTagRules);
  if (fixedArtistCount + sharedArtistMin + taggedArtistCount > count && mode !== "shared_dependency") {
    throw new Error("고정 작가, 태그 지정 인원, 공유 작가 최소 인원의 합이 전체 작가 수를 넘습니다.");
  }

  const dependencyRatios = {
    fixed: Number(styleElement("sharedDependencyFixedRatio")?.value || 0),
    reference: Number(styleElement("sharedDependencyReferenceRatio")?.value || 0),
    rated: Number(styleElement("sharedDependencyRatedRatio")?.value || 0),
    other_shared: Number(styleElement("sharedDependencyOtherRatio")?.value || 0),
  };
  const dependencyArtistPolicy = normalizeSharedDependencyArtistPolicy(
    styleElement("sharedDependencyArtistPolicy")?.value || styleState.sharedDependencyArtistPolicy,
  );
  if (mode === "shared_dependency") {
    normalizeSharedDependencyRatios(dependencyRatios);
  }
  return {
    count,
    scores: normalizeSelectedScores(styleState.allowedScores),
    weight_mode: mode,
    min_weight: minWeight,
    max_weight: maxWeight,
    prefer_high_scores: Boolean(styleElement("preferHighScores")?.checked),
    ranges: validateCustomRanges(),
    weight_profile: mode === "profile" ? styleState.weightProfile : undefined,
    shared_artist_min: sharedArtistMin,
    shared_artist_max: sharedArtistMax,
    shared_dependency_source_ratios: dependencyRatios,
    shared_dependency_artist_policy: dependencyArtistPolicy,
    rating_tag_rules: ratingTagRules,
    rating_exclude_tags: ratingExcludeTags,
  };
}

async function loadStyleArtists(reroll = "all") {
  let payload;
  try {
    showStyleStatus("그림체를 구성하는 중입니다...");
    payload = buildStyleRequestPayload(readStyleOptions(), styleState.artists, reroll);
    payload = applySharedDependencyReference(
      payload,
      reroll,
      styleElement("weightMode")?.value,
      styleState.sharedDependencyReferenceId,
      styleState.sharedDependencyReferenceMode,
    );
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
        if (data.shared_dependency_reference_id !== undefined) {
          styleState.sharedDependencyReferenceId = data.shared_dependency_reference_id;
          styleState.sharedDependencyReference = data.shared_dependency_reference || null;
          if (data.shared_dependency_reference_mode === "fixed" || data.shared_dependency_reference_mode === "random") {
            styleState.sharedDependencyReferenceMode = data.shared_dependency_reference_mode;
          }
          styleState.sharedDependencyArtistPolicy = normalizeSharedDependencyArtistPolicy(
            data.shared_dependency_artist_policy,
          );
          const artistPolicy = styleElement("sharedDependencyArtistPolicy");
          if (artistPolicy) artistPolicy.value = styleState.sharedDependencyArtistPolicy;
          styleState.sharedDependencyScale = data.shared_dependency_scale ?? data.shared_dependency_reference?.scale ?? null;
          styleState.sharedDependencyCfgRescale = data.shared_dependency_cfg_rescale ?? data.shared_dependency_reference?.cfg_rescale ?? null;
        }
        const preserveOrder = ["profile", "shared_dependency"].includes(styleElement("weightMode")?.value);
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

function renderArtistPromptPreview(prompt) {
  const normalized = typeof prompt === "string" ? prompt.trim() : "";
  const preview = styleElement("artistPromptPreview");
  if (preview) preview.value = normalized;
  renderPromptTokens(styleElement("artistPromptTokens"), normalized, "artist");
  return normalized;
}

function updateArtistPrompt() {
  const promptOptions = styleElement("weightMode")?.value === "profile"
    ? { profile: styleState.weightProfile }
    : {};
  const prompt = chooseArtistsForPrompt(styleState.artists, Math.random, promptOptions)
    .map((item) => `${formatStyleWeight(item.weight)}::artist:${formatArtistPromptTag(item.artist)}::`)
    .join(", ");
  return renderArtistPromptPreview(prompt);
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
  const removed = styleState.artists[index];
  if (removed) styleState.selectedFixedArtistNames.delete(removed.artist);
  styleState.artists.splice(index, 1);
  renderWeightGraph();
  renderRatedArtistSelect();
}

function swapStyleArtists(a, b) {
  if (a === b || !styleState.artists[a] || !styleState.artists[b]) return;
  [styleState.artists[a], styleState.artists[b]] = [styleState.artists[b], styleState.artists[a]];
  renderWeightGraph();
}

function sortFixedArtistEntriesForTable(entries, mode) {
  if (!["asc", "desc"].includes(mode)) return [...entries];
  const factor = mode === "asc" ? 1 : -1;
  return [...entries].sort((left, right) => (
    factor * (Number(left.artist.weight) - Number(right.artist.weight))
    || left.index - right.index
  ));
}

function updateWeightTableSortHeaders() {
  const labels = {
    default: { icon: "↑↓", label: "가중치 정렬: 원래 순서" },
    asc: { icon: "↑", label: "가중치 정렬: 오름차순" },
    desc: { icon: "↓", label: "가중치 정렬: 내림차순" },
  };
  const current = labels[styleState.weightTableSortMode] || labels.default;
  document.querySelectorAll("[data-weight-table-sort]").forEach((button) => {
    const icon = button.querySelector("[data-weight-sort-icon]");
    if (icon) icon.textContent = current.icon;
    button.setAttribute("aria-label", current.label);
    button.dataset.sortMode = styleState.weightTableSortMode;
  });
}

function cycleWeightTableSort() {
  const next = { default: "asc", asc: "desc", desc: "default" };
  styleState.weightTableSortMode = next[styleState.weightTableSortMode] || "default";
  renderStyleArtistList();
}

function renderStyleArtistListTarget(list) {
  list.replaceChildren();
  const entries = sortFixedArtistEntriesForTable(
    fixedStyleArtistEntries(styleState.artists),
    styleState.weightTableSortMode,
  );
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "style-artist-list-empty";
    empty.textContent = "고정으로 추가한 작가가 없습니다.";
    list.append(empty);
    return;
  }
  entries.forEach(({ artist: item, index, slot, stackIndex }) => {
    const row = document.createElement("div");
    row.className = "style-artist-row";

    const position = document.createElement("input");
    position.type = "number";
    position.min = "0";
    position.max = String(styleSlotCount());
    position.value = String(normalizeFixedArtistSlot(item, index + 1));
    position.title = "순서";
    position.setAttribute("aria-label", `${item.artist} 순서`);
    position.addEventListener("change", () => {
      styleState.artists = moveStyleArtistToPosition(styleState.artists, index, position.value, styleSlotCount());
      renderWeightGraph();
    });

    const name = document.createElement("input");
    name.type = "text";
    name.value = item.artist;
    name.title = "작가명";
    name.setAttribute("aria-label", `${item.artist} 작가명`);
    name.addEventListener("change", () => {
      styleState.artists = updateStyleArtistAtIndex(styleState.artists, index, { artist: name.value });
      renderWeightGraph();
      renderRatedArtistSelect();
    });

    const weight = document.createElement("input");
    weight.type = "number";
    weight.min = String(styleNumber("styleMinWeight", 0.1));
    weight.max = String(styleNumber("styleMaxWeight", 2.3));
    weight.step = "0.01";
    weight.value = Number(item.weight).toFixed(2);
    weight.title = "가중치";
    weight.setAttribute("aria-label", `${item.artist} 가중치`);
    weight.addEventListener("change", () => {
      const nextWeight = clampStyleWeight(weight.value);
      styleState.artists = updateStyleArtistAtIndex(styleState.artists, index, { weight: nextWeight });
      renderWeightGraph();
    });

    const randomWeight = document.createElement("label");
    randomWeight.className = "style-artist-random-weight";
    const randomWeightInput = document.createElement("input");
    randomWeightInput.type = "checkbox";
    randomWeightInput.checked = item.random_weight === true;
    randomWeightInput.setAttribute("aria-label", `${item.artist} 가중치 랜덤`);
    randomWeightInput.addEventListener("change", () => {
      styleState.artists = updateStyleArtistAtIndex(styleState.artists, index, { random_weight: randomWeightInput.checked });
      renderWeightGraph();
    });
    const randomWeightText = document.createElement("span");
    randomWeightText.textContent = "랜덤";
    randomWeight.append(randomWeightInput, randomWeightText);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button danger-button";
    remove.title = "작가 삭제";
    remove.setAttribute("aria-label", `${item.artist} 삭제`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeStyleArtist(index));

    row.append(position, name, weight, randomWeight, remove);
    list.append(row);
  });
}

function renderStyleArtistList() {
  ["styleArtistList", "weightTableArtistList"].forEach((id) => {
    const list = styleElement(id);
    if (list) renderStyleArtistListTarget(list);
  });
  updateWeightTableSortHeaders();
}

function openWeightTableModal() {
  styleElement("weightTableModal")?.classList.remove("hidden");
  renderStyleArtistList();
  renderRatedArtistSelect();
}

function closeWeightTableModal() {
  hideStyleArtistAutocomplete();
  styleElement("weightTableModal")?.classList.add("hidden");
}

function fixedArtistOverlayCoordinates(indexOrSlot, weight, total, min, max) {
  const slotInfo = typeof indexOrSlot === "object" && indexOrSlot !== null ? indexOrSlot : null;
  const slotCount = Math.max(1, Math.trunc(Number(total)));
  const normalizedSlot = slotInfo ? normalizeFixedArtistSlot(slotInfo, 1) : null;
  const slot = normalizedSlot > 0 ? Math.min(slotCount, normalizedSlot) : null;
  const plotLeft = 58;
  const plotRight = 24;
  const plotWidth = 900 - plotLeft - plotRight;
  const ratioX = slot
    ? (plotLeft + (((slot - 1) / Math.max(1, slotCount - 1)) * plotWidth)) / 900
    : (slotInfo ? 0.5 : (slotCount <= 1 ? 0.5 : indexOrSlot / (slotCount - 1)));
  const ratioY = max > min ? (clampStyleWeight(weight) - min) / (max - min) : 0.5;
  const left = slot
    ? Math.min(100, Math.max(0, Number((ratioX * 100).toFixed(2))))
    : Math.min(92, Math.max(8, Number((ratioX * 100).toFixed(2))));
  const baseBottom = ratioY * 68 + 8;
  const stackIndex = slotInfo ? Number(slotInfo.stackIndex || 0) : 0;
  const stackDirection = baseBottom < 42 ? 1 : -1;
  const stackOffset = stackIndex * 13 * stackDirection;
  const bottom = Math.min(82, Math.max(8, Number((baseBottom + stackOffset).toFixed(2))));
  return {
    left,
    bottom,
    xOffset: left <= 16 ? "0%" : (left >= 84 ? "-100%" : "-50%"),
  };
}

function fixedArtistCardSpan(left) {
  const width = 34;
  if (left <= 16) return [left, left + width];
  if (left >= 84) return [left - width, left];
  return [left - (width / 2), left + (width / 2)];
}

function fixedArtistSpansOverlap(first, second) {
  return first[0] < second[1] && second[0] < first[1];
}

function styleSlotCount() {
  return Math.max(1, Math.trunc(styleNumber("styleArtistCount", Math.max(1, styleState.artists.length))));
}

function graphInsertionPositionForEvent(graph, event) {
  const svg = graph.querySelector(".weight-profile-svg");
  if (!svg) return graphInsertionPositionFromRatio(0, styleSlotCount());
  const rect = svg.getBoundingClientRect();
  const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * 900;
  const plotRatio = (svgX - 58) / (900 - 58 - 24);
  return graphInsertionPositionFromRatio(plotRatio, styleSlotCount());
}

function fixedArtistDropLinePercent(position, artistCount) {
  return fixedArtistOverlayCoordinates({ slot: position, stackIndex: 0 }, 1, artistCount, 0, 2).left;
}

function fixedArtistGraphLeftPx(graph, leftPercent) {
  const svg = graph.querySelector(".weight-profile-svg");
  if (!svg) return null;
  const graphRect = graph.getBoundingClientRect();
  const svgRect = svg.getBoundingClientRect();
  return Number((svgRect.left - graphRect.left + (svgRect.width * leftPercent / 100)).toFixed(2));
}

function updateFixedArtistDropIndicator(graph, event) {
  const position = graphInsertionPositionForEvent(graph, event);
  let indicator = graph.querySelector(".weight-fixed-drop-indicator");
  if (!indicator) {
    indicator = document.createElement("div");
    indicator.className = "weight-fixed-drop-indicator";
    const label = document.createElement("span");
    indicator.append(label);
    graph.append(indicator);
  }
  const leftPercent = fixedArtistDropLinePercent(position, styleSlotCount());
  const leftPx = fixedArtistGraphLeftPx(graph, leftPercent);
  indicator.style.left = leftPx === null ? `${leftPercent}%` : `${leftPx}px`;
  indicator.querySelector("span").textContent = `${position}번 위치`;
  indicator.classList.add("active");
  return position;
}

function hideFixedArtistDropIndicator(graph) {
  graph.querySelector(".weight-fixed-drop-indicator")?.classList.remove("active");
}

function fixedArtistDragIndexes(sourceIndex) {
  const source = styleState.artists[sourceIndex];
  if (!source) return [];
  if (!styleState.selectedFixedArtistNames.has(source.artist)) return [sourceIndex];
  const selected = fixedStyleArtistEntries(styleState.artists)
    .filter(({ artist }) => styleState.selectedFixedArtistNames.has(artist.artist))
    .map(({ index }) => index);
  return selected.length ? selected : [sourceIndex];
}

function moveFixedArtistByGraphDrop(graph, event) {
  if (![...event.dataTransfer.types].some((type) => type === "application/x-fixed-style-artist" || type === "application/x-fixed-style-artists")) return;
  event.preventDefault();
  hideFixedArtistDropIndicator(graph);
  let sourceIndexes = [];
  try {
    sourceIndexes = JSON.parse(event.dataTransfer.getData("application/x-fixed-style-artists") || "[]");
  } catch (_) {
    sourceIndexes = [];
  }
  if (!sourceIndexes.length) sourceIndexes = [Number(event.dataTransfer.getData("application/x-fixed-style-artist"))];
  const targetPosition = graphInsertionPositionForEvent(graph, event);
  styleState.artists = moveSelectedArtistsToPosition(styleState.artists, sourceIndexes, targetPosition, styleSlotCount());
  renderWeightGraph();
}

function renderWeightGraphFixedArtistOverlays(graph) {
  const entries = fixedArtistSlotEntries(styleState.artists);
  const fixedNames = new Set(entries.map(({ artist }) => artist.artist));
  styleState.selectedFixedArtistNames.forEach((artist) => {
    if (!fixedNames.has(artist)) styleState.selectedFixedArtistNames.delete(artist);
  });
  if (!entries.length) return;
  const min = styleNumber("styleMinWeight", 0.1);
  const max = styleNumber("styleMaxWeight", 2.3);
  const slotCount = styleSlotCount();
  graph.ondragover = (event) => {
    if (![...event.dataTransfer.types].some((type) => type === "application/x-fixed-style-artist" || type === "application/x-fixed-style-artists")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    updateFixedArtistDropIndicator(graph, event);
  };
  graph.ondrop = (event) => moveFixedArtistByGraphDrop(graph, event);
  graph.ondragleave = (event) => {
    if (!graph.contains(event.relatedTarget)) hideFixedArtistDropIndicator(graph);
  };

  const occupiedLanes = [];
  const overlayEntries = entries.map((entry) => {
    const coordinates = fixedArtistOverlayCoordinates({ slot: entry.slot, stackIndex: 0 }, entry.artist.weight, slotCount, min, max);
    const span = fixedArtistCardSpan(coordinates.left);
    let laneIndex = occupiedLanes.findIndex((laneSpans) => laneSpans.every((usedSpan) => !fixedArtistSpansOverlap(usedSpan, span)));
    if (laneIndex < 0) laneIndex = occupiedLanes.length;
    if (!occupiedLanes[laneIndex]) occupiedLanes[laneIndex] = [];
    occupiedLanes[laneIndex].push(span);
    return { ...entry, visualStackIndex: Math.max(entry.stackIndex, laneIndex) };
  });

  overlayEntries.forEach(({ artist: item, index, slot, stackIndex, visualStackIndex }) => {
    const card = document.createElement("article");
    const { left, bottom, xOffset } = fixedArtistOverlayCoordinates({ slot, stackIndex: visualStackIndex ?? stackIndex }, item.weight, slotCount, min, max);
    card.className = "weight-fixed-artist-card";
    card.classList.toggle("selected", styleState.selectedFixedArtistNames.has(item.artist));
    card.draggable = !styleState.pending;
    card.dataset.index = String(index);
    card.dataset.slot = String(slot);
    const leftPx = fixedArtistGraphLeftPx(graph, left);
    card.style.left = leftPx === null ? `${left}%` : `${leftPx}px`;
    card.style.bottom = `${bottom}%`;
    card.style.setProperty("--fixed-card-x-offset", xOffset);

    const select = document.createElement("input");
    select.type = "checkbox";
    select.className = "weight-fixed-artist-select";
    select.checked = styleState.selectedFixedArtistNames.has(item.artist);
    select.title = "묶음 이동 선택";
    select.setAttribute("aria-label", `${item.artist} 묶음 이동 선택`);
    select.addEventListener("change", () => {
      if (select.checked) styleState.selectedFixedArtistNames.add(item.artist);
      else styleState.selectedFixedArtistNames.delete(item.artist);
      renderWeightGraph();
    });

    const grip = document.createElement("span");
    grip.className = "weight-fixed-artist-grip";
    grip.textContent = slot === 0 ? "랜덤" : `#${slot}`;
    grip.title = "드래그해서 순서 변경";

    const name = document.createElement("input");
    name.type = "text";
    name.value = item.artist;
    name.title = "작가명";
    name.setAttribute("aria-label", `${item.artist} 작가명`);
    name.addEventListener("change", () => {
      styleState.selectedFixedArtistNames.delete(item.artist);
      if (name.value.trim()) styleState.selectedFixedArtistNames.add(name.value.trim());
      styleState.artists = updateStyleArtistAtIndex(styleState.artists, index, { artist: name.value });
      renderWeightGraph();
      renderRatedArtistSelect();
    });

    const position = document.createElement("input");
    position.type = "number";
    position.min = "0";
    position.max = String(slotCount);
    position.value = String(slot);
    position.title = "순서";
    position.setAttribute("aria-label", `${item.artist} 순서`);
    position.addEventListener("change", () => {
      styleState.artists = moveSelectedArtistsToPosition(styleState.artists, [index], position.value, slotCount);
      renderWeightGraph();
    });

    const weight = document.createElement("input");
    weight.type = "number";
    weight.min = String(min);
    weight.max = String(max);
    weight.step = "0.01";
    weight.value = Number(item.weight).toFixed(2);
    weight.title = "가중치";
    weight.setAttribute("aria-label", `${item.artist} 가중치`);
    weight.addEventListener("change", () => {
      const nextWeight = clampStyleWeight(weight.value);
      styleState.artists = updateStyleArtistAtIndex(styleState.artists, index, { weight: nextWeight });
      renderWeightGraph();
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button small danger-button";
    remove.title = "작가 삭제";
    remove.setAttribute("aria-label", `${item.artist} 삭제`);
    remove.textContent = "×";
    remove.addEventListener("click", () => removeStyleArtist(index));

    card.addEventListener("dragstart", (event) => {
      if (event.target.closest("input, button") || styleState.pending) {
        event.preventDefault();
        return;
      }
      event.dataTransfer.effectAllowed = "move";
      const indexes = fixedArtistDragIndexes(index);
      event.dataTransfer.setData("application/x-fixed-style-artist", String(index));
      event.dataTransfer.setData("application/x-fixed-style-artists", JSON.stringify(indexes));
      card.classList.add("dragging");
      card.dataset.dragCount = String(indexes.length);
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      hideFixedArtistDropIndicator(graph);
    });
    card.append(select, grip, name, position, weight, remove);
    graph.append(card);
  });
}

function renderWeightGraph() {
  const graph = styleElement("weightGraph");
  renderStyleArtistList();
  if (!graph) {
    saveFixedStyleArtists(styleState.artists);
    return;
  }
  graph.replaceChildren();
  const profileMode = styleElement("weightMode")?.value === "profile";
  graph.classList.toggle("profile-mode", profileMode);
  if (profileMode) {
    renderWeightProfileGraph(graph);
    renderWeightGraphFixedArtistOverlays(graph);
    renderWeightProfilePreview();
    updateArtistPrompt();
    refreshPromptPresetsForArtists();
    saveFixedStyleArtists(styleState.artists);
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
      saveFixedStyleArtists(styleState.artists);
    };
    slider.addEventListener("input", () => syncWeight(slider.value));
    number.addEventListener("change", () => syncWeight(number.value));

    const label = document.createElement("strong");
    label.className = "weight-artist-label";
    label.title = item.artist;
    label.textContent = item.artist;

    const score = document.createElement("span");
    score.className = "weight-score";
    score.textContent = item.score ? `평점 ${item.score}` : `#${index + 1}`;

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
  renderWeightGraphFixedArtistOverlays(graph);
  updateArtistPrompt();
  refreshPromptPresetsForArtists();
  saveFixedStyleArtists(styleState.artists);
}

function currentStyleArtistFragment(value) {
  return String(value || "").split(/[,\n;]+/).at(-1)?.trim() || "";
}

function replaceCurrentStyleArtistFragment(value, artist) {
  const text = String(value || "");
  const match = text.match(/^(.*?)([^,\n;]*)$/s);
  const prefix = match?.[1] || "";
  return `${prefix}${artist}`;
}

function styleArtistControlIds(context = "main") {
  return context === "modal"
    ? {
      search: "weightTableArtistSearch", autocomplete: "weightTableArtistAutocomplete",
      select: "weightTableArtistSelect", position: "weightTableArtistPosition",
      weight: "weightTableArtistWeight", randomWeight: "weightTableArtistRandomWeight",
    }
    : {
      search: "styleArtistSearch", autocomplete: "styleArtistAutocomplete",
      select: "styleArtistSelect", position: "styleArtistPosition",
      weight: "styleArtistWeight", randomWeight: "styleArtistRandomWeight",
    };
}

function hideStyleArtistAutocomplete() {
  styleElement("styleArtistAutocomplete")?.classList.add("hidden");
  styleElement("weightTableArtistAutocomplete")?.classList.add("hidden");
  styleState.styleArtistAutocompleteRequestToken += 1;
  styleState.styleArtistAutocompleteItems = [];
  styleState.styleArtistAutocompleteIndex = -1;
}

function setStyleArtistAutocompleteIndex(index) {
  const box = styleElement(styleArtistControlIds(styleState.styleArtistAutocompleteContext).autocomplete);
  if (!box || !styleState.styleArtistAutocompleteItems.length) return;
  styleState.styleArtistAutocompleteIndex = (index + styleState.styleArtistAutocompleteItems.length) % styleState.styleArtistAutocompleteItems.length;
  box.querySelectorAll("button").forEach((button, buttonIndex) => {
    button.classList.toggle("active", buttonIndex === styleState.styleArtistAutocompleteIndex);
  });
}

function applyStyleArtistAutocomplete(index = styleState.styleArtistAutocompleteIndex) {
  const ids = styleArtistControlIds(styleState.styleArtistAutocompleteContext);
  const input = styleElement(ids.search);
  const item = styleState.styleArtistAutocompleteItems[index];
  if (!input || !item) return;
  input.value = replaceCurrentStyleArtistFragment(input.value, item.name);
  hideStyleArtistAutocomplete();
  input.focus();
  renderRatedArtistSelect();
}

async function updateStyleArtistAutocomplete(context = "main") {
  styleState.styleArtistAutocompleteContext = context;
  const ids = styleArtistControlIds(context);
  const input = styleElement(ids.search);
  const box = styleElement(ids.autocomplete);
  if (!input || !box) return;
  const query = currentStyleArtistFragment(input.value);
  if (query.length < 2) {
    hideStyleArtistAutocomplete();
    return;
  }
  const requestToken = ++styleState.styleArtistAutocompleteRequestToken;
  try {
    const items = await apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}&category=1`);
    if (requestToken !== styleState.styleArtistAutocompleteRequestToken) return;
    styleState.styleArtistAutocompleteItems = Array.isArray(items) ? items : [];
    styleState.styleArtistAutocompleteIndex = -1;
    box.replaceChildren();
    styleState.styleArtistAutocompleteItems.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = item.name;
      const count = document.createElement("span");
      count.textContent = String(item.post_count || 0);
      button.append(name, count);
      button.addEventListener("mouseenter", () => setStyleArtistAutocompleteIndex(index));
      button.addEventListener("click", () => applyStyleArtistAutocomplete(index));
      box.append(button);
    });
    box.classList.toggle("hidden", !styleState.styleArtistAutocompleteItems.length);
  } catch {
    hideStyleArtistAutocomplete();
  }
}

function handleStyleArtistAutocompleteKeydown(event, context = "main") {
  styleState.styleArtistAutocompleteContext = context;
  const box = styleElement(styleArtistControlIds(context).autocomplete);
  if (!box || box.classList.contains("hidden") || !styleState.styleArtistAutocompleteItems.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setStyleArtistAutocompleteIndex(styleState.styleArtistAutocompleteIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setStyleArtistAutocompleteIndex(styleState.styleArtistAutocompleteIndex <= 0 ? styleState.styleArtistAutocompleteItems.length - 1 : styleState.styleArtistAutocompleteIndex - 1);
  } else if (event.key === "Enter" && styleState.styleArtistAutocompleteIndex >= 0) {
    event.preventDefault();
    applyStyleArtistAutocomplete();
  } else if (event.key === "Escape") {
    hideStyleArtistAutocomplete();
  }
}

function hidePromptTagAutocomplete() {
  styleState.promptTagAutocompleteBox?.classList.add("hidden");
  styleState.promptTagAutocompleteRequestToken += 1;
  styleState.promptTagAutocompleteItems = [];
  styleState.promptTagAutocompleteIndex = -1;
  styleState.promptTagAutocompleteInput = null;
  styleState.promptTagAutocompleteBox = null;
}

function setPromptTagAutocompleteIndex(index) {
  const box = styleState.promptTagAutocompleteBox;
  if (!box || !styleState.promptTagAutocompleteItems.length) return;
  styleState.promptTagAutocompleteIndex = (index + styleState.promptTagAutocompleteItems.length) % styleState.promptTagAutocompleteItems.length;
  box.querySelectorAll("button").forEach((button, buttonIndex) => {
    button.classList.toggle("active", buttonIndex === styleState.promptTagAutocompleteIndex);
  });
}

function applyPromptTagAutocomplete(index = styleState.promptTagAutocompleteIndex) {
  const input = styleState.promptTagAutocompleteInput;
  const item = styleState.promptTagAutocompleteItems[index];
  if (!input || !item) return;
  const result = replaceCurrentPromptTagFragment(
    input.value,
    formatPromptAutocompleteTag(item, input.dataset.prefixArtist !== "false"),
    input.selectionStart,
  );
  input.value = result.value;
  input.setSelectionRange(result.cursor, result.cursor);
  hidePromptTagAutocomplete();
  input.focus();
  input.dispatchEvent(new Event("input", { bubbles: true }));
  clearTimeout(styleState.promptTagAutocompleteTimer);
  styleState.promptTagAutocompleteTimer = null;
}

async function updatePromptTagAutocomplete(input) {
  const box = input?.closest(".field")?.querySelector(".prompt-tag-autocomplete");
  if (!input || !box) return;
  const fragment = currentPromptTagFragment(input.value, input.selectionStart);
  const query = fragment.replace(/^artist:/i, "");
  if (query.length < 2) {
    hidePromptTagAutocomplete();
    return;
  }
  if (styleState.promptTagAutocompleteBox && styleState.promptTagAutocompleteBox !== box) {
    styleState.promptTagAutocompleteBox.classList.add("hidden");
  }
  const requestToken = ++styleState.promptTagAutocompleteRequestToken;
  styleState.promptTagAutocompleteInput = input;
  styleState.promptTagAutocompleteBox = box;
  try {
    const items = await apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}`);
    if (requestToken !== styleState.promptTagAutocompleteRequestToken || styleState.promptTagAutocompleteInput !== input) return;
    styleState.promptTagAutocompleteItems = Array.isArray(items) ? items : [];
    styleState.promptTagAutocompleteIndex = -1;
    box.replaceChildren();
    styleState.promptTagAutocompleteItems.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      const name = document.createElement("span");
      name.textContent = item.name;
      const detail = document.createElement("span");
      detail.textContent = `${item.category_name || "other"} · ${item.post_count || 0}`;
      button.append(name, detail);
      button.addEventListener("mouseenter", () => setPromptTagAutocompleteIndex(index));
      button.addEventListener("click", () => applyPromptTagAutocomplete(index));
      box.append(button);
    });
    box.classList.toggle("hidden", !styleState.promptTagAutocompleteItems.length);
  } catch {
    if (requestToken === styleState.promptTagAutocompleteRequestToken) hidePromptTagAutocomplete();
  }
}

function handlePromptTagAutocompleteKeydown(event) {
  const box = styleState.promptTagAutocompleteBox;
  if (styleState.promptTagAutocompleteInput !== event.currentTarget || !box || box.classList.contains("hidden") || !styleState.promptTagAutocompleteItems.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    setPromptTagAutocompleteIndex(styleState.promptTagAutocompleteIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setPromptTagAutocompleteIndex(styleState.promptTagAutocompleteIndex <= 0 ? styleState.promptTagAutocompleteItems.length - 1 : styleState.promptTagAutocompleteIndex - 1);
  } else if (event.key === "Enter" && styleState.promptTagAutocompleteIndex >= 0) {
    event.preventDefault();
    applyPromptTagAutocomplete();
  } else if (event.key === "Escape") {
    hidePromptTagAutocomplete();
  }
}

function bindPromptTagAutocomplete(input) {
  if (!input || input.dataset.tagAutocompleteBound === "true") return;
  input.dataset.tagAutocompleteBound = "true";
  input.addEventListener("input", () => {
    clearTimeout(styleState.promptTagAutocompleteTimer);
    styleState.promptTagAutocompleteTimer = setTimeout(() => updatePromptTagAutocomplete(input), 220);
  });
  input.addEventListener("keydown", handlePromptTagAutocompleteKeydown);
}

function filteredRatedArtists(searchId = "styleArtistSearch") {
  const query = (styleElement(searchId)?.value || "").trim().toLowerCase();
  return styleState.ratedArtists.filter((item) => !query || item.artist.toLowerCase().includes(query));
}

function renderRatedArtistSelectTarget(context) {
  const ids = styleArtistControlIds(context);
  const select = styleElement(ids.select);
  if (!select) return;
  const selectedArtists = new Set(styleState.artists.map((item) => item.artist));
  const options = filteredRatedArtists(ids.search).filter((item) => !selectedArtists.has(item.artist));
  select.replaceChildren();
  if (!options.length) {
    select.add(new Option("추가할 작가가 없습니다", ""));
    return;
  }
  options.forEach((item) => select.add(new Option(`${item.artist} (평점 ${item.score})`, item.artist)));
}

function renderRatedArtistSelect() {
  renderRatedArtistSelectTarget("main");
  renderRatedArtistSelectTarget("modal");
}

function addStyleArtist(context = "main") {
  const ids = styleArtistControlIds(context);
  const input = styleElement(ids.search);
  const selectedArtist = styleElement(ids.select)?.value || "";
  const entries = parseStyleArtistEntries(input?.value || selectedArtist);
  if (!entries.length && selectedArtist) entries.push({ artist: selectedArtist });
  if (!entries.length) return;
  const beforeFixedCount = fixedStyleArtistEntries(styleState.artists).length;
  const positionText = styleElement(ids.position)?.value;
  const position = positionText === "0" ? 0 : Math.trunc(Number(positionText || styleState.artists.length + 1));
  const weight = clampStyleWeight(styleElement(ids.weight)?.value || 1);
  const randomWeight = Boolean(styleElement(ids.randomWeight)?.checked);
  const inserted = insertStyleArtistsAtPosition(styleState.artists, entries, { position, weight, randomWeight });
  try {
    styleState.artists = limitArtistsToTotalCount(
      inserted,
      Math.trunc(Number(styleElement("styleArtistCount")?.value || inserted.length)),
    );
  } catch (error) {
    showStyleStatus(error.message, "error");
    return;
  }
  const added = fixedStyleArtistEntries(styleState.artists).length - beforeFixedCount;
  if (input && added > 0) input.value = "";
  hideStyleArtistAutocomplete();
  renderWeightGraph();
  renderRatedArtistSelect();
  showStyleStatus(
    added ? `${added}명의 작가를 추가했습니다.` : "이미 들어간 작가입니다.",
    added ? "ok" : "",
  );
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
  input.autocomplete = "off";
  const autocomplete = document.createElement("div");
  autocomplete.className = "autocomplete prompt-tag-autocomplete hidden";
  const tokens = document.createElement("div");
  tokens.className = "prompt-token-surface";
  tokens.dataset.promptField = "character";
  tokens.setAttribute("aria-label", "캐릭터 프롬프트 토큰");
  input.addEventListener("input", persistAndRenderPromptControls);
  bindPromptTagAutocomplete(input);
  editor.append(input, autocomplete, tokens);
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "icon-button danger-button";
  remove.title = "캐릭터 프롬프트 삭제";
  remove.setAttribute("aria-label", "캐릭터 프롬프트 삭제");
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    if (styleState.promptTagAutocompleteInput === input) hidePromptTagAutocomplete();
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

function sharedDependencyParameterValue(value, minimum, maximum) {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= minimum && numeric <= maximum ? numeric : null;
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
  const inputScale = generationNumber("generationScale", 5);
  const inputCfgRescale = generationNumber("generationCfgRescale", 0);
  const sharedDependencyMode = styleElement("weightMode")?.value === "shared_dependency";
  const referenceScale = sharedDependencyParameterValue(styleState.sharedDependencyScale, 0, 10);
  const referenceCfgRescale = sharedDependencyParameterValue(styleState.sharedDependencyCfgRescale, 0, 1);
  const scale = sharedDependencyMode && referenceScale !== null ? referenceScale : inputScale;
  const cfgRescale = sharedDependencyMode && referenceCfgRescale !== null ? referenceCfgRescale : inputCfgRescale;
  if (![width, height].every((value) => Number.isInteger(value) && value > 0 && value % 64 === 0)) {
    throw new Error("너비와 높이는 64 단위의 양수여야 합니다.");
  }
  if (!Number.isInteger(steps) || steps < 1 || steps > 50) throw new Error("스텝은 1~50이어야 합니다.");
  if (scale < 0 || scale > 10 || cfgRescale < 0 || cfgRescale > 1) throw new Error("생성 수치 범위를 확인하세요.");
  const seedFixed = Boolean(styleElement("generationSeedFixed")?.checked);
  const seed = Number(styleElement("generationSeed")?.value);
  if (seedFixed && (!Number.isInteger(seed) || seed < 1 || seed > 4294967295)) throw new Error("고정 시드를 확인하세요.");
  const qualityPrompt = buildEffectivePromptText(styleElement("basePrompt")?.value, "base", "", styleState.promptGroups);
  const fixedPrompt = styleElement("fixedPrompt")?.value || "";
  const excludedQualityTags = styleState.excludedPromptTags
    .map((item) => String(item?.prompt || "").trim())
    .filter(Boolean);
  const payload = {
    request_id: requestId,
    weight_mode: styleElement("weightMode")?.value || "balanced",
    ...(sharedDependencyMode && styleState.sharedDependencyReferenceId
      ? {
          shared_dependency_reference_id: styleState.sharedDependencyReferenceId,
          shared_dependency_reference_mode: styleState.sharedDependencyReferenceMode,
          shared_dependency_artist_policy: normalizeSharedDependencyArtistPolicy(
            styleElement("sharedDependencyArtistPolicy")?.value || styleState.sharedDependencyArtistPolicy,
          ),
        }
      : {}),
    artists: chooseArtistsForPrompt(
      styleState.artists,
      Math.random,
      styleElement("weightMode")?.value === "profile" ? { profile: styleState.weightProfile } : {},
    )
      .map(({ artist, score, weight }) => ({ artist, score, weight })),
    base_prompt: combinePromptSections(qualityPrompt, fixedPrompt),
    quality_prompt: qualityPrompt,
    original_quality_prompt: combinePromptSections(qualityPrompt, ...excludedQualityTags),
    excluded_quality_tags: excludedQualityTags,
    fixed_prompt: fixedPrompt,
    negative_prompt: buildEffectivePromptText(styleElement("negativePrompt")?.value, "negative", "", styleState.promptGroups),
    character_prompts: readCharacterPrompts(),
    width,
    height,
    sampler: styleElement("generationSampler")?.value || "k_euler_ancestral",
    noise_schedule: styleElement("generationScheduler")?.value || "karras",
    steps,
    scale,
    cfg_rescale: cfgRescale,
    variety_plus: Boolean(styleElement("generationVarietyPlus")?.checked),
  };
  if (seedFixed) payload.seed = seed;
  return payload;
}

function opusFreeGenerationIssues({ width, height, steps }) {
  const issues = [];
  if (Number(steps) > OPUS_FREE_MAX_STEPS) {
    issues.push(`스텝 ${steps}: Opus 무료 기준인 ${OPUS_FREE_MAX_STEPS}스텝을 초과합니다.`);
  }
  const pixels = Number(width) * Number(height);
  if (Number.isFinite(pixels) && pixels > OPUS_FREE_MAX_PIXELS) {
    issues.push(`해상도 ${width}×${height}: ${pixels.toLocaleString("ko-KR")}픽셀로 1,048,576픽셀을 초과합니다.`);
  }
  return issues;
}

async function confirmGenerationAnlasRisk(mode) {
  const width = generationNumber("generationWidth", 832);
  const height = generationNumber("generationHeight", 1216);
  const steps = generationNumber("generationSteps", 28);
  const issues = opusFreeGenerationIssues({ width, height, steps });
  if (!issues.length) return true;
  const limitMode = styleElement("generationLimitMode")?.value || "count";
  const requestedCount = Math.max(1, Math.trunc(generationNumber("generationCount", 1)));
  const runDescription = mode === "continuous"
    ? (limitMode === "unlimited" ? "중지할 때까지 연속 생성" : `${requestedCount}장 연속 생성`)
    : "1장 생성";
  return globalThis.appDialog.confirm({
    title: "Anlas가 차감될 수 있습니다",
    message: `${runDescription} 요청이 Opus 무료 이미지 생성 기준을 벗어납니다. 그래도 생성할까요?`,
    details: [
      ...issues,
      "Opus 무료 기준: 한 번에 1장 · 베이스 이미지 없음 · 28스텝 이하 · 최대 1,048,576픽셀",
      "이 프로그램은 이미지를 한 번에 1장씩 요청합니다.",
    ],
    cancelLabel: "설정 다시 확인",
    confirmLabel: "Anlas 사용 가능성 확인 후 생성",
    tone: "warning",
  });
}

function normalizeRandomTargets(values, legacyMode = "weights") {
  if (!Array.isArray(values)) {
    return legacyMode === "artists_and_weights" ? ["artists", "weights"] : ["weights"];
  }
  return RANDOM_STYLE_TARGETS.filter((target) => values.includes(target));
}

function selectedRandomTargets() {
  if (typeof document === "undefined") return new Set(["weights"]);
  return new Set([...document.querySelectorAll("[data-random-target][aria-pressed='true']")]
    .map((button) => button.dataset.randomTarget)
    .filter((target) => RANDOM_STYLE_TARGETS.includes(target)));
}

function setRandomTargets(values, legacyMode = "weights") {
  const selected = new Set(normalizeRandomTargets(values, legacyMode));
  document.querySelectorAll("[data-random-target]").forEach((button) => {
    const active = selected.has(button.dataset.randomTarget);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  return selected;
}

function pickRandomPreset(presets, randomValue = Math.random()) {
  const items = Array.isArray(presets) ? presets : [];
  if (!items.length) return null;
  const numeric = Number(randomValue);
  const normalized = Number.isFinite(numeric) ? numeric : 0;
  const index = Math.min(items.length - 1, Math.max(0, Math.floor(normalized * items.length)));
  return items[index];
}

function setGenerationBusy(busy) {
  styleState.generating = busy;
  ["generateOne", "startContinuous"].forEach((id) => {
    const button = styleElement(id);
    if (button) button.disabled = busy || styleState.running;
  });
  syncGenerationRemote();
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

function normalizeStyleHistoryItem(item) {
  const value = item && typeof item === "object" ? item : {};
  let artists = Array.isArray(value.artists) ? value.artists : [];
  if (!artists.length && value.artist_prompt) artists = parseStyleArtistEntries(value.artist_prompt);
  artists = artists.map((entry) => {
    const artist = String(entry?.artist || "").trim();
    const weight = Number(entry?.weight);
    if (!artist) return null;
    return {
      ...entry,
      artist,
      weight: Number.isFinite(weight) && weight > 0 ? Number(weight.toFixed(2)) : 1,
      ...(entry?.fixed === true ? { fixed: true } : {}),
      ...(entry?.random_weight === true ? { random_weight: true } : {}),
    };
  }).filter(Boolean);
  const generation = value.generation_settings && typeof value.generation_settings === "object"
    ? { ...value.generation_settings }
    : {};
  const hasValue = (source, key) => source?.[key] !== undefined && source?.[key] !== null && source?.[key] !== "";
  ["width", "height", "steps", "scale", "cfg_rescale", "sampler", "variety_plus", "model", "seed"]
    .forEach((key) => {
      if (!hasValue(generation, key) && hasValue(value, key)) generation[key] = value[key];
    });
  if (!hasValue(generation, "scheduler")) {
    const scheduler = hasValue(generation, "noise_schedule")
      ? generation.noise_schedule
      : value.noise_schedule;
    if (scheduler !== undefined && scheduler !== null && scheduler !== "") generation.scheduler = scheduler;
  }
  if (!hasValue(generation, "resolution_preset") && hasValue(generation, "width") && hasValue(generation, "height")) {
    const resolution = `${generation.width}x${generation.height}`;
    generation.resolution_preset = ["832x1216", "1216x832", "1024x1024"].includes(resolution)
      ? resolution
      : "custom";
  }
  const qualityPrompt = String(value.quality_prompt || "").trim()
    ? value.quality_prompt
    : (value.base_prompt || "");
  return {
    ...value,
    id: Number(value.id),
    image_url: value.image_url || value.thumbnail_url || "",
    artists,
    base_prompt: qualityPrompt,
    fixed_prompt: value.fixed_prompt || "",
    negative_prompt: value.negative_prompt || "",
    character_prompts: Array.isArray(value.character_prompts)
      ? value.character_prompts.map((entry) => typeof entry === "string" ? entry : entry?.prompt || "").filter(Boolean)
      : [],
    generation_settings: generation,
  };
}

function styleHistoryPreviewMeta(item) {
  const normalized = normalizeStyleHistoryItem(item);
  const settings = normalized.generation_settings || {};
  const scheduler = settings.scheduler || settings.noise_schedule || "native";
  return `생성 #${normalized.id} · 작가 ${normalized.artists.length}명 · ${managerKnown(settings.width)}×${managerKnown(settings.height)} · ${managerKnown(settings.sampler)} / ${managerKnown(scheduler)} · ${managerKnown(settings.steps)} steps · CFG ${managerKnown(settings.scale)} · Rescale ${managerKnown(settings.cfg_rescale)} · Seed ${managerKnown(settings.seed)}`;
}

function styleHistoryArtistPrompt(item) {
  const value = item && typeof item === "object" ? item : {};
  const stored = typeof value.artist_prompt === "string" ? value.artist_prompt.trim() : "";
  if (stored) return stored;
  return (Array.isArray(value.artists) ? value.artists : [])
    .map((artist) => `${formatStyleWeight(artist.weight)}::artist:${formatArtistPromptTag(artist.artist)}::`)
    .join(", ");
}

function renderStyleHistorySelection(item) {
  const normalized = item ? normalizeStyleHistoryItem(item) : null;
  renderArtistPromptPreview(styleHistoryArtistPrompt(normalized));
  const target = styleElement("latestStyleResult");
  if (!target) return;
  target.replaceChildren();
  if (!item) {
    const placeholder = document.createElement("div");
    placeholder.className = "latest-result-placeholder";
    placeholder.textContent = "최근 생성 결과가 여기에 표시됩니다.";
    target.append(placeholder);
    return;
  }
  if (normalized.image_url) {
    const image = document.createElement("img");
    image.src = normalized.image_url;
    image.alt = `그림체 제작 히스토리 #${normalized.id}`;
    target.append(image);
  }
  const meta = document.createElement("div");
  meta.className = "latest-result-meta";
  meta.textContent = styleHistoryPreviewMeta(normalized);
  target.append(meta);
}

function renderStyleHistoryDetail(item) {
  const target = styleElement("styleHistoryDetail");
  if (!target) return;
  target.replaceChildren();
  if (!item) {
    const placeholder = document.createElement("div");
    placeholder.className = "latest-result-placeholder";
    placeholder.textContent = "생성 기록을 선택하면 자세히 볼 수 있습니다.";
    target.append(placeholder);
    return;
  }
  const normalized = normalizeStyleHistoryItem(item);
  const heading = document.createElement("h3");
  heading.textContent = `생성 #${normalized.id}`;
  const meta = document.createElement("p");
  meta.textContent = styleHistoryPreviewMeta(normalized);
  const actions = document.createElement("div");
  actions.className = "style-history-detail-actions";
  const load = document.createElement("button");
  load.type = "button";
  load.className = "primary";
  load.textContent = "설정 반영";
  load.title = "선택한 히스토리의 설정을 현재 그림체 제작에 반영";
  load.setAttribute("aria-label", "선택한 히스토리 설정 반영");
  load.addEventListener("click", () => applyStyleHistoryItem(normalized));
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.textContent = "확정 그림체로";
  confirm.title = "선택한 히스토리를 확정 그림체로 저장";
  confirm.setAttribute("aria-label", "선택한 히스토리를 확정 그림체로 저장");
  confirm.addEventListener("click", () => openConfirmedStyleModal(normalized, false, "generated"));
  actions.append(load, confirm);
  target.append(heading, meta, actions);
}

function renderStyleHistoryList() {
  const list = styleElement("styleHistoryList");
  if (!list) return;
  list.replaceChildren();
  if (!styleState.historyItems.length) {
    const empty = document.createElement("p");
    empty.className = "latest-result-placeholder";
    empty.textContent = "아직 생성한 그림체가 없습니다.";
    list.append(empty);
    renderStyleHistoryDetail(null);
    renderStyleHistorySelection(null);
    return;
  }
  styleState.historyItems.forEach((item) => {
    const card = document.createElement("article");
    card.className = "style-history-card";
    card.classList.toggle("selected", Number(item.id) === Number(styleState.historySelectedId));
    const select = document.createElement("button");
    select.type = "button";
    select.className = "style-history-card-select";
    select.classList.toggle("selected", Number(item.id) === Number(styleState.historySelectedId));
    select.setAttribute("aria-pressed", String(Number(item.id) === Number(styleState.historySelectedId)));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "style-history-card-delete";
    remove.setAttribute("aria-label", `생성 #${item.id} 삭제`);
    remove.title = `생성 #${item.id} 삭제`;
    remove.textContent = "×";
    const deleteFromCard = (event) => {
      event.preventDefault();
      event.stopPropagation();
      deleteStyleHistoryItem(item);
    };
    remove.addEventListener("click", deleteFromCard);
    if (item.image_url) {
      const image = document.createElement("img");
      image.src = item.thumbnail_url || item.image_url;
      image.alt = `생성 #${item.id}`;
      image.loading = "lazy";
      select.append(image);
    }
    const title = document.createElement("strong");
    title.textContent = `#${item.id}`;
    const info = document.createElement("small");
    info.textContent = `${Array.isArray(item.artists) ? item.artists.length : 0}명${item.confirmed ? " · 확정됨" : ""}`;
    select.append(title, info);
    select.addEventListener("click", () => {
      styleState.historySelectedId = item.id;
      renderStyleHistorySelection(item);
      renderStyleHistoryList();
      renderStyleHistoryDetail(item);
    });
    card.append(select, remove);
    list.append(card);
  });
  const selected = styleState.historyItems.find((item) => Number(item.id) === Number(styleState.historySelectedId))
    || styleState.historyItems[0];
  if (selected && Number(styleState.historySelectedId) !== Number(selected.id)) {
    styleState.historySelectedId = selected.id;
    renderStyleHistorySelection(selected);
    renderStyleHistoryDetail(selected);
  }
  if (selected && Number(styleState.historySelectedId) === Number(selected.id)) renderStyleHistorySelection(selected);
}

async function loadStyleHistory({ force = false } = {}) {
  if (!force && !styleState.historyDirty) return;
  const token = ++styleState.historyRequestToken;
  const status = styleElement("styleHistoryStatus");
  if (status) status.textContent = "히스토리를 불러오는 중...";
  try {
    const items = await apiFetch("/api/style-manager/generated");
    if (token !== styleState.historyRequestToken) return;
    styleState.historyItems = Array.isArray(items) ? items : [];
    styleState.historyDirty = false;
    if (!styleState.historyItems.some((item) => Number(item.id) === Number(styleState.historySelectedId))) {
      styleState.historySelectedId = styleState.historyItems[0]?.id ?? null;
    }
    renderStyleHistoryList();
    const selected = styleState.historyItems.find((item) => Number(item.id) === Number(styleState.historySelectedId));
    renderStyleHistoryDetail(selected);
    renderStyleHistorySelection(selected);
    if (status) status.textContent = `${styleState.historyItems.length}개 기록`;
  } catch (error) {
    if (token !== styleState.historyRequestToken) return;
    if (status) status.textContent = error.message;
  }
}

function applyStyleHistoryItem(item) {
  const normalized = normalizeStyleHistoryItem(item);
  if (!normalized.artists.length) {
    showStyleStatus("불러올 작가 정보가 없는 기록입니다.", "error");
    return false;
  }
  styleState.artists = normalized.artists.map((artist) => ({ ...artist }));
  styleState.promptGroups = [];
  const characterList = styleElement("characterPromptList");
  characterList?.replaceChildren();
  styleElement("basePrompt").value = normalized.base_prompt;
  styleElement("fixedPrompt").value = normalized.fixed_prompt;
  styleElement("negativePrompt").value = normalized.negative_prompt;
  normalized.character_prompts.forEach((prompt, index) => addCharacterPrompt(prompt, `history-${normalized.id}-${index + 1}`));
  if (!normalized.character_prompts.length) addCharacterPrompt();
  applyGenerationSettings(normalized.generation_settings);
  renderStyleArtistList();
  renderWeightGraph();
  updateArtistPrompt();
  persistAndRenderPromptControls();
  showStyleStatus(`생성 #${normalized.id}을 현재 그림체로 불러왔습니다.`, "ok");
  return true;
}

async function deleteStyleHistoryItem(item) {
  if (!item || !await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "generated",
    title: "생성 기록 삭제",
    message: `생성 #${item.id}와 저장된 이미지를 삭제할까요?`,
    details: ["삭제한 기록은 복구할 수 없습니다."],
    confirmLabel: "바로 삭제",
    tone: "danger",
  })) return false;
  try {
    await apiFetch("/api/style-manager/generated/delete-batch", {
      method: "POST",
      body: JSON.stringify({ image_ids: [Number(item.id)] }),
    });
    styleState.historySelectedId = null;
    styleState.historyDirty = true;
    await loadStyleHistory({ force: true });
    return true;
  } catch (error) {
    const status = styleElement("styleHistoryStatus");
    if (status) status.textContent = error.message;
    return false;
  }
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
    styleState.historyDirty = true;
    if (!styleElement("styleMakerHistory")?.classList.contains("history-collapsed")) loadStyleHistory({ force: true });
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
  syncGenerationRemote();
}

async function randomizePromptTargets(targets) {
  if (!targets.has("quality") && !targets.has("negative")) return true;
  await loadPromptPresets({ force: true });
  if (!styleState.promptPresets.length) throw new Error("랜덤으로 사용할 수집 프롬프트가 없습니다.");
  const qualityCandidates = styleState.promptPresets.filter((preset) => (
    String(preset.base_prompt || preset.quality_prompt || "").trim()
  ));
  const negativeCandidates = styleState.promptPresets.filter((preset) => (
    String(preset.negative_prompt || "").trim()
  ));
  if (targets.has("quality") && !qualityCandidates.length) {
    throw new Error("랜덤으로 사용할 퀄리티 프롬프트가 없습니다.");
  }
  if (targets.has("negative") && !negativeCandidates.length) {
    throw new Error("랜덤으로 사용할 네거티브 프롬프트가 없습니다.");
  }
  const qualityPreset = targets.has("quality") ? pickRandomPreset(qualityCandidates) : null;
  const negativePreset = targets.has("negative") ? pickRandomPreset(negativeCandidates) : null;
  if (qualityPreset) {
    styleElement("basePrompt").value = qualityPreset.base_prompt || qualityPreset.quality_prompt || "";
    styleState.excludedPromptTags = Array.isArray(qualityPreset.excluded_tags)
      ? qualityPreset.excluded_tags.map((item) => ({ tag: String(item?.tag || ""), prompt: String(item?.prompt || "") })).filter((item) => item.prompt)
      : [];
    styleState.selectedPromptPresetKey = qualityPreset.key || "";
  }
  if (negativePreset) styleElement("negativePrompt").value = negativePreset.negative_prompt || "";
  persistAndRenderPromptControls();
  renderExcludedPromptTags();
  return true;
}

async function randomizeSelectedStyleParts() {
  const targets = selectedRandomTargets();
  const artists = targets.has("artists");
  const weights = targets.has("weights");
  if (artists || weights) {
    const reroll = artists ? (weights ? "all" : "artists") : "weights";
    styleState.suppressAutomaticPromptPreset = true;
    let rerolled;
    try {
      rerolled = await loadStyleArtists(reroll);
    } finally {
      styleState.suppressAutomaticPromptPreset = false;
    }
    if (!rerolled) throw new Error("그림체를 다시 구성하지 못했습니다.");
  }
  await randomizePromptTargets(targets);
  return true;
}

async function generateOneRandomizedStyle() {
  if (styleState.running || styleState.generating) return null;
  if (!await confirmGenerationAnlasRisk("single")) return null;
  await randomizeSelectedStyleParts();
  return generateCurrentStyle();
}

async function runContinuousGeneration() {
  if (styleState.running || styleState.generating) return;
  if (!await confirmGenerationAnlasRisk("continuous")) return;
  styleState.running = true;
  styleState.paused = false;
  styleState.stopRequested = false;
  styleState.completed = 0;
  renderQueueState();
  try {
    while (!styleState.stopRequested && !reachedGenerationLimit()) {
      while (styleState.paused && !styleState.stopRequested) await wait(150);
      if (styleState.stopRequested) break;
      await randomizeSelectedStyleParts();
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

// The API keeps the legacy `skip_delete_confirmation` key. The settings UI
// uses the clearer positive meaning: checked means the delete confirmation is on.
function deleteConfirmationEnabledFromSkip(skipValue) {
  return skipValue !== true;
}

function skipDeleteConfirmationFromEnabled(enabledValue) {
  return enabledValue !== true;
}

async function openSettingsModal() {
  styleElement("settingsModal")?.classList.remove("hidden");
  const status = styleElement("novelAiSettingsStatus");
  const checkboxes = () => [...document.querySelectorAll("[data-delete-confirmation-category]")];
  try {
    const [data, preferences] = await Promise.all([
      apiFetch("/api/settings/novelai"),
      apiFetch("/api/settings/preferences"),
    ]);
    const values = preferences.skip_delete_confirmation || {};
    checkboxes().forEach((checkbox) => {
      checkbox.checked = deleteConfirmationEnabledFromSkip(
        values[checkbox.dataset.deleteConfirmationCategory],
      );
    });
    globalThis.appDialog.setPreferences?.(preferences);
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

async function saveAppPreferences() {
  const status = styleElement("novelAiSettingsStatus");
  const values = Object.fromEntries([...document.querySelectorAll("[data-delete-confirmation-category]")]
    .map((checkbox) => [
      checkbox.dataset.deleteConfirmationCategory,
      skipDeleteConfirmationFromEnabled(checkbox.checked),
    ]));
  try {
    const preferences = await apiFetch("/api/settings/preferences", {
      method: "PUT",
      body: JSON.stringify({ skip_delete_confirmation: values }),
    });
    globalThis.appDialog.setPreferences?.(preferences);
    if (status) status.textContent = "삭제 확인 설정을 저장했습니다.";
    return true;
  } catch (error) {
    if (status) status.textContent = error.message;
    return false;
  }
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
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "novelai_key",
    title: "NovelAI App Key 삭제",
    message: "저장된 App Key를 이 프로그램에서 삭제할까요?",
    confirmLabel: "키 삭제",
    tone: "danger",
  })) return;
  const status = styleElement("novelAiSettingsStatus");
  try {
    await apiFetch("/api/settings/novelai", { method: "DELETE" });
    if (status) status.textContent = "저장된 키를 삭제했습니다.";
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function styleManagerFilterValues() {
  return {
    query: styleElement("styleManagerSearch")?.value || "",
    scope: styleElement("styleManagerScopeFilter")?.value || "all",
    metadata: styleElement("styleManagerMetadataFilter")?.value || "all",
    recommendationMin: styleElement("styleManagerRecommendationMin")?.value || "",
    sort: styleElement("styleManagerSort")?.value || "newest",
  };
}

function filterStyleManagerItems(styles, mode, filters = {}) {
  const query = String(filters.query || "").trim().toLocaleLowerCase();
  const scope = String(filters.scope || "all");
  const metadata = String(filters.metadata || "all");
  const recommendationMin = filters.recommendationMin === "" || filters.recommendationMin === null
    ? null
    : Number(filters.recommendationMin);
  const filtered = (Array.isArray(styles) ? styles : []).filter((item) => {
    if (query) {
      const haystack = [
        item.name, item.title, item.description, item.artist_prompt, item.quality_prompt, item.base_prompt,
        item.fixed_prompt, item.negative_prompt, item.model, item.source_url,
        ...(Array.isArray(item.artists) ? item.artists : []).map((artist) => artist?.artist),
        ...(Array.isArray(item.character_prompts) ? item.character_prompts : []).map((character) => character?.prompt || character),
      ].filter(Boolean).join("\n").toLocaleLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (mode === "generated" && scope === "confirmed" && !item.confirmed) return false;
    if (mode === "generated" && scope === "unconfirmed" && item.confirmed) return false;
    if (mode === "confirmed" && scope !== "all" && item.source_type !== scope) return false;
    if (mode === "shared" && scope !== "all" && item.board_tab !== scope) return false;
    if (mode === "shared" && metadata !== "all" && item.metadata_status !== metadata) return false;
    if (mode === "shared" && Number.isFinite(recommendationMin) && Number(item.recommendation_count) < recommendationMin) return false;
    return true;
  });
  const timestamp = (item) => String(item.updated_at || item.created_at || item.posted_at || "");
  filtered.sort((left, right) => {
    if (filters.sort === "recommend") {
      return Number(right.recommendation_count ?? -1) - Number(left.recommendation_count ?? -1)
        || Number(right.id || 0) - Number(left.id || 0);
    }
    const direction = filters.sort === "oldest" ? 1 : -1;
    return direction * timestamp(left).localeCompare(timestamp(right))
      || direction * (Number(left.id || 0) - Number(right.id || 0));
  });
  return filtered;
}

function renderStyleManagerPagination(total) {
  const pageCount = Math.max(1, Math.ceil(total / styleState.managerPageSize));
  styleState.managerPageCount = pageCount;
  styleState.managerPage = Math.min(Math.max(styleState.managerPage, 1), pageCount);
  const summary = styleElement("styleManagerPageSummary");
  if (summary) summary.textContent = `${styleState.managerPage} / ${pageCount} 페이지`;
  const previous = styleElement("styleManagerPrevPage");
  const next = styleElement("styleManagerNextPage");
  if (previous) previous.disabled = styleState.managerPage <= 1;
  if (next) next.disabled = styleState.managerPage >= pageCount;
}

function updateStyleManagerListStatus(total) {
  const status = styleElement("styleManagerStatus");
  if (!status) return;
  if (!total) {
    status.textContent = "조건에 맞는 그림체가 없습니다.";
  } else {
    status.textContent = `${total}개 · ${styleState.managerPage}페이지`;
  }
  renderStyleManagerPagination(total);
}

function setStyleManagerLoadProgress({ label = "", completed = 0, total = 0, indeterminate = false, failures = 0 } = {}) {
  const container = styleElement("styleManagerLoadProgress");
  const bar = styleElement("styleManagerLoadProgressBar");
  const text = styleElement("styleManagerLoadProgressText");
  container?.classList.toggle("hidden", !label);
  if (bar) {
    bar.max = Math.max(1, total);
    if (indeterminate) bar.removeAttribute("value");
    else bar.value = Math.max(0, Math.min(completed, total));
  }
  if (text) text.textContent = label
    ? `${label}${total ? ` · ${completed}/${total}${failures ? ` · 표시 실패 ${failures}장` : ""}` : ""}`
    : "";
}

function createStyleManagerImageProgress(total) {
  const token = ++styleState.managerImageLoadToken;
  let completed = 0;
  let failures = 0;
  if (!total) {
    setStyleManagerLoadProgress();
    return () => {};
  }
  setStyleManagerLoadProgress({ label: "이미지 가져오는 중", completed, total });
  return (failed = false) => {
    if (token !== styleState.managerImageLoadToken) return;
    completed += 1;
    if (failed) failures += 1;
    setStyleManagerLoadProgress({
      label: completed < total ? "이미지 가져오는 중" : "현재 페이지 이미지 준비 완료",
      completed,
      total,
      failures,
    });
  };
}

function paginateStyleManagerItems(items, page, pageSize) {
  const size = Math.max(1, Math.trunc(Number(pageSize) || 1));
  const currentPage = Math.max(1, Math.trunc(Number(page) || 1));
  return (Array.isArray(items) ? items : []).slice((currentPage - 1) * size, currentPage * size);
}

function normalizeStyleManagerPageSize(value) {
  const size = Math.trunc(Number(value));
  return STYLE_MANAGER_PAGE_SIZES.includes(size) ? size : 24;
}

function renderStyleManagerList(styles) {
  const list = styleElement("styleManagerList");
  if (!list) return;
  list.replaceChildren();
  const visibleStyles = filterStyleManagerItems(styles, styleState.managerMode, styleManagerFilterValues());
  styleState.managerTotal = styleState.managerMode === "shared" ? styleState.managerTotal : visibleStyles.length;
  renderStyleManagerPagination(styleState.managerTotal);
  const pageStyles = styleState.managerMode === "shared"
    ? visibleStyles
    : paginateStyleManagerItems(visibleStyles, styleState.managerPage, styleState.managerPageSize);
  const settleImage = createStyleManagerImageProgress(
    pageStyles.filter((style) => style.thumbnail_url || style.image_url || style.representative_image_url).length,
  );
  pageStyles.forEach((style) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "style-manager-item";
    button.dataset.styleManagerId = String(style.id);
    button.classList.add(`manager-${styleState.managerMode}-item`);
    button.classList.toggle("selection-mode", styleState.managerSelectionMode && styleState.managerMode !== "shared");
    button.classList.toggle("selected", styleState.selectedStyleIds.has(style.id));
    const detailActive = styleState.managerDetail && String(styleState.managerDetail.id) === String(style.id);
    button.classList.toggle("detail-active", Boolean(detailActive));
    if (detailActive) button.setAttribute("aria-current", "true");
    button.setAttribute("aria-pressed", String(styleState.selectedStyleIds.has(style.id)));
    const selectionMark = document.createElement("span");
    selectionMark.className = "style-manager-selection-mark";
    selectionMark.textContent = styleState.selectedStyleIds.has(style.id) ? "✓" : "";
    selectionMark.setAttribute("aria-hidden", "true");
    button.append(selectionMark);
    const imageUrl = style.image_url || style.representative_image_url;
    if (imageUrl) {
      const image = document.createElement("img");
      image.addEventListener("load", () => settleImage(false), { once: true });
      image.addEventListener("error", () => settleImage(true), { once: true });
      image.src = style.thumbnail_url || imageUrl;
      image.alt = "그림체 대표 이미지";
      image.loading = "eager";
      image.decoding = "async";
      button.append(image);
    }
    const body = document.createElement("span");
    body.className = "style-manager-item-body";
    const title = document.createElement("strong");
    title.textContent = styleState.managerMode === "confirmed"
      ? (style.name || `확정 그림체 #${style.id}`)
      : styleState.managerMode === "shared"
        ? (style.title || `공유 이미지 #${style.id}`)
        : `생성 #${style.id}`;
    const info = document.createElement("span");
    if (styleState.managerMode === "generated") {
      info.textContent = `작가 ${(style.artists || []).length}명${style.confirmed ? " · 확정됨" : ""}`;
    } else if (styleState.managerMode === "confirmed") {
      info.textContent = `${style.source_type === "manual" ? "직접 추가" : style.source_type === "shared" ? "공유에서 확정" : "제작에서 확정"}`;
    } else {
      info.textContent = `${style.board_tab || "공유"}${style.confirmed ? " · 확정됨" : ""}`;
    }
    body.append(title, info);
    if (styleState.managerDescriptions) {
      const description = document.createElement("span");
      description.className = "style-manager-card-description";
      description.textContent = style.description || style.quality_prompt || style.base_prompt || style.prompt || "설명 없음";
      body.append(description);
    }
    if (!styleState.managerDescriptions) {
      button.classList.add("image-only");
      button.setAttribute("aria-label", title.textContent);
    } else {
      button.append(body);
    }
    button.addEventListener("click", () => {
      if (styleState.managerSelectionMode && styleState.managerMode !== "shared") {
        styleState.selectedStyleIds = toggleSelectedStyleId(styleState.selectedStyleIds, style.id);
        renderStyleManagerList(styleState.managerStyles);
        syncStyleSelectionControls();
      }
      renderStyleManagerDetail(style);
    });
    list.append(button);
  });
  updateStyleManagerListStatus(styleState.managerTotal);
}

function syncStyleManagerDetailSelection() {
  const detailId = styleState.managerDetail?.id;
  document.querySelectorAll("#styleManagerList .style-manager-item").forEach((button) => {
    const active = detailId !== undefined && String(button.dataset.styleManagerId) === String(detailId);
    button.classList.toggle("detail-active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

function toggleSelectedStyleId(selectedIds, styleId) {
  const next = new Set(selectedIds);
  if (next.has(styleId)) next.delete(styleId);
  else next.add(styleId);
  return next;
}

function syncStyleSelectionControls() {
  const count = styleState.selectedStyleIds.size;
  const begin = styleElement("beginStyleSelection");
  const remove = styleElement("deleteSelectedStyles");
  const cancel = styleElement("cancelStyleSelection");
  const canDelete = styleState.managerMode !== "shared";
  begin?.classList.toggle("hidden", !canDelete);
  styleElement("addConfirmedStyle")?.classList.toggle("hidden", styleState.managerMode !== "confirmed");
  begin?.classList.toggle("active", styleState.managerSelectionMode);
  begin?.setAttribute("aria-pressed", String(styleState.managerSelectionMode));
  remove?.classList.toggle("hidden", !styleState.managerSelectionMode || !canDelete);
  cancel?.classList.toggle("hidden", !styleState.managerSelectionMode || !canDelete);
  if (remove) {
    remove.disabled = count === 0;
    remove.textContent = `선택 삭제 (${count})`;
  }
}

function syncStyleManagerFilterControls() {
  const scope = styleElement("styleManagerScopeFilter");
  const options = {
    generated: [["all", "전체"], ["confirmed", "확정됨"], ["unconfirmed", "미확정"]],
    confirmed: [["all", "전체"], ["manual", "직접 추가"], ["generated", "제작에서 확정"], ["shared", "공유에서 확정"]],
    shared: [["all", "전체 게시판"], ["NAI", "NAI"], ["R18_NAI", "🔞 NAI"]],
  }[styleState.managerMode];
  if (scope) {
    scope.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
    scope.value = "all";
  }
  const shared = styleState.managerMode === "shared";
  styleElement("styleManagerMetadataField")?.classList.toggle("hidden", !shared);
  styleElement("styleManagerRecommendationField")?.classList.toggle("hidden", !shared);
  const recommendSort = styleElement("styleManagerRecommendSort");
  if (recommendSort) recommendSort.hidden = !shared;
  const sort = styleElement("styleManagerSort");
  if (!shared && sort?.value === "recommend") sort.value = "newest";
}

function styleManagerSharedQuery(offset) {
  const filters = styleManagerFilterValues();
  const query = new URLSearchParams({ offset: String(offset), limit: String(styleState.managerPageSize) });
  if (filters.query.trim()) query.set("q", filters.query.trim());
  if (filters.scope !== "all") query.set("tab", filters.scope);
  if (filters.metadata !== "all") query.set("metadata", filters.metadata);
  if (String(filters.recommendationMin).trim()) query.set("recommendation_min", filters.recommendationMin);
  const sorts = { newest: "posted_desc", oldest: "posted_asc", recommend: "recommend_desc" };
  query.set("sort", sorts[filters.sort] || "posted_desc");
  return query.toString();
}

function applyStyleManagerFilters({ delayed = false } = {}) {
  clearTimeout(styleState.managerFilterTimer);
  const apply = () => {
    styleState.managerPage = 1;
    resetStyleManagerDetail();
    if (styleState.managerMode === "shared") loadStyleManager();
    else renderStyleManagerList(styleState.managerStyles);
  };
  if (delayed) styleState.managerFilterTimer = setTimeout(apply, 250);
  else apply();
}

function setStyleManagerPage(page) {
  const nextPage = Math.trunc(Number(page));
  if (!Number.isFinite(nextPage)) return;
  styleState.managerPage = Math.min(Math.max(nextPage, 1), styleState.managerPageCount);
  resetStyleManagerDetail();
  if (styleState.managerMode === "shared") loadStyleManager();
  else renderStyleManagerList(styleState.managerStyles);
}

function setStyleManagerMode(mode) {
  if (!["generated", "confirmed", "shared"].includes(mode)) return;
  styleState.managerMode = mode;
  styleState.managerDirty = true;
  styleState.managerPage = 1;
  syncStyleManagerFilterControls();
  setStyleSelectionMode(false);
  resetStyleManagerDetail();
  document.querySelectorAll("[data-style-manager-mode]").forEach((button) => {
    const active = button.dataset.styleManagerMode === mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  const titles = { generated: "제작 기록", confirmed: "확정 그림체", shared: "공유 그림체" };
  const title = styleElement("styleManagerListTitle");
  if (title) title.textContent = titles[mode];
  syncStyleSelectionControls();
  loadStyleManager();
}

function setStyleSelectionMode(enabled) {
  styleState.managerSelectionMode = Boolean(enabled);
  styleState.selectedStyleIds = new Set();
  syncStyleSelectionControls();
  renderStyleManagerList(styleState.managerStyles);
}

async function loadStyleManager() {
  const status = styleElement("styleManagerStatus");
  const requestedMode = styleState.managerMode;
  const requestToken = ++styleState.managerRequestToken;
  const title = { generated: "제작 기록", confirmed: "확정 그림체", shared: "공유 그림체" }[requestedMode];
  styleState.managerImageLoadToken += 1;
  setStyleManagerLoadProgress({ label: `${title} 목록 정보를 가져오는 중`, indeterminate: true });
  try {
    let styles;
    let sharedResult = null;
    if (styleState.managerMode === "confirmed") {
      styles = await apiFetch("/api/confirmed-styles");
    } else if (styleState.managerMode === "shared") {
      sharedResult = await apiFetch(`/api/style-manager/shared?${styleManagerSharedQuery((styleState.managerPage - 1) * styleState.managerPageSize)}`);
      styles = sharedResult.items || [];
    } else {
      styles = await apiFetch("/api/style-manager/generated");
    }
    if (requestToken !== styleState.managerRequestToken || requestedMode !== styleState.managerMode) return;
    if (sharedResult) {
      styleState.managerTotal = Number(sharedResult.total || 0);
    }
    styleState.managerStyles = styles;
    const availableIds = new Set(styles.map((style) => style.id));
    styleState.selectedStyleIds = new Set(
      [...styleState.selectedStyleIds].filter((styleId) => availableIds.has(styleId)),
    );
    renderStyleManagerList(styles);
    syncStyleSelectionControls();
    styleState.managerDirty = false;
  } catch (error) {
    if (requestToken !== styleState.managerRequestToken || requestedMode !== styleState.managerMode) return;
    setStyleManagerLoadProgress();
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
  styleElement("style-manager-tab")?.classList.remove("has-detail");
  target.replaceChildren();
  const placeholder = document.createElement("div");
  placeholder.className = "latest-result-placeholder";
  placeholder.textContent = "확인할 그림체를 선택하세요.";
  target.append(placeholder);
  styleState.managerImages = [];
  styleState.managerImageIndex = 0;
  styleState.managerDetail = null;
  styleState.managerNegativeExpanded = false;
  syncStyleManagerDetailSelection();
  closeGeneratedImage();
}

async function deleteManagedStyle(styleId) {
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "style",
    title: "그림체 삭제",
    message: "이 그림체와 함께 저장된 생성 이미지를 모두 삭제할까요?",
    details: ["생성 이미지도 함께 삭제됩니다.", "삭제한 그림체와 생성 이미지는 복구할 수 없습니다."],
    confirmLabel: "그림체 삭제",
    tone: "danger",
  })) return;
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

async function deleteSelectedManagedStyles() {
  const styleIds = [...styleState.selectedStyleIds].sort((left, right) => left - right);
  if (!styleIds.length) return;
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: styleState.managerMode === "confirmed" ? "style" : "generated",
    title: `${styleIds.length}개 삭제`,
    message: styleState.managerMode === "confirmed"
      ? "선택한 확정 그림체를 삭제할까요? 원본 제작 기록과 공유 그림체는 유지됩니다."
      : "선택한 생성 결과를 삭제할까요?",
    details: ["삭제한 항목은 복구할 수 없습니다."],
    confirmLabel: `${styleIds.length}개 삭제`,
    tone: "danger",
  })) return;
  const status = styleElement("styleManagerStatus");
  try {
    const endpoint = styleState.managerMode === "confirmed"
      ? "/api/confirmed-styles/delete-batch"
      : "/api/style-manager/generated/delete-batch";
    const key = styleState.managerMode === "confirmed" ? "style_ids" : "image_ids";
    const result = await apiFetch(endpoint, {
      method: "POST",
      body: JSON.stringify({ [key]: styleIds }),
    });
    const deletedIds = new Set(result.deleted_ids || []);
    styleState.historyDirty = true;
    if (styleState.managerDetail && deletedIds.has(styleState.managerDetail.id)) {
      resetStyleManagerDetail();
    }
    setStyleSelectionMode(false);
    await loadStyleManager();
    if (status) status.textContent = `${deletedIds.size}개 항목을 삭제했습니다.`;
  } catch (error) {
    if (status) status.textContent = error.message;
  }
}

function managerArtistText(item) {
  if (item?.artist_prompt) return item.artist_prompt;
  const artists = Array.isArray(item?.artists) ? item.artists : [];
  return artists
    .map((artist) => `${formatStyleWeight(artist.weight)}::artist:${formatArtistPromptTag(artist.artist)}::`)
    .join(", ") || "없음";
}

function managerCombinedPromptText(item) {
  if (!item) return "이미지를 선택하세요.";
  return combinePromptSections(managerArtistText(item), item.base_prompt) || "없음";
}

function appendManagerPromptBlock(parent, label, value, className = "") {
  const section = document.createElement("section");
  section.className = `manager-prompt-block ${className}`.trim();
  const heading = document.createElement("h3");
  heading.textContent = label;
  const content = document.createElement("div");
  content.className = "manager-info-content";
  content.textContent = value || "없음";
  section.append(heading, content);
  parent.append(section);
}

function renderStyleManagerImageSelection() {
  const detail = styleState.managerDetail;
  const stage = styleElement("styleManagerImageStage");
  const inspector = styleElement("styleManagerImageInspector");
  if (!detail || !stage || !inspector) return;
  const item = detail.images[styleState.managerImageIndex];
  stage.replaceChildren();
  inspector.replaceChildren();
  if (!item) {
    const empty = document.createElement("div");
    empty.className = "latest-result-placeholder";
    empty.textContent = "저장된 이미지가 없습니다.";
    stage.append(empty);
    return;
  }
  const image = document.createElement("img");
  image.className = "manager-selected-image";
  image.src = item.image_url;
  image.alt = `선택한 생성 이미지 ${styleState.managerImageIndex + 1}`;
  image.addEventListener("click", () => openGeneratedImage(detail.images, styleState.managerImageIndex));
  stage.append(image);
  const imageActions = document.createElement("div");
  imageActions.className = "manager-image-actions";
  if (detail.images.length > 1) {
    const previous = document.createElement("button");
    previous.type = "button";
    previous.textContent = "이전";
    previous.addEventListener("click", () => {
      styleState.managerImageIndex = (styleState.managerImageIndex - 1 + detail.images.length) % detail.images.length;
      renderStyleManagerImageSelection();
    });
    const position = document.createElement("span");
    position.textContent = `${styleState.managerImageIndex + 1} / ${detail.images.length}`;
    const next = document.createElement("button");
    next.type = "button";
    next.textContent = "다음";
    next.addEventListener("click", () => {
      styleState.managerImageIndex = (styleState.managerImageIndex + 1) % detail.images.length;
      renderStyleManagerImageSelection();
    });
    imageActions.append(previous, position, next);
  }
  const fullButton = document.createElement("button");
  fullButton.type = "button";
  fullButton.textContent = "크게 보기";
  fullButton.addEventListener("click", () => openGeneratedImage(detail.images, styleState.managerImageIndex));
  imageActions.append(fullButton);
  stage.append(imageActions);

  appendManagerPromptBlock(inspector, "작가 · 퀄리티", managerCombinedPromptText(item), "manager-primary-prompt");
  appendManagerPromptBlock(
    inspector,
    "캐릭터",
    (item.character_prompts || []).join("\n\n") || "없음",
  );
  const negativeToggle = document.createElement("button");
  negativeToggle.type = "button";
  negativeToggle.className = "manager-negative-toggle";
  negativeToggle.textContent = styleState.managerNegativeExpanded ? "▲ 네거티브 접기" : "▼ 네거티브 보기";
  negativeToggle.setAttribute("aria-expanded", String(styleState.managerNegativeExpanded));
  negativeToggle.addEventListener("click", () => {
    styleState.managerNegativeExpanded = !styleState.managerNegativeExpanded;
    renderStyleManagerImageSelection();
  });
  inspector.append(negativeToggle);
  if (styleState.managerNegativeExpanded) {
    appendManagerPromptBlock(inspector, "네거티브", item.negative_prompt || "없음", "manager-negative-prompt");
  }
  const generation = document.createElement("div");
  generation.className = "manager-generation-summary";
  generation.textContent = `${item.width}×${item.height} · ${item.sampler} / ${item.noise_schedule || "native"} · ${item.steps} steps · CFG ${item.scale} · Rescale ${item.cfg_rescale} · Seed ${item.seed}`;
  inspector.append(generation);
}

function managerCharacterText(item) {
  const characters = Array.isArray(item?.character_prompts) ? item.character_prompts : [];
  return characters.map((entry) => typeof entry === "string" ? entry : entry?.prompt || "").filter(Boolean).join("\n\n") || "없음";
}

function managerPromptParts(item) {
  if (styleState.managerMode === "generated") {
    return {
      primary: combinePromptSections(managerArtistText(item), item.quality_prompt || item.base_prompt, item.fixed_prompt),
      negative: item.negative_prompt || "",
    };
  }
  return {
    primary: combinePromptSections(item.artist_prompt, item.quality_prompt || item.base_prompt || item.prompt, item.fixed_prompt),
    negative: item.negative_prompt || "",
  };
}

function managerKnown(value, suffix = "") {
  return value === null || value === undefined || value === "" ? "알 수 없음" : `${value}${suffix}`;
}

function safeManagerExternalUrl(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  try {
    const parsed = new URL(value.trim(), document.baseURI || "http://localhost/");
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function appendSharedDependencyBlock(parent, item) {
  if (styleState.managerMode !== "generated") return;
  const referenceId = item?.shared_dependency_reference_id;
  if (!Number.isInteger(referenceId) || referenceId < 1) return;
  const section = document.createElement("section");
  section.className = "manager-prompt-block manager-shared-dependency";
  const heading = document.createElement("h3");
  heading.textContent = "의존 공유 그림체";
  const content = document.createElement("div");
  content.className = "manager-info-content";
  const title = item.shared_dependency_reference_title || `공유 이미지 #${referenceId}`;
  const titleText = document.createElement("span");
  titleText.textContent = `${title} (#${referenceId})`;
  content.append(titleText);
  const sourceUrl = safeManagerExternalUrl(item.shared_dependency_reference_source_url);
  if (sourceUrl) {
    const link = document.createElement("a");
    link.className = "button-link";
    link.href = sourceUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "원문 열기";
    link.addEventListener("click", (event) => event.stopPropagation());
    content.append(" ", link);
  }
  section.append(heading, content);
  parent.append(section);
}

function managerGenerationText(item) {
  const variety = item.variety_plus === null || item.variety_plus === undefined
    ? "Variety+ 알 수 없음"
    : `Variety+ ${item.variety_plus ? "켜짐" : "꺼짐"}`;
  return [
    `${managerKnown(item.width)}×${managerKnown(item.height)}`,
    `${managerKnown(item.sampler)} / ${managerKnown(item.noise_schedule)}`,
    `${managerKnown(item.steps)} steps`,
    `CFG ${managerKnown(item.scale)}`,
    `Rescale ${managerKnown(item.cfg_rescale)}`,
    variety,
    `Seed ${managerKnown(item.seed)}`,
    managerKnown(item.model),
  ].join(" · ");
}

function normalizedManagerModalImage(item) {
  const prompts = managerPromptParts(item);
  return {
    ...item,
    base_prompt: prompts.primary,
    negative_prompt: prompts.negative,
    character_prompts: Array.isArray(item.character_prompts) ? item.character_prompts.map((entry) => typeof entry === "string" ? entry : entry?.prompt || "") : [],
  };
}

function renderStyleManagerDetail(item) {
  const target = styleElement("styleManagerDetail");
  if (!target) return;
  styleElement("style-manager-tab")?.classList.add("has-detail");
  target.replaceChildren();
  styleState.managerDetail = item;
  const confirmedImages = styleState.managerMode === "confirmed" && Array.isArray(item.images) && item.images.length
    ? item.images.map((image) => normalizedManagerModalImage({ ...item, ...image, image_url: image.image_url }))
    : [normalizedManagerModalImage(item)];
  styleState.managerImages = confirmedImages;
  styleState.managerImageIndex = 0;
  styleState.managerNegativeExpanded = false;
  const head = document.createElement("div");
  head.className = "style-manager-detail-head";
  const heading = document.createElement("h2");
  heading.textContent = styleState.managerMode === "confirmed"
    ? (item.name || `확정 그림체 #${item.id}`)
    : styleState.managerMode === "shared"
      ? (item.title || `공유 이미지 #${item.id}`)
      : `생성 #${item.id}`;
  const headActions = document.createElement("div");
  headActions.className = "style-manager-list-actions";
  if (styleState.managerMode === "confirmed") {
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.textContent = "정보 수정";
    editButton.addEventListener("click", () => openConfirmedStyleModal(item, true));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "danger-button";
    deleteButton.textContent = "삭제";
    deleteButton.addEventListener("click", () => deleteSingleManagerItem(item));
    headActions.append(editButton, deleteButton);
  } else {
    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "primary";
    confirmButton.textContent = item.confirmed ? "다시 확정본 만들기" : "확정 그림체로 추가";
    confirmButton.addEventListener("click", () => openConfirmedStyleModal(item, false));
    headActions.append(confirmButton);
    if (styleState.managerMode === "shared" && item.source_url) {
      const sourceLink = document.createElement("a");
      sourceLink.className = "button-link";
      sourceLink.href = item.source_url;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      sourceLink.textContent = "원문 열기";
      headActions.append(sourceLink);
    }
    if (styleState.managerMode === "generated") {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "danger-button";
      deleteButton.textContent = "생성 결과 삭제";
      deleteButton.addEventListener("click", () => deleteSingleManagerItem(item));
      headActions.append(deleteButton);
    }
  }
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "ghost style-manager-detail-close";
  closeButton.textContent = "상세 닫기";
  closeButton.setAttribute("aria-label", "상세보기 닫기");
  closeButton.addEventListener("click", resetStyleManagerDetail);
  headActions.append(closeButton);
  head.append(heading, headActions);
  const detailGrid = document.createElement("div");
  detailGrid.className = "style-manager-detail-grid";
  const imageStage = document.createElement("section");
  imageStage.className = "manager-image-stage";
  const image = document.createElement("img");
  image.className = "manager-selected-image";
  image.src = styleState.managerImages[0]?.image_url || item.image_url || "";
  image.alt = "선택한 그림체 이미지";
  image.addEventListener("click", () => openGeneratedImage(styleState.managerImages, styleState.managerImageIndex));
  if (styleState.managerImages.length > 1) {
    const previous = document.createElement("button");
    previous.type = "button";
    previous.className = "manager-group-image-nav";
    previous.textContent = "↑ 같은 그림체 이전 이미지";
    const next = document.createElement("button");
    next.type = "button";
    next.className = "manager-group-image-nav";
    next.textContent = "↓ 같은 그림체 다음 이미지";
    const counter = document.createElement("span");
    counter.className = "manager-group-image-counter";
    const showImage = (index) => {
      styleState.managerImageIndex = (index + styleState.managerImages.length) % styleState.managerImages.length;
      image.src = styleState.managerImages[styleState.managerImageIndex].image_url || "";
      counter.textContent = `${styleState.managerImageIndex + 1} / ${styleState.managerImages.length}`;
    };
    previous.addEventListener("click", () => showImage(styleState.managerImageIndex - 1));
    next.addEventListener("click", () => showImage(styleState.managerImageIndex + 1));
    imageStage.append(previous, image, next, counter);
    showImage(0);
  } else {
    imageStage.append(image);
  }
  const inspector = document.createElement("section");
  inspector.className = "manager-image-inspector";
  const prompts = managerPromptParts(item);
  appendManagerPromptBlock(inspector, "작가 · 퀄리티", prompts.primary || "없음", "manager-primary-prompt");
  appendManagerPromptBlock(inspector, "캐릭터", managerCharacterText(item));
  appendSharedDependencyBlock(inspector, item);
  const negativeToggle = document.createElement("button");
  negativeToggle.type = "button";
  negativeToggle.className = "manager-negative-toggle";
  negativeToggle.textContent = "▼ 네거티브 보기";
  negativeToggle.setAttribute("aria-expanded", "false");
  negativeToggle.addEventListener("click", () => {
    const block = inspector.querySelector(".manager-negative-prompt");
    const expanded = block?.classList.toggle("hidden") === false;
    negativeToggle.textContent = expanded ? "▲ 네거티브 접기" : "▼ 네거티브 보기";
    negativeToggle.setAttribute("aria-expanded", String(expanded));
  });
  inspector.append(negativeToggle);
  appendManagerPromptBlock(inspector, "네거티브", prompts.negative || "없음", "manager-negative-prompt hidden");
  if (styleState.managerMode === "confirmed" && item.description) {
    appendManagerPromptBlock(inspector, "설명", item.description);
  }
  const generation = document.createElement("div");
  generation.className = "manager-generation-summary";
  generation.textContent = managerGenerationText(item);
  inspector.append(generation);
  detailGrid.append(imageStage, inspector);
  target.append(head, detailGrid);
  syncStyleManagerDetailSelection();
}

async function deleteSingleManagerItem(item) {
  if (!await globalThis.appDialog.confirm({
    delete: true,
    delete_category: styleState.managerMode === "confirmed" ? "style" : "generated",
    title: "항목 삭제",
    message: styleState.managerMode === "confirmed"
      ? `이 확정 그림체와 같은 묶음의 이미지 ${item.image_count || 1}장을 모두 삭제할까요? 원본은 유지됩니다.`
      : "이 생성 결과를 삭제할까요?",
    confirmLabel: "삭제",
    tone: "danger",
  })) return;
  const endpoint = styleState.managerMode === "confirmed"
    ? `/api/confirmed-styles/${item.id}`
    : "/api/style-manager/generated/delete-batch";
  const options = styleState.managerMode === "confirmed"
    ? { method: "DELETE" }
    : { method: "POST", body: JSON.stringify({ image_ids: [item.id] }) };
  try {
    await apiFetch(endpoint, options);
    styleState.historyDirty = true;
    resetStyleManagerDetail();
    await loadStyleManager();
  } catch (error) {
    const status = styleElement("styleManagerStatus");
    if (status) status.textContent = error.message;
  }
}

function confirmedFormValue(id, value) {
  const element = styleElement(id);
  if (element) element.value = value === null || value === undefined ? "" : String(value);
}

function normalizeConfirmedModelName(value) {
  const model = String(value || "").trim();
  const lowered = model.toLowerCase();
  if (lowered.startsWith("novelai diffusion v4.5 curated") || lowered === "nai-diffusion-4-5-curated") {
    return "NovelAI Diffusion V4.5 Curated";
  }
  if (lowered.startsWith("novelai diffusion v4.5") || lowered === "nai-diffusion-4-5-full") {
    return "NovelAI Diffusion V4.5 Full";
  }
  return model;
}

function setConfirmedModelValue(value) {
  const element = styleElement("confirmedStyleModel");
  if (!element) return;
  const model = normalizeConfirmedModelName(value);
  if (model && ![...element.options].some((option) => option.value === model)) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = `기존 기록: ${model}`;
    element.append(option);
  }
  element.value = model;
}

function renderConfirmedExcludedTags() {
  const section = styleElement("confirmedStyleExcludedSection");
  const list = styleElement("confirmedStyleExcludedTags");
  if (!section || !list) return;
  list.replaceChildren();
  styleState.confirmedModalExcludedTags.forEach((tag, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = tag;
    button.title = "퀄리티 프롬프트로 복구";
    button.addEventListener("click", () => {
      const quality = styleElement("confirmedStyleQualityPrompt");
      if (quality) quality.value = combinePromptSections(quality.value, tag);
      styleState.confirmedModalExcludedTags.splice(index, 1);
      renderConfirmedExcludedTags();
    });
    list.append(button);
  });
  section.classList.toggle("hidden", !styleState.confirmedModalExcludedTags.length);
}

function setConfirmedPreview(url, showHint = false) {
  const image = styleElement("confirmedStylePreview");
  const hint = styleElement("confirmedStyleDropHint");
  if (image) {
    image.src = url || "";
    image.classList.toggle("hidden", !url);
  }
  hint?.classList.toggle("hidden", Boolean(url) && !showHint);
}

function confirmedArtistPromptSignature(prompt) {
  return normalizeNumericPromptClosers(String(prompt || ""))
    .replace(/(\d+(?:\.\d+)?)\s*::\s*artist:/gi, (_, weight) => `${Number(weight)}::artist:`)
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function groupConfirmedImportItems(items) {
  const groups = [];
  (Array.isArray(items) ? items : []).forEach((item, index) => {
    const signature = confirmedArtistPromptSignature(item?.metadata?.artist_prompt);
    const group = signature && groups.find((entry) => entry.signature === signature);
    if (group) {
      group.items.push(item);
    } else {
      groups.push({
        signature: signature || `unidentified:${index}`,
        items: [item],
        data: { ...(item?.metadata || {}) },
      });
    }
  });
  return groups;
}

function attachConfirmedStyleSuspects(groups, confirmedStyles) {
  const stylesBySignature = new Map();
  (Array.isArray(confirmedStyles) ? confirmedStyles : []).forEach((style) => {
    const signature = confirmedArtistPromptSignature(style?.artist_prompt);
    if (!signature) return;
    if (!stylesBySignature.has(signature)) stylesBySignature.set(signature, []);
    stylesBySignature.get(signature).push(style);
  });
  (Array.isArray(groups) ? groups : []).forEach((group) => {
    group.suspectedStyles = stylesBySignature.get(group.signature) || [];
  });
  return groups;
}

function confirmedCurrentImportGroup() {
  return styleState.confirmedImportGroups[styleState.confirmedImportGroupIndex] || null;
}

function confirmedPreviewViewerItem(data, imageUrl, image = {}) {
  return {
    ...data,
    image_url: imageUrl || "",
    base_prompt: combinePromptSections(data?.artist_prompt, data?.quality_prompt || data?.base_prompt),
    character_prompts: Array.isArray(data?.character_prompts)
      ? data.character_prompts.map((entry) => typeof entry === "string" ? entry : entry?.prompt || "").filter(Boolean)
      : [],
    width: image.width || data?.width,
    height: image.height || data?.height,
  };
}

function openConfirmedStylePreview() {
  const group = confirmedCurrentImportGroup();
  if (group?.items?.length) {
    const items = group.items.map((item) => confirmedPreviewViewerItem(
      item.metadata || group.data || {},
      item.objectUrl,
      item.metadata || {},
    ));
    openGeneratedImage(items, Math.min(styleState.confirmedImportImageIndex, items.length - 1));
    return;
  }
  const source = styleState.confirmedModalPreviewData;
  if (!source?.image_url) return;
  const images = Array.isArray(source.images) && source.images.length
    ? source.images.map((image) => confirmedPreviewViewerItem(source, image.image_url, image))
    : [confirmedPreviewViewerItem(source, source.image_url, source)];
  openGeneratedImage(images, 0);
}

function revokeConfirmedImportGroups(groups = styleState.confirmedImportGroups) {
  groups.forEach((group) => group.items.forEach((item) => {
    if (item.objectUrl) URL.revokeObjectURL(item.objectUrl);
  }));
}

function captureConfirmedImportGroupData() {
  const group = confirmedCurrentImportGroup();
  if (!group) return;
  const data = readConfirmedStyleForm();
  group.data = data;
  const item = group.items[styleState.confirmedImportImageIndex];
  if (item) item.metadata = { ...(item.metadata || {}), ...data };
}

function renderConfirmedDuplicateCandidates(group) {
  const warning = styleElement("confirmedStyleDuplicateWarning");
  const panel = styleElement("confirmedStyleDuplicateCandidates");
  const modal = styleElement("confirmedStyleDuplicateModal");
  if (!warning || !panel || !modal) return;
  const suspects = group?.suspectedStyles || [];
  warning.classList.toggle("hidden", !suspects.length);
  warning.textContent = suspects.length
    ? `이미 추가된 그림체 의심 ${suspects.length}개 · 클릭해서 확인`
    : "";
  if (!suspects.length) styleState.confirmedDuplicatePanelOpen = false;
  modal.classList.toggle("hidden", !styleState.confirmedDuplicatePanelOpen || !suspects.length);
  panel.replaceChildren();
  if (!styleState.confirmedDuplicatePanelOpen) return;
  styleState.confirmedDuplicateStyleIndex = Math.max(0, Math.min(styleState.confirmedDuplicateStyleIndex, suspects.length - 1));
  suspects.forEach((style, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "confirmed-style-duplicate-card";
    button.classList.toggle("active", index === styleState.confirmedDuplicateStyleIndex);
    button.title = `${style.name || `확정 그림체 #${style.id}`} 자세히 보기`;
    const image = document.createElement("img");
    image.src = style.image_url || style.images?.[0]?.image_url || "";
    image.alt = style.name || `의심 그림체 ${style.id}`;
    const name = document.createElement("span");
    name.textContent = style.name || `확정 그림체 #${style.id}`;
    const count = document.createElement("small");
    count.textContent = `${Number(style.image_count) || style.images?.length || 1}장`;
    button.append(image, name, count);
    button.addEventListener("click", () => {
      styleState.confirmedDuplicateStyleIndex = index;
      styleState.confirmedDuplicateImageIndex = 0;
      renderConfirmedDuplicateCandidates(group);
    });
    panel.append(button);
  });
  const style = suspects[styleState.confirmedDuplicateStyleIndex];
  const images = Array.isArray(style.images) && style.images.length
    ? style.images
    : [{ image_url: style.image_url, width: style.width, height: style.height }];
  styleState.confirmedDuplicateImageIndex = Math.max(0, Math.min(styleState.confirmedDuplicateImageIndex, images.length - 1));
  const selectedImage = images[styleState.confirmedDuplicateImageIndex] || {};
  const image = styleElement("confirmedStyleDuplicateDetailImage");
  if (image) image.src = selectedImage.image_url || style.image_url || "";
  const name = styleElement("confirmedStyleDuplicateDetailName");
  if (name) name.textContent = style.name || `확정 그림체 #${style.id}`;
  const counter = styleElement("confirmedStyleDuplicateDetailCounter");
  if (counter) counter.textContent = `후보 ${styleState.confirmedDuplicateStyleIndex + 1}/${suspects.length} · 이미지 ${styleState.confirmedDuplicateImageIndex + 1}/${images.length}`;
  ["confirmedStyleDuplicatePrevImage", "confirmedStyleDuplicateNextImage"].forEach((id) => {
    const button = styleElement(id);
    if (button) button.disabled = images.length < 2;
  });
  const info = styleElement("confirmedStyleDuplicateDetailInfo");
  if (info) {
    info.replaceChildren();
    appendMetaRow(info, "작가 프롬프트", style.artist_prompt);
    appendMetaRow(info, "퀄리티 프롬프트", style.quality_prompt);
    appendMetaRow(info, "고정 프롬프트", style.fixed_prompt);
    appendMetaRow(info, "캐릭터 프롬프트", (style.character_prompts || []).join("\n"));
    appendMetaRow(info, "네거티브", style.negative_prompt);
    appendMetaRow(info, "이미지 크기", `${selectedImage.width || style.width || "?"}×${selectedImage.height || style.height || "?"}`);
    appendMetaRow(info, "생성 설정", `${style.model || "모델 미상"} · ${style.sampler || "샘플러 미상"} / ${style.noise_schedule || "스케줄러 미상"} · ${style.steps || "?"} steps · CFG ${style.scale ?? "?"}`);
    if (style.description) appendMetaRow(info, "설명", style.description);
  }
}

function openConfirmedDuplicateReview() {
  const suspects = confirmedCurrentImportGroup()?.suspectedStyles || [];
  if (!suspects.length) return;
  styleState.confirmedDuplicatePanelOpen = true;
  styleState.confirmedDuplicateStyleIndex = 0;
  styleState.confirmedDuplicateImageIndex = 0;
  renderConfirmedDuplicateCandidates(confirmedCurrentImportGroup());
}

function closeConfirmedDuplicateReview() {
  styleState.confirmedDuplicatePanelOpen = false;
  styleElement("confirmedStyleDuplicateModal")?.classList.add("hidden");
}

function moveConfirmedDuplicateImage(delta) {
  const suspects = confirmedCurrentImportGroup()?.suspectedStyles || [];
  const style = suspects[styleState.confirmedDuplicateStyleIndex];
  const length = Array.isArray(style?.images) && style.images.length ? style.images.length : 1;
  if (length < 2) return;
  styleState.confirmedDuplicateImageIndex = (styleState.confirmedDuplicateImageIndex + delta + length) % length;
  renderConfirmedDuplicateCandidates(confirmedCurrentImportGroup());
}

function renderConfirmedImportNavigator() {
  const groups = styleState.confirmedImportGroups;
  const group = confirmedCurrentImportGroup();
  const items = group?.items || [];
  const item = items[styleState.confirmedImportImageIndex] || null;
  const strip = styleElement("confirmedStyleGroupStrip");
  if (strip) {
    strip.replaceChildren();
    groups.forEach((entry, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "confirmed-style-group-thumb";
      const active = index === styleState.confirmedImportGroupIndex;
      button.classList.toggle("active", active);
      const thumbIndex = active ? Math.min(styleState.confirmedImportImageIndex, entry.items.length - 1) : 0;
      const thumbMetadata = entry.items[thumbIndex]?.metadata || {};
      const missingMetadata = thumbMetadata.metadata_status !== "ok"
        && !thumbMetadata.artist_prompt && !thumbMetadata.quality_prompt && !(thumbMetadata.character_prompts || []).length;
      button.classList.toggle("metadata-missing", missingMetadata);
      const image = document.createElement("img");
      image.src = entry.items[thumbIndex]?.objectUrl || "";
      image.alt = `그림체 ${index + 1}`;
      const count = document.createElement("span");
      count.textContent = active && entry.items.length > 1
        ? `${index + 1} · ${thumbIndex + 1}/${entry.items.length}`
        : `${index + 1} · ${entry.items.length}장`;
      button.append(image, count);
      button.addEventListener("click", () => selectConfirmedImportItem(index, 0));
      strip.append(button);
      if (active) requestAnimationFrame(() => button.scrollIntoView({ block: "nearest", inline: "nearest" }));
    });
    strip.classList.toggle("hidden", !groups.length);
  }
  if (item) setConfirmedPreview(item.objectUrl || "");
  else if (!styleState.confirmedModalSource && !styleState.confirmedModalEditId) setConfirmedPreview("", true);
  const counter = styleElement("confirmedStyleImportCounter");
  if (counter) {
    const missingMetadata = item?.metadata?.metadata_status !== "ok"
      && !item?.metadata?.artist_prompt && !item?.metadata?.quality_prompt && !(item?.metadata?.character_prompts || []).length;
    const baseText = group
      ? `그림체 ${styleState.confirmedImportGroupIndex + 1}/${groups.length} · 같은 그림 ${styleState.confirmedImportImageIndex + 1}/${items.length}`
      : "가져온 이미지 없음";
    counter.textContent = `${baseText}${missingMetadata ? " · 프롬프트 메타데이터 없음" : ""}`;
    counter.classList.toggle("metadata-missing", Boolean(missingMetadata));
    counter.classList.toggle("hidden", !group && Boolean(styleState.confirmedModalSource || styleState.confirmedModalEditId));
  }
  renderConfirmedDuplicateCandidates(group);
  const editing = Boolean(styleState.confirmedModalEditId);
  const busy = styleState.confirmedImportBusy;
  const controls = {
    confirmedStylePrevGroup: busy || groups.length < 2,
    confirmedStyleNextGroup: busy || groups.length < 2,
    confirmedStylePrevImage: busy || items.length < 2,
    confirmedStyleNextImage: busy || items.length < 2,
    splitConfirmedStyleImage: busy || items.length < 2,
    removeConfirmedStyleGroup: busy || !group,
    chooseConfirmedStyleImage: busy,
    chooseConfirmedStyleFolder: busy,
  };
  Object.entries(controls).forEach(([id, disabled]) => {
    const element = styleElement(id);
    if (element) element.disabled = editing || disabled;
  });
  ["saveConfirmedStyle", "saveAllConfirmedStyles"].forEach((id) => {
    const element = styleElement(id);
    if (element) element.disabled = busy;
  });
}

function selectConfirmedImportItem(groupIndex, imageIndex, { capture = true } = {}) {
  if (capture) captureConfirmedImportGroupData();
  const groups = styleState.confirmedImportGroups;
  if (!groups.length) {
    styleState.confirmedImportGroupIndex = 0;
    styleState.confirmedImportImageIndex = 0;
    renderConfirmedImportNavigator();
    return;
  }
  styleState.confirmedImportGroupIndex = (Number(groupIndex) + groups.length) % groups.length;
  styleState.confirmedDuplicatePanelOpen = false;
  const group = confirmedCurrentImportGroup();
  styleState.confirmedImportImageIndex = (Number(imageIndex) + group.items.length) % group.items.length;
  applyExtractedConfirmedMetadata(group.items[styleState.confirmedImportImageIndex]?.metadata || group.data || {});
  renderConfirmedImportNavigator();
}

function moveConfirmedImportGroup(delta) {
  selectConfirmedImportItem(styleState.confirmedImportGroupIndex + delta, 0);
}

function moveConfirmedImportImage(delta) {
  selectConfirmedImportItem(
    styleState.confirmedImportGroupIndex,
    styleState.confirmedImportImageIndex + delta,
  );
}

function splitConfirmedImportImage() {
  const group = confirmedCurrentImportGroup();
  if (!group || group.items.length < 2) return;
  captureConfirmedImportGroupData();
  const [item] = group.items.splice(styleState.confirmedImportImageIndex, 1);
  const newGroup = {
    signature: `manual:${Date.now()}:${Math.random()}`,
    items: [item],
    data: { ...(item.metadata || group.data || {}) },
  };
  const nextIndex = styleState.confirmedImportGroupIndex + 1;
  styleState.confirmedImportGroups.splice(nextIndex, 0, newGroup);
  selectConfirmedImportItem(nextIndex, 0, { capture: false });
}

function removeConfirmedImportGroup() {
  const group = confirmedCurrentImportGroup();
  if (!group) return;
  revokeConfirmedImportGroups([group]);
  styleState.confirmedImportGroups.splice(styleState.confirmedImportGroupIndex, 1);
  const nextIndex = Math.min(styleState.confirmedImportGroupIndex, styleState.confirmedImportGroups.length - 1);
  selectConfirmedImportItem(Math.max(0, nextIndex), 0, { capture: false });
}

function confirmedGeneratedSourceValues(item) {
  return {
    ...item,
    name: `제작 그림체 #${item.id}`,
    description: "",
    artist_prompt: managerArtistText(item),
    quality_prompt: item.quality_prompt || item.base_prompt || "",
    original_quality_prompt: item.original_quality_prompt || item.quality_prompt || item.base_prompt || "",
    excluded_quality_tags: item.excluded_quality_tags || [],
    fixed_prompt: item.fixed_prompt || "",
    negative_prompt: item.negative_prompt || "",
  };
}

function confirmedSourceValues(item, sourceMode = styleState.managerMode) {
  if (!item) return {};
  return sourceMode === "generated" ? confirmedGeneratedSourceValues(item) : item;
}

function openConfirmedStyleModal(item = null, editing = false, sourceMode = styleState.managerMode) {
  const source = confirmedSourceValues(item, sourceMode);
  styleState.confirmedModalSource = !editing && item
    ? { source_type: sourceMode === "shared" ? "shared" : "generated", source_id: item.id }
    : null;
  styleState.confirmedModalEditId = editing ? item.id : null;
  styleState.confirmedModalPreviewData = source;
  styleState.confirmedModalFile = null;
  revokeConfirmedImportGroups();
  styleState.confirmedImportGroups = [];
  styleState.confirmedImportGroupIndex = 0;
  styleState.confirmedImportImageIndex = 0;
  styleState.confirmedDuplicatePanelOpen = false;
  styleState.confirmedModalExcludedTags = [...(source.excluded_quality_tags || [])];
  styleState.confirmedModalOriginalQualityPrompt = source.original_quality_prompt || source.quality_prompt || source.base_prompt || "";
  if (styleState.confirmedModalObjectUrl) URL.revokeObjectURL(styleState.confirmedModalObjectUrl);
  styleState.confirmedModalObjectUrl = "";
  confirmedFormValue("confirmedStyleName", source.name || "");
  confirmedFormValue("confirmedStyleDescription", source.description || "");
  confirmedFormValue("confirmedStyleArtistPrompt", source.artist_prompt || "");
  confirmedFormValue("confirmedStyleQualityPrompt", source.quality_prompt || source.base_prompt || source.prompt || "");
  confirmedFormValue("confirmedStyleFixedPrompt", source.fixed_prompt || "");
  confirmedFormValue("confirmedStyleCharacterPrompts", (source.character_prompts || []).map((entry) => typeof entry === "string" ? entry : entry?.prompt || "").filter(Boolean).join("\n"));
  confirmedFormValue("confirmedStyleNegativePrompt", source.negative_prompt || "");
  confirmedFormValue("confirmedStyleSampler", source.sampler || "");
  confirmedFormValue("confirmedStyleScheduler", source.noise_schedule || "");
  confirmedFormValue("confirmedStyleSteps", source.steps);
  confirmedFormValue("confirmedStyleScale", source.scale);
  confirmedFormValue("confirmedStyleCfgRescale", source.cfg_rescale);
  confirmedFormValue("confirmedStyleVariety", source.variety_plus === true ? "1" : source.variety_plus === false ? "0" : "unknown");
  setConfirmedModelValue(source.model || "");
  setConfirmedPreview(source.image_url || "", !source.image_url);
  renderConfirmedExcludedTags();
  const title = styleElement("confirmedStyleModalTitle");
  if (title) title.textContent = editing ? "확정 그림체 수정" : item ? "확정 그림체로 추가" : "그림체 직접 추가";
  const choose = styleElement("chooseConfirmedStyleImage");
  if (choose) choose.disabled = editing;
  const chooseFolder = styleElement("chooseConfirmedStyleFolder");
  if (chooseFolder) chooseFolder.disabled = editing;
  const saveAll = styleElement("saveAllConfirmedStyles");
  if (saveAll) saveAll.classList.toggle("hidden", editing || Boolean(item));
  const status = styleElement("confirmedStyleMetadataStatus");
  if (status) status.textContent = editing ? "저장된 정보를 수정합니다." : item ? "원본의 저장 정보를 불러왔습니다." : "PNG 원본이면 NovelAI 설정을 자동으로 읽습니다.";
  const modalStatus = styleElement("confirmedStyleModalStatus");
  if (modalStatus) modalStatus.textContent = "";
  styleState.confirmedFolderPending = false;
  renderConfirmedFolderContents([]);
  setConfirmedImportProgress(0, 0);
  styleElement("confirmedStyleModal")?.classList.remove("hidden");
  renderConfirmedImportNavigator();
}

function closeConfirmedStyleModal() {
  closeConfirmedDuplicateReview();
  closeConfirmedFolderReview();
  styleElement("confirmedStyleModal")?.classList.add("hidden");
  if (styleState.confirmedModalObjectUrl) URL.revokeObjectURL(styleState.confirmedModalObjectUrl);
  styleState.confirmedModalObjectUrl = "";
  styleState.confirmedModalFile = null;
  styleState.confirmedModalPreviewData = null;
  revokeConfirmedImportGroups();
  styleState.confirmedImportGroups = [];
  styleState.confirmedDuplicatePanelOpen = false;
  styleState.confirmedFolderPending = false;
  renderConfirmedFolderContents([]);
  setConfirmedImportProgress(0, 0);
  hidePromptTagAutocomplete();
}

let comparisonStyles = [];
let comparisonGroups = [];
let comparisonSelectedStyleIds = new Set();
let comparisonFocusedStyleId = null;
let comparisonEditingGroupId = null;
let comparisonCharacterPrompts = [];
let comparisonActiveGroupId = null;
let comparisonFocusedResultStyleId = null;

function normalizeComparisonCharacterPrompts(values) {
  if (!Array.isArray(values)) return [];
  return values.map((value) => String(value || "").trim()).filter(Boolean);
}

function readComparisonCharacterPrompts() {
  const target = styleElement("comparisonCharacterPromptList");
  if (!target) return [];
  return normalizeComparisonCharacterPrompts(
    [...target.querySelectorAll("textarea")].map((input) => input.value),
  );
}

function readComparisonCharacterPromptRows() {
  const target = styleElement("comparisonCharacterPromptList");
  if (!target) return [];
  return [...target.querySelectorAll("textarea")].map((input) => input.value);
}

function renderComparisonCharacterPrompts() {
  const target = styleElement("comparisonCharacterPromptList");
  const empty = styleElement("comparisonCharacterPromptEmpty");
  const add = styleElement("addComparisonCharacterPrompt");
  if (!target) return;
  const locked = Boolean(comparisonEditingGroupId);
  target.replaceChildren();
  comparisonCharacterPrompts.forEach((prompt, index) => {
    const row = document.createElement("div");
    row.className = "comparison-character-prompt-row";
    const field = document.createElement("label");
    field.className = "field";
    const title = document.createElement("span");
    title.textContent = `캐릭터 ${index + 1}`;
    const input = document.createElement("textarea");
    input.value = prompt;
    input.autocomplete = "off";
    input.disabled = locked;
    input.addEventListener("input", () => { comparisonCharacterPrompts[index] = input.value; });
    const autocomplete = document.createElement("div");
    autocomplete.className = "autocomplete prompt-tag-autocomplete hidden";
    field.append(title, input, autocomplete);
    bindPromptTagAutocomplete(input);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "삭제";
    remove.disabled = locked;
    remove.addEventListener("click", () => {
      comparisonCharacterPrompts = readComparisonCharacterPromptRows();
      comparisonCharacterPrompts.splice(index, 1);
      renderComparisonCharacterPrompts();
    });
    row.append(field, remove);
    target.append(row);
  });
  if (empty) empty.classList.toggle("hidden", comparisonCharacterPrompts.length > 0);
  if (add) add.disabled = locked || comparisonCharacterPrompts.length >= 6;
}

function addComparisonCharacterPrompt() {
  comparisonCharacterPrompts = readComparisonCharacterPromptRows();
  if (comparisonCharacterPrompts.length >= 6) return;
  comparisonCharacterPrompts.push("");
  renderComparisonCharacterPrompts();
  const inputs = styleElement("comparisonCharacterPromptList")?.querySelectorAll("textarea");
  inputs?.[inputs.length - 1]?.focus();
}

function comparisonTextRow(target, label, value) {
  const row = document.createElement("div");
  const strong = document.createElement("strong");
  const text = document.createElement("pre");
  strong.textContent = label;
  text.textContent = value || "없음";
  row.append(strong, text);
  target.append(row);
}

function renderComparisonStyleDetail(item) {
  const target = styleElement("comparisonStyleDetail");
  if (!target) return;
  target.replaceChildren();
  if (!item) {
    const empty = document.createElement("div");
    empty.className = "latest-result-placeholder";
    empty.textContent = "갤러리의 그림을 클릭하면 상세정보를 표시합니다.";
    target.append(empty);
    return;
  }
  const image = document.createElement("img");
  image.src = item.image_url || "";
  image.alt = item.name || `확정 그림체 #${item.id}`;
  target.append(image);
  comparisonTextRow(target, "이름", item.name || `확정 그림체 #${item.id}`);
  comparisonTextRow(target, "작가 프롬프트", item.artist_prompt);
  comparisonTextRow(target, "퀄리티 프롬프트", item.quality_prompt);
  comparisonTextRow(target, "고정 프롬프트", item.fixed_prompt);
  comparisonTextRow(target, "네거티브 프롬프트", item.negative_prompt);
  comparisonTextRow(target, "생성 설정", `${item.sampler || "기본"} / ${item.noise_schedule || "기본"} · ${item.steps ?? "기본"} steps · CFG ${item.scale ?? "기본"} · Rescale ${item.cfg_rescale ?? "기본"} · Variety+ ${item.variety_plus === true ? "켜짐" : item.variety_plus === false ? "꺼짐" : "기본"} · ${item.model || "기본 모델"}`);
}

function updateComparisonSelectedSummary() {
  const summary = styleElement("comparisonSelectedSummary");
  if (summary) summary.textContent = `${comparisonSelectedStyleIds.size}개 선택`;
}

function renderComparisonPicker() {
  const target = styleElement("comparisonStylePicker");
  if (!target) return;
  const query = (styleElement("comparisonStyleSearch")?.value || "").trim().toLowerCase();
  target.replaceChildren();
  comparisonStyles.filter((item) => `${item.name} ${item.artist_prompt} ${item.quality_prompt} ${item.fixed_prompt} ${item.negative_prompt} ${item.model}`.toLowerCase().includes(query)).forEach((item) => {
    const label = document.createElement("label");
    label.className = "comparison-style-choice";
    label.classList.toggle("selected", comparisonSelectedStyleIds.has(item.id));
    label.classList.toggle("focused", comparisonFocusedStyleId === item.id);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = comparisonSelectedStyleIds.has(item.id);
    const image = document.createElement("img");
    image.src = item.image_url || "";
    image.alt = item.name || `확정 그림체 #${item.id}`;
    const name = document.createElement("strong");
    name.textContent = item.name || `확정 그림체 #${item.id}`;
    const artist = document.createElement("small");
    artist.textContent = item.artist_prompt || "작가 프롬프트 없음";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) comparisonSelectedStyleIds.add(item.id);
      else comparisonSelectedStyleIds.delete(item.id);
      comparisonFocusedStyleId = item.id;
      renderComparisonStyleDetail(item);
      renderComparisonPicker();
      updateComparisonSelectedSummary();
    });
    label.addEventListener("click", () => {
      comparisonFocusedStyleId = item.id;
      renderComparisonStyleDetail(item);
    });
    label.append(checkbox, image, name, artist);
    target.append(label);
  });
  updateComparisonSelectedSummary();
}

function comparisonSetValue(id, value) {
  const element = styleElement(id);
  if (element) element.value = value === null || value === undefined ? "" : String(value);
}

function syncComparisonResolutionFields() {
  const custom = styleElement("comparisonResolution")?.value === "custom";
  styleElement("comparisonCustomResolution")?.classList.toggle("hidden", !custom);
  styleElement("comparisonSeedField")?.classList.toggle("hidden", styleElement("comparisonSeedMode")?.value !== "manual");
}

function toggleComparisonColumn(column) {
  const detail = column === "detail";
  const editor = styleElement("comparisonEditor");
  const panel = styleElement(detail ? "comparisonDetailPanel" : "comparisonSettingsPanel");
  const content = styleElement(detail ? "comparisonDetailContent" : "comparisonSettingsContent");
  const button = styleElement(detail ? "toggleComparisonDetailColumn" : "toggleComparisonSettingsColumn");
  if (!editor || !panel || !content || !button) return;
  const collapsed = !panel.classList.contains("is-collapsed");
  panel.classList.toggle("is-collapsed", collapsed);
  content.classList.toggle("hidden", collapsed);
  editor.classList.toggle(detail ? "detail-collapsed" : "settings-collapsed", collapsed);
  button.setAttribute("aria-expanded", String(!collapsed));
  button.textContent = detail ? (collapsed ? "▶" : "◀") : (collapsed ? "◀" : "▶");
}

async function openComparisonEditor(group = null) {
  comparisonStyles = await apiFetch("/api/confirmed-styles");
  comparisonEditingGroupId = group?.id || null;
  comparisonSelectedStyleIds = new Set(
    (group?.selected_style_ids || group?.results?.map((item) => item.confirmed_style_id) || [])
      .filter(Number.isInteger),
  );
  comparisonFocusedStyleId = comparisonSelectedStyleIds.values().next().value || comparisonStyles[0]?.id || null;
  const defaults = group?.defaults || {};
  comparisonSetValue("comparisonName", group?.name || "새 비교군");
  comparisonSetValue("comparisonFixedPrompt", group?.fixed_prompt || "");
  comparisonCharacterPrompts = normalizeComparisonCharacterPrompts(group?.character_prompts || []);
  renderComparisonCharacterPrompts();
  const preset = ["832x1216", "1216x832", "1024x1024"].includes(`${group?.width}x${group?.height}`) ? `${group.width}x${group.height}` : group ? "custom" : "832x1216";
  comparisonSetValue("comparisonResolution", preset);
  comparisonSetValue("comparisonWidth", group?.width || 832);
  comparisonSetValue("comparisonHeight", group?.height || 1216);
  comparisonSetValue("comparisonSeedMode", group?.seed_mode || "none");
  comparisonSetValue("comparisonSeed", group?.seed || "");
  comparisonSetValue("comparisonDefaultSampler", defaults.sampler || "k_euler_ancestral");
  comparisonSetValue("comparisonDefaultSchedule", defaults.noise_schedule || "karras");
  comparisonSetValue("comparisonDefaultSteps", defaults.steps ?? 28);
  comparisonSetValue("comparisonDefaultScale", defaults.scale ?? 5);
  comparisonSetValue("comparisonDefaultRescale", defaults.cfg_rescale ?? 0);
  comparisonSetValue("comparisonDefaultVariety", defaults.variety_plus ? "1" : "0");
  comparisonSetValue("comparisonDefaultModel", defaults.model || "nai-diffusion-4-5-full");
  ["comparisonName", "comparisonFixedPrompt", "comparisonResolution", "comparisonWidth", "comparisonHeight", "comparisonSeedMode", "comparisonSeed", "comparisonDefaultSampler", "comparisonDefaultSchedule", "comparisonDefaultSteps", "comparisonDefaultScale", "comparisonDefaultRescale", "comparisonDefaultVariety", "comparisonDefaultModel"].forEach((id) => { const element = styleElement(id); if (element) element.disabled = Boolean(group); });
  const save = styleElement("createComparison");
  if (save) save.textContent = group ? "선택 변경 저장" : "선택한 그림체 생성";
  styleElement("comparisonGroups")?.classList.add("hidden");
  styleElement("comparisonGallery")?.classList.add("hidden");
  styleElement("comparisonEditor")?.classList.remove("hidden");
  styleElement("addComparison")?.classList.add("hidden");
  styleElement("backToComparisonList")?.classList.remove("hidden");
  const title = styleElement("comparisonPageTitle");
  if (title) title.textContent = group ? `${group.name} 선택 수정` : "비교군 추가";
  syncComparisonResolutionFields();
  renderComparisonPicker();
  renderComparisonStyleDetail(comparisonStyles.find((item) => item.id === comparisonFocusedStyleId));
}

function closeComparisonEditor() {
  comparisonEditingGroupId = null;
  styleElement("comparisonEditor")?.classList.add("hidden");
  styleElement("comparisonGallery")?.classList.add("hidden");
  styleElement("comparisonGroups")?.classList.remove("hidden");
  styleElement("addComparison")?.classList.remove("hidden");
  styleElement("backToComparisonList")?.classList.add("hidden");
  const title = styleElement("comparisonPageTitle");
  if (title) title.textContent = "비교군 관리";
}

function setComparisonProgress(completed, total, message = "") {
  const panel = styleElement("comparisonProgress");
  const bar = styleElement("comparisonProgressBar");
  const text = styleElement("comparisonProgressText");
  if (!panel || !bar || !text) return;
  const safeTotal = Math.max(1, Number(total) || 0);
  const safeCompleted = Math.max(0, Math.min(safeTotal, Number(completed) || 0));
  panel.classList.remove("hidden");
  bar.max = safeTotal;
  bar.value = safeCompleted;
  text.textContent = message || `${safeCompleted}/${Number(total) || 0}개 생성 완료`;
}

function hideComparisonProgress() {
  styleElement("comparisonProgress")?.classList.add("hidden");
}

function comparisonGroupById(groupId) {
  return comparisonGroups.find((group) => group.id === Number(groupId));
}

function comparisonStyleById(styleId) {
  return comparisonStyles.find((style) => style.id === Number(styleId));
}

async function deleteComparisonGroup(group) {
  if (!group || !await globalThis.appDialog.confirm({
    delete: true,
    delete_category: "comparison_group",
    title: "비교군 삭제",
    message: `${group.name}과 생성된 비교 이미지를 모두 삭제할까요?`,
    confirmLabel: "삭제",
    tone: "danger",
  })) return false;
  await apiFetch(`/api/comparisons/${group.id}`, { method: "DELETE" });
  comparisonActiveGroupId = null;
  closeComparisonEditor();
  await loadComparisons();
  return true;
}

function renderComparisonFolders() {
  const target = styleElement("comparisonGroups");
  if (!target) return;
  target.replaceChildren();
  if (!comparisonGroups.length) {
    const empty = document.createElement("div");
    empty.className = "latest-result-placeholder";
    empty.textContent = "저장된 비교군이 없습니다.";
    target.append(empty);
    return;
  }
  comparisonGroups.forEach((group) => {
    const folder = document.createElement("article");
    folder.className = "comparison-folder";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "comparison-folder-open";
    const preview = document.createElement("div");
    preview.className = "comparison-folder-preview";
    group.results.slice(0, 4).forEach((result) => {
      const image = document.createElement("img");
      image.src = result.image_url;
      image.alt = result.style_name;
      preview.append(image);
    });
    if (!group.results.length) {
      const empty = document.createElement("span");
      empty.className = "comparison-folder-empty";
      empty.textContent = "아직 생성된 그림 없음";
      preview.append(empty);
    }
    const badge = document.createElement("span");
    badge.className = "comparison-folder-badge";
    badge.textContent = "폴더";
    preview.append(badge);
    const meta = document.createElement("div");
    meta.className = "comparison-folder-meta";
    const name = document.createElement("strong");
    name.textContent = group.name;
    const count = document.createElement("small");
    count.textContent = `${group.results.length}/${group.selected_style_ids?.length || group.results.length}개 · ${group.width}×${group.height}`;
    meta.append(name, count);
    open.append(preview, meta);
    open.addEventListener("click", () => openComparisonGallery(group.id));
    const actions = document.createElement("div");
    actions.className = "comparison-folder-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "선택 변경";
    edit.addEventListener("click", () => openComparisonEditor(group));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "삭제";
    remove.addEventListener("click", () => deleteComparisonGroup(group));
    actions.append(edit, remove);
    folder.append(open, actions);
    target.append(folder);
  });
}

function comparisonResultItem(group, styleId) {
  const result = group.results.find((item) => item.confirmed_style_id === styleId);
  return result
    ? { styleId, result, style: comparisonStyleById(styleId), missing: false }
    : { styleId, result: null, style: comparisonStyleById(styleId), missing: true };
}

function renderComparisonResultDetail(group, item) {
  const target = styleElement("comparisonResultDetail");
  if (!target) return;
  target.replaceChildren();
  if (!group || !item) {
    const empty = document.createElement("div");
    empty.className = "latest-result-placeholder";
    empty.textContent = "갤러리의 그림을 선택하세요.";
    target.append(empty);
    return;
  }
  const settings = item.result?.settings || {};
  const style = item.style || {};
  const image = document.createElement("img");
  image.src = item.result?.image_url || style.image_url || "";
  image.alt = item.result?.style_name || style.name || `확정 그림체 #${item.styleId}`;
  const head = document.createElement("div");
  head.className = "comparison-result-detail-head";
  const title = document.createElement("h3");
  title.textContent = item.result?.style_name || style.name || `확정 그림체 #${item.styleId}`;
  const state = document.createElement("small");
  state.textContent = item.missing ? "미생성" : "생성 완료";
  head.append(title, state);
  const actions = document.createElement("div");
  actions.className = "comparison-result-detail-actions";
  const reacquire = document.createElement("button");
  reacquire.type = "button";
  reacquire.className = "primary";
  reacquire.textContent = item.missing ? "이 그림 생성" : "그림 재습득";
  reacquire.addEventListener("click", () => regenerateComparisonStyle(group.id, item.styleId));
  actions.append(reacquire);
  if (item.result) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "그림 삭제";
    remove.addEventListener("click", async () => {
      if (!await globalThis.appDialog.confirm({ delete: true, delete_category: "comparison_result", title: "비교 그림 삭제", message: "이 그림을 삭제할까요? 나중에 다시 생성할 수 있습니다.", confirmLabel: "삭제", tone: "danger" })) return;
      await apiFetch(`/api/comparison-results/${item.result.id}`, { method: "DELETE" });
      comparisonFocusedResultStyleId = item.styleId;
      await loadComparisons({ openGroupId: group.id });
    });
    actions.append(remove);
  }
  const info = document.createElement("div");
  info.className = "comparison-result-info";
  comparisonTextRow(info, "작가 프롬프트", settings.artist_prompt || style.artist_prompt);
  comparisonTextRow(info, "퀄리티 프롬프트", settings.quality_prompt || style.quality_prompt);
  comparisonTextRow(info, "고정 프롬프트", combinePromptSections(settings.style_fixed_prompt || style.fixed_prompt, settings.comparison_fixed_prompt || group.fixed_prompt));
  comparisonTextRow(info, "캐릭터 프롬프트", (settings.character_prompts || group.character_prompts || []).join("\n"));
  comparisonTextRow(info, "네거티브 프롬프트", settings.negative_prompt || style.negative_prompt);
  comparisonTextRow(info, "생성 설정", `${settings.sampler || style.sampler || "기본"} / ${settings.noise_schedule || style.noise_schedule || "기본"} · ${settings.steps ?? style.steps ?? "기본"} steps · CFG ${settings.scale ?? style.scale ?? "기본"} · Rescale ${settings.cfg_rescale ?? style.cfg_rescale ?? "기본"} · Variety+ ${(settings.variety_plus ?? style.variety_plus) ? "켜짐" : "꺼짐"} · ${settings.model || style.model || "기본 모델"} · Seed ${settings.seed ?? "미지정"}`);
  target.append(image, head, actions, info);
}

function renderComparisonGallery(group) {
  const target = styleElement("comparisonResultGallery");
  if (!target || !group) return;
  const selectedIds = group.selected_style_ids?.length
    ? group.selected_style_ids
    : group.results.map((item) => item.confirmed_style_id);
  if (!selectedIds.includes(comparisonFocusedResultStyleId)) {
    comparisonFocusedResultStyleId = selectedIds[0] || null;
  }
  styleElement("comparisonGalleryTitle").textContent = group.name;
  styleElement("comparisonGalleryCount").textContent = `${group.results.length}/${selectedIds.length}개 생성`;
  target.replaceChildren();
  selectedIds.forEach((styleId) => {
    const item = comparisonResultItem(group, styleId);
    const card = document.createElement("button");
    card.type = "button";
    card.className = "comparison-result-card";
    card.classList.toggle("selected", comparisonFocusedResultStyleId === styleId);
    card.classList.toggle("missing", item.missing);
    const image = document.createElement("img");
    image.src = item.result?.image_url || item.style?.image_url || "";
    image.alt = item.result?.style_name || item.style?.name || `확정 그림체 #${styleId}`;
    const name = document.createElement("span");
    name.textContent = image.alt;
    const state = document.createElement("small");
    state.textContent = item.missing ? "미생성 · 클릭하여 확인" : "생성 완료";
    card.append(image, name, state);
    card.addEventListener("click", () => {
      comparisonFocusedResultStyleId = styleId;
      renderComparisonGallery(group);
    });
    target.append(card);
  });
  renderComparisonResultDetail(group, comparisonFocusedResultStyleId ? comparisonResultItem(group, comparisonFocusedResultStyleId) : null);
}

function openComparisonGallery(groupId) {
  const group = comparisonGroupById(groupId);
  if (!group) return;
  comparisonActiveGroupId = group.id;
  styleElement("comparisonGroups")?.classList.add("hidden");
  styleElement("comparisonEditor")?.classList.add("hidden");
  styleElement("comparisonGallery")?.classList.remove("hidden");
  styleElement("addComparison")?.classList.add("hidden");
  styleElement("backToComparisonList")?.classList.remove("hidden");
  styleElement("comparisonPageTitle").textContent = group.name;
  renderComparisonGallery(group);
}

function closeComparisonGallery() {
  comparisonActiveGroupId = null;
  comparisonFocusedResultStyleId = null;
  closeComparisonEditor();
}

function backFromComparisonSubview() {
  const editorOpen = !styleElement("comparisonEditor")?.classList.contains("hidden");
  if (editorOpen && comparisonActiveGroupId && comparisonGroupById(comparisonActiveGroupId)) {
    comparisonEditingGroupId = null;
    openComparisonGallery(comparisonActiveGroupId);
    return;
  }
  if (!styleElement("comparisonGallery")?.classList.contains("hidden")) {
    closeComparisonGallery();
    return;
  }
  closeComparisonEditor();
}

async function loadComparisons({ openGroupId = null } = {}) {
  const [groups, styles] = await Promise.all([
    apiFetch("/api/comparisons"),
    apiFetch("/api/confirmed-styles"),
  ]);
  comparisonGroups = groups;
  comparisonStyles = styles;
  renderComparisonFolders();
  const targetGroupId = openGroupId || comparisonActiveGroupId;
  if (targetGroupId && comparisonGroupById(targetGroupId)) openComparisonGallery(targetGroupId);
}

async function regenerateComparisonStyle(groupId, styleId) {
  const status = styleElement("comparisonStatus");
  setComparisonProgress(0, 1, "그림을 재습득하는 중 · 0/1");
  try {
    await apiFetch(`/api/comparisons/${groupId}/styles/${styleId}/generate`, { method: "POST", body: "{}" });
    comparisonFocusedResultStyleId = styleId;
    setComparisonProgress(1, 1, "그림 재습득 완료 · 1/1");
    if (status) status.textContent = "선택한 그림을 다시 생성했습니다.";
    await loadComparisons({ openGroupId: groupId });
  } catch (error) {
    if (status) status.textContent = error.message;
    setComparisonProgress(0, 1, "그림 재습득 실패");
  }
}

function comparisonRequestPayload(styleIds) {
  return {
    group_id: comparisonEditingGroupId,
    name: styleElement("comparisonName").value,
    style_ids: styleIds,
    fixed_prompt: styleElement("comparisonFixedPrompt").value,
    character_prompts: readComparisonCharacterPrompts(),
    width: Number(styleElement("comparisonWidth").value),
    height: Number(styleElement("comparisonHeight").value),
    seed_mode: styleElement("comparisonSeedMode").value,
    seed: Number(styleElement("comparisonSeed").value) || null,
    defer_generation: true,
    defaults: {
      sampler: styleElement("comparisonDefaultSampler").value,
      noise_schedule: styleElement("comparisonDefaultSchedule").value,
      steps: Number(styleElement("comparisonDefaultSteps").value),
      scale: Number(styleElement("comparisonDefaultScale").value),
      cfg_rescale: Number(styleElement("comparisonDefaultRescale").value),
      variety_plus: styleElement("comparisonDefaultVariety").value === "1",
      model: styleElement("comparisonDefaultModel").value,
    },
  };
}

async function createComparison() {
  const styleIds = [...comparisonSelectedStyleIds];
  const modalStatus = styleElement("comparisonModalStatus");
  const globalStatus = styleElement("comparisonStatus");
  const button = styleElement("createComparison");
  if (!styleIds.length) {
    modalStatus.textContent = "확정 그림체를 한 개 이상 선택하세요.";
    return;
  }
  button.disabled = true;
  let groupId = comparisonEditingGroupId;
  try {
    modalStatus.textContent = "비교군 정보를 저장하는 중…";
    const prepared = await apiFetch("/api/comparisons", {
      method: "POST",
      body: JSON.stringify(comparisonRequestPayload(styleIds)),
    });
    groupId = prepared.id;
    comparisonEditingGroupId = groupId;
    const pending = prepared.pending_style_ids || [];
    let completed = Number(prepared.generated_count) || 0;
    const total = Number(prepared.total_count) || styleIds.length;
    setComparisonProgress(completed, total, `${completed}/${total}개 생성 완료`);
    for (const [index, styleId] of pending.entries()) {
      const style = comparisonStyleById(styleId);
      modalStatus.textContent = `${style?.name || `확정 그림체 #${styleId}`} 생성 중 · ${completed}/${total}`;
      await apiFetch(`/api/comparisons/${groupId}/styles/${styleId}/generate`, { method: "POST", body: "{}" });
      completed += 1;
      setComparisonProgress(completed, total, `${completed}/${total}개 생성 완료`);
      modalStatus.textContent = `${index + 1}/${pending.length}개 새 그림 처리 · 전체 ${completed}/${total}`;
    }
    if (globalStatus) globalStatus.textContent = `비교군 생성 완료 · ${completed}/${total}개`;
    closeComparisonEditor();
    comparisonActiveGroupId = groupId;
    await loadComparisons({ openGroupId: groupId });
  } catch (error) {
    modalStatus.textContent = error.message;
    if (globalStatus) globalStatus.textContent = error.message;
    if (groupId) {
      closeComparisonEditor();
      comparisonActiveGroupId = groupId;
      await loadComparisons({ openGroupId: groupId });
    }
  } finally {
    button.disabled = false;
  }
}

function applyExtractedConfirmedMetadata(metadata) {
  confirmedFormValue("confirmedStyleArtistPrompt", metadata.artist_prompt || "");
  confirmedFormValue("confirmedStyleQualityPrompt", metadata.quality_prompt || "");
  confirmedFormValue("confirmedStyleFixedPrompt", metadata.fixed_prompt || "");
  confirmedFormValue("confirmedStyleCharacterPrompts", (metadata.character_prompts || []).map((entry) => typeof entry === "string" ? entry : entry?.prompt || "").filter(Boolean).join("\n"));
  confirmedFormValue("confirmedStyleNegativePrompt", metadata.negative_prompt || "");
  confirmedFormValue("confirmedStyleSampler", metadata.sampler || "");
  confirmedFormValue("confirmedStyleScheduler", metadata.noise_schedule || "");
  confirmedFormValue("confirmedStyleSteps", metadata.steps);
  confirmedFormValue("confirmedStyleScale", metadata.scale);
  confirmedFormValue("confirmedStyleCfgRescale", metadata.cfg_rescale);
  confirmedFormValue("confirmedStyleVariety", metadata.variety_plus === true ? "1" : metadata.variety_plus === false ? "0" : "unknown");
  setConfirmedModelValue(metadata.model || "");
  styleState.confirmedModalExcludedTags = [...(metadata.excluded_quality_tags || [])];
  styleState.confirmedModalOriginalQualityPrompt = metadata.original_quality_prompt || metadata.quality_prompt || "";
  renderConfirmedExcludedTags();
}

async function extractConfirmedImportFile(file) {
  const form = new FormData();
  form.append("image", file, file.name || "pasted.png");
  const metadata = await apiFetch("/api/confirmed-styles/extract", { method: "POST", body: form });
  metadata.model = normalizeConfirmedModelName(metadata.model);
  return { file, metadata, objectUrl: URL.createObjectURL(file) };
}

function renderConfirmedFolderContents(files) {
  const button = styleElement("confirmedStyleFolderContents");
  const summary = styleElement("confirmedStyleFolderSummary");
  const list = styleElement("confirmedStyleFolderContentsList");
  if (!button || !summary || !list) return;
  const items = [...(files || [])];
  styleState.confirmedFolderPreviewUrls.forEach((url) => URL.revokeObjectURL(url));
  styleState.confirmedFolderPreviewUrls = [];
  styleState.confirmedFolderFiles = items;
  button.classList.toggle("hidden", !items.length);
  button.textContent = items.length ? `폴더 이미지 ${items.length}장 확인` : "";
  summary.textContent = items.length ? `이미지 ${items.length}장 · 썸네일을 누르면 크게 볼 수 있습니다.` : "";
  list.replaceChildren();
  const viewerItems = [];
  items.forEach((file, index) => {
    const objectUrl = URL.createObjectURL(file);
    styleState.confirmedFolderPreviewUrls.push(objectUrl);
    viewerItems.push({
      image_url: objectUrl,
      base_prompt: file.webkitRelativePath || file.name || `이미지 ${index + 1}`,
      negative_prompt: "",
      character_prompts: [],
      width: "?",
      height: "?",
      sampler: "",
      noise_schedule: "",
      steps: "?",
      scale: "?",
      cfg_rescale: "?",
      seed: "?",
    });
    const card = document.createElement("button");
    card.type = "button";
    card.className = "confirmed-style-folder-card";
    const image = document.createElement("img");
    image.src = objectUrl;
    image.loading = "lazy";
    image.alt = file.name || `폴더 이미지 ${index + 1}`;
    const label = document.createElement("span");
    label.textContent = file.webkitRelativePath || file.name || "이름 없는 이미지";
    card.append(image, label);
    card.addEventListener("click", () => openGeneratedImage(viewerItems, index));
    list.append(card);
  });
  if (!items.length) closeConfirmedFolderReview();
}

function openConfirmedFolderReview() {
  if (!styleElement("confirmedStyleFolderContentsList")?.children.length) return;
  styleElement("importConfirmedStyleFolder")?.classList.toggle("hidden", !styleState.confirmedFolderPending);
  styleElement("confirmedStyleFolderModal")?.classList.remove("hidden");
}

function closeConfirmedFolderReview() {
  styleElement("confirmedStyleFolderModal")?.classList.add("hidden");
}

function cancelConfirmedFolderReview() {
  closeConfirmedFolderReview();
  if (!styleState.confirmedFolderPending) return;
  styleState.confirmedFolderPending = false;
  renderConfirmedFolderContents([]);
}

function stageConfirmedFolderFiles(files) {
  const candidates = [...(files || [])].filter((file) => (
    file instanceof Blob && (!file.type || file.type.startsWith("image/"))
  ));
  if (!candidates.length) return;
  styleState.confirmedFolderPending = true;
  renderConfirmedFolderContents(candidates);
  openConfirmedFolderReview();
}

async function confirmConfirmedFolderImport() {
  const files = [...styleState.confirmedFolderFiles];
  if (!files.length) return;
  styleState.confirmedFolderPending = false;
  closeConfirmedFolderReview();
  await useConfirmedStyleFiles(files);
}

function setConfirmedImportProgress(completed, total) {
  const container = styleElement("confirmedStyleImportProgress");
  const bar = styleElement("confirmedStyleImportProgressBar");
  const text = styleElement("confirmedStyleImportProgressText");
  const active = total > 0 && completed < total;
  container?.classList.toggle("hidden", !active);
  styleElement("confirmedStyleImageColumn")?.classList.toggle("importing", active);
  if (bar) {
    bar.max = Math.max(1, total);
    bar.value = Math.max(0, Math.min(completed, total));
  }
  if (text) text.textContent = total
    ? `가져오는 중 ${completed}/${total} · 남음 ${Math.max(0, total - completed)}`
    : "";
}

async function useConfirmedStyleFiles(files, { showFolderContents = false } = {}) {
  if (styleState.confirmedModalEditId || styleState.confirmedImportBusy) return;
  const candidates = [...(files || [])].filter((file) => (
    file instanceof Blob && (!file.type || file.type.startsWith("image/"))
  ));
  if (!candidates.length) return;
  renderConfirmedFolderContents(showFolderContents ? candidates : []);
  const currentCount = styleState.confirmedImportGroups.reduce((total, group) => total + group.items.length, 0);
  if (currentCount + candidates.length > 500) {
    const status = styleElement("confirmedStyleModalStatus");
    if (status) status.textContent = "이미지는 한 번에 최대 500장까지 가져올 수 있습니다.";
    return;
  }
  const oversized = candidates.find((file) => file.size > 32 * 1024 * 1024);
  if (oversized) {
    const status = styleElement("confirmedStyleModalStatus");
    if (status) status.textContent = `${oversized.name || "이미지"}: 32MB 이하여야 합니다.`;
    return;
  }
  styleState.confirmedImportBusy = true;
  styleState.confirmedModalSource = null;
  const status = styleElement("confirmedStyleMetadataStatus");
  const extracted = [];
  let completed = 0;
  setConfirmedImportProgress(completed, candidates.length);
  renderConfirmedImportNavigator();
  try {
    for (let offset = 0; offset < candidates.length; offset += 4) {
      const results = await Promise.allSettled(candidates.slice(offset, offset + 4).map(async (file) => {
        const item = await extractConfirmedImportFile(file);
        completed += 1;
        setConfirmedImportProgress(completed, candidates.length);
        if (status) status.textContent = `이미지 정보를 읽는 중 · ${completed}/${candidates.length} · 남음 ${candidates.length - completed}`;
        return item;
      }));
      results.forEach((result) => {
        if (result.status === "fulfilled") extracted.push(result.value);
      });
      const failure = results.find((result) => result.status === "rejected");
      if (failure) throw failure.reason;
    }
    const incomingGroups = groupConfirmedImportItems(extracted);
    if (status) status.textContent = "이미 추가된 그림체가 있는지 확인하는 중…";
    attachConfirmedStyleSuspects(incomingGroups, await apiFetch("/api/confirmed-styles"));
    incomingGroups.forEach((incoming) => {
      const existing = incoming.signature && styleState.confirmedImportGroups.find((group) => group.signature === incoming.signature);
      if (existing) {
        existing.items.push(...incoming.items);
        existing.suspectedStyles = incoming.suspectedStyles;
      }
      else styleState.confirmedImportGroups.push(incoming);
    });
    if (styleState.confirmedImportGroups.length === incomingGroups.length) {
      selectConfirmedImportItem(0, 0, { capture: false });
    } else {
      renderConfirmedImportNavigator();
    }
    if (status) status.textContent = `${candidates.length}장을 읽어 ${incomingGroups.length}개 그림체 후보로 분류했습니다.`;
  } catch (error) {
    extracted.forEach((item) => URL.revokeObjectURL(item.objectUrl));
    if (status) status.textContent = error.message;
  } finally {
    styleState.confirmedImportBusy = false;
    setConfirmedImportProgress(candidates.length, candidates.length);
    renderConfirmedImportNavigator();
  }
}

async function useConfirmedStyleFile(file) {
  return useConfirmedStyleFiles(file ? [file] : []);
}

function nullableConfirmedNumber(id) {
  const value = styleElement(id)?.value.trim();
  if (!value) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function readConfirmedStyleForm() {
  const variety = styleElement("confirmedStyleVariety")?.value || "unknown";
  return {
    name: styleElement("confirmedStyleName")?.value || "",
    description: styleElement("confirmedStyleDescription")?.value || "",
    artist_prompt: styleElement("confirmedStyleArtistPrompt")?.value || "",
    quality_prompt: styleElement("confirmedStyleQualityPrompt")?.value || "",
    original_quality_prompt: styleState.confirmedModalOriginalQualityPrompt || styleElement("confirmedStyleQualityPrompt")?.value || "",
    excluded_quality_tags: [...styleState.confirmedModalExcludedTags],
    fixed_prompt: styleElement("confirmedStyleFixedPrompt")?.value || "",
    character_prompts: (styleElement("confirmedStyleCharacterPrompts")?.value || "").split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
    negative_prompt: styleElement("confirmedStyleNegativePrompt")?.value || "",
    sampler: styleElement("confirmedStyleSampler")?.value || "",
    noise_schedule: styleElement("confirmedStyleScheduler")?.value || "",
    steps: nullableConfirmedNumber("confirmedStyleSteps"),
    scale: nullableConfirmedNumber("confirmedStyleScale"),
    cfg_rescale: nullableConfirmedNumber("confirmedStyleCfgRescale"),
    variety_plus: variety === "1" ? true : variety === "0" ? false : null,
    model: styleElement("confirmedStyleModel")?.value || "",
  };
}

async function saveConfirmedImportGroups(saveAll) {
  captureConfirmedImportGroupData();
  const selectedIndexes = saveAll
    ? styleState.confirmedImportGroups.map((_, index) => index)
    : [styleState.confirmedImportGroupIndex];
  const selectedGroups = selectedIndexes.map((index) => styleState.confirmedImportGroups[index]).filter(Boolean);
  if (!selectedGroups.length) throw new Error("저장할 그림체 이미지를 추가해 주세요.");
  const form = new FormData();
  const manifest = [];
  let fileIndex = 0;
  selectedGroups.forEach((group) => {
    const fileIndexes = [];
    group.items.forEach((item) => {
      form.append("images", item.file, item.file.name || `import-${fileIndex + 1}.png`);
      fileIndexes.push(fileIndex);
      fileIndex += 1;
    });
    manifest.push({ file_indexes: fileIndexes, data: group.data || group.items[0]?.metadata || {} });
  });
  form.append("manifest", JSON.stringify(manifest));
  const result = await apiFetch("/api/confirmed-styles/import-batch", { method: "POST", body: form });
  selectedIndexes.sort((left, right) => right - left).forEach((index) => {
    const [removed] = styleState.confirmedImportGroups.splice(index, 1);
    if (removed) revokeConfirmedImportGroups([removed]);
  });
  styleState.confirmedImportGroupIndex = Math.min(
    styleState.confirmedImportGroupIndex,
    Math.max(0, styleState.confirmedImportGroups.length - 1),
  );
  styleState.confirmedImportImageIndex = 0;
  return result;
}

async function saveConfirmedStyleFromModal(saveAll = false) {
  const status = styleElement("confirmedStyleModalStatus");
  const data = readConfirmedStyleForm();
  try {
    let result;
    if (styleState.confirmedModalEditId) {
      result = await apiFetch(`/api/confirmed-styles/${styleState.confirmedModalEditId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
    } else if (styleState.confirmedImportGroups.length) {
      result = await saveConfirmedImportGroups(saveAll);
    } else if (styleState.confirmedModalSource) {
      result = await apiFetch("/api/confirmed-styles", {
        method: "POST",
        body: JSON.stringify({ ...data, ...styleState.confirmedModalSource }),
      });
    } else {
      throw new Error("대표 이미지를 추가해 주세요.");
    }
    styleState.managerDirty = true;
    if (styleState.confirmedImportGroups.length && !saveAll) {
      selectConfirmedImportItem(styleState.confirmedImportGroupIndex, 0, { capture: false });
      if (status) status.textContent = "현재 그림체 묶음을 저장했습니다. 남은 묶음을 계속 확인할 수 있습니다.";
    } else {
      closeConfirmedStyleModal();
      setStyleManagerMode("confirmed");
    }
    return result;
  } catch (error) {
    if (status) status.textContent = error.message;
    return null;
  }
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

function syncGenerationRemote() {
  const status = styleElement("generationRemoteStatus");
  const sourceStatus = styleElement("generationStatus");
  if (status) status.textContent = sourceStatus?.textContent || (styleState.generating ? "1장 생성 중..." : "대기 중");
  const one = styleElement("remoteGenerateOne");
  const start = styleElement("remoteStartContinuous");
  const pause = styleElement("remotePauseContinuous");
  const stop = styleElement("remoteStopContinuous");
  if (one) one.disabled = styleState.generating || styleState.running;
  if (start) start.disabled = styleState.generating || styleState.running;
  if (pause) {
    pause.disabled = !styleState.running;
    pause.textContent = styleState.paused ? "계속" : "일시정지";
  }
  if (stop) stop.disabled = !styleState.running;
}

function clampGenerationRemotePosition() {
  const remote = styleElement("generationRemote");
  if (!remote || remote.classList.contains("hidden")) return;
  const rect = remote.getBoundingClientRect();
  const margin = 8;
  const left = Math.min(Math.max(margin, rect.left), Math.max(margin, window.innerWidth - rect.width - margin));
  const top = Math.min(Math.max(margin, rect.top), Math.max(margin, window.innerHeight - rect.height - margin));
  remote.style.left = `${left}px`;
  remote.style.top = `${top}px`;
  remote.style.right = "auto";
  remote.style.bottom = "auto";
  try { localStorage.setItem(GENERATION_REMOTE_POSITION_KEY, JSON.stringify({ left, top })); } catch (_) { /* Storage can be disabled. */ }
}

function restoreGenerationRemotePosition() {
  const remote = styleElement("generationRemote");
  if (!remote || typeof localStorage === "undefined") return;
  try {
    const position = JSON.parse(localStorage.getItem(GENERATION_REMOTE_POSITION_KEY) || "null");
    if (Number.isFinite(Number(position?.left)) && Number.isFinite(Number(position?.top))) {
      remote.style.left = `${Number(position.left)}px`;
      remote.style.top = `${Number(position.top)}px`;
      remote.style.right = "auto";
      remote.style.bottom = "auto";
    }
  } catch (_) { /* Storage can be disabled. */ }
}

function setGenerationPanelCollapsed(collapsed) {
  const layout = styleElement("styleMakerLayout");
  const panel = styleElement("styleMakerGeneration");
  const button = styleElement("toggleGenerationPanel");
  const remote = styleElement("generationRemote");
  const value = Boolean(collapsed);
  if (value) styleState.generationRemoteClosed = false;
  layout?.classList.toggle("generation-collapsed", value);
  panel?.classList.toggle("is-collapsed", value);
  if (button) {
    button.setAttribute("aria-expanded", String(!value));
    button.setAttribute("aria-label", value ? "프롬프트와 생성 펼치기" : "프롬프트와 생성 접기");
    button.title = button.getAttribute("aria-label");
    button.textContent = value ? "‹" : "›";
  }
  if (remote) {
    remote.classList.toggle("hidden", !value || styleState.generationRemoteClosed);
    if (value) {
      restoreGenerationRemotePosition();
      syncGenerationRemote();
      requestAnimationFrame(clampGenerationRemotePosition);
    }
  }
}

function toggleStyleHistory(open) {
  const panel = styleElement("styleMakerHistory");
  const layout = styleElement("styleMakerLayout");
  const button = styleElement("toggleStyleHistory");
  const shouldOpen = open === undefined ? panel?.classList.contains("history-collapsed") : Boolean(open);
  panel?.classList.toggle("history-collapsed", !shouldOpen);
  layout?.classList.toggle("history-open", shouldOpen);
  if (button) {
    button.setAttribute("aria-expanded", String(shouldOpen));
    button.setAttribute("aria-label", shouldOpen ? "히스토리 닫기" : "히스토리 열기");
    button.title = button.getAttribute("aria-label");
  }
  if (shouldOpen) loadStyleHistory();
}

function setupGenerationRemoteDrag() {
  const remote = styleElement("generationRemote");
  const handle = styleElement("generationRemoteHandle");
  if (!remote || !handle || handle.dataset.bound === "true") return;
  handle.dataset.bound = "true";
  let startX = 0;
  let startY = 0;
  let originLeft = 0;
  let originTop = 0;
  const finish = () => {
    styleState.generationRemoteDragging = false;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    clampGenerationRemotePosition();
  };
  const move = (event) => {
    if (!styleState.generationRemoteDragging) return;
    remote.style.left = `${originLeft + event.clientX - startX}px`;
    remote.style.top = `${originTop + event.clientY - startY}px`;
    remote.style.right = "auto";
    remote.style.bottom = "auto";
  };
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    const rect = remote.getBoundingClientRect();
    startX = event.clientX;
    startY = event.clientY;
    originLeft = rect.left;
    originTop = rect.top;
    styleState.generationRemoteDragging = true;
    handle.setPointerCapture?.(event.pointerId);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
    event.preventDefault();
  });
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    const rect = remote.getBoundingClientRect();
    const delta = event.shiftKey ? 40 : 10;
    const x = rect.left + (event.key === "ArrowLeft" ? -delta : event.key === "ArrowRight" ? delta : 0);
    const y = rect.top + (event.key === "ArrowUp" ? -delta : event.key === "ArrowDown" ? delta : 0);
    remote.style.left = `${x}px`;
    remote.style.top = `${y}px`;
    remote.style.right = "auto";
    remote.style.bottom = "auto";
    clampGenerationRemotePosition();
    event.preventDefault();
  });
}

function toggleGenerationRemote() {
  const remote = styleElement("generationRemote");
  const button = styleElement("toggleGenerationRemote");
  if (!remote || !button) return;
  styleState.generationRemoteCollapsed = !styleState.generationRemoteCollapsed;
  remote.classList.toggle("is-collapsed", styleState.generationRemoteCollapsed);
  button.setAttribute("aria-expanded", String(!styleState.generationRemoteCollapsed));
  button.setAttribute("aria-label", styleState.generationRemoteCollapsed ? "리모콘 펼치기" : "리모콘 접기");
  button.title = button.getAttribute("aria-label");
  button.textContent = styleState.generationRemoteCollapsed ? "+" : "−";
  requestAnimationFrame(clampGenerationRemotePosition);
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
    if (event.target.value !== "shared_dependency") {
      styleState.sharedDependencyReferenceId = null;
      styleState.sharedDependencyReference = null;
      styleState.sharedDependencyReferenceMode = "random";
      styleState.sharedDependencyScale = null;
      styleState.sharedDependencyCfgRescale = null;
    }
    styleElement("customRangeSection")?.classList.toggle("hidden", event.target.value !== "custom");
    syncSharedDependencyControls();
    renderWeightGraph();
    renderWeightProfilePreview();
  });
  styleElement("openSharedDependencyReference")?.addEventListener("click", openSharedDependencyReferenceModal);
  styleElement("randomizeSharedDependencyReference")?.addEventListener("click", randomizeSharedDependencyReference);
  styleElement("clearSharedDependencyReference")?.addEventListener("click", clearSharedDependencyReference);
  styleElement("closeSharedDependencyReference")?.addEventListener("click", closeSharedDependencyReferenceModal);
  styleElement("chooseRandomSharedDependencyReference")?.addEventListener("click", () => {
    void randomizeSharedDependencyReference();
    styleState.sharedDependencyReferenceMode = "random";
    renderSharedDependencyReferenceSummary();
  });
  styleElement("rerollSharedDependencyReference")?.addEventListener("click", () => void randomizeSharedDependencyReference());
  styleElement("sharedDependencyReferenceSearch")?.addEventListener("input", () => {
    clearTimeout(styleState.managerFilterTimer);
    styleState.managerFilterTimer = setTimeout(() => {
      styleState.sharedDependencyPickerPage = 1;
      void loadSharedDependencyReferencePage(1);
    }, 220);
  });
  styleElement("sharedDependencyReferencePrev")?.addEventListener("click", () => {
    void loadSharedDependencyReferencePage(styleState.sharedDependencyPickerPage - 1);
  });
  styleElement("sharedDependencyReferenceNext")?.addEventListener("click", () => {
    void loadSharedDependencyReferencePage(styleState.sharedDependencyPickerPage + 1);
  });
  document.querySelectorAll("[data-close-shared-dependency-reference]").forEach((item) => item.addEventListener("click", closeSharedDependencyReferenceModal));
  styleElement("addWeightRange")?.addEventListener("click", addWeightRange);
  styleElement("toggleStyleSettings")?.addEventListener("click", toggleStyleSettings);
  styleElement("rerollStyleArtists")?.addEventListener("click", () => loadStyleArtists("artists"));
  styleElement("rerollStyleWeights")?.addEventListener("click", () => loadStyleArtists("weights"));
  styleElement("rerollStyleAll")?.addEventListener("click", () => loadStyleArtists("all"));
  document.querySelectorAll("[data-weight-table-sort]").forEach((button) => button.addEventListener("click", cycleWeightTableSort));
  styleElement("styleArtistSearch")?.addEventListener("input", () => {
    renderRatedArtistSelect();
    clearTimeout(styleState.styleArtistAutocompleteTimer);
    styleState.styleArtistAutocompleteTimer = setTimeout(updateStyleArtistAutocomplete, 220);
  });
  styleElement("styleArtistSearch")?.addEventListener("keydown", handleStyleArtistAutocompleteKeydown);
  styleElement("styleArtistSelect")?.addEventListener("change", (event) => {
    const input = styleElement("styleArtistSearch");
    if (input && event.target.value) input.value = event.target.value;
  });
  styleElement("addStyleArtist")?.addEventListener("click", () => addStyleArtist("main"));
  styleElement("openWeightTable")?.addEventListener("click", openWeightTableModal);
  styleElement("closeWeightTable")?.addEventListener("click", closeWeightTableModal);
  document.querySelectorAll("[data-close-weight-table]").forEach((item) => item.addEventListener("click", closeWeightTableModal));
  styleElement("weightTableArtistSearch")?.addEventListener("input", () => {
    renderRatedArtistSelect();
    clearTimeout(styleState.styleArtistAutocompleteTimer);
    styleState.styleArtistAutocompleteTimer = setTimeout(() => updateStyleArtistAutocomplete("modal"), 220);
  });
  styleElement("weightTableArtistSearch")?.addEventListener("keydown", (event) => handleStyleArtistAutocompleteKeydown(event, "modal"));
  styleElement("weightTableArtistSelect")?.addEventListener("change", (event) => {
    const input = styleElement("weightTableArtistSearch");
    if (input && event.target.value) input.value = event.target.value;
  });
  styleElement("weightTableAddArtist")?.addEventListener("click", () => addStyleArtist("modal"));
  styleElement("openRatingTagRules")?.addEventListener("click", openRatingTagRulesModal);
  styleElement("closeRatingTagRules")?.addEventListener("click", closeRatingTagRulesModal);
  styleElement("cancelRatingTagRules")?.addEventListener("click", closeRatingTagRulesModal);
  document.querySelectorAll("[data-close-rating-tag-rules]").forEach((item) => item.addEventListener("click", closeRatingTagRulesModal));
  styleElement("addRatingTagRule")?.addEventListener("click", addRatingTagRule);
  styleElement("addRatingTagExclusion")?.addEventListener("click", addRatingTagExclusion);
  styleElement("saveRatingTagRules")?.addEventListener("click", saveRatingTagRules);
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
  styleElement("togglePromptView")?.addEventListener("click", (event) => {
    setPromptViewMode(event.currentTarget.dataset.mode === "text" ? "buttons" : "text");
  });
  ["basePrompt", "negativePrompt"].forEach((id) => styleElement(id)?.addEventListener("input", () => {
    fixPromptPresetAfterManualEdit();
    persistAndRenderPromptControls();
  }));
  styleElement("fixedPrompt")?.addEventListener("input", savePromptDraft);
  ["basePrompt", "fixedPrompt", "negativePrompt"]
    .forEach((id) => bindPromptTagAutocomplete(styleElement(id)));
  styleElement("openPromptPresetModal")?.addEventListener("click", openPromptPresetModal);
  styleElement("closePromptPresetModal")?.addEventListener("click", closePromptPresetModal);
  styleElement("cancelPromptPresetModal")?.addEventListener("click", closePromptPresetModal);
  document.querySelectorAll("[data-close-prompt-preset]").forEach((item) => item.addEventListener("click", closePromptPresetModal));
  styleElement("promptPresetQualityEditor")?.addEventListener("input", updatePromptPresetFullPreview);
  styleElement("saveAndApplyPromptPreset")?.addEventListener("click", saveAndApplyPromptPreset);
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
    if (event.target.value !== "custom") {
      const [width, height] = event.target.value.split("x");
      styleElement("generationWidth").value = width;
      styleElement("generationHeight").value = height;
    }
    savePromptDraft();
  });
  [["generationScaleRange", "generationScale"], ["generationCfgRescaleRange", "generationCfgRescale"]].forEach(([rangeId, numberId]) => {
    const range = styleElement(rangeId);
    const number = styleElement(numberId);
    range?.addEventListener("input", () => { number.value = range.value; savePromptDraft(); });
    number?.addEventListener("input", () => { range.value = number.value; savePromptDraft(); });
  });
  styleElement("generateOne")?.addEventListener("click", () => generateOneRandomizedStyle().catch(() => {}));
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
    savePromptDraft();
  });
  document.querySelectorAll("[data-random-target]").forEach((button) => {
    button.addEventListener("click", () => {
      const active = button.getAttribute("aria-pressed") !== "true";
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
      savePromptDraft();
    });
  });
  document.addEventListener("pointerdown", (event) => {
    const target = event.target;
    const artistInput = styleElement("styleArtistSearch");
    const artistBox = styleElement("styleArtistAutocomplete");
    if (!artistInput?.contains(target) && !artistBox?.contains(target)) hideStyleArtistAutocomplete();

    const promptInput = styleState.promptTagAutocompleteInput;
    const promptBox = styleState.promptTagAutocompleteBox;
    if (promptInput && !promptInput.contains(target) && !promptBox?.contains(target)) {
      hidePromptTagAutocomplete();
    }
  });
  [
    "generationWidth",
    "generationHeight",
    "generationSampler",
    "generationScheduler",
    "generationSteps",
    "generationVarietyPlus",
    "generationSeed",
    "generationSeedFixed",
    "generationCount",
    "sharedStyleArtistMin",
    "sharedStyleArtistMax",
    "sharedDependencyFixedRatio",
    "sharedDependencyReferenceRatio",
    "sharedDependencyRatedRatio",
    "sharedDependencyOtherRatio",
    "sharedDependencyArtistPolicy",
  ].forEach((id) => styleElement(id)?.addEventListener("change", () => {
    savePromptDraft();
    renderRatingTagRuleCountSummary();
    if (id === "sharedDependencyArtistPolicy") {
      styleState.sharedDependencyArtistPolicy = normalizeSharedDependencyArtistPolicy(styleElement(id)?.value);
    }
    if (id.startsWith("sharedDependency")) renderSharedDependencyRatioSummary();
  }));
  ["styleMinWeight", "styleMaxWeight"].forEach((id) => styleElement(id)?.addEventListener("change", renderWeightGraph));
  styleElement("styleArtistCount")?.addEventListener("change", () => {
    renderWeightGraph();
    renderRatingTagRuleCountSummary();
  });
  styleElement("openWeightGraph")?.addEventListener("click", openWeightGraphModal);
  styleElement("closeWeightGraph")?.addEventListener("click", closeWeightGraphModal);
  document.querySelectorAll("[data-close-weight-graph]").forEach((item) => item.addEventListener("click", closeWeightGraphModal));

  const storedPrompts = loadPromptDraft();
  const storedPreset = loadPromptPresetSettings();
  styleState.selectedPromptPresetKey = storedPreset.selected_key;
  styleState.promptGroups = storedPrompts.prompt_groups;
  applyGenerationSettings(storedPrompts.generation_settings);
  styleElement("basePrompt").value = storedPrompts.base_prompt;
  styleElement("fixedPrompt").value = storedPrompts.fixed_prompt;
  styleElement("negativePrompt").value = storedPrompts.negative_prompt;
  storedPrompts.character_prompts.forEach((value, index) => addCharacterPrompt(value, storedPrompts.character_prompt_ids[index]));
  styleState.promptGroups = cleanPromptGroups(styleState.promptGroups, storedPrompts);
  setPromptViewMode("buttons");
  renderAllPromptTokens();
  renderPromptGroups();
  addWeightRange();
  syncScoreControls();
  renderWeightProfilePreview();
  loadRatedStyleArtists();
  styleState.artists = loadFixedStyleArtists();
  loadStyleArtists();
  renderQueueState();
}

if (typeof document !== "undefined") {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      const isStyleMaker = button.dataset.tab === "style-maker";
      document.body.classList.toggle("style-maker-active", isStyleMaker);
      if (isStyleMaker) initializeStyleMaker();
      if (button.dataset.tab === "style-manager" && styleState.managerDirty) loadStyleManager();
      if (button.dataset.tab === "comparison") loadComparisons();
    });
  });

  styleElement("openSettings")?.addEventListener("click", openSettingsModal);
  styleElement("closeSettings")?.addEventListener("click", closeSettingsModal);
  document.querySelectorAll("[data-close-settings]").forEach((item) => item.addEventListener("click", closeSettingsModal));
  styleElement("saveNovelAiKey")?.addEventListener("click", saveNovelAiKey);
  styleElement("saveAppPreferences")?.addEventListener("click", saveAppPreferences);
  styleElement("selectAllDeleteConfirmations")?.addEventListener("click", () => {
    document.querySelectorAll("[data-delete-confirmation-category]").forEach((checkbox) => { checkbox.checked = true; });
  });
  styleElement("clearAllDeleteConfirmations")?.addEventListener("click", () => {
    document.querySelectorAll("[data-delete-confirmation-category]").forEach((checkbox) => { checkbox.checked = false; });
  });
  styleElement("testNovelAiKey")?.addEventListener("click", testNovelAiKey);
  styleElement("deleteNovelAiKey")?.addEventListener("click", deleteNovelAiKey);
  styleElement("refreshStyleManager")?.addEventListener("click", loadStyleManager);
  document.querySelectorAll("[data-style-manager-mode]").forEach((button) => {
    button.addEventListener("click", () => setStyleManagerMode(button.dataset.styleManagerMode));
  });
  syncStyleManagerFilterControls();
  styleElement("styleManagerSearch")?.addEventListener("input", () => applyStyleManagerFilters({ delayed: true }));
  ["styleManagerScopeFilter", "styleManagerMetadataFilter", "styleManagerRecommendationMin", "styleManagerSort"]
    .forEach((id) => styleElement(id)?.addEventListener("change", () => applyStyleManagerFilters()));
  const managerPageSize = styleElement("styleManagerPageSize");
  if (managerPageSize) {
    try {
      managerPageSize.value = String(normalizeStyleManagerPageSize(localStorage.getItem(STYLE_MANAGER_PAGE_SIZE_KEY)));
    } catch (_) { managerPageSize.value = String(styleState.managerPageSize); }
    styleState.managerPageSize = normalizeStyleManagerPageSize(managerPageSize.value);
    managerPageSize.addEventListener("change", () => {
      styleState.managerPageSize = normalizeStyleManagerPageSize(managerPageSize.value);
      managerPageSize.value = String(styleState.managerPageSize);
      styleState.managerPage = 1;
      resetStyleManagerDetail();
      try { localStorage.setItem(STYLE_MANAGER_PAGE_SIZE_KEY, String(styleState.managerPageSize)); } catch (_) { /* Storage can be disabled. */ }
      if (styleState.managerMode === "shared") loadStyleManager();
      else renderStyleManagerList(styleState.managerStyles);
    });
  }
  const managerCardSize = styleElement("styleManagerCardSize");
  if (managerCardSize) {
    try {
      const storedSize = localStorage.getItem(STYLE_MANAGER_CARD_SIZE_KEY);
      if (["small", "medium", "large"].includes(storedSize)) managerCardSize.value = storedSize;
    } catch (_) { /* Storage can be disabled. */ }
    styleElement("styleManagerList")?.setAttribute("data-card-size", managerCardSize.value);
    managerCardSize.addEventListener("change", () => {
      styleElement("styleManagerList")?.setAttribute("data-card-size", managerCardSize.value);
      try { localStorage.setItem(STYLE_MANAGER_CARD_SIZE_KEY, managerCardSize.value); } catch (_) { /* Storage can be disabled. */ }
    });
  }
  try {
    styleState.managerDescriptions = localStorage.getItem(STYLE_MANAGER_DESCRIPTION_KEY) === "1";
  } catch (_) { styleState.managerDescriptions = false; }
  const descriptionToggle = styleElement("toggleStyleDescriptions");
  if (descriptionToggle) {
    descriptionToggle.checked = styleState.managerDescriptions;
    descriptionToggle.addEventListener("change", () => {
      styleState.managerDescriptions = descriptionToggle.checked;
      try { localStorage.setItem(STYLE_MANAGER_DESCRIPTION_KEY, descriptionToggle.checked ? "1" : "0"); } catch (_) { /* Storage can be disabled. */ }
      renderStyleManagerList(styleState.managerStyles);
    });
  }
  styleElement("addConfirmedStyle")?.addEventListener("click", () => openConfirmedStyleModal());
  styleElement("addComparison")?.addEventListener("click", () => { hideComparisonProgress(); openComparisonEditor(); });
  styleElement("backToComparisonList")?.addEventListener("click", backFromComparisonSubview);
  styleElement("editComparisonSelection")?.addEventListener("click", () => {
    const group = comparisonGroupById(comparisonActiveGroupId);
    if (group) openComparisonEditor(group);
  });
  styleElement("deleteOpenComparison")?.addEventListener("click", () => {
    const group = comparisonGroupById(comparisonActiveGroupId);
    if (group) deleteComparisonGroup(group);
  });
  styleElement("comparisonStyleSearch")?.addEventListener("input", renderComparisonPicker);
  styleElement("toggleComparisonDetailColumn")?.addEventListener("click", () => toggleComparisonColumn("detail"));
  styleElement("toggleComparisonSettingsColumn")?.addEventListener("click", () => toggleComparisonColumn("settings"));
  styleElement("comparisonResolution")?.addEventListener("change", (event) => { const [width, height] = event.target.value.split("x"); if (width && height) { styleElement("comparisonWidth").value = width; styleElement("comparisonHeight").value = height; } syncComparisonResolutionFields(); });
  styleElement("comparisonSeedMode")?.addEventListener("change", syncComparisonResolutionFields);
  bindPromptTagAutocomplete(styleElement("comparisonFixedPrompt"));
  styleElement("addComparisonCharacterPrompt")?.addEventListener("click", addComparisonCharacterPrompt);
  styleElement("createComparison")?.addEventListener("click", createComparison);
  styleElement("styleManagerPrevPage")?.addEventListener("click", () => setStyleManagerPage(styleState.managerPage - 1));
  styleElement("styleManagerNextPage")?.addEventListener("click", () => setStyleManagerPage(styleState.managerPage + 1));
  styleElement("beginStyleSelection")?.addEventListener("click", () => {
    if (!styleState.managerSelectionMode) setStyleSelectionMode(true);
  });
  styleElement("cancelStyleSelection")?.addEventListener("click", () => setStyleSelectionMode(false));
  styleElement("deleteSelectedStyles")?.addEventListener("click", deleteSelectedManagedStyles);
  styleElement("closeConfirmedStyleModal")?.addEventListener("click", closeConfirmedStyleModal);
  styleElement("cancelConfirmedStyle")?.addEventListener("click", closeConfirmedStyleModal);
  document.querySelectorAll("[data-close-confirmed-style]").forEach((item) => item.addEventListener("click", closeConfirmedStyleModal));
  styleElement("saveConfirmedStyle")?.addEventListener("click", () => saveConfirmedStyleFromModal(false));
  styleElement("saveAllConfirmedStyles")?.addEventListener("click", () => saveConfirmedStyleFromModal(true));
  styleElement("chooseConfirmedStyleImage")?.addEventListener("click", () => styleElement("confirmedStyleFile")?.click());
  styleElement("chooseConfirmedStyleFolder")?.addEventListener("click", () => styleElement("confirmedStyleFolder")?.click());
  styleElement("confirmedStyleFile")?.addEventListener("change", (event) => {
    useConfirmedStyleFiles(event.target.files);
    event.target.value = "";
  });
  styleElement("confirmedStyleFolder")?.addEventListener("change", (event) => {
    stageConfirmedFolderFiles(event.target.files);
    event.target.value = "";
  });
  styleElement("confirmedStylePrevGroup")?.addEventListener("click", () => moveConfirmedImportGroup(-1));
  styleElement("confirmedStyleNextGroup")?.addEventListener("click", () => moveConfirmedImportGroup(1));
  styleElement("confirmedStylePrevImage")?.addEventListener("click", () => moveConfirmedImportImage(-1));
  styleElement("confirmedStyleNextImage")?.addEventListener("click", () => moveConfirmedImportImage(1));
  styleElement("splitConfirmedStyleImage")?.addEventListener("click", splitConfirmedImportImage);
  styleElement("removeConfirmedStyleGroup")?.addEventListener("click", removeConfirmedImportGroup);
  styleElement("confirmedStyleDuplicateWarning")?.addEventListener("click", openConfirmedDuplicateReview);
  styleElement("confirmedStyleFolderContents")?.addEventListener("click", openConfirmedFolderReview);
  styleElement("closeConfirmedStyleFolder")?.addEventListener("click", cancelConfirmedFolderReview);
  styleElement("cancelConfirmedStyleFolder")?.addEventListener("click", cancelConfirmedFolderReview);
  styleElement("importConfirmedStyleFolder")?.addEventListener("click", confirmConfirmedFolderImport);
  document.querySelectorAll("[data-close-confirmed-folder]").forEach((item) => item.addEventListener("click", cancelConfirmedFolderReview));
  styleElement("closeConfirmedStyleDuplicate")?.addEventListener("click", closeConfirmedDuplicateReview);
  document.querySelectorAll("[data-close-confirmed-duplicate]").forEach((item) => item.addEventListener("click", closeConfirmedDuplicateReview));
  styleElement("confirmedStyleDuplicatePrevImage")?.addEventListener("click", () => moveConfirmedDuplicateImage(-1));
  styleElement("confirmedStyleDuplicateNextImage")?.addEventListener("click", () => moveConfirmedDuplicateImage(1));
  const confirmedDropZone = styleElement("confirmedStyleDropZone");
  styleElement("confirmedStylePreview")?.addEventListener("click", openConfirmedStylePreview);
  ["dragenter", "dragover"].forEach((eventName) => confirmedDropZone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    confirmedDropZone.classList.add("drag-over");
  }));
  ["dragleave", "drop"].forEach((eventName) => confirmedDropZone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    confirmedDropZone.classList.remove("drag-over");
    if (eventName === "drop" && !styleState.confirmedModalEditId) useConfirmedStyleFiles(event.dataTransfer?.files);
  }));
  ["confirmedStyleArtistPrompt", "confirmedStyleQualityPrompt", "confirmedStyleFixedPrompt", "confirmedStyleCharacterPrompts", "confirmedStyleNegativePrompt"]
    .forEach((id) => bindPromptTagAutocomplete(styleElement(id)));
  document.addEventListener("paste", (event) => {
    const modal = styleElement("confirmedStyleModal");
    if (!modal || modal.classList.contains("hidden") || styleState.confirmedModalEditId) return;
    const files = [...(event.clipboardData?.files || [])].filter((item) => item.type.startsWith("image/"));
    if (files.length) {
      event.preventDefault();
      useConfirmedStyleFiles(files);
    }
  });
  styleElement("generatedImageClose")?.addEventListener("click", closeGeneratedImage);
  document.querySelectorAll("[data-close-generated-image]").forEach((item) => item.addEventListener("click", closeGeneratedImage));
  styleElement("generatedImagePrev")?.addEventListener("click", () => moveGeneratedImage(-1));
  styleElement("generatedImageNext")?.addEventListener("click", () => moveGeneratedImage(1));
  document.addEventListener("keydown", (event) => {
    const sharedDependencyModal = styleElement("sharedDependencyReferenceModal");
    if (sharedDependencyModal && !sharedDependencyModal.classList.contains("hidden")) {
      if (event.key === "Escape") closeSharedDependencyReferenceModal();
      return;
    }
    const promptPresetModal = styleElement("promptPresetModal");
    if (promptPresetModal && !promptPresetModal.classList.contains("hidden")) {
      if (event.key === "Escape") closePromptPresetModal();
      return;
    }
    const imageModal = styleElement("generatedImageModal");
    if (imageModal && !imageModal.classList.contains("hidden")) {
      if (event.key === "Escape") closeGeneratedImage();
      if (event.key === "ArrowLeft") moveGeneratedImage(-1);
      if (event.key === "ArrowRight") moveGeneratedImage(1);
      return;
    }
    const duplicateModal = styleElement("confirmedStyleDuplicateModal");
    if (duplicateModal && !duplicateModal.classList.contains("hidden")) {
      if (event.key === "Escape") closeConfirmedDuplicateReview();
      if (event.key === "ArrowLeft") moveConfirmedDuplicateImage(-1);
      if (event.key === "ArrowRight") moveConfirmedDuplicateImage(1);
      return;
    }
    const folderModal = styleElement("confirmedStyleFolderModal");
    if (folderModal && !folderModal.classList.contains("hidden")) {
      if (event.key === "Escape") cancelConfirmedFolderReview();
      return;
    }
  });
  styleElement("toggleGenerationPanel")?.addEventListener("click", () => {
    setGenerationPanelCollapsed(!styleElement("styleMakerGeneration")?.classList.contains("is-collapsed"));
  });
  styleElement("toggleStyleHistory")?.addEventListener("click", () => toggleStyleHistory());
  styleElement("closeStyleHistory")?.addEventListener("click", () => toggleStyleHistory(false));
  styleElement("refreshStyleHistory")?.addEventListener("click", () => loadStyleHistory({ force: true }));
  styleElement("toggleGenerationRemote")?.addEventListener("click", toggleGenerationRemote);
  styleElement("closeGenerationRemote")?.addEventListener("click", () => {
    styleState.generationRemoteClosed = true;
    styleElement("generationRemote")?.classList.add("hidden");
  });
  styleElement("remoteGenerateOne")?.addEventListener("click", () => generateOneRandomizedStyle().catch(() => {}));
  styleElement("remoteStartContinuous")?.addEventListener("click", runContinuousGeneration);
  styleElement("remotePauseContinuous")?.addEventListener("click", () => {
    styleState.paused = !styleState.paused;
    renderQueueState();
  });
  styleElement("remoteStopContinuous")?.addEventListener("click", () => {
    styleState.stopRequested = true;
    styleState.paused = false;
    renderQueueState();
  });
  setupGenerationRemoteDrag();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    STYLE_REQUEST_CONTROL_IDS,
    CUSTOM_RANGE_FIELDS,
    STYLE_FIXED_ARTISTS_STORAGE_KEY,
    normalizeSharedDependencyArtistPolicy,
    applyStyleRerollResult,
    buildStyleRequestPayload,
    applySharedDependencyReference,
    normalizeStoredFixedStyleArtists,
    saveFixedStyleArtists,
    loadFixedStyleArtists,
    normalizeRandomTargets,
    pickRandomPreset,
    normalizeSelectedScores,
    reorderArtists,
    runLatestStyleRequest,
    sortArtistsByWeight,
    sortFixedArtistEntriesForTable,
    validateCustomRangeValues,
    interpolateWeightProfile,
    formatArtistPromptTag,
    parseStyleArtistNames,
    parseStyleArtistEntries,
    insertStyleArtistsAtPosition,
    updateStyleArtistAtIndex,
    moveStyleArtistToPosition,
    fixedStyleArtistEntries,
    limitArtistsToTotalCount,
    fixedArtistSlotEntries,
    chooseArtistsForPrompt,
    fixedArtistOverlayCoordinates,
    graphInsertionPositionFromRatio,
    openWeightGraphModal,
    moveSelectedArtistsToPosition,
    hasProfileDragMoved,
    normalizeStoredPrompts,
    promptStoragePayload,
    combinePromptSections,
    currentPromptTagFragment,
    replaceCurrentPromptTagFragment,
    formatPromptAutocompleteTag,
    parsePromptTokens,
    appendUniquePromptToken,
    removePromptToken,
    addPromptGroupItem,
    cleanPromptGroups,
    buildEffectivePromptText,
    promptPresetFullText,
    reachedGenerationLimit,
    toggleSelectedStyleId,
    managerCombinedPromptText,
    confirmedGeneratedSourceValues,
    normalizeConfirmedModelName,
    confirmedArtistPromptSignature,
    groupConfirmedImportItems,
    attachConfirmedStyleSuspects,
    filterStyleManagerItems,
    paginateStyleManagerItems,
    normalizeStyleManagerPageSize,
    normalizeRatingTagRules,
    validateRatingTagRules,
    ratingTagRuleCount,
    normalizeRatingExcludeTags,
    validateRatingExcludeTags,
    opusFreeGenerationIssues,
    normalizeStyleHistoryItem,
    styleHistoryArtistPrompt,
    styleHistoryPreviewMeta,
    deleteConfirmationEnabledFromSkip,
    skipDeleteConfirmationFromEnabled,
    normalizeComparisonCharacterPrompts,
    normalizeNumericPromptClosers,
    sharedDependencyParameterValue,
    normalizeSharedDependencyRatios,
    sharedDependencyControlsState,
    normalizeSharedDependencyReferenceItem,
    sharedDependencyReferenceQuery,
    setSharedDependencyReference,
    clearSharedDependencyReference,
    setSharedDependencyReferenceFromArca,
  };
}
