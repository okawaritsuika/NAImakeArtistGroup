(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    groups: [], targets: [], selectedSources: [], baseSource: null, reference: null,
    editingGroup: null, group: null, review: null, sourceIndex: 0,
    sourceGalleryMode: "view", directSamples: [], directArtist: "", galleryArtist: null, galleryArtistTag: "",
    pendingRemoveArtist: null, reviewFocusManualExpanded: null,
  };
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null ? "" : String(value);
    return node;
  };
  const status = (message, kind) => {
    const node = $("styleGroupStatus");
    if (node) { node.textContent = message || ""; node.dataset.state = kind || ""; }
  };
  async function json(url, options) {
    options = options || {};
    const form = typeof FormData !== "undefined" && options.body instanceof FormData;
    const response = await fetch(url, {
      headers: Object.assign(form ? {} : { "Content-Type": "application/json" }, options.headers || {}),
      ...options,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || "그림체 그룹 요청에 실패했습니다.");
    return body;
  }

  function normalizeArtistTag(value) {
    return String(value || "").replace(/_/g, " ").trim().split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  }
  function sourceKey(type, id) { return String(type) + ":" + String(id); }
  function targetPriority(type, id, order) {
    const index = (order || []).indexOf(sourceKey(type, id));
    return index < 0 ? null : index + 1;
  }
  function newTargetsOnly(targets, existingSources) {
    const existing = new Set((existingSources || []).map((source) => sourceKey(source.source_type, source.source_id)));
    return (targets || []).filter((target) => !existing.has(sourceKey(target.source_type, target.source_id)));
  }
  function setTargetSelection(sources, target, checked) {
    const key = sourceKey(target.source_type, target.source_id);
    const rest = (sources || []).filter((source) => sourceKey(source.source_type, source.source_id) !== key);
    if (checked) rest.push({ source_type: target.source_type, source_id: target.source_id, label: target.label || target.name });
    return rest;
  }
  function sourceGalleryHelp(mode) {
    return mode === "reference" ? "한 번 클릭하면 옆 큰 미리보기 갱신 · 더블 클릭 기준 선택" : "그림을 클릭하면 옆 큰 미리보기가 갱신됩니다.";
  }
  function targetCardKeyboardAction(event) {
    return event && (event.key === "Enter" || event.key === " ") ? "toggle" : null;
  }
  function canStartGroupReview(args) {
    args = args || {};
    return args.addingTo ? Boolean((args.selectedSources || []).length || args.referenceSelected || args.baseChanged) : Boolean((args.selectedSources || []).length);
  }
  function sourceHasArtist(source, artistKey) {
    return (source && source.artists || []).some((artist) => normalizeArtistTag(artist.artist_key || artist.artist_tag) === artistKey)
      || (source && source.images || []).some((image) => normalizeArtistTag(image.artist_key || image.artist_tag) === artistKey);
  }
  function visibleSourcesForArtist(sources, artistKey) {
    return (sources || []).filter((source) => sourceHasArtist(source, artistKey));
  }
  function baseSourceIndex(sources, baseSource) {
    if (!baseSource) return 0;
    const index = (sources || []).findIndex((source) => sourceKey(source.source_type, source.source_id) === sourceKey(baseSource.source_type, baseSource.source_id));
    return index < 0 ? 0 : index;
  }
  function filterArtistGalleryImages(images, artistKey) {
    const normalized = normalizeArtistTag(artistKey);
    return (images || []).filter((image) => normalizeArtistTag(image.artist_key || image.artist_tag) === normalized);
  }
  function nextSourceIndex(length, current, delta) {
    if (!length) return 0;
    return (Number(current || 0) + Number(delta || 0) + length) % length;
  }
  function shouldCloseModalOnBackdrop(event) {
    return Boolean(event && event.target && event.currentTarget && event.target === event.currentTarget);
  }
  function reviewFocusExpanded(hasArtist, manualExpanded) {
    return manualExpanded === null || manualExpanded === undefined ? Boolean(hasArtist) : Boolean(manualExpanded);
  }
  function keyboardAction(event) {
    const target = event && event.target;
    const tag = String(target && target.tagName || "").toLowerCase();
    if (["input", "textarea", "select", "button"].includes(tag) || target && target.isContentEditable || target && target.closest && target.closest(".style-group-modal,[role=dialog],.modal")) return null;
    return ({ ArrowLeft: "include", ArrowRight: "exclude", ArrowUp: "previous", ArrowDown: "next" })[event && event.key] || null;
  }
  function openModal(id) { $(id)?.classList.remove("hidden"); }
  function closeModal(id) {
    globalThis.promptTagAutocomplete?.hide?.();
    $(id)?.classList.add("hidden");
  }
  function setReviewFocusExpanded(expanded) {
    const toggle = $("styleGroupReviewFocusToggle"); const body = $("styleGroupReviewFocusBody");
    if (toggle) { toggle.setAttribute("aria-expanded", String(Boolean(expanded))); toggle.textContent = expanded ? "현재 작가 영역 접기" : "현재 작가 영역 펼치기"; }
    if (body) body.hidden = !expanded;
  }
  function setGalleryActions(artistKey) {
    state.galleryArtist = artistKey || null;
    const actions = $("styleGroupGalleryActions");
    if (!actions) return;
    const enabled = Boolean(state.galleryArtist);
    actions.classList.toggle("hidden", !enabled);
    const danbooruButton = $("styleGroupGalleryDanbooru"); const naiButton = $("styleGroupGalleryNaiTest"); const help = $("styleGroupGalleryNaiHelp");
    if (danbooruButton) danbooruButton.title = "Danbooru 그림 가져오기";
    const canGenerate = state.group?.base_source?.source_type === "nai_test";
    if (naiButton) { naiButton.disabled = !enabled || !canGenerate; naiButton.title = canGenerate ? "기본 NAI 테스트에서 이 작가로 1장을 생성합니다." : "기본 대상이 평가 관리라 NAI 생성은 사용할 수 없습니다."; }
    if (help) help.textContent = canGenerate ? "" : "기본 테스트 없음 · 평가 관리 기반 그룹에서는 NAI 생성을 사용할 수 없습니다.";
  }
  function artistGallerySizeValue(value) { return Math.max(180, Math.min(360, Number(value) || 240)); }
  function setArtistGallerySize(value) {
    const root = $("styleGroupArtistGallery"); const input = $("styleGroupArtistSize"); const output = $("styleGroupArtistSizeValue");
    const size = artistGallerySizeValue(value);
    if (root) root.style.setProperty("--style-group-artist-size", size + "px");
    if (input && input.value !== String(size)) input.value = String(size);
    if (output) output.textContent = size + "px";
  }
  function galleryImageLabel(image, fallback) { return image?.artist_tag || image?.artist_key || fallback || "그림"; }
  function updateGalleryPreview(image, button, fallback) {
    const preview = $("styleGroupGalleryPreview"); const empty = $("styleGroupGalleryPreviewEmpty"); const label = $("styleGroupGalleryPreviewLabel");
    const url = image?.image_url || ""; const title = image ? galleryImageLabel(image, fallback) : "선택된 그림 없음";
    if (preview) { preview.src = url; preview.alt = title; preview.hidden = !url; }
    if (empty) { empty.hidden = Boolean(url); empty.textContent = image ? "미리보기를 사용할 수 없습니다." : "그림을 선택해 주세요."; }
    if (label) label.textContent = title;
    $("styleGroupSourceGallery")?.querySelectorAll(".style-group-gallery-image").forEach((item) => { const selected = item === button; item.classList.toggle("is-selected", selected); item.setAttribute("aria-pressed", String(selected)); });
  }
  function renderGalleryImages(images, options) {
    options = options || {};
    const root = $("styleGroupSourceGallery"); if (!root) return;
    const items = images || []; root.replaceChildren();
    if (!items.length) { updateGalleryPreview(null, null, options.artistFallback); root.append(text("p", "이 출처에 표시할 그림이 없습니다.", "help-text")); return; }
    let firstButton = null;
    items.forEach((image, index) => {
      const button = document.createElement("button"); button.type = "button"; button.className = "style-group-gallery-image"; button.setAttribute("aria-pressed", "false");
      const img = document.createElement("img"); img.src = image.image_url || ""; img.alt = galleryImageLabel(image, options.artistFallback || "출처 그림");
      button.append(img, text("span", options.caption ? options.caption(image) : galleryImageLabel(image, options.artistFallback)));
      button.addEventListener("click", () => updateGalleryPreview(image, button, options.artistFallback));
      if (options.referenceMode) button.addEventListener("dblclick", (event) => { event.preventDefault(); state.reference = { source_type: image.source_type, source_id: image.source_id, candidate_key: image.candidate_key, image_url: image.image_url }; renderWizardSummary(); closeModal("styleGroupSourceGalleryModal"); });
      root.append(button); if (index === 0) firstButton = button;
    });
    updateGalleryPreview(items[0], firstButton, options.artistFallback);
  }
  function prepareDirectArtist(artistTag) {
    state.directArtist = artistTag || ""; state.directSamples = [];
    const field = $("styleGroupDirectArtist"); if (field) field.value = state.directArtist;
    $("styleGroupDirectSamples")?.replaceChildren();
    const importAction = $("styleGroupDirectImport"); if (importAction) importAction.disabled = true;
    const score = $("styleGroupDirectScore"); if (score) score.value = "";
    openModal("styleGroupDirectModal");
  }
  function requestRemoveArtist(artist) {
    state.pendingRemoveArtist = artist || null;
    const name = $("styleGroupRemoveArtistName"); if (name) name.textContent = artist?.artist_tag || "";
    openModal("styleGroupRemoveArtistModal");
  }
  function sourceSet() { return new Set(state.selectedSources.map((source) => sourceKey(source.source_type, source.source_id))); }
  function existingSet() { return new Set((state.editingGroup?.sources || []).map((source) => sourceKey(source.source_type, source.source_id))); }

  async function loadGroups() { state.groups = await json("/api/style-groups"); renderGroups(); }
  async function loadTargets() { const data = await json("/api/style-groups/targets"); state.targets = data.sources || []; renderTargetCards(); }

  function renderGroups() {
    const root = $("styleGroupGallery"); if (!root) return;
    root.replaceChildren();
    if (!state.groups.length) { root.append(text("p", "아직 만든 그림체 그룹이 없습니다.", "help-text")); return; }
    state.groups.forEach((group) => {
      const card = document.createElement("article"); card.className = "style-group-card style-group-author-card";
      const image = document.createElement("img"); image.alt = group.name + " 기준 그림"; image.src = group.reference_image_url || (group.images || []).find((item) => item.image_url)?.image_url || ""; image.hidden = !image.src; card.append(image);
      const body = document.createElement("div"); body.append(text("h3", group.name), text("p", (group.artist_count || 0) + "명 · " + (group.image_count || 0) + "장 · 미확인 작가 " + (group.unreviewed_count || 0) + "명", "help-text"));
      body.append(text("p", (group.sources || []).map((source) => source.label || source.source_type).join(" · "), "help-text"));
      const actions = document.createElement("div"); actions.className = "style-group-card-actions";
      const open = text("button", "그룹 열기", "primary"); open.type = "button"; open.addEventListener("click", () => openReview(group.id));
      const rename = text("button", "이름 수정", "ghost"); rename.type = "button"; rename.addEventListener("click", async () => { const name = window.prompt("새 그룹 이름", group.name); if (!name || !name.trim()) return; try { await json("/api/style-groups/" + group.id, { method: "PATCH", body: JSON.stringify({ name: name.trim() }) }); await loadGroups(); } catch (error) { status(error.message, "error"); } });
      const remove = text("button", "삭제", "danger"); remove.type = "button"; remove.addEventListener("click", async () => { if (!window.confirm("이 그룹과 전용 복사본을 삭제할까요?")) return; try { await json("/api/style-groups/" + group.id, { method: "DELETE" }); await loadGroups(); } catch (error) { status(error.message, "error"); } });
      actions.append(open, rename, remove); body.append(actions); card.append(body); root.append(card);
      card.addEventListener("click", (event) => { if (!event.target.closest("button")) openReview(group.id); });
    });
  }

  function renderTargetCards(referenceMode) {
    const root = $("styleGroupTargetCards"); if (!root) return;
    root.replaceChildren();
    const selected = sourceSet(); const existing = existingSet();
    state.targets.forEach((target) => {
      const key = sourceKey(target.source_type, target.source_id);
      const isExisting = existing.has(key); const isSelected = selected.has(key); const title = target.label || target.name || key;
      const card = document.createElement("article"); card.className = "style-group-target-card"; card.classList.toggle("is-selected", isSelected); card.classList.toggle("is-existing", isExisting); card.setAttribute("aria-label", title);
      const head = document.createElement("div"); head.className = "style-group-target-card-head"; head.append(text("h4", title), text("span", (target.artist_count || 0) + "명 · " + (target.image_count || 0) + "장", "help-text")); card.append(head);
      card.append(text("p", target.source_type === "rating_management" ? "평가 관리의 로컬 대표·예시 그림 전체" : "이 테스트에서 완료된 로컬 그림", "help-text"));
      if (referenceMode) {
        const choose = text("button", "이 출처 그림 보기", "ghost"); choose.type = "button"; choose.addEventListener("click", () => openSourceGallery(target, "reference")); card.append(choose);
      } else {
        card.setAttribute("role", "checkbox"); card.setAttribute("tabindex", "0"); card.setAttribute("aria-checked", String(isSelected)); if (isExisting) card.setAttribute("aria-disabled", "true");
        const selection = document.createElement("label"); selection.className = "style-group-target-selection";
        const input = document.createElement("input"); input.type = "checkbox"; input.checked = isSelected; input.disabled = isExisting; input.setAttribute("aria-label", title + " 선택");
        input.addEventListener("change", () => {
          state.selectedSources = setTargetSelection(state.selectedSources, target, input.checked);
          if (!state.baseSource && input.checked) state.baseSource = state.selectedSources[state.selectedSources.length - 1];
          if (!input.checked && state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) === key) state.baseSource = state.selectedSources[0] || null;
          renderTargetCards(false); renderWizardSummary();
        });
        selection.append(input); card.append(selection);
        const footer = document.createElement("div"); footer.className = "style-group-target-footer";
        footer.append(text("span", isExisting ? "이미 연결됨" : isSelected ? "선택됨" : "선택 안 함", "style-group-target-state"));
        const base = text("button", state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) === key ? "기본 대상 ✓" : "기본 대상으로 지정", state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) === key ? "primary" : "ghost");
        base.type = "button"; base.disabled = !isSelected; base.addEventListener("click", (event) => { event.stopPropagation(); state.baseSource = { source_type: target.source_type, source_id: target.source_id, label: title }; renderTargetCards(false); renderWizardSummary(); }); footer.append(base); card.append(footer);
        const toggle = () => { if (!input.disabled) { input.checked = !input.checked; input.dispatchEvent(new Event("change")); } };
        card.addEventListener("click", (event) => { if (event.target.closest("button") || event.target.closest("input")) return; toggle(); });
        card.addEventListener("keydown", (event) => { if (event.target.closest && event.target.closest("input")) return; if (!targetCardKeyboardAction(event)) return; event.preventDefault(); toggle(); });
      }
      root.append(card);
    });
  }
  function renderWizardSummary() {
    const targetSummary = $("styleGroupTargetSummary"); if (targetSummary) targetSummary.textContent = state.selectedSources.length + "개 출처 · 기본 " + (state.baseSource?.label || state.baseSource?.source_type || "미지정");
    const referenceSummary = $("styleGroupReferenceSummary"); if (referenceSummary) referenceSummary.textContent = state.reference ? "선택한 출처 그림 1장" : "선택하지 않음 · 최초 포함 작가의 대표 그림을 사용합니다.";
    const summary = $("styleGroupSelectedTargets"); if (!summary) return; summary.replaceChildren(); state.selectedSources.forEach((source) => summary.append(text("span", (source.label || source.source_type) + (state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) === sourceKey(source.source_type, source.source_id) ? " (기본)" : ""), "style-group-chip")));
  }
  async function openWizard(group) {
    state.editingGroup = group || null;
    state.selectedSources = (group?.sources || []).filter((source) => ["rating_management", "nai_test"].includes(source.source_type)).map((source) => ({ source_type: source.source_type, source_id: source.source_id, label: source.label }));
    state.baseSource = group?.base_source?.source_type ? { ...group.base_source, label: (group.sources || []).find((source) => source.source_type === group.base_source.source_type && String(source.source_id) === String(group.base_source.source_id))?.label || group.base_source.source_type } : state.selectedSources[0] || null;
    state.reference = null; $("styleGroupWizardTitle").textContent = group ? "그룹 출처·기준 수정" : "새 그림체 그룹"; $("styleGroupName").value = group?.name || ""; $("styleGroupName").disabled = Boolean(group);
    await loadTargets(); renderTargetCards(false); renderWizardSummary(); openModal("styleGroupWizardModal");
  }
  function closeWizard() { closeModal("styleGroupWizardModal"); state.editingGroup = null; }
  function targetFor(type, id) { return state.targets.find((target) => target.source_type === type && String(target.source_id) === String(id)) || { source_type: type, source_id: id, label: type }; }

  async function openSourceGallery(target, mode) {
    try {
      const data = await json("/api/style-groups/source-gallery?source_type=" + encodeURIComponent(target.source_type) + "&source_id=" + encodeURIComponent(target.source_id));
      state.sourceGalleryMode = mode || "view"; $("styleGroupSourceGalleryTitle").textContent = target.label || target.name || "출처 그림"; $("styleGroupSourceGalleryHelp").textContent = state.sourceGalleryMode === "reference" ? "한 장을 기준 그림으로 선택합니다. 작가 판단과 독립적으로 보관됩니다. " + sourceGalleryHelp("reference") : sourceGalleryHelp("view");
      setGalleryActions(null);
      renderGalleryImages(data.images || [], { referenceMode: state.sourceGalleryMode === "reference", artistFallback: "출처 그림" });
      openModal("styleGroupSourceGalleryModal");
    } catch (error) { status(error.message, "error"); }
  }
  function openReviewSourceGallery(source, artistKey) {
    const images = filterArtistGalleryImages(source?.images || [], artistKey);
    state.sourceGalleryMode = "view";
    $("styleGroupSourceGalleryTitle").textContent = source?.label || source?.source_type || "현재 출처 그림";
    $("styleGroupSourceGalleryHelp").textContent = "현재 작가의 현재 출처 그림";
    setGalleryActions(null);
    renderGalleryImages(images, { artistFallback: artistKey || "출처 그림" });
    openModal("styleGroupSourceGalleryModal");
  }
  function chooseReference() { renderTargetCards(true); openModal("styleGroupTargetModal"); }

  async function openReview(id, artistKey) {
    try { state.group = await json("/api/style-groups/" + id); state.reviewFocusManualExpanded = null; await refreshReview(artistKey || ""); $("styleGroupGallery")?.classList.add("hidden"); $("styleGroupReview")?.classList.remove("hidden"); closeWizard(); } catch (error) { status(error.message, "error"); }
  }
  async function refreshReview(artistKey) {
    const suffix = artistKey ? "?artist_key=" + encodeURIComponent(artistKey) : "";
    state.review = await json("/api/style-groups/" + state.group.id + "/artist-review" + suffix); state.sourceIndex = baseSourceIndex(state.review.sources || [], state.group.base_source); renderReview();
  }
  function renderReview() {
    const group = state.group; const review = state.review; if (!group || !review) return;
    $("styleGroupReviewTitle").textContent = group.name;
    $("styleGroupReviewBase").textContent = "기본 대상: " + (group.base_source?.source_type ? targetFor(group.base_source.source_type, group.base_source.source_id).label : "없음");
    const reference = $("styleGroupReferenceImage"); const referenceSrc = String(group.reference_image_url || ""); reference.src = referenceSrc; reference.hidden = !referenceSrc; $("styleGroupReferenceEmpty").hidden = Boolean(referenceSrc); reference.closest(".style-group-image-stage")?.classList.toggle("is-empty", !referenceSrc);
    const artist = review.artist; const sources = review.sources || []; const source = sources[state.sourceIndex];
    $("styleGroupCandidateLabel").textContent = artist ? artist.artist_tag + " · 현재 대표" : "현재 작가 없음";
    $("styleGroupCandidateMeta").textContent = artist ? (artist.image_count || 0) + "장 · " + (state.sourceIndex + 1) + "/" + Math.max(1, sources.length) + " 출처" : "모든 기본 대상 작가를 판단했습니다.";
    $("styleGroupReviewSourceStatus").textContent = source ? source.label || source.source_type : "출처 없음";
    const candidate = $("styleGroupCandidateImage"); const candidateSrc = String(source?.representative?.image_url || ""); candidate.src = candidateSrc; candidate.hidden = !candidateSrc; candidate.onclick = () => source && openReviewSourceGallery(source, artist?.artist_key); $("styleGroupCandidateEmpty").hidden = Boolean(candidateSrc); candidate.closest(".style-group-image-stage")?.classList.toggle("is-empty", !candidateSrc);
    const focusExpanded = reviewFocusExpanded(artist, state.reviewFocusManualExpanded);
    setReviewFocusExpanded(focusExpanded);
    $("styleGroupInclude").disabled = !artist; $("styleGroupExclude").disabled = !artist; $("styleGroupOpenArtistGallery").disabled = !artist;
    const sourceList = $("styleGroupSourceList"); sourceList.replaceChildren(); sources.forEach((item, index) => { const button = text("button", (index + 1) + ". " + (item.label || item.source_type) + " · " + (item.images || []).length + "장", index === state.sourceIndex ? "primary" : "ghost"); button.type = "button"; button.addEventListener("click", () => { state.sourceIndex = index; renderReview(); }); sourceList.append(button); });
    const artists = $("styleGroupArtistGallery"); artists.replaceChildren(); (group.included_artists || []).forEach((included) => {
      const card = document.createElement("article"); card.className = "style-group-artist-card"; card.setAttribute("aria-label", included.artist_tag);
      const base = group.base_source || {}; const image = (group.images || []).find((item) => item.image_url && item.source_type === base.source_type && String(item.source_id) === String(base.source_id) && (item.artist_keys?.includes(included.artist_key) || item.artist_key === included.artist_key)) || (group.images || []).find((item) => item.artist_keys?.includes(included.artist_key) || item.artist_key === included.artist_key);
       const thumbWrap = document.createElement("div"); thumbWrap.className = "style-group-artist-thumb";
       if (image?.image_url) { const thumb = document.createElement("img"); thumb.src = image.image_url; thumb.alt = included.artist_tag; thumbWrap.append(thumb); } else thumbWrap.append(text("span", "이미지 없음", "style-group-artist-thumb-empty"));
       const remove = text("button", "×", "style-group-artist-remove"); remove.type = "button"; remove.title = included.artist_tag + " 작가 제거"; remove.setAttribute("aria-label", included.artist_tag + " 작가 제거"); remove.addEventListener("click", (event) => { event.stopPropagation(); requestRemoveArtist(included); }); thumbWrap.append(remove); card.append(thumbWrap);
      const footer = document.createElement("div"); footer.className = "style-group-artist-card-footer"; footer.append(text("h4", included.artist_tag)); const all = text("button", "상세 보기", "ghost"); all.type = "button"; all.addEventListener("click", (event) => { event.stopPropagation(); openIncludedGallery(included.artist_key); }); footer.append(all); card.append(footer);
      card.addEventListener("click", (event) => { if (!event.target.closest("button")) openIncludedGallery(included.artist_key); }); artists.append(card);
    });
  }
  async function openIncludedGallery(artistKey) {
    try {
      const data = await json("/api/style-groups/" + state.group.id + "/artist-gallery?artist_key=" + encodeURIComponent(artistKey));
      state.galleryArtistTag = data.artist?.artist_tag || artistKey; $("styleGroupSourceGalleryTitle").textContent = state.galleryArtistTag; $("styleGroupSourceGalleryHelp").textContent = "연결된 모든 출처의 현재 작가 그림";
      setGalleryActions(artistKey);
      const images = [];
      (data.sources || []).forEach((source) => {
        filterArtistGalleryImages(source.images, artistKey).forEach((image) => images.push(Object.assign({}, image, { source_label: source.label || source.source_type })));
      });
      renderGalleryImages(images, { artistFallback: artistKey, caption: (image) => image.source_label + " · " + galleryImageLabel(image, artistKey) });
      openModal("styleGroupSourceGalleryModal");
    } catch (error) { status(error.message, "error"); }
  }
  async function generateIncludedArtistTest() {
    const artistKey = state.galleryArtist; const base = state.group?.base_source;
    if (!artistKey || base?.source_type !== "nai_test") return;
    try {
      const test = await json("/api/nai-artist-tests/" + base.source_id);
      const preflight = globalThis.naiArtistTestGenerationPreflight;
      if (typeof preflight === "function" && !(await preflight(test, "single"))) return;
      await json("/api/style-groups/" + state.group.id + "/nai-tests/" + base.source_id + "/generate-first", { method: "POST", body: JSON.stringify({ artist_tag: state.galleryArtistTag || artistKey }) });
      closeModal("styleGroupSourceGalleryModal"); await openReview(state.group.id, artistKey); await loadGroups();
    } catch (error) { status(error.message, "error"); }
  }
  async function confirmRemoveArtist() {
    const artist = state.pendingRemoveArtist; if (!artist || !state.group) return;
    try {
      const groupId = state.group.id;
      await json("/api/style-groups/" + groupId + "/artists/" + encodeURIComponent(artist.artist_key), { method: "DELETE" });
      state.pendingRemoveArtist = null; closeModal("styleGroupRemoveArtistModal"); await openReview(groupId); await loadGroups();
    } catch (error) { status(error.message, "error"); }
  }
  async function decideArtist(include) {
    const artist = state.review?.artist; if (!artist) return; const source = state.review.sources?.[state.sourceIndex]; const representative = source?.representative;
    try { state.group = await json("/api/style-groups/" + state.group.id + "/artist-decision", { method: "POST", body: JSON.stringify({ artist_tag: artist.artist_tag, include: include, reference_source_type: representative?.source_type, reference_source_id: representative?.source_id, reference_candidate_key: representative?.candidate_key }) }); await refreshReview(""); await loadGroups(); } catch (error) { status(error.message, "error"); }
  }
  function moveSource(delta) { if (!state.review?.sources?.length) return; state.sourceIndex = nextSourceIndex(state.review.sources.length, state.sourceIndex, delta); renderReview(); }

  function renderExcluded() {
    const root = $("styleGroupExcludedList"); if (!root) return; root.replaceChildren(); const query = ($("styleGroupExcludedSearch")?.value || "").trim().toLowerCase();
    (state.group?.excluded_artists || []).filter((artist) => !query || artist.artist_tag.toLowerCase().includes(query)).forEach((artist) => { const row = document.createElement("div"); row.className = "style-group-excluded-row"; row.append(text("span", artist.artist_tag)); const reconsider = text("button", "다시 확인", "ghost"); reconsider.type = "button"; reconsider.addEventListener("click", () => { closeModal("styleGroupExcludedModal"); openReview(state.group.id, artist.artist_key); }); const include = text("button", "바로 포함", "primary"); include.type = "button"; include.addEventListener("click", async () => { try { state.group = await json("/api/style-groups/" + state.group.id + "/artist-decision", { method: "POST", body: JSON.stringify({ artist_tag: artist.artist_tag, include: true }) }); renderExcluded(); renderReview(); await loadGroups(); } catch (error) { status(error.message, "error"); } }); row.append(reconsider, include); root.append(row); });
  }
  function renderDirectSamples() {
    const root = $("styleGroupDirectSamples"); if (!root) return; root.replaceChildren(); state.directSamples.forEach((sample, index) => { const label = document.createElement("label"); label.className = "style-group-gallery-image style-group-sample-choice"; const input = document.createElement("input"); input.type = "checkbox"; input.checked = sample.selected !== false; input.addEventListener("change", () => { state.directSamples[index].selected = input.checked; $("styleGroupDirectImport").disabled = !state.directSamples.some((item) => item.selected !== false); }); const image = document.createElement("img"); image.src = sample.large_url || sample.preview_url || sample.url || ""; image.alt = state.directArtist + " " + (sample.id || index + 1); label.append(input, image); root.append(label); });
  }
  async function searchDirectArtist() { const artist = $("styleGroupDirectArtist").value.trim(); if (!artist) return status("작가명을 입력해 주세요.", "error"); try { const data = await json("/api/style-groups/danbooru/search", { method: "POST", body: JSON.stringify({ artist_tag: artist, sample_limit: 30 }) }); state.directArtist = artist; state.directSamples = (data.samples || []).map((sample) => Object.assign({}, sample, { selected: true })); $("styleGroupDirectImport").disabled = !state.directSamples.length; renderDirectSamples(); } catch (error) { status(error.message, "error"); } }
  async function importDirectSamples() { const samples = state.directSamples.filter((sample) => sample.selected !== false); if (!samples.length) return; try { state.group = await json("/api/style-groups/" + state.group.id + "/artists/import", { method: "POST", body: JSON.stringify({ artist_tag: state.directArtist, samples: samples, score: $("styleGroupDirectScore").value ? Number($("styleGroupDirectScore").value) : null }) }); closeModal("styleGroupDirectModal"); await openReview(state.group.id, state.directArtist); await loadGroups(); } catch (error) { status(error.message, "error"); } }

  async function startWizard() {
    try {
      const name = $("styleGroupName").value.trim(); const added = newTargetsOnly(state.selectedSources, state.editingGroup?.sources || []);
      if (!state.editingGroup && !name) throw new Error("그룹 이름을 입력해 주세요.");
      if (state.editingGroup) {
        const currentBaseKey = sourceKey(state.editingGroup.base_source?.source_type, state.editingGroup.base_source?.source_id);
        const baseChanged = Boolean(state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) !== currentBaseKey);
        if (!canStartGroupReview({ addingTo: true, selectedSources: added, referenceSelected: Boolean(state.reference), baseChanged })) throw new Error("새 출처, 새 기준 또는 기본 대상을 선택해 주세요.");
        if (added.length) await json("/api/style-groups/" + state.editingGroup.id + "/sources", { method: "POST", body: JSON.stringify({ sources: added }) });
        if (state.reference) await json("/api/style-groups/" + state.editingGroup.id + "/reference", { method: "POST", body: JSON.stringify(state.reference) });
        if (state.baseSource && sourceKey(state.baseSource.source_type, state.baseSource.source_id) !== sourceKey(state.editingGroup.base_source?.source_type, state.editingGroup.base_source?.source_id)) await json("/api/style-groups/" + state.editingGroup.id + "/base-source", { method: "PATCH", body: JSON.stringify(state.baseSource) });
        const id = state.editingGroup.id; closeWizard(); await loadGroups(); await openReview(id); return;
      }
      const group = await json("/api/style-groups", { method: "POST", body: JSON.stringify({ author_mode: true, name: name, sources: state.selectedSources, base_source: state.baseSource, reference: state.reference }) }); const id = group.id; closeWizard(); await loadGroups(); await openReview(id);
    } catch (error) { status(error.message, "error"); }
  }

  function bind() {
    $("styleGroupNew")?.addEventListener("click", () => openWizard());
    $("styleGroupCancelCreate")?.addEventListener("click", closeWizard); $("styleGroupWizardClose")?.addEventListener("click", closeWizard); $("styleGroupStart")?.addEventListener("click", startWizard);
    $("styleGroupChooseTargets")?.addEventListener("click", () => { renderTargetCards(false); openModal("styleGroupTargetModal"); }); $("styleGroupTargetClose")?.addEventListener("click", () => closeModal("styleGroupTargetModal")); $("styleGroupTargetDone")?.addEventListener("click", () => closeModal("styleGroupTargetModal")); $("styleGroupChooseReference")?.addEventListener("click", chooseReference); $("styleGroupChangeReference")?.addEventListener("click", chooseReference);
    $("styleGroupSourceGalleryClose")?.addEventListener("click", () => closeModal("styleGroupSourceGalleryModal")); $("styleGroupExcludedClose")?.addEventListener("click", () => closeModal("styleGroupExcludedModal")); $("styleGroupDirectClose")?.addEventListener("click", () => closeModal("styleGroupDirectModal")); $("styleGroupRemoveArtistClose")?.addEventListener("click", () => closeModal("styleGroupRemoveArtistModal")); $("styleGroupRemoveArtistCancel")?.addEventListener("click", () => closeModal("styleGroupRemoveArtistModal")); $("styleGroupRemoveArtistConfirm")?.addEventListener("click", confirmRemoveArtist);
    $("styleGroupClearReference")?.addEventListener("click", async () => { if (!state.group) return; try { state.group = await json("/api/style-groups/" + state.group.id, { method: "PATCH", body: JSON.stringify({ clear_reference: true }) }); renderReview(); await loadGroups(); } catch (error) { status(error.message, "error"); } });
    $("styleGroupReviewFocusToggle")?.addEventListener("click", () => { const expanded = $("styleGroupReviewFocusToggle").getAttribute("aria-expanded") === "true"; state.reviewFocusManualExpanded = !expanded; setReviewFocusExpanded(!expanded); }); $("styleGroupArtistSize")?.addEventListener("input", (event) => setArtistGallerySize(event.target.value)); $("styleGroupGalleryDanbooru")?.addEventListener("click", () => { closeModal("styleGroupSourceGalleryModal"); prepareDirectArtist(state.galleryArtistTag || state.galleryArtist); }); $("styleGroupGalleryNaiTest")?.addEventListener("click", generateIncludedArtistTest);
    $("styleGroupExcludedOpen")?.addEventListener("click", () => { renderExcluded(); openModal("styleGroupExcludedModal"); }); $("styleGroupExcludedSearch")?.addEventListener("input", renderExcluded); $("styleGroupDirectOpen")?.addEventListener("click", () => openModal("styleGroupDirectModal")); $("styleGroupDirectAdd")?.addEventListener("click", async () => { try { state.group = await json("/api/style-groups/" + state.group.id + "/artists", { method: "POST", body: JSON.stringify({ artist_tag: $("styleGroupDirectArtist").value }) }); closeModal("styleGroupDirectModal"); await openReview(state.group.id, $("styleGroupDirectArtist").value); await loadGroups(); } catch (error) { status(error.message, "error"); } }); $("styleGroupDirectSearch")?.addEventListener("click", searchDirectArtist); $("styleGroupDirectImport")?.addEventListener("click", importDirectSamples); $("styleGroupAddSource")?.addEventListener("click", () => openWizard(state.group));
    const directArtist = $("styleGroupDirectArtist"); if (directArtist) globalThis.promptTagAutocomplete?.bind?.(directArtist);
    $("styleGroupBack")?.addEventListener("click", () => { $("styleGroupReview")?.classList.add("hidden"); $("styleGroupGallery")?.classList.remove("hidden"); }); $("styleGroupPreviousSource")?.addEventListener("click", () => moveSource(-1)); $("styleGroupNextSource")?.addEventListener("click", () => moveSource(1)); $("styleGroupInclude")?.addEventListener("click", () => decideArtist(true)); $("styleGroupExclude")?.addEventListener("click", () => decideArtist(false)); $("styleGroupOpenArtistGallery")?.addEventListener("click", () => { const artist = state.review?.artist; if (artist) openIncludedGallery(artist.artist_key); });
    document.querySelectorAll("[data-style-group-close]").forEach((backdrop) => backdrop.addEventListener("click", (event) => { if (shouldCloseModalOnBackdrop(event)) closeModal({ wizard: "styleGroupWizardModal", targets: "styleGroupTargetModal", "source-gallery": "styleGroupSourceGalleryModal", excluded: "styleGroupExcludedModal", direct: "styleGroupDirectModal", "remove-artist": "styleGroupRemoveArtistModal" }[backdrop.dataset.styleGroupClose]); }));
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { ["styleGroupWizardModal", "styleGroupTargetModal", "styleGroupSourceGalleryModal", "styleGroupExcludedModal", "styleGroupDirectModal", "styleGroupRemoveArtistModal"].forEach(closeModal); return; } if ($("styleGroupReview")?.classList.contains("hidden")) return; const action = keyboardAction(event); if (!action) return; event.preventDefault(); if (action === "include") decideArtist(true); else if (action === "exclude") decideArtist(false); else moveSource(action === "previous" ? -1 : 1); });
    setArtistGallerySize($("styleGroupArtistSize")?.value || 240); document.querySelector('.tab[data-tab="style-group"]')?.addEventListener("click", () => loadGroups().catch((error) => status(error.message, "error"))); loadGroups().catch(() => {});
  }
  if (typeof document !== "undefined") { if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind, { once: true }); else bind(); }
  if (typeof module !== "undefined" && module.exports) module.exports = { normalizeArtistTag, sourceKey, sourceHasArtist, visibleSourcesForArtist, filterArtistGalleryImages, keyboardAction, newTargetsOnly, setTargetSelection, sourceGalleryHelp, targetCardKeyboardAction, canStartGroupReview, targetPriority, nextSourceIndex, baseSourceIndex, shouldCloseModalOnBackdrop, reviewFocusExpanded, artistGallerySizeValue, galleryImageLabel };
})();
