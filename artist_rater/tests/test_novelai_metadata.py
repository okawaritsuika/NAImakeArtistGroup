import gzip
import io
import json
import sqlite3
import struct
import tempfile
import unittest
import zlib
from contextlib import closing
from pathlib import Path

from PIL import Image

from arca_style_collector import (
    _save_article,
    extract_novelai_metadata,
    export_arca_style_seed,
    get_arca_style_detail,
    init_arca_style_tables,
    list_arca_styles,
)
from novelai_metadata import classify_model


def png_text(key, value):
    payload = value.encode("utf-8")
    kind = b"tEXt"
    chunk = struct.pack(">I", len(key.encode() + b"\0" + payload)) + kind + key.encode() + b"\0" + payload
    chunk += struct.pack(">I", zlib.crc32(kind + key.encode() + b"\0" + payload) & 0xFFFFFFFF)
    end = b"IEND"
    return b"\x89PNG\r\n\x1a\n" + chunk + struct.pack(">I", 0) + end + struct.pack(">I", zlib.crc32(end) & 0xFFFFFFFF)


def png_stealth(payload, compressed=True):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if compressed:
        raw = gzip.compress(raw)
    signature = b"stealth_pngcomp" if compressed else b"stealth_pnginfo"
    bits = "".join(f"{byte:08b}" for byte in signature)
    bits += f"{len(raw) * 8:032b}"
    bits += "".join(f"{byte:08b}" for byte in raw)
    height = 64
    width = (len(bits) + height - 1) // height
    image = Image.new("RGBA", (width, height), (10, 20, 30, 254))
    alpha = bytearray(image.getchannel("A").tobytes())
    for index, bit in enumerate(bits):
        x, y = divmod(index, height)
        alpha[y * width + x] = (alpha[y * width + x] & 0xFE) | int(bit)
    image.putalpha(Image.frombytes("L", image.size, bytes(alpha)))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def webp_exif(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-16-be")
    exif = Image.Exif()
    exif[37510] = b"UNICODE\x00" + raw
    output = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 30, 40)).save(output, "WEBP", lossless=True, exif=exif)
    return output.getvalue()


class NovelAiMetadataTest(unittest.TestCase):
    def test_model_ids_are_exact_and_human_readable_hash_is_not_guessed_variant(self):
        self.assertEqual(classify_model("nai-diffusion-5-full")["model_id"], "nai-diffusion-5-full")
        self.assertEqual(classify_model("nai-diffusion-4-5-curated")["model_family"], "v4.5")
        old_export = classify_model("NovelAI Diffusion V4.5 4BDE2A90")
        self.assertEqual(old_export["model_family"], "v4.5")
        self.assertEqual(old_export["model_variant"], "unknown")
        self.assertEqual(old_export["model_id"], "")
        self.assertEqual(classify_model("nai-diffusion-4-full")["model_family"], "v4")
        self.assertEqual(classify_model("nai-diffusion-3")["model_generation"], "v3")

    def test_v5_uses_official_v4_prompt_character_caption_shape_and_preserves_raw_model(self):
        payload = {
            "model": "nai-diffusion-5-full",
            "v4_prompt": {"caption": {
                "base_caption": "artist:foo, watercolor",
                "char_captions": [{"char_caption": "shimamura uzuki", "centers": [{"x": 0.4, "y": 0.5}]}],
            }},
            "v4_negative_prompt": {"caption": {"base_caption": "lowres"}},
        }
        result = extract_novelai_metadata(png_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(result["model"], payload["model"])
        self.assertEqual(result["model_id"], payload["model"])
        self.assertEqual(result["model_family"], "v5")
        self.assertEqual(result["character_prompts"][0]["prompt"], "shimamura uzuki")
        self.assertEqual(json.loads(result["raw_metadata_json"])["model"], payload["model"])

    def test_v5_png_restores_exact_complexity_and_common_wire_options_without_prompt_loss(self):
        payload = {
            "model": "nai-diffusion-5-full",
            "qualityToggle": True,
            "ucPreset": 3,
            "v4_prompt": {"caption": {
                "base_caption": "high complexity, artist:foo, watercolor",
                "char_captions": [{"char_caption": "character one", "centers": [{"x": 0.2, "y": 0.8}]}],
            }},
            "v4_negative_prompt": {"caption": {"base_caption": "lowres"}},
        }
        result = extract_novelai_metadata(png_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(result["metadata_status"], "ok")
        self.assertEqual(result["complexity"], "high")
        self.assertEqual(result["prompt"], payload["v4_prompt"]["caption"]["base_caption"])
        self.assertEqual(result["character_prompts"][0]["prompt"], "character one")
        self.assertEqual(result["quality_toggle"], True)
        self.assertEqual(result["uc_preset"], 3)
        raw = json.loads(result["raw_metadata_json"])
        self.assertEqual(raw["qualityToggle"], True)
        self.assertEqual(raw["ucPreset"], 3)

    def test_v45_keeps_common_wire_options_but_never_restores_complexity(self):
        payload = {
            "model": "nai-diffusion-4-5-curated",
            "qualityToggle": False,
            "ucPreset": 2,
            "v4_prompt": {"caption": {
                "base_caption": "high complexity, artist:foo",
                "char_captions": [{"char_caption": "v45 character", "centers": []}],
            }},
        }
        result = extract_novelai_metadata(png_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(result["complexity"], "")
        self.assertEqual(result["quality_toggle"], False)
        self.assertEqual(result["uc_preset"], 2)
        self.assertEqual(result["character_prompts"][0]["prompt"], "v45 character")

    def test_v5_complexity_must_be_one_exact_top_level_tag(self):
        for prompt in (
            "high complexity, high complexity, artist:foo",
            "high complexity, medium complexity, artist:foo",
            "high complexity (strong), artist:foo",
        ):
            with self.subTest(prompt=prompt):
                payload = {"model": "nai-diffusion-5-full", "prompt": prompt}
                result = extract_novelai_metadata(png_text("Comment", json.dumps(payload)), "image/png")
                self.assertEqual(result["complexity"], "")

    def test_v5_webp_exif_restores_character_prompt_complexity_and_options(self):
        payload = {
            "model": "nai-diffusion-5-curated",
            "qualityToggle": True,
            "ucPreset": 1,
            "v4_prompt": {"caption": {
                "base_caption": "ultra complexity, artist:webp",
                "char_captions": [{"char_caption": "webp character", "centers": [{"x": 0.5, "y": 0.5}]}],
            }},
        }
        result = extract_novelai_metadata(webp_exif(payload), "image/webp")
        self.assertEqual(result["model_id"], "nai-diffusion-5-curated")
        self.assertEqual(result["complexity"], "ultra")
        self.assertEqual(result["character_prompts"][0]["prompt"], "webp character")
        self.assertEqual(result["quality_toggle"], True)
        self.assertEqual(result["uc_preset"], 1)

    def test_v5_png_stealth_restores_character_prompt_complexity_and_options(self):
        payload = {
            "model": "nai-diffusion-5-full",
            "qualityToggle": False,
            "ucPreset": 4,
            "v4_prompt": {"caption": {
                "base_caption": "low complexity, artist:stealth",
                "char_captions": [{"char_caption": "stealth character", "centers": []}],
            }},
        }
        result = extract_novelai_metadata(png_stealth(payload), "image/png")
        self.assertEqual(result["complexity"], "low")
        self.assertEqual(result["character_prompts"][0]["prompt"], "stealth character")
        self.assertEqual(result["quality_toggle"], False)
        self.assertEqual(result["uc_preset"], 4)
        self.assertEqual(json.loads(result["raw_metadata_json"])["model"], payload["model"])

    def test_unknown_model_is_not_inferred_from_prompt_text(self):
        payload = {"model": "unpublished-model", "prompt": "v5 style words", "seed": 7, "sampler": "k_euler"}
        result = extract_novelai_metadata(png_text("Comment", json.dumps(payload)), "image/png")
        self.assertEqual(result["metadata_status"], "ok")
        self.assertEqual(result["model_id"], "")
        self.assertEqual(result["model_family"], "unknown")

    def test_migration_is_idempotent_and_image_filter_is_image_level(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "old.sqlite"
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE arca_style_items (
                        id INTEGER PRIMARY KEY, source_url TEXT UNIQUE, title TEXT, board_tab TEXT,
                        posted_at TEXT, representative_image_url TEXT, representative_image_path TEXT,
                        image_count INTEGER, metadata_status TEXT, prompt TEXT, negative_prompt TEXT, model TEXT,
                        raw_metadata_json TEXT, collected_at TEXT, updated_at TEXT,
                        recommendation_count INTEGER, view_count INTEGER
                    );
                    CREATE TABLE arca_style_images (
                        id INTEGER PRIMARY KEY, item_id INTEGER, image_url TEXT, image_path TEXT,
                        content_type TEXT, metadata_status TEXT, prompt TEXT, base_prompt TEXT, negative_prompt TEXT,
                        seed TEXT, sampler TEXT, steps INTEGER, scale REAL, cfg_rescale REAL, noise_schedule TEXT,
                        model TEXT, width INTEGER, height INTEGER, raw_metadata_json TEXT, created_at TEXT
                    );
                    INSERT INTO arca_style_items VALUES (1,'https://arca.live/b/aiart/mixed','그림체 공유','NAI','','https://img/v4.png','v4.png',2,'no_metadata','','','','{}','now','now',NULL,NULL);
                    INSERT INTO arca_style_images(id,item_id,image_url,image_path,content_type,metadata_status,prompt,base_prompt,negative_prompt,seed,sampler,steps,scale,cfg_rescale,noise_schedule,model,width,height,raw_metadata_json,created_at)
                    VALUES (1,1,'https://img/v4.png','v4.png','image/png','ok','v4','v4','','','',NULL,NULL,NULL,NULL,'nai-diffusion-4-5-full',640,832,'{}','now');
                    INSERT INTO arca_style_images(id,item_id,image_url,image_path,content_type,metadata_status,prompt,base_prompt,negative_prompt,seed,sampler,steps,scale,cfg_rescale,noise_schedule,model,width,height,raw_metadata_json,created_at)
                    VALUES (2,1,'https://img/v5.png','v5.png','image/png','ok','v5','v5','','','',NULL,NULL,NULL,NULL,'nai-diffusion-5-curated',832,1216,'{}','now');
                    INSERT INTO arca_style_items VALUES (2,'https://arca.live/b/aiart/stale','그림체 공유','NAI','','','',1,'no_metadata','','','nai-diffusion-5-full','{"model":"nai-diffusion-5-full","prompt":"stale"}','now','now',NULL,NULL);
                """)
            init_arca_style_tables(db)
            init_arca_style_tables(db)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT model_id,model_family,model_generation FROM arca_style_images WHERE id=2").fetchone(), ("nai-diffusion-5-curated", "v5", "v5"))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM arca_style_images").fetchone()[0], 2)
                self.assertEqual(
                    conn.execute("SELECT model_id,model_family,model_generation,model_variant,complexity,quality_toggle,uc_preset FROM arca_style_items WHERE id=2").fetchone(),
                    ("", "unknown", "unknown", "unknown", "", None, None),
                )
            items = list_arca_styles(db, {"model": "v5"})
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["image_count"], 1)
            self.assertEqual(items[0]["representative_image_url"], "https://img/v5.png")
            self.assertEqual(items[0]["representative_image_path"], "v5.png")
            self.assertEqual(items[0]["prompt"], "v5")
            self.assertEqual(items[0]["base_prompt"], "v5")
            self.assertEqual(items[0]["model_id"], "nai-diffusion-5-curated")
            self.assertEqual(items[0]["model_family"], "v5")
            self.assertEqual(items[0]["model_generation"], "v5")
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT model_id FROM arca_style_images WHERE item_id=? AND model_family='v5'", (items[0]["id"],)).fetchone()[0],
                    "nai-diffusion-5-curated",
                )
            detail = get_arca_style_detail(db, items[0]["id"], {"model": "v5"})
            self.assertEqual([image["model_id"] for image in detail["images"]], ["nai-diffusion-5-curated"])
            self.assertEqual(detail["image_count"], 1)
            self.assertEqual(detail["representative_image_path"], "v5.png")
            v45_items = list_arca_styles(db, {"model": "v4.5"})
            self.assertEqual(v45_items[0]["image_count"], 1)
            self.assertEqual(v45_items[0]["representative_image_path"], "v4.png")
            self.assertEqual(v45_items[0]["model_id"], "nai-diffusion-4-5-full")
            v45_detail = get_arca_style_detail(db, items[0]["id"], {"model": "v4.5"})
            self.assertEqual([image["model_id"] for image in v45_detail["images"]], ["nai-diffusion-4-5-full"])

    def test_new_collection_and_local_reuse_persist_model_generation(self):
        payload = {
            "model": "nai-diffusion-5-full",
            "prompt": "artist:foo",
            "seed": 7,
            "sampler": "k_euler",
            "qualityToggle": True,
            "ucPreset": 2,
        }
        image_bytes = png_text("Comment", json.dumps(payload))

        class Response:
            headers = {"Content-Type": "image/png"}
            def raise_for_status(self):
                return None
            def iter_content(self, _size):
                return [image_bytes]
            def close(self):
                return None

        class Session:
            def get(self, *_args, **_kwargs):
                return Response()

        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "collect.sqlite"
            image_dir = Path(temp) / "images"
            init_arca_style_tables(db)
            article = {
                "source_url": "https://arca.live/b/aiart/model-generation",
                "article_id": "model-generation", "board_tab": "NAI",
                "title": "그림체 공유", "author": "tester", "posted_at": "2026-08-21",
                "body_text": "", "image_urls": ["https://img.example/model.png"],
            }
            summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
            _save_article(db, image_dir, Session(), article, summary)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(
                    conn.execute("SELECT model_id,model_family,model_generation,model_variant FROM arca_style_items").fetchone(),
                    ("nai-diffusion-5-full", "v5", "v5", "full"),
                )
                self.assertEqual(
                    conn.execute("SELECT model_id,model_family,model_generation,model_variant FROM arca_style_images").fetchone(),
                    ("nai-diffusion-5-full", "v5", "v5", "full"),
                )
                self.assertEqual(
                    conn.execute("SELECT quality_toggle,uc_preset FROM arca_style_items").fetchone(),
                    (1, 2),
                )
                self.assertEqual(
                    conn.execute("SELECT quality_toggle,uc_preset FROM arca_style_images").fetchone(),
                    (1, 2),
                )

            class NoNetworkSession:
                def get(self, *_args, **_kwargs):
                    raise AssertionError("existing local image should be reused")

            summary = {"saved": 0, "updated": 0, "metadata_ok": 0, "no_metadata": 0, "items": []}
            _save_article(db, image_dir, NoNetworkSession(), article, summary)
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute("SELECT model_generation FROM arca_style_items").fetchone()[0], "v5")
                self.assertEqual(conn.execute("SELECT model_generation FROM arca_style_images").fetchone()[0], "v5")

    def test_export_backfills_model_fields_for_old_source_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "old-source.sqlite"
            target = Path(temp) / "seed.sqlite"
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE arca_style_items (
                        id INTEGER PRIMARY KEY, source_url TEXT UNIQUE, article_id TEXT, board_tab TEXT,
                        title TEXT, author TEXT, posted_at TEXT, collected_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        representative_image_url TEXT, representative_image_path TEXT, image_count INTEGER NOT NULL DEFAULT 0,
                        metadata_status TEXT DEFAULT 'none', prompt TEXT DEFAULT '', negative_prompt TEXT DEFAULT '',
                        seed TEXT DEFAULT '', sampler TEXT DEFAULT '', steps INTEGER, scale REAL, cfg_rescale REAL,
                        noise_schedule TEXT DEFAULT '', model TEXT DEFAULT '', width INTEGER, height INTEGER,
                        raw_metadata_json TEXT DEFAULT '{}', body_prompt_text TEXT DEFAULT '', memo TEXT DEFAULT '',
                        recommendation_count INTEGER, view_count INTEGER
                    );
                    CREATE TABLE arca_style_images (
                        id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, image_url TEXT NOT NULL,
                        image_path TEXT DEFAULT '', content_type TEXT DEFAULT '', metadata_status TEXT DEFAULT 'none',
                        prompt TEXT DEFAULT '', negative_prompt TEXT DEFAULT '', seed TEXT DEFAULT '', sampler TEXT DEFAULT '',
                        steps INTEGER, scale REAL, cfg_rescale REAL, noise_schedule TEXT DEFAULT '', model TEXT DEFAULT '',
                        width INTEGER, height INTEGER, raw_metadata_json TEXT DEFAULT '{}', created_at TEXT NOT NULL
                    );
                    CREATE TABLE arca_collection_runs (
                        id INTEGER PRIMARY KEY, keyword TEXT NOT NULL, tabs TEXT NOT NULL,
                        start_date TEXT NOT NULL, end_date TEXT NOT NULL, max_pages INTEGER NOT NULL,
                        max_posts INTEGER NOT NULL, search_scope TEXT NOT NULL DEFAULT 'all', status TEXT NOT NULL,
                        scanned_pages INTEGER DEFAULT 0, scanned_posts INTEGER DEFAULT 0, saved INTEGER DEFAULT 0,
                        updated INTEGER DEFAULT 0, error TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE arca_collection_run_items (run_id INTEGER NOT NULL, item_id INTEGER NOT NULL, PRIMARY KEY(run_id,item_id));
                    CREATE TABLE arca_collection_invalidations (
                        keyword TEXT NOT NULL, tabs TEXT NOT NULL, max_pages INTEGER NOT NULL, max_posts INTEGER NOT NULL,
                        search_scope TEXT NOT NULL, invalidated_date TEXT NOT NULL, created_at TEXT NOT NULL,
                        UNIQUE(keyword,tabs,max_pages,max_posts,search_scope,invalidated_date)
                    );
                    INSERT INTO arca_style_items(id,source_url,board_tab,title,collected_at,updated_at,metadata_status,prompt,model,raw_metadata_json)
                    VALUES(1,'https://arca.live/b/aiart/old-export','NAI','그림체 공유','now','now','ok','v5','nai-diffusion-5-full','{"model":"nai-diffusion-5-full","prompt":"v5"}');
                    INSERT INTO arca_style_images(id,item_id,image_url,metadata_status,prompt,model,raw_metadata_json,created_at)
                    VALUES(1,1,'https://img/v5.png','ok','v5','nai-diffusion-5-full','{"model":"nai-diffusion-5-full","prompt":"v5"}','now');
                """)
            export_arca_style_seed(source, target)
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(
                    conn.execute("SELECT model_id,model_family,model_generation,model_variant FROM arca_style_items").fetchone(),
                    ("nai-diffusion-5-full", "v5", "v5", "full"),
                )
                self.assertEqual(
                    conn.execute("SELECT model_id,model_family,model_generation,model_variant FROM arca_style_images").fetchone(),
                    ("nai-diffusion-5-full", "v5", "v5", "full"),
                )
            with closing(sqlite3.connect(source)) as conn:
                self.assertNotIn("model_id", {row[1] for row in conn.execute("PRAGMA table_info(arca_style_images)")})


if __name__ == "__main__":
    unittest.main()
