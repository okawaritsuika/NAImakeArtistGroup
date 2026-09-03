import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NaiArtistTestFrontendContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.js = (ROOT / "static" / "nai_artist_test.js").read_text(encoding="utf-8")

    def test_screen_exposes_marker_settings_selection_and_resume_controls(self):
        for value in (
            'id="naiArtistTestResultCardSize"', 'id="naiArtistTestArtistHistoryCardSize"',
            'data-tab="nai-artist-test"', 'id="nai-artist-test-tab"', 'id="naiArtistTestListView"', 'id="naiArtistTestEditorView"', 'id="naiArtistTestDetailView"',
            'id="naiArtistTestAdd"', 'id="naiArtistTestBackToList"', 'id="naiArtistTestBackFromDetail"', 'id="naiArtistTestBasePrompt"',
            'id="naiArtistTestScoreMin"', 'id="naiArtistTestScoreMax"', 'id="naiArtistTestImagesPerArtist"',
            'id="naiArtistTestArtistSort"', 'id="naiArtistTestArtistToolbar"', 'id="naiArtistTestArtists"', 'id="naiArtistTestSelectionCount"', 'id="naiArtistTestSelectAll"', 'id="naiArtistTestClearSelection"', 'id="naiArtistTestDelay"', 'id="naiArtistTestGenerateOne"', 'id="naiArtistTestStart"', 'id="naiArtistTestPause"', 'id="naiArtistTestCancel"', 'class="nai-artist-test-generate-actions"', 'class="nai-artist-test-head-copy"', 'nai-artist-test-head-actions', 'class="nai-artist-test-filter-fields"', 'class="nai-artist-test-selection-actions"', 'class="nai-artist-test-session-actions"', 'class="nai-artist-test-danger-actions"',
            'id="naiArtistTestCurrent"', 'id="naiArtistTestCustomResolution"', 'id="naiArtistTestArtistPreview"', 'id="naiArtistTestPreviewImage"', 'id="naiArtistTestPreviewPrevious"', 'id="naiArtistTestPreviewNext"', 'id="naiArtistTestPreviewCounter"', 'id="naiArtistTestSettingsToggle"', 'id="naiArtistTestSettingsBody"', 'id="naiArtistTestWorkspace"', 'id="naiArtistTestWorkspaceToggle"', 'id="naiArtistTestCurrentImage"', 'id="naiArtistTestRatingButtons"', 'id="naiArtistTestItemSettings"', 'id="naiArtistTestPromptTabs"', 'id="naiArtistTestAppendOpen"', 'id="naiArtistTestResultArtistFilter"', 'id="naiArtistTestResultScoreFilter"', 'id="naiArtistTestImageModal"', 'id="naiArtistTestImageModalClose"', 'id="naiArtistTestImageModalPrevious"', 'id="naiArtistTestImageModalNext"', 'id="naiArtistTestImageModalImage"', 'id="naiArtistTestImageModalMeta"', 'id="naiArtistTestTestMode"', 'id="naiArtistTestArtistMode"', 'id="naiArtistTestArtistSummaries"', 'id="naiArtistTestArtistDetailView"', 'id="naiArtistTestHistoryArtistSearch"', 'id="naiArtistTestAddPrompt"', 'id="naiArtistTestPromptVariants"', 'id="naiArtistTestUsagePreflight"', 'id="naiArtistTestAppendModal"', 'id="naiArtistTestAppendModalClose"', 'id="naiArtistTestAppendCancel"', 'id="naiArtistTestAppendPrompt"', 'id="naiArtistTestAppendCount"', 'id="naiArtistTestAppendEstimate"', 'id="naiArtistTestAppendSubmit"', 'id="naiArtistTestStartModal"', 'id="naiArtistTestStartWarningEyebrow"', 'id="naiArtistTestStartWarningTitle"', 'id="naiArtistTestStartWarningDescription"', 'id="naiArtistTestStartMetricPending"', 'id="naiArtistTestStartMetricDelay"', 'id="naiArtistTestStartMetricUsage"', 'id="naiArtistTestStartMetricExpected"', 'id="naiArtistTestStartMetricAfter"', 'id="naiArtistTestStartWarningAmber"', 'id="naiArtistTestStartWarningDanger"', 'id="naiArtistTestStartConfirm"', 'id="naiArtistTestStartCancel"', 'id="naiArtistTestAnlasModal"', 'id="naiArtistTestAnlasReason"', 'id="naiArtistTestAnlasConfirm"', 'id="naiArtistTestAnlasCancel"', 'id="naiArtistTestDeleteModal"', 'id="naiArtistTestDeleteName"', 'id="naiArtistTestDeleteConfirm"', 'id="naiArtistTestDeleteCancel"', 'id="naiArtistTestDeleteDetail"', 'data-state="pending"', 'data-prompt-variant', 'nai_artist_test.js',
        ):
            self.assertIn(value, self.html)
        self.assertIn("{{ '{{artist}}' }}", self.html)
        self.assertIn("남은 이미지 한꺼번에 생성", self.html)
        self.assertIn("다음 이미지 1장 생성", self.html)
        self.assertIn("모든 생성이 끝난 뒤 이미지 평가가 열립니다.", self.html)
        self.assertIn("BATCH GENERATION", self.html)
        self.assertIn("SINGLE GENERATION", self.js)
        self.assertIn("ANLAS WARNING", self.html)
        self.assertIn("PROMPT VARIANT", self.html)
        self.assertIn("DELETE TEST", self.html)
        self.assertIn('<fieldset class="nai-artist-test-scope-fieldset"><legend>생성 대상</legend>', self.html)
        self.assertIn('value="all"', self.html)
        self.assertIn('value="remaining"', self.html)
        self.assertIn("전체 작가", self.html)
        self.assertIn("이 테스트에 포함된 모든 작가에 새 프롬프트를 추가합니다.", self.html)
        self.assertIn("미생성 항목이 남은 작가만", self.html)
        self.assertIn("아직 생성할 항목이 남아 있는 작가에만 추가합니다.", self.html)
        self.assertIn("naiArtistTestAppendCancel", self.html)
        self.assertIn('class="nai-artist-test-artist-gallery"', self.html)
        self.assertIn('id="naiArtistTestArtistToolbar"', self.html.split('id="naiArtistTestSelectionCount"', 1)[0])
        self.assertIn('class="nai-artist-test-filter-fields"', self.html)
        self.assertIn('class="nai-artist-test-selection-actions"', self.html)
        self.assertNotIn('id="naiArtistTestQualityPrompt"', self.html)
        self.assertIn('quality_prompt: ""', self.js)
        self.assertIn('original_quality_prompt: ""', self.js)
        self.assertNotIn('id="naiArtistTestLeadingPrompt"', self.html)
        self.assertNotIn('id="naiArtistTestFixedPrompt"', self.html)
        self.assertNotIn('<details id="naiArtistTestAppendPanel"', self.html)
        self.assertNotIn("naiArtistTestLeadingPrompt", self.js)
        self.assertNotIn("naiArtistTestFixedPrompt", self.js)
        nai_section = self.html.split('id="nai-artist-test-tab"', 1)[1].split('id="style-maker-tab"', 1)[0]
        self.assertNotIn('input type="checkbox"', nai_section)
        self.assertNotIn('naiArtistTestAddSelected', nai_section)
        self.assertNotIn('naiArtistTestSelectedArtists', nai_section)

    def test_prompt_inputs_have_field_local_autocomplete_boxes(self):
        for input_id in (
            "naiArtistTestBasePrompt",
            "naiArtistTestNegativePrompt",
            "naiArtistTestCharacterPrompts",
            "naiArtistTestAppendPrompt",
        ):
            match = re.search(
                rf'<label class="field">(?:(?!</label>).)*id="{input_id}"(?:(?!</label>).)*class="autocomplete prompt-tag-autocomplete hidden"',
                self.html,
                re.S,
            )
            self.assertIsNotNone(match, input_id)
        self.assertIn("bindNaiArtistTestPromptInputs();", self.js)
        self.assertIn("globalThis.promptTagAutocomplete?.bind(input)", self.js)
        self.assertIn('autocomplete.className = "autocomplete prompt-tag-autocomplete hidden"', self.js)
        self.assertIn("bindNaiArtistTestPromptAutocomplete(prompt)", self.js)
        self.assertIn('artistMarkerCount(variant.prompt) !== 1', self.js)

    def test_small_viewport_keeps_progress_actions_visible(self):
        self.assertIn("#naiArtistTestEditorView .nai-artist-test-view-head", self.css)
        self.assertIn("#naiArtistTestDetailView .nai-artist-test-view-head", self.css)
        self.assertIn(".nai-artist-test-head-actions", self.css)
        self.assertIn(".nai-artist-test-filter-fields", self.css)
        self.assertIn(".nai-artist-test-selection-actions", self.css)
        self.assertIn(".nai-artist-test-session-actions", self.css)
        self.assertIn(".nai-artist-test-danger-actions", self.css)
        self.assertIn(".nai-artist-test-dialog", self.css)
        self.assertIn(".nai-artist-test-dialog-panel.is-warning", self.css)
        self.assertIn(".nai-artist-test-dialog-panel.is-prompt", self.css)
        self.assertIn(".nai-artist-test-dialog-panel.is-danger", self.css)
        self.assertIn(".nai-artist-test-dialog-body", self.css)
        self.assertIn(".nai-artist-test-scope-option:has(input:checked)", self.css)
        self.assertIn(".nai-artist-test-generate-actions", self.css)
        self.assertIn("min-height: 44px", self.css)
        self.assertIn("max-height: calc(100vh - 16px)", self.css)
        self.assertIn("overflow: auto", self.css)
        self.assertIn(".nai-artist-test-delete", self.css)
        self.assertIn(".nai-artist-test-batch-open", self.css)
        self.assertIn("position: sticky", self.css)
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertIn("grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.75fr)", self.css)
        self.assertIn(".nai-artist-test-marquee", self.css)
        self.assertIn("user-select: none", self.css)
        self.assertIn("-webkit-user-drag: none", self.css)
        self.assertIn("overflow-x: hidden", self.css)
        self.assertIn("completed_count", self.js)
        self.assertIn("remaining_count", self.js)
        self.assertIn("저장된 테스트가 없습니다", self.js)
        self.assertIn("setTimeout(loadArtists, 250)", self.js)
        self.assertIn("aria-pressed", self.js)
        self.assertIn("pointerdown", self.js)
        self.assertIn("marqueeSelectedArtistKeys", self.js)
        self.assertIn("marqueeAutoScrollDelta", self.js)
        self.assertIn("requestAnimationFrame", self.js)
        self.assertIn("cancelAnimationFrame", self.js)
        self.assertIn("mergeArtistSelections", self.js)
        self.assertIn("rating_id", self.js)
        self.assertIn("activeAwaitingItem", self.js)
        self.assertIn("preferredInteractiveItem", self.js)
        self.assertIn("remainingDelayMs", self.js)
        self.assertIn("filterNaiArtistTestResults", self.js)
        self.assertIn("promptVariantTabs", self.js)
        self.assertIn("resultPromptIndex", self.js)
        self.assertIn("startWarningSummary", self.js)
        self.assertIn("주의사항을 확인하고 한꺼번에 생성", self.html)
        self.assertIn("data-nai-artist-test-start-close", self.html)
        self.assertIn("data-nai-artist-test-append-close", self.html)
        self.assertIn("cycleResultViewerIndex", self.js)
        self.assertIn("runGenerationLoop", self.js)
        self.assertIn("generationEvaluationReady", self.js)
        self.assertNotIn("waitForNextImage", self.js)
        self.assertIn("prompt_variants", self.js)
        self.assertIn("/api/nai-artist-tests/artist-history", self.js)
        self.assertIn("workspaceExpanded", self.js)
        self.assertIn("data-nai-artist-test-modal-close", self.html)
        self.assertIn("Escape", self.js)
        self.assertIn("ArrowLeft", self.js)
        self.assertIn("ArrowRight", self.js)
        self.assertIn("generation_requested_at", self.js)
        self.assertIn("/items/${item.id}/rating", self.js)
        self.assertNotIn("while (!state.stopRequested)", self.js)
        self.assertNotIn("nai-artist-test-result-artist select", self.js)
        self.assertIn("각 이미지 점수의 평균", self.html)
        self.assertIn("테스트 완료", self.js)
        self.assertIn("aria-expanded=\"true\"", self.html)
        self.assertIn(".nai-artist-test-target-browser", self.css)
        self.assertIn("min-height: 40px", self.css)
        self.assertIn(".nai-artist-test-editor-layout.settings-collapsed", self.css)
        self.assertIn("writing-mode: vertical-rl", self.css)
        self.assertIn("button.title", self.js)
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertIn(".nai-artist-test-image-modal", self.css)
        self.assertIn(".nai-artist-test-image-modal.hidden", self.css)
        self.assertIn(".nai-artist-test-image-modal-stage", self.css)
        self.assertIn(".nai-artist-test-image-modal-meta", self.css)
        self.assertIn(".nai-artist-test-workspace-head", self.css)
        self.assertIn('id="naiArtistTestWorkspaceHead"', self.html)
        self.assertIn('const workspaceHead = $("naiArtistTestWorkspaceHead")', self.js)
        self.assertIn('document.querySelector("#naiArtistTestDetailView .nai-artist-test-workspace-head")', self.js)
        self.assertIn('workspaceHead.classList.toggle("is-collapsed", !expanded)', self.js)
        self.assertIn('const detailView = $("naiArtistTestDetailView")', self.js)
        self.assertIn('detailView?.classList.toggle("is-workspace-collapsed", !expanded)', self.js)
        self.assertIn('["naiArtistTestDetailStatus", "naiArtistTestCurrent", "naiArtistTestUsagePreflight"]', self.js)
        self.assertIn('summary.hidden = !expanded', self.js)
        self.assertIn('summary.classList.toggle("is-workspace-collapsed", !expanded)', self.js)
        self.assertIn(".nai-artist-test-workspace-head.is-collapsed", self.css)
        collapsed_head = re.search(r"\.nai-artist-test-workspace-head\.is-collapsed \{(?P<body>.*?)\}", self.css, re.S)
        self.assertIsNotNone(collapsed_head)
        self.assertIn("height: auto", collapsed_head.group("body"))
        self.assertIn("min-height: 44px", collapsed_head.group("body"))
        self.assertNotIn("height: 0", collapsed_head.group("body"))
        self.assertIn(".nai-artist-test-workspace.is-collapsed + .nai-artist-test-history-head", self.css)
        self.assertIn("#naiArtistTestDetailStatus.is-workspace-collapsed", self.css)
        self.assertIn("#naiArtistTestCurrent.is-workspace-collapsed", self.css)
        self.assertIn("#naiArtistTestUsagePreflight.is-workspace-collapsed", self.css)
        self.assertIn("#naiArtistTestDetailView.is-workspace-collapsed .nai-artist-test-results", self.css)
        self.assertIn("max-height: none", self.css)
        self.assertIn("overflow: visible", self.css)
        self.assertIn(".nai-artist-test-workspace-head.is-collapsed > div", self.css)
        collapsed_button = re.search(r"\.nai-artist-test-workspace-head\.is-collapsed button\s*\{(?P<body>.*?)\}", self.css, re.S)
        self.assertIsNotNone(collapsed_button)
        self.assertIn("position: static", collapsed_button.group("body"))
        self.assertNotIn("position: absolute", collapsed_button.group("body"))
        self.assertIn(".nai-artist-test-batch-list", self.css)
        self.assertIn(".nai-artist-test-artist-summary-grid", self.css)
        self.assertIn("display: none !important", self.css)
        self.assertIn("#naiArtistTestDetailView .nai-artist-test-view-head {\n  position: static", self.css)
        self.assertIn(".nai-artist-test-workspace[hidden]", self.css)
        self.assertIn("appendTargetArtists", self.js)
        self.assertIn("/api/nai-artist-tests/${state.selectedTest.id}/append", self.js)
        self.assertIn("/api/settings/novelai/test", self.js)
        self.assertIn("FULL_CAPACITY_IMAGES", self.js)
        self.assertIn("usageEstimateForConfig", self.js)
        self.assertIn("Usage 환산 대상 아님", self.js)
        self.assertIn("state.running = true; state.stopRequested = false; renderDetailControls();", self.js)
        self.assertIn("startActive", self.js)
        self.assertIn("pauseActive", self.js)
        self.assertIn("dataset.state", self.js)
        self.assertIn("Anlas가 사용될 수 있음", self.js)
        self.assertIn('#naiArtistTestDetailStatus[data-state="running"]', self.css)
        self.assertIn("deleteConfirmationMessage", self.js)
        self.assertIn('method: "DELETE"', self.js)
        self.assertIn("window.confirm", self.js)
        self.assertIn("stopPropagation", self.js)

    def test_list_navigation_actions_are_in_header_action_regions(self):
        editor_start = self.html.index('id="naiArtistTestEditorView"')
        editor_end = self.html.index('id="naiArtistTestStatus"', editor_start)
        editor_head = self.html[editor_start:editor_end]
        editor_actions_start = editor_head.index('class="toolbar nai-artist-test-head-actions"')
        self.assertNotIn('id="naiArtistTestBackToList"', editor_head[:editor_actions_start])
        editor_actions = editor_head[editor_actions_start:]
        self.assertIn('id="naiArtistTestBackToList"', editor_actions)
        self.assertIn('id="naiArtistTestCreate"', editor_actions)

        detail_start = self.html.index('id="naiArtistTestDetailView"')
        detail_end = self.html.index('id="naiArtistTestDetailStatus"', detail_start)
        detail_head = self.html[detail_start:detail_end]
        detail_actions_start = detail_head.index('class="toolbar nai-artist-test-detail-actions"')
        self.assertNotIn('id="naiArtistTestBackFromDetail"', detail_head[:detail_actions_start])
        self.assertIn('id="naiArtistTestBackFromDetail"', detail_head[detail_actions_start:])

        artist_detail_start = self.html.index('id="naiArtistTestArtistDetailView"')
        artist_detail_end = self.html.index('id="naiArtistTestArtistHistoryCardSize"', artist_detail_start)
        artist_detail_head = self.html[artist_detail_start:artist_detail_end]
        section_actions_start = artist_detail_head.index('class="nai-artist-test-section-actions"')
        self.assertNotIn('id="naiArtistTestBackFromArtistDetail"', artist_detail_head[:section_actions_start])
        self.assertIn('id="naiArtistTestBackFromArtistDetail"', artist_detail_head[section_actions_start:])

    def test_current_image_stage_does_not_reserve_black_placeholder_space(self):
        stage = re.search(r"\.nai-artist-test-current-image \{(?P<body>.*?)\}", self.css, re.S)
        image = re.search(r"\.nai-artist-test-current-image img \{(?P<body>.*?)\}", self.css, re.S)
        self.assertIsNotNone(stage)
        self.assertIsNotNone(image)
        self.assertIn("min-height: 0", stage.group("body"))
        self.assertIn("background: transparent", stage.group("body"))
        self.assertIn("width: auto", image.group("body"))
        self.assertIn("max-width: 100%", image.group("body"))
        self.assertIn("height: auto", image.group("body"))

    def test_image_history_galleries_share_persisted_card_size_controls(self):
        for value in ("small", "medium", "large"):
            self.assertIn(f'value="{value}"', self.html)
        self.assertIn('id="naiArtistTestResults" class="nai-artist-test-results"', self.html)
        self.assertIn('id="naiArtistTestArtistHistoryResults" class="nai-artist-test-results"', self.html)
        self.assertIn('const NAI_ARTIST_TEST_CARD_SIZE_KEY = "naiArtistRater.naiArtistTestCardSize.v1"', self.js)
        self.assertIn('localStorage.getItem(NAI_ARTIST_TEST_CARD_SIZE_KEY)', self.js)
        self.assertIn('localStorage.setItem(NAI_ARTIST_TEST_CARD_SIZE_KEY, size)', self.js)
        self.assertIn('"naiArtistTestResults", "naiArtistTestArtistHistoryResults"', self.js)
        self.assertIn('"naiArtistTestResultCardSize", "naiArtistTestArtistHistoryCardSize"', self.js)
        self.assertIn('data-card-size', self.js)
        self.assertIn('--nai-artist-test-card-min: 170px', self.css)
        self.assertIn('.nai-artist-test-results[data-card-size="small"]', self.css)
        self.assertIn('.nai-artist-test-results[data-card-size="large"]', self.css)
        self.assertIn('.nai-artist-test-history-toolbar .field', self.css)

    def test_headers_and_editor_actions_have_explicit_hierarchy(self):
        section = self.html.split('id="nai-artist-test-tab"', 1)[1].split('id="style-maker-tab"', 1)[0]
        self.assertLess(section.index('class="nai-artist-test-head-copy"'), section.index('id="naiArtistTestAdd"'))
        self.assertLess(section.index('class="nai-artist-test-filter-fields"'), section.index('class="nai-artist-test-selection-actions"'))
        self.assertLess(section.index('class="nai-artist-test-generate-actions"'), section.index('class="nai-artist-test-session-actions"'))
        self.assertLess(section.index('class="nai-artist-test-session-actions"'), section.index('class="nai-artist-test-danger-actions"'))
        mobile_css = self.css[self.css.index('@media (max-width: 900px)'):]
        self.assertIn('.nai-artist-test-filter-fields {\n    grid-template-columns: repeat(2, minmax(0, 1fr));', mobile_css)
        self.assertIn('.nai-artist-test-view button {\n    min-height: 44px;', mobile_css)


if __name__ == "__main__":
    unittest.main()
