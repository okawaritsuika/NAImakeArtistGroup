import unittest
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "templates" / "index.html"


class FrontendContractTest(unittest.TestCase):
    def test_sample_viewer_always_starts_at_first_randomized_sample(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("state.sampleIndex = 0;", source)
        self.assertNotIn("Math.floor(Math.random() * data.samples.length)", source)

    def test_candidate_pool_only_refills_automatically_when_empty(self):
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("async function loadCandidatePool(force = false)", source)
        self.assertIn("if (state.candidatePool.length && !force) return true;", source)

    def test_manual_artist_preview_uses_modal_and_sample_api(self):
        source = APP_JS.read_text(encoding="utf-8")
        html = INDEX_HTML.read_text(encoding="utf-8")
        self.assertIn('id="manualPreviewButton"', html)
        self.assertIn('id="manualPreviewModal"', html)
        self.assertIn('async function openManualPreview()', source)
        self.assertIn('apiFetch("/api/artist_samples"', source)


if __name__ == "__main__":
    unittest.main()
