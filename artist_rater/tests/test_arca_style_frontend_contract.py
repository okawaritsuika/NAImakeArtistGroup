import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArcaStyleFrontendContractTest(unittest.TestCase):
    def test_archive_ui_contract(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'data-tab="arca-style-collector"', 'id="arca-style-collector-tab"',
            'id="collectArcaStyles"', 'id="arcaSearchCoverage"', 'id="arcaStyleList"',
            'id="arcaStyleDialog"', 'id="saveArcaStyle"', 'id="deleteArcaStyle"',
            'id="arcaStyleSourceLink"',
            'id="arcaCollectionState"', 'id="arcaCollectionProgress"',
            'id="arcaCollectionCounts"', 'id="arcaCollectionElapsed"', 'id="arcaCollectionEta"',
            'id="arcaDirectUrl"', 'id="collectArcaUrl"',
            'id="arcaBrowserSessionState"', 'id="importArcaBrowserSession"',
            'id="arcaStyleSort"',
            'value="recommend_desc"', 'value="views_desc"',
            "arca_style_collector.js",
        ):
            self.assertIn(marker, html)
        self.assertNotIn('id="arcaKeyword"', html)
        self.assertNotIn('id="arcaMaxPages"', html)
        self.assertNotIn('id="arcaMaxPosts"', html)

    def test_archive_script_uses_safe_dom_and_required_operations(self):
        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        for marker in (
            "loadArcaStyles", "collectArcaStyles", "pollArcaCollectionJob",
            "openArcaStyle", "renderArcaStyleGroups", "saveArcaStyle", "deleteArcaStyle",
            "collectArcaUrl",
            "loadArcaBrowserSession", "importArcaBrowserSession",
        ):
            self.assertIn(f"function {marker}", source)
        self.assertIn("arca-image-prompt-card", source)
        self.assertIn("베이스", source)
        self.assertIn("네거티브", source)
        self.assertIn("캐릭터", source)
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn("arca-detail-edit", source + html)
        self.assertIn("arca-dialog-actions", source + html)
        self.assertIn("arca-dialog-scroll", html)
        self.assertIn("arca-image-prompt-viewer", source)
        self.assertIn("arca-prompt-textarea", source)
        self.assertIn("arca-selected-image-preview", source)
        self.assertIn('arcaEl("arcaStyleSourceLink").href = item.source_url', source)
        self.assertIn("item.recommendation_count", source)
        self.assertIn("item.view_count", source)
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".arca-style-list-scroll", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn("max-height: max(260px, calc(100vh - 360px))", css)
        self.assertIn("grid-auto-rows: max-content", css)
        self.assertIn(".arca-style-meta span", css)
        self.assertIn("min-height: 220px", css)
        self.assertNotIn(".arca-style-list-scroll { overflow: visible;", css)


if __name__ == "__main__":
    unittest.main()
