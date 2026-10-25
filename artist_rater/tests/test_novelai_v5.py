import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as app_module
from confirmed_style_store import normalize_confirmed_model_name, normalize_confirmed_style
from model_definitions import MODEL_DEFINITIONS, normalize_model_id
from app import _comparison_generation_data, _comparison_model
from novelai import (
    NAI_V5_MEDIUM_NEGATIVE_PROMPT,
    NovelAIError,
    build_generation_payload,
    generate_novelai_png,
    normalize_generation_data,
    test_novelai_subscription,
)
from tests.test_style_api import valid_png


def generation_data(**overrides):
    data = {
        "model": "nai-diffusion-5-full",
        "width": 832,
        "height": 1216,
        "steps": 23,
        "scale": 7.0,
        "cfg_rescale": 0.0,
        "sampler": "k_euler_ancestral",
        "noise_schedule": "native",
        "base_prompt": "1girl",
        "negative_prompt": "lowres",
        "character_prompts": [],
    }
    data.update(overrides)
    return data


class NovelAIV5BackendTest(unittest.TestCase):
    def test_central_definitions_have_required_models_and_limits(self):
        self.assertEqual(
            set(MODEL_DEFINITIONS).intersection(
                {
                    "nai-diffusion-5-full-medium",
                    "nai-diffusion-5-full",
                    "nai-diffusion-5-curated",
                    "nai-diffusion-4-5-full",
                    "nai-diffusion-4-5-curated",
                }
            ),
            {
                "nai-diffusion-5-full-medium",
                "nai-diffusion-5-full",
                "nai-diffusion-5-curated",
                "nai-diffusion-4-5-full",
                "nai-diffusion-4-5-curated",
            },
        )
        self.assertEqual(MODEL_DEFINITIONS["nai-diffusion-5-full"].max_character_prompts, 22)
        self.assertEqual(MODEL_DEFINITIONS["nai-diffusion-5-full-medium"].max_character_prompts, 22)
        self.assertEqual(MODEL_DEFINITIONS["nai-diffusion-4-5-full"].max_character_prompts, 6)

    def test_legacy_short_aliases_are_explicit_and_ambiguous_generation_names_are_rejected(self):
        for alias, expected in {
            "V5 Full Medium": "nai-diffusion-5-full-medium",
            "novelai diffusion v5 full medium": "nai-diffusion-5-full-medium",
            "NovelAI Diffusion V5 70AB5786": "nai-diffusion-5-full-medium",
            "NovelAI Diffusion V5 0ADF9AB7": "nai-diffusion-5-full",
            "NovelAI Diffusion V5 657484A5": "nai-diffusion-5-full",
            "NovelAI Diffusion V5 DB276663": "nai-diffusion-5-curated",
            "NAID5F": "nai-diffusion-5-full",
            "naid5c": "nai-diffusion-5-curated",
            "NAID4.5F": "nai-diffusion-4-5-full",
            "naid4.5c": "nai-diffusion-4-5-curated",
        }.items():
            with self.subTest(alias=alias):
                self.assertEqual(normalize_model_id(alias), expected)
        for ambiguous in ("V5", "V5 Medium", "NovelAI Diffusion V5", "V4.5", "NovelAI Diffusion V4.5"):
            with self.subTest(ambiguous=ambiguous):
                with self.assertRaises(ValueError):
                    normalize_model_id(ambiguous)
        self.assertEqual(
            normalize_confirmed_model_name("NovelAI Diffusion V4.5 4BDE2A90"),
            "NovelAI Diffusion V4.5 4BDE2A90",
        )

    def test_v5_payload_uses_existing_structured_prompt_wire_format(self):
        payload = build_generation_payload(
            generation_data(
                complexity="ultra",
                quality_toggle=True,
                character_prompts=["char"] * 22,
            ),
            "artist:test",
            42,
        )
        parameters = payload["parameters"]
        self.assertEqual(payload["model"], "nai-diffusion-5-full")
        self.assertIn("v4_prompt", parameters)
        self.assertIn("v4_negative_prompt", parameters)
        self.assertNotIn("v5_prompt", parameters)
        self.assertNotIn("complexity", parameters)
        self.assertTrue(parameters["qualityToggle"])
        self.assertIn("ultra complexity", payload["input"])
        self.assertEqual(len(parameters["v4_prompt"]["caption"]["char_captions"]), 22)

    def test_all_supported_v5_and_v45_ids_preserve_top_level_model_and_wire_shape(self):
        for model in (
            "nai-diffusion-5-full-medium",
            "nai-diffusion-5-full",
            "nai-diffusion-5-curated",
            "nai-diffusion-4-5-full",
            "nai-diffusion-4-5-curated",
        ):
            with self.subTest(model=model):
                payload = build_generation_payload(
                    generation_data(model=model), "artist:test", 42
                )
                self.assertEqual(payload["model"], model)
                self.assertEqual(payload["parameters"]["v4_prompt"]["caption"]["base_caption"], "artist:test, 1girl")
                self.assertIn("v4_prompt", payload["parameters"])
                self.assertIn("v4_negative_prompt", payload["parameters"])
                self.assertNotIn("v5_prompt", payload["parameters"])

    def test_medium_overrides_locked_options_without_mutating_high_settings(self):
        data = generation_data(
            model="nai-diffusion-5-full-medium", steps=40, sampler="k_dpmpp_2m",
            cfg_rescale=0.7, noise_schedule="native", variety_plus=True, uc_preset=4,
            negative_prompt="custom negative", base_prompt="landscape", scale=4.5,
            seed=123, complexity="high", quality_toggle=True,
            character_prompts=[f"character {index}" for index in range(22)],
        )
        original = dict(data)
        normalized = normalize_generation_data(data)
        for key, expected in {
            "steps": 14, "sampler": "k_euler_ancestral", "cfg_rescale": 0.0,
            "noise_schedule": "karras", "variety_plus": False, "uc_preset": 2,
            "skip_cfg_above_sigma": None,
            "negative_prompt": "nsfw, " + NAI_V5_MEDIUM_NEGATIVE_PROMPT,
        }.items():
            with self.subTest(key=key):
                self.assertEqual(normalized[key], expected)
        for key in ("base_prompt", "character_prompts", "scale", "seed", "width", "height", "complexity", "quality_toggle"):
            with self.subTest(preserved=key):
                self.assertEqual(normalized[key], data[key])
        self.assertEqual(data, original)
        data["model"] = "nai-diffusion-5-full"
        high = normalize_generation_data(data)
        for key in ("steps", "sampler", "cfg_rescale", "noise_schedule", "variety_plus", "uc_preset", "negative_prompt"):
            with self.subTest(high_setting=key):
                self.assertEqual(high[key], original[key])

    def test_medium_allows_omitted_locked_fields_but_validates_editable_fields(self):
        data = generation_data(model="nai-diffusion-5-full-medium")
        for key in ("steps", "sampler", "cfg_rescale", "negative_prompt"):
            data.pop(key)
        self.assertEqual(normalize_generation_data(data)["steps"], 14)
        for override, message in (
            ({"scale": 11}, "scale"),
            ({"character_prompts": ["character"] * 23}, "maximum 22"),
        ):
            with self.subTest(override=override):
                with self.assertRaisesRegex(ValueError, message):
                    normalize_generation_data(dict(data, **override))

    def test_medium_payload_uses_fixed_uc_with_empty_character_negatives(self):
        payload = build_generation_payload(
            generation_data(
                model="nai-diffusion-5-full-medium", base_prompt="landscape",
                character_prompts=["character one", "character two"],
                negative_prompt="ignored custom negative", steps=35, variety_plus=True,
                quality_toggle=False, complexity="medium", scale=4.5,
            ),
            "artist:test", seed=42,
        )
        parameters = payload["parameters"]
        self.assertEqual(payload["model"], "nai-diffusion-5-full-medium")
        self.assertEqual(payload["input"], "artist:test, landscape, medium complexity")
        self.assertEqual(parameters["negative_prompt"], "nsfw, " + NAI_V5_MEDIUM_NEGATIVE_PROMPT)
        self.assertEqual(parameters["v4_negative_prompt"]["caption"]["base_caption"], parameters["negative_prompt"])
        self.assertEqual(
            [entry["char_caption"] for entry in parameters["v4_negative_prompt"]["caption"]["char_captions"]],
            ["", ""],
        )
        self.assertEqual(parameters["steps"], 14)
        self.assertEqual(parameters["sampler"], "k_euler_ancestral")
        self.assertEqual(parameters["noise_schedule"], "karras")
        self.assertEqual(parameters["ucPreset"], 2)
        self.assertEqual(parameters["tag_hint_uc_preset"], 2)
        self.assertEqual(parameters["seed"], 42)
        self.assertEqual(parameters["scale"], 4.5)
        self.assertFalse(parameters["qualityToggle"])
        for key in ("cfg_rescale", "sm", "sm_dyn", "skip_cfg_above_sigma"):
            self.assertNotIn(key, parameters)

    def test_medium_heavy_uc_follows_final_base_prompt_nsfw_rule(self):
        for base, artist, character, expected in (
            ("landscape", "artist:test", "NSFW", "nsfw, " + NAI_V5_MEDIUM_NEGATIVE_PROMPT),
            ("NSFW, landscape", "artist:test", "character", NAI_V5_MEDIUM_NEGATIVE_PROMPT),
            ("landscape", "NSFW", "character", NAI_V5_MEDIUM_NEGATIVE_PROMPT),
        ):
            with self.subTest(base=base, artist=artist, character=character):
                data = generation_data(model="nai-diffusion-5-full-medium", base_prompt=base, character_prompts=[character])
                payload = build_generation_payload(
                    data, artist,
                )
                self.assertEqual(payload["parameters"]["negative_prompt"], expected)
                self.assertEqual(normalize_generation_data(data, artist_prompt=artist)["negative_prompt"], expected)

    def test_full_high_payload_keeps_editable_negative_and_sampler_options(self):
        payload = build_generation_payload(generation_data(
            negative_prompt="custom negative", character_prompts=["character"],
            cfg_rescale=0.5, variety_plus=True, sampler="k_dpmpp_2m", steps=30,
        ), "artist:test")
        parameters = payload["parameters"]
        self.assertEqual(parameters["negative_prompt"], "custom negative")
        self.assertEqual(parameters["v4_negative_prompt"]["caption"]["char_captions"][0]["char_caption"], "custom negative")
        self.assertEqual(parameters["cfg_rescale"], 0.5)
        self.assertEqual(parameters["sampler"], "k_dpmpp_2m")
        self.assertEqual(parameters["steps"], 30)
        self.assertIn("skip_cfg_above_sigma", parameters)

    def test_v45_rejects_seventh_character_but_v5_accepts_it(self):
        with self.assertRaisesRegex(ValueError, "maximum 6"):
            build_generation_payload(
                generation_data(
                    model="nai-diffusion-4-5-full",
                    character_prompts=["char"] * 7,
                ),
                "artist:test",
            )
        build_generation_payload(generation_data(character_prompts=["char"] * 22), "artist:test")

    def test_complexity_is_v5_only(self):
        with self.assertRaisesRegex(ValueError, "only supported"):
            build_generation_payload(
                generation_data(model="nai-diffusion-4-5-full", complexity="low"),
                "artist:test",
            )

    def test_comparison_generation_validates_the_selected_model_before_request(self):
        group = {
            "defaults": {},
            "fixed_prompt": "",
            "character_prompts": ["char"] * 22,
            "width": 832,
            "height": 1216,
        }
        style = {
            "model": "nai-diffusion-5-full",
            "complexity": "high",
            "quality_prompt": "",
            "fixed_prompt": "",
            "negative_prompt": "",
        }
        data, selected_model = _comparison_generation_data(group, style)
        self.assertEqual(selected_model, "nai-diffusion-5-full")
        self.assertEqual(data["model"], selected_model)
        self.assertEqual(len(normalize_generation_data(data)["character_prompts"]), 22)

        style["model"] = "nai-diffusion-4-5-full"
        with self.assertRaisesRegex(ValueError, "maximum 6"):
            normalize_generation_data(_comparison_generation_data(group, style)[0])

    def test_comparison_model_only_uses_fallback_for_empty_values(self):
        self.assertEqual(_comparison_model("", "nai-diffusion-4-5-full"), "nai-diffusion-4-5-full")
        self.assertEqual(_comparison_model("V5 Curated", "nai-diffusion-4-5-full"), "nai-diffusion-5-curated")
        with self.assertRaises(ValueError):
            _comparison_model("unsupported-model", "nai-diffusion-4-5-full")

    def test_medium_confirmed_style_and_comparison_keep_model_and_characters(self):
        characters = [f"character {index}" for index in range(22)]
        confirmed = normalize_confirmed_style({
            "model": "nai-diffusion-5-full-medium", "character_prompts": characters,
            "complexity": "high", "scale": 4.5,
        })
        self.assertEqual(confirmed["model"], "NovelAI Diffusion V5 Full Medium")
        self.assertEqual(json.loads(confirmed["character_prompts_json"]), characters)
        data, selected_model = _comparison_generation_data({
            "defaults": {"model": "nai-diffusion-5-full", "steps": 35},
            "fixed_prompt": "landscape", "character_prompts": characters,
            "width": 832, "height": 1216,
        }, confirmed)
        self.assertEqual(selected_model, "nai-diffusion-5-full-medium")
        normalized = normalize_generation_data(data)
        self.assertEqual(normalized["model"], selected_model)
        self.assertEqual(normalized["character_prompts"], characters)
        self.assertEqual(normalized["complexity"], "high")
        self.assertEqual(normalized["steps"], 14)
        self.assertEqual(normalized["scale"], 4.5)

    def test_comparison_style_empty_complexity_overrides_group_default(self):
        group = {
            "defaults": {"model": "nai-diffusion-5-full", "complexity": "ultra"},
            "fixed_prompt": "",
            "character_prompts": [],
            "width": 832,
            "height": 1216,
        }
        style = {
            "model": "nai-diffusion-5-full",
            "complexity": "",
            "quality_prompt": "",
            "fixed_prompt": "",
            "negative_prompt": "",
        }
        data, _ = _comparison_generation_data(group, style)
        self.assertEqual(data["complexity"], "")

    def test_explicit_generation_model_is_used_for_model_specific_validation(self):
        opener = Mock(side_effect=RuntimeError("stop before parsing"))
        with self.assertRaises(NovelAIError):
            generate_novelai_png(
                "secret",
                generation_data(character_prompts=["char"] * 22),
                "artist:test",
                opener=opener,
                model="nai-diffusion-5-full",
            )
        self.assertTrue(opener.called)

        opener.reset_mock()
        with self.assertRaisesRegex(ValueError, "maximum 6"):
            generate_novelai_png(
                "secret",
                generation_data(character_prompts=["char"] * 7),
                "artist:test",
                opener=opener,
                model="nai-diffusion-4-5-full",
            )
        opener.assert_not_called()

        opener.reset_mock()
        with self.assertRaises(NovelAIError):
            generate_novelai_png(
                "secret",
                generation_data(model="nai-diffusion-4-5-full", character_prompts=["char"] * 22),
                "artist:test",
                opener=opener,
                model="nai-diffusion-5-full",
            )
        self.assertTrue(opener.called)

    def test_confirmed_style_preserves_v5_model_limit_and_complexity(self):
        normalized = normalize_confirmed_style(
            {
                "model": "nai-diffusion-5-curated",
                "character_prompts": [f"char-{index}" for index in range(22)],
                "complexity": "high",
            }
        )
        self.assertEqual(normalized["model"], "NovelAI Diffusion V5 Curated")
        self.assertEqual(len(json.loads(normalized["character_prompts_json"])), 22)
        self.assertEqual(normalized["complexity"], "high")
        with self.assertRaisesRegex(ValueError, "up to 6"):
            normalize_confirmed_style(
                {
                    "model": "nai-diffusion-4-5-full",
                    "character_prompts": ["char"] * 7,
                }
            )

    def test_confirmed_style_uses_explicit_v5_generation_for_ambiguous_export_names(self):
        normalized = normalize_confirmed_style({
            "model": "NovelAI Diffusion V5 4BDE2A90",
            "character_prompts": [f"char-{index}" for index in range(22)],
            "complexity": "high",
        })
        self.assertEqual(normalized["model"], "NovelAI Diffusion V5 4BDE2A90")
        self.assertEqual(len(json.loads(normalized["character_prompts_json"])), 22)
        self.assertEqual(normalized["complexity"], "high")

    def test_confirmed_style_keeps_legacy_unknown_records_at_old_limit(self):
        prompts = [f"char-{index}" for index in range(20)]
        for model in ("", "old-unknown-model"):
            with self.subTest(model=model):
                normalized = normalize_confirmed_style({
                    "model": model,
                    "character_prompts": prompts,
                })
                self.assertEqual(json.loads(normalized["character_prompts_json"]), prompts)

    def test_confirmed_style_rejects_known_v45_over_limit(self):
        with self.assertRaises(ValueError):
            normalize_confirmed_style({
                "model": "nai-diffusion-4-5-full",
                "character_prompts": ["char"] * 7,
            })

    def test_confirmed_style_preserves_quality_toggle_and_uc_preset(self):
        normalized = normalize_confirmed_style({
            "model": "nai-diffusion-5-full",
            "quality_toggle": True,
            "uc_preset": 3,
        })
        self.assertTrue(normalized["quality_toggle"])
        self.assertEqual(normalized["uc_preset"], 3)

    def test_subscription_usage_is_optional_and_preserves_anlas(self):
        body = json.dumps(
            {
                "trainingStepsLeft": {
                    "fixedTrainingStepsLeft": 100,
                    "purchasedTrainingSteps": 54,
                },
                "usage": {
                    "isNegative": False,
                    "percent": 73,
                    "timeUntilNextPercent": 17.4,
                },
            }
        ).encode()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read = Mock(return_value=body)
        result = test_novelai_subscription("secret", opener=Mock(return_value=response))
        self.assertEqual(result["anlas"], 154)
        self.assertEqual(
            result["usage"],
            {"isNegative": False, "percent": 73, "timeUntilNextPercent": 17.4},
        )


class NovelAIMediumApiTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = patch.multiple(app_module,
            DATA_DIR=root,
            THUMBNAIL_DIR=root / "thumbnails",
            GENERATED_DIR=root / "generated",
            SETTINGS_JSON_PATH=root / "settings.json",
            DB_PATH=root / "test.sqlite",
            CONFIRMED_STYLE_IMAGE_DIR=root / "confirmed",
            COMPARISON_IMAGE_DIR=root / "comparison",
            ARCA_STYLE_IMAGE_DIR=root / "arca",
            ARCA_STYLE_SEED_PATH=root / "missing-seed.sqlite",
            STYLE_GROUP_IMAGE_DIR=root / "style_groups",
            MERGE_SOURCE_DIRS=[],
        )
        paths.start()
        self.addCleanup(paths.stop)
        app_module.init_db()
        self.client = app_module.app.test_client()

    def assert_medium_settings(self, settings):
        for key, expected in {
            "model": "nai-diffusion-5-full-medium", "steps": 14,
            "sampler": "k_euler_ancestral", "noise_schedule": "karras",
            "scale": 4.5, "cfg_rescale": 0.0, "uc_preset": 2,
        }.items():
            with self.subTest(setting=key):
                self.assertEqual(settings[key], expected)

    @patch("app.load_app_key", return_value="test-only-key")
    @patch("app.generate_novelai_png", return_value=(valid_png(64, 64), 123))
    def test_medium_generation_response_and_history_save_enforced_settings(self, generate, _key):
        payload = generation_data(
            model="nai-diffusion-5-full-medium", request_id="medium-api-fixture",
            artists=[{"artist": "nsfw_artist", "weight": 1.0}],
            width=64, height=64, steps=40, sampler="k_dpmpp_2m", noise_schedule="native",
            scale=4.5, cfg_rescale=0.7, uc_preset=4, variety_plus=True,
            negative_prompt="custom negative should be ignored", seed=123,
            character_prompts=["character one"],
        )
        response = self.client.post("/api/style-maker/generate", json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        result = response.get_json()
        self.assert_medium_settings(result)
        generate.assert_called_once()
        sent = generate.call_args.args[1]
        self.assert_medium_settings(sent)
        self.assertEqual(sent["negative_prompt"], NAI_V5_MEDIUM_NEGATIVE_PROMPT)
        detail_response = self.client.get(f"/api/art-styles/{result['style_id']}")
        self.assertEqual(detail_response.status_code, 200)
        image = detail_response.get_json()["images"][0]
        self.assert_medium_settings(image)
        self.assertEqual(image["negative_prompt"], sent["negative_prompt"])
        self.assertEqual(image["character_prompts"], ["character one"])
        self.assertEqual(image["base_prompt"], "1girl")
        self.assertFalse(image["variety_plus"])
        self.assertTrue((app_module.GENERATED_DIR / image["image_path"]).is_file())

    @patch("app.load_app_key", return_value="test-only-key")
    @patch("app.generate_novelai_png", return_value=(valid_png(64, 64), 123))
    def test_medium_comparison_snapshot_saves_enforced_settings(self, generate, _key):
        style = app_module.create_confirmed_style(
            app_module.DB_PATH, app_module.CONFIRMED_STYLE_IMAGE_DIR, valid_png(64, 64),
            {
                "name": "Medium fixture", "model": "nai-diffusion-5-full-medium",
                "artist_prompt": "artist:nsfw_artist", "negative_prompt": "custom negative",
                "steps": 35, "sampler": "k_dpmpp_2m", "noise_schedule": "native",
                "scale": 4.5, "cfg_rescale": 0.7, "uc_preset": 4,
            },
        )
        prepared = self.client.post("/api/comparisons", json={
            "name": "Medium comparison", "style_ids": [style["id"]],
            "fixed_prompt": "landscape", "character_prompts": ["character one"],
            "width": 64, "height": 64, "seed_mode": "none", "defaults": {},
            "defer_generation": True,
        })
        self.assertEqual(prepared.status_code, 201, prepared.get_json())
        group_id = prepared.get_json()["id"]
        response = self.client.post(f"/api/comparisons/{group_id}/styles/{style['id']}/generate", json={})
        self.assertEqual(response.status_code, 201, response.get_json())
        snapshot = response.get_json()["settings"]
        self.assert_medium_settings(snapshot)
        self.assertEqual(snapshot["negative_prompt"], NAI_V5_MEDIUM_NEGATIVE_PROMPT)
        self.assertEqual(snapshot["character_prompts"], ["character one"])
        generate.assert_called_once()
        self.assert_medium_settings(generate.call_args.args[1])
        saved = self.client.get("/api/comparisons").get_json()[0]["results"][0]["settings"]
        self.assertEqual(saved, snapshot)


if __name__ == "__main__":
    unittest.main()
