import unittest
from pathlib import Path
import subprocess


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "templates" / "index.html"
APP_BEHAVIOR_TEST = Path(__file__).resolve().parent / "app_behavior.test.js"


class FrontendContractTest(unittest.TestCase):
    def test_tooltips_escape_panel_clipping_with_viewport_positioning(self):
        source = APP_JS.read_text(encoding="utf-8")
        css = (APP_JS.parent / "style.css").read_text(encoding="utf-8")
        self.assertIn("function initializeHelpTooltips()", source)
        self.assertIn("getBoundingClientRect()", source)
        self.assertIn("document.body.appendChild(entry.content)", source)
        self.assertIn("showPopover()", source)
        self.assertIn("window.addEventListener(\"scroll\", () => active && positionTooltip(active), true)", source)
        self.assertIn(".help-tooltip-content.is-open", css)
        self.assertIn("position: fixed", css)
        self.assertIn("max-height: calc(100vh - 24px)", css)

    def test_sample_viewer_always_starts_at_first_randomized_sample(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("state.sampleIndex = 0;", source)
        self.assertNotIn("Math.floor(Math.random() * data.samples.length)", source)

    def test_candidate_pool_shows_first_artist_and_asks_before_refilling(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("async function loadCandidatePool(force = false)", source)
        self.assertIn("if (state.candidatePool.length && !force) return true;", source)
        self.assertIn('title: "후보를 모두 확인했습니다"', source)
        self.assertIn('bindClick("candidateButton", async () => {', source)
        self.assertIn("if (loaded) await showNextArtist();", source)

    def test_candidate_picker_sends_exclusion_prompt_and_latest_option(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="excludeQueryText"', html)
        self.assertIn('id="excludeAutocomplete"', html)
        self.assertIn('id="latestSamples"', html)
        self.assertIn('exclude_query_text: valueOf("excludeQueryText")', source)
        self.assertIn('latest_samples: Boolean($("latestSamples")?.checked)', source)
        self.assertIn('updateAutocomplete("exclude")', source)
        self.assertIn('handleAutocompleteKeydown(event, "exclude")', source)

    def test_candidate_picker_exposes_cutoff_presets_and_propagates_selected_date(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="candidateCutoffPreset"', html)
        self.assertIn('value="2025-01-31"', html)
        self.assertIn('value="2026-06-15"', html)
        self.assertIn('value="custom"', html)
        self.assertIn('id="candidateCutoffDate"', html)
        self.assertIn("selectedCandidateCutoffDate()", source)
        self.assertIn("cutoff_date: selectedCandidateCutoffDate()", source)
        self.assertIn("cutoff_date: state.candidateMeta.cutoff_date", source)

    def test_candidate_skip_is_persisted_before_loading_next_artist_and_can_be_cleared(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="skipArtist"', html)
        self.assertIn('id="clearSkippedArtists"', html)
        self.assertIn('id="skippedArtistsModal"', html)
        self.assertIn('id="skippedArtistsList"', html)
        self.assertIn('id="clearAllSkippedArtists"', html)
        self.assertIn("async function skipCurrentArtist()", source)
        self.assertIn('apiFetch("/api/skipped_artists", {', source)
        self.assertIn("saved = true;", source)
        self.assertIn("await showNextArtist();", source)
        self.assertIn("async function clearSkippedArtists()", source)
        self.assertIn("async function loadSkippedArtists()", source)
        self.assertIn("async function restoreSkippedArtist", source)
        self.assertIn("textContent = String(item.artist_tag", source)
        self.assertIn("state.seenArtists.delete(artist);", source)

    def test_delete_confirmations_are_category_scoped(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        for category in (
            "rating_example", "rating", "generated", "style", "arca_style",
            "comparison_group", "comparison_result", "novelai_key",
        ):
            self.assertIn(f'data-delete-confirmation-category="{category}"', html)
            self.assertIn(f'"{category}"', source)
        self.assertIn("delete_category", source)
        self.assertIn("appPreferences.skip_delete_confirmation[category]", source)

    def test_rating_editor_can_update_or_clear_the_query_prompt(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn('queryInput.dataset.edit = "query-text"', source)
        self.assertIn('query_text: card.querySelector(\'[data-edit="query-text"]\').value', source)

    def test_prompt_inputs_use_shared_autocomplete_for_static_and_dynamic_rating_fields(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("function bindManualTagsAutocomplete()", source)
        self.assertIn('window.addEventListener("load", bindManualTagsAutocomplete', source)
        self.assertIn('queryField.className = "field inline-edit-query-field"', source)
        self.assertIn('queryAutocomplete.className = "autocomplete prompt-tag-autocomplete hidden"', source)
        self.assertIn("globalThis.promptTagAutocomplete?.bind(queryInput)", source)

    def test_rating_cards_offer_danbooru_search_and_sample_viewer(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        css = (APP_JS.parent / "style.css").read_text(encoding="utf-8")
        self.assertIn("function buildDanbooruSearchUrl", source)
        self.assertIn("function buildDanbooruPostUrl", source)
        self.assertIn("async function openRatingSampleViewer", source)
        self.assertIn("await loadStoredRatingExamples()", source)
        self.assertIn("new URLSearchParams()", source)
        self.assertIn('searchLink.dataset.action = "danbooru-search"', source)
        self.assertIn('thumbButton.dataset.action = "open-samples"', source)
        self.assertIn('findThumbnail.textContent = thumb ? "WebP 썸네일 갱신" : "WebP 썸네일 받기"', source)
        self.assertIn('고화질 WebP 썸네일을 준비하는 중입니다', source)
        self.assertIn('async function loadManualPreviewSamples', source)
        self.assertIn('async function loadStoredRatingExamples', source)
        self.assertIn('async function collectRatingExamples', source)
        self.assertIn('async function setRatingExampleThumbnail', source)
        self.assertIn('async function deleteRatingExample', source)
        self.assertIn('`/api/ratings/${ratingId}/examples`', source)
        self.assertIn('`/api/ratings/${state.manualPreviewRatingId}/examples/collect`', source)
        self.assertIn('`/api/ratings/${state.manualPreviewRatingId}/examples/${sample.example_id}/thumbnail`', source)
        self.assertIn('`/api/ratings/${state.manualPreviewRatingId}/examples/${sample.example_id}`', source)
        self.assertIn('artist_tag: artist', source)
        self.assertIn('query_tags: state.manualPreviewQueryTags', source)
        self.assertIn('sample_limit: 10', source)
        self.assertIn('id="manualPreviewLoadMore"', html)
        self.assertIn('id="manualPreviewModal"', html)
        self.assertIn('id="manualPreviewSetThumbnail"', html)
        self.assertIn('id="manualPreviewDeleteExample"', html)
        self.assertIn('id="manualPreviewRepresentativeBadge"', html)
        self.assertIn(".thumb-button", css)
        self.assertIn("cursor: zoom-in", css)
        self.assertIn(".manual-preview-example-actions", css)

    def test_unrated_rating_filter_is_exposed_to_api(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('data-filter="unrated"', html)
        self.assertIn('params.set("rating_status", "unrated")', source)

    def test_manual_preview_actions_stay_in_header_and_viewer_uses_remaining_row(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        css = (APP_JS.parent / "style.css").read_text(encoding="utf-8")
        modal = html.split('id="manualPreviewModal"', 1)[1].split('id="confirmedStyleModal"', 1)[0]
        header = modal.split('id="manualPreviewStatus"', 1)[0]
        self.assertIn('class="modal-dialog manual-preview-dialog"', modal)
        self.assertIn('class="modal-head manual-preview-head"', modal)
        self.assertIn('id="manualPreviewLoadMore"', header)
        self.assertIn('id="manualPreviewLoadMore" class="primary"', header)
        self.assertIn('id="manualPreviewClose"', header)
        self.assertNotIn('id="manualPreviewLoadMore"', modal.split('id="manualPreviewStatus"', 1)[1])
        self.assertIn(".manual-preview-actions", css)
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("grid-template-rows: auto auto minmax(0, 1fr)", css)
        self.assertIn("representative_preview_url: preview.sample.large_url || preview.sample.preview_url", source)
        self.assertIn("representative_preview_url: sample?.large_url || sample?.preview_url", source)

    def test_manual_artist_preview_uses_modal_and_sample_api(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="manualPreviewButton"', html)
        self.assertIn('id="manualPreviewModal"', html)
        self.assertIn('async function openManualPreview()', source)
        self.assertIn('apiFetch("/api/artist_samples"', source)

    def test_native_dialogs_are_replaced_with_the_shared_designed_modal(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="appDialog"', html)
        self.assertIn('id="appDialogConfirm"', html)
        self.assertIn("function openAppDialog(options = {})", source)
        self.assertNotIn("window.confirm(", source)
        self.assertNotIn('if (!confirm("', source)

    def test_rating_card_behavior_with_node(self):
        result = subprocess.run(
            ["node", "--test", str(APP_BEHAVIOR_TEST)],
            cwd=APP_JS.parent.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
