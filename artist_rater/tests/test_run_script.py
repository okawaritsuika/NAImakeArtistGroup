import unittest
from pathlib import Path


class RunScriptTest(unittest.TestCase):
    def test_dependencies_are_installed_only_when_missing(self):
        script = (Path(__file__).resolve().parents[1] / "run.bat").read_text(encoding="utf-8")
        self.assertIn('python -c "import flask, requests, PIL, browser_cookie3, playwright"', script)
        self.assertIn("if errorlevel 1", script.lower())
        self.assertIn("python launcher.py", script)


if __name__ == "__main__":
    unittest.main()
