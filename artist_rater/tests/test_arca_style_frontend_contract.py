import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArcaStyleFrontendContractTest(unittest.TestCase):
    def test_archive_ui_contract(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'data-tab="arca-style-collector"', 'id="arca-style-collector-tab"',
            'data-tab="arca-style-statistics"', 'id="arca-style-statistics-tab"',
            'id="collectArcaStyles"', 'id="restoreArcaImages"',
            'id="confirmRestoreArcaImages"', 'id="cancelRestoreArcaImages"',
            'id="arcaSearchCoverage"', 'id="arcaStyleList"',
            'id="arcaStyleDialog"', 'id="saveArcaStyle"', 'id="deleteArcaStyle"',
            'id="arcaStyleSourceLink"',
            'id="arcaCollectionState"', 'id="arcaCollectionProgress"',
            'id="arcaCollectionCounts"', 'id="arcaCollectionElapsed"', 'id="arcaCollectionEta"',
            'id="pauseArcaCollection"', 'id="resumeArcaCollection"', 'id="stopArcaCollection"',
            'id="arcaDirectUrl"', 'id="collectArcaUrl"',
            'id="arcaBrowserSessionState"', 'id="importArcaBrowserSession"',
            'id="setupArcaSessionBridge"', 'id="refreshArcaBrowserSession"',
            'id="arcaSessionBridgeSetupStatus"', 'chrome://extensions',
            'id="arcaStyleSort"', 'id="arcaRecommendationMinList"',
            'id="arcaStylePageSize"', 'id="arcaStyleCardSize"',
            'id="arcaStylePagination"', 'id="arcaStylePrevPage"', 'id="arcaStyleNextPage"',
            'id="arcaStylePageInput"', 'id="arcaStyleGoPage"',
            'id="arcaStyleStatistics"', 'class="arca-statistics-content"', 'id="arcaStyleStatisticsSummary"',
            'id="arcaStyleStatisticsStatus"',
            'id="arcaRecommendationPreset"', 'id="arcaRecommendationMin"',
            'id="arcaRecommendationMax"', 'id="applyArcaRecommendationFilter"',
            'id="arcaArtistStatisticsRows"', 'id="arcaQualityStatisticsRows"',
            'id="arcaArtistWeightRange"', 'id="arcaArtistStatisticsPageSize"',
            'id="arcaQualityWeightRange"', 'id="arcaQualityStatisticsPageSize"',
            'id="arcaArtistStatisticsPrev"', 'id="arcaArtistStatisticsNext"',
            'id="arcaQualityStatisticsPrev"', 'id="arcaQualityStatisticsNext"',
            'data-arca-stat-kind="artist"', 'data-arca-stat-kind="quality"',
            'data-arca-sort-key="recommendation_max"', 'id="arcaTagRelatedTitle"',
            'id="arcaTagStatisticsModal"', 'id="arcaTagImageModal"',
            'id="arcaTagWeightRows"', 'id="arcaTagImageGallery"',
            'id="arcaTagRelatedTags"', 'id="arcaTagImageSourceLink"',
            'id="arcaQualitySequenceRows"', 'id="arcaSequenceModal"',
            'id="arcaSequenceStatisticsSort"',
            'id="arcaSequenceImageGallery"', 'id="arcaTagImagePrompt"',
            'data-arca-statistics-view="artist"', 'data-arca-statistics-view="quality"',
            'data-arca-statistics-view="sequence"', 'id="arcaStatisticsSampleGallery"',
            'id="shuffleArcaStatisticsImages"',
            'value="recommend_desc"', 'value="views_desc"',
            "arca_style_collector.js",
        ):
            self.assertIn(marker, html)
        self.assertNotIn('id="arcaKeyword"', html)
        self.assertNotIn('id="arcaMaxPages"', html)
        self.assertNotIn('id="arcaMaxPosts"', html)
        self.assertIn("먼저 아래 버튼으로 필요한 용량과 시간을 확인하세요", html)

        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".arca-collector-panel", css)
        self.assertIn("overflow-y: auto", css)

    def test_archive_script_uses_safe_dom_and_required_operations(self):
        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        for marker in (
            "loadArcaStyles", "collectArcaStyles", "pollArcaCollectionJob",
            "openArcaStyle", "renderArcaStyleGroups", "saveArcaStyle", "deleteArcaStyle",
            "collectArcaUrl", "restoreArcaImages", "loadArcaImageRestoreEstimate",
            "loadArcaBrowserSession", "importArcaBrowserSession",
            "setupArcaSessionBridge", "loadArcaSearchCoverage", "loadArcaStyleStatistics",
            "renderArcaPagination", "applyArcaCardSize", "goToArcaPage",
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
        self.assertIn("/api/arca-styles/statistics", source)
        self.assertIn("/api/arca-styles/statistics/tag", source)
        self.assertIn("/api/arca-styles/statistics/sequence", source)
        self.assertIn("filterAndSortArcaStatisticRows", source)
        self.assertIn("paginateArcaStatisticRows", source)
        self.assertIn("arca-statistic-inline-image", source)
        self.assertIn("함께 사용된 다른 작가", source)
        self.assertIn("openArcaTagImage", source)
        self.assertNotIn("qualityNetworkLayout", source)
        self.assertNotIn('id="arcaQualityNetworkSvg"', html)
        self.assertNotIn('id="arcaQualityBundleRows"', html)
        self.assertNotIn("data-arca-tag-view", html)
        self.assertIn("randomArcaStatisticsSamples", source)
        self.assertIn("arcaStatisticsQuery", source)
        self.assertIn("recommendation_desc", source + html)
        self.assertIn("loadCurrentArcaCollectionJob", source)
        self.assertIn("controlArcaCollection", source)
        self.assertIn("/api/arca-styles/collection-jobs/current", source)
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".arca-style-list-scroll", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn("max-height: max(260px, calc(100vh - 360px))", css)
        self.assertIn("grid-auto-rows: max-content", css)
        self.assertIn(".arca-style-meta span", css)
        self.assertIn(".arca-statistics-view.active", css)
        self.assertIn(".arca-tag-image-gallery", css)
        self.assertIn(".arca-tag-statistics-dialog", css)
        self.assertIn(".arca-tag-image-dialog", css)
        self.assertIn(".arca-weight-statistics-table", css)
        self.assertIn(".arca-related-tags", css)
        self.assertIn("max-height: 180px", css)
        self.assertIn("relatedList.scrollTop = 0", source)
        self.assertIn(".arca-statistics-sample-gallery", css)
        self.assertIn(".arca-statistics-content", css)
        self.assertIn(".arca-recommendation-filter", css)
        self.assertIn(".arca-statistics-sort-button", css)
        self.assertIn(".arca-statistic-inline-image", css)
        self.assertIn("grid-template-columns: 92px", css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", css)
        self.assertIn("max-height: 620px", css)
        self.assertIn("font-size: 14px; white-space: nowrap", css)
        self.assertIn(".arca-statistics-table { width: 100%; min-width: 860px; border-collapse: collapse; font-size: 15px; }", css)
        self.assertIn(".arca-statistics-table td.is-number { text-align: left", css)
        self.assertIn(".arca-statistics-table th:not(:last-child)", css)
        self.assertIn("const sampleLimits = { artist: 12, quality: 15, sequence: 12 }", source)
        self.assertIn(".arca-statistics-pagination", css)
        self.assertIn(".arca-collection-control-actions", css)
        self.assertIn("--arca-card-height: 220px", css)
        self.assertIn('.arca-style-list[data-card-size="small"] .arca-style-card', css)
        self.assertIn("aspect-ratio: 1 / 1", css)
        self.assertIn(".arca-style-pagination", css)
        self.assertNotIn(".arca-style-list-scroll { overflow: visible;", css)


if __name__ == "__main__":
    unittest.main()
