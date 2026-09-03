import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import data_merge
from data_merge import merge_data_directories, normalize_data_dirs


SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, artist_tag TEXT UNIQUE, score INTEGER,
    mode TEXT, created_at TEXT, updated_at TEXT, representative_thumbnail_path TEXT DEFAULT ''
);
CREATE TABLE rating_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rating_id INTEGER NOT NULL, post_id INTEGER,
    image_path TEXT, created_at TEXT, UNIQUE(rating_id, post_id),
    FOREIGN KEY(rating_id) REFERENCES ratings(id)
);
CREATE TABLE art_styles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, style_hash TEXT UNIQUE, artists_json TEXT,
    artist_prompt TEXT, representative_image_path TEXT DEFAULT '', image_count INTEGER,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE arca_style_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_url TEXT UNIQUE, title TEXT
);
CREATE TABLE arca_style_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, image_url TEXT,
    image_path TEXT, UNIQUE(item_id, image_url),
    FOREIGN KEY(item_id) REFERENCES arca_style_items(id)
);
CREATE TABLE arca_collection_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_json TEXT, status TEXT
);
CREATE TABLE arca_collection_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, keyword TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE generated_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE, style_id INTEGER,
    image_path TEXT, artist_prompt TEXT, created_at TEXT,
    FOREIGN KEY(style_id) REFERENCES art_styles(id)
);
CREATE TABLE generation_requests (
    request_id TEXT PRIMARY KEY, payload_hash TEXT, status TEXT, image_id INTEGER,
    created_at TEXT, updated_at TEXT,
    FOREIGN KEY(image_id) REFERENCES generated_images(id)
);
CREATE TABLE confirmed_styles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, image_path TEXT UNIQUE,
    source_type TEXT, source_id INTEGER, artist_prompt TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE confirmed_style_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT, style_id INTEGER, image_path TEXT UNIQUE,
    position INTEGER, created_at TEXT,
    FOREIGN KEY(style_id) REFERENCES confirmed_styles(id)
);
CREATE TABLE comparison_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, fixed_prompt TEXT,
    character_prompts_json TEXT, width INTEGER, height INTEGER, seed_mode TEXT, seed INTEGER,
    defaults_json TEXT, selected_style_ids_json TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE comparison_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, confirmed_style_id INTEGER,
    style_name TEXT, image_path TEXT, settings_json TEXT, created_at TEXT,
    UNIQUE(group_id, confirmed_style_id), FOREIGN KEY(group_id) REFERENCES comparison_groups(id),
    FOREIGN KEY(confirmed_style_id) REFERENCES confirmed_styles(id)
);
"""


def _db(path):
    connection = sqlite3.connect(path / "artist_rater.sqlite")
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


class DataMergeTest(unittest.TestCase):
    def test_project_directory_layout_is_resolved_and_api_lists_rating_and_generated_history(self):
        app_globals = {
            name: getattr(app, name)
            for name in (
                "DATA_DIR",
                "THUMBNAIL_DIR",
                "GENERATED_DIR",
                "CONFIRMED_STYLE_IMAGE_DIR",
                "COMPARISON_IMAGE_DIR",
                "ARCA_STYLE_IMAGE_DIR",
                "SETTINGS_JSON_PATH",
                "DB_PATH",
                "MERGE_SOURCE_DIRS",
                "ARCA_LOGIN_MANAGER",
            )
        }

        def restore_app_globals():
            for name, value in app_globals.items():
                setattr(app, name, value)

        self.addCleanup(restore_app_globals)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            primary = root / "primary-data"
            source_project = root / "source-project"
            source_data = source_project / "artist_rater" / "data"

            app.configure_data_directories([source_data])
            app.init_db()
            (source_data / "thumbnails").mkdir(parents=True, exist_ok=True)
            (source_data / "thumbnails" / "source.webp").write_bytes(b"source thumbnail")
            (source_data / "generated").mkdir(parents=True, exist_ok=True)
            (source_data / "generated" / "source.png").write_bytes(b"source generated")
            connection = sqlite3.connect(app.DB_PATH)
            with connection:
                connection.execute(
                    "INSERT INTO ratings(artist_tag,score,mode,created_at,updated_at,representative_thumbnail_path) "
                    "VALUES(?,?,?,?,?,?)",
                    ("source_artist", 4, "manual", "now", "now", "source.webp"),
                )
                rating_id = connection.execute("SELECT id FROM ratings WHERE artist_tag=?", ("source_artist",)).fetchone()[0]
                connection.execute(
                    "INSERT INTO rating_examples(rating_id,post_id,image_path,source_url,post_url,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (rating_id, 101, "source.webp", "https://image.test/source", "https://post.test/101", "now"),
                )
                connection.execute(
                    "INSERT INTO art_styles(style_hash,artists_json,artist_prompt,created_at,updated_at) "
                    "VALUES(?,?,?,?,?)",
                    ("source_style", "[]", "source_artist", "now", "now"),
                )
                style_id = connection.execute("SELECT id FROM art_styles WHERE style_hash=?", ("source_style",)).fetchone()[0]
                connection.execute(
                    "INSERT INTO generated_images(request_id,style_id,image_path,combined_prompt,artist_prompt,artists_json,"
                    "seed,width,height,sampler,steps,scale,cfg_rescale,model,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("source_request", style_id, "source.png", "prompt", "source_artist", "[]", 1, 64, 64, "k_euler", 10, 1.0, 0.0, "nai-diffusion-5-full", "now"),
                )
            connection.close()

            source_db_bytes = (source_data / "artist_rater.sqlite").read_bytes()
            app.configure_data_directories([primary, source_project])
            self.assertEqual(app.MERGE_SOURCE_DIRS, [source_data.resolve()])
            app.init_db()
            client = app.app.test_client()

            ratings = client.get("/api/ratings")
            generated = client.get("/api/style-manager/generated")
            examples = client.get("/api/ratings/1/examples")

            self.assertEqual(ratings.status_code, 200)
            self.assertEqual([item["artist_tag"] for item in ratings.get_json()], ["source_artist"])
            self.assertEqual(generated.status_code, 200)
            self.assertEqual([item["request_id"] for item in generated.get_json()], ["source_request"])
            self.assertEqual(generated.get_json()[0]["image_url"], "/generated/source.png")
            self.assertEqual(examples.status_code, 200)
            self.assertEqual(examples.get_json()["examples"][0]["image_url"], "/thumbnails/source.webp")
            self.assertEqual((source_data / "artist_rater.sqlite").read_bytes(), source_db_bytes)

    def test_normalize_requires_primary_to_be_one_of_data_dirs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            primary, sources = normalize_data_dirs([root / "a", root / "b"], root / "b")
            self.assertEqual(primary, (root / "b").resolve())
            self.assertEqual(sources, [(root / "a").resolve()])
            with self.assertRaises(ValueError):
                normalize_data_dirs([root / "a"], root / "outside")

    def test_merge_maps_relationships_deduplicates_and_keeps_source_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            primary, source = root / "primary", root / "source"
            primary.mkdir()
            source.mkdir()
            primary_db = _db(primary)
            source_db = _db(source)
            primary_db.execute("INSERT INTO settings VALUES ('app_key','primary')")
            primary_db.execute("INSERT INTO ratings VALUES (1,'primary',5,'manual','now','now','')")
            primary_db.execute("INSERT INTO art_styles VALUES (1,'primary-hash','[]','primary','',0,'now','now')")
            primary_db.execute("INSERT INTO arca_style_items VALUES (1,'https://source.test/primary','primary')")
            primary_db.execute("INSERT INTO arca_style_images VALUES (1,1,'https://img.test/primary','primary.png')")
            primary_db.execute("INSERT INTO arca_style_items VALUES (2,'https://source.test/shared','seed shared')")
            primary_db.execute("INSERT INTO arca_style_images VALUES (2,2,'https://img.test/shared','')")
            primary_db.execute("INSERT INTO comparison_groups VALUES (1,'primary','','[]',512,512,'none',NULL,'{}','[]','now','now')")
            primary_db.commit()
            source_db.execute("INSERT INTO settings VALUES ('app_key','source')")
            source_db.execute("INSERT INTO ratings VALUES (1,'source',4,'manual','now','now','source.png')")
            source_db.execute("INSERT INTO rating_examples VALUES (1,1,99,'source.png','now')")
            source_db.execute("INSERT INTO ratings VALUES (2,'source-two',3,'manual','now','now','')")
            source_db.execute("INSERT INTO ratings VALUES (3,'source-three',2,'manual','now','now','')")
            source_db.execute("INSERT INTO rating_examples VALUES (2,2,100,'','now')")
            source_db.execute("INSERT INTO rating_examples VALUES (3,3,101,'','now')")
            source_db.execute("INSERT INTO art_styles VALUES (1,'source-hash','[]','source','generated.png',1,'now','now')")
            source_db.execute("INSERT INTO arca_style_items VALUES (1,'https://source.test/shared','shared')")
            source_db.execute("INSERT INTO arca_style_images VALUES (1,1,'https://img.test/shared','shared.png')")
            source_db.execute("INSERT INTO arca_collection_jobs VALUES (1,'{}','running')")
            source_db.execute("INSERT INTO arca_collection_runs VALUES (1,1,'shared','now','now')")
            source_db.execute("INSERT INTO generated_images VALUES (1,'source-request',1,'generated.png','source','now')")
            source_db.execute("INSERT INTO generation_requests VALUES ('source-request','hash','complete',1,'now','now')")
            source_db.execute("INSERT INTO confirmed_styles VALUES (1,'source style','confirmed.png','generated',1,'source','now','now')")
            source_db.execute("INSERT INTO confirmed_style_images VALUES (1,1,'confirmed.png',0,'now')")
            source_db.execute("INSERT INTO confirmed_styles VALUES (2,'shared source style','shared-confirmed.png','shared',1,'source','now','now')")
            source_db.execute("INSERT INTO confirmed_style_images VALUES (2,2,'shared-confirmed.png',0,'now')")
            source_db.execute("INSERT INTO comparison_groups VALUES (1,'source group','','[]',512,512,'none',NULL,'{}','[1]','now','now')")
            source_db.execute("INSERT INTO comparison_results VALUES (1,1,1,'source style','result.png','{}','now')")
            source_db.commit()
            source_db.close()
            primary_db.close()
            for dirname, filename, content in (
                ("thumbnails", "source.png", b"thumbnail"),
                ("generated", "generated.png", b"generated"),
                ("confirmed_style_images", "confirmed.png", b"confirmed"),
                ("comparison_images", "result.png", b"result"),
                ("confirmed_style_images", "shared-confirmed.png", b"shared-confirmed"),
                ("arca_style_images", "shared.png", b"shared"),
            ):
                (source / dirname).mkdir(parents=True, exist_ok=True)
                (source / dirname / filename).write_bytes(content)
            source_db_bytes = (source / "artist_rater.sqlite").read_bytes()
            stats = merge_data_directories(primary, [source])
            self.assertEqual(stats["sources"], 1)

            connection = sqlite3.connect(primary / "artist_rater.sqlite")
            self.assertEqual(connection.execute("SELECT value FROM settings WHERE key='app_key'").fetchone()[0], "primary")
            rating_id = connection.execute("SELECT id FROM ratings WHERE artist_tag='source'").fetchone()[0]
            self.assertEqual(connection.execute("SELECT rating_id FROM rating_examples").fetchone()[0], rating_id)
            self.assertEqual(connection.execute("SELECT rating_id FROM rating_examples WHERE post_id=100").fetchone()[0], connection.execute("SELECT id FROM ratings WHERE artist_tag='source-two'").fetchone()[0])
            self.assertEqual(connection.execute("SELECT rating_id FROM rating_examples WHERE post_id=101").fetchone()[0], connection.execute("SELECT id FROM ratings WHERE artist_tag='source-three'").fetchone()[0])
            generated_id = connection.execute("SELECT id FROM generated_images WHERE request_id='source-request'").fetchone()[0]
            self.assertEqual(connection.execute("SELECT style_id FROM generated_images").fetchone()[0], 2)
            confirmed_id = connection.execute("SELECT id,source_id FROM confirmed_styles WHERE name='source style'").fetchone()
            self.assertEqual(confirmed_id[1], generated_id)
            shared_image_id = connection.execute("SELECT id FROM arca_style_images WHERE image_url='https://img.test/shared'").fetchone()[0]
            shared_source_id = connection.execute("SELECT source_id FROM confirmed_styles WHERE name='shared source style'").fetchone()[0]
            self.assertEqual(shared_source_id, shared_image_id)
            self.assertEqual(connection.execute("SELECT image_path FROM arca_style_images WHERE id=?", (shared_image_id,)).fetchone()[0], "shared.png")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM arca_collection_jobs").fetchone()[0], 0)
            self.assertIsNone(connection.execute("SELECT job_id FROM arca_collection_runs WHERE keyword='shared'").fetchone()[0])
            selected = json.loads(connection.execute("SELECT selected_style_ids_json FROM comparison_groups WHERE name='source group'").fetchone()[0])
            self.assertEqual(selected, [confirmed_id[0]])
            result = connection.execute("SELECT group_id,confirmed_style_id FROM comparison_results").fetchone()
            group_id = connection.execute("SELECT id FROM comparison_groups WHERE name='source group'").fetchone()[0]
            self.assertEqual(tuple(result), (group_id, confirmed_id[0]))
            connection.close()

            # Re-running is idempotent and source bytes/files are untouched.
            with patch.object(data_merge, "_copy_file_tree", side_effect=AssertionError("unchanged source must skip file scan")):
                skipped = merge_data_directories(primary, [source])
            self.assertEqual(skipped, {"sources": 1, "rows": 0, "files": 0})
            connection = sqlite3.connect(primary / "artist_rater.sqlite")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ratings WHERE artist_tag='source'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM generated_images WHERE request_id='source-request'").fetchone()[0], 1)
            connection.close()
            self.assertEqual((source / "artist_rater.sqlite").read_bytes(), source_db_bytes)
            self.assertEqual((source / "thumbnails" / "source.png").read_bytes(), b"thumbnail")

            source_db = sqlite3.connect(source / "artist_rater.sqlite")
            with source_db:
                source_db.execute("INSERT INTO ratings VALUES (4,'source-four',1,'manual','now','now','')")
            source_db.close()
            changed = merge_data_directories(primary, [source])
            self.assertEqual(changed["sources"], 1)
            connection = sqlite3.connect(primary / "artist_rater.sqlite")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ratings WHERE artist_tag='source-four'").fetchone()[0], 1)
            connection.close()


if __name__ == "__main__":
    unittest.main()
