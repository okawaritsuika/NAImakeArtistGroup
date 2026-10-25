import unittest
import re
from html.parser import HTMLParser
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "templates" / "index.html"
JS_PATH = ROOT / "static" / "style_maker.js"
CSS_PATH = ROOT / "static" / "style.css"
BEHAVIOR_TEST_PATH = ROOT / "tests" / "style_maker_behavior.test.js"
GRAPH_BEHAVIOR_TEST_PATH = ROOT / "tests" / "style_weight_graph_behavior.test.js"


class ElementContractParser(HTMLParser):
    """Track actual ancestry so moved controls remain covered across modal layouts."""
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__()
        self.stack = []
        self.by_id = {}
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parents": self.stack[:], "text": ""}
        self.nodes.append(node)
        element_id = node["attrs"].get("id")
        if element_id:
            if element_id in self.by_id:
                raise AssertionError(f"Duplicate DOM id: {element_id}")
            self.by_id[element_id] = node
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"] += data

    def ancestor_ids(self, element_id):
        return [node["attrs"].get("id") for node in self.by_id[element_id]["parents"]]


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
    def test_fixed_only_random_selection_control_is_in_artist_conditions(self):
        dom = ElementContractParser(self.html)
        self.assertIn("styleArtistsPanel", dom.ancestor_ids("styleFixedArtistsOnly"))
        self.assertIn("고정 작가에서만 랜덤 선택", dom.by_id["styleArtistsPanel"]["text"])
        self.assertRegex(self.css, r"\.style-fixed-artists-only\s*\{[^}]*min-height:\s*44px")

    def test_confirmed_setting_choices_match_generation_controls_and_keep_unknown(self):
        for confirmed, generation in (
            ("confirmedStyleSampler", "generationSampler"),
            ("confirmedStyleScheduler", "generationScheduler"),
        ):
            def choices(element_id):
                select = re.search(r'<select id="' + element_id + r'"[^>]*>(.*?)</select>', self.html, re.S)
                self.assertIsNotNone(select, element_id)
                return re.findall(r'<option value="([^"]*)"', select.group(1))
            self.assertEqual(choices(confirmed), [""] + choices(generation))
        for field, bounds in (
            ("confirmedStyleSteps", ('min="1"', 'max="50"', 'step="1"')),
            ("confirmedStyleScale", ('min="0"', 'max="10"', 'step="0.1"')),
            ("confirmedStyleCfgRescale", ('min="0"', 'max="1"', 'step="0.01"')),
        ):
            control = re.search(r'<input id="' + field + r'"[^>]*>', self.html).group(0)
            for bound in bounds:
                self.assertIn(bound, control)

    def test_confirmed_settings_keep_footer_outside_scroll_and_stack_on_small_screens(self):
        dialog = self.css.split(".confirmed-style-dialog {", 1)[1].split("}", 1)[0]
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto auto", dialog)
        self.assertIn("100dvh", dialog)
        responsive = self.css.split("@media (max-width: 1050px)", 1)[1]
        self.assertIn("grid-auto-rows: max-content", responsive)
        self.assertIn(".confirmed-style-image-scroller {\n    overflow: visible", responsive)
        mobile = self.css.split("@media (max-width: 760px)", 1)[1]
        self.assertIn(".confirmed-style-settings-grid {\n    grid-template-columns: 1fr", mobile)
        self.assertIn(".confirmed-style-dialog > .modal-actions", mobile)

    def test_medium_model_controls_have_wrapping_hint_and_full_width_model_row(self):
        self.assertIn('value="nai-diffusion-5-full-medium"', self.html)
        self.assertIn('id="generationMediumHint"', self.html)
        self.assertIn('id="comparisonMediumHint"', self.html)
        self.assertIn('.generation-parameters-body > .model-parameter-row {\n  grid-column: 1 / -1;', self.css)
        self.assertIn('overflow-wrap: anywhere;', self.css)

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

    def test_artist_source_picker_contract_uses_safe_dom_and_responsive_modal(self):
        for marker in (
            'id="styleArtistSourceOpen"',
            'aria-haspopup="dialog"',
            'aria-controls="styleArtistSourceModal"',
            'id="styleArtistSourceCount"',
            'id="styleArtistSourceSummary"',
            'id="styleArtistSourceModal"',
            'hidden',
            'role="dialog"',
            'aria-modal="true"',
            'aria-labelledby="styleArtistSourceTitle"',
            'id="styleArtistSourceTitle"',
            'id="styleArtistSourceClose"',
            'id="styleArtistSourceSearch"',
            'id="styleArtistSourceDraftSummary"',
            'id="styleArtistSourceList"',
            'id="styleArtistSourceDetail"',
            'id="styleArtistSourceDetailEmpty"',
            'id="styleArtistSourceDetailHeader"',
            'id="styleArtistSourceDetailMeta"',
            'id="styleArtistSourceArtistSearch"',
            'id="styleArtistSourceArtistList"',
            'id="styleArtistSourcePromptSection"',
            'id="styleArtistSourcePromptList"',
            'id="styleArtistSourceCancel"',
            'id="styleArtistSourceApply"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

        for marker in (
            'styleElement("styleArtistSourceOpen")?.addEventListener',
            'styleElement("styleArtistSourceApply")?.addEventListener',
            'styleElement("styleArtistSourceSearch")?.addEventListener',
            'styleElement("styleArtistSourceArtistSearch")?.addEventListener',
            'data-close-style-artist-source',
            'function toggleArtistSource',
            'function loadArtistSourceDetail',
            'textContent =',
            'createElement',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

        self.assertNotIn("styleRatingSource", self.html)
        self.assertNotIn("styleRatingSource", self.script)
        for marker in (
            "grid-template-rows: auto auto minmax(0, 1fr) auto",
            ".style-artist-source-modal[hidden]",
            "width: min(1120px, calc(100vw - 32px))",
            "max-height: calc(100dvh - 32px)",
            "grid-template-columns: minmax(260px, .9fr) minmax(0, 1.6fr)",
            "min-width: 0",
            "min-height: 0",
            "@media (max-width: 820px)",
            "grid-template-columns: 1fr",
            "@media (max-width: 560px)",
            "width: calc(100vw - 16px)",
            "height: calc(100dvh - 16px)",
            "grid-template-columns: 1fr 1fr",
            "min-height: 44px",
            "white-space: pre-wrap",
            "overflow-wrap: anywhere",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)
        hidden_modal_start = self.css.index(".style-artist-source-modal[hidden]")
        hidden_modal_end = self.css.index("}", hidden_modal_start)
        self.assertIn("display: none", self.css[hidden_modal_start:hidden_modal_end])

    def test_editor_and_generation_controls_exist(self):
        for marker in (
            'id="rerollStyleArtists"',
            'id="rerollStyleWeights"',
            'id="rerollStyleAll"',
            'data-weight-table-sort',
            'id="weightGraph"',
            'id="artistPromptPreview"',
            'id="styleArtistSearch"',
            'id="styleArtistAutocomplete"',
            'id="styleArtistSelect"',
            'id="styleArtistPosition"',
            'id="styleArtistWeight"',
            'id="styleArtistList"',
            '고정 작가 편집',
            'id="openStyleAddArtist"',
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

    def test_weight_profile_uses_settings_preview_and_separate_editors(self):
        dom = ElementContractParser(self.html)
        for element_id in ("openWeightGraph", "weightGraphPreview"):
            self.assertIn("styleWeightsPanel", dom.ancestor_ids(element_id))
        self.assertIn("weightGraphModal", dom.ancestor_ids("weightGraph"))
        self.assertIn("weightTableModal", dom.ancestor_ids("weightTableArtistList"))
        self.assertNotIn("styleMakerSettings", dom.ancestor_ids("styleArtistList"))
        self.assertIn("styleMakerEditor", dom.ancestor_ids("latestStyleResult"))
        self.assertIn("styleCombinationModal", dom.ancestor_ids("artistPromptPreview"))

    def test_weight_table_has_full_size_editor_modal_and_random_controls(self):
        for marker in (
            'id="openWeightTable"',
            'id="weightTableModal"',
            'id="weightTableArtistList"',
            'id="weightTableArtistSearch"',
            'id="weightTableArtistAutocomplete"',
            'id="weightTableArtistSelect"',
            'id="weightTableArtistPosition"',
            'id="weightTableArtistWeight"',
            'id="weightTableArtistRandomWeight"',
            'id="weightTableAddArtist"',
            'id="styleArtistRandomWeight"',
            '순서 0은',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

        self.assertIn('position.min = "0"', self.script)
        self.assertIn('randomWeightInput.checked = item.random_weight === true', self.script)
        self.assertIn('updateStyleArtistAutocomplete("modal")', self.script)
        self.assertIn(".weight-table-dialog", self.css)
        self.assertEqual(self.html.count("data-weight-table-sort"), 2)
        self.assertIn("가중치 <span data-weight-sort-icon>↑↓</span>", self.html)
        self.assertNotIn('id="weightTableSortAsc"', self.html)
        self.assertNotIn('id="weightTableSortDesc"', self.html)
        self.assertNotIn('id="sortStyleAsc"', self.html)
        self.assertNotIn('id="sortStyleDesc"', self.html)
        modal_start = self.html.index('id="weightTableModal"')
        modal_add = self.html.index('class="artist-add-row weight-table-artist-add"', modal_start)
        modal_table = self.html.index('class="weight-table-content"', modal_start)
        self.assertLess(modal_add, modal_table)
        self.assertIn(".style-artist-list .style-artist-row:hover", self.css)
        self.assertIn("background: #202833", self.css)

    def test_generation_sampler_matches_novelai_sampling_methods(self):
        expected = {
            "k_dpmpp_2m": "DPM++ 2M",
            "k_dpmpp_2m_sde": "DPM++ 2M SDE",
            "k_euler_ancestral": "Euler Ancestral",
            "k_euler": "Euler",
            "k_dpm_2": "DPM2",
            "k_dpmpp_2s_ancestral": "DPM++ 2S Ancestral",
            "k_dpmpp_sde": "DPM++ SDE",
            "k_dpm_fast": "DPM Fast",
            "ddim_v3": "DDIM",
        }
        sampler_start = self.html.index('id="generationSampler"')
        sampler_end = self.html.index("</select>", sampler_start)
        sampler_html = self.html[sampler_start:sampler_end]
        for value, label in expected.items():
            with self.subTest(value=value):
                self.assertIn(f'value="{value}"', sampler_html)
                self.assertIn(f">{label}</option>", sampler_html)
        self.assertIn('value="k_euler_ancestral" selected', sampler_html)

    def test_style_settings_use_two_tabs_and_number_only_rating_buttons(self):
        dom = ElementContractParser(self.html)
        settings = dom.by_id["styleMakerSettings"]
        self.assertFalse(any(node["tag"] == "details" and settings in node["parents"] for node in dom.nodes))
        for tab, panel in (("styleArtistsTab", "styleArtistsPanel"), ("styleWeightsTab", "styleWeightsPanel")):
            self.assertEqual("tab", dom.by_id[tab]["attrs"]["role"])
            self.assertEqual(panel, dom.by_id[tab]["attrs"]["aria-controls"])
            self.assertEqual("tabpanel", dom.by_id[panel]["attrs"]["role"])
            self.assertEqual(tab, dom.by_id[panel]["attrs"]["aria-labelledby"])
        self.assertEqual("true", dom.by_id["styleArtistsTab"]["attrs"]["aria-selected"])
        self.assertEqual("false", dom.by_id["styleWeightsTab"]["attrs"]["aria-selected"])
        scores = [node for node in dom.nodes if "data-score" in node["attrs"] and dom.by_id["styleScoreButtons"] in node["parents"]]
        self.assertEqual([str(score) for score in range(1, 6)], [node["text"].strip() for node in scores])
        self.assertTrue(all(node["attrs"].get("aria-pressed") in ("true", "false") for node in scores))
        for control in ("styleArtistCountDown", "styleArtistCount", "styleArtistCountUp", "styleScoreAll"):
            self.assertIn("styleArtistsPanel", dom.ancestor_ids(control))
        self.assertRegex(self.css, r"#styleMakerSettings \.style-settings-body\s*\{[^}]*overflow:\s*hidden")

    def test_weight_graph_uses_all_slot_overview_and_transactional_footer(self):
        dom = ElementContractParser(self.html)
        body = dom.by_id["weightGraph"]
        for element_id in ("weightGraphStatus", "cancelWeightGraph", "applyWeightGraph"):
            self.assertIn("weightGraphModal", dom.ancestor_ids(element_id))
            self.assertNotIn(body, dom.by_id[element_id]["parents"])
            self.assertTrue(any(node["tag"] == "footer" for node in dom.by_id[element_id]["parents"]))
        render = self.script.split("function renderWeightGraph()", 1)[1].split("function currentStyleArtistFragment", 1)[0]
        self.assertIn("renderWeightProfileGraph(graph)", render)
        self.assertNotIn("renderWeightGraphFixedArtistOverlays(graph)", render)
        self.assertNotIn('column.className = "weight-column"', render)
        for marker in ("weightProfileSlotValues", "weightProfileFromSlotValues", "weightGraphDraft", '"weightGraphArtist"', '"weightGraphValue"', '"data-weight-slot"', "function applyWeightGraphModal()"):
            self.assertIn(marker, self.script)
        self.assertRegex(self.css, r"\.weight-graph-dialog\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto")
        self.assertRegex(self.css, r"\.weight-graph\.weight-overview\s*\{[^}]*overflow-x:\s*hidden")
        self.assertIn(".weight-overview-detail", self.css)

    def test_fixed_artist_add_controls_prevent_label_overlap(self):
        self.assertIn(".artist-add-row .field > span", self.css)
        self.assertIn("white-space: nowrap", self.css)
        self.assertIn("text-overflow: ellipsis", self.css)
        self.assertIn(".style-editor-head .status", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)

    def test_random_weight_add_controls_remain_in_both_artist_editors(self):
        dom = ElementContractParser(self.html)
        self.assertIn("styleAddArtistModal", dom.ancestor_ids("styleArtistRandomWeight"))
        self.assertIn("weightTableModal", dom.ancestor_ids("weightTableArtistRandomWeight"))
        self.assertIn("styleAddArtistModal", dom.ancestor_ids("styleArtistWeight"))
        self.assertIn("weightTableModal", dom.ancestor_ids("weightTableArtistWeight"))
        self.assertEqual(self.html.count('class="compact-check style-artist-random-add"'), 2)

    def test_latest_generation_result_fits_remaining_viewport_space(self):
        self.assertRegex(self.css, r"#styleMakerEditor\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto")
        self.assertRegex(self.css, r"#styleMakerEditor #latestStyleResult\s*\{[^}]*min-height:\s*0")
        self.assertRegex(self.css, r"#latestStyleResult>img\s*\{[^}]*object-fit:\s*contain")

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

    def test_collected_prompt_presets_follow_the_generation_random_targets(self):
        for marker in (
            'id="openPromptPresetModal"',
            'id="promptPresetModal"',
            'id="promptPresetGallery"',
            'id="promptPresetQualityEditor"',
            'id="promptPresetFullPreview"',
            'id="promptPresetExcludedList"',
            'id="saveAndApplyPromptPreset"',
            'id="promptPresetStatus"',
            'id="excludedPromptTags"',
            'id="excludedPromptTagList"',
            'id="promptPresetModelFilter"',
            'value="v5"',
            'value="v4.5"',
            'value="nai-diffusion-5-full"',
            'value="nai-diffusion-5-curated"',
            'value="nai-diffusion-4-5-full"',
            'value="nai-diffusion-4-5-curated"',
            'value="unknown"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertNotIn('id="promptPresetSelect"', self.html)
        self.assertNotIn('id="promptPresetMode"', self.html)
        self.assertNotIn('>자동 추천</option>', self.html)
        self.assertNotIn('>수동 고정</option>', self.html)
        self.assertNotIn('return applyPromptPreset(styleState.promptPresets[0])', self.script)
        for marker in (
            'apiFetch("/api/style-maker/prompt-presets"',
            "function applyPromptPreset",
            "function renderPromptPresetModal",
            "function saveAndApplyPromptPreset",
            'button.addEventListener("dblclick"',
            'method: "PATCH"',
            "function refreshPromptPresetsForArtists",
            "function fixPromptPresetAfterManualEdit",
            "function restoreExcludedPromptTag",
            'targets.has("quality")',
            'targets.has("negative")',
            "function normalizePromptPresetModelFilter",
            "model_filter: normalizePromptPresetModelFilter(styleState.promptPresetModelFilter)",
            "model_filter: modelFilter",
            'styleElement("promptPresetModelFilter")?.addEventListener("change"',
            'loadPromptPresets({ force: true })',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        self.assertIn(".prompt-preset-model-filter", self.css)

    def test_fixed_prompt_tags_follow_quality_and_are_kept_out_of_random_presets(self):
        self.assertIn('id="fixedPrompt"', self.html)
        self.assertIn('id="fixedPromptAutocomplete"', self.html)
        self.assertLess(self.html.index('id="basePrompt"'), self.html.index('id="fixedPrompt"'))
        self.assertIn('function updatePromptTagAutocomplete(input)', self.script)
        self.assertIn('function handlePromptTagAutocompleteKeydown(event)', self.script)
        self.assertIn('apiFetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}${categoryQuery}`)', self.script)
        self.assertIn('styleElement("fixedPrompt")?.value', self.script)
        self.assertIn('combinePromptSections(', self.script)

    def test_leading_prompt_is_before_artist_tags_and_persisted_in_generation(self):
        leading = self.html.index('id="leadingPrompt"')
        artist = self.html.index('id="artistPromptTokenTitle"')
        self.assertLess(leading, artist)
        self.assertIn('id="leadingPromptAutocomplete"', self.html)
        for marker in (
            'leading_prompt: typeof leadingPrompt === "string" ? leadingPrompt : ""',
            'typeof value.leading_prompt === "string" ? value.leading_prompt : ""',
            'styleElement("leadingPrompt")?.value || ""',
            'leading_prompt: leadingPrompt',
            'styleElement("leadingPrompt").value = storedPrompts.leading_prompt',
            '["leadingPrompt", "fixedPrompt"]',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_all_prompt_textareas_use_danbooru_tag_autocomplete(self):
        for marker in (
            'id="basePromptAutocomplete"',
            'id="fixedPromptAutocomplete"',
            'id="negativePromptAutocomplete"',
            'id="promptPresetQualityEditorAutocomplete"',
            'id="arcaEditPromptAutocomplete"',
            'id="arcaEditNegativePromptAutocomplete"',
            'id="styleGroupDirectArtistAutocomplete"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn('["leadingPrompt", "basePrompt", "fixedPrompt", "negativePrompt"]', self.script)
        self.assertIn('autocomplete.className = "autocomplete prompt-tag-autocomplete hidden"', self.script)
        self.assertIn("bindPromptTagAutocomplete(input);", self.script)
        self.assertIn('globalThis.promptTagAutocomplete = Object.freeze({', self.script)
        self.assertIn('input.setAttribute("role", "combobox")', self.script)
        self.assertIn('box.setAttribute("role", "listbox")', self.script)
        self.assertIn('return `artist:${/\\d$/.test(name) ? `${name} ` : name}`;', self.script)
        self.assertIn('fragment.replace(/^artist:/i, "")', self.script)

    def test_static_prompt_fields_have_owned_autocomplete_boxes(self):
        for marker in (
            'id="manualTagsAutocomplete"',
            'id="naiArtistTestBasePromptAutocomplete"',
            'id="naiArtistTestNegativePromptAutocomplete"',
            'id="naiArtistTestCharacterPromptsAutocomplete"',
            'id="naiArtistTestAppendPromptAutocomplete"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        direct = self.html[self.html.index('id="styleGroupDirectArtist"'):]
        self.assertIn('autocomplete="off"', direct[:300])
        self.assertIn('data-autocomplete-category="1"', direct[:300])
        self.assertIn('data-prefix-artist="false"', direct[:300])
        for field_id in ("manualTags", "naiArtistTestBasePrompt", "naiArtistTestNegativePrompt", "naiArtistTestCharacterPrompts", "naiArtistTestAppendPrompt", "arcaEditPrompt", "arcaEditNegativePrompt"):
            field_start = self.html.index(f'id="{field_id}"')
            field_end = self.html.find("</label>", field_start)
            with self.subTest(field=field_id):
                self.assertIn('autocomplete="off"', self.html[field_start:field_end])

    def test_rated_artist_tag_rules_open_in_a_modal_and_are_sent_with_style_requests(self):
        for marker in (
            'id="openRatingTagRules"',
            'id="ratingTagRulesModal"',
            'id="ratingTagRulesList"',
            'id="addRatingTagRule"',
            'id="saveRatingTagRules"',
            'id="ratingTagExclusionsList"',
            'id="addRatingTagExclusion"',
        ):
            self.assertIn(marker, self.html)
        self.assertNotIn('id="ratingArtistTagFilter"', self.html)
        self.assertIn('rating_tag_rules:', self.script)
        self.assertIn('rating_exclude_tags:', self.script)
        self.assertIn('function openRatingTagRulesModal()', self.script)
        self.assertIn('bindPromptTagAutocomplete(tagInput);', self.script)
        self.assertIn('tagInput.dataset.ratingTagAutocomplete = "true"', self.script)
        self.assertIn('.rating-tag-rule-row .prompt-tag-autocomplete', self.css)

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
            "function sortFixedArtistEntriesForTable",
            "function cycleWeightTableSort",
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

    def test_style_manager_has_wide_gallery_inspector_and_batch_delete(self):
        for marker in (
            'id="beginStyleSelection"',
            'id="deleteSelectedStyles"',
            'id="cancelStyleSelection"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            'grid-template-columns: minmax(560px, 3fr) minmax(430px, 2fr)',
            'grid-template-columns: minmax(0, 1fr)',
            'min-width: 0',
            'min-height: 0',
            'aspect-ratio: 3 / 4',
            'overflow-wrap: anywhere',
            '.manager-image-inspector',
            '.manager-selected-image',
        ):
            self.assertIn(marker, self.css)
        for marker in (
            '"/api/confirmed-styles/delete-batch"',
            '"/api/style-manager/generated/delete-batch"',
            'appendManagerPromptBlock(inspector, "작가 · 퀄리티", managerCombinedPromptText(item)',
            'negativeToggle.textContent = styleState.managerNegativeExpanded',
            'appendManagerPromptBlock(\n    inspector,\n    "캐릭터"',
            'function renderStyleManagerImageSelection()',
        ):
            self.assertIn(marker, self.script)
        self.assertIn('class="danger-button style-manager-delete-selected hidden"', self.html)
        self.assertIn('.style-manager-delete-selected', self.css)
        self.assertIn('min-width: 172px', self.css)
        selection_branch = self.script.index('if (styleState.managerSelectionMode && styleState.managerMode !== "shared")')
        detail_load = self.script.index('renderStyleManagerDetail(style);', selection_branch)
        self.assertLess(selection_branch, detail_load)
        self.assertNotIn('return;', self.script[selection_branch:detail_load])

    def test_style_manager_restores_three_galleries_and_adds_all_generation_history(self):
        self.assertIn('id="styleManagerModeTabs"', self.html)
        self.assertIn('role="tablist"', self.html)
        for mode, label in (
            ("generated", "제작 기록"),
            ("confirmed", "확정 그림체"),
            ("shared", "공유 그림체"),
            ("all_generated", "모든 제작 기록"),
        ):
            with self.subTest(mode=mode):
                self.assertIn(f'data-style-manager-mode="{mode}"', self.html)
                self.assertIn(f">{label}</button>", self.html)
        self.assertIn('managerMode: "generated",', self.script)
        self.assertIn('if (!["generated", "confirmed", "shared", "all_generated"].includes(mode)) return;', self.script)
        self.assertIn('apiFetch("/api/style-manager/generated")', self.script)
        self.assertIn('apiFetch("/api/style-manager/all-generated")', self.script)
        for marker in (
            'item.source_label, item.source_name, item.source_artist_tag',
            'mode === "all_generated" && scope !== "all"',
            'styleManagerRecordKey',
            'styleState.managerMode !== "all_generated"',
            '"그림체 제작"',
            '"NAI 작가 테스트"',
            '"비교군 관리"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        self.assertIn('.style-manager-mode-tabs', self.css)
        self.assertIn('aspect-ratio: 3 / 4', self.css)
        self.assertIn('overflow-wrap: anywhere', self.css)

    def test_style_manager_mobile_caps_min_content_without_changing_toolbar_layout(self):
        for selector in (
            ".style-manager-view.active",
            ".style-manager-toolbar",
            ".style-manager-mode-tabs",
        ):
            start = self.css.index(f"{selector} {{")
            rule = self.css[start:self.css.index("}", start)]
            with self.subTest(selector=selector):
                self.assertIn("min-width: 0", rule)
                self.assertIn("max-width: 100%", rule)

        pane_rule_start = self.css.index(
            ".style-manager-list-pane,\n.style-manager-detail {"
        )
        pane_rule = self.css[pane_rule_start:self.css.index("}", pane_rule_start)]
        self.assertIn("min-width: 0", pane_rule)
        self.assertIn("max-width: 100%", pane_rule)
        self.assertIn("overflow: auto", pane_rule)

        manager_start = self.css.index(".style-manager-toolbar {")
        mobile_start = self.css.index("@media (max-width: 760px)", manager_start)
        mobile_css = self.css[mobile_start:]
        toolbar_start = mobile_css.index(".style-manager-toolbar {")
        toolbar_rule = mobile_css[toolbar_start:mobile_css.index("}", toolbar_start)]
        filters_start = mobile_css.index(".style-manager-filters {")
        filters_rule = mobile_css[filters_start:mobile_css.index("}", filters_start)]
        self.assertIn("flex-direction: column", toolbar_rule)
        self.assertIn("grid-template-columns: 1fr 1fr", filters_rule)

    def test_style_manager_detail_selection_is_distinct_and_closable(self):
        for marker in (
            'button.dataset.styleManagerId = String(style.id);',
            'button.classList.toggle("detail-active", Boolean(detailActive));',
            'button.setAttribute("aria-current", "true");',
            'function syncStyleManagerDetailSelection()',
            'button.removeAttribute("aria-current");',
            'closeButton.className = "ghost style-manager-detail-close";',
            'closeButton.textContent = "상세 닫기";',
            'closeButton.addEventListener("click", resetStyleManagerDetail);',
            'syncStyleManagerDetailSelection();',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        self.assertIn('.style-manager-item.detail-active', self.css)
        self.assertIn('outline: 2px solid var(--accent-strong);', self.css)

    def test_confirmed_style_import_supports_multiple_images_folders_and_group_navigation(self):
        for marker in (
            'id="confirmedStyleFile" class="hidden" type="file" accept="image/png,image/jpeg,image/webp" multiple',
            'id="confirmedStyleFolder"',
            'webkitdirectory',
            'id="confirmedStyleGroupStrip"',
            'id="confirmedStylePrevGroup"',
            'id="confirmedStyleNextGroup"',
            'id="confirmedStylePrevImage"',
            'id="confirmedStyleNextImage"',
            'id="splitConfirmedStyleImage"',
            'id="removeConfirmedStyleGroup"',
            'id="saveAllConfirmedStyles"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            "function groupConfirmedImportItems",
            "function useConfirmedStyleFiles",
            'apiFetch("/api/confirmed-styles/import-batch"',
            "useConfirmedStyleFiles(event.dataTransfer?.files)",
            "useConfirmedStyleFiles(files)",
            "function splitConfirmedImportImage",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        self.assertIn(".confirmed-style-group-strip", self.css)
        self.assertIn(".confirmed-style-import-navigator", self.css)

    def test_comparison_groups_use_folder_gallery_progress_and_reacquire(self):
        for marker in (
            'id="comparisonProgress"',
            'id="comparisonGallery"',
            'id="comparisonResultGallery"',
            'id="comparisonResultDetail"',
            'id="editComparisonSelection"',
            'id="deleteOpenComparison"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            '.comparison-folder',
            '.comparison-gallery-view',
            '.comparison-result-card',
            '.comparison-result-detail',
        ):
            self.assertIn(marker, self.css)
        for marker in (
            'function setComparisonProgress(',
            'function renderComparisonFolders(',
            'function openComparisonGallery(',
            'function renderComparisonResultDetail(',
            'async function regenerateComparisonStyle(',
            'defer_generation: true',
            '/generate`',
        ):
            self.assertIn(marker, self.script)

    def test_workspace_has_viewport_grid_and_owned_internal_scroll(self):
        self.assertRegex(self.css, r"body\.style-maker-active\s*\{[^}]*height:\s*100dvh[^}]*overflow:\s*hidden")
        self.assertRegex(self.css, r"#style-maker-tab\.active\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\)")
        for marker in ("--settings-width", "--generation-width", "--history-width"):
            self.assertIn(marker, self.css)
        self.assertRegex(self.css, r"#styleMakerGeneration \.generation-scroll\s*\{[^}]*overflow:\s*hidden")
        self.assertRegex(self.css, r"#styleMakerHistory \.style-history-scroll\s*\{[^}]*overflow-y:\s*auto[^}]*overflow-x:\s*hidden")

    def test_workspace_switches_side_panels_to_overlays_at_1100_pixels(self):
        breakpoint = re.search(r"@media\s*\(max-width:\s*1100px\)", self.css)
        self.assertIsNotNone(breakpoint)
        responsive = self.css[breakpoint.start():]
        self.assertRegex(responsive, r"#styleMakerGeneration\s*\{[^}]*position:\s*absolute")
        self.assertRegex(responsive, r"#styleMakerHistory:not\(\.history-collapsed\)\s*\{[^}]*position:\s*absolute")

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

    def test_artist_tags_remain_in_extra_prompt_editor_and_base_tokens_can_be_excluded(self):
        dom = ElementContractParser(self.html)
        self.assertIn("stylePromptExtrasModal", dom.ancestor_ids("artistPromptTokens"))
        self.assertIn("styleMakerGeneration", dom.ancestor_ids("basePrompt"))
        self.assertIn("excludeBasePromptToken", self.script)
        self.assertIn("excludedPromptTagList", self.html)

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
        self.assertIn("function opusFreeGenerationIssues", source)
        self.assertIn('title: "Anlas가 차감될 수 있습니다"', source)
        self.assertIn('await confirmGenerationAnlasRisk("single")', source)
        self.assertIn('await confirmGenerationAnlasRisk("continuous")', source)

    def test_settings_modal_and_delete_confirmation_categories_match_each_action(self):
        source = JS_PATH.read_text(encoding="utf-8")
        arca_source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn('id="openSettings" class="icon-button" type="button" title="설정" aria-label="설정"', self.html)
        self.assertIn('<h2 id="settingsTitle">설정</h2>', self.html)
        self.assertIn("<legend>삭제 전 확인</legend>", self.html)
        self.assertIn("기본값은 모두 확인", self.html)
        self.assertIn("전체 확인 안 함", self.html)
        self.assertIn("deleteConfirmationEnabledFromSkip", source)
        self.assertIn("skipDeleteConfirmationFromEnabled", source)
        for category in (
            "rating_example", "rating", "generated", "style", "arca_style",
            "comparison_group", "comparison_result", "novelai_key",
        ):
            self.assertIn(
                f'<input type="checkbox" checked data-delete-confirmation-category="{category}">',
                self.html,
            )
        style_delete = source[source.index("async function deleteManagedStyle"):source.index("async function deleteSelectedManagedStyles")]
        self.assertIn('delete_category: "style"', style_delete)
        for function_name in ("deleteSelectedManagedStyles", "deleteSingleManagerItem"):
            start = source.index(f"async function {function_name}")
            end = source.find("\nasync function ", start + 1)
            section = source[start:] if end < 0 else source[start:end]
            self.assertIn('delete_category: styleState.managerMode === "confirmed" ? "style" : "generated"', section)
        self.assertIn('delete_category: "arca_style"', arca_source)
        self.assertIn("grid-template-rows: repeat(5, auto)", self.css)
        self.assertIn("max-height: min(720px, calc(100vh - 24px))", self.css)
        self.assertIn("overflow-y: auto", self.css[self.css.index(".compact-modal {"):])

    def test_style_history_and_collapsed_generation_remote_exist(self):
        for marker in (
            'id="styleMakerHistory"', 'id="toggleStyleHistory"', 'id="styleHistoryList"',
            'id="styleHistoryDetail"', 'id="refreshStyleHistory"',
            'id="toggleGenerationPanel"', 'id="generationRemote"',
            'id="generationRemoteHandle"', 'id="remoteGenerateOne"',
            'id="remoteStartContinuous"', 'id="remotePauseContinuous"', 'id="remoteStopContinuous"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            'apiFetch("/api/style-manager/generated")',
            'apiFetch("/api/style-manager/generated/delete-batch"',
            'function normalizeStyleHistoryItem(',
            'function renderArtistPromptPreview(',
            'function styleHistoryArtistPrompt(',
            'function renderStyleHistorySelection(',
            'styleHistoryPreviewMeta(',
            'function applyStyleHistoryItem(',
            'function setGenerationPanelCollapsed(',
            'function setupGenerationRemoteDrag(',
            'openConfirmedStyleModal(normalized, false, "generated")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        for marker in (
            '.style-maker-layout.history-open',
            '.style-maker-layout.settings-collapsed.history-open',
            '.style-maker-layout.settings-collapsed.generation-collapsed',
            '.style-maker-layout.settings-collapsed.history-open.generation-collapsed',
            '.style-maker-generation.is-collapsed',
            '.style-history-card',
            '.generation-remote',
            'touch-action: none',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)
        self.assertIn('class="style-maker-pane style-maker-history history-collapsed"', self.html)
        self.assertLess(self.html.index('id="styleHistoryList"'), self.html.index('id="styleHistoryDetail"'))
        dom = ElementContractParser(self.html)
        self.assertTrue(any('style-history-scroll' in node['attrs'].get('class', '').split() for node in dom.by_id['styleHistoryList']['parents']))
        self.assertFalse(any('style-history-scroll' in node['attrs'].get('class', '').split() for node in dom.by_id['styleHistoryDetail']['parents']))
        self.assertTrue(any(node["tag"] == "svg" and dom.by_id["styleHistoryRail"] in node["parents"] for node in dom.nodes))
        self.assertIn('load.textContent = "설정 반영"', self.script)
        self.assertIn('confirm.textContent = "확정 그림체로"', self.script)
        self.assertIn('remove.textContent = "×"', self.script)
        self.assertIn('renderStyleHistorySelection(item)', self.script)
        self.assertIn('renderArtistPromptPreview(styleHistoryArtistPrompt(normalized))', self.script)
        self.assertIn('latestStyleResult', self.script)
        self.assertIn('className = "style-history-card-delete"', self.script)
        self.assertIn('event.stopPropagation()', self.script)
        delete_css_start = self.css.index('.style-history-card-delete {')
        delete_css_end = self.css.index('.style-history-card-delete:hover', delete_css_start)
        delete_css = self.css[delete_css_start:delete_css_end]
        for marker in (
            'display: grid;', 'place-items: center;', 'width: 28px;', 'height: 28px;',
            'min-width: 28px;', 'padding: 0;', 'box-sizing: border-box;',
            'font-size: 18px;', 'line-height: 1;', 'text-align: center;',
        ):
            with self.subTest(delete_css_marker=marker):
                self.assertIn(marker, delete_css)
        mobile_delete_css = self.css[self.css.index('@media (max-width: 1320px)'):]
        mobile_delete_css_start = mobile_delete_css.index('.style-history-card-delete {')
        mobile_delete_css = mobile_delete_css[mobile_delete_css_start:]
        for marker in ('width: 34px;', 'height: 34px;', 'min-width: 34px;', 'padding: 0;'):
            with self.subTest(mobile_delete_css_marker=marker):
                self.assertIn(marker, mobile_delete_css)
        history_start = self.script.index('function renderStyleHistoryList(')
        history_end = self.script.index('async function loadStyleHistory(', history_start)
        history_source = self.script[history_start:history_end]
        self.assertIn('const card = document.createElement("article")', history_source)
        self.assertIn('const select = document.createElement("button")', history_source)
        self.assertIn('const remove = document.createElement("button")', history_source)
        self.assertIn('card.append(select, remove)', history_source)
        self.assertNotIn('remove.setAttribute("role"', history_source)
        self.assertNotIn('remove.addEventListener("keydown"', history_source)
        detail_start = self.script.index('function renderStyleHistoryDetail(')
        detail_end = self.script.index('function renderStyleHistoryList(', detail_start)
        self.assertNotIn('remove.textContent', self.script[detail_start:detail_end])

    def test_style_maker_narrow_layout_keeps_fixed_panels_over_the_result(self):
        breakpoint = re.search(r"@media\s*\(max-width:\s*760px\)\s*\{\s*body\.style-maker-active main", self.css)
        self.assertIsNotNone(breakpoint)
        responsive = self.css[breakpoint.start():]
        self.assertRegex(responsive, r"#styleMakerSettings\s*\{[^}]*position:\s*absolute")
        self.assertRegex(responsive, r"#styleMakerLayout\s*\{[^}]*--settings-width:\s*0px")
        self.assertIn("max-height:calc(100dvh - 16px)", responsive.replace("max-height: ", "max-height:"))

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

    def test_prompt_and_generation_share_a_panel_and_only_generation_actions_float(self):
        dom = ElementContractParser(self.html)
        for control in ("basePrompt", "negativePrompt", "generationLimitMode", "generationCount", "styleRandomTargets"):
            self.assertIn("styleMakerGeneration", dom.ancestor_ids(control))
        for control in ("leadingPrompt", "fixedPrompt", "characterPromptList", "promptGroupList"):
            self.assertIn("stylePromptExtrasModal", dom.ancestor_ids(control))
        for control in ("generationModel", "generationSampler", "generationScale", "generationMediumHint"):
            self.assertIn("styleGenerationParametersModal", dom.ancestor_ids(control))
        for control in ("remoteGenerateOne", "remoteStartContinuous", "remotePauseContinuous", "remoteStopContinuous"):
            self.assertIn("generationRemote", dom.ancestor_ids(control))
            self.assertNotIn("styleMakerGeneration", dom.ancestor_ids(control))
        for control in ("generateOne", "startContinuous", "pauseContinuous", "stopContinuous"):
            self.assertTrue(any("hidden" in node["attrs"].get("class", "").split() for node in dom.by_id[control]["parents"]))
        self.assertEqual("true", dom.by_id["toggleStyleSettings"]["attrs"]["aria-expanded"])
        self.assertIn("openGenerationRemote", dom.by_id)

    def test_workspace_modal_actions_stay_outside_the_scroll_body(self):
        dom = ElementContractParser(self.html)
        for modal_id in (
            "styleAddArtistModal", "styleCombinationModal", "stylePromptExtrasModal",
            "styleGenerationParametersModal", "styleSharedMixModal", "styleUsageModal",
            "ratingTagRulesModal", "weightTableModal",
        ):
            with self.subTest(modal=modal_id):
                modal = dom.by_id[modal_id]
                bodies = [node for node in dom.nodes if modal in node["parents"] and "workspace-modal-body" in node["attrs"].get("class", "").split()]
                self.assertEqual(1, len(bodies))
                footer_actions = [node for node in dom.nodes if node["tag"] == "button" and modal in node["parents"] and any(parent["tag"] == "footer" or "modal-actions" in parent["attrs"].get("class", "").split() for parent in node["parents"])]
                self.assertTrue(footer_actions)
                self.assertTrue(all(bodies[0] not in button["parents"] for button in footer_actions))
        self.assertRegex(self.css, r"\.workspace-dialog\s*\{[^}]*grid-template-rows:\s*auto minmax\(0,\s*1fr\) auto")
        self.assertRegex(self.css, r"\.workspace-modal-body\s*\{[^}]*overflow:\s*auto")

    def test_excluded_prompts_restore_from_the_main_prompt_panel(self):
        dom = ElementContractParser(self.html)
        for control in ("excludedPromptTab", "excludedPromptPanel", "excludedPromptTagList", "restoreAllExcludedPrompts"):
            self.assertIn("styleMakerGeneration", dom.ancestor_ids(control))
            self.assertNotIn("stylePromptExtrasModal", dom.ancestor_ids(control))
        self.assertEqual("excludedPromptPanel", dom.by_id["excludedPromptTab"]["attrs"]["aria-controls"])
        self.assertEqual("excludedPromptTab", dom.by_id["excludedPromptPanel"]["attrs"]["aria-labelledby"])
        self.assertNotIn("excludedPromptTags", dom.ancestor_ids("restoreAllExcludedPrompts"))
        self.assertRegex(self.css, r"#styleMakerGeneration #excludedPromptTags\s*\{[^}]*min-height:0;[^}]*overflow:auto")

    def test_combination_separates_selection_from_the_fixed_candidate_editor(self):
        dom = ElementContractParser(self.html)
        self.assertIn("styleCombinationModal", dom.ancestor_ids("styleCombinationSummary"))
        self.assertIn("styleCombinationCandidates", dom.ancestor_ids("styleArtistList"))
        self.assertNotIn("styleCombinationCandidates", dom.ancestor_ids("styleCurrentCombination"))
        self.assertEqual("details", dom.by_id["styleCombinationCandidates"]["tag"])
        self.assertNotIn("open", dom.by_id["styleCombinationCandidates"]["attrs"])

    def test_style_editor_behavior_with_node(self):
        result = subprocess.run(
            ["node", "--test", str(BEHAVIOR_TEST_PATH), str(GRAPH_BEHAVIOR_TEST_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_confirmed_import_progress_folder_contents_and_duplicate_review_exist(self):
        for marker in (
            'id="confirmedStyleImportProgress"',
            'id="confirmedStyleImportProgressBar"',
            'id="confirmedStyleFolderContents"',
            'id="confirmedStyleFolderContentsList"',
            'id="confirmedStyleFolderModal"',
            'id="confirmedStyleFolderSummary"',
            'id="importConfirmedStyleFolder"',
            'id="cancelConfirmedStyleFolder"',
            'id="confirmedStyleDuplicateWarning"',
            'id="confirmedStyleDuplicateCandidates"',
            'id="confirmedStyleDuplicateModal"',
            'id="confirmedStyleDuplicateDetailImage"',
            'id="confirmedStyleDuplicateDetailInfo"',
            'id="confirmedStyleDuplicatePrevImage"',
            'id="confirmedStyleDuplicateNextImage"',
            'id="confirmedStyleCharacterPrompts"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            "function renderConfirmedFolderContents(",
            "function openConfirmedFolderReview(",
            "function stageConfirmedFolderFiles(",
            "function confirmConfirmedFolderImport(",
            "function openConfirmedStylePreview(",
            "function setConfirmedImportProgress(",
            "function attachConfirmedStyleSuspects(",
            "function openConfirmedDuplicateReview(",
            "function moveConfirmedDuplicateImage(",
            "Promise.allSettled(",
            "남음 ${candidates.length - completed}",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        self.assertIn("cursor: not-allowed", self.css)
        self.assertIn(".confirmed-style-duplicate-dialog", self.css)
        self.assertIn(".confirmed-style-duplicate-detail-info", self.css)
        self.assertIn(".confirmed-style-import-toolbar", self.css)
        self.assertIn(".confirmed-style-image-scroller", self.css)
        self.assertIn(".confirmed-style-folder-dialog", self.css)
        self.assertIn("#generatedImageModal", self.css)
        self.assertIn("z-index: 160", self.css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", self.css)
        self.assertLess(self.html.index('id="confirmedStyleImportCounter"'), self.html.index('id="confirmedStyleGroupStrip"'))
        self.assertLess(self.html.index('id="removeConfirmedStyleGroup"'), self.html.index('id="confirmedStyleGroupStrip"'))
        self.assertLess(self.html.index('id="confirmedStyleMetadataStatus"'), self.html.index('id="confirmedStyleGroupStrip"'))
        self.assertIn('styleElement("confirmedStylePreview")?.addEventListener("click", openConfirmedStylePreview)', self.script)
        self.assertIn("stageConfirmedFolderFiles(event.target.files)", self.script)
        self.assertIn("group.items[styleState.confirmedImportImageIndex]?.metadata", self.script)
        self.assertIn("entry.items[thumbIndex]?.objectUrl", self.script)
        self.assertIn("프롬프트 메타데이터 없음", self.script)
        self.assertIn(".confirmed-style-group-thumb.metadata-missing", self.css)
        self.assertNotIn('confirmedDropZone?.addEventListener("click"', self.script)
        self.assertLess(
            self.script.index('const imageModal = styleElement("generatedImageModal")'),
            self.script.index('const folderModal = styleElement("confirmedStyleFolderModal")'),
        )

    def test_style_manager_reports_page_image_loading_progress_and_uses_thumbnails(self):
        for marker in (
            'id="styleManagerLoadProgress"',
            'id="styleManagerLoadProgressBar"',
            'id="styleManagerLoadProgressText"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            "function setStyleManagerLoadProgress(",
            "function createStyleManagerImageProgress(",
            'style.thumbnail_url || imageUrl',
            'image.loading = "eager"',
            'image.decoding = "async"',
            "이미지 가져오는 중",
        ):
            self.assertIn(marker, self.script)

    def test_dense_layout_contracts_keep_actions_and_empty_states_compact(self):
        for marker in (
            'class="nai-artist-test-selection-meta"',
            'class="nai-artist-test-selection-buttons"',
            'class="style-group-gallery-action-buttons"',
            'class="arca-collection-actions"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            ".status:empty",
            ".latest-style-result:has(> .latest-result-placeholder)",
            ".style-group-image-stage.is-empty",
            ".style-group-gallery-action-buttons",
            ".arca-collection-actions",
            "grid-template-columns: minmax(0, 1fr) auto",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)

    def test_empty_style_result_does_not_change_workspace_columns_or_hide_controls(self):
        self.assertNotIn(".style-maker-layout:has(#latestStyleResult > .latest-result-placeholder)", self.css)
        self.assertNotIn(".style-maker-layout:has(#latestStyleResult > .latest-result-meta:only-child)", self.css)
        self.assertRegex(self.css, r"#styleMakerEditor\s*\{[^}]*align-self:\s*stretch")
        self.assertRegex(self.css, r"#styleMakerEditor #latestStyleResult\s*\{[^}]*min-height:\s*0")
        dom = ElementContractParser(self.html)
        for element_id in ("rerollStyleArtists", "rerollStyleWeights", "rerollStyleAll"):
            self.assertIn("styleMakerEditor", dom.ancestor_ids(element_id))
            self.assertNotIn("latestStyleResult", dom.ancestor_ids(element_id))

    def test_style_manager_desktop_rows_stretch_scroll_panes_and_stack_on_mobile(self):
        manager_start = self.css.index(".style-manager-view.active {")
        manager_rule = self.css[manager_start:self.css.index("}", manager_start)]
        for marker in (
            "grid-template-rows: auto minmax(0, 1fr)",
            "align-items: stretch",
            "align-content: stretch",
        ):
            with self.subTest(manager_marker=marker):
                self.assertIn(marker, manager_rule)

        pane_start = self.css.index(
            ".style-manager-list-pane,\n.style-manager-detail {"
        )
        pane_rule = self.css[pane_start:self.css.index("}", pane_start)]
        for marker in ("align-self: stretch", "max-height: 100%", "overflow: auto"):
            with self.subTest(pane_marker=marker):
                self.assertIn(marker, pane_rule)

        mobile_start = self.css.index("@media (max-width: 1050px)", manager_start)
        mobile_css = self.css[mobile_start:self.css.index("@media (max-width: 760px)", mobile_start)]
        for marker in (
            "grid-template-rows: auto",
            "height: auto",
            "max-height: none",
            "overflow: visible",
        ):
            with self.subTest(mobile_marker=marker):
                self.assertIn(marker, mobile_css)

    def test_small_viewports_keep_comparison_min_content_constrained(self):
        comparison_mobile_start = self.css.index("@media (max-width: 760px)")
        comparison_mobile = self.css[comparison_mobile_start:self.css.index(".topbar", comparison_mobile_start)]
        self.assertIn(".comparison-editor:not(.detail-collapsed):not(.settings-collapsed)", comparison_mobile)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", comparison_mobile)

    def test_pick_layout_remains_multi_column_until_the_900px_breakpoint(self):
        wide = self.css[self.css.index("@media (max-width: 1320px)"):self.css.index("@media (max-width: 900px)")]
        self.assertNotIn(".pick-layout", wide)
        narrow = self.css[self.css.index("@media (max-width: 900px)"):]
        for marker in (
            ".pick-layout",
            "grid-template-columns: 1fr",
            "height: auto",
            "min-height: 0",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, narrow)
        self.assertIn(".style-manager-load-progress", self.css)

    def test_shared_dependency_controls_and_payload_contract_exist(self):
        for marker in (
            'value="shared_dependency"',
            'id="sharedDependencySettings"',
            'id="sharedDependencyFixedRatio"',
            'id="sharedDependencyReferenceRatio"',
            'id="sharedDependencyRatedRatio"',
            'id="sharedDependencyOtherRatio"',
            'id="sharedDependencyCountStatus"',
            'id="sharedDependencyRatioSummary"',
        ):
            self.assertIn(marker, self.html)
        for marker in (
            'styleElement("weightMode")?.value === "shared_dependency"',
            "shared_dependency_source_ratios",
            "sharedDependencyFixedRatio",
            "normalizeSharedDependencyRatios",
            "shared_dependency_reference_id",
            "applySharedDependencyReference",
            "sharedDependencyParameterValue",
        ):
            self.assertIn(marker, self.script)
        for marker in ('sharedDependencyPercent', '기준 공유 그림체 작가 포함', '기준 그림체 남은 작가'):
            self.assertNotIn(marker, self.html)
        self.assertNotIn("shared_dependency_percent", self.script)

    def test_shared_dependency_reference_summary_and_mix_modal_preserve_clear_fixed_action(self):
        dom = ElementContractParser(self.html)
        for element_id in ("sharedDependencyReferencePicker", "sharedDependencyReferenceSummary", "openSharedDependencyReference"):
            self.assertIn("styleWeightsPanel", dom.ancestor_ids(element_id))
        self.assertIn("styleSharedMixModal", dom.ancestor_ids("clearSharedDependencyReference"))
        self.assertIn("고정 해제 · 랜덤으로", dom.by_id["clearSharedDependencyReference"]["text"])
        for marker in ("function clearSharedDependencyReference()", 'styleState.sharedDependencyReferenceMode = "random"', "styleState.sharedDependencyReferenceId = null", "styleState.sharedDependencyReference = null", 'styleElement("clearSharedDependencyReference")?.addEventListener'):
            self.assertIn(marker, self.script)

    def test_generated_detail_shows_shared_dependency_snapshot_link(self):
        for marker in (
            "function appendSharedDependencyBlock(",
            "shared_dependency_reference_id",
            "shared_dependency_reference_title",
            "shared_dependency_reference_source_url",
            'textContent = "의존 공유 그림체"',
            'target = "_blank"',
            'rel = "noopener noreferrer"',
            'event.stopPropagation()',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_static_input_help_uses_keyboard_accessible_tooltips(self):
        self.assertIn('class="help-tooltip-wrap"', self.html)
        self.assertIn('class="help-tooltip-button"', self.html)
        self.assertIn('role="tooltip"', self.html)
        self.assertIn('aria-describedby="help-rating-exclusion"', self.html)
        self.assertIn(".help-tooltip-button:focus-visible", self.css)
        self.assertIn(".field-label", self.css)
        self.assertIn(".field .help-tooltip-content", self.css)
        self.assertIn('.check-row input[type="checkbox"]', self.css)
        self.assertIn('class="field-label"><span>제외할 태그/프롬프트</span><span class="help-tooltip-wrap"', self.html)
        self.assertEqual(self.html.count('id="help-exclude-query"'), 1)

    def test_style_maker_moved_controls_retain_modal_help_and_accessible_tooltips(self):
        dom = ElementContractParser(self.html)
        self.assertIn("ratingTagRulesModal", dom.ancestor_ids("help-rating-exclusion"))
        self.assertIn("styleSharedMixModal", dom.ancestor_ids("sharedDependencyRatioSummary"))
        self.assertIn("합계 100%", dom.by_id["sharedDependencyRatioSummary"]["text"])
        self.assertIn("후보가 부족하면", dom.by_id["sharedDependencyRatioSummary"]["text"])
        self.assertIn("순서 0은", dom.by_id["weightTableModal"]["text"])
        self.assertIn(".help-tooltip-wrap:focus-within", self.css)
        self.assertIn("z-index: 1001", self.css)

    def test_high_score_preference_remains_with_artist_conditions(self):
        dom = ElementContractParser(self.html)
        self.assertIn("styleArtistsPanel", dom.ancestor_ids("preferHighScores"))
        self.assertIn("styleArtistsPanel", dom.ancestor_ids("styleScoreButtons"))
        self.assertEqual("checkbox", dom.by_id["preferHighScores"]["attrs"]["type"])

    def test_novelai_v5_model_controls_and_usage_contract(self):
        for marker in (
            'id="generationModel"', 'value="nai-diffusion-5-full"', 'value="nai-diffusion-5-curated"',
            'value="nai-diffusion-4-5-full"', 'value="nai-diffusion-4-5-curated"',
            'id="generationComplexity"', 'value="ultra"', 'id="generationQualityToggle"',
            'id="characterPromptLimitStatus"', 'id="generationModelBadge"',
            'id="novelAiUsage"', 'id="refreshNovelAiUsage"', 'id="novelAiUsageCountdown"',
            'id="styleManagerModelFilter"', 'id="confirmedStyleModelBadge"',
            'value="NovelAI Diffusion V5 Full"', 'value="NovelAI Diffusion V5 Curated"',
            'id="confirmedStyleComplexity"', 'id="comparisonDefaultComplexity"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        for marker in (
            "NOVELAI_MODEL_DEFINITIONS", "normalizeNovelAiModel", "maxCharacterPrompts: 22",
            "maxCharacterPrompts: 6", "normalizeNovelAiComplexity", "validateCharacterPromptLimit",
            "quality_toggle", "function renderNovelAiUsage", "timeUntilNextPercent",
            "createNovelAiModelBadge", "styleManagerModelFilter", "query.set(\"model\"",
            "confirmedStyleComplexity", "comparisonDefaultComplexity", "settings.complexity || style.complexity",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)
        for marker in (".model-badge", ".novelai-usage-panel", ".model-limit-status", "@media (max-width: 760px)"):
            self.assertIn(marker, self.css)


if __name__ == "__main__":
    unittest.main()
