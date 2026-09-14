import io
import json
import unittest

from PIL import Image, PngImagePlugin

from arca_style_collector import extract_novelai_metadata
from shared_style_webp import verified_webp
from tests.test_arca_style_collector import png_with_stealth, webp_with_exif_user_comment


class SharedStyleWebpTest(unittest.TestCase):
    def setUp(self):
        self.metadata = {
            "prompt": "artist:test, 한글, 日本語, {weighted}",
            "uc": "bad quality, 글자", "model": "nai-diffusion-5-full",
            "seed": 4294967295, "steps": 28, "sampler": "k_euler",
            "scale": 5.5, "qualityToggle": False, "ucPreset": 0,
            "v4_prompt": {"caption": {"base_caption": "artist:test, 한글",
                "char_captions": [{"char_caption": "red hair, 日本語",
                    "centers": [{"x": 0.25, "y": 0.75}]}]}},
            "v4_negative_prompt": {"caption": {"base_caption": "bad quality",
                "char_captions": [{"char_caption": "blue hair"}]}},
            "unknown_future_setting": {"keep": [False, None, 1.25]},
        }

    def assert_round_trip(self, data):
        converted = verified_webp(data)
        before, after = [extract_novelai_metadata(x) for x in (data, converted)]
        for value in (before, after):
            value["raw_metadata_json"] = json.loads(value["raw_metadata_json"])
        self.assertEqual(before, after)
        self.assertEqual(converted[8:12], b"WEBP")

    def test_text_png_preserves_all_settings_and_character_prompts(self):
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", json.dumps(self.metadata, ensure_ascii=False))
        output = io.BytesIO()
        Image.new("RGB", (32, 48), (30, 50, 90)).save(output, "PNG", pnginfo=info)
        self.assert_round_trip(output.getvalue())

    def test_stealth_png_copies_metadata_out_of_pixels(self):
        self.assert_round_trip(png_with_stealth(self.metadata))

    def test_existing_webp_exif_preserves_unicode(self):
        self.assert_round_trip(webp_with_exif_user_comment(self.metadata))

    def test_missing_metadata_is_rejected(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, "PNG")
        with self.assertRaisesRegex(ValueError, "metadata is required"):
            verified_webp(output.getvalue())
