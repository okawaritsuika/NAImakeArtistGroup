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
