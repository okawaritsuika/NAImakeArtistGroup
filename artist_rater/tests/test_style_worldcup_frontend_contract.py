import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StyleWorldcupFrontendContractTests(unittest.TestCase):
    def test_template_has_labeled_form_and_separate_match_result_regions(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        ids = re.findall(r'\bid="([^"]+)"', template)
        self.assertEqual(len(ids), len(set(ids)))
        for element_id in (
            "style-worldcup-tab", "worldcupNew", "worldcupStatus", "worldcupForm", "worldcupList", "worldcupDetail",
            "worldcupName", "worldcupSize", "worldcupIncludeTags",
            "worldcupExcludeTags", "worldcupModel", "worldcupRecommendation", "worldcupStart", "worldcupStartBottom",
            "worldcupCandidateCount", "worldcupTitle", "worldcupProgress", "worldcupBack", "worldcupMatch", "worldcupResult", "worldcupHistory",
            "worldcupSizeSection", "worldcupSizeHelp",
            "worldcupIncludeTagsAutocomplete", "worldcupExcludeTagsAutocomplete",
            "worldcupRecommendationField", "worldcupCreateStatus", "worldcupCreateStatusBottom",
            "worldcupAutoSelect", "worldcupPicker", "worldcupPickerBody", "worldcupPickerVisibleCount", "worldcupPickerMarquee",
            "worldcupPickerSources", "worldcupPickerAllSource", "worldcupPickerSharedSource", "worldcupPickerConfirmedSource",
            "worldcupPickerMode", "worldcupPickerStatus", "worldcupPickerGrid", "worldcupPickerPrev",
            "worldcupPickerNext", "worldcupPickerPage", "worldcupPickerSelectionCount", "worldcupPickerClose",
            "worldcupPickerModel", "worldcupPickerCardSize", "worldcupPickerCardSizeValue",
            "worldcupPickerFilters", "worldcupPickerFilterApply", "worldcupPickerSort", "worldcupPickerCloseBottom",
            "worldcupGalleryLayout", "worldcupCandidateDetail", "worldcupCandidateDetailBack", "worldcupCandidateDetailTitle", "worldcupCandidateDetailStatus",
            "worldcupCandidateDetailMetadata", "worldcupCandidateDetailThumbnails", "worldcupCandidateDetailContent",
            "worldcupCandidateDetailImage", "worldcupCandidateDetailImageModel", "worldcupCandidateDetailBase", "worldcupCandidateDetailNegative", "worldcupCandidateDetailCharacters",
            "worldcupCandidateDetailPrev", "worldcupCandidateDetailNext", "worldcupCandidateDetailSize", "worldcupCandidateDetailSizeValue",
        ):
            self.assertIn(element_id, ids)
        for element_id in ("worldcupName", "worldcupSize", "worldcupIncludeTags", "worldcupExcludeTags", "worldcupModel", "worldcupRecommendation", "worldcupPickerCardSize", "worldcupCandidateDetailSize"):
            self.assertIn(f'for="{element_id}"', template)
        self.assertIn('role="status" aria-live="polite"', template)
        self.assertRegex(template, r'id="worldcupStart"[^>]+disabled')
        self.assertRegex(template, r'<details id="worldcupHistory"[^>]+hidden')
        self.assertIn("베이스 프롬프트", template)
        self.assertIn("네거티브·캐릭터 프롬프트는 사용하지 않습니다", template)

    def test_creation_form_contains_gallery_and_immediate_start_without_confirmation_step(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "style_worldcup.js").read_text(encoding="utf-8")
        picker = template[template.index('<section id="worldcupPicker"'):]
        form = re.search(r'<form id="worldcupForm"[^>]*>(.*?)</form>', picker, re.S).group(1)
        self.assertRegex(picker, r'<form id="worldcupForm"[^>]+novalidate')
        for element_id in ("worldcupName", "worldcupStart", "worldcupSize", "worldcupAutoSelect", "worldcupCandidateCount", "worldcupPickerSelectionCount", "worldcupPickerFilters", "worldcupPickerGrid", "worldcupStartBottom"):
            self.assertIn(f'id="{element_id}"', form)
        head = re.search(r'<div class="worldcup-create-head">(.*?)</div>', form, re.S).group(1)
        for element_id in ("worldcupPickerTitle", "worldcupName", "worldcupStart", "worldcupPickerClose"):
            self.assertIn(f'id="{element_id}"', head)
        for removed in ("worldcupPickerApply", "worldcupPickerApplyBottom", "worldcupSources", "worldcupSharedSource", "worldcupConfirmedSource", "worldcupPreview", "worldcupManualSelect", "worldcupSelectionSummary"):
            self.assertNotIn(f'id="{removed}"', template)
        self.assertNotIn('view !== "form"', source)
        self.assertNotIn('picker.draft', source)
        self.assertNotIn('showModal', source)
        self.assertNotIn('<dialog', template)
        self.assertIn('selection_scope: "all"', source)
        self.assertIn('selected_candidates: [...state.selection.keys()]', source)
        self.assertIn('$("worldcupPickerFilterApply").addEventListener("click", applyPickerFilters)', source)
        self.assertIn('후보 개수는 필터 적용 후 표시됩니다.', template)
        self.assertIn('id="worldcupPickerVisibleCount">필터 적용 전</p>', template)
        self.assertIn('event.target.id === "worldcupRecommendation"', source)
        for element_id in ("worldcupPickerAllSource", "worldcupPickerSharedSource", "worldcupPickerConfirmedSource"):
            self.assertRegex(template, rf'<button id="{element_id}"[^>]+type="button"[^>]+aria-pressed="(?:true|false)"')

    def test_creation_density_filters_counts_and_scroll_ownership(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        self.assertRegex(template, r'<section id="worldcupPickerFilters"[^>]+aria-labelledby="worldcupPickerFilterTitle"')
        self.assertNotRegex(template, r'<details id="worldcupPickerFilters"')
        for element_id in ("worldcupModel", "worldcupRecommendation", "worldcupIncludeTags", "worldcupExcludeTags"):
            self.assertEqual(template.count(f'id="{element_id}"'), 1)
        self.assertIn("추천수 N 이하 제외", template)
        self.assertIn("공유에만 적용 · 추천수 미상 제외", template)
        self.assertIn('class="worldcup-selection-bar"', template)
        self.assertIn('class="worldcup-selection-counts" role="status" aria-live="polite"', template)
        self.assertIn('id="worldcupPickerSelectionCount" class="worldcup-selected-badge"', template)
        self.assertIn('id="worldcupPickerVisibleCount"', template)
        self.assertIn('class="worldcup-auto-help"><summary>선택 안내</summary>', template)
        self.assertIn('class="worldcup-filter-guide"><summary>조건 안내</summary>', template)
        guide = re.search(r'<details class="worldcup-filter-guide">(.*?)</details>', template, re.S).group(1)
        for element_id in ("worldcupRecommendationHelp", "worldcupFilterHelp", "worldcupFilterExample"):
            self.assertIn(f'id="{element_id}"', guide)
        for removed_class in ("worldcup-create-start", "worldcup-create-summary", "worldcup-filter-guidance"):
            self.assertNotIn(removed_class, template)
            self.assertNotIn(removed_class, css)
        for element_id in ("worldcupIncludeTags", "worldcupExcludeTags"):
            self.assertRegex(template, rf'<textarea id="{element_id}"[^>]+rows="1"')
        for selector in ("worldcup-picker-page", "worldcup-picker-body"):
            rule = re.search(rf"\.{selector}\s*\{{([^}}]+)\}}", css).group(1)
            self.assertIn("overflow: visible", rule)
            self.assertNotIn("overflow-y: auto", rule)
        self.assertIn("grid-template-columns: auto minmax(200px, 420px) minmax(0, 1fr) auto auto", css)
        self.assertIn("grid-template-columns: minmax(150px, .85fr) minmax(140px, .75fr) minmax(160px, 1.25fr) minmax(160px, 1.25fr) auto auto", css)
        self.assertIn(".worldcup-create-form { display: grid; gap: 10px; }", css)
        self.assertIn(".worldcup-auto-size { width: 160px; }", css)
        self.assertIn(".worldcup-filter-grid textarea { min-height: 44px; height: 44px; }", css)
        self.assertIn("resize: vertical", css)
        self.assertIn(".worldcup-filter-guide[open] { grid-column: 1 / -1; margin-top: 0; }", css)
        self.assertNotIn("@media (min-width: 1100px)", css)
        narrow = css[css.index("@media (max-width: 900px)"):]
        self.assertIn(".worldcup-filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }", narrow)
        self.assertIn(".worldcup-filter-grid > button, .worldcup-filter-guide { margin-top: 0; }", narrow)
        self.assertIn(".worldcup-picker-size-field { grid-column: 1 / -1; }", narrow)
        mobile = css[css.index("@media (max-width: 700px)"):]
        self.assertIn(".worldcup-create-head > #worldcupPickerClose { grid-column: 2; grid-row: 1; }", mobile)
        self.assertIn(".worldcup-create-head > .worldcup-name-field { grid-column: 1 / -1; grid-row: 2; }", mobile)
        self.assertIn(".worldcup-create-head > #worldcupStart { grid-column: 1 / -1; grid-row: 3; }", mobile)
        self.assertNotIn(".worldcup-filter-grid", mobile)
        self.assertNotIn(".worldcup-picker-toolbar", mobile)
    def test_candidate_detail_is_gallery_side_panel_with_navigation_and_image_size(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "style_worldcup.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        form = re.search(r'<form id="worldcupForm"[^>]*>(.*?)</form>', template, re.S).group(1)
        self.assertIn('id="worldcupGalleryLayout" class="worldcup-gallery-layout" data-detail-open="false"', form)
        panel = re.search(r'<aside id="worldcupCandidateDetail"[^>]+aria-labelledby="worldcupCandidateDetailTitle"[^>]+hidden>(.*?)</aside>', form, re.S).group(1)
        self.assertLess(form.index('class="worldcup-gallery-results"'), form.index('id="worldcupPickerGrid"'))
        self.assertLess(form.index('id="worldcupPickerGrid"'), form.index('<aside id="worldcupCandidateDetail"'))
        self.assertIn('type="button">상세 닫기</button>', panel)
        for element_id in ("worldcupCandidateDetailBack", "worldcupCandidateDetailPrev", "worldcupCandidateDetailNext"):
            self.assertRegex(panel, rf'<button id="{element_id}"[^>]+type="button"')
        self.assertRegex(panel, r'id="worldcupCandidateDetailSize"[^>]+type="range"[^>]+min="40"[^>]+max="100"[^>]+step="10"[^>]+value="100"')
        self.assertIn('id="worldcupCandidateDetailSizeValue" for="worldcupCandidateDetailSize"', panel)
        self.assertLess(panel.index('class="worldcup-candidate-toolbar"'), panel.index('id="worldcupCandidateDetailImage"'))
        self.assertLess(panel.index('id="worldcupCandidateDetailImage"'), panel.index('id="worldcupCandidateDetailThumbnails"'))
        self.assertLess(panel.index('id="worldcupCandidateDetailThumbnails"'), panel.index('class="worldcup-candidate-prompts"'))
        self.assertNotIn('<details open', panel)
        self.assertIn('wrapper.append(card, detail)', source)
        self.assertIn('"worldcup-picker-detail"', source)
        self.assertIn('candidateDetail.token', source)
        self.assertIn('parts.map((part) => encodeURIComponent(part)).join("/")', source)
        self.assertIn('$("worldcupCandidateDetailBase").textContent', source)
        self.assertIn('$("worldcupCandidateDetailNegative").textContent', source)
        self.assertIn('$("worldcupCandidateDetailCharacters").textContent', source)
        self.assertIn('.worldcup-gallery-layout[data-detail-open="true"] { grid-template-columns: minmax(0, 1fr) minmax(320px, 38%); }', css)
        content = re.search(r'\.worldcup-candidate-content\s*\{([^}]+)\}', css).group(1)
        self.assertIn('grid-template-columns: minmax(0, 1fr)', content)
        self.assertIn('width: var(--worldcup-detail-image-size, 100%)', css)
        self.assertIn('max-height: 60dvh; object-fit: contain', css)
        self.assertIn('grid-template-columns: repeat(auto-fill, minmax(64px, 1fr))', css)
        self.assertIn('.worldcup-candidate-thumbnail .worldcup-image { height: 72px; object-fit: contain; }', css)
        narrow = css[css.index('@media (max-width: 900px)'):]
        drawer = re.search(r'\.worldcup-candidate-detail\s*\{([^}]+)\}', narrow).group(1)
        for declaration in ('position: fixed', 'right: 0', 'z-index: 80', 'width: min(100%, 420px)', 'height: 100dvh', 'overflow-y: auto', 'box-sizing: border-box'):
            self.assertIn(declaration, drawer)
        self.assertIn('.worldcup-candidate-head { position: sticky; top: -12px;', narrow)
        heading = re.search(r'\.worldcup-candidate-head h3\s*\{([^}]+)\}', css).group(1)
        self.assertIn('-webkit-line-clamp: 2', heading)
        self.assertIn('line-height: 1.4', heading)

    def test_model_filter_card_density_and_rectangle_selection_contract(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        source = (ROOT / "static" / "style_worldcup.js").read_text(encoding="utf-8")
        model_select = re.search(r'<select id="worldcupModel">(.*?)</select>', template).group(1)
        self.assertEqual(re.findall(r'<option value="([^"]+)"', model_select), [
            "all", "v5", "nai-diffusion-5-full-medium", "nai-diffusion-5-full", "nai-diffusion-5-curated",
            "v4.5", "nai-diffusion-4-5-full", "nai-diffusion-4-5-curated", "unknown",
        ])
        self.assertIn('model: $("worldcupModel").value || "all"', source)
        self.assertIn('$("worldcupModel").addEventListener("change", invalidateCount)', source)
        self.assertRegex(template, r'id="worldcupPickerCardSize"[^>]+type="range"[^>]+min="112"[^>]+max="240"[^>]+step="16"[^>]+value="160"')
        self.assertIn('id="worldcupPickerCardSizeValue" for="worldcupPickerCardSize"', template)
        self.assertIn('grid-template-columns: minmax(240px, 1.3fr) minmax(140px, .8fr) minmax(150px, .8fr) minmax(160px, 1fr)', css)
        self.assertIn('@media (max-width: 900px)', css)
        self.assertIn('.worldcup-picker-source-field { grid-column: 1 / -1; }', css)
        self.assertIn('flex: 1 1 0; padding: 8px 10px; border-width: 2px; font-size: 13px', css)
        self.assertIn('-webkit-line-clamp: 2', css)
        self.assertIn('text-overflow: ellipsis; white-space: nowrap', css)
        card = re.search(r'\.worldcup-picker-card\s*\{([^}]+)\}', css).group(1)
        self.assertIn('grid-template-rows: auto auto auto auto', card)
        meta = re.search(r'\.worldcup-picker-card-meta\s*\{([^}]+)\}', css).group(1)
        self.assertIn('grid-template-columns: auto minmax(0, 1fr) auto', meta)
        chip = re.search(r'\.worldcup-picker-chip\s*\{([^}]+)\}', css).group(1)
        for declaration in ('border: 1px', 'border-radius: 4px', 'padding: 2px 4px', 'font-size: 11px', 'line-height: 16px', 'text-overflow: ellipsis'):
            self.assertIn(declaration, chip)
        self.assertIn('PICKER_PAGE_SIZE = 60', source)
        self.assertIn('safeLocalImageUrl(participant?.thumbnail_url)', source)
        self.assertIn('image.decoding = "async"; image.draggable = false', source)
        self.assertIn('setPointerCapture(event.pointerId)', source)
        self.assertIn('doc.elementFromPoint(event.clientX, event.clientY)', source)
        self.assertIn('event.pointerType !== "mouse"', source)
        self.assertIn('baseline: new Map(state.selection)', source)
        self.assertIn('const intersects = cardRect.right', source)
        self.assertIn('state.selection = drag.baseline', source)
        self.assertIn('Math.min(bounds.width', source)
        self.assertRegex(template, r'id="worldcupPickerMarquee"[^>]+aria-hidden="true"[^>]+hidden')
        marquee = re.search(r"\.worldcup-picker-marquee\s*\{([^}]+)\}", css).group(1)
        self.assertIn("position: absolute", marquee)
        self.assertIn("pointer-events: none", marquee)
        self.assertIn("box-sizing: border-box", marquee)
        self.assertIn('.worldcup-picker-grid { position: relative;', css)
        self.assertNotIn('touch-action: none', css)
        for event_name in ('pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'lostpointercapture'):
            self.assertIn(f'addEventListener("{event_name}"', source)

    def test_unified_tags_use_shared_autocomplete_in_document_flow(self):
        template = (ROOT / "templates" / "style_worldcup.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "style_worldcup.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        for removed_id in ("worldcupIncludeArtists", "worldcupExcludeArtists"):
            self.assertNotIn(removed_id, template)
            self.assertNotIn(removed_id, source)
        for input_id in ("worldcupIncludeTags", "worldcupExcludeTags"):
            self.assertRegex(template, rf'<label class="field worldcup-field" for="{input_id}">')
            self.assertRegex(template, rf'<textarea id="{input_id}"[^>]+autocomplete="off"')
            self.assertIn(f'id="{input_id}Autocomplete" class="autocomplete prompt-tag-autocomplete hidden"', template)
        self.assertNotIn("data-autocomplete-category", template)
        self.assertIn("globalThis.promptTagAutocomplete?.bind?.($(id))", source)
        self.assertIn("globalThis.promptTagAutocomplete?.hide?.()", source)
        self.assertLess(source.index('FILTER_IDS.forEach((id) => $(id).addEventListener("input", invalidateCount))'), source.index("TAG_IDS.forEach((id) => globalThis.promptTagAutocomplete?.bind?.($(id)))"))
        self.assertNotIn("/api/tags/autocomplete", source)
        self.assertNotIn("include_artists:", source)
        self.assertNotIn("exclude_artists:", source)
        box = re.search(r"\.worldcup-field \.prompt-tag-autocomplete\s*\{([^}]+)\}", css).group(1)
        self.assertIn("position: static", box)
        self.assertIn("max-height: min(220px, 40dvh)", box)
        self.assertIn("min-width: 0", box)
        self.assertIn("overflow-y: auto", box)
        button = re.search(r"\.worldcup-field \.prompt-tag-autocomplete button\s*\{([^}]+)\}", css).group(1)
        self.assertIn("min-height: 44px", button)
        self.assertIn("white-space: normal", button)
        self.assertIn("overflow-wrap: anywhere", button)

    def test_folder_gallery_has_bounded_preview_grid_and_whole_card_button(self):
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        preview = re.search(r"\.worldcup-folder-preview\s*\{([^}]+)\}", css).group(1)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", preview)
        self.assertIn("grid-template-rows: repeat(2, minmax(0, 1fr))", preview)
        self.assertIn("aspect-ratio: 16 / 10", preview)
        self.assertIn("overflow: hidden", preview)
        self.assertIn(".worldcup-folder-open", css)
        self.assertIn(".worldcup-folder-preview > .worldcup-image-missing", css)

    def test_responsive_layout_has_one_scroll_owner_and_accessible_controls(self):
        shared_css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertRegex(shared_css, r"\.topbar \.tabs > button\s*\{[^}]*min-height: 44px")
        css = (ROOT / "static" / "style_worldcup.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn("repeat(auto-fill, minmax(min(100%, 260px), 1fr))", css)
        self.assertIn("min-width: 0", css)
        self.assertIn("min-height: 0", css)
        self.assertIn("object-fit: contain", css)
        self.assertIn("overflow-wrap: anywhere", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn(":focus-visible", css)
        without_overlays = re.sub(r"\.worldcup-(?:picker-marquee|candidate-detail)\s*\{[^}]+\}", "", css)
        self.assertNotRegex(without_overlays, r"position:\s*(?:absolute|fixed)")
        self.assertIn(".worldcup-view.active { overflow-x: hidden; overflow-y: auto; }", css)
        self.assertIn("@media (max-width: 1320px)", css)
        self.assertIn(".worldcup-view.active { height: auto; overflow: visible; }", css)
        mobile = css[css.index("@media (max-width: 700px)"):]
        self.assertIn(".worldcup-form-grid, .worldcup-match { grid-template-columns: 1fr; }", mobile)

    def test_data_is_rendered_as_text_and_prompt_details_are_outside_choice(self):
        source = (ROOT / "static" / "style_worldcup.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)
        self.assertIn('link.rel = "noopener noreferrer"', source)
        self.assertIn("safeLocalImageUrl(participant?.image_url)", source)
        self.assertIn("card.append(participantInfo(participant))", source)
        self.assertIn('$("worldcupHistory").open = false', source)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_node_behavior_suite(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(ROOT / "tests" / "style_worldcup_behavior.test.js")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
