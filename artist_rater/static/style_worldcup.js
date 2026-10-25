(function () {
  "use strict";

  const TAG_IDS = ["worldcupIncludeTags", "worldcupExcludeTags"];
  const FILTER_IDS = [...TAG_IDS, "worldcupRecommendation"];
  const PICKER_SOURCES = { worldcupPickerAllSource: "all", worldcupPickerSharedSource: "shared", worldcupPickerConfirmedSource: "confirmed" };
  const MODEL_LABELS = { all: "전체 모델", v5: "V5 전체", "nai-diffusion-5-full-medium": "V5 Medium", "nai-diffusion-5-full": "V5 Full", "nai-diffusion-5-curated": "V5 Curated", "v4.5": "V4.5 전체", "nai-diffusion-4-5-full": "V4.5 Full", "nai-diffusion-4-5-curated": "V4.5 Curated", unknown: "모델 미상" };
  function splitConditions(value) {
    return [...new Set(String(value || "").split(/[,\n\r]+/).map((part) => part.trim()).filter(Boolean))];
  }
  function safeSourceUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) { return ""; }
  }
  function safeLocalImageUrl(value) {
    const url = String(value || "");
    return /^\/(?!\/)/.test(url) && !/[\\\x00-\x20]/.test(url) ? url : "";
  }
  function roundLabel(size) { return Number(size) === 2 ? "결승" : Number(size) + "강"; }
  function availableSizes(count) {
    const sizes = [];
    if (!Number.isSafeInteger(count)) return sizes;
    for (let size = 2; size <= count; size *= 2) sizes.push(size);
    return sizes;
  }
  function canStart(count, size, busy) {
    return !busy && Number.isSafeInteger(count) && count >= 2 && (size === "all" || availableSizes(count).includes(Number(size)));
  }
  function previewParticipants(cup) {
    const participants = cup.status === "completed" && cup.winner ? [cup.winner, ...(cup.preview_participants || [])] : (cup.preview_participants || []);
    const seen = new Set();
    return participants.filter((participant) => {
      if (!participant || seen.has(participant.ordinal)) return false;
      seen.add(participant.ordinal);
      return true;
    }).slice(0, 4);
  }

  function createController(doc, fetcher) {
    const $ = (id) => doc.getElementById(id);
    const state = { view: "list", busy: false, list: [], detail: null, count: null, counts: null, filters: null, filterKey: null, previewVersion: 0, selection: new Map() };
    const picker = { open: false, busy: false, ready: false, token: 0, groupSelection: new Map(), filters: null, filterKey: null, source: "all", mode: "all", page: 1, total: 0, items: [], cards: new Map(), drag: null, suppressClick: false };
    state.picker = picker;
    const candidateDetail = { token: 0, open: false, index: 0, item: null, data: null, images: [], scroll: null, returnFocus: null };
    state.candidateDetail = candidateDetail;
    const PICKER_PAGE_SIZE = 60;
    const text = (tag, value, className) => {
      const node = doc.createElement(tag);
      if (className) node.className = className;
      node.textContent = value == null ? "" : String(value);
      return node;
    };
    function status(message, kind) {
      $("worldcupStatus").textContent = message || "";
      $("worldcupStatus").dataset.state = kind || "";
      ["worldcupCreateStatus", "worldcupCreateStatusBottom"].forEach((id) => { $(id).textContent = message || ""; $(id).dataset.state = kind || ""; });
    }
    function readFilters() {
      const recommendation = $("worldcupRecommendation").value.trim();
      return {
        sources: ["shared", "confirmed"],
        model: $("worldcupModel").value || "all",
        include_tags: splitConditions($("worldcupIncludeTags").value),
        exclude_tags: splitConditions($("worldcupExcludeTags").value),
        exclude_recommendation_lte: recommendation === "" ? null : Number(recommendation),
      };
    }
    function validFilters() {
      const filters = readFilters();
      const recommendation = filters.exclude_recommendation_lte;
      if (recommendation !== null && (!Number.isSafeInteger(recommendation) || recommendation < 0)) {
        (picker.open ? pickerStatus : status)("추천수는 0 이상의 정수로 입력해 주세요.", "error");
        $("worldcupRecommendation").focus();
        return null;
      }
      return filters;
    }
    function syncControls() {
      $("style-worldcup-tab").setAttribute("aria-busy", String(state.busy));
      $("style-worldcup-tab").querySelectorAll("button, input, select, textarea").forEach((node) => { node.disabled = state.busy; });
      syncPickerControls();
    }
    function renderSizeHelp() {
      const all = $("worldcupSize").value === "all";
      const size = all ? state.count : Number($("worldcupSize").value);
      let help = all ? "자동 선택하면 공유·확정 전체 후보 중 조건에 맞는 그림체 " + size + "개를 모두 선택합니다." : "자동 선택하면 공유·확정 전체 후보 중 조건에 맞는 그림체 " + size + "개를 무작위로 뽑습니다.";
      if (size >= 2 && !availableSizes(size).includes(size)) {
        const byes = 2 ** Math.ceil(Math.log2(size)) - size;
        help += " 첫 라운드에서 " + byes + "개는 부전승으로 다음 라운드에 진출합니다.";
      }
      $("worldcupSizeHelp").textContent = state.count >= 2 ? help : "";
    }
    function renderSizes() {
      const select = $("worldcupSize"); select.replaceChildren();
      if (state.count >= 2) {
        const all = text("option", "전부 참가 (" + state.count + "개)"); all.value = "all"; select.append(all);
        availableSizes(state.count).forEach((size) => { const option = text("option", size + "강 (" + size + "개)"); option.value = String(size); select.append(option); });
        select.value = "all";
      } else {
        const option = text("option", state.count === null ? "필터 적용 후 선택" : "후보 2개부터 가능");
        option.value = ""; select.append(option); select.value = "";
      }
    }
    function renderCount() {
      const count = $("worldcupCandidateCount");
      const breakdown = state.counts && Number.isInteger(state.counts.shared) && Number.isInteger(state.counts.confirmed)
        ? " (공유 " + state.counts.shared + "개 · 확정 " + state.counts.confirmed + "개)" : "";
      const countText = "조건에 맞는 총 " + state.count + "개" + breakdown;
      count.dataset.state = state.count !== null && state.count < 2 ? "insufficient" : "";
      count.textContent = state.count === null ? "후보 개수는 필터 적용 후 표시됩니다." : countText;
      renderSizeHelp();
      renderPickerSelection();
    }
    function invalidateCount() {
      globalThis.promptTagAutocomplete?.hide?.();
      state.previewVersion += 1;
      if (picker.open) pickerStatus("필터 적용을 누르면 목록이 바뀝니다. 선택한 그림체는 유지됩니다.");
    }
    function showView(view, focusId) {
      globalThis.promptTagAutocomplete?.hide?.();
      state.view = view;
      $("worldcupHead").hidden = view === "picker";
      $("worldcupStatus").hidden = view === "picker";
      $("worldcupList").hidden = view !== "list";
      $("worldcupDetail").hidden = view !== "detail";
      $("worldcupPicker").hidden = view !== "picker";
      $("worldcupCandidateDetail").hidden = view !== "picker" || !candidateDetail.open;
      $("worldcupGalleryLayout").dataset.detailOpen = String(view === "picker" && candidateDetail.open);
      if (focusId) $(focusId).focus();
    }
    function scrollOwner() { return doc.scrollingElement || $("style-worldcup-tab"); }
    function pageScroll() { return { tab: $("style-worldcup-tab").scrollTop, page: scrollOwner().scrollTop }; }
    function restoreScroll(value = { tab: 0, page: 0 }) { $("style-worldcup-tab").scrollTop = value.tab; scrollOwner().scrollTop = value.page; }
    async function request(path, payload) {
      const options = payload === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) };
      const response = await fetcher("/api/style-worldcups" + path, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(body.error || "요청에 실패했습니다. 다시 시도해 주세요.");
        error.status = response.status;
        throw error;
      }
      return body;
    }
    async function run(message, action) {
      if (state.busy) return;
      globalThis.promptTagAutocomplete?.hide?.();
      state.busy = true;
      status(message);
      syncControls();
      try { await action(); }
      catch (error) { status(error.message || "요청에 실패했습니다. 다시 시도해 주세요.", "error"); }
      finally { state.busy = false; syncControls(); }
    }
    function pickerStatus(message, kind) {
      $("worldcupPickerStatus").textContent = message || "";
      $("worldcupPickerStatus").dataset.state = kind || "";
    }
    function syncPickerControls() {
      if (!picker.open) return;
      const blocked = picker.busy || state.busy;
      $("worldcupPicker").setAttribute("aria-busy", String(blocked));
      $("worldcupPicker").querySelectorAll("button, select, input, textarea").forEach((node) => { node.disabled = blocked; });
      $("worldcupPickerCardSize").disabled = false;
      $("worldcupPickerClose").disabled = state.busy;
      $("worldcupPickerCloseBottom").disabled = state.busy;
      $("worldcupStart").disabled = blocked || state.selection.size < 2;
      $("worldcupStartBottom").disabled = $("worldcupStart").disabled;
      $("worldcupSize").disabled = blocked || state.count === null || state.count < 2;
      $("worldcupAutoSelect").disabled = !canStart(state.count, $("worldcupSize").value, blocked);
      $("worldcupPickerFilterApply").disabled = picker.busy || state.busy;
      Object.entries(PICKER_SOURCES).forEach(([id, source]) => { $(id).setAttribute("aria-pressed", String(picker.source === source)); $(id).disabled = blocked || !picker.filters; });
      $("worldcupPickerMode").disabled = blocked || !picker.filters;
      $("worldcupPickerSort").disabled = blocked || !picker.filters;
      $("worldcupPickerPrev").disabled = blocked || picker.page <= 1;
      $("worldcupPickerNext").disabled = blocked || picker.page >= Math.max(1, Math.ceil(picker.total / PICKER_PAGE_SIZE));
      picker.cards.forEach(({ card, detail, item }) => {
        card.disabled = blocked || (item.available === false && !selectedKey(item));
        detail.disabled = blocked;
      });
      syncCandidateControls();
    }
    function groupKey(item) { return item.group_key || item.key; }
    function selectedKey(item) { return picker.groupSelection.get(groupKey(item)); }
    function addPickerSelection(item) {
      if (selectedKey(item)) return;
      state.selection.set(item.key, item); picker.groupSelection.set(groupKey(item), item.key);
    }
    function renderPickerSelection() {
      $("worldcupPickerSelectionCount").textContent = "선택 " + state.selection.size + "개" + (state.selection.size < 2 ? " · 시작은 2개부터" : "");
      ["worldcupStart", "worldcupStartBottom"].forEach((id) => { $(id).textContent = "월드컵 시작 (" + state.selection.size + "개)"; });
      syncPickerControls();
    }
    function updatePickerCard(entry) {
      const selected = Boolean(selectedKey(entry.item));
      entry.card.setAttribute("aria-pressed", String(selected));
      entry.card.setAttribute("aria-label", (entry.item.title || "제목 없는 그림체") + " · " + (selected ? "선택됨, 눌러서 제외" : "눌러서 선택"));
      entry.label.textContent = selected ? "✓ 선택됨" : "+ 선택";
    }
    function setPickerSelection(key, selected) {
      const entry = picker.cards.get(key);
      if (!entry || (selected && entry.item.available === false)) return;
      const existing = selectedKey(entry.item);
      if (selected && !existing) addPickerSelection(entry.item);
      else if (!selected && existing) { state.selection.delete(existing); picker.groupSelection.delete(groupKey(entry.item)); }
      updatePickerCard(entry);
    }
    function togglePickerCard(key) {
      const entry = picker.cards.get(key);
      if (!entry || picker.busy || !picker.open || picker.drag?.active) return;
      setPickerSelection(key, !selectedKey(entry.item));
      if (picker.mode === "selected") renderPicker(key);
      else { renderPickerSelection(); entry.card.focus({ preventScroll: true }); }
    }
    function renderPicker(focusKey) {
      const grid = $("worldcupPickerGrid");
      const previousCards = picker.cards; picker.cards = new Map();
      let items = picker.items;
      if (picker.mode === "selected") {
        const selected = [...state.selection.values()].filter((item) => picker.source === "all" || (item.image_source || "shared") === picker.source);
        const sort = $("worldcupPickerSort").value;
        if (sort === "recommendation_desc" || sort === "recommendation_asc") selected.sort((left, right) => {
          const a = left.recommendation_count; const b = right.recommendation_count;
          if ((a == null) !== (b == null)) return a == null ? 1 : -1;
          return (a == null ? 0 : (sort === "recommendation_desc" ? b - a : a - b)) || groupKey(left).localeCompare(groupKey(right));
        });
        picker.total = selected.length;
        picker.page = Math.min(picker.page, Math.max(1, Math.ceil(picker.total / PICKER_PAGE_SIZE)));
        items = selected.slice((picker.page - 1) * PICKER_PAGE_SIZE, picker.page * PICKER_PAGE_SIZE);
      }
      const cards = [];
      if (!items.length) cards.push(text("p", !picker.filters ? "조건을 설정하고 필터 적용을 눌러 주세요." : picker.mode === "selected" ? "선택한 그림이 없습니다. 전체 후보에서 추가해 주세요." : "표시할 후보가 없습니다.", "worldcup-help"));
      items.forEach((item) => {
        let entry = previousCards.get(item.key);
        if (!entry || entry.item !== item) {
          const card = doc.createElement("button"); card.type = "button"; card.className = "worldcup-picker-card";
          card.dataset.candidateKey = item.key;
          card.dataset.unavailable = String(item.available === false);
          card.title = item.title || "제목 없는 그림체";
          const label = text("span", "", "worldcup-picker-card-state");
          const model = item.model_label || "모델 미상";
          const metadata = text("span", "", "worldcup-picker-card-meta");
          const recommendation = item.recommendation_count == null ? "추천 —" : "추천 " + item.recommendation_count;
          [item.image_source === "confirmed" ? "확정" : "공유", model, recommendation].forEach((value, index) => {
            const chip = text("span", value, "worldcup-picker-chip");
            chip.title = index === 2 && item.recommendation_count == null ? "추천수 없음/미상" : value;
            metadata.append(chip);
          });
          card.append(imageFor(item, true, true), text("strong", item.title || "제목 없는 그림체", "worldcup-picker-card-title"), metadata, label);
          card.addEventListener("click", (event) => {
            if (picker.suppressClick && event.detail !== 0) { picker.suppressClick = false; event.preventDefault(); return; }
            togglePickerCard(item.key);
          });
          const wrapper = doc.createElement("article"); wrapper.className = "worldcup-picker-item";
          const detail = text("button", "상세 보기", "worldcup-picker-detail"); detail.type = "button";
          detail.setAttribute("aria-label", (item.title || "그림체") + " 상세 보기");
          detail.addEventListener("click", () => openCandidateDetail(item, detail));
          wrapper.append(card, detail);
          entry = { card, label, item, wrapper, detail };
        }
        picker.cards.set(item.key, entry); updatePickerCard(entry); cards.push(entry.wrapper);
      });
      grid.replaceChildren(...cards, $("worldcupPickerMarquee"));
      $("worldcupPickerVisibleCount").textContent = picker.filters ? "현재 목록 " + picker.total + "개 · 이번 페이지 " + items.length + "개" : "필터 적용 전";
      $("worldcupPickerPage").textContent = picker.filters ? picker.page + " / " + Math.max(1, Math.ceil(picker.total / PICKER_PAGE_SIZE)) + " 페이지" : "";
      renderPickerSelection();
      if (focusKey) {
        const cards = [...picker.cards.values()].map((entry) => entry.card);
        (cards.find((node) => node.dataset.candidateKey === focusKey) || cards[0] || $("worldcupPickerMode")).focus({ preventScroll: true });
      }
    }
    function pickerCardFrom(node) {
      while (node && node !== $("worldcupPickerGrid")) {
        if (node.dataset?.candidateKey && picker.cards.get(node.dataset.candidateKey)?.card === node) return node;
        node = node.parentNode;
      }
      return null;
    }
    function startPickerDrag(event) {
      picker.suppressClick = false;
      if (!picker.open || picker.busy || state.busy || event.pointerType !== "mouse" || event.button !== 0) return;
      const card = pickerCardFrom(event.target);
      const grid = $("worldcupPickerGrid");
      if (card?.disabled) return;
      for (let node = event.target; node && node !== grid; node = node.parentNode) {
        if (node.tagName === "BUTTON" && node !== card) return;
      }
      const bounds = grid.getBoundingClientRect();
      picker.drag = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY, x: event.clientX - bounds.left, y: event.clientY - bounds.top, start: card, selected: !card || !selectedKey(picker.cards.get(card.dataset.candidateKey).item), active: false, baseline: new Map(state.selection), groups: new Map(picker.groupSelection) };
      grid.setPointerCapture(event.pointerId);
    }
    function movePickerDrag(event) {
      const drag = picker.drag;
      if (!drag || drag.pointerId !== event.pointerId) return;
      if (!drag.active && Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY) < 5) return;
      drag.active = true;
      drag.lastX = event.clientX; drag.lastY = event.clientY;
      event.preventDefault();
      const bounds = $("worldcupPickerGrid").getBoundingClientRect();
      const endX = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
      const endY = Math.max(0, Math.min(bounds.height, event.clientY - bounds.top));
      const rect = { left: Math.min(drag.x, endX), top: Math.min(drag.y, endY), right: Math.max(drag.x, endX), bottom: Math.max(drag.y, endY) };
      const marquee = $("worldcupPickerMarquee"); marquee.hidden = false;
      Object.entries({ left: rect.left, top: rect.top, width: rect.right - rect.left, height: rect.bottom - rect.top }).forEach(([key, value]) => { marquee.style[key] = value + "px"; });
      picker.cards.forEach((entry, key) => {
        const cardRect = entry.card.getBoundingClientRect();
        const intersects = cardRect.right - bounds.left >= rect.left && cardRect.left - bounds.left <= rect.right && cardRect.bottom - bounds.top >= rect.top && cardRect.top - bounds.top <= rect.bottom;
        const group = groupKey(entry.item); const baselineKey = drag.groups.get(group);
        if (intersects) setPickerSelection(key, drag.selected);
        else {
          const existing = selectedKey(entry.item);
          if (existing && existing !== baselineKey) { state.selection.delete(existing); picker.groupSelection.delete(group); }
          if (baselineKey) { state.selection.set(baselineKey, drag.baseline.get(baselineKey)); picker.groupSelection.set(group, baselineKey); }
          updatePickerCard(entry);
        }
      });
      renderPickerSelection();
    }
    function finishPickerDrag(refresh = true, cancelled = false) {
      const drag = picker.drag;
      if (!drag) return;
      picker.drag = null;
      $("worldcupPickerMarquee").hidden = true;
      if (cancelled) { state.selection = drag.baseline; picker.groupSelection = drag.groups; picker.cards.forEach(updatePickerCard); }
      const grid = $("worldcupPickerGrid");
      if (grid.hasPointerCapture(drag.pointerId)) grid.releasePointerCapture(drag.pointerId);
      if (drag.active) {
        picker.suppressClick = true;
        if (refresh && picker.mode === "selected") renderPicker(drag.start?.dataset.candidateKey);
      }
      renderPickerSelection();
    }
    function endPickerDrag(event) {
      const drag = picker.drag;
      if (!drag || drag.pointerId !== event.pointerId) return;
      const clickedKey = !drag.active && drag.start && pickerCardFrom(doc.elementFromPoint(event.clientX, event.clientY)) === drag.start ? drag.start.dataset.candidateKey : null;
      finishPickerDrag();
      if (clickedKey) { togglePickerCard(clickedKey); picker.suppressClick = true; }
    }
    function resizePickerCards() {
      const size = Math.max(112, Math.min(240, Number($("worldcupPickerCardSize").value) || 160));
      $("worldcupPickerGrid").style.setProperty("--worldcup-card-size", size + "px");
      $("worldcupPickerCardSizeValue").textContent = size + "px";
    }
    function pickerRequestCurrent(token, filterKey) {
      return picker.open && token === picker.token && filterKey === picker.filterKey;
    }
    async function loadPickerPage(page, autoSize) {
      if (!picker.open || picker.busy || state.busy || !picker.filters) return;
      finishPickerDrag(false, true);
      if (picker.mode === "selected" && autoSize === undefined) {
        picker.token += 1; picker.page = page; pickerStatus(""); renderPicker();
        restoreScroll(); return;
      }
      const token = ++picker.token;
      const filterKey = picker.filterKey;
      const filters = { ...picker.filters, sources: autoSize !== undefined || picker.source === "all" ? picker.filters.sources : [picker.source] };
      picker.busy = true; pickerStatus(autoSize === undefined ? "후보를 불러오는 중…" : "자동으로 고른 그림체를 불러오는 중…"); syncPickerControls();
      try {
        const data = await request("/candidates", { ...filters, sort: $("worldcupPickerSort").value || "default", page, per_page: PICKER_PAGE_SIZE, ...(autoSize === undefined ? {} : { auto_size: autoSize }) });
        if (!pickerRequestCurrent(token, filterKey)) return;
        if (autoSize !== undefined) {
          if (!Array.isArray(data.selection)) throw new Error("자동 선택 명단을 불러오지 못했습니다. 다시 열어 주세요.");
          data.selection.forEach(addPickerSelection);
          picker.mode = "selected"; $("worldcupPickerMode").value = "selected";
        }
        picker.page = data.page || page; picker.items = (data.items || []).slice(0, PICKER_PAGE_SIZE); picker.total = data.count;
        picker.ready = true;
        pickerStatus(""); renderPicker();
        restoreScroll();
      } catch (error) {
        if (pickerRequestCurrent(token, filterKey)) pickerStatus(error.message || "후보를 불러오지 못했습니다. 다시 열어 주세요.", "error");
      } finally {
        if (pickerRequestCurrent(token, filterKey)) { picker.busy = false; syncPickerControls(); }
      }
    }
    function closePicker() {
      finishPickerDrag(false, true);
      picker.open = false; picker.busy = false; picker.token += 1;
      state.previewVersion += 1; candidateDetail.token += 1;
      candidateDetail.open = false;
      $("worldcupCandidateDetail").hidden = true;
      $("worldcupGalleryLayout").dataset.detailOpen = "false";
    }
    async function autoSelect() {
      if (!picker.open || picker.busy || !canStart(state.count, $("worldcupSize").value, state.busy)) return;
      const size = $("worldcupSize").value;
      picker.source = "all";
      await loadPickerPage(1, size === "all" ? "all" : Number(size));
    }
    async function changePickerView(source = picker.source) {
      if (!picker.open || picker.busy || state.busy || !picker.filters) return;
      if (source !== "all" && !picker.filters.sources.includes(source)) return;
      finishPickerDrag(false, true);
      picker.source = source; picker.mode = $("worldcupPickerMode").value;
      picker.page = 1; picker.items = []; picker.total = 0;
      renderPicker();
      restoreScroll();
      await loadPickerPage(1);
    }
    async function applyPickerFilters() {
      if (!picker.open || picker.busy || state.busy) return;
      const version = state.previewVersion + 1;
      const applied = await preview();
      if (!applied || !picker.open || version !== state.previewVersion || state.filterKey !== JSON.stringify(readFilters())) return;
      picker.filters = state.filters; picker.filterKey = state.filterKey; picker.token += 1;
      picker.mode = "all"; $("worldcupPickerMode").value = "all";
      $("worldcupPickerModel").textContent = "적용 모델 · " + (MODEL_LABELS[picker.filters.model] || MODEL_LABELS.all);
      await loadPickerPage(1);
    }
    function detailImageUrl(value) {
      const url = String(value || "");
      if (!/^\/(?:arca-style-images|confirmed-style-images)\//.test(url) || /[\\\x00-\x1f]/.test(url)) return "";
      const parts = url.split("/");
      if (parts.some((part) => part === "." || part === "..")) return "";
      return parts.map((part) => encodeURIComponent(part)).join("/");
    }
    function syncCandidateControls() {
      const blocked = state.busy || !candidateDetail.open || !candidateDetail.images.length;
      $("worldcupCandidateDetailPrev").disabled = blocked || candidateDetail.index <= 0;
      $("worldcupCandidateDetailNext").disabled = blocked || candidateDetail.index >= candidateDetail.images.length - 1;
      $("worldcupCandidateDetailSize").disabled = blocked;
      $("worldcupCandidateDetailBack").disabled = state.busy;
    }
    function resizeCandidateImage() {
      const value = Number($("worldcupCandidateDetailSize").value);
      const size = Number.isFinite(value) ? Math.max(40, Math.min(100, value)) : 100;
      $("worldcupCandidateDetailSize").value = String(size);
      $("worldcupCandidateDetailSizeValue").textContent = size + "%";
      $("worldcupCandidateDetailImage").style.setProperty("--worldcup-detail-image-size", size + "%");
    }
    function moveCandidateImage(offset) {
      if (!candidateDetail.open || state.view !== "picker" || state.busy) return;
      renderCandidateImage(candidateDetail.index + offset);
    }
    function renderCandidateImage(index) {
      const image = candidateDetail.images[index];
      if (!image) return;
      candidateDetail.index = index;
      $("worldcupCandidateDetailImage").replaceChildren(imageFor(image));
      $("worldcupCandidateDetailImageModel").textContent = (index + 1) + " / " + candidateDetail.images.length + " · " + (image.model_display_name || MODEL_LABELS[image.model] || image.model || "모델 미상");
      $("worldcupCandidateDetailBase").textContent = image.base_prompt || image.prompt || "베이스 프롬프트가 없습니다.";
      $("worldcupCandidateDetailNegative").textContent = image.negative_prompt || "네거티브 프롬프트가 없습니다.";
      const characters = image.character_prompts;
      $("worldcupCandidateDetailCharacters").textContent = Array.isArray(characters) && characters.length
        ? characters.map((entry, position) => {
          const prompt = typeof entry === "string" ? entry : entry?.prompt || "";
          const negative = typeof entry === "object" && entry ? entry.negative_prompt || entry.uc || "" : "";
          return "캐릭터 " + (position + 1) + "\n" + (prompt || "프롬프트가 없습니다.") + (negative ? "\n네거티브: " + negative : "");
        }).join("\n\n") : "캐릭터 프롬프트가 없습니다.";
      Array.from($("worldcupCandidateDetailThumbnails").children).forEach((button, position) => button.setAttribute("aria-pressed", String(position === index)));
      syncCandidateControls();
    }
    async function openCandidateDetail(item, returnFocus) {
      if (!picker.open || picker.busy || state.busy) return;
      finishPickerDrag(false, true);
      if (!candidateDetail.open) candidateDetail.scroll = pageScroll();
      candidateDetail.returnFocus = returnFocus; candidateDetail.item = item;
      const token = ++candidateDetail.token;
      candidateDetail.open = true; candidateDetail.images = []; candidateDetail.data = null; candidateDetail.index = 0;
      $("worldcupCandidateDetailTitle").textContent = item.title || "그림체 상세";
      $("worldcupCandidateDetailTitle").title = item.title || "그림체 상세";
      $("worldcupCandidateDetailStatus").textContent = "상세 정보를 불러오는 중…";
      ["worldcupCandidateDetailMetadata", "worldcupCandidateDetailThumbnails", "worldcupCandidateDetailImage"].forEach((id) => $(id).replaceChildren());
      $("worldcupCandidateDetailContent").hidden = true;
      resizeCandidateImage(); syncCandidateControls();
      showView("picker", "worldcupCandidateDetailTitle");
      try {
        if (!/^\/api\/(?:arca-styles|confirmed-styles)\/[1-9][0-9]*$/.test(item.detail_url || "")) throw new Error("이 그림체의 상세 주소를 확인할 수 없습니다.");
        const response = await fetcher(item.detail_url, {});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || "상세 정보를 불러오지 못했습니다.");
        if (token !== candidateDetail.token || !candidateDetail.open || state.view !== "picker") return;
        candidateDetail.data = data;
        const confirmed = item.image_source === "confirmed";
        candidateDetail.images = (data.images || []).map((image) => {
          const url = detailImageUrl(image.local_image_url || image.image_url);
          return { ...image, image_url: url, thumbnail_url: url.replace(confirmed ? "/confirmed-style-images/" : "/arca-style-images/", "/style-manager-thumbnails/" + (confirmed ? "confirmed" : "shared") + "/"), available: Boolean(url) && image.image_available !== false, image_source: item.image_source, title: item.title,
            ...(confirmed ? { base_prompt: [data.artist_prompt, data.quality_prompt, data.fixed_prompt].filter(Boolean).join(", "), negative_prompt: data.negative_prompt, character_prompts: data.character_prompts, model: data.model } : {}) };
        });
        const metadata = $("worldcupCandidateDetailMetadata");
        metadata.append(text("p", (confirmed ? "확정 그림체" : "공유 그림체") + " · " + (item.recommendation_count == null ? "추천수 없음/미상" : "추천 " + item.recommendation_count) + " · 이미지 " + candidateDetail.images.length + "개", "worldcup-help"));
        const sourceUrl = safeSourceUrl(data.source_url || data.url || item.source_url);
        if (sourceUrl) { const link = text("a", "원문 게시글 열기 ↗"); link.href = sourceUrl; link.target = "_blank"; link.rel = "noopener noreferrer"; metadata.append(link); }
        const thumbs = $("worldcupCandidateDetailThumbnails");
        candidateDetail.images.forEach((image, index) => {
          const button = doc.createElement("button"); button.type = "button"; button.className = "worldcup-candidate-thumbnail";
          button.setAttribute("aria-label", "이미지 " + (index + 1) + " 보기"); button.append(imageFor(image, true, true));
          button.addEventListener("click", () => renderCandidateImage(index)); thumbs.append(button);
        });
        const initial = Math.max(0, candidateDetail.images.findIndex((image) => String(image.id) === String(item.key).split(":")[1]));
        $("worldcupCandidateDetailContent").hidden = !candidateDetail.images.length;
        $("worldcupCandidateDetailStatus").textContent = candidateDetail.images.length ? "← → 다른 그림 · Esc 상세 닫기" : "표시할 이미지가 없습니다.";
        renderCandidateImage(initial);
      } catch (error) {
        if (token === candidateDetail.token && candidateDetail.open && state.view === "picker") $("worldcupCandidateDetailStatus").textContent = error.message || "상세 정보를 불러오지 못했습니다.";
      }
    }
    function closeCandidateDetail() {
      candidateDetail.token += 1; candidateDetail.open = false;
      showView("picker"); candidateDetail.returnFocus?.focus({ preventScroll: true });
      restoreScroll(candidateDetail.scroll || undefined);
    }
    function imageFor(participant, compact = false, thumbnail = false) {
      const missingMessage = participant?.image_source === "confirmed"
        ? "이미지가 없습니다. 그림체 관리에서 확정 그림체의 원본 이미지를 확인해 주세요."
        : "이미지가 없습니다. 공유 그림체 수집에서 이미지를 설치·복원해 주세요.";
      const missing = () => text("span", compact ? "이미지 없음" : missingMessage, "worldcup-image-missing");
      const url = participant?.available === false ? "" : (thumbnail && safeLocalImageUrl(participant?.thumbnail_url)) || safeLocalImageUrl(participant?.image_url);
      if (!url) return missing();
      const image = doc.createElement("img");
      image.className = "worldcup-image";
      image.src = url;
      image.alt = participant.title || "그림체";
      image.loading = "lazy";
      if (thumbnail) { image.decoding = "async"; image.draggable = false; }
      image.addEventListener("error", () => image.replaceWith(missing()), { once: true });
      return image;
    }
    function participantInfo(participant) {
      const details = doc.createElement("details"); details.className = "worldcup-info";
      details.append(text("summary", "베이스 프롬프트 · 출처 보기"));
      if (participant.image_source !== "confirmed") details.append(text("p", participant.recommendation_count == null ? "추천수 미상" : "추천 " + participant.recommendation_count, "worldcup-help"));
      details.append(text("pre", participant.base_prompt || "저장된 베이스 프롬프트가 없습니다."));
      const sourceUrl = safeSourceUrl(participant.source_url);
      if (sourceUrl) {
        const link = text("a", "원문 게시글 열기 ↗");
        link.href = sourceUrl; link.target = "_blank"; link.rel = "noopener noreferrer";
        details.append(link);
      }
      return details;
    }
    function participantCard(participant, selectable) {
      const card = doc.createElement("article"); card.className = "worldcup-card";
      card.append(text("p", participant.image_source === "confirmed" ? "확정 그림체" : "공유 그림체", "worldcup-help"));
      if (selectable) {
        const button = doc.createElement("button"); button.type = "button"; button.className = "worldcup-choice";
        button.setAttribute("aria-label", (participant.title || "그림체") + " 선택");
        button.append(imageFor(participant), text("span", participant.title || "제목 없는 그림체"), text("span", "이 그림 선택", "worldcup-choice-label"));
        button.addEventListener("click", () => choose(participant.ordinal));
        card.append(button);
      } else {
        card.append(text("p", "우승", "worldcup-winner-label"), imageFor(participant), text("h4", participant.title || "제목 없는 그림체"));
      }
      card.append(participantInfo(participant));
      return card;
    }
    function renderList() {
      const root = $("worldcupList"); root.replaceChildren();
      if (!state.list.length) {
        root.append(text("p", "아직 저장된 월드컵이 없습니다. 새로 만들어 시작해 보세요.", "worldcup-help"));
        return;
      }
      state.list.forEach((cup) => {
        const card = doc.createElement("article"); card.className = "worldcup-list-card";
        const completed = cup.status === "completed";
        const button = doc.createElement("button"); button.type = "button"; button.className = "worldcup-folder-open";
        button.setAttribute("aria-label", cup.name + " · " + (completed ? "결과 보기" : "이어하기"));
        const preview = doc.createElement("span"); preview.className = "worldcup-folder-preview";
        const previews = previewParticipants(cup);
        preview.dataset.count = String(previews.length);
        if (previews.length) previews.forEach((participant) => preview.append(imageFor(participant, true)));
        else preview.append(imageFor(null, true));
        const meta = doc.createElement("span"); meta.className = "worldcup-folder-meta";
        meta.append(text("strong", cup.name), text("small", cup.size + "개 참가"));
        button.append(preview, meta, text("span", completed ? "완료 · 결과 보기" : "진행 중 · 이어하기", "worldcup-folder-state"));
        if (cup.winner) button.append(text("span", "우승 · " + (cup.winner.title || "그림체"), "worldcup-help"));
        const date = new Date(cup.updated_at);
        if (!Number.isNaN(date.getTime())) button.append(text("span", "저장 " + date.toLocaleString("ko-KR"), "worldcup-help"));
        button.addEventListener("click", () => open(cup.id));
        card.append(button); root.append(card);
      });
    }
    function renderDetail() {
      const cup = state.detail;
      const participants = new Map(cup.participants.map((participant) => [participant.ordinal, participant]));
      const completed = cup.status === "completed";
      $("worldcupTitle").textContent = cup.name;
      $("worldcupMatch").replaceChildren(); $("worldcupResult").replaceChildren();
      $("worldcupMatch").hidden = completed;
      $("worldcupResult").hidden = !completed;
      $("worldcupHistory").hidden = !completed;
      $("worldcupHistory").open = false;
      $("worldcupHistoryList").replaceChildren();
      if (completed) {
        $("worldcupProgress").textContent = cup.size + "개 참가 · 월드컵 완료 · 최종 결과가 저장되었습니다.";
        const winner = participants.get(cup.winner);
        if (winner) $("worldcupResult").append(participantCard(winner, false));
        (cup.history || []).forEach((match) => {
          const title = (ordinal) => participants.get(ordinal)?.title || "그림체";
          $("worldcupHistoryList").append(text("li", roundLabel(match.round_size) + " · " + title(match.left) + " / " + title(match.right) + " → " + title(match.winner) + " 선택"));
        });
      } else if (cup.current_match) {
        const match = cup.current_match;
        const byeCount = Number(match.bye_count ?? cup.bye_count ?? 0);
        $("worldcupProgress").textContent = cup.size + "개 참가 · " + roundLabel(match.round_size) + " · " + match.match_number + " / " + match.matches_in_round + " 경기" + (byeCount > 0 ? " · 첫 라운드 부전승 " + byeCount + "개" : "") + " · 선택할 때마다 자동 저장됩니다.";
        [match.left, match.right].forEach((ordinal) => {
          const participant = participants.get(ordinal);
          if (participant) $("worldcupMatch").append(participantCard(participant, true));
        });
      }
    }
    async function load() {
      return run("저장된 월드컵을 불러오는 중…", async () => {
        const list = await request("");
        state.list = list;
        renderList();
        status("");
      });
    }
    async function newWorldcup() {
      if (state.busy) return;
      closePicker();
      $("worldcupForm").reset();
      [...FILTER_IDS, "worldcupModel", "worldcupPickerSort"].forEach((id) => { $(id).value = id === "worldcupModel" ? "all" : id === "worldcupPickerSort" ? "default" : ""; });
      state.selection.clear(); state.count = null; state.counts = null; state.filterKey = null; state.filters = null;
      picker.open = true; picker.ready = false; picker.filters = null; picker.filterKey = null; picker.source = "all"; picker.mode = "all"; picker.page = 1; picker.total = 0; picker.items = []; picker.groupSelection.clear(); picker.suppressClick = false;
      $("worldcupPickerMode").value = "all";
      $("worldcupPickerModel").textContent = "적용 모델 · 없음";
      pickerStatus(""); renderSizes(); renderCount(); status(""); resizePickerCards(); renderPicker();
      showView("picker", "worldcupName"); restoreScroll();
    }
    async function showList() {
      if (state.busy) return;
      closePicker();
      showView("list");
      await load();
      $("worldcupNew").focus();
    }
    async function preview() {
      if (state.busy || picker.busy || !picker.open) return;
      const filters = validFilters(); if (!filters) return;
      const version = ++state.previewVersion;
      const token = ++picker.token;
      const filterKey = JSON.stringify(filters);
      let applied = false;
      picker.busy = true; pickerStatus("조건에 맞는 후보 확인 중…"); syncPickerControls();
      try {
        const data = await request("/preview", filters);
        if (!picker.open || token !== picker.token || version !== state.previewVersion || filterKey !== JSON.stringify(readFilters())) return false;
        state.count = data.count; state.counts = data.counts || null; state.filterKey = filterKey; state.filters = filters;
        applied = true;
        renderSizes();
        renderCount(); status("");
      } catch (error) {
        if (picker.open && token === picker.token) pickerStatus(error.message || "후보를 확인하지 못했습니다. 필터 적용으로 다시 시도해 주세요.", "error");
      } finally {
        if (picker.open && token === picker.token) { picker.busy = false; syncPickerControls(); }
      }
      return applied;
    }
    async function start() {
      if (state.busy || picker.busy || !picker.open || state.view !== "picker" || state.selection.size < 2) return;
      finishPickerDrag(true);
      const filters = state.filters || { sources: ["shared", "confirmed"], model: "all" };
      const name = $("worldcupName").value.trim();
      if (!name) { status("월드컵 이름을 입력해 주세요.", "error"); $("worldcupName").focus(); return; }
      return run("월드컵을 만드는 중…", async () => {
        const cup = await request("", { name, size: "all", selected_candidates: [...state.selection.keys()], selection_scope: "all", ...filters });
        closePicker();
        state.detail = cup;
        renderDetail(); showView("detail", "worldcupTitle");
        status("월드컵이 저장되었습니다. 더 마음에 드는 그림을 선택해 주세요.");
      });
    }
    async function open(id) {
      return run("월드컵을 불러오는 중…", async () => {
        const cup = await request("/" + encodeURIComponent(id));
        state.detail = cup;
        renderDetail(); showView("detail", "worldcupTitle"); status("");
      });
    }
    async function choose(ordinal) {
      const cup = state.detail;
      if (state.busy || !cup?.current_match || ![cup.current_match.left, cup.current_match.right].includes(ordinal)) return;
      return run("선택을 저장하는 중…", async () => {
        let latest;
        let conflict = false;
        try { latest = await request("/" + encodeURIComponent(cup.id) + "/choose", { revision: cup.revision, winner: ordinal, compact: true }); }
        catch (error) {
          if (error.status !== 409) throw error;
          latest = await request("/" + encodeURIComponent(cup.id));
          conflict = true;
        }
        if (!conflict && latest.participants_partial === true) {
          const participants = new Map(cup.participants.map((participant) => [participant.ordinal, participant]));
          latest.participants.forEach((participant) => participants.set(participant.ordinal, participant));
          latest = { ...latest, participants: [...participants.values()] };
          delete latest.participants_partial;
        }
        state.detail = latest;
        renderDetail(); $("worldcupTitle").focus();
        status(conflict ? "다른 화면에서 저장된 최신 진행 상태를 불러왔습니다." : latest.status === "completed" ? "우승 결과가 저장되었습니다." : "선택이 저장되었습니다.");
      });
    }
    function bind() {
      $("worldcupNew").addEventListener("click", newWorldcup);
      $("worldcupBack").addEventListener("click", showList);
      $("worldcupAutoSelect").addEventListener("click", autoSelect);
      Object.entries(PICKER_SOURCES).forEach(([id, source]) => $(id).addEventListener("click", () => changePickerView(source)));
      $("worldcupPickerMode").addEventListener("change", () => changePickerView());
      $("worldcupPickerSort").addEventListener("change", () => changePickerView());
      $("worldcupPickerFilterApply").addEventListener("click", applyPickerFilters);
      $("worldcupPickerFilters").addEventListener("keydown", (event) => {
        if (event.key === "Enter" && event.target.id === "worldcupRecommendation") { event.preventDefault(); return applyPickerFilters(); }
      });
      $("worldcupPickerPrev").addEventListener("click", () => loadPickerPage(picker.page - 1));
      $("worldcupPickerNext").addEventListener("click", () => loadPickerPage(picker.page + 1));
      $("worldcupPickerClose").addEventListener("click", showList);
      $("worldcupPickerCloseBottom").addEventListener("click", showList);
      doc.addEventListener?.("keydown", (event) => {
        if (event.key === "Escape" && picker.drag) { event.preventDefault(); finishPickerDrag(true, true); return; }
        if (state.view !== "picker" || !candidateDetail.open || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.key === "Escape") { event.preventDefault(); closeCandidateDetail(); return; }
        if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) || event.target?.isContentEditable) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); moveCandidateImage(event.key === "ArrowLeft" ? -1 : 1); }
      });
      $("worldcupCandidateDetailBack").addEventListener("click", closeCandidateDetail);
      $("worldcupCandidateDetailPrev").addEventListener("click", () => moveCandidateImage(-1));
      $("worldcupCandidateDetailNext").addEventListener("click", () => moveCandidateImage(1));
      $("worldcupCandidateDetailSize").addEventListener("input", resizeCandidateImage);
      const pickerGrid = $("worldcupPickerGrid");
      pickerGrid.addEventListener("pointerdown", startPickerDrag);
      pickerGrid.addEventListener("pointermove", movePickerDrag);
      pickerGrid.addEventListener("pointerup", endPickerDrag);
      pickerGrid.addEventListener("pointercancel", () => finishPickerDrag(true, true));
      pickerGrid.addEventListener("lostpointercapture", () => finishPickerDrag(true, true));
      pickerGrid.addEventListener("click", () => { picker.suppressClick = false; });
      pickerGrid.addEventListener("dragstart", (event) => event.preventDefault());
      doc.addEventListener?.("scroll", () => {
        if (picker.drag?.active) movePickerDrag({ pointerId: picker.drag.pointerId, clientX: picker.drag.lastX, clientY: picker.drag.lastY, preventDefault() {} });
      }, true);
      $("worldcupPickerCardSize").addEventListener("input", resizePickerCards);
      $("worldcupForm").addEventListener("submit", (event) => { event.preventDefault(); return start(); });
      FILTER_IDS.forEach((id) => $(id).addEventListener("input", invalidateCount));
      $("worldcupModel").addEventListener("change", invalidateCount);
      TAG_IDS.forEach((id) => globalThis.promptTagAutocomplete?.bind?.($(id)));
      $("worldcupSize").addEventListener("change", renderCount);
      doc.querySelector('.tab[data-tab="style-worldcup"]')?.addEventListener("click", load);
      syncControls();
    }
    bind();
    return { load, newWorldcup, showList, preview, start, open, choose, state };
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { splitConditions, safeSourceUrl, safeLocalImageUrl, roundLabel, availableSizes, canStart, previewParticipants, createController };
  if (typeof document !== "undefined") {
    const initialize = () => {
      if (document.getElementById("style-worldcup-tab")) globalThis.styleWorldcup = createController(document, (...args) => fetch(...args));
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialize, { once: true });
    else initialize();
  }
})();
