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
            'id="styleArtistSelect"',
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
        settings_start = self.html.index('id="styleMakerSettings"')
        editor_start = self.html.index('id="styleMakerEditor"')
        preview_index = self.html.index('id="weightGraphPreview"')
        result_index = self.html.index('id="latestStyleResult"')
        self.assertLess(settings_start, preview_index)
        self.assertLess(preview_index, editor_start)
        self.assertGreater(result_index, editor_start)

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
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        source = JS_PATH.read_text(encoding="utf-8")
        self.assertIn("function selectPromptTab", source)

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
            "styleScoreAll",
            "weightMode",
        ):
            with self.subTest(control_id=control_id):
                self.assertIn(f'"{control_id}"', source)

    def test_settings_continuous_generation_and_manager_controls_exist(self):
        source = JS_PATH.read_text(encoding="utf-8")
        for marker in (
            'id="settingsModal"', 'id="novelAiAppKey"', 'id="testNovelAiKey"',
            'id="generationLimitMode"', 'id="generationCount"', 'id="styleChangeMode"',
            'id="startContinuous"', 'id="pauseContinuous"', 'id="stopContinuous"',
            'data-tab="style-manager"', 'id="styleManagerList"', 'id="styleManagerDetail"',
            'id="generatedImageModal"', 'id="generatedImagePrev"', 'id="generatedImageNext"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)
        self.assertIn("async function runContinuousGeneration()", source)
        self.assertIn("await generateCurrentStyle()", source)
        self.assertIn("async function loadStyleManager()", source)
        self.assertIn("function renderGeneratedImageModal()", source)

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
