import unittest
from html.parser import HTMLParser
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "templates" / "index.html"
JS_PATH = ROOT / "static" / "style_maker.js"
CSS_PATH = ROOT / "static" / "style.css"
BEHAVIOR_TEST_PATH = ROOT / "tests" / "style_maker_behavior.test.js"


class NestedWorkspacePanelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.in_style_maker = False
        self.nested_panels = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        is_workspace_panel = bool(classes & {"panel", "card"})
        if attributes.get("id") == "style-maker-tab":
            self.in_style_maker = True
        if self.in_style_maker and is_workspace_panel:
            if any(item[1] for item in self.stack):
                self.nested_panels.append(attributes.get("id") or tag)
        self.stack.append((tag, is_workspace_panel, attributes.get("id")))

    def handle_endtag(self, tag):
        while self.stack:
            opened_tag, _, opened_id = self.stack.pop()
            if opened_id == "style-maker-tab":
                self.in_style_maker = False
            if opened_tag == tag:
                break


class StyleFrontendContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.script = JS_PATH.read_text(encoding="utf-8")

    def test_maker_tab_workspace_and_script_exist(self):
        for marker in (
            'data-tab="style-maker"',
            'id="style-maker-tab"',
            'id="styleMakerSettings"',
            'id="styleMakerEditor"',
            'id="styleMakerGeneration"',
            "style_maker.js",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertTrue(JS_PATH.exists())

    def test_settings_controls_exist_with_required_defaults(self):
        for marker in (
            'id="styleArtistCount"',
            'value="12"',
            'id="styleScoreButtons"',
            'id="styleScoreAll"',
            'id="weightMode"',
            'value="random"',
            'value="balanced"',
            'value="profile"',
            'id="styleMinWeight"',
            'value="0.1"',
            'id="styleMaxWeight"',
            'value="2.3"',
            'id="preferHighScores"',
            'id="toggleStyleSettings"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_editor_and_generation_controls_exist(self):
        for marker in (
            'id="rerollStyleArtists"',
            'id="rerollStyleWeights"',
            'id="rerollStyleAll"',
            'id="sortStyleAsc"',
            'id="sortStyleDesc"',
            'id="weightGraph"',
            'id="artistPromptPreview"',
            'id="styleArtistSearch"',
            'id="styleArtistAutocomplete"',
            'id="styleArtistSelect"',
            'id="styleArtistPosition"',
            'id="styleArtistWeight"',
            'id="styleArtistList"',
            '가중치 표',
            '여기서도 바로 수정',
            'style-artist-row-head',
            'id="addStyleArtist"',
            'id="basePrompt"',
            'id="negativePrompt"',
            'id="characterPromptList"',
            'id="addCharacterPrompt"',
            'id="generationWidth"',
            'id="generationHeight"',
            'id="generationSampler"',
            'id="generationSteps"',
            'id="generationScale"',
            'id="generationCfgRescale"',
            'id="generateOne"',
            'id="latestStyleResult"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_weight_profile_uses_left_preview_and_editor_modal(self):
        for marker in (
            'id="weightGraphPreview"',
            'id="openWeightGraph"',
            'id="weightGraphModal"',
            'id="weightGraph"',
            'id="closeWeightGraph"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertLess(
            self.html.index('id="styleArtistList"'),
            self.html.index('id="latestStyleResult"'),
        )
        self.assertLess(
            self.html.index('id="styleArtistList"'),
            self.html.index('id="styleMakerEditor"'),
        )
        settings_start = self.html.index('id="styleMakerSettings"')
        editor_start = self.html.index('id="styleMakerEditor"')
        preview_index = self.html.index('id="weightGraphPreview"')
        result_index = self.html.index('id="latestStyleResult"')
        self.assertLess(settings_start, preview_index)
        self.assertLess(preview_index, editor_start)
        self.assertGreater(result_index, editor_start)
        self.assertLess(
            self.html.index('id="latestStyleResult"'),
            self.html.index('id="artistPromptPreview"'),
        )

    def test_style_settings_have_collapsible_groups_and_one_outer_scroll(self):
        self.assertNotIn('id="toggleStyleSettingsBody"', self.html)
        for label in ("작가 구성", "허용 평점", "가중치 설정", "가중치 표"):
            with self.subTest(label=label):
                self.assertIn(f"<summary>{label}</summary>", self.html)
        self.assertGreaterEqual(self.html.count('class="style-settings-section" open'), 3)
        self.assertIn(".style-settings-body", self.css)
        self.assertIn("overflow-y: auto", self.css)
        self.assertIn("scrollbar-gutter: stable", self.css)
        artist_list_start = self.css.index(".style-artist-list {")
        artist_list_end = self.css.index("}", artist_list_start)
        self.assertIn("overflow: visible", self.css[artist_list_start:artist_list_end])

    def test_weight_graph_edits_fixed_artists_as_overlays_not_bottom_table(self):
        overlay_start = self.script.index("function renderWeightGraphFixedArtistOverlays")
        overlay_end = self.script.index("function renderWeightGraph()", overlay_start)
        overlay_script = self.script[overlay_start:overlay_end]
        self.assertNotIn('id="weightGraphFixedArtistList"', self.html)
        self.assertNotIn('class="weight-graph-fixed-artists"', self.html)
        self.assertIn("function renderWeightGraphFixedArtistOverlays", self.script)
        self.assertIn("weight-fixed-artist-card", overlay_script)
        self.assertIn("const overlayEntries = entries.map", overlay_script)
        self.assertIn("occupiedLanes", overlay_script)
        self.assertIn("overlayEntries.forEach(({ artist: item, index, slot, stackIndex, visualStackIndex })", overlay_script)
        self.assertIn('dataTransfer.setData("application/x-fixed-style-artist"', overlay_script)
        self.assertIn('dataTransfer.setData("application/x-fixed-style-artists"', overlay_script)
        self.assertIn(".weight-fixed-artist-card", self.css)
        self.assertIn("position: absolute", self.css)
        self.assertIn("--fixed-card-x-offset", self.css)
        self.assertNotIn("translate(-50%, 50%)", self.css)
        self.assertIn("weight-fixed-drop-indicator", self.script)
        self.assertIn(".weight-fixed-drop-indicator", self.css)
        self.assertIn("weight-fixed-artist-select", self.script)
        self.assertIn(".weight-fixed-artist-card.selected", self.css)

    def test_fixed_artist_add_controls_prevent_label_overlap(self):
        self.assertIn(".artist-add-row .field > span", self.css)
        self.assertIn("white-space: nowrap", self.css)
        self.assertIn("text-overflow: ellipsis", self.css)
        self.assertIn(".style-editor-head .status", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)

    def test_latest_generation_result_keeps_large_preview_space(self):
        self.assertIn("grid-template-rows: auto auto minmax(420px, 1fr) auto", self.css)
        self.assertIn("min-height: 420px", self.css)
        self.assertIn("max-height: min(72vh, 820px)", self.css)

    def test_generation_result_metadata_includes_saved_parameters(self):
        script = JS_PATH.read_text(encoding="utf-8")
        for marker in ("result.sampler", "result.steps", "result.scale", "result.cfg_rescale"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_style_manager_supports_whole_style_deletion(self):
        script = JS_PATH.read_text(encoding="utf-8")
        for marker in (
            "그림체 삭제",
            "생성 이미지도 함께 삭제됩니다",
            'method: "DELETE"',
            "function deleteManagedStyle",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_compact_generation_parameter_panel_and_prompt_persistence_exist(self):
        for marker in (
            'id="generationParameters"',
            'id="toggleGenerationParameters"',
            'id="generationModel"',
            'id="generationResolutionPreset"',
            'id="generationScheduler"',
            'value="karras" selected',
            'id="generationScaleRange"',
            'id="generationCfgRescaleRange"',
            'id="generationSeed"',
            'id="generationSeedFixed"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        script = JS_PATH.read_text(encoding="utf-8")
        self.assertIn('naiArtistRater.prompts.v1', script)
        self.assertIn('localStorage.setItem', script)
        self.assertIn('localStorage.getItem', script)

    def test_prompt_token_editors_and_drag_groups_exist(self):
        for marker in (
            'class="prompt-workspace"',
            'id="basePromptTokens"',
            'id="negativePromptTokens"',
            'id="addPromptGroup"',
            'id="promptGroupList"',
            'class="prompt-control-groups"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        source = JS_PATH.read_text(encoding="utf-8")
        for marker in (
            'application/x-style-prompt-token',
            'function renderPromptTokens',
            'function renderPromptGroups',
            'function addPromptGroup',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_base_and_negative_prompts_use_tabs(self):
        for marker in (
            'class="prompt-tabs"',
            'role="tablist"',
            'id="basePromptTab"',
            'aria-controls="basePromptPanel"',
            'aria-selected="true"',
            'id="negativePromptTab"',
            'aria-controls="negativePromptPanel"',
            'id="basePromptPanel"',
            'id="negativePromptPanel"',
            'class="field prompt-editor negative hidden"',
            'id="togglePromptView"',
            '>텍스트 편집</button>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        source = JS_PATH.read_text(encoding="utf-8")
        self.assertIn("function selectPromptTab", source)
        self.assertIn("function setPromptViewMode", source)
        self.assertIn('setPromptViewMode("buttons")', source)

    def test_collected_prompt_presets_support_auto_and_fixed_modes(self):
        for marker in (
            'id="promptPresetMode"',
            '<option value="auto">자동 추천</option>',
            '<option value="fixed">수동 고정</option>',
            'id="promptPresetSelect"',
            'id="applyPromptPreset"',
            'id="promptPresetStatus"',
            'id="excludedPromptTags"',
            'id="excludedPromptTagList"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            'apiFetch("/api/style-maker/prompt-presets"',
            "function applyPromptPreset",
            "function refreshAutomaticPromptPreset",
            "function fixPromptPresetAfterManualEdit",
            "function restoreExcludedPromptTag",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_fixed_prompt_tags_follow_quality_and_are_kept_out_of_random_presets(self):
        self.assertIn('id="fixedPrompt"', self.html)
        self.assertIn('id="fixedPromptAutocomplete"', self.html)
        self.assertLess(self.html.index('id="basePrompt"'), self.html.index('id="fixedPrompt"'))
        self.assertIn('function updatePromptTagAutocomplete(input)', self.script)
        self.assertIn('function handlePromptTagAutocompleteKeydown(event)', self.script)
        self.assertIn('apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}`)', self.script)
        self.assertIn('styleElement("fixedPrompt")?.value', self.script)
        self.assertIn('combinePromptSections(', self.script)

    def test_all_prompt_textareas_use_danbooru_tag_autocomplete(self):
        for marker in (
            'id="basePromptAutocomplete"',
            'id="fixedPromptAutocomplete"',
            'id="negativePromptAutocomplete"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn('["basePrompt", "fixedPrompt", "negativePrompt"].forEach((id) => bindPromptTagAutocomplete', self.script)
        self.assertIn('autocomplete.className = "autocomplete prompt-tag-autocomplete hidden"', self.script)
        self.assertIn("bindPromptTagAutocomplete(input);", self.script)
        self.assertIn('Number(item?.category) === 1 ? `artist:${name}` : name', self.script)
        self.assertIn('fragment.replace(/^artist:/i, "")', self.script)

    def test_editor_script_exposes_state_and_required_operations(self):
        source = JS_PATH.read_text(encoding="utf-8")
        for marker in (
            "const styleState =",
            "allowedScores: new Set([1, 2, 3, 4, 5])",
            "customRanges: []",
            "async function loadStyleArtists",
            'apiFetch("/api/style-maker/artists"',
            "function buildStyleRequestPayload",
            "function renderWeightGraph",
            "function sortStyleArtists",
            "function swapStyleArtists",
            "function addStyleArtist",
            "function removeStyleArtist",
            "function validateCustomRanges",
            "function updateArtistPrompt",
            'addEventListener("dragstart"',
            'addEventListener("drop"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_workspace_uses_internal_scroll_and_responsive_grid(self):
        for marker in (
            ".style-maker-layout",
            "minmax(210px, 280px)",
            "minmax(0, 1fr)",
            "minmax(520px, 640px)",
            "overflow: auto",
            ".weight-column",
            "grid-template-columns: 1fr",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)

    def test_workspace_switches_before_the_981_to_1008_pixel_clipping_range(self):
        self.assertIn("@media (max-width: 1320px)", self.css)
        self.assertIn("grid-template-columns: minmax(210px, 280px) minmax(0, 1fr) minmax(520px, 640px)", self.css)
        self.assertIn("overflow-x: auto", self.css)

    def test_prompt_workspace_and_groups_have_responsive_styles(self):
        for marker in (
            ".prompt-workspace",
            ".prompt-token-surface",
            ".prompt-token-chip",
            ".prompt-control-group",
            ".prompt-group-drop-zone",
            ".prompt-group-item",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)

    def test_artist_tags_are_above_quality_tags_and_base_buttons_can_be_excluded(self):
        self.assertIn('id="artistPromptTokens"', self.html)
        self.assertLess(self.html.index('id="artistPromptTokens"'), self.html.index('id="basePromptTokens"'))
        self.assertIn("function excludeBasePromptToken", self.script)
        self.assertIn('chip.addEventListener("click", () => excludeBasePromptToken(token))', self.script)

    def test_score_and_drag_controls_expose_accessible_state(self):
        source = JS_PATH.read_text(encoding="utf-8")
        self.assertIn('button.setAttribute("aria-pressed"', source)
        self.assertIn("all.indeterminate =", source)
        self.assertIn('document.createElement("span")', source)
        self.assertNotIn('drag = document.createElement("button")', source)

    def test_pending_requests_disable_conflicting_style_controls(self):
        source = JS_PATH.read_text(encoding="utf-8")
        self.assertIn("requestToken: 0", source)
        self.assertIn("pending: false", source)
        self.assertIn("function setStyleRequestPending", source)
        for control_id in (
            "rerollStyleArtists",
            "rerollStyleWeights",
            "rerollStyleAll",
            "styleArtistCount",
            "sharedStyleArtistMin",
            "sharedStyleArtistMax",
            "styleScoreAll",
            "weightMode",
        ):
            with self.subTest(control_id=control_id):
                self.assertIn(f'"{control_id}"', source)

    def test_settings_continuous_generation_and_manager_controls_exist(self):
        source = JS_PATH.read_text(encoding="utf-8")
        for marker in (
            'id="settingsModal"', 'id="novelAiAppKey"', 'id="testNovelAiKey"',
            'id="generationLimitMode"', 'id="generationCount"',
            'id="sharedStyleArtistMin"', 'id="sharedStyleArtistMax"',
            'data-random-target="artists"', 'data-random-target="weights"',
            'data-random-target="quality"', 'data-random-target="negative"',
            'id="startContinuous"', 'id="pauseContinuous"', 'id="stopContinuous"',
            'data-tab="style-manager"', 'id="styleManagerList"', 'id="styleManagerDetail"',
            'id="generatedImageModal"', 'id="generatedImagePrev"', 'id="generatedImageNext"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn("async function runContinuousGeneration()", source)
        self.assertIn("async function randomizeSelectedStyleParts()", source)
        self.assertIn("async function randomizePromptTargets(targets)", source)
        self.assertIn("async function generateOneRandomizedStyle()", source)
        self.assertIn('styleElement("generateOne")?.addEventListener("click", () => generateOneRandomizedStyle()', source)
        self.assertIn("await generateCurrentStyle()", source)
        self.assertIn("async function loadStyleManager()", source)
        self.assertIn("function renderGeneratedImageModal()", source)

    def test_single_generation_randomizes_enabled_targets_before_generation(self):
        start = self.script.index("async function generateOneRandomizedStyle()")
        end = self.script.index("async function runContinuousGeneration()", start)
        function_source = self.script[start:end]
        self.assertLess(
            function_source.index("await randomizeSelectedStyleParts();"),
            function_source.index("return generateCurrentStyle();"),
        )

    def test_workspace_does_not_nest_panels_or_cards(self):
        parser = NestedWorkspacePanelParser()
        parser.feed(self.html)
        self.assertEqual([], parser.nested_panels)

    def test_style_editor_behavior_with_node(self):
        result = subprocess.run(
            ["node", "--test", str(BEHAVIOR_TEST_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
