import tempfile
import unittest
from pathlib import Path

from comparison_store import (
    create_group,
    delete_group,
    get_group,
    init_comparison_tables,
    remove_group_results,
    save_result,
    set_group_seed,
)


class ComparisonStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "comparison.sqlite"
        self.image_dir = self.root / "images"
        init_comparison_tables(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_group_keeps_settings_and_removes_only_unselected_results(self):
        group_id = create_group(self.db_path, {
            "name": "테스트 비교군",
            "fixed_prompt": "white background",
            "character_prompts": ["1girl"],
            "width": 832,
            "height": 1216,
            "seed_mode": "first",
            "defaults": {"steps": 28},
            "style_ids": [10, 20],
        })
        save_result(self.db_path, self.image_dir, group_id, 10, "A", b"first", {"seed": 1})
        save_result(self.db_path, self.image_dir, group_id, 20, "B", b"second", {"seed": 1})
        set_group_seed(self.db_path, group_id, 1234)

        removed = remove_group_results(self.db_path, self.image_dir, group_id, [20])
        group = get_group(self.db_path, group_id)

        self.assertEqual(len(removed), 1)
        self.assertEqual(group["seed"], 1234)
        self.assertEqual(group["character_prompts"], ["1girl"])
        self.assertEqual(group["selected_style_ids"], [10, 20])
        self.assertEqual([item["confirmed_style_id"] for item in group["results"]], [20])
        self.assertEqual(len(list(self.image_dir.iterdir())), 1)

        self.assertTrue(delete_group(self.db_path, self.image_dir, group_id))
        self.assertIsNone(get_group(self.db_path, group_id))
        self.assertEqual(list(self.image_dir.iterdir()), [])

    def test_saving_the_same_style_replaces_image_and_keeps_one_result(self):
        group_id = create_group(self.db_path, {
            "name": "교체 테스트",
            "fixed_prompt": "",
            "character_prompts": [],
            "style_ids": [10],
            "width": 832,
            "height": 1216,
            "seed_mode": "none",
            "defaults": {},
        })
        first = save_result(self.db_path, self.image_dir, group_id, 10, "A", b"first", {"seed": 1})
        second = save_result(self.db_path, self.image_dir, group_id, 10, "A", b"second", {"seed": 2})
        group = get_group(self.db_path, group_id)

        self.assertNotEqual(first, second)
        self.assertEqual(len(group["results"]), 1)
        self.assertEqual(group["results"][0]["settings"]["seed"], 2)
        self.assertFalse((self.image_dir / first).exists())
        self.assertEqual((self.image_dir / second).read_bytes(), b"second")

    def test_group_preserves_model_and_complexity_and_accepts_broad_v5_input(self):
        group_id = create_group(self.db_path, {
            "name": "V5 비교군",
            "character_prompts": ["char"] * 22,
            "model": "nai-diffusion-5-full",
            "complexity": "high",
            "width": 832,
            "height": 1216,
            "seed_mode": "none",
            "defaults": {"steps": 23},
            "style_ids": [10],
        })
        group = get_group(self.db_path, group_id)
        self.assertEqual(group["defaults"]["model"], "nai-diffusion-5-full")
        self.assertEqual(group["defaults"]["complexity"], "high")
        self.assertEqual(len(group["character_prompts"]), 22)

    def test_group_rejects_more_than_broadest_supported_character_limit(self):
        with self.assertRaisesRegex(ValueError, "최대 22"):
            create_group(self.db_path, {
                "character_prompts": ["char"] * 23,
                "width": 832,
                "height": 1216,
                "seed_mode": "none",
                "defaults": {},
                "style_ids": [10],
            })


if __name__ == "__main__":
    unittest.main()
