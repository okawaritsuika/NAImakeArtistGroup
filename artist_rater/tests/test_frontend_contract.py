import unittest
from pathlib import Path
import subprocess


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "templates" / "index.html"
APP_BEHAVIOR_TEST = Path(__file__).resolve().parent / "app_behavior.test.js"


class FrontendContractTest(unittest.TestCase):
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

    def test_rating_editor_can_update_or_clear_the_query_prompt(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn('queryInput.dataset.edit = "query-text"', source)
        self.assertIn('query_text: card.querySelector(\'[data-edit="query-text"]\').value', source)

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
