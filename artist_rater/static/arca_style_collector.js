const arcaState = {
  loaded: false, collecting: false, selectedId: null, timer: null, pollTimer: null,
  loginPollTimer: null, activeJobId: null, browserConnected: false,
  pendingCollectionPayload: null, loginImporting: false, browserSessionLoadPromise: null,
  imageRestoreEstimate: null,
  coverageTimer: null, statisticsLoaded: false, statisticsData: null, statisticsView: "artist",
  page: 1, totalPages: 1, totalItems: 0,
  statisticTables: {
    artist: { page: 1, sortKey: "count", sortDirection: "desc" },
    quality: { page: 1, sortKey: "count", sortDirection: "desc" },
  },
};
const arcaEl = (id) => typeof document === "undefined" ? null : document.getElementById(id);

function formatArcaLocalDate(value) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fillMissingArcaDates(value = {}, today = "") {
  return {
    start_date: String(value.start_date || today),
    end_date: String(value.end_date || today),
  };
}

function isArcaCollectionBusy(value) {
  return Boolean(value?.collecting || value?.pendingCollectionPayload);
}

function shouldRefreshArcaBrowserSession(eventType, visibilityState) {
  return eventType === "focus" || (eventType === "visibilitychange" && visibilityState === "visible");
}

function normalizeArcaPayload(value) {
  return {
    keyword: String(value.keyword || "그림체 공유").trim(),
    tabs: value.tabs || [],
    start_date: value.start_date || "",
    end_date: value.end_date || "",
    max_pages: Number(value.max_pages || 0),
    max_posts: Number(value.max_posts || 0),
  };
}

function normalizeArcaUrlPayload(value) {
  return { source_url: String(value || "").trim() };
}

function arcaListQuery(value = {}) {
  const query = new URLSearchParams({
    q: String(value.q || ""),
    metadata: String(value.metadata || "all"),
    sort: String(value.sort || "posted_desc"),
    page: String(Math.max(1, Math.trunc(Number(value.page) || 1))),
    per_page: String(Math.max(1, Math.trunc(Number(value.per_page) || 50))),
  });
  const recommendationMin = String(value.recommendation_min ?? "").trim();
  if (recommendationMin) query.set("recommendation_min", recommendationMin);
  return query;
}

function normalizeArcaStatisticRows(entries, limit = null) {
  const rows = (Array.isArray(entries) ? entries : [])
    .map((entry) => {
      const count = Number(entry?.count);
      const percentage = Number(entry?.percentage);
      const averageWeight = Number(entry?.average_weight);
      const medianWeight = Number(entry?.median_weight);
      const maxWeight = Number(entry?.max_weight);
      const averageRecommendations = entry?.average_recommendations == null ? NaN : Number(entry.average_recommendations);
      const medianRecommendations = entry?.median_recommendations == null ? NaN : Number(entry.median_recommendations);
      const maxRecommendations = entry?.max_recommendations == null ? NaN : Number(entry.max_recommendations);
      return {
        tag: String(entry?.tag || "").trim(),
        count: Number.isFinite(count) ? Math.max(0, Math.trunc(count)) : 0,
        percentage: Number.isFinite(percentage) ? Math.min(100, Math.max(0, percentage)) : 0,
        average_weight: Number.isFinite(averageWeight) ? averageWeight : null,
        median_weight: Number.isFinite(medianWeight) ? medianWeight : null,
        max_weight: Number.isFinite(maxWeight) ? maxWeight : null,
        dominant_weight_range: String(entry?.dominant_weight_range || ""),
        representative_image: entry?.representative_image || null,
        average_recommendations: Number.isFinite(averageRecommendations) ? averageRecommendations : null,
        median_recommendations: Number.isFinite(medianRecommendations) ? medianRecommendations : null,
        max_recommendations: Number.isFinite(maxRecommendations) ? maxRecommendations : null,
      };
    })
    .filter((entry) => entry.tag);
  if (limit == null) return rows;
  const maxRows = Number.isFinite(Number(limit)) ? Math.max(0, Math.trunc(Number(limit))) : rows.length;
  return rows.slice(0, maxRows);
}

function arcaStatisticsSummary(result = {}) {
  const imageCount = Number(result?.analyzed_image_count);
  const postCount = Number(result?.analyzed_post_count);
  const images = Number.isFinite(imageCount) ? Math.max(0, Math.trunc(imageCount)) : 0;
  const posts = Number.isFinite(postCount) ? Math.max(0, Math.trunc(postCount)) : 0;
  if (!images) return "집계할 이미지 프롬프트가 없습니다.";
  return `이미지 프롬프트 ${images.toLocaleString()}개 · 게시글 ${posts.toLocaleString()}개 분석`;
}

function arcaStatisticEntryText(entry) {
  const count = Number.isFinite(Number(entry?.count)) ? Math.max(0, Math.trunc(Number(entry.count))) : 0;
  const percentage = Number.isFinite(Number(entry?.percentage)) ? Math.min(100, Math.max(0, Number(entry.percentage))) : 0;
  const roundedPercentage = Math.round(percentage * 10) / 10;
  const percentageText = Number.isInteger(roundedPercentage) ? String(roundedPercentage) : roundedPercentage.toFixed(1);
  return `이미지 ${count.toLocaleString()}개 · ${percentageText}%`;
}

function formatArcaWeight(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return String(Math.round(number * 1000) / 1000);
}

function formatArcaRecommendation(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return (Math.round(number * 10) / 10).toLocaleString();
}

const ARCA_WEIGHT_RANGE_ORDER = [
  "0 미만", "0.00–0.49", "0.50–0.79", "0.80–0.99", "1.00",
  "1.01–1.19", "1.20–1.49", "1.50–1.99", "2.00 이상",
];

function filterAndSortArcaStatisticRows(entries, options = {}) {
  const query = String(options.query || "").trim().toLocaleLowerCase();
  const range = String(options.range || "");
  const sort = String(options.sort || "count_desc");
  const rangeRank = (value) => {
    const index = ARCA_WEIGHT_RANGE_ORDER.indexOf(String(value || ""));
    return index < 0 ? -1 : index;
  };
  const numeric = (value, fallback = -Infinity) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const rows = normalizeArcaStatisticRows(entries).filter((entry) => (
    (!query || entry.tag.toLocaleLowerCase().includes(query))
    && (!range || entry.dominant_weight_range === range)
  ));
  const comparators = {
    count_desc: (left, right) => right.count - left.count,
    count_asc: (left, right) => left.count - right.count,
    weight_desc: (left, right) => numeric(right.average_weight) - numeric(left.average_weight),
    weight_asc: (left, right) => numeric(left.average_weight, Infinity) - numeric(right.average_weight, Infinity),
    range_desc: (left, right) => rangeRank(right.dominant_weight_range) - rangeRank(left.dominant_weight_range),
    range_asc: (left, right) => rangeRank(left.dominant_weight_range) - rangeRank(right.dominant_weight_range),
    recommendation_desc: (left, right) => numeric(right.average_recommendations) - numeric(left.average_recommendations),
    recommendation_asc: (left, right) => numeric(left.average_recommendations, Infinity) - numeric(right.average_recommendations, Infinity),
    recommendation_max_desc: (left, right) => numeric(right.max_recommendations) - numeric(left.max_recommendations),
    recommendation_max_asc: (left, right) => numeric(left.max_recommendations, Infinity) - numeric(right.max_recommendations, Infinity),
    percentage_desc: (left, right) => right.percentage - left.percentage,
    percentage_asc: (left, right) => left.percentage - right.percentage,
    tag_asc: (left, right) => left.tag.localeCompare(right.tag),
    tag_desc: (left, right) => right.tag.localeCompare(left.tag),
  };
  const compare = comparators[sort] || comparators.count_desc;
  return rows.sort((left, right) => compare(left, right) || right.count - left.count || left.tag.localeCompare(right.tag));
}

function paginateArcaStatisticRows(entries, page = 1, perPage = 40) {
  const rows = Array.isArray(entries) ? entries : [];
  const size = Math.max(1, Math.trunc(Number(perPage) || 40));
  const totalPages = Math.max(1, Math.ceil(rows.length / size));
  const currentPage = Math.min(Math.max(1, Math.trunc(Number(page) || 1)), totalPages);
  return {
    rows: rows.slice((currentPage - 1) * size, currentPage * size),
    page: currentPage,
    perPage: size,
    total: rows.length,
    totalPages,
  };
}

function filterArcaStatisticRows(entries, query = "") {
  return filterAndSortArcaStatisticRows(entries, { query });
}

function appendArcaRecommendationQuery(query, filters = {}) {
  const recommendationQuery = arcaStatisticsQuery(filters);
  for (const [key, value] of recommendationQuery) query.set(key, value);
  return query;
}

function arcaTagDetailQuery(kind, tag, limit = 24, filters = {}) {
  return appendArcaRecommendationQuery(
    new URLSearchParams({ kind: String(kind || ""), tag: String(tag || ""), limit: String(limit) }),
    filters,
  );
}

function arcaStatisticsQuery(value = {}) {
  const query = new URLSearchParams();
  const minimum = String(value.recommendation_min ?? "").trim();
  const maximum = String(value.recommendation_max ?? "").trim();
  if (minimum) query.set("recommendation_min", minimum);
  if (maximum) query.set("recommendation_max", maximum);
  return query;
}

function arcaRecommendationPreset(preset) {
  if (preset === "all") return { recommendation_min: "", recommendation_max: "" };
  if (["10", "30", "50", "100"].includes(String(preset))) {
    return { recommendation_min: String(preset), recommendation_max: "" };
  }
  return null;
}

function arcaSequenceDetailQuery(tags, limit = 40, filters = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  for (const tag of tags || []) query.append("tag", String(tag));
  return appendArcaRecommendationQuery(query, filters);
}

function randomArcaStatisticsSamples(entries, limit = 8, random = Math.random) {
  const pool = (Array.isArray(entries) ? entries : []).filter((entry) => entry?.representative_image?.image_url).slice();
  for (let index = pool.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.max(0, Math.min(0.999999, Number(random()) || 0)) * (index + 1));
    [pool[index], pool[swapIndex]] = [pool[swapIndex], pool[index]];
  }
  return pool.slice(0, Math.max(0, Number(limit) || 0));
}

function arcaCoverageQuery(value = {}) {
  const query = new URLSearchParams({
    keyword: String(value.keyword || "그림체 공유"),
    start_date: String(value.start_date || ""),
    end_date: String(value.end_date || ""),
    max_pages: String(value.max_pages || 0),
    max_posts: String(value.max_posts || 0),
  });
  for (const tab of value.tabs || []) query.append("tabs", tab);
  return query;
}

function arcaCoverageText(result) {
  const coverage = result?.coverage || [];
  if (!coverage.length) return "이 조건으로 완료한 수집 기록이 없습니다.";
  const ranges = coverage.map((entry) => entry.start_date === entry.end_date
    ? entry.start_date
    : `${entry.start_date} ~ ${entry.end_date}`);
  return `완료한 범위: ${ranges.join(", ")}`;
}

function arcaBrowserSessionText(status) {
  if (status?.connected) return `${status.browser || "브라우저"} 로그인 연결됨`;
  return status?.message || status?.error || "브라우저 로그인 연결 안 됨";
}

function isArcaBrowserSessionPending(status) {
  return ["opening", "waiting"].includes(status?.state);
}

function arcaBrowserSessionAction(status, hasPendingCollection = false) {
  if (status?.connected) return hasPendingCollection ? "resume" : "settled";
  if (isArcaBrowserSessionPending(status)) return "poll";
  return hasPendingCollection ? "clear" : "settled";
}

function arcaSummaryText(result) {
  if (result.error) return String(result.error);
  if (result.job_type === "image_archive") {
    return `공유 그림체 이미지 ${result.downloaded_images || 0}장을 ZIP에서 설치했습니다.`;
  }
  if (result.job_type === "image_url_refresh") {
    return result.skipped_existing
      ? "받을 이미지가 없습니다."
      : `게시글 ${result.scanned_posts || 0}개를 확인하고 이미지 URL ${result.updated || 0}개를 갱신했습니다.`;
  }
  if (result.job_type === "image_restore") {
    return result.skipped_existing
      ? "받을 이미지가 없습니다."
      : `이미지 ${result.downloaded_images || 0}개를 복원했습니다.`;
  }
  return result.skipped_existing
    ? "이미 검색한 범위입니다. 저장된 목록을 표시합니다."
    : `페이지 ${result.scanned_pages || 0} · 글 ${result.scanned_posts || 0} · 신규 ${result.saved || 0} · 갱신 ${result.updated || 0}`;
}

function collectionProgress(job) {
  if (job?.status === "completed" && job?.skipped_existing) {
    return { determinate: true, percent: 100 };
  }
  if (job?.job_type === "image_archive") {
    if (job.stage === "downloading_archive") {
      const bytes = job?.progress?.bytes || [0, null];
      const done = Number(bytes[0] || 0);
      const total = bytes[1] == null ? null : Number(bytes[1]);
      return total && Number.isFinite(total)
        ? { determinate: true, percent: Math.min(100, Math.round(done * 100 / total)) }
        : { determinate: false, percent: 0 };
    }
    if (job.stage === "verifying_archive") return { determinate: false, percent: 0 };
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

function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let scaled = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && scaled >= 1024; index += 1) {
    scaled /= 1024;
    unit = units[index];
  }
  return `${scaled >= 10 ? scaled.toFixed(1) : scaled.toFixed(2)} ${unit}`;
}

function imageRestoreEstimateText(estimate) {
  const missing = Number(estimate?.missing_images || 0);
  const local = Number(estimate?.local_images || 0);
  if (!missing) return `모든 이미지가 준비되어 있습니다 · 저장됨 ${local.toLocaleString()}장`;
  const basis = estimate?.estimate_source === "local_average" ? "현재 파일 평균 기준" : "이미지당 4 MB 기준";
  return `누락 ${missing.toLocaleString()}장 · 예상 ${formatBytes(estimate?.estimated_download_bytes)} · 약 ${durationText(estimate?.estimated_seconds)} (${basis}, 사이트 제한·인터넷 속도에 따라 달라짐)`;
}

function imageDownloadSummary(estimate) {
  const total = Number(estimate?.total_images || 0);
  const local = Number(estimate?.local_images || 0);
  const missing = Number(estimate?.missing_images || 0);
  const completed = total > 0 && missing === 0;
  return {
    completed,
    text: completed
      ? `이미지 ${local.toLocaleString()}장 준비됨 · 필요할 때 열기`
      : `누락 ${missing.toLocaleString()}장 · 설치 방법 보기`,
  };
}

function updateArcaImageDownloadDisclosure(estimate) {
  const state = imageDownloadSummary(estimate);
  const details = arcaEl("arcaImageDownloadOptions");
  const summary = arcaEl("arcaImageDownloadSummary");
  if (summary) summary.textContent = state.text;
  if (details) details.open = !state.completed;
}

function collectionCountsText(job) {
  if (job?.status === "completed" && job?.skipped_existing) {
    return "이미 수집한 기간 · 새 요청 없음";
  }
  const progress = job?.progress || {};
  const pages = progress.pages || [0, null];
  const posts = progress.posts || [0, null];
  const total = (pair) => pair[1] == null ? "?" : pair[1];
  if (job?.job_type === "image_archive") {
    const bytes = progress.bytes || [job?.downloaded_bytes || 0, job?.estimated_bytes ?? null];
    if (job.stage === "downloading_archive") {
      return `ZIP 다운로드 ${formatBytes(bytes[0])}/${bytes[1] == null ? "?" : formatBytes(bytes[1])}`;
    }
    if (job.stage === "verifying_archive") return "ZIP SHA-256 및 매니페스트 확인 중";
    return `압축 해제 ${posts[0] || 0}/${total(posts)} · 준비 ${progress.images || 0}장`;
  }
  if (job?.job_type === "image_url_refresh") {
    return `게시글 주소 갱신 ${posts[0] || 0}/${total(posts)} · 이미지 URL ${job.updated || 0}개`;
  }
  if (job?.job_type === "image_restore") {
    const bytes = progress.bytes || [job?.downloaded_bytes || 0, job?.estimated_bytes ?? null];
    const byteTotal = bytes[1] == null ? "?" : formatBytes(bytes[1]);
    return `이미지 확인 ${posts[0] || 0}/${total(posts)} · 복원 ${progress.images || 0}장 · ${formatBytes(bytes[0])}/${byteTotal}`;
  }
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

function initializeArcaDateInputs() {
  const start = arcaEl("arcaStartDate");
  const end = arcaEl("arcaEndDate");
  const dates = fillMissingArcaDates(
    { start_date: start?.value, end_date: end?.value },
    formatArcaLocalDate(new Date()),
  );
  if (start && !start.value) start.value = dates.start_date;
  if (end && !end.value) end.value = dates.end_date;
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
  const labels = {
    queued: "대기", running: "수집 중", pause_requested: "일시정지 중…", paused: "일시정지",
    stop_requested: "중지 중…", stopped: "중지됨", completed: "완료", failed: "실패", interrupted: "중단됨",
  };
  const progress = collectionProgress(job);
  const bar = arcaEl("arcaCollectionProgress");
  arcaEl("arcaCollectionState").textContent = job.job_type === "image_archive" && job.status === "running"
    ? job.stage === "downloading_archive" ? "ZIP 다운로드 중"
      : job.stage === "verifying_archive" ? "ZIP 검증 중"
        : "ZIP 압축 해제 중"
    : job.job_type === "image_restore" && job.status === "running"
    ? "이미지 복원 중"
    : job.job_type === "image_url_refresh" && job.status === "running"
      ? "최신 이미지 주소 확인 중"
      : labels[job.status] || job.status;
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
  const running = ["queued", "running"].includes(job.status);
  const pausing = ["pause_requested", "paused"].includes(job.status);
  const stopping = job.status === "stop_requested";
  const resumable = ["paused", "interrupted", "stopped", "failed"].includes(job.status);
  arcaEl("pauseArcaCollection")?.classList.toggle("hidden", !running);
  arcaEl("resumeArcaCollection")?.classList.toggle("hidden", !resumable);
  arcaEl("stopArcaCollection")?.classList.toggle("hidden", !(running || pausing || stopping));
}

function setArcaCollectionControlsDisabled(disabled) {
  for (const id of ["collectArcaStyles", "restoreArcaImages", "confirmRestoreArcaImages", "cancelRestoreArcaImages", "downloadArcaImageArchive", "chooseArcaImageArchive", "arcaImageArchiveFile", "arcaTabNai", "arcaTabR18Nai", "arcaStartDate", "arcaEndDate", "collectArcaUrl", "arcaDirectUrl", "importArcaBrowserSession", "setupArcaSessionBridge", "refreshArcaBrowserSession"]) {
    const element = arcaEl(id);
    if (element) element.disabled = disabled;
  }
}

function renderArcaBrowserSession(status) {
  arcaState.browserConnected = Boolean(status?.connected);
  arcaSetStatus("arcaBrowserSessionState", arcaBrowserSessionText(status), status?.connected ? "ok" : status?.error ? "error" : "");
}

function clearArcaBrowserSessionPoll() {
  clearTimeout(arcaState.loginPollTimer);
  arcaState.loginPollTimer = null;
}

function clearPendingArcaCollection() {
  const hadPendingCollection = Boolean(arcaState.pendingCollectionPayload);
  arcaState.pendingCollectionPayload = null;
  if (hadPendingCollection && !arcaState.collecting) setArcaCollectionControlsDisabled(false);
}

async function resumePendingArcaCollection() {
  if (!arcaState.pendingCollectionPayload || arcaState.collecting) return;
  const payload = arcaState.pendingCollectionPayload;
  arcaState.pendingCollectionPayload = null;
  await runArcaCollection(payload);
}

async function handleArcaBrowserSessionStatus(status, forceClearPending = false) {
  renderArcaBrowserSession(status);
  const action = arcaBrowserSessionAction(status, Boolean(arcaState.pendingCollectionPayload));
  if (action === "poll") {
    scheduleArcaBrowserSessionPoll();
    return;
  }
  clearArcaBrowserSessionPoll();
  if (action === "resume") {
    await resumePendingArcaCollection();
  } else if (action === "clear") {
    if (forceClearPending || !arcaState.loginImporting) {
      clearPendingArcaCollection();
    }
  }
}

async function loadArcaBrowserSession() {
  if (arcaState.browserSessionLoadPromise) return arcaState.browserSessionLoadPromise;
  arcaState.browserSessionLoadPromise = (async () => {
    try {
      const status = await arcaFetch("/api/arca-styles/browser-session");
      await handleArcaBrowserSessionStatus(status);
    } catch (error) {
      clearArcaBrowserSessionPoll();
      renderArcaBrowserSession({ connected: false, error: error.message });
      if (!arcaState.loginImporting) clearPendingArcaCollection();
    }
  })();
  try {
    return await arcaState.browserSessionLoadPromise;
  } finally {
    arcaState.browserSessionLoadPromise = null;
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
  if (arcaState.loginImporting) return;
  arcaState.loginImporting = true;
  const button = arcaEl("importArcaBrowserSession");
  if (button) button.disabled = true;
  arcaSetStatus("arcaBrowserSessionState", "Chrome과 Edge에서 로그인 확인 중…");
  try {
    const status = await arcaFetch("/api/arca-styles/browser-session/import", { method: "POST" });
    await handleArcaBrowserSessionStatus(status, true);
  } catch (error) {
    renderArcaBrowserSession({ connected: false, error: error.message });
    clearArcaBrowserSessionPoll();
    clearPendingArcaCollection();
  } finally {
    arcaState.loginImporting = false;
    if (button) button.disabled = Boolean(arcaState.collecting || arcaState.pendingCollectionPayload);
  }
}

async function setupArcaSessionBridge() {
  const button = arcaEl("setupArcaSessionBridge");
  if (button) button.disabled = true;
  arcaSetStatus("arcaSessionBridgeSetupStatus", "확장 폴더를 준비하는 중…");
  try {
    const result = await arcaFetch("/api/arca-styles/browser-session/extension/setup", { method: "POST" });
    const path = String(result.path || "");
    let copied = false;
    if (path && typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(path);
        copied = true;
      } catch (_error) {
        copied = false;
      }
    }
    const suffix = copied ? " 폴더 경로도 복사했습니다." : path ? ` 선택할 폴더: ${path}` : "";
    arcaSetStatus("arcaSessionBridgeSetupStatus", `설치 폴더를 열었습니다.${suffix}`, "success");
  } catch (error) {
    arcaSetStatus("arcaSessionBridgeSetupStatus", error.message, "error");
  } finally {
    if (button) button.disabled = isArcaCollectionBusy(arcaState);
  }
}

async function loadArcaSearchCoverage() {
  try {
    const query = arcaCoverageQuery(arcaPayload());
    const result = await arcaFetch(`/api/arca-styles/search-status?${query}`);
    arcaSetStatus("arcaSearchCoverage", arcaCoverageText(result));
  } catch (error) {
    arcaSetStatus("arcaSearchCoverage", error.message, "error");
  }
}

async function loadArcaImageRestoreEstimate() {
  const element = arcaEl("arcaImageRestoreEstimate");
  const button = arcaEl("restoreArcaImages");
  const confirmButton = arcaEl("confirmRestoreArcaImages");
  const cancelButton = arcaEl("cancelRestoreArcaImages");
  if (button) button.disabled = true;
  if (element) element.textContent = "누락 이미지와 예상 용량·시간을 계산하는 중…";
  try {
    const estimate = await arcaFetch("/api/arca-styles/restore-images/estimate");
    arcaState.imageRestoreEstimate = estimate;
    const hasMissing = Number(estimate.missing_images || 0) > 0;
    updateArcaImageDownloadDisclosure(estimate);
    if (element) element.textContent = imageRestoreEstimateText(estimate);
    button?.classList.toggle("hidden", hasMissing);
    confirmButton?.classList.toggle("hidden", !hasMissing);
    cancelButton?.classList.toggle("hidden", !hasMissing);
    if (button) button.disabled = !hasMissing;
    return estimate;
  } catch (error) {
    arcaState.imageRestoreEstimate = null;
    if (element) element.textContent = `예상 용량을 계산하지 못했습니다: ${error.message}`;
    if (button) button.disabled = false;
    return null;
  }
}

function resetArcaImageRestoreEstimate() {
  arcaState.imageRestoreEstimate = null;
  const button = arcaEl("restoreArcaImages");
  if (button) {
    button.classList.remove("hidden");
    button.disabled = false;
  }
  arcaEl("confirmRestoreArcaImages")?.classList.add("hidden");
  arcaEl("cancelRestoreArcaImages")?.classList.add("hidden");
  const element = arcaEl("arcaImageRestoreEstimate");
  if (element) element.textContent = "아직 다운로드하지 않습니다. 먼저 아래 버튼으로 필요한 용량과 시간을 확인하세요.";
}

async function prepareArcaImageRestore() {
  if (isArcaCollectionBusy(arcaState)) return;
  await loadArcaImageRestoreEstimate();
}

async function startGoogleArcaImageArchive() {
  if (isArcaCollectionBusy(arcaState)) return;
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  arcaSetStatus("arcaImageArchiveStatus", "Google Drive ZIP 다운로드를 준비합니다.");
  try {
    const result = await arcaFetch("/api/arca-styles/image-archive/google", { method: "POST", body: "{}" });
    arcaState.activeJobId = result.job_id;
    arcaSetStatus("arcaImageArchiveStatus", "다운로드 중입니다. 중단되면 같은 버튼으로 이어받을 수 있습니다.");
    await pollArcaCollectionJob(result.job_id);
  } catch (error) {
    arcaState.activeJobId = null;
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaImageArchiveStatus", error.message, "error");
  }
}

async function uploadLocalArcaImageArchive(file) {
  if (!file || isArcaCollectionBusy(arcaState)) return;
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  arcaSetStatus("arcaImageArchiveStatus", `로컬 ZIP 확인 중 · ${formatBytes(file.size)}`);
  let upload = null;
  try {
    upload = await arcaFetch("/api/arca-styles/image-archive/upload/start", {
      method: "POST",
      body: JSON.stringify({ name: file.name, size: file.size }),
    });
    let offset = Number(upload.uploaded_bytes || 0);
    const chunkBytes = Number(upload.chunk_bytes || 8 * 1024 * 1024);
    while (offset < file.size) {
      const chunk = file.slice(offset, Math.min(file.size, offset + chunkBytes));
      const response = await fetch(
        `/api/arca-styles/image-archive/upload/${encodeURIComponent(upload.upload_id)}?offset=${offset}`,
        { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: chunk },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      offset = Number(data.uploaded_bytes || 0);
      const percent = Math.min(100, Math.round(offset * 100 / file.size));
      arcaSetStatus("arcaImageArchiveStatus", `로컬 ZIP 전달 중 ${percent}% · ${formatBytes(offset)}/${formatBytes(file.size)}`);
    }
    const result = await arcaFetch(
      `/api/arca-styles/image-archive/upload/${encodeURIComponent(upload.upload_id)}/finish`,
      { method: "POST", body: "{}" },
    );
    arcaState.activeJobId = result.job_id;
    arcaSetStatus("arcaImageArchiveStatus", "로컬 ZIP의 SHA-256을 확인하고 압축을 풉니다.");
    await pollArcaCollectionJob(result.job_id);
  } catch (error) {
    if (upload?.upload_id) {
      await fetch(`/api/arca-styles/image-archive/upload/${encodeURIComponent(upload.upload_id)}`, { method: "DELETE" }).catch(() => null);
    }
    arcaState.activeJobId = null;
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaImageArchiveStatus", error.message, "error");
  } finally {
    const input = arcaEl("arcaImageArchiveFile");
    if (input) input.value = "";
  }
}

function scheduleArcaSearchCoverage() {
  clearTimeout(arcaState.coverageTimer);
  arcaState.coverageTimer = setTimeout(loadArcaSearchCoverage, 200);
}

async function pollArcaCollectionJob(jobId) {
  if (arcaState.activeJobId !== jobId) return;
  try {
    const job = await arcaFetch(`/api/arca-styles/collection-jobs/${jobId}`);
    renderArcaCollectionProgress(job);
    if (["completed", "failed", "interrupted", "stopped"].includes(job.status)) {
      clearTimeout(arcaState.pollTimer);
      arcaState.pollTimer = null;
      if (job.status === "completed") arcaState.activeJobId = null;
      arcaState.collecting = false;
      setArcaCollectionControlsDisabled(false);
      if (job.job_type === "image_archive") {
        const message = job.status === "completed"
          ? arcaSummaryText(job)
          : job.error || "ZIP 설치가 중단되었습니다.";
        arcaSetStatus("arcaImageArchiveStatus", message, job.status === "completed" ? "success" : "error");
      }
      if (job.status === "completed") {
        arcaSetStatus("arcaCollectorStatus", arcaSummaryText(job), job.error ? "error" : "success");
        await Promise.all([loadArcaStyles(), loadArcaSearchCoverage(), loadArcaStyleStatistics(), loadArcaImageRestoreEstimate()]);
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

async function loadCurrentArcaCollectionJob() {
  try {
    const job = await arcaFetch("/api/arca-styles/collection-jobs/current");
    if (!job?.id) return;
    arcaState.activeJobId = job.id;
    arcaState.collecting = ["queued", "running", "pause_requested", "paused", "stop_requested"].includes(job.status);
    setArcaCollectionControlsDisabled(arcaState.collecting);
    renderArcaCollectionProgress(job);
    if (arcaState.collecting) {
      clearTimeout(arcaState.pollTimer);
      arcaState.pollTimer = setTimeout(() => pollArcaCollectionJob(job.id), 250);
    }
  } catch (error) {
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  }
}

async function controlArcaCollection(action) {
  const jobId = arcaState.activeJobId;
  if (!jobId) return;
  for (const id of ["pauseArcaCollection", "resumeArcaCollection", "stopArcaCollection"]) {
    const button = arcaEl(id);
    if (button) button.disabled = true;
  }
  try {
    const result = await arcaFetch(`/api/arca-styles/collection-jobs/${jobId}/${action}`, { method: "POST" });
    if (action === "resume") {
      arcaState.activeJobId = result.job_id;
      arcaState.collecting = true;
      setArcaCollectionControlsDisabled(true);
      await pollArcaCollectionJob(result.job_id);
    } else {
      renderArcaCollectionProgress(result);
    }
  } catch (error) {
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  } finally {
    for (const id of ["pauseArcaCollection", "resumeArcaCollection", "stopArcaCollection"]) {
      const button = arcaEl(id);
      if (button) button.disabled = false;
    }
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

function renderArcaPagination(result) {
  const page = Math.max(1, Number(result?.page) || 1);
  const totalPages = Math.max(1, Number(result?.total_pages) || 1);
  arcaState.page = page;
  arcaState.totalPages = totalPages;
  arcaState.totalItems = Math.max(0, Number(result?.total) || 0);
  if (arcaEl("arcaStylePageSummary")) arcaEl("arcaStylePageSummary").textContent = `${page} / ${totalPages} 페이지`;
  if (arcaEl("arcaStylePageInput")) {
    arcaEl("arcaStylePageInput").value = String(page);
    arcaEl("arcaStylePageInput").max = String(totalPages);
  }
  if (arcaEl("arcaStylePrevPage")) arcaEl("arcaStylePrevPage").disabled = page <= 1;
  if (arcaEl("arcaStyleNextPage")) arcaEl("arcaStyleNextPage").disabled = page >= totalPages;
}

function applyArcaCardSize() {
  const size = arcaEl("arcaStyleCardSize")?.value || "medium";
  if (arcaEl("arcaStyleList")) arcaEl("arcaStyleList").dataset.cardSize = size;
}

async function goToArcaPage(page) {
  arcaState.page = Math.min(Math.max(1, Math.trunc(Number(page) || 1)), arcaState.totalPages);
  await loadArcaStyles();
  arcaEl("arcaStyleList")?.scrollTo({ top: 0, behavior: "smooth" });
}

function arcaTableCell(value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value == null ? "" : String(value);
  if (className) cell.className = className;
  return cell;
}

function renderArcaStatisticTable(kind, entries, targetId) {
  const body = arcaEl(targetId);
  if (!body) return;
  const rows = normalizeArcaStatisticRows(entries);
  body.replaceChildren(...rows.map((entry) => {
    const row = document.createElement("tr");
    const tagCell = document.createElement("td");
    const identity = document.createElement("div");
    identity.className = "arca-statistic-identity";
    const representative = entry.representative_image;
    if (representative?.image_url) {
      const preview = arcaButton("", () => openArcaTagImage(representative, entry.tag), "arca-statistic-inline-image");
      const image = document.createElement("img");
      image.src = representative.image_url;
      image.alt = `${entry.tag} 대표 그림`;
      preview.append(image);
      identity.append(preview);
    } else {
      const empty = document.createElement("span");
      empty.className = "arca-statistic-inline-image is-empty";
      empty.textContent = "없음";
      identity.append(empty);
    }
    const tagButton = arcaButton(entry.tag, () => loadArcaTagStatistics(kind, entry.tag), "arca-statistic-tag-button");
    tagButton.title = kind === "artist" ? "상세 및 함께 사용된 작가 보기" : "퀄리티 태그 상세 보기";
    identity.append(tagButton);
    tagCell.append(identity);
    row.append(
      tagCell,
      arcaTableCell(entry.count.toLocaleString(), "is-number"),
      arcaTableCell(`${entry.percentage}%`, "is-number"),
      arcaTableCell(formatArcaWeight(entry.average_weight), "is-number"),
      arcaTableCell(entry.dominant_weight_range || "-"),
      arcaTableCell(formatArcaRecommendation(entry.average_recommendations), "is-number"),
      arcaTableCell(formatArcaRecommendation(entry.max_recommendations), "is-number"),
    );
    return row;
  }));
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = arcaTableCell("표시할 태그가 없습니다.");
    cell.colSpan = 7;
    row.append(cell);
    body.append(row);
  }
}

function populateArcaWeightRanges(selectId, entries) {
  const select = arcaEl(selectId);
  if (!select) return;
  const selected = select.value;
  const ranges = new Set(normalizeArcaStatisticRows(entries).map((entry) => entry.dominant_weight_range).filter(Boolean));
  const options = [select.options[0], ...ARCA_WEIGHT_RANGE_ORDER.filter((range) => ranges.has(range)).map((range) => {
    const option = document.createElement("option");
    option.value = range;
    option.textContent = range;
    return option;
  })].filter(Boolean);
  select.replaceChildren(...options);
  select.value = ranges.has(selected) ? selected : "";
}

function statisticTableOptions(prefix, kind) {
  const table = arcaState.statisticTables[kind];
  return {
    query: arcaEl(`${prefix}StatisticsSearch`)?.value,
    range: arcaEl(`${prefix}WeightRange`)?.value,
    sort: `${table.sortKey}_${table.sortDirection}`,
  };
}

function updateArcaStatisticSortHeaders(kind) {
  const table = arcaState.statisticTables[kind];
  document.querySelectorAll(`[data-arca-stat-kind="${kind}"]`).forEach((header) => {
    const active = header.dataset.arcaSortKey === table.sortKey;
    header.setAttribute("aria-sort", active ? (table.sortDirection === "asc" ? "ascending" : "descending") : "none");
  });
}

function renderArcaStatisticCategory(kind) {
  const artist = kind === "artist";
  const prefix = artist ? "arcaArtist" : "arcaQuality";
  const entries = artist ? arcaState.statisticsData?.artists || [] : arcaState.statisticsData?.quality_tags || [];
  const filtered = filterAndSortArcaStatisticRows(entries, statisticTableOptions(prefix, kind));
  const tableState = arcaState.statisticTables[kind];
  const page = paginateArcaStatisticRows(filtered, tableState.page, arcaEl(`${prefix}StatisticsPageSize`)?.value);
  tableState.page = page.page;
  renderArcaStatisticTable(kind, page.rows, `${prefix}StatisticsRows`);
  updateArcaStatisticSortHeaders(kind);
  const count = arcaEl(`${prefix}StatisticsCount`);
  if (count) count.textContent = `${page.total.toLocaleString()}개 검색됨 · 전체 ${entries.length.toLocaleString()}개`;
  if (arcaEl(`${prefix}StatisticsPage`)) arcaEl(`${prefix}StatisticsPage`).textContent = `${page.page} / ${page.totalPages} 페이지`;
  if (arcaEl(`${prefix}StatisticsPrev`)) arcaEl(`${prefix}StatisticsPrev`).disabled = page.page <= 1;
  if (arcaEl(`${prefix}StatisticsNext`)) arcaEl(`${prefix}StatisticsNext`).disabled = page.page >= page.totalPages;
}

function renderArcaArtistStatistics() { renderArcaStatisticCategory("artist"); }

function renderArcaQualityStatistics() { renderArcaStatisticCategory("quality"); }

function changeArcaStatisticSort(kind, sortKey) {
  const table = arcaState.statisticTables[kind];
  if (!table) return;
  if (table.sortKey === sortKey) table.sortDirection = table.sortDirection === "desc" ? "asc" : "desc";
  else {
    table.sortKey = sortKey;
    table.sortDirection = sortKey === "tag" ? "asc" : "desc";
  }
  table.page = 1;
  renderArcaStatisticCategory(kind);
}

function changeArcaStatisticPage(kind, offset) {
  const table = arcaState.statisticTables[kind];
  if (!table) return;
  table.page = Math.max(1, table.page + offset);
  renderArcaStatisticCategory(kind);
}

function renderArcaSequenceRows(entries) {
  const body = arcaEl("arcaQualitySequenceRows");
  if (!body) return;
  const sort = arcaEl("arcaSequenceStatisticsSort")?.value || "count_desc";
  const numeric = (value) => value == null || !Number.isFinite(Number(value)) ? -Infinity : Number(value);
  const rows = (Array.isArray(entries) ? entries : []).slice().sort((left, right) => {
    if (sort === "recommendation_desc") return numeric(right.average_recommendations) - numeric(left.average_recommendations) || Number(right.count || 0) - Number(left.count || 0);
    if (sort === "recommendation_max_desc") return numeric(right.max_recommendations) - numeric(left.max_recommendations) || Number(right.count || 0) - Number(left.count || 0);
    return Number(right.count || 0) - Number(left.count || 0);
  });
  body.replaceChildren(...rows.map((entry) => {
    const row = document.createElement("tr");
    const tags = document.createElement("td");
    tags.className = "arca-combination-tags";
    tags.append(arcaButton(
      (entry.tags || []).join(" → "),
      () => loadArcaQualitySequence(entry.tags || []),
      "arca-sequence-button",
    ));
    row.append(
      arcaTableCell(Number(entry.count || 0).toLocaleString(), "is-number"),
      arcaTableCell(`${Number(entry.percentage || 0)}%`, "is-number"),
      arcaTableCell(formatArcaRecommendation(entry.average_recommendations), "is-number"),
      arcaTableCell(formatArcaRecommendation(entry.max_recommendations), "is-number"),
    );
    row.prepend(tags);
    return row;
  }));
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = arcaTableCell("반복된 퀄리티 조합이 없습니다.");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
  }
}

function closeArcaTagImage() {
  arcaEl("arcaTagImageModal")?.classList.add("hidden");
}

function closeArcaTagStatistics() {
  closeArcaTagImage();
  arcaEl("arcaTagStatisticsModal")?.classList.add("hidden");
}

function closeArcaSequence() {
  closeArcaTagImage();
  arcaEl("arcaSequenceModal")?.classList.add("hidden");
}

function openArcaTagImage(image, tag) {
  const modal = arcaEl("arcaTagImageModal");
  if (!modal) return;
  const preview = arcaEl("arcaTagLargeImage");
  if (preview) {
    preview.src = image.image_url || "";
    preview.alt = `${tag} 가중치 ${formatArcaWeight(image.weight)} 적용 이미지`;
  }
  const title = arcaEl("arcaTagImageTitle");
  if (title) title.textContent = image.title || tag || "이미지 크게 보기";
  const caption = arcaEl("arcaTagImageCaption");
  const weightText = Number.isFinite(Number(image.weight)) ? ` · 가중치 ${formatArcaWeight(image.weight)}` : "";
  const recommendationText = image.recommendation_count == null ? "" : ` · 추천 ${Number(image.recommendation_count).toLocaleString()}`;
  if (caption) caption.textContent = `${tag}${weightText}${recommendationText} · ${image.posted_at || "날짜 없음"}`;
  const prompt = arcaEl("arcaTagImagePrompt");
  if (prompt) prompt.textContent = image.prompt || "프롬프트 없음";
  const source = arcaEl("arcaTagImageSourceLink");
  if (source) {
    source.href = image.source_url || "#";
    source.classList.toggle("hidden", !image.source_url);
  }
  modal.classList.remove("hidden");
}

function createArcaStatisticsImageCard(image, label, compact = false) {
  const figure = document.createElement("figure");
  figure.classList.toggle("is-compact", compact);
  const previewButton = document.createElement("button");
  previewButton.type = "button";
  previewButton.className = "arca-tag-image-preview";
  previewButton.addEventListener("click", () => openArcaTagImage(image, label));
  const preview = document.createElement("img");
  preview.src = image.image_url;
  preview.alt = `${label} 적용 이미지`;
  previewButton.append(preview);
  const caption = document.createElement("figcaption");
  const weightText = Number.isFinite(Number(image.weight)) ? `가중치 ${formatArcaWeight(image.weight)} · ` : "";
  const recommendationText = image.recommendation_count == null ? "" : `추천 ${Number(image.recommendation_count).toLocaleString()} · `;
  caption.textContent = `${weightText}${recommendationText}${image.posted_at || "날짜 없음"}`;
  const actions = document.createElement("div");
  actions.className = "arca-image-card-actions";
  const prompt = document.createElement("pre");
  prompt.className = "arca-image-prompt hidden";
  prompt.textContent = image.prompt || "프롬프트 없음";
  const promptButton = arcaButton("프롬프트 보기", () => {
    const opening = prompt.classList.contains("hidden");
    prompt.classList.toggle("hidden", !opening);
    promptButton.textContent = opening ? "프롬프트 닫기" : "프롬프트 보기";
  }, "arca-prompt-toggle");
  actions.append(promptButton);
  if (image.source_url) {
    const source = document.createElement("a");
    source.href = image.source_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    source.className = "arca-tag-image-source";
    source.textContent = "사이트 이동";
    actions.append(source);
  }
  figure.append(previewButton, caption, actions, prompt);
  return figure;
}

function renderArcaTagStatistics(result) {
  const modal = arcaEl("arcaTagStatisticsModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  arcaEl("arcaTagStatisticsTitle").textContent = result.tag || "태그 상세";
  const weights = result.weights || {};
  arcaEl("arcaTagStatisticsSummary").textContent = `이미지 ${Number(result.image_count || 0).toLocaleString()}개 · 사용 ${Number(result.occurrence_count || 0).toLocaleString()}회 · 평균 ${formatArcaWeight(weights.average)} · 중앙값 ${formatArcaWeight(weights.median)} · 최고 ${formatArcaWeight(weights.max)}`;
  const weightRows = arcaEl("arcaTagWeightRows");
  weightRows?.replaceChildren(...(weights.bins || []).map((entry) => {
    const row = document.createElement("tr");
    row.append(arcaTableCell(entry.label), arcaTableCell(Number(entry.count || 0).toLocaleString(), "is-number"), arcaTableCell(`${Number(entry.percentage || 0)}%`, "is-number"));
    return row;
  }));
  const relatedSection = arcaEl("arcaTagRelatedSection");
  const relatedTags = Array.isArray(result.related_tags) ? result.related_tags : [];
  relatedSection?.classList.toggle("hidden", !relatedTags.length);
  if (arcaEl("arcaTagRelatedTitle")) {
    arcaEl("arcaTagRelatedTitle").textContent = result.kind === "artist" ? "함께 사용된 다른 작가" : "함께 사용된 퀄리티 태그";
  }
  const relatedList = arcaEl("arcaTagRelatedTags");
  relatedList?.replaceChildren(...relatedTags.map((entry) => (
    arcaButton(
      `${entry.tag} · ${Number(entry.count || 0).toLocaleString()}개 (${Number(entry.percentage || 0)}%)`,
      () => loadArcaTagStatistics(result.kind, entry.tag),
      "arca-related-tag-button",
    )
  )));
  if (relatedList) relatedList.scrollTop = 0;
  const gallery = arcaEl("arcaTagImageGallery");
  gallery?.classList.toggle("is-quality", result.kind === "quality");
  gallery?.classList.toggle("is-artist", result.kind === "artist");
  gallery?.replaceChildren(...(result.images || []).map((image) => createArcaStatisticsImageCard(image, result.tag, result.kind === "quality")));
}

async function loadArcaTagStatistics(kind, tag) {
  const modal = arcaEl("arcaTagStatisticsModal");
  modal?.classList.remove("hidden");
  arcaEl("arcaTagStatisticsTitle").textContent = tag || "태그 상세";
  arcaSetStatus("arcaTagStatisticsStatus", "태그 상세를 불러오는 중…");
  try {
    const query = arcaTagDetailQuery(kind, tag, 24, {
      recommendation_min: arcaEl("arcaRecommendationMin")?.value,
      recommendation_max: arcaEl("arcaRecommendationMax")?.value,
    });
    const result = await arcaFetch(`/api/arca-styles/statistics/tag?${query}`);
    renderArcaTagStatistics(result);
    arcaSetStatus("arcaTagStatisticsStatus", "");
  } catch (error) {
    arcaSetStatus("arcaTagStatisticsStatus", error.message, "error");
  }
}

function renderArcaQualitySequence(result) {
  const tags = result.tags || [];
  arcaEl("arcaSequenceTitle").textContent = tags.join(" → ") || "퀄리티 순서 조합";
  arcaEl("arcaSequenceSummary").textContent = `이 순서 조합을 사용하는 이미지 ${Number(result.image_count || 0).toLocaleString()}개`;
  arcaEl("arcaSequenceImageGallery")?.replaceChildren(...(result.images || []).map((image) => (
    createArcaStatisticsImageCard(image, tags.join(" → "), false)
  )));
}

async function loadArcaQualitySequence(tags) {
  const modal = arcaEl("arcaSequenceModal");
  modal?.classList.remove("hidden");
  arcaEl("arcaSequenceTitle").textContent = (tags || []).join(" → ") || "퀄리티 순서 조합";
  arcaSetStatus("arcaSequenceStatus", "조합 이미지를 불러오는 중…");
  try {
    const result = await arcaFetch(`/api/arca-styles/statistics/sequence?${arcaSequenceDetailQuery(tags, 40, {
      recommendation_min: arcaEl("arcaRecommendationMin")?.value,
      recommendation_max: arcaEl("arcaRecommendationMax")?.value,
    })}`);
    renderArcaQualitySequence(result);
    arcaSetStatus("arcaSequenceStatus", "");
  } catch (error) {
    arcaSetStatus("arcaSequenceStatus", error.message, "error");
  }
}

function arcaStatisticsViewEntries(view) {
  if (view === "quality") return arcaState.statisticsData?.quality_tags || [];
  if (view === "sequence") return arcaState.statisticsData?.quality_sequences || [];
  return arcaState.statisticsData?.artists || [];
}

function renderArcaStatisticsSamples() {
  const view = arcaState.statisticsView;
  const gallery = arcaEl("arcaStatisticsSampleGallery");
  if (!gallery) return;
  const titles = { artist: "작가 대표 그림", quality: "퀄리티 대표 그림", sequence: "순서 조합 대표 그림" };
  const sampleLimits = { artist: 12, quality: 15, sequence: 12 };
  arcaEl("arcaStatisticsSampleTitle").textContent = titles[view] || titles.artist;
  const samples = randomArcaStatisticsSamples(arcaStatisticsViewEntries(view), sampleLimits[view] || sampleLimits.artist);
  gallery.classList.toggle("is-quality", view === "quality");
  gallery.replaceChildren(...samples.map((entry) => {
    const figure = document.createElement("figure");
    const image = entry.representative_image;
    const label = view === "sequence" ? (entry.tags || []).join(" → ") : entry.tag;
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "arca-statistics-sample-image";
    preview.addEventListener("click", () => openArcaTagImage(image, label));
    const img = document.createElement("img");
    img.src = image.image_url;
    img.alt = `${label} 대표 그림`;
    preview.append(img);
    const detail = arcaButton(label, () => {
      if (view === "sequence") loadArcaQualitySequence(entry.tags || []);
      else loadArcaTagStatistics(view, entry.tag);
    }, "arca-statistics-sample-label");
    figure.append(preview, detail);
    return figure;
  }));
  if (!samples.length) {
    const empty = document.createElement("p");
    empty.textContent = "표시할 대표 그림이 없습니다.";
    gallery.append(empty);
  }
}

function selectArcaStatisticsView(view) {
  const selected = ["artist", "quality", "sequence"].includes(view) ? view : "artist";
  arcaState.statisticsView = selected;
  document.querySelectorAll("[data-arca-statistics-view]").forEach((button) => {
    const active = button.dataset.arcaStatisticsView === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  arcaEl("arcaArtistStatisticsPanel")?.classList.toggle("hidden", selected !== "artist");
  arcaEl("arcaQualityStatisticsPanel")?.classList.toggle("hidden", selected !== "quality");
  arcaEl("arcaSequenceStatisticsPanel")?.classList.toggle("hidden", selected !== "sequence");
  renderArcaStatisticsSamples();
}

function renderArcaStyleStatistics(result) {
  arcaState.statisticsData = result || {};
  arcaState.statisticTables.artist.page = 1;
  arcaState.statisticTables.quality.page = 1;
  const summary = arcaEl("arcaStyleStatisticsSummary");
  if (summary) {
    const minimum = arcaEl("arcaRecommendationMin")?.value;
    const maximum = arcaEl("arcaRecommendationMax")?.value;
    const range = minimum || maximum ? ` · 추천수 ${minimum || 0}–${maximum || "제한 없음"}` : "";
    summary.textContent = `${arcaStatisticsSummary(result)}${range}`;
  }
  const scope = arcaEl("arcaStatisticsScopeNote");
  if (scope) scope.textContent = result?.collection_scope_note || "";
  populateArcaWeightRanges("arcaArtistWeightRange", result?.artists);
  populateArcaWeightRanges("arcaQualityWeightRange", result?.quality_tags);
  renderArcaArtistStatistics();
  renderArcaQualityStatistics();
  renderArcaSequenceRows(result?.quality_sequences);
  selectArcaStatisticsView(arcaState.statisticsView);
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
    const query = arcaListQuery({
      q: arcaEl("arcaStyleSearch")?.value,
      metadata: arcaEl("arcaMetadataFilter")?.value,
      recommendation_min: arcaEl("arcaRecommendationMinList")?.value,
      sort: arcaEl("arcaStyleSort")?.value,
      page: arcaState.page,
      per_page: arcaEl("arcaStylePageSize")?.value,
    });
    const result = await arcaFetch(`/api/arca-styles?${query}`);
    const items = Array.isArray(result?.items) ? result.items : [];
    renderArcaList(items);
    renderArcaPagination(result);
    const start = result.total ? (result.page - 1) * result.per_page + 1 : 0;
    const end = result.total ? start + items.length - 1 : 0;
    arcaSetStatus("arcaStyleListStatus", `전체 ${Number(result.total || 0).toLocaleString()}개 · ${start}-${end} 표시`);
    arcaState.loaded = true;
  } catch (error) {
    arcaSetStatus("arcaStyleListStatus", error.message, "error");
  }
}

async function loadArcaStyleStatistics() {
  const root = arcaEl("arcaStyleStatistics");
  if (root) root.setAttribute("aria-busy", "true");
  arcaSetStatus("arcaStyleStatisticsStatus", "통계를 불러오는 중…");
  try {
    const query = arcaStatisticsQuery({
      recommendation_min: arcaEl("arcaRecommendationMin")?.value,
      recommendation_max: arcaEl("arcaRecommendationMax")?.value,
    });
    const result = await arcaFetch(`/api/arca-styles/statistics?${query}`);
    renderArcaStyleStatistics(result);
    arcaState.statisticsLoaded = true;
    arcaSetStatus("arcaStyleStatisticsStatus", "");
  } catch (error) {
    arcaState.statisticsLoaded = false;
    arcaSetStatus("arcaStyleStatisticsStatus", error.message, "error");
  } finally {
    if (root) root.setAttribute("aria-busy", "false");
  }
}

function applyArcaRecommendationPreset() {
  const values = arcaRecommendationPreset(arcaEl("arcaRecommendationPreset")?.value);
  if (!values) return;
  if (arcaEl("arcaRecommendationMin")) arcaEl("arcaRecommendationMin").value = values.recommendation_min;
  if (arcaEl("arcaRecommendationMax")) arcaEl("arcaRecommendationMax").value = values.recommendation_max;
  void loadArcaStyleStatistics();
}

async function refreshArcaStyleData() {
  await loadArcaStyles();
}

function loadArcaCollectorData() {
  return Promise.all([
    arcaState.loaded ? Promise.resolve([]) : loadArcaStyles(),
    loadArcaImageRestoreEstimate(),
  ]);
}

async function runArcaCollection(payload) {
  if (arcaState.collecting) return;
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  try {
    const result = await arcaFetch("/api/arca-styles/collect", { method: "POST", body: JSON.stringify(payload) });
    arcaState.activeJobId = result.job_id;
    await pollArcaCollectionJob(result.job_id);
  } catch (error) {
    arcaState.collecting = false;
    setArcaCollectionControlsDisabled(false);
    arcaSetStatus("arcaCollectorStatus", error.message, "error");
  }
}

async function collectArcaStyles() {
  if (isArcaCollectionBusy(arcaState)) return;
  const payload = arcaPayload();
  if (payload.tabs.includes("R18_NAI") && !arcaState.browserConnected) {
    arcaState.pendingCollectionPayload = payload;
    setArcaCollectionControlsDisabled(true);
    arcaSetStatus("arcaBrowserSessionState", "브라우저 로그인 연결 후 수집을 자동으로 시작합니다.");
    await importArcaBrowserSession();
    return;
  }
  await runArcaCollection(payload);
}

async function restoreArcaImages() {
  if (isArcaCollectionBusy(arcaState)) return;
  if (Number(arcaState.imageRestoreEstimate?.missing_images || 0) <= 0) return;
  if (!arcaState.browserConnected) {
    arcaSetStatus("arcaCollectorStatus", "R18 게시글 확인을 위해 Chrome 로그인을 연결합니다.");
    await importArcaBrowserSession();
    if (!arcaState.browserConnected) {
      arcaSetStatus("arcaCollectorStatus", "Chrome 로그인을 연결한 뒤 다시 다운로드를 시작해 주세요.", "error");
      return;
    }
  }
  arcaState.collecting = true;
  setArcaCollectionControlsDisabled(true);
  arcaSetStatus("arcaCollectorStatus", "게시글별 최신 주소를 확인하며 누락 이미지를 안전 속도로 받습니다.");
  try {
    const result = await arcaFetch("/api/arca-styles/restore-images", { method: "POST", body: "{}" });
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
  if (!id || !await globalThis.appDialog.confirm({
    title: "수집 그림체 삭제",
    message: "선택한 수집 그림체를 삭제할까요?",
    details: ["날짜 정보가 있는 항목은 다음 수집 때 다시 검색될 수 있습니다."],
    confirmLabel: "수집 항목 삭제",
    tone: "danger",
  })) return;
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
    await Promise.all([loadArcaStyles(), loadArcaStyleStatistics()]);
  } catch (error) {
    arcaSetStatus(arcaState.selectedId === id ? "arcaStyleDialogStatus" : "arcaStyleListStatus", error.message, "error");
  }
}

function bindArcaCollector() {
  initializeArcaDateInputs();
  document.querySelector('[data-tab="arca-style-collector"]')?.addEventListener("click", () => { void loadArcaCollectorData(); });
  document.querySelector('[data-tab="arca-style-statistics"]')?.addEventListener("click", () => { if (!arcaState.statisticsLoaded) void loadArcaStyleStatistics(); });
  arcaEl("collectArcaStyles")?.addEventListener("click", collectArcaStyles);
  arcaEl("restoreArcaImages")?.addEventListener("click", prepareArcaImageRestore);
  arcaEl("confirmRestoreArcaImages")?.addEventListener("click", restoreArcaImages);
  arcaEl("cancelRestoreArcaImages")?.addEventListener("click", resetArcaImageRestoreEstimate);
  arcaEl("downloadArcaImageArchive")?.addEventListener("click", startGoogleArcaImageArchive);
  arcaEl("chooseArcaImageArchive")?.addEventListener("click", () => arcaEl("arcaImageArchiveFile")?.click());
  arcaEl("arcaImageArchiveFile")?.addEventListener("change", (event) => uploadLocalArcaImageArchive(event.target.files?.[0]));
  arcaEl("collectArcaUrl")?.addEventListener("click", collectArcaUrl);
  arcaEl("importArcaBrowserSession")?.addEventListener("click", importArcaBrowserSession);
  arcaEl("setupArcaSessionBridge")?.addEventListener("click", setupArcaSessionBridge);
  arcaEl("refreshArcaBrowserSession")?.addEventListener("click", loadArcaBrowserSession);
  arcaEl("pauseArcaCollection")?.addEventListener("click", () => controlArcaCollection("pause"));
  arcaEl("resumeArcaCollection")?.addEventListener("click", () => controlArcaCollection("resume"));
  arcaEl("stopArcaCollection")?.addEventListener("click", () => controlArcaCollection("stop"));
  arcaEl("refreshArcaStyles")?.addEventListener("click", refreshArcaStyleData);
  arcaEl("refreshArcaStatistics")?.addEventListener("click", loadArcaStyleStatistics);
  arcaEl("arcaRecommendationPreset")?.addEventListener("change", applyArcaRecommendationPreset);
  arcaEl("applyArcaRecommendationFilter")?.addEventListener("click", loadArcaStyleStatistics);
  for (const id of ["arcaRecommendationMin", "arcaRecommendationMax"]) {
    arcaEl(id)?.addEventListener("input", () => { if (arcaEl("arcaRecommendationPreset")) arcaEl("arcaRecommendationPreset").value = "custom"; });
    arcaEl(id)?.addEventListener("keydown", (event) => { if (event.key === "Enter") void loadArcaStyleStatistics(); });
  }
  for (const id of ["arcaArtistStatisticsSearch", "arcaArtistWeightRange", "arcaArtistStatisticsPageSize"]) {
    arcaEl(id)?.addEventListener("input", () => {
      arcaState.statisticTables.artist.page = 1;
      renderArcaArtistStatistics();
    });
  }
  for (const id of ["arcaQualityStatisticsSearch", "arcaQualityWeightRange", "arcaQualityStatisticsPageSize"]) {
    arcaEl(id)?.addEventListener("input", () => {
      arcaState.statisticTables.quality.page = 1;
      renderArcaQualityStatistics();
    });
  }
  document.querySelectorAll("[data-arca-stat-kind][data-arca-sort-key]").forEach((header) => {
    header.querySelector("button")?.addEventListener("click", () => changeArcaStatisticSort(header.dataset.arcaStatKind, header.dataset.arcaSortKey));
  });
  arcaEl("arcaArtistStatisticsPrev")?.addEventListener("click", () => changeArcaStatisticPage("artist", -1));
  arcaEl("arcaArtistStatisticsNext")?.addEventListener("click", () => changeArcaStatisticPage("artist", 1));
  arcaEl("arcaQualityStatisticsPrev")?.addEventListener("click", () => changeArcaStatisticPage("quality", -1));
  arcaEl("arcaQualityStatisticsNext")?.addEventListener("click", () => changeArcaStatisticPage("quality", 1));
  arcaEl("arcaSequenceStatisticsSort")?.addEventListener("input", () => renderArcaSequenceRows(arcaState.statisticsData?.quality_sequences));
  document.querySelectorAll("[data-arca-statistics-view]").forEach((button) => {
    button.addEventListener("click", () => selectArcaStatisticsView(button.dataset.arcaStatisticsView));
  });
  arcaEl("shuffleArcaStatisticsImages")?.addEventListener("click", renderArcaStatisticsSamples);
  arcaEl("closeArcaTagStatistics")?.addEventListener("click", closeArcaTagStatistics);
  arcaEl("closeArcaTagImage")?.addEventListener("click", closeArcaTagImage);
  arcaEl("closeArcaSequence")?.addEventListener("click", closeArcaSequence);
  arcaEl("arcaTagLargeImage")?.addEventListener("click", closeArcaTagImage);
  document.querySelectorAll("[data-close-arca-tag-statistics]").forEach((item) => item.addEventListener("click", closeArcaTagStatistics));
  document.querySelectorAll("[data-close-arca-tag-image]").forEach((item) => item.addEventListener("click", closeArcaTagImage));
  document.querySelectorAll("[data-close-arca-sequence]").forEach((item) => item.addEventListener("click", closeArcaSequence));
  arcaEl("saveArcaStyle")?.addEventListener("click", saveArcaStyle);
  arcaEl("deleteArcaStyle")?.addEventListener("click", deleteArcaStyle);
  arcaEl("closeArcaStyle")?.addEventListener("click", () => arcaEl("arcaStyleDialog").classList.add("hidden"));
  for (const id of ["arcaStyleSearch", "arcaMetadataFilter", "arcaRecommendationMinList", "arcaStyleSort", "arcaStylePageSize"]) {
    arcaEl(id)?.addEventListener("input", () => {
      arcaState.page = 1;
      clearTimeout(arcaState.timer);
      arcaState.timer = setTimeout(loadArcaStyles, 250);
    });
  }
  arcaEl("arcaStyleCardSize")?.addEventListener("change", applyArcaCardSize);
  arcaEl("arcaStylePrevPage")?.addEventListener("click", () => goToArcaPage(arcaState.page - 1));
  arcaEl("arcaStyleNextPage")?.addEventListener("click", () => goToArcaPage(arcaState.page + 1));
  arcaEl("arcaStyleGoPage")?.addEventListener("click", () => goToArcaPage(arcaEl("arcaStylePageInput")?.value));
  arcaEl("arcaStylePageInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") void goToArcaPage(event.currentTarget.value);
  });
  applyArcaCardSize();
  for (const id of ["arcaTabNai", "arcaTabR18Nai", "arcaStartDate", "arcaEndDate"]) {
    arcaEl(id)?.addEventListener("change", scheduleArcaSearchCoverage);
  }
  if (typeof window !== "undefined") {
    window.addEventListener("focus", () => {
      if (shouldRefreshArcaBrowserSession("focus", document.visibilityState)) loadArcaBrowserSession();
    });
  }
  document.addEventListener("visibilitychange", () => {
    if (shouldRefreshArcaBrowserSession("visibilitychange", document.visibilityState)) loadArcaBrowserSession();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!arcaEl("arcaTagImageModal")?.classList.contains("hidden")) closeArcaTagImage();
    else if (!arcaEl("arcaSequenceModal")?.classList.contains("hidden")) closeArcaSequence();
    else if (!arcaEl("arcaTagStatisticsModal")?.classList.contains("hidden")) closeArcaTagStatistics();
  });
  loadArcaBrowserSession();
  loadArcaSearchCoverage();
  loadCurrentArcaCollectionJob();
}

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", bindArcaCollector);
if (typeof module !== "undefined") module.exports = {
  normalizeArcaPayload, normalizeArcaUrlPayload, arcaSummaryText, collectionProgress, durationText,
  etaText, formatBytes, imageRestoreEstimateText, imageDownloadSummary, collectionCountsText, groupTitle, promptSection, promptKindClass, imagePromptFields,
  arcaBrowserSessionText, isArcaBrowserSessionPending,
  arcaListQuery, arcaCoverageQuery, arcaCoverageText,
  formatArcaLocalDate, fillMissingArcaDates, arcaBrowserSessionAction,
  isArcaCollectionBusy, shouldRefreshArcaBrowserSession,
  normalizeArcaStatisticRows, arcaStatisticsSummary, arcaStatisticEntryText,
  formatArcaWeight, filterArcaStatisticRows, filterAndSortArcaStatisticRows, paginateArcaStatisticRows,
  arcaTagDetailQuery, arcaSequenceDetailQuery, arcaStatisticsQuery, arcaRecommendationPreset,
  randomArcaStatisticsSamples, formatArcaRecommendation,
};
