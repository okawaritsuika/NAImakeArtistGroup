import json
import unittest
from unittest.mock import Mock

from confirmed_style_store import normalize_confirmed_model_name, normalize_confirmed_style
from model_definitions import MODEL_DEFINITIONS, normalize_model_id
from app import _comparison_generation_data, _comparison_model
from novelai import (
    NovelAIError,
    build_generation_payload,
    generate_novelai_png,
    normalize_generation_data,
    test_novelai_subscription,
)


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
                    "nai-diffusion-5-full",
                    "nai-diffusion-5-curated",
                    "nai-diffusion-4-5-full",
                    "nai-diffusion-4-5-curated",
                }
            ),
            {
                "nai-diffusion-5-full",
                "nai-diffusion-5-curated",
                "nai-diffusion-4-5-full",
                "nai-diffusion-4-5-curated",
            },
        )
        self.assertEqual(MODEL_DEFINITIONS["nai-diffusion-5-full"].max_character_prompts, 22)
        self.assertEqual(MODEL_DEFINITIONS["nai-diffusion-4-5-full"].max_character_prompts, 6)

    def test_legacy_short_aliases_are_explicit_and_ambiguous_generation_names_are_rejected(self):
        for alias, expected in {
            "NAID5F": "nai-diffusion-5-full",
            "naid5c": "nai-diffusion-5-curated",
            "NAID4.5F": "nai-diffusion-4-5-full",
            "naid4.5c": "nai-diffusion-4-5-curated",
        }.items():
            with self.subTest(alias=alias):
                self.assertEqual(normalize_model_id(alias), expected)
        for ambiguous in ("V5", "NovelAI Diffusion V5", "V4.5", "NovelAI Diffusion V4.5"):
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


if __name__ == "__main__":
    unittest.main()
