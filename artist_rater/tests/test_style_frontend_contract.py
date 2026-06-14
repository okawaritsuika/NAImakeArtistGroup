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
            'value="custom"',
            'id="styleMinWeight"',
            'value="0.1"',
            'id="styleMaxWeight"',
            'value="2.3"',
            'id="preferHighScores"',
            'id="customRangeList"',
            'id="addWeightRange"',
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
            "minmax(220px, 300px)",
            "minmax(420px, 1fr)",
            "minmax(300px, 380px)",
            "overflow: auto",
            ".weight-column",
            "grid-template-columns: 1fr",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.css)

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
