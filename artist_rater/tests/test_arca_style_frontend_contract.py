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
            'id="downloadArcaImageArchive"', 'id="chooseArcaImageArchive"',
            'id="arcaImageArchiveFile"', 'id="arcaImageArchiveStatus"',
            'id="confirmRestoreArcaImages"', 'id="cancelRestoreArcaImages"',
            'id="arcaSearchCoverage"', 'id="arcaStyleList"',
            'id="arcaCollectorPanel"', 'id="arcaKeyword"',
            'id="arcaStyleDialog"', 'id="saveArcaStyle"', 'id="deleteArcaStyle"',
            'id="arcaStyleSourceLink"',
            'id="arcaCollectionProgressPanel"', 'id="arcaCollectionState"', 'id="arcaCollectionProgress"',
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
            'id="arcaStatisticsModelFilter"', 'value="v5"', 'value="v4.5"',
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
        self.assertIn('value="그림체 공유"', html)
        self.assertIn("입력한 검색어가 포함된 제목만 검색합니다.", html)
        self.assertNotIn('id="arcaMaxPages"', html)
        self.assertNotIn('id="arcaMaxPosts"', html)
        self.assertIn("먼저 아래 버튼으로 필요한 용량과 시간을 확인하세요", html)

        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".arca-collector-panel", css)
        self.assertIn("overflow-y: auto", css)
        self.assertIn(".arca-collector-panel-body", css)
        self.assertIn(".arca-collector-panel:not([open]) { width: fit-content", css)
        self.assertIn(".arca-collector-panel:not([open]) > summary { overflow-wrap: anywhere; font-size: 0; }", css)
        self.assertIn(".arca-collector-panel:not([open]) > summary::marker { font-size: 1rem; }", css)

    def test_archive_script_uses_safe_dom_and_required_operations(self):
        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        for marker in (
            "loadArcaStyles", "collectArcaStyles", "pollArcaCollectionJob",
            "openArcaStyle", "renderArcaStyleGroups", "saveArcaStyle", "deleteArcaStyle",
            "collectArcaUrl", "restoreArcaImages", "prepareArcaImageRestore", "loadArcaImageRestoreEstimate",
            "startGoogleArcaImageArchive", "uploadLocalArcaImageArchive",
            "loadArcaBrowserSession", "importArcaBrowserSession",
            "setupArcaSessionBridge", "loadArcaSearchCoverage", "loadArcaStyleStatistics",
            "renderArcaPagination", "applyArcaCardSize", "goToArcaPage",
            "shouldOpenArcaCollectionPanel",
        ):
            self.assertIn(f"function {marker}", source)
        self.assertIn("arca-image-prompt-card", source)
        self.assertIn("arca-style-thumb-button", source)
        self.assertIn("openArcaStyle(item.id)", source)
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
        self.assertIn('model: arcaEl("arcaStatisticsModelFilter")?.value', source)
        self.assertIn('arcaEl("arcaStatisticsModelFilter")?.addEventListener("change"', source)
        self.assertIn("recommendation_desc", source + html)
        self.assertIn("loadCurrentArcaCollectionJob", source)
        self.assertIn("controlArcaCollection", source)
        self.assertIn("/api/arca-styles/collection-jobs/current", source)
        self.assertIn("/api/arca-styles/image-archive/google", source)
        self.assertIn("/api/arca-styles/image-archive/upload/start", source)
        self.assertIn('id="arcaImageDownloadOptions"', html)
        self.assertIn("imageDownloadSummary", source)
        self.assertNotIn("/api/arca-styles/restore-images/prepare", source)
        self.assertIn("await loadArcaImageRestoreEstimate()", source)
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
        self.assertIn("grid-template-columns: minmax(180px, 1.35fr) repeat(3, minmax(140px, 1fr)) auto", css)
        self.assertIn("@media (max-width: 700px) { .arca-recommendation-filter { grid-template-columns: 1fr 1fr; }", css)
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
        self.assertIn("aspect-ratio: auto", css)
        self.assertIn(".arca-style-list[data-card-size=\"small\"] .arca-style-actions button", css)
        self.assertIn(".arca-style-collector-view.active:has(.arca-collector-panel:not([open]))", css)
        self.assertIn(".arca-style-pagination", css)
        self.assertNotIn(".arca-style-list-scroll { overflow: visible;", css)

    def test_collection_search_keyword_and_coverage_actions_have_separate_contracts(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<details id="arcaCollectorPanel" class="arca-collector-panel panel" open>', html)
        self.assertIn("<summary>그림체 수집</summary>", html)
        self.assertIn('<div class="arca-collector-panel-body">', html)
        self.assertIn('<div id="arcaSearchCoverage" class="status arca-search-coverage"></div>', html)
        self.assertIn('<div class="arca-collection-actions">', html)

        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn('keyword: arcaEl("arcaKeyword")?.value', source)
        self.assertIn('arcaEl("arcaKeyword")?.addEventListener("input", scheduleArcaSearchCoverage)', source)
        self.assertIn('keyword: String(value.keyword || "그림체 공유").trim() || "그림체 공유"', source)

    def test_arca_edit_prompts_use_shared_autocomplete_and_close_hides_it(self):
        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        self.assertIn('"arcaEditPrompt", "arcaEditNegativePrompt"', source)
        self.assertIn("globalThis.promptTagAutocomplete?.bind?.(input)", source)
        self.assertIn("globalThis.promptTagAutocomplete?.hide?.()", source)
        self.assertNotIn('"arcaEditMemo"', source[source.index('"arcaEditPrompt", "arcaEditNegativePrompt"'):source.index('"arcaEditPrompt", "arcaEditNegativePrompt"') + 100])

    def test_image_level_model_filter_contract(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "arca_style_collector.js").read_text(encoding="utf-8")
        for marker in (
            'id="arcaModelFilter"', 'value="v5"', 'value="v4.5"',
            'value="nai-diffusion-5-full"', 'value="nai-diffusion-5-curated"',
            'value="nai-diffusion-4-5-full"', 'value="nai-diffusion-4-5-curated"',
            'value="unknown"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "normalizeArcaModel", "arcaModelDisplayName", 'model: arcaEl("arcaModelFilter")?.value',
            'query.set("model", model)', "arcaStyleDetailQuery", 'arcaEl("arcaModelFilter")?.value',
            "image.model", "createArcaModelBadge",
        ):
            self.assertIn(marker, source)
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn(".arca-image-choice .model-badge", css)

    def test_collection_filters_and_progress_can_collapse_compactly(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<details id="arcaStyleFilters" class="panel arca-style-filters" open>', html)
        self.assertIn("<summary>목록 검색과 필터</summary>", html)
        self.assertIn('<div class="arca-style-filter-fields">', html)
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: minmax(180px, 2fr) repeat(6, minmax(90px, 1fr))", css)
        self.assertIn(".arca-collection-progress:not([open])", css)
        self.assertIn("padding: 5px 10px", css)
        self.assertIn("--arca-card-height: 190px", css)
        self.assertIn("--arca-card-height: 170px", css)
        self.assertIn("--arca-card-height: 220px", css)


if __name__ == "__main__":
    unittest.main()
