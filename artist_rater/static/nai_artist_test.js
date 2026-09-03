/* Resumable NAI artist-test screen.  Generation is intentionally one request
 * at a time so pause/reload never creates a hidden client-side queue. */
(function () {
  "use strict";

  const state = { artists: [], tests: [], selectedArtists: [], selectedTest: null, activeArtist: null, previewImages: [], previewIndex: 0, previewStatus: "", previewRequestToken: 0, workspaceExpanded: true, resultArtistFilter: "", resultScoreFilter: "all", resultPromptIndex: "all", historyCardSize: "medium", viewerItems: [], viewerIndex: 0, view: "list", listMode: "tests", artistHistory: { artists: [], items: [] }, selectedHistoryArtist: null, running: false, generationLoopInFlight: false, singleGenerationInFlight: false, ratingWaiting: false, stopRequested: false, artistSearchTimer: null, historySearchTimer: null, suppressGalleryClick: false, marqueeScrollFrame: null, usagePreflight: null, startWarningResolver: null, anlasWarningResolver: null, deleteWarningResolver: null, deleteWarningTestId: null, modalTrigger: null };
  const NAI_ARTIST_TEST_CARD_SIZE_KEY = "naiArtistRater.naiArtistTestCardSize.v1";
  const NAI_ARTIST_TEST_CARD_SIZES = ["small", "medium", "large"];
  const NAI_ARTIST_MARKER = "{{artist}}";
  const $ = (id) => document.getElementById(id);
  const text = (element, value) => { if (element) element.textContent = String(value ?? ""); };
  function artistMarkerCount(value) { return String(value || "").split("{{artist}}").length - 1; }
  function normalizeDelay(value) { const numeric = Number(value); return Number.isFinite(numeric) && numeric >= 0 ? numeric : null; }
  function normalizeHistoryCardSize(value) { return NAI_ARTIST_TEST_CARD_SIZES.includes(value) ? value : "medium"; }

  function setHistoryCardSize(value, persist = true) {
    const size = normalizeHistoryCardSize(value);
    state.historyCardSize = size;
    ["naiArtistTestResults", "naiArtistTestArtistHistoryResults"].forEach((id) => $(id)?.setAttribute("data-card-size", size));
    ["naiArtistTestResultCardSize", "naiArtistTestArtistHistoryCardSize"].forEach((id) => { const control = $(id); if (control) control.value = size; });
    if (persist && typeof localStorage !== "undefined") {
      try { localStorage.setItem(NAI_ARTIST_TEST_CARD_SIZE_KEY, size); } catch (_) { /* Storage can be disabled. */ }
    }
    return size;
  }

  function initializeHistoryCardSize() {
    let storedSize = "medium";
    if (typeof localStorage !== "undefined") {
      try { storedSize = localStorage.getItem(NAI_ARTIST_TEST_CARD_SIZE_KEY) || "medium"; } catch (_) { storedSize = "medium"; }
    }
    setHistoryCardSize(storedSize, false);
    ["naiArtistTestResultCardSize", "naiArtistTestArtistHistoryCardSize"].forEach((id) => $(id)?.addEventListener("change", (event) => setHistoryCardSize(event.target.value)));
  }

  async function api(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
    const value = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(value.error || "요청에 실패했습니다.");
    return value;
  }

  function setStatus(message, kind = "") {
    [$("naiArtistTestStatus"), $("naiArtistTestListStatus"), $("naiArtistTestDetailStatus")].forEach((target) => {
      text(target, message);
      target?.classList.toggle("error", kind === "error");
    });
  }

  function selectedArtists() {
    return artistSelectionPayload(state.selectedArtists);
  }

  function artistKey(artist) { return String(artist?.artist_tag || artist?.artist || "").replaceAll("_", " ").trim().toLowerCase(); }

  function sortArtistCandidates(artists, sort = "recent") {
    const result = Array.isArray(artists) ? [...artists] : [];
    if (sort === "score_desc") result.sort((a, b) => Number(b.danbooru_score) - Number(a.danbooru_score));
    if (sort === "score_asc") result.sort((a, b) => Number(a.danbooru_score) - Number(b.danbooru_score));
    if (sort === "artist") result.sort((a, b) => String(a.artist_tag).localeCompare(String(b.artist_tag)));
    return result;
  }

  function artistSelectionPayload(artists) {
    return (Array.isArray(artists) ? artists : []).map((artist) => ({ artist_tag: artist.artist_tag }));
  }

  function toggleArtistSelection(artists, artist) {
    const result = Array.isArray(artists) ? [...artists] : [];
    if (!artist) return result;
    const key = artistKey(artist);
    const index = result.findIndex((item) => artistKey(item) === key);
    if (index >= 0) result.splice(index, 1); else result.push({ ...artist });
    return result;
  }

  function mergeArtistSelections(selected, candidates) {
    const result = Array.isArray(selected) ? [...selected] : [];
    const keys = new Set(result.map(artistKey));
    (Array.isArray(candidates) ? candidates : []).forEach((artist) => {
      const key = artistKey(artist);
      if (artist && key && !keys.has(key)) { result.push({ ...artist }); keys.add(key); }
    });
    return result;
  }

  function isMarqueeDrag(distance, threshold = 5) {
    return Number.isFinite(Number(distance)) && Number(distance) >= Number(threshold);
  }

  function marqueeAutoScrollDelta(pointerY, viewportHeight, edge = 72, maxStep = 18) {
    const y = Number(pointerY); const height = Number(viewportHeight);
    if (!Number.isFinite(y) || !Number.isFinite(height) || height <= 0 || edge <= 0 || maxStep <= 0) return 0;
    if (y < edge) return -Math.ceil(Math.min(maxStep, ((edge - y) / edge) * maxStep));
    if (y > height - edge) return Math.ceil(Math.min(maxStep, ((y - (height - edge)) / edge) * maxStep));
    return 0;
  }

  function marqueeSelectedArtistKeys(cards, selectionRect, existingKeys = []) {
    const result = new Set((Array.isArray(existingKeys) ? existingKeys : []).map(String));
    if (!selectionRect) return [...result];
    (Array.isArray(cards) ? cards : []).forEach((card) => {
      const left = Math.max(Number(selectionRect.left), Number(card.left));
      const right = Math.min(Number(selectionRect.right), Number(card.right));
      const top = Math.max(Number(selectionRect.top), Number(card.top));
      const bottom = Math.min(Number(selectionRect.bottom), Number(card.bottom));
      if (right >= left && bottom >= top) result.add(String(card.artist_key || card.artist_tag || ""));
    });
    result.delete("");
    return [...result];
  }

  function uniquePreviewImages(artist, examples = []) {
    const urls = [];
    if (artist?.thumbnail_url) urls.push(String(artist.thumbnail_url));
    (Array.isArray(examples) ? examples : []).forEach((example) => {
      const url = typeof example === "string" ? example : example?.image_url;
      if (url) urls.push(String(url));
    });
    return [...new Set(urls)];
  }

  function cyclePreviewIndex(index, count, direction = 1) {
    const size = Number(count);
    if (!Number.isInteger(size) || size <= 0) return 0;
    const current = Number.isInteger(Number(index)) ? Number(index) : 0;
    return ((current + Number(direction) % size) % size + size) % size;
  }

  function settingsExpanded(current, action = "toggle") {
    return action === "expand" ? true : action === "collapse" ? false : !Boolean(current);
  }

  function activeAwaitingItem(test) {
    return test?.items?.find((item) => item.status === "complete" && item.image_score == null) || null;
  }

  function hasPendingGeneration(test) {
    return Boolean(test?.items?.some((item) => item.status === "pending" || item.status === "processing"));
  }

  function promptVariantTotal(variants, artistCount) {
    const count = Number(artistCount);
    if (!Number.isFinite(count) || count < 0) return 0;
    return (Array.isArray(variants) ? variants : []).reduce((total, variant) => total + Math.max(0, Number(variant?.images_per_artist) || 0), 0) * count;
  }

  function generationEvaluationReady(test) {
    return !hasPendingGeneration(test) && Boolean(activeAwaitingItem(test));
  }

  function isEvaluationPending(test) {
    const total = Number(test?.total_count || 0);
    const generated = Number(test?.generated_count ?? test?.completed_count ?? 0);
    const rated = Number(test?.rated_count || 0);
    return total > 0 && generated >= total && rated < total;
  }

  function preferredInteractiveItem(test, previousId = null) {
    if (!test || !Array.isArray(test.items)) return null;
    const awaiting = activeAwaitingItem(test);
    if (!hasPendingGeneration(test) && awaiting) return awaiting;
    return test.items.find((item) => item.id === previousId)
      || [...test.items].reverse().find((item) => item.status === "complete")
      || test.items.find((item) => item.status === "processing")
      || test.items.find((item) => item.status === "pending")
      || null;
  }

  function remainingDelayMs(delaySeconds, generationRequestedAt, now = Date.now()) {
    const delay = Number(delaySeconds);
    const started = Date.parse(generationRequestedAt || "");
    if (!Number.isFinite(delay) || delay <= 0 || !Number.isFinite(started)) return 0;
    return Math.max(0, delay * 1000 - (Number(now) - started));
  }

  function averageScores(scores) {
    const values = (Array.isArray(scores) ? scores : []).map(Number).filter((value) => Number.isFinite(value));
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  }

  const FULL_CAPACITY_IMAGES = 1728;

  function isV5Model(model) {
    return /^nai-diffusion-5(?:-|$)/i.test(String(model || ""));
  }

  function pendingGenerationCount(test) {
    return Array.isArray(test?.items)
      ? test.items.filter((item) => item.status === "pending" || item.status === "processing").length
      : 0;
  }

  function appendTargetArtists(items, targetScope = "all") {
    const result = [];
    const keys = new Set();
    (Array.isArray(items) ? items : []).forEach((item) => {
      if (targetScope === "remaining" && item.status !== "pending" && item.status !== "processing") return;
      const key = artistKey(item);
      if (!key || keys.has(key)) return;
      keys.add(key); result.push(item.artist_tag);
    });
    return result;
  }

  function estimateV5Usage(usageValue, pendingCount, model) {
    const pending = Math.max(0, Math.floor(Number(pendingCount) || 0));
    if (!isV5Model(model)) return { eligible: false, model: String(model || ""), pending_count: pending, message: "V4.5는 Usage 소모 대상이 아닙니다." };
    const source = usageValue?.usage && typeof usageValue.usage === "object" ? usageValue.usage : usageValue;
    const percent = Number(source?.percent);
    if (!Number.isFinite(percent)) return { eligible: true, available: false, pending_count: pending, message: "현재 V5 Usage를 확인할 수 없어 추정하지 않습니다." };
    const currentPercent = Math.max(0, Math.min(100, percent));
    const expectedPercent = pending / FULL_CAPACITY_IMAGES * 100;
    const currentRemainingImages = currentPercent / 100 * FULL_CAPACITY_IMAGES;
    return {
      eligible: true, available: true, pending_count: pending, current_percent: currentPercent,
      expected_percent: expectedPercent, expected_remaining_percent: Math.max(0, currentPercent - expectedPercent),
      current_remaining_images: currentRemainingImages,
      expected_remaining_images: Math.max(0, currentRemainingImages - pending),
    };
  }

  function usageEstimateForConfig(usageValue, pendingCount, config = {}) {
    const estimate = estimateV5Usage(usageValue, pendingCount, config.model);
    const risk = v5AnlasRisk(config);
    if (!risk) return { ...estimate, anlasRisk: false };
    const current = estimate.available
      ? `현재 Usage ${estimate.current_percent.toFixed(1)}%(약 ${Math.round(estimate.current_remaining_images)}장)`
      : "현재 Usage를 확인할 수 없음";
    const { expected_percent: _expectedPercent, expected_remaining_percent: _expectedRemainingPercent, expected_remaining_images: _expectedRemainingImages, ...usageOnly } = estimate;
    return {
      ...usageOnly,
      anlasRisk: true,
      usageConversion: false,
      message: `V5 ${current} · 이번 batch는 Usage 환산 대상 아님 · steps 28 초과/1,048,576px 초과로 Anlas가 사용될 수 있음`,
    };
  }

  function v5AnlasRisk(config = {}) {
    return isV5Model(config.model) && (Number(config.steps) > 28 || Number(config.width) * Number(config.height) > 1048576);
  }

  function generationControlState(test, inFlight = false, ratingSubmitting = false) {
    const evaluationPending = isEvaluationPending(test);
    const status = test?.status || "pending";
    const pending = pendingGenerationCount(test);
    const startable = !inFlight && !ratingSubmitting && !evaluationPending && status !== "running" && status !== "completed" && pending > 0;
    const startActive = startable;
    const pauseActive = status === "running" && !evaluationPending && pending > 0;
    return {
      startLabel: status === "cancelled" ? "중단된 일괄 생성 재개" : status === "paused" ? "한꺼번에 생성 재개" : evaluationPending ? "평가 대기" : status === "completed" ? "생성 완료" : "남은 이미지 한꺼번에 생성",
      statusLabel: evaluationPending ? "평가 대기" : status === "cancelled" ? "중단(재개 가능)" : ({ pending: "대기", running: "실행 중", paused: "일시정지", completed: "완료" }[status] || "대기"),
      startDisabled: !startable,
      singleDisabled: !startable,
      batchDisabled: !startable,
      pauseDisabled: status !== "running" || evaluationPending || inFlight === false && pending === 0,
      cancelDisabled: status === "completed",
      startActive,
      pauseActive,
      statusState: evaluationPending ? "evaluation" : status,
    };
  }

  function startConfirmationPlan(config = {}, estimate = {}, pendingCount = 0) {
    const pending = Math.max(0, Math.floor(Number(pendingCount) || 0));
    const anlasRisk = v5AnlasRisk(config);
    const firstMessage = anlasRisk
      ? `NAI 작가 테스트를 시작/재개합니다. 총 ${pending}장의 생성 요청이 남았습니다. V5 steps 28 초과/1,048,576px 초과로 Anlas가 사용될 수 있습니다.`
      : estimate?.eligible === false
        ? `NAI 작가 테스트를 시작/재개합니다. 총 ${pending}장의 생성 요청이 남았습니다. V4.5는 Usage 소모 대상이 아닙니다.`
        : `NAI 작가 테스트를 시작/재개합니다. 총 ${pending}장의 생성 요청이 남았습니다.`;
    return {
      requiresFirstConfirm: pending > 0,
      requiresFinalConfirm: pending > 0 && anlasRisk,
      anlasRisk,
      firstMessage,
      finalMessage: anlasRisk ? "현재 설정에서 Anlas가 사용될 수 있음(steps 28 초과 또는 해상도 초과)을 확인했습니다. 최종적으로 생성 요청을 진행할까요?" : "",
      estimate,
    };
  }

  function promptVariantTabs(test = {}) {
    const variants = Array.isArray(test?.config?.prompt_variants) && test.config.prompt_variants.length
      ? test.config.prompt_variants
      : [{ prompt: test?.config?.base_prompt || "", images_per_artist: test?.images_per_artist || 1 }];
    return [{ promptIndex: "all", label: "전체" }, ...variants.map((variant, index) => ({ promptIndex: index, label: `프롬프트 ${index + 1}` }))];
  }

  function filterNaiArtistTestResults(items, artistQuery = "", scoreFilter = "all", promptIndex = "all") {
    const query = String(artistQuery || "").trim().toLocaleLowerCase();
    return (Array.isArray(items) ? items : []).filter((item) => {
      if (item?.status !== "complete" || !item?.image_path) return false;
      if (query && !String(item.artist_tag || "").toLocaleLowerCase().includes(query)) return false;
      if (scoreFilter === "unrated" && item.image_score != null) return false;
      if (scoreFilter !== "all" && scoreFilter !== "unrated" && String(item.image_score) !== String(scoreFilter)) return false;
      if (promptIndex !== "all" && String(item.prompt_index ?? 0) !== String(promptIndex)) return false;
      return true;
    });
  }

  function startWarningSummary(config = {}, estimate = {}, pendingCount = 0, delaySeconds = 0) {
    const pending = Math.max(0, Math.floor(Number(pendingCount) || 0));
    const delay = Number(delaySeconds);
    const delayText = Number.isFinite(delay) ? `요청 사이에 ${delay}초 딜레이를 적용합니다.` : "요청 사이에 설정된 딜레이를 적용합니다.";
    if (estimate?.anlasRisk) return `${estimate.message}. ${pending}장의 남은 이미지를 순차 생성하며 ${delayText} 모든 수치는 추정치입니다.`;
    if (estimate?.eligible === false) return `V4.5는 Usage 대상 아님. ${pending}장의 남은 이미지를 순차 생성하며 ${delayText}`;
    if (!estimate?.available) return `남은 생성 ${pending}장. ${delayText} Usage를 확인할 수 없어 소모량은 추정하지 않습니다.`;
    return `남은 생성 ${pending}장. 현재 V5 Usage ${estimate.current_percent.toFixed(1)}%(약 ${Math.round(estimate.current_remaining_images)}장), ${pending}장 생성 예상 소모 ${estimate.expected_percent.toFixed(1)}%, 생성 후 약 ${estimate.expected_remaining_percent.toFixed(1)}%(약 ${Math.round(estimate.expected_remaining_images)}장). ${delayText} 모두 추정치입니다.`;
  }

  function cycleResultViewerIndex(index, count, direction = 1) {
    return cyclePreviewIndex(index, count, direction);
  }

  function naiArtistTestViews(active) {
    return { list: active === "list", editor: active === "editor", detail: active === "detail" };
  }

  function showView(view) {
    state.view = view;
    ["list", "editor", "detail"].forEach((name) => $("naiArtistTest" + name[0].toUpperCase() + name.slice(1) + "View")?.classList.toggle("hidden", name !== view));
    if (view === "list") { closeImageViewer(); state.selectedTest = null; return loadTests(); }
  }

  function setSelectedArtists(artists) {
    state.selectedArtists = Array.isArray(artists) ? artists : [];
    renderArtists();
  }

  function toggleSelectedArtist(artist) {
    setSelectedArtists(toggleArtistSelection(state.selectedArtists, artist));
  }

  function renderPreview() {
    const artist = state.activeArtist;
    const image = $("naiArtistTestPreviewImage");
    const current = state.previewImages[state.previewIndex] || "";
    text($("naiArtistTestPreviewArtist"), artist?.artist_tag || "작가를 선택하세요");
    text($("naiArtistTestPreviewCounter"), current ? `${state.previewIndex + 1} / ${state.previewImages.length}` : "0 / 0");
    text($("naiArtistTestPreviewStatus"), current ? state.previewStatus : (state.previewStatus || (artist ? "저장 이미지가 없습니다." : "카드를 클릭하면 대표 이미지와 저장 예제를 볼 수 있습니다.")));
    if (image) {
      image.hidden = !current;
      if (current) {
        image.dataset.previewUrl = current;
        image.onerror = () => { if (image.dataset.previewUrl !== current) return; image.hidden = true; text($("naiArtistTestPreviewStatus"), "미리보기 이미지를 불러오지 못했습니다."); };
        image.src = current; image.alt = `${artist?.artist_tag || "작가"} 미리보기`;
      } else { image.removeAttribute("src"); delete image.dataset.previewUrl; image.onerror = null; }
    }
    [$("naiArtistTestPreviewPrevious"), $("naiArtistTestPreviewNext")].forEach((button) => { if (button) button.disabled = state.previewImages.length < 2; });
  }

  async function setActiveArtist(artist) {
    if (!artist) return;
    const key = artistKey(artist);
    const token = ++state.previewRequestToken;
    state.activeArtist = { ...artist };
    state.previewImages = uniquePreviewImages(artist);
    state.previewIndex = 0;
    state.previewStatus = artist.rating_id ? "저장 예제를 불러오는 중..." : "저장 예제 정보가 없습니다.";
    renderPreview();
    if (!artist.rating_id) return;
    try {
      const payload = await api(`/api/ratings/${encodeURIComponent(artist.rating_id)}/examples`);
      if (token !== state.previewRequestToken || artistKey(state.activeArtist) !== key) return;
      const representative = payload?.rating?.thumbnail_url || state.activeArtist.thumbnail_url;
      state.previewImages = uniquePreviewImages({ ...state.activeArtist, thumbnail_url: representative }, payload?.examples);
      state.previewStatus = state.previewImages.length ? "" : "저장 이미지가 없습니다.";
      renderPreview();
    } catch (error) {
      if (token !== state.previewRequestToken || artistKey(state.activeArtist) !== key) return;
      state.previewStatus = "저장 예제를 불러오지 못했습니다.";
      renderPreview();
    }
  }

  function stepPreview(direction) {
    if (!state.previewImages.length) return;
    state.previewIndex = cyclePreviewIndex(state.previewIndex, state.previewImages.length, direction);
    renderPreview();
  }

  function updateMarqueeSelection(target, marquee) {
    const left = Math.min(marquee.startX, marquee.currentX);
    const right = Math.max(marquee.startX, marquee.currentX);
    const top = Math.min(marquee.startY, marquee.currentY);
    const bottom = Math.max(marquee.startY, marquee.currentY);
    const cards = [...target.querySelectorAll(".nai-artist-test-artist-row")].map((card) => {
      const rect = card.getBoundingClientRect();
      return { artist_key: card.dataset.artistKey, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
    });
    const keys = new Set(marqueeSelectedArtistKeys(cards, { left, right, top, bottom }, [...marquee.initialKeys]));
    const selectedByKey = new Map(state.selectedArtists.map((artist) => [artistKey(artist), artist]));
    state.artists.forEach((artist) => { if (keys.has(artistKey(artist))) selectedByKey.set(artistKey(artist), artist); });
    state.selectedArtists = [...selectedByKey.values()];
    const count = $("naiArtistTestSelectionCount");
    text(count, state.selectedArtists.length ? `${state.selectedArtists.length}명 선택됨` : "선택된 작가 없음");
    target.querySelectorAll(".nai-artist-test-artist-row").forEach((card) => {
      const selected = state.selectedArtists.some((artist) => artistKey(artist) === card.dataset.artistKey);
      card.classList.toggle("is-selected", selected); card.setAttribute("aria-pressed", String(selected));
    });
  }

  function marqueeRectElement(target) {
    let marquee = target.querySelector(".nai-artist-test-marquee");
    if (!marquee) { marquee = document.createElement("div"); marquee.className = "nai-artist-test-marquee"; target.append(marquee); }
    return marquee;
  }

  function updateMarqueeOverlay(target, marquee) {
    const element = marqueeRectElement(target); const bounds = target.getBoundingClientRect();
    element.style.left = `${Math.min(marquee.startX, marquee.currentX) - bounds.left + target.scrollLeft}px`;
    element.style.top = `${Math.min(marquee.startY, marquee.currentY) - bounds.top + target.scrollTop}px`;
    element.style.width = `${Math.abs(marquee.currentX - marquee.startX)}px`; element.style.height = `${Math.abs(marquee.currentY - marquee.startY)}px`;
    updateMarqueeSelection(target, marquee);
  }

  function stopMarqueeAutoScroll() {
    if (state.marqueeScrollFrame != null) cancelAnimationFrame(state.marqueeScrollFrame);
    state.marqueeScrollFrame = null;
  }

  function startMarqueeAutoScroll(target, pointerY) {
    if (!state.marquee?.moved) return;
    state.marquee.pointerY = pointerY;
    if (state.marqueeScrollFrame != null) return;
    const tick = () => {
      state.marqueeScrollFrame = null;
      const marquee = state.marquee;
      if (!marquee?.moved) return;
      const delta = marqueeAutoScrollDelta(marquee.pointerY, window.innerHeight);
      if (!delta) return;
      const view = target.closest(".nai-artist-test-view");
      const scroller = target.scrollHeight > target.clientHeight ? target : (view && view.scrollHeight > view.clientHeight ? view : window);
      if (scroller === window) window.scrollBy(0, delta); else scroller.scrollTop += delta;
      updateMarqueeOverlay(target, marquee);
      state.marqueeScrollFrame = requestAnimationFrame(tick);
    };
    state.marqueeScrollFrame = requestAnimationFrame(tick);
  }

  function bindArtistGallery(target) {
    if (!target || target.dataset.bound === "true") return;
    target.dataset.bound = "true";
    target.addEventListener("click", (event) => {
      const card = event.target.closest(".nai-artist-test-artist-row");
      if (!card || !target.contains(card)) return;
      if (state.suppressGalleryClick) { state.suppressGalleryClick = false; return; }
      const artist = state.artists.find((item) => artistKey(item) === card.dataset.artistKey);
      if (artist) { void setActiveArtist(artist); toggleSelectedArtist(artist); }
    });
    target.addEventListener("keydown", (event) => {
      const card = event.target.closest(".nai-artist-test-artist-row");
      if (!card || !target.contains(card) || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      const artist = state.artists.find((item) => artistKey(item) === card.dataset.artistKey);
      if (artist) { void setActiveArtist(artist); toggleSelectedArtist(artist); }
    });
    target.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest("button, input, select, textarea")) return;
      const card = event.target.closest(".nai-artist-test-artist-row");
      state.marquee = { startX: event.clientX, startY: event.clientY, currentX: event.clientX, currentY: event.clientY, moved: false, card, initialKeys: new Set(state.selectedArtists.map(artistKey)) };
      target.setPointerCapture?.(event.pointerId); event.preventDefault();
    });
    target.addEventListener("pointermove", (event) => {
      const marquee = state.marquee; if (!marquee) return;
      marquee.currentX = event.clientX; marquee.currentY = event.clientY;
      const distance = Math.hypot(marquee.currentX - marquee.startX, marquee.currentY - marquee.startY);
      if (!marquee.moved && !isMarqueeDrag(distance)) return;
      marquee.moved = true; event.preventDefault();
      updateMarqueeOverlay(target, marquee); startMarqueeAutoScroll(target, event.clientY);
    });
    const finishMarquee = (event) => {
      const marquee = state.marquee; if (!marquee) return;
      stopMarqueeAutoScroll();
      if (marquee.moved) {
        state.suppressGalleryClick = true; updateMarqueeSelection(target, marquee); marqueeRectElement(target).remove();
      } else if (marquee.card) {
        const artist = state.artists.find((item) => artistKey(item) === marquee.card.dataset.artistKey);
        if (artist) { state.suppressGalleryClick = true; void setActiveArtist(artist); toggleSelectedArtist(artist); }
      }
      target.releasePointerCapture?.(event.pointerId); state.marquee = null;
    };
    target.addEventListener("pointerup", finishMarquee); target.addEventListener("pointercancel", finishMarquee);
  }

  function renderArtists() {
    const target = $("naiArtistTestArtists");
    if (!target) return;
    bindArtistGallery(target);
    target.replaceChildren();
    const selectAll = $("naiArtistTestSelectAll"); if (selectAll) selectAll.disabled = !state.artists.length;
    if (!state.artists.length) { const empty = document.createElement("p"); empty.className = "nai-artist-test-empty"; empty.textContent = "조건에 맞는 평가 작가가 없습니다."; target.append(empty); text($("naiArtistTestSelectionCount"), state.selectedArtists.length ? `${state.selectedArtists.length}명 선택됨` : "선택된 작가 없음"); return; }
    state.artists.forEach((artist) => {
      const row = document.createElement("div"); row.className = "nai-artist-test-artist-row";
      const selected = state.selectedArtists.some((item) => artistKey(item) === artistKey(artist));
      row.dataset.artistKey = artistKey(artist); row.tabIndex = 0; row.setAttribute("role", "button"); row.setAttribute("aria-pressed", String(selected)); row.classList.toggle("is-selected", selected);
      if (artist.thumbnail_url) { const image = document.createElement("img"); image.src = artist.thumbnail_url; image.alt = `${artist.artist_tag} 대표 이미지`; image.draggable = false; row.append(image); }
      else { const placeholder = document.createElement("div"); placeholder.className = "nai-artist-test-thumbnail-placeholder"; placeholder.textContent = "이미지 없음"; row.append(placeholder); }
      const details = document.createElement("div"); details.className = "nai-artist-test-artist-details";
      const name = document.createElement("strong"); name.textContent = artist.artist_tag;
      const oldScore = document.createElement("span"); oldScore.className = "artist-score"; oldScore.textContent = `기존 ${artist.danbooru_score}점`;
      const directScore = document.createElement("span"); directScore.className = "artist-score nai-direct-score"; directScore.textContent = artist.nai_direct_score == null ? "NAI 직접 평가 없음" : `NAI 직접 ${artist.nai_direct_score}점`;
      details.append(name, oldScore, directScore); row.append(details); target.append(row);
    });
    text($("naiArtistTestSelectionCount"), state.selectedArtists.length ? `${state.selectedArtists.length}명 선택됨` : "선택된 작가 없음");
  }

  async function loadArtists() {
    try {
      const params = new URLSearchParams({ score_min: $("naiArtistTestScoreMin")?.value || "1", score_max: $("naiArtistTestScoreMax")?.value || "5", q: $("naiArtistTestArtistSearch")?.value || "", sort: $("naiArtistTestArtistSort")?.value || "recent" });
      state.artists = await api(`/api/nai-artist-tests/artists?${params}`);
      renderArtists();
    } catch (error) { setStatus(error.message, "error"); }
  }

  function renderTests() {
    const target = $("naiArtistTestTests");
    if (!target) return;
    target.replaceChildren();
    if (!state.tests.length) {
      const empty = document.createElement("div"); empty.className = "nai-artist-test-empty"; empty.textContent = "저장된 테스트가 없습니다. 상단의 ‘테스트 추가’에서 첫 묶음을 만들어 보세요."; target.append(empty); return;
    }
    const statusLabels = { pending: "대기", running: "실행 중", paused: "일시정지", cancelled: "중단", completed: "완료" };
    state.tests.forEach((test) => {
      const card = document.createElement("article"); card.className = "nai-artist-test-batch"; card.dataset.testId = String(test.id);
      const button = document.createElement("button"); button.type = "button"; button.className = "nai-artist-test-batch-open"; button.dataset.testId = String(test.id); button.setAttribute("aria-label", `${test.name} 테스트 상세 보기`);
      if (test.cover_image_path) { const image = document.createElement("img"); image.src = `/generated/${test.cover_image_path}`; image.alt = `${test.name} 대표 이미지`; button.append(image); }
      else { const placeholder = document.createElement("span"); placeholder.className = "nai-artist-test-batch-placeholder"; placeholder.textContent = "이미지 없음"; button.append(placeholder); }
      const details = document.createElement("span"); details.className = "nai-artist-test-batch-details";
      const title = document.createElement("strong"); title.textContent = test.name;
      const meta = document.createElement("span"); meta.textContent = `${isEvaluationPending(test) ? "평가 대기" : (test.status === "cancelled" ? "중단(재개 가능)" : (statusLabels[test.status] || "대기"))} · 생성 ${test.generated_count ?? test.completed_count ?? 0}/${test.total_count || 0} · 평가 ${test.rated_count || 0}/${test.total_count || 0} · 남음 ${test.remaining_count || 0}`;
      details.append(title, meta); button.append(details); button.addEventListener("click", () => selectTest(test.id));
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "ghost nai-artist-test-delete"; remove.textContent = "삭제"; remove.setAttribute("aria-label", `${test.name} 테스트 삭제`); remove.addEventListener("click", (event) => { event.stopPropagation(); void deleteTestById(test.id); });
      card.append(button, remove); target.append(card);
    });
  }

  function deleteConfirmationMessage() {
    return "테스트 기록·항목·평가가 삭제되며 되돌릴 수 없습니다.\n생성된 이미지 파일과 일반 생성 기록은 삭제되지 않습니다.\n정말 삭제하시겠습니까?";
  }

  function closeDeleteWarning(result = false) {
    $("naiArtistTestDeleteModal")?.classList.add("hidden");
    const resolve = state.deleteWarningResolver;
    state.deleteWarningResolver = null;
    state.deleteWarningTestId = null;
    if (resolve) resolve(Boolean(result));
  }

  function openDeleteWarning(testId) {
    const id = Number(testId); const test = state.tests.find((item) => Number(item.id) === id) || state.selectedTest;
    const modal = $("naiArtistTestDeleteModal");
    if (!modal || !test) return Promise.resolve(false);
    text($("naiArtistTestDeleteName"), test.name || "이 테스트");
    modal.classList.remove("hidden"); state.deleteWarningTestId = id;
    $("naiArtistTestDeleteConfirm")?.focus();
    return new Promise((resolve) => { state.deleteWarningResolver = resolve; });
  }

  async function deleteTestById(testId) {
    const id = Number(testId);
    if (!Number.isInteger(id) || id < 1) return false;
    if (!(await openDeleteWarning(id))) return false;
    try {
      await api(`/api/nai-artist-tests/${id}`, { method: "DELETE" });
      if (state.selectedTest?.id === id) await showView("list");
      else await loadTests();
      setStatus("NAI 작가 테스트를 삭제했습니다.", "ok");
      return true;
    } catch (error) {
      setStatus(error.message, "error");
      return false;
    }
  }

  function renderListMode() {
    const tests = $("naiArtistTestTests"); const artists = $("naiArtistTestArtistModeView"); const detail = $("naiArtistTestArtistDetailView");
    tests?.classList.toggle("hidden", state.listMode !== "tests");
    artists?.classList.toggle("hidden", state.listMode !== "artists" || Boolean(state.selectedHistoryArtist));
    detail?.classList.toggle("hidden", state.listMode !== "artists" || !state.selectedHistoryArtist);
    [$("naiArtistTestTestMode"), $("naiArtistTestArtistMode")].forEach((button) => {
      if (!button) return;
      const active = (button.id === "naiArtistTestTestMode") === (state.listMode === "tests");
      button.setAttribute("aria-selected", String(active));
      button.classList.toggle("primary", active);
      button.classList.toggle("ghost", !active);
      button.classList.toggle("is-active", active);
    });
  }

  function renderArtistSummaries() {
    const target = $("naiArtistTestArtistSummaries"); if (!target) return;
    target.replaceChildren();
    const query = String($("naiArtistTestHistoryArtistSearch")?.value || "").trim().toLocaleLowerCase();
    const artists = state.artistHistory.artists.filter((artist) => !query || String(artist.artist_tag || "").toLocaleLowerCase().includes(query));
    artists.forEach((artist) => {
      const button = document.createElement("button"); button.type = "button"; button.className = "nai-artist-test-artist-summary";
      if (artist.cover_image_path) { const image = document.createElement("img"); image.src = `/generated/${artist.cover_image_path}`; image.alt = `${artist.artist_tag} 대표 이미지`; button.append(image); }
      else { const placeholder = document.createElement("span"); placeholder.className = "nai-artist-test-batch-placeholder"; placeholder.textContent = "이미지 없음"; button.append(placeholder); }
      const name = document.createElement("strong"); name.textContent = artist.artist_tag;
      const meta = document.createElement("span"); meta.textContent = `이미지 ${artist.image_count}장 · 평가 ${artist.rated_count}장 · 평균 ${artist.average == null ? "없음" : Number(artist.average).toFixed(2)}점`;
      button.append(name, meta); button.addEventListener("click", () => selectHistoryArtist(artist.artist_tag)); target.append(button);
    });
    if (!target.children.length) { const empty = document.createElement("p"); empty.className = "nai-artist-test-empty"; empty.textContent = "생성된 작가 이미지가 없습니다."; target.append(empty); }
  }

  function renderArtistHistoryResults() {
    const target = $("naiArtistTestArtistHistoryResults"); if (!target || !state.selectedHistoryArtist) return;
    target.replaceChildren();
    const items = state.artistHistory.items.filter((item) => item.artist_tag === state.selectedHistoryArtist);
    items.forEach((item) => {
      const card = document.createElement("button"); card.type = "button"; card.className = "nai-artist-test-image-card"; card.setAttribute("aria-label", `${item.artist_tag} ${item.test_name} ${item.ordinal}번 이미지 크게 보기`);
      const image = document.createElement("img"); image.src = item.image_url || `/generated/${item.image_path}`; image.alt = `${item.artist_tag} 생성 표본 ${item.ordinal}`;
      const title = document.createElement("strong"); title.textContent = `${item.test_name} · ${item.ordinal}번`;
      const score = document.createElement("span"); score.textContent = item.image_score == null ? "이미지 평가 대기" : `이미지 평가 ${item.image_score}점`;
      const prompt = document.createElement("small"); prompt.textContent = item.effective_prompt || item.prompt_template || "프롬프트 없음";
      card.append(image, title, score, prompt); card.addEventListener("click", () => openImageViewer(item, items)); target.append(card);
    });
    if (!target.children.length) { const empty = document.createElement("p"); empty.className = "nai-artist-test-empty"; empty.textContent = "이 작가의 생성 이미지가 없습니다."; target.append(empty); }
  }

  function renderPromptTabs() {
    const target = $("naiArtistTestPromptTabs"); if (!target || !state.selectedTest) return;
    target.replaceChildren();
    promptVariantTabs(state.selectedTest).forEach((tab) => {
      const button = document.createElement("button"); button.type = "button"; button.className = state.resultPromptIndex === tab.promptIndex ? "primary" : "ghost"; button.textContent = tab.label; button.setAttribute("aria-pressed", String(state.resultPromptIndex === tab.promptIndex)); button.dataset.promptIndex = String(tab.promptIndex);
      button.addEventListener("click", () => {
        state.resultPromptIndex = tab.promptIndex;
        const scoped = tab.promptIndex === "all" ? state.selectedTest : { ...state.selectedTest, items: state.selectedTest.items.filter((item) => String(item.prompt_index ?? 0) === String(tab.promptIndex)) };
        const preferred = preferredInteractiveItem(scoped, state.currentItemId);
        state.currentItemId = preferred?.id || (tab.promptIndex === "all" ? state.currentItemId : null);
        renderPromptTabs(); renderResults(); renderCurrentWorkspace(); renderProgress();
      });
      target.append(button);
    });
  }

  async function loadArtistHistory() {
    try { closeImageViewer(); state.artistHistory = await api(`/api/nai-artist-tests/artist-history?q=${encodeURIComponent($("naiArtistTestHistoryArtistSearch")?.value || "")}`); renderArtistSummaries(); renderArtistHistoryResults(); } catch (error) { setStatus(error.message, "error"); }
  }

  function selectHistoryArtist(artistTag) {
    state.selectedHistoryArtist = artistTag; renderListMode(); renderArtistHistoryResults();
    text($("naiArtistTestArtistDetailTitle"), artistTag);
    const summary = state.artistHistory.artists.find((artist) => artist.artist_tag === artistTag);
    text($("naiArtistTestArtistDetailMeta"), summary ? `이미지 ${summary.image_count}장 · 평균 ${summary.average == null ? "없음" : Number(summary.average).toFixed(2)}점` : "");
  }

  async function loadTests() {
    try { state.tests = await api("/api/nai-artist-tests"); renderTests(); renderListMode(); if (state.listMode === "artists") await loadArtistHistory(); if (state.selectedTest && state.view === "detail") await selectTest(state.selectedTest.id); } catch (error) { setStatus(error.message, "error"); }
  }

  function currentInteractiveItem() {
    if (!state.selectedTest) return null;
    return preferredInteractiveItem(state.selectedTest, state.currentItemId);
  }

  function renderItemSettings(item) {
    const target = $("naiArtistTestItemSettings"); if (!target) return;
    target.replaceChildren();
    if (!item || !state.selectedTest) { const empty = document.createElement("p"); empty.className = "help-text"; empty.textContent = "이미지가 생성되면 설정이 표시됩니다."; target.append(empty); return; }
    const config = state.selectedTest.config || {};
    const values = [
      ["작가", item.artist_tag], ["모델", config.model], ["해상도", `${config.width || "?"} × ${config.height || "?"}`],
      ["샘플러", config.sampler], ["스케줄러", config.noise_schedule], ["Steps", config.steps], ["CFG", config.scale],
      ["Rescale", config.cfg_rescale], ["Seed", config.seed == null ? "자동" : config.seed],
      ["프롬프트", String(item.prompt_template || config.base_prompt || "").replace("{{artist}}", item.artist_tag)],
      ["네거티브", config.negative_prompt || "없음"], ["캐릭터", Array.isArray(config.character_prompts) && config.character_prompts.length ? config.character_prompts.join("\n") : "없음"],
    ];
    values.forEach(([label, value]) => { const row = document.createElement("div"); row.className = "nai-artist-test-setting-row"; const name = document.createElement("strong"); name.textContent = label; const content = document.createElement("span"); content.textContent = String(value ?? ""); row.append(name, content); target.append(row); });
  }

  function renderCurrentWorkspace() {
    const item = currentInteractiveItem();
    const image = $("naiArtistTestCurrentImage"); const status = $("naiArtistTestCurrentImageStatus"); const buttons = $("naiArtistTestRatingButtons");
    text($("naiArtistTestCurrentArtist"), item ? item.artist_tag : "현재 이미지");
    text($("naiArtistTestCurrentItemMeta"), item ? `항목 ${item.ordinal} · ${item.image_score == null ? "평가 대기" : `이미지 ${item.image_score}점`}` : "");
    if (image) {
      const url = item?.image_path ? `/generated/${item.image_path}` : "";
      image.hidden = !url; if (url) { image.src = url; image.alt = `${item.artist_tag} 생성 이미지`; } else image.removeAttribute("src");
    }
    text(status, item?.image_path ? (item.image_score == null ? (state.ratingWaiting ? (state.nextStatus || "이 이미지의 점수를 선택하세요.") : (state.nextStatus || "전체 이미지를 생성하는 중입니다.")) : (state.selectedTest?.status === "completed" ? `이미지 평가 ${item.image_score}점 · 테스트 완료` : (state.nextStatus || `이미지 평가 ${item.image_score}점`))) : "생성된 이미지를 기다리는 중입니다.");
    if (buttons) {
      buttons.replaceChildren();
      if (item?.image_path && (state.ratingWaiting || (item.image_score != null && !hasPendingGeneration(state.selectedTest)))) for (let score = 1; score <= 5; score += 1) { const button = document.createElement("button"); button.type = "button"; button.className = "nai-artist-test-rating-button"; button.textContent = `${score}점`; button.setAttribute("aria-label", `${score}점으로 평가`); button.disabled = state.ratingSubmitting || item.image_score != null; button.classList.toggle("is-selected", item.image_score === score); button.addEventListener("click", () => { void rateItem(item, score); }); buttons.append(button); }
    }
    renderItemSettings(item);
  }

  function renderWorkspaceToggle() {
    const workspace = $("naiArtistTestWorkspace");
    const workspaceHead = $("naiArtistTestWorkspaceHead") || document.querySelector("#naiArtistTestDetailView .nai-artist-test-workspace-head");
    const button = $("naiArtistTestWorkspaceToggle");
    const detailView = $("naiArtistTestDetailView");
    const expanded = state.workspaceExpanded !== false;
    detailView?.classList.toggle("is-workspace-collapsed", !expanded);
    ["naiArtistTestDetailStatus", "naiArtistTestCurrent", "naiArtistTestUsagePreflight"].forEach((id) => {
      const summary = $(id);
      if (summary) {
        summary.hidden = !expanded;
        summary.classList.toggle("is-workspace-collapsed", !expanded);
      }
    });
    if (workspaceHead) {
      workspaceHead.classList.toggle("is-collapsed", !expanded);
      workspaceHead.dataset.state = expanded ? "expanded" : "collapsed";
    }
    if (workspace) {
      workspace.hidden = !expanded;
      workspace.classList.toggle("hidden", !expanded);
      workspace.classList.toggle("is-collapsed", !expanded);
    }
    if (button) {
      button.setAttribute("aria-expanded", String(expanded));
      button.setAttribute("aria-label", expanded ? "현재 생성창 접기" : "현재 생성창 펼치기");
      button.title = expanded ? "현재 생성창 접기" : "현재 생성창 펼치기";
      text(button, expanded ? "생성창 접기" : "생성창 펼치기");
    }
  }

  function closeImageViewer() {
    const modal = $("naiArtistTestImageModal");
    modal?.classList.add("hidden"); state.viewerItems = []; state.viewerIndex = 0;
  }

  function renderImageViewer() {
    const item = state.viewerItems[state.viewerIndex]; const modal = $("naiArtistTestImageModal");
    if (!item || !modal) { closeImageViewer(); return; }
    const image = $("naiArtistTestImageModalImage"); if (image) { image.src = `/generated/${item.image_path}`; image.alt = `${item.artist_tag} 생성 표본 ${item.ordinal}`; }
    const artist = state.selectedTest?.artists?.find((entry) => entry.artist_tag === item.artist_tag);
    const config = item.config || state.selectedTest?.config || {};
    const average = artist?.nai_direct_score ?? item.nai_direct_score;
    const meta = $("naiArtistTestImageModalMeta"); if (meta) { meta.replaceChildren(); [["작가", item.artist_tag], ["테스트", item.test_name || state.selectedTest?.name || "현재 테스트"], ["항목", item.ordinal], ["이미지 점수", item.image_score == null ? "미평가" : `${item.image_score}점`], ["작가 평균", average == null ? "없음" : `${Number(average).toFixed(2)}점`], ["프롬프트", item.effective_prompt || String(item.prompt_template || config.base_prompt || "").replace("{{artist}}", item.artist_tag)], ["네거티브", config.negative_prompt || "없음"], ["캐릭터", Array.isArray(config.character_prompts) && config.character_prompts.length ? config.character_prompts.join("\n") : "없음"], ["모델", config.model || "없음"], ["해상도", config.width && config.height ? `${config.width} × ${config.height}` : "없음"], ["Sampler / Scheduler", `${config.sampler || "?"} / ${config.noise_schedule || "?"}`], ["Steps / CFG / Rescale", `${config.steps ?? "?"} / ${config.scale ?? "?"} / ${config.cfg_rescale ?? "?"}`], ["Seed", config.seed == null ? "자동" : config.seed]].forEach(([label, value]) => { const row = document.createElement("div"); const name = document.createElement("strong"); name.textContent = label; const content = document.createElement("span"); content.textContent = String(value); row.append(name, content); meta.append(row); }); }
    text($("naiArtistTestImageModalTitle"), `${item.artist_tag} · ${state.viewerIndex + 1}/${state.viewerItems.length}`);
    $("naiArtistTestImageModalPrevious")?.toggleAttribute("disabled", state.viewerItems.length < 2); $("naiArtistTestImageModalNext")?.toggleAttribute("disabled", state.viewerItems.length < 2);
  }

  function openImageViewer(item, sourceItems = null) {
    const items = Array.isArray(sourceItems) ? sourceItems : filterNaiArtistTestResults(state.selectedTest?.items, state.resultArtistFilter, state.resultScoreFilter, state.resultPromptIndex);
    const index = items.findIndex((entry) => entry.id === item?.id); if (index < 0) return;
    state.viewerItems = items; state.viewerIndex = index; $("naiArtistTestImageModal")?.classList.remove("hidden"); renderImageViewer();
  }

  function renderResults() {
    const target = $("naiArtistTestResults"); if (!target || !state.selectedTest) return;
    target.replaceChildren();
    const allItems = filterNaiArtistTestResults(state.selectedTest.items, "", "all");
    const filteredItems = filterNaiArtistTestResults(state.selectedTest.items, state.resultArtistFilter, state.resultScoreFilter, state.resultPromptIndex);
    const modal = $("naiArtistTestImageModal");
    const currentViewerId = state.viewerItems[state.viewerIndex]?.id;
    state.viewerItems = filteredItems;
    if (modal && !modal.classList.contains("hidden")) { const nextIndex = filteredItems.findIndex((item) => item.id === currentViewerId); if (nextIndex < 0) closeImageViewer(); else { state.viewerIndex = nextIndex; renderImageViewer(); } }
    filteredItems.forEach((item) => {
      const card = document.createElement("button"); card.type = "button"; card.className = "nai-artist-test-image-card"; card.setAttribute("aria-label", `${item.artist_tag} ${item.ordinal}번 이미지 크게 보기`); card.addEventListener("click", () => openImageViewer(item));
      const image = document.createElement("img"); image.src = `/generated/${item.image_path}`; image.alt = `${item.artist_tag} 생성 표본 ${item.ordinal}`;
      const title = document.createElement("strong"); title.textContent = item.artist_tag;
      const score = document.createElement("span"); score.textContent = item.image_score == null ? "이미지 평가 대기" : `이미지 평가 ${item.image_score}점`;
      const artist = state.selectedTest.artists.find((entry) => entry.artist_tag === item.artist_tag);
      const average = document.createElement("small"); average.textContent = artist?.nai_direct_score == null ? "작가 평균 없음" : `작가 NAI 평균 ${Number(artist.nai_direct_score).toFixed(2)}점`;
      card.append(image, title, score, average); target.append(card);
    });
    if (!target.children.length) { const empty = document.createElement("p"); empty.className = "nai-artist-test-empty"; empty.textContent = allItems.length ? "필터 조건에 맞는 이미지가 없습니다." : "아직 생성된 이미지가 없습니다."; target.append(empty); }
  }

  function renderProgress() {
    if (!state.selectedTest) return;
    const current = currentInteractiveItem() || state.selectedTest.items.find((item) => item.status === "pending");
    const generated = state.selectedTest.generated_count ?? state.selectedTest.completed_count ?? 0;
    const total = state.selectedTest.total_count || 0;
    const rated = state.selectedTest.rated_count || 0;
    const phase = isEvaluationPending(state.selectedTest) ? "생성 완료 · 평가 대기" : state.running || state.selectedTest.status === "running" ? "한꺼번에 생성 중" : state.selectedTest.status === "paused" ? "생성 일시정지" : state.selectedTest.status === "cancelled" ? "중단(재개 가능)" : "생성 대기";
    text($("naiArtistTestCurrent"), `${current ? `현재 작가: ${current.artist_tag} · ` : ""}${phase} ${generated}/${total} · 평가 ${rated}/${total} · 남음 ${state.selectedTest.remaining_count || 0}`);
  }

  function renderUsagePreflight() {
    const target = $("naiArtistTestUsagePreflight");
    if (!target) return;
    const estimate = state.usagePreflight;
    if (!estimate) { text(target, "시작/재개 직전에 V5 Usage를 확인합니다."); return; }
    if (!estimate.eligible) { text(target, estimate.message); return; }
    if (estimate.anlasRisk) { text(target, estimate.message); return; }
    if (!estimate.available) { text(target, estimate.message); return; }
    text(target, `V5 Usage 현재 ${estimate.current_percent.toFixed(1)}% (약 ${Math.round(estimate.current_remaining_images)}장) · ${estimate.pending_count}장 생성 추정 후 ${estimate.expected_remaining_percent.toFixed(1)}% (${Math.round(estimate.expected_remaining_images)}장) · 추정치`);
  }

  function renderAppendEstimate() {
    const target = $("naiArtistTestAppendEstimate");
    const button = $("naiArtistTestAppendSubmit");
    if (!target || !state.selectedTest) return;
    const scope = document.querySelector('input[name="naiArtistTestAppendScope"]:checked')?.value || "all";
    const artists = appendTargetArtists(state.selectedTest.items, scope);
    const count = Number($("naiArtistTestAppendCount")?.value || 0);
    text(target, `${scope === "remaining" ? "미생성 항목이 남은" : "전체"} 작가 ${artists.length}명 × ${Number.isFinite(count) ? count : 0}장 = ${artists.length * (Number.isFinite(count) ? count : 0)}장 추가 예정`);
    if (button) button.disabled = !artists.length || !Number.isInteger(count) || count < 1 || count > 100 || state.selectedTest.status === "running" && pendingGenerationCount(state.selectedTest) > 0;
  }

  function closeAppendModal() {
    $("naiArtistTestAppendModal")?.classList.add("hidden");
    hideNaiArtistTestPromptAutocomplete();
  }

  function openAppendModal() {
    if (!state.selectedTest) return;
    renderAppendEstimate();
    $("naiArtistTestAppendModal")?.classList.remove("hidden");
    $("naiArtistTestAppendPrompt")?.focus();
  }

  function readAppendVariant() {
    return { prompt: $("naiArtistTestAppendPrompt")?.value || "", images_per_artist: Number($("naiArtistTestAppendCount")?.value || 0) };
  }

  async function appendPromptVariant() {
    if (!state.selectedTest) return;
    const variant = readAppendVariant();
    const scope = document.querySelector('input[name="naiArtistTestAppendScope"]:checked')?.value || "all";
    if (artistMarkerCount(variant.prompt) !== 1 || !Number.isInteger(variant.images_per_artist) || variant.images_per_artist < 1 || variant.images_per_artist > 100) {
      setStatus("추가 프롬프트는 {{artist}}를 정확히 1개 포함하고 장수는 1~100이어야 합니다.", "error"); return;
    }
    try {
      state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/append`, { method: "POST", body: JSON.stringify({ target_scope: scope, prompt_variants: [variant] }) });
      state.currentItemId = preferredInteractiveItem(state.selectedTest, state.currentItemId)?.id || null;
      state.ratingWaiting = false; state.stopRequested = true; setStatus(`${state.selectedTest.appended_count || 0}개 항목을 추가했습니다. 재개를 눌러 생성하세요.`, "ok");
      closeAppendModal(); renderPromptTabs(); renderResults(); renderCurrentWorkspace(); renderProgress(); renderDetailControls(); renderTests();
      void loadTests();
    } catch (error) { setStatus(error.message, "error"); }
  }

  async function loadUsagePreflight(testOverride = null) {
    const selectedTest = testOverride || state.selectedTest;
    const pending = pendingGenerationCount(selectedTest);
    const config = selectedTest?.config || {};
    if (!isV5Model(config.model)) {
      state.usagePreflight = { eligible: false, anlasRisk: false, message: "V4.5는 Usage 소모 대상이 아닙니다." };
      renderUsagePreflight();
      return state.usagePreflight;
    }
    try {
      const result = await api("/api/settings/novelai/test", { method: "POST" });
      state.usagePreflight = usageEstimateForConfig(result, pending, config);
    } catch (error) {
      state.usagePreflight = usageEstimateForConfig(null, pending, config);
      if (!state.usagePreflight.anlasRisk) state.usagePreflight.message = `Usage를 조회하지 못했습니다. 실행은 계속할 수 있지만 추정하지 않습니다. (${error.message})`;
    }
    renderUsagePreflight();
    return state.usagePreflight;
  }

  function closeStartWarning(result = false) {
    $("naiArtistTestStartModal")?.classList.add("hidden");
    const resolve = state.startWarningResolver;
    state.startWarningResolver = null;
    if (resolve) resolve(Boolean(result));
  }

  function renderStartWarning(plan, estimate, pending, mode = "batch", testOverride = null) {
    const selectedTest = testOverride || state.selectedTest;
    const config = selectedTest?.config || {};
    const delay = Number(selectedTest?.delay_seconds);
    text($("naiArtistTestStartWarningEyebrow"), mode === "single" ? "SINGLE GENERATION" : "BATCH GENERATION");
    text($("naiArtistTestStartWarningTitle"), mode === "single" ? "다음 이미지 1장 생성" : "남은 이미지 한꺼번에 생성");
    text($("naiArtistTestStartWarningDescription"), mode === "single" ? "이번 요청은 이미지 1장만 생성합니다." : "모든 생성이 끝난 뒤 이미지 평가가 열립니다.");
    text($("naiArtistTestStartMetricPending"), `${pending}장`);
    text($("naiArtistTestStartMetricDelay"), Number.isFinite(delay) ? `${delay}초` : "설정값");
    const usage = $("naiArtistTestStartMetricUsage"); const expected = $("naiArtistTestStartMetricExpected"); const after = $("naiArtistTestStartMetricAfter");
    if (estimate?.eligible === false) {
      text(usage, "Usage 비대상"); text(expected, "Usage 비대상"); text(after, "Usage 비대상");
    } else if (estimate?.anlasRisk) {
      text(usage, estimate.available ? `${estimate.current_percent.toFixed(1)}% · 약 ${Math.round(estimate.current_remaining_images)}장` : "확인 불가"); text(expected, "Anlas 위험 · 환산 불가"); text(after, "Anlas 위험 · 환산 불가");
    } else if (!estimate?.available) {
      text(usage, "확인 불가"); text(expected, "추정 불가"); text(after, "추정 불가");
    } else {
      text(usage, `${estimate.current_percent.toFixed(1)}% · 약 ${Math.round(estimate.current_remaining_images)}장`); text(expected, `${estimate.expected_percent.toFixed(1)}% · 약 ${Math.round(pending)}장`); text(after, `${estimate.expected_remaining_percent.toFixed(1)}% · 약 ${Math.round(estimate.expected_remaining_images)}장`);
    }
    text($("naiArtistTestStartWarningAmber"), "Usage와 장수는 현재 구독 응답을 기준으로 한 추정치입니다. 실제 소모와 다를 수 있습니다. 요청 사이에 설정한 딜레이를 적용합니다.");
    const danger = $("naiArtistTestStartWarningDanger"); if (danger) { danger.hidden = !plan.anlasRisk; text(danger, "steps 28 초과 또는 1,048,576px 초과로 Usage와 별개로 Anlas가 사용될 수 있습니다."); }
  }

  function openStartWarning(plan, estimate, pending, mode = "batch", testOverride = null) {
    const modal = $("naiArtistTestStartModal");
    if (!modal) return Promise.resolve(false);
    renderStartWarning(plan, estimate, pending, mode, testOverride);
    modal.classList.remove("hidden");
    $("naiArtistTestStartConfirm")?.focus();
    return new Promise((resolve) => { state.startWarningResolver = resolve; });
  }

  function closeAnlasWarning(result = false) {
    $("naiArtistTestAnlasModal")?.classList.add("hidden");
    const resolve = state.anlasWarningResolver;
    state.anlasWarningResolver = null;
    if (resolve) resolve(Boolean(result));
  }

  function openAnlasWarning(config, pending, mode = "batch") {
    const modal = $("naiArtistTestAnlasModal");
    if (!modal) return Promise.resolve(false);
    text($("naiArtistTestAnlasEyebrow"), "ANLAS WARNING");
    text($("naiArtistTestAnlasTitle"), "Anlas 사용 가능성 최종 확인");
    const reasons = []; if (Number(config.steps) > 28) reasons.push("steps 28 초과"); if (Number(config.width) * Number(config.height) > 1048576) reasons.push("1,048,576px 초과");
    text($("naiArtistTestAnlasReason"), `V5 ${reasons.join(" 및 ")} 설정으로 Anlas가 사용될 수 있습니다. ${mode === "single" ? "1장" : `${pending}장`} 생성 요청을 진행합니다.`);
    modal.classList.remove("hidden");
    $("naiArtistTestAnlasConfirm")?.focus();
    return new Promise((resolve) => { state.anlasWarningResolver = resolve; });
  }

  async function confirmGenerationWithUsage(mode = "batch", testOverride = null) {
    const selectedTest = testOverride || state.selectedTest;
    const pending = pendingGenerationCount(selectedTest);
    const config = selectedTest?.config || {};
    if (mode === "single" && !v5AnlasRisk(config)) return true;
    const estimate = await loadUsagePreflight(selectedTest);
    const plan = startConfirmationPlan(config, estimate, mode === "single" ? 1 : pending);
    if (!plan.requiresFirstConfirm) return true;
    const firstApproved = await openStartWarning(plan, estimate, mode === "single" ? 1 : pending, mode, selectedTest);
    if (!firstApproved) return false;
    if (plan.requiresFinalConfirm && !(await openAnlasWarning(config, mode === "single" ? 1 : pending, mode))) return false;
    return true;
  }

  function renderDetailControls() {
    if (!state.selectedTest) return;
    const controls = generationControlState(state.selectedTest, state.running || state.generationInFlight || state.generationLoopInFlight, state.ratingSubmitting);
    const single = $("naiArtistTestGenerateOne");
    if (single) { single.disabled = controls.singleDisabled; single.classList.add("ghost"); single.classList.toggle("is-active", !controls.singleDisabled); single.title = controls.singleDisabled ? "현재 상태에서는 다음 이미지 생성이 비활성화됩니다." : "다음 이미지 1장 생성"; }
    const start = $("naiArtistTestStart");
    if (start) { start.disabled = controls.batchDisabled; text(start, controls.startLabel); start.title = controls.startLabel; start.classList.toggle("primary", controls.startActive); start.classList.toggle("ghost", !controls.startActive); }
    const pause = $("naiArtistTestPause"); if (pause) { pause.disabled = controls.pauseDisabled; pause.classList.toggle("primary", controls.pauseActive); pause.classList.toggle("ghost", !controls.pauseActive); }
    const cancel = $("naiArtistTestCancel"); if (cancel) { cancel.disabled = controls.cancelDisabled; text(cancel, controls.cancelDisabled ? "중단" : "중단(재개 가능)"); }
    const detailStatus = $("naiArtistTestDetailStatus"); if (detailStatus) { detailStatus.dataset.state = controls.statusState; text(detailStatus, controls.statusLabel); }
    renderAppendEstimate();
  }

  async function selectTest(id) {
    try {
      const sameTest = state.selectedTest?.id === id;
      const previousId = sameTest ? state.currentItemId : null;
      if (!sameTest) {
        state.resultArtistFilter = "";
        state.resultScoreFilter = "all";
        state.resultPromptIndex = "all";
        state.usagePreflight = null;
        closeImageViewer(); closeAppendModal(); closeStartWarning(false);
      }
      state.selectedTest = await api(`/api/nai-artist-tests/${id}`);
      state.currentItemId = preferredInteractiveItem(state.selectedTest, previousId)?.id || null;
      state.nextStatus = ""; state.ratingWaiting = !hasPendingGeneration(state.selectedTest) && Boolean(activeAwaitingItem(state.selectedTest));
      showView("detail");
      $("naiArtistTestDetailTitle").textContent = state.selectedTest.name;
      const artistFilter = $("naiArtistTestResultArtistFilter"); if (artistFilter) artistFilter.value = state.resultArtistFilter;
      const scoreFilter = $("naiArtistTestResultScoreFilter"); if (scoreFilter) scoreFilter.value = state.resultScoreFilter;
      renderPromptTabs(); renderWorkspaceToggle(); renderResults(); renderCurrentWorkspace(); renderProgress(); renderUsagePreflight(); renderDetailControls();
    } catch (error) { setStatus(error.message, "error"); }
  }

  function promptVariantRows() {
    return [...document.querySelectorAll("#naiArtistTestPromptVariants [data-prompt-variant]")];
  }

  function refreshPromptVariantLabels() {
    promptVariantRows().forEach((row, index) => {
      const label = row.querySelector("[data-prompt-input]")?.closest(".field")?.querySelector("span");
      if (label) text(label, `프롬프트 ${index + 1}`);
      const remove = row.querySelector("[data-remove-prompt]"); if (remove) remove.disabled = promptVariantRows().length <= 1;
    });
  }

  function isNaiArtistMarkerCursor(input) {
    const value = String(input?.value || "");
    const cursor = Number(input?.selectionStart);
    if (!Number.isInteger(cursor)) return false;
    let start = value.indexOf(NAI_ARTIST_MARKER);
    while (start >= 0) {
      const end = start + NAI_ARTIST_MARKER.length;
      if (cursor >= start && cursor <= end) return true;
      start = value.indexOf(NAI_ARTIST_MARKER, end);
    }
    return false;
  }

  function hideNaiArtistTestPromptAutocomplete() {
    if (typeof globalThis !== "undefined" && typeof globalThis.promptTagAutocomplete?.hide === "function") {
      globalThis.promptTagAutocomplete?.hide();
    }
  }

  function guardNaiArtistMarkerAutocomplete(event) {
    const input = event.currentTarget;
    if (!isNaiArtistMarkerCursor(input)) return;
    if (event.type === "input") {
      hideNaiArtistTestPromptAutocomplete();
      event.stopImmediatePropagation();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
    const box = input.closest?.(".field")?.querySelector(".prompt-tag-autocomplete");
    if (!box || box.classList.contains("hidden") || !box.querySelector("button")) return;
    hideNaiArtistTestPromptAutocomplete();
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  function bindNaiArtistTestPromptAutocomplete(input) {
    if (!input || typeof globalThis === "undefined") return;
    if (input.dataset && typeof input.addEventListener === "function" && input.dataset.naiArtistMarkerGuardBound !== "true") {
      input.dataset.naiArtistMarkerGuardBound = "true";
      input.addEventListener("input", guardNaiArtistMarkerAutocomplete, true);
      input.addEventListener("keydown", guardNaiArtistMarkerAutocomplete, true);
    }
    if (typeof globalThis.promptTagAutocomplete?.bind === "function") {
      globalThis.promptTagAutocomplete?.bind(input);
    }
  }

  function bindNaiArtistTestPromptInputs() {
    ["naiArtistTestBasePrompt", "naiArtistTestNegativePrompt", "naiArtistTestCharacterPrompts", "naiArtistTestAppendPrompt"]
      .forEach((id) => bindNaiArtistTestPromptAutocomplete($(id)));
    if (typeof document !== "undefined") {
      document.querySelectorAll("#naiArtistTestPromptVariants [data-prompt-input]").forEach(bindNaiArtistTestPromptAutocomplete);
    }
  }

  function addPromptVariantRow() {
    const target = $("naiArtistTestPromptVariants"); if (!target) return null;
    const row = document.createElement("div"); row.className = "nai-artist-test-prompt-row"; row.dataset.promptVariant = "true";
    const promptLabel = document.createElement("label"); promptLabel.className = "field"; const promptName = document.createElement("span"); promptName.textContent = "프롬프트"; const prompt = document.createElement("textarea"); prompt.dataset.promptInput = "true"; prompt.autocomplete = "off"; prompt.placeholder = "{{artist}}, ...";
    const autocomplete = document.createElement("div"); autocomplete.className = "autocomplete prompt-tag-autocomplete hidden";
    promptLabel.append(promptName, prompt, autocomplete);
    const countLabel = document.createElement("label"); countLabel.className = "field"; const countName = document.createElement("span"); countName.textContent = "장수"; const count = document.createElement("input"); count.type = "number"; count.min = "1"; count.max = "100"; count.value = "1"; count.dataset.promptCount = "true"; countLabel.append(countName, count);
    const remove = document.createElement("button"); remove.type = "button"; remove.className = "ghost nai-artist-test-remove-prompt"; remove.dataset.removePrompt = "true"; remove.textContent = "제거"; remove.addEventListener("click", () => { hideNaiArtistTestPromptAutocomplete(); row.remove(); refreshPromptVariantLabels(); });
    row.append(promptLabel, countLabel, remove); target.append(row); bindNaiArtistTestPromptAutocomplete(prompt); refreshPromptVariantLabels(); return row;
  }

  function readPromptVariants() {
    const rows = promptVariantRows();
    return rows.map((row) => ({ prompt: row.querySelector("[data-prompt-input]")?.value || "", images_per_artist: Number(row.querySelector("[data-prompt-count]")?.value || 0) }));
  }

  function readResolution() {
    const value = $("naiArtistTestResolution")?.value || "832x1216";
    if (value === "custom") return { width: Number($("naiArtistTestWidth")?.value), height: Number($("naiArtistTestHeight")?.value) };
    const [width, height] = value.split("x").map(Number); return { width, height };
  }

  function readConfig() {
    const seedValue = $("naiArtistTestSeed")?.value.trim(); const resolution = readResolution();
    const variants = readPromptVariants(); const prompt = variants[0]?.prompt || $("naiArtistTestBasePrompt")?.value || "";
    const config = {
      base_prompt: prompt,
      quality_prompt: "", original_quality_prompt: "",
      prompt_variants: variants,
      negative_prompt: $("naiArtistTestNegativePrompt")?.value || "",
      character_prompts: ($("naiArtistTestCharacterPrompts")?.value || "").split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
      model: $("naiArtistTestModel")?.value, ...resolution, sampler: $("naiArtistTestSampler")?.value || "k_euler_ancestral", noise_schedule: $("naiArtistTestScheduler")?.value || "native",
      steps: Number($("naiArtistTestSteps")?.value), scale: Number($("naiArtistTestScale")?.value), cfg_rescale: Number($("naiArtistTestCfgRescale")?.value),
      variety_plus: Boolean($("naiArtistTestVariety")?.checked), quality_toggle: Boolean($("naiArtistTestQualityToggle")?.checked), uc_preset: Number($("naiArtistTestUcPreset")?.value || 0), complexity: $("naiArtistTestComplexity")?.value || "",
    };
    if (seedValue) config.seed = Number(seedValue); return config;
  }

  async function createTest() {
    try {
      const delay = Number($("naiArtistTestDelay")?.value); if (delay < 1 && !window.confirm("딜레이가 1초 미만입니다. 제한/밴 위험이 커질 수 있습니다. 계속할까요?")) return;
      const artists = selectedArtists(); if (!artists.length) throw new Error("대상 작가를 하나 이상 선택하세요.");
      const variants = readPromptVariants(); if (!variants.length || variants.some((variant) => artistMarkerCount(variant.prompt) !== 1 || !Number.isInteger(variant.images_per_artist) || variant.images_per_artist < 1 || variant.images_per_artist > 100)) throw new Error("각 프롬프트는 {{artist}}를 정확히 1개 포함하고 장수는 1~100이어야 합니다.");
      const config = readConfig();
      const test = await api("/api/nai-artist-tests", { method: "POST", body: JSON.stringify({ name: $("naiArtistTestName")?.value, config, prompt_variants: variants, artists, images_per_artist: variants[0].images_per_artist, delay_seconds: delay }) });
      state.selectedTest = test; setStatus("테스트 묶음을 저장했습니다.", "ok"); await loadTests(); await selectTest(test.id);
    } catch (error) { setStatus(error.message, "error"); }
  }

  async function generateNextOnce() {
    if (!state.selectedTest || state.generationInFlight || state.stopRequested) return null;
    state.generationInFlight = true; state.nextStatus = "다음 이미지 생성 중..."; renderCurrentWorkspace();
    try {
      const result = await api(`/api/nai-artist-tests/${state.selectedTest.id}/generate-next`, { method: "POST" });
      state.selectedTest = result.test || await api(`/api/nai-artist-tests/${state.selectedTest.id}`);
      const awaiting = activeAwaitingItem(state.selectedTest);
      state.currentItemId = result.item_id || (result.waiting_for_rating ? awaiting?.id : currentInteractiveItem()?.id) || null;
      state.ratingWaiting = Boolean(result.waiting_for_rating) || generationEvaluationReady(state.selectedTest);
      state.nextStatus = result.waiting_for_rating ? "전체 이미지 생성이 끝났습니다. 점수를 선택하세요." : "";
      renderResults(); renderCurrentWorkspace(); renderProgress(); renderDetailControls(); renderTests();
      return result;
    } finally { state.generationInFlight = false; renderDetailControls(); }
  }

  async function waitForGenerationDelay(item) {
    while (true) {
      if (state.stopRequested || state.selectedTest?.status !== "running") return false;
      const remaining = remainingDelayMs(state.selectedTest.delay_seconds, item.generation_requested_at, Date.now());
      if (remaining <= 0) break;
      state.nextStatus = `다음 이미지 생성까지 ${Math.ceil(remaining / 1000)}초`; renderCurrentWorkspace(); renderProgress();
      await new Promise((resolve) => setTimeout(resolve, Math.min(remaining, 250)));
    }
    return !state.stopRequested && state.selectedTest?.status === "running";
  }

  async function runSingleGeneration() {
    if (!state.selectedTest || state.singleGenerationInFlight || state.generationInFlight || state.generationLoopInFlight) return;
    if (!hasPendingGeneration(state.selectedTest)) {
      state.ratingWaiting = Boolean(activeAwaitingItem(state.selectedTest));
      state.currentItemId = activeAwaitingItem(state.selectedTest)?.id || state.currentItemId;
      renderCurrentWorkspace(); renderProgress(); renderDetailControls();
      return;
    }
    if (!(await confirmGenerationWithUsage("single"))) return;
    const previousLastGenerated = state.selectedTest.items.filter((item) => item.status === "complete").slice(-1)[0] || null;
    state.singleGenerationInFlight = true; state.running = true; state.stopRequested = false; renderDetailControls();
    try {
      state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/start`, { method: "POST" });
      if (state.stopRequested || state.selectedTest.status !== "running") return;
      if (previousLastGenerated && !(await waitForGenerationDelay(previousLastGenerated))) return;
      if (state.stopRequested) return;
      const result = await generateNextOnce();
      if (!result || state.stopRequested) return;
      if (generationEvaluationReady(state.selectedTest) || !hasPendingGeneration(state.selectedTest)) {
        const awaiting = activeAwaitingItem(state.selectedTest);
        state.currentItemId = awaiting?.id || result.item_id || state.currentItemId;
        state.ratingWaiting = Boolean(awaiting);
        state.nextStatus = awaiting ? "모든 이미지 생성이 끝났습니다. 점수를 선택하세요." : "";
      } else if (state.selectedTest.status === "running" && hasPendingGeneration(state.selectedTest)) {
        state.stopRequested = true;
        state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/pause`, { method: "POST" });
        state.nextStatus = "1장 생성이 끝났습니다. 다음 생성을 계속하려면 재개하세요.";
      }
      renderResults(); renderCurrentWorkspace(); renderProgress(); renderDetailControls(); renderTests();
    } catch (error) { setStatus(error.message, "error"); }
    finally {
      state.singleGenerationInFlight = false; state.running = false;
      renderCurrentWorkspace(); renderProgress(); renderDetailControls();
      await loadTests();
    }
  }

  async function runGenerationLoop() {
    if (state.generationLoopInFlight || !state.selectedTest) return;
    state.generationLoopInFlight = true; state.ratingWaiting = false;
    try {
      let lastGenerated = state.selectedTest.items.filter((item) => item.status === "complete").slice(-1)[0] || null;
      while (!state.stopRequested && state.selectedTest?.status === "running") {
        if (lastGenerated && !(await waitForGenerationDelay(lastGenerated))) break;
        state.nextStatus = "";
        const result = await generateNextOnce();
        if (!result || state.stopRequested || result.waiting_for_rating || result.done || state.selectedTest?.status === "completed") break;
        const awaiting = activeAwaitingItem(state.selectedTest);
        if (generationEvaluationReady(state.selectedTest)) {
          state.currentItemId = awaiting.id;
          state.ratingWaiting = true;
          state.nextStatus = "전체 이미지 생성이 끝났습니다. 점수를 선택하세요.";
          renderCurrentWorkspace(); renderProgress(); renderDetailControls();
          break;
        }
        lastGenerated = state.selectedTest.items.find((item) => item.id === result.item_id) || state.selectedTest.items.filter((item) => item.status === "complete").slice(-1)[0];
      }
    } finally {
      state.generationLoopInFlight = false;
      renderCurrentWorkspace(); renderProgress(); renderDetailControls();
    }
  }

  async function rateItem(item, score) {
    if (state.ratingSubmitting || !state.selectedTest || !item || item.image_score != null) return;
    state.ratingSubmitting = true; renderCurrentWorkspace();
    try {
      state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/items/${item.id}/rating`, { method: "POST", body: JSON.stringify({ score }) });
      const awaiting = activeAwaitingItem(state.selectedTest);
      state.currentItemId = awaiting?.id || item.id; state.ratingWaiting = Boolean(awaiting);
      state.nextStatus = state.selectedTest.status === "completed" ? "테스트가 완료되었습니다." : "";
      renderResults(); renderProgress(); renderCurrentWorkspace();
    } catch (error) { setStatus(error.message, "error"); }
    finally { state.ratingSubmitting = false; renderCurrentWorkspace(); renderProgress(); renderDetailControls(); void loadTests(); }
  }

  async function runTest() {
    if (!state.selectedTest || state.running || state.generationInFlight || state.generationLoopInFlight) return;
    const awaiting = activeAwaitingItem(state.selectedTest);
    if (!hasPendingGeneration(state.selectedTest) && awaiting) {
      state.currentItemId = awaiting.id; state.ratingWaiting = true; state.nextStatus = "전체 이미지 생성이 끝났습니다. 점수를 선택하세요.";
      renderCurrentWorkspace(); renderProgress(); renderDetailControls(); return;
    }
    if (!hasPendingGeneration(state.selectedTest) || !(await confirmGenerationWithUsage("batch"))) return;
    state.running = true; state.stopRequested = false; renderDetailControls();
    try {
      state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/start`, { method: "POST" });
      const startedAwaiting = activeAwaitingItem(state.selectedTest);
      if (!hasPendingGeneration(state.selectedTest) && startedAwaiting) { state.currentItemId = startedAwaiting.id; state.ratingWaiting = true; renderCurrentWorkspace(); renderProgress(); renderDetailControls(); }
      else if (state.selectedTest.status !== "completed") await runGenerationLoop();
    } catch (error) { setStatus(error.message, "error"); }
    state.running = false; renderCurrentWorkspace(); renderProgress(); renderDetailControls(); await loadTests();
  }

  async function pauseTest() { state.stopRequested = true; if (state.selectedTest) { try { state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/pause`, { method: "POST" }); state.ratingWaiting = !hasPendingGeneration(state.selectedTest) && Boolean(activeAwaitingItem(state.selectedTest)); state.nextStatus = ""; renderResults(); renderCurrentWorkspace(); renderProgress(); renderDetailControls(); } catch (error) { setStatus(error.message, "error"); } } }
  async function cancelTest() { state.stopRequested = true; if (state.selectedTest) { try { state.selectedTest = await api(`/api/nai-artist-tests/${state.selectedTest.id}/cancel`, { method: "POST" }); state.ratingWaiting = !hasPendingGeneration(state.selectedTest) && Boolean(activeAwaitingItem(state.selectedTest)); state.nextStatus = ""; renderResults(); renderCurrentWorkspace(); renderProgress(); renderDetailControls(); } catch (error) { setStatus(error.message, "error"); } } }

  if (typeof document !== "undefined" && !(typeof module !== "undefined" && module.exports)) {
    $("naiArtistTestAdd")?.addEventListener("click", () => { state.selectedTest = null; state.selectedArtists = []; showView("editor"); renderArtists(); refreshPromptVariantLabels(); void loadArtists(); });
    $("naiArtistTestBackToList")?.addEventListener("click", () => showView("list"));
    $("naiArtistTestBackFromDetail")?.addEventListener("click", () => showView("list"));
    $("naiArtistTestTestMode")?.addEventListener("click", () => { closeImageViewer(); state.listMode = "tests"; state.selectedHistoryArtist = null; renderListMode(); renderTests(); });
    $("naiArtistTestArtistMode")?.addEventListener("click", () => { closeImageViewer(); state.listMode = "artists"; state.selectedHistoryArtist = null; renderListMode(); void loadArtistHistory(); });
    $("naiArtistTestBackFromArtistDetail")?.addEventListener("click", () => { state.selectedHistoryArtist = null; renderListMode(); renderArtistSummaries(); });
    $("naiArtistTestHistoryArtistSearch")?.addEventListener("input", () => { clearTimeout(state.historySearchTimer); state.historySearchTimer = setTimeout(loadArtistHistory, 250); });
    $("naiArtistTestAddPrompt")?.addEventListener("click", addPromptVariantRow);
    $("naiArtistTestPromptVariants")?.addEventListener("click", (event) => { const remove = event.target.closest("[data-remove-prompt]"); if (!remove || remove.disabled) return; hideNaiArtistTestPromptAutocomplete(); remove.closest("[data-prompt-variant]")?.remove(); refreshPromptVariantLabels(); });
    $("naiArtistTestCreate")?.addEventListener("click", createTest); $("naiArtistTestRefreshTests")?.addEventListener("click", loadTests);
    $("naiArtistTestAppendOpen")?.addEventListener("click", openAppendModal);
    $("naiArtistTestAppendModalClose")?.addEventListener("click", closeAppendModal);
    $("naiArtistTestAppendCancel")?.addEventListener("click", closeAppendModal);
    document.querySelector("[data-nai-artist-test-append-close]")?.addEventListener("click", closeAppendModal);
    $("naiArtistTestAppendSubmit")?.addEventListener("click", appendPromptVariant);
    $("naiArtistTestAppendCount")?.addEventListener("input", renderAppendEstimate);
    document.querySelectorAll('input[name="naiArtistTestAppendScope"]').forEach((input) => input.addEventListener("change", renderAppendEstimate));
    $("naiArtistTestSelectAll")?.addEventListener("click", () => { state.selectedArtists = mergeArtistSelections(state.selectedArtists, state.artists); renderArtists(); });
    $("naiArtistTestClearSelection")?.addEventListener("click", () => { state.selectedArtists = []; renderArtists(); });
    $("naiArtistTestPreviewPrevious")?.addEventListener("click", () => stepPreview(-1)); $("naiArtistTestPreviewNext")?.addEventListener("click", () => stepPreview(1));
    $("naiArtistTestSettingsToggle")?.addEventListener("click", () => {
      const body = $("naiArtistTestSettingsBody"); const settings = $("naiArtistTestSettings"); const button = $("naiArtistTestSettingsToggle");
      const expanded = settingsExpanded(!(body?.hidden));
      if (body) body.hidden = !expanded; settings?.classList.toggle("is-collapsed", !expanded); settings?.parentElement?.classList.toggle("settings-collapsed", !expanded); button?.setAttribute("aria-expanded", String(expanded)); button?.setAttribute("aria-label", expanded ? "생성 설정 접기" : "생성 설정 펼치기"); if (button) button.title = expanded ? "생성 설정 접기" : "생성 설정 펼치기"; text(button, expanded ? "설정 접기" : "설정 펼치기");
    });
    $("naiArtistTestWorkspaceToggle")?.addEventListener("click", () => { state.workspaceExpanded = !state.workspaceExpanded; renderWorkspaceToggle(); });
    $("naiArtistTestResultArtistFilter")?.addEventListener("input", (event) => { state.resultArtistFilter = event.target.value; renderResults(); });
    $("naiArtistTestResultScoreFilter")?.addEventListener("change", (event) => { state.resultScoreFilter = event.target.value; renderResults(); });
    $("naiArtistTestImageModalClose")?.addEventListener("click", closeImageViewer);
    document.querySelector("[data-nai-artist-test-modal-close]")?.addEventListener("click", closeImageViewer);
    $("naiArtistTestImageModalPrevious")?.addEventListener("click", () => { state.viewerIndex = cycleResultViewerIndex(state.viewerIndex, state.viewerItems.length, -1); renderImageViewer(); });
    $("naiArtistTestImageModalNext")?.addEventListener("click", () => { state.viewerIndex = cycleResultViewerIndex(state.viewerIndex, state.viewerItems.length, 1); renderImageViewer(); });
    $("naiArtistTestStartConfirm")?.addEventListener("click", () => closeStartWarning(true));
    $("naiArtistTestStartCancel")?.addEventListener("click", () => closeStartWarning(false));
    $("naiArtistTestStartCancelSecondary")?.addEventListener("click", () => closeStartWarning(false));
    document.querySelector("[data-nai-artist-test-start-close]")?.addEventListener("click", () => closeStartWarning(false));
    $("naiArtistTestAnlasConfirm")?.addEventListener("click", () => closeAnlasWarning(true));
    $("naiArtistTestAnlasCancel")?.addEventListener("click", () => closeAnlasWarning(false));
    $("naiArtistTestAnlasCancelSecondary")?.addEventListener("click", () => closeAnlasWarning(false));
    document.querySelector("[data-nai-artist-test-anlas-close]")?.addEventListener("click", () => closeAnlasWarning(false));
    $("naiArtistTestDeleteConfirm")?.addEventListener("click", () => closeDeleteWarning(true));
    $("naiArtistTestDeleteCancel")?.addEventListener("click", () => closeDeleteWarning(false));
    $("naiArtistTestDeleteCancelSecondary")?.addEventListener("click", () => closeDeleteWarning(false));
    document.querySelector("[data-nai-artist-test-delete-close]")?.addEventListener("click", () => closeDeleteWarning(false));
    document.addEventListener("keydown", (event) => {
      const imageModal = $("naiArtistTestImageModal");
      const startModal = $("naiArtistTestStartModal");
      const anlasModal = $("naiArtistTestAnlasModal");
      const appendModal = $("naiArtistTestAppendModal");
      const deleteModal = $("naiArtistTestDeleteModal");
      if (event.key === "Escape") {
        if (startModal && !startModal.classList.contains("hidden")) { event.preventDefault(); closeStartWarning(false); }
        else if (anlasModal && !anlasModal.classList.contains("hidden")) { event.preventDefault(); closeAnlasWarning(false); }
        else if (appendModal && !appendModal.classList.contains("hidden")) { event.preventDefault(); closeAppendModal(); }
        else if (deleteModal && !deleteModal.classList.contains("hidden")) { event.preventDefault(); closeDeleteWarning(false); }
        else if (imageModal && !imageModal.classList.contains("hidden")) { event.preventDefault(); closeImageViewer(); }
      } else if (imageModal && !imageModal.classList.contains("hidden") && event.key === "ArrowLeft") { event.preventDefault(); state.viewerIndex = cycleResultViewerIndex(state.viewerIndex, state.viewerItems.length, -1); renderImageViewer(); }
      else if (imageModal && !imageModal.classList.contains("hidden") && event.key === "ArrowRight") { event.preventDefault(); state.viewerIndex = cycleResultViewerIndex(state.viewerIndex, state.viewerItems.length, 1); renderImageViewer(); }
    });
    $("naiArtistTestScoreMin")?.addEventListener("change", loadArtists); $("naiArtistTestScoreMax")?.addEventListener("change", loadArtists); $("naiArtistTestArtistSort")?.addEventListener("change", loadArtists); $("naiArtistTestArtistSearch")?.addEventListener("input", () => { clearTimeout(state.artistSearchTimer); state.artistSearchTimer = setTimeout(loadArtists, 250); });
    $("naiArtistTestGenerateOne")?.addEventListener("click", runSingleGeneration); $("naiArtistTestStart")?.addEventListener("click", runTest); $("naiArtistTestPause")?.addEventListener("click", pauseTest); $("naiArtistTestCancel")?.addEventListener("click", cancelTest);
    $("naiArtistTestDeleteDetail")?.addEventListener("click", () => { if (state.selectedTest) void deleteTestById(state.selectedTest.id); });
    $("naiArtistTestResolution")?.addEventListener("change", (event) => $("naiArtistTestCustomResolution")?.classList.toggle("hidden", event.target.value !== "custom"));
    initializeHistoryCardSize(); renderListMode(); renderWorkspaceToggle(); renderPreview(); refreshPromptVariantLabels(); bindNaiArtistTestPromptInputs(); renderUsagePreflight(); loadArtists(); loadTests();
  }

  if (typeof globalThis !== "undefined") {
    globalThis.naiArtistTestGenerationPreflight = (test, mode = "single") => confirmGenerationWithUsage(mode, test || null);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { readResolution, artistMarkerCount, normalizeDelay, normalizeHistoryCardSize, sortArtistCandidates, artistSelectionPayload, toggleArtistSelection, mergeArtistSelections, isMarqueeDrag, marqueeAutoScrollDelta, marqueeSelectedArtistKeys, uniquePreviewImages, cyclePreviewIndex, cycleResultViewerIndex, filterNaiArtistTestResults, promptVariantTabs, promptVariantTotal, hasPendingGeneration, generationEvaluationReady, isEvaluationPending, settingsExpanded, activeAwaitingItem, preferredInteractiveItem, remainingDelayMs, averageScores, FULL_CAPACITY_IMAGES, isV5Model, pendingGenerationCount, appendTargetArtists, estimateV5Usage, usageEstimateForConfig, v5AnlasRisk, generationControlState, startConfirmationPlan, startWarningSummary, naiArtistTestViews, deleteConfirmationMessage, confirmGenerationWithUsage, bindNaiArtistTestPromptAutocomplete, isNaiArtistMarkerCursor };
})();
