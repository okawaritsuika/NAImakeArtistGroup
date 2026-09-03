import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StyleGroupFrontendContractTest(unittest.TestCase):
    def test_group_tab_review_and_keyboard_contract_are_present(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "static" / "style_groups.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        for marker in ("data-tab=\"style-group\"", "styleGroupChooseReference", "styleGroupStart", "styleGroupReview", "styleGroupTargetModal", "styleGroupSourceGalleryModal", "styleGroupExcludedModal", "styleGroupClearReference", "styleGroupGalleryActions", "styleGroupArtistSize", "styleGroupArtistSizeValue", "포함 작가 그림 크기", "styleGroupGalleryPreview", "styleGroupGalleryPreviewEmpty", "styleGroupRemoveArtistModal", "styleGroupReviewFocusToggle", "aria-controls=\"styleGroupReviewFocusBody\"", "style-group-gallery-layout", "style-group-review-cross", "style-group-review-decision-bar", "styleGroupPreviousSource", "styleGroupInclude", "styleGroupExclude", "styleGroupNextSource"):
            self.assertIn(marker, html)
        for marker in ("/api/style-groups", "artist-decision", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "isContentEditable", "textContent", "newTargetsOnly", "setTargetSelection", "sourceGalleryHelp", "targetCardKeyboardAction", "canStartGroupReview", "input.disabled", "normalizeArtistTag", "baseSourceIndex", "filterArtistGalleryImages", "Danbooru 그림 가져오기", "기본 테스트 없음", "source.label", "dblclick", "renderGalleryImages", "updateGalleryPreview", "galleryImageLabel", "artistGallerySizeValue", "setArtistGallerySize", "aria-pressed", "role", "checkbox", "aria-checked", "aria-disabled", "tabindex", "keydown", "setReviewFocusExpanded", "confirmRemoveArtist", "styleGroupArtistSize", "styleGroupGalleryDanbooru", "styleGroupGalleryNaiTest", "naiArtistTestGenerationPreflight", "remove-artist", "method: \"DELETE\""):
            self.assertIn(marker, source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("REFERENCE_CLICK_DELAY_MS", source)
        self.assertNotIn("styleGroupImageModal", html + source)
        self.assertNotIn("styleGroupGallerySize", html + source)
        self.assertNotIn("갤러리 그림 크기", html + source)
        self.assertNotIn("openLargeImage", source)
        self.assertNotIn("썸네일 크기", html)
        self.assertIn("grid-template-columns: 1fr", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", css)
        self.assertIn(".style-group-gallery-layout", css)
        self.assertIn("width: min(980px, 100%)", css)
        self.assertIn("--style-group-artist-size", css)
        self.assertIn("min(100%, var(--style-group-artist-size", css)
        self.assertIn("max-height: calc(100dvh - 24px)", css)
        self.assertIn("height: auto", css)
        self.assertIn("height: auto; max-height: 360px", css)
        self.assertNotIn("aspect-ratio: 4 / 3", css)
        style_group_css = css[css.index("/* Author-centered style-group wizard and galleries. */"):]
        self.assertIn(".style-group-artist-card img", style_group_css)
        self.assertIn("height: auto; aspect-ratio: 1 / 1", style_group_css)
        self.assertIn(".style-group-artist-thumb-empty", style_group_css)
        self.assertNotIn("height: 150px", style_group_css)
        self.assertNotIn("height: 190px", style_group_css)
        self.assertNotIn("min-height: 190px", style_group_css)
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn(".style-group-target-card.is-selected", css)
        self.assertIn("focus-visible", css)
        self.assertIn("cursor: pointer", css)

    def test_review_stages_share_aligned_desktop_geometry(self):
        html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        review = html[html.index('id="styleGroupReview"'):]
        review_head_start = review.index('class="style-group-review-head"')
        review_focus_start = review.index('class="style-group-review-focus-head"', review_head_start)
        review_head = review[review_head_start:review_focus_start]
        review_tools_start = review_head.index('class="style-group-review-tools"')
        self.assertNotIn('id="styleGroupBack"', review_head[:review_tools_start])
        review_tools = review_head[review_tools_start:]
        self.assertIn('id="styleGroupBack"', review_tools)
        self.assertGreater(review_tools.index('id="styleGroupBack"'), review_tools.index('id="styleGroupExcludedOpen"'))
        candidate_heading = review.index('class="style-group-review-stage-heading style-group-artist-heading"')
        candidate_stage = review.index('class="style-group-image-stage style-group-review-cross"')
        cross_start = candidate_stage
        candidate_tools = review.index('class="style-group-candidate-tools"')
        source_list = review.index('id="styleGroupSourceList"')
        self.assertLess(candidate_heading, candidate_stage)
        self.assertLess(candidate_stage, candidate_tools)
        self.assertLess(candidate_tools, source_list)
        self.assertIn('class="style-group-image-stage"><img id="styleGroupReferenceImage"', review)
        stage_end = review.index('</div><div class="style-group-review-decision-bar"', cross_start)
        cross = review[cross_start:stage_end]
        self.assertIn('class="style-group-image-stage style-group-review-cross"><img id="styleGroupCandidateImage"', cross)
        self.assertIn('id="styleGroupCandidateEmpty"', cross)
        for control_id in ("styleGroupPreviousSource", "styleGroupInclude", "styleGroupExclude", "styleGroupNextSource"):
            self.assertNotIn('id="' + control_id + '"', cross)
        decision_start = review.index('class="style-group-review-decision-bar"')
        decision_end = review.index('</div><div class="style-group-candidate-tools"', decision_start)
        decision_bar = review[decision_start:decision_end]
        self.assertIn('role="group"', decision_bar)
        for control_id in ("styleGroupPreviousSource", "styleGroupInclude", "styleGroupExclude", "styleGroupNextSource"):
            self.assertIn('id="' + control_id + '"', decision_bar)
        self.assertNotIn("style-group-review-image-overlay", review)
        self.assertIn(".style-group-review-stage-heading", css)
        self.assertIn(".style-group-reference-panel .style-group-image-stage, .style-group-candidate-panel .style-group-image-stage", css)
        self.assertIn("height: min(60vh, 540px); min-height: 0", css)
        self.assertIn(".style-group-review-cross { width: 100%;", css)
        self.assertIn(".style-group-review-decision-bar", css)
        self.assertNotIn(".style-group-review-cross > button", css)
        self.assertIn(".style-group-review-decision-bar #styleGroupInclude", css)
        self.assertIn(".style-group-review-decision-bar #styleGroupExclude", css)
        decision_rule = css.index(".style-group-review-decision-bar {\n")
        mobile_rule = css.rindex("@media (max-width: 720px)")
        self.assertLess(decision_rule, mobile_rule)
        self.assertIn(".style-group-review-decision-bar { grid-template-columns: repeat(2, minmax(0, 1fr)); }", css[mobile_rule:])
        self.assertIn("min-height: 44px", css)

    def test_group_card_actions_are_compact_single_row_with_mobile_targets(self):
        css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
        actions = re.search(r"\.style-group-card-actions\s*\{(?P<body>.*?)\}", css, re.S)
        self.assertIsNotNone(actions)
        action_body = actions.group("body")
        self.assertIn("display: grid", action_body)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto auto", action_body)
        self.assertIn("gap: 6px", action_body)
        self.assertIn("width: 100%", action_body)
        self.assertIn("min-width: 0", action_body)
        self.assertIn("margin-top: 10px", action_body)
        self.assertNotIn("flex-wrap", action_body)

        buttons = re.search(r"\.style-group-card-actions button\s*\{(?P<body>.*?)\}", css, re.S)
        self.assertIsNotNone(buttons)
        button_body = buttons.group("body")
        self.assertIn("min-width: 0", button_body)
        self.assertIn("min-height: 34px", button_body)
        self.assertIn("padding: 5px 8px", button_body)
        self.assertIn("font-size: .82rem", button_body)
        self.assertIn("line-height: 1.35", button_body)
        self.assertIn("white-space: nowrap", button_body)

        card_title = re.search(r"\.style-group-card h3\s*\{(?P<body>.*?)\}", css, re.S)
        self.assertIsNotNone(card_title)
        self.assertIn("font-size: 1rem", card_title.group("body"))
        self.assertIn("line-height: 1.35", card_title.group("body"))
        self.assertIn(".style-group-card .help-text { font-size: .8rem; line-height: 1.35", css)
        mobile = css.rindex("@media (max-width: 720px)")
        self.assertIn(".style-group-card-actions button { min-height: 44px; }", css[mobile:])

    def test_direct_artist_prompt_and_review_stages_use_shared_hooks(self):
        source = (ROOT / "static" / "style_groups.js").read_text(encoding="utf-8")
        self.assertIn('const directArtist = $("styleGroupDirectArtist");', source)
        self.assertIn("globalThis.promptTagAutocomplete?.bind?.(directArtist)", source)
        self.assertIn('classList.toggle("is-empty", !referenceSrc)', source)
        self.assertIn('classList.toggle("is-empty", !candidateSrc)', source)
        self.assertIn("globalThis.promptTagAutocomplete?.hide?.()", source)


if __name__ == "__main__":
    unittest.main()
