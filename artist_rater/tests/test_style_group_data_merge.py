import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from data_merge import merge_data_directories


SCHEMA = """
CREATE TABLE ratings (id INTEGER PRIMARY KEY, artist_tag TEXT UNIQUE, score INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE generated_images (id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, image_path TEXT);
CREATE TABLE nai_artist_tests (id INTEGER PRIMARY KEY, name TEXT, config_json TEXT, images_per_artist INTEGER, delay_seconds REAL, status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE nai_artist_test_items (id INTEGER PRIMARY KEY, test_id INTEGER, artist_tag TEXT, danbooru_score INTEGER, ordinal INTEGER, status TEXT, request_id TEXT UNIQUE, generated_image_id INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE nai_artist_test_ratings (id INTEGER PRIMARY KEY, test_id INTEGER, artist_tag TEXT, score INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE nai_artist_test_images (test_id INTEGER, item_id INTEGER, generated_image_id INTEGER, artist_tag TEXT, created_at TEXT, PRIMARY KEY(test_id,item_id));
CREATE TABLE style_groups (id INTEGER PRIMARY KEY, name TEXT, reference_image_path TEXT, base_source_type TEXT DEFAULT '', base_source_id TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
CREATE TABLE style_group_sources (id INTEGER PRIMARY KEY, group_id INTEGER, source_type TEXT, source_id TEXT, label TEXT, position INTEGER, cursor INTEGER, status TEXT, created_at TEXT, updated_at TEXT, UNIQUE(group_id,source_type,source_id));
CREATE TABLE style_group_decisions (id INTEGER PRIMARY KEY, group_id INTEGER, source_id INTEGER, candidate_key TEXT, included INTEGER, candidate_position INTEGER, decided_at TEXT, UNIQUE(group_id,source_id,candidate_key));
CREATE TABLE style_group_images (id INTEGER PRIMARY KEY, group_id INTEGER, source_type TEXT, source_id TEXT, candidate_key TEXT, image_path TEXT, original_name TEXT, width INTEGER, height INTEGER, sha256 TEXT, is_reference INTEGER, created_at TEXT, UNIQUE(group_id,sha256));
CREATE TABLE style_group_artists (id INTEGER PRIMARY KEY, group_id INTEGER, artist_key TEXT, artist_tag TEXT, decision TEXT, direct INTEGER, created_at TEXT, updated_at TEXT, UNIQUE(group_id,artist_key));
CREATE TABLE style_group_image_artists (image_id INTEGER, artist_key TEXT, PRIMARY KEY(image_id,artist_key));
"""


def make_db(path, destination=False):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(SCHEMA)
        if destination:
            connection.execute("INSERT INTO ratings VALUES (1,'existing_artist',5,'r1','r1')")
            connection.execute("INSERT INTO nai_artist_tests VALUES (1,'existing_test','{}',1,2,'completed','t1','t1')")
        else:
            connection.execute("INSERT INTO ratings VALUES (1,'source_artist',4,'r2','r2')")
            connection.execute("INSERT INTO nai_artist_tests VALUES (1,'source_test','{}',1,2,'completed','t2','t2')")
            connection.execute("INSERT INTO nai_artist_test_items VALUES (1,1,'source_artist',4,0,'complete','source-request',NULL,'i1','i1')")
            connection.executemany(
                "INSERT INTO style_groups (id,name,reference_image_path,created_at,updated_at) VALUES (?,?,?,?,?)",
                [(1,'same-name','', 'g1', 'g1'), (2,'same-name','', 'g2', 'g2')],
            )
            connection.executemany(
                "INSERT INTO style_group_sources VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(1,1,'danbooru','1','artist',0,0,'pending','s1','s1'), (2,1,'nai_test','1','test',1,0,'pending','s2','s2')],
            )


class StyleGroupMergeTest(unittest.TestCase):
    def test_same_name_groups_and_nai_source_ids_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "primary"
            source = root / "source"
            primary.mkdir()
            source.mkdir()
            make_db(primary / "artist_rater.sqlite", destination=True)
            make_db(source / "artist_rater.sqlite")
            stats = merge_data_directories(primary, [source])
            self.assertGreaterEqual(stats["rows"], 6)
            with closing(sqlite3.connect(primary / "artist_rater.sqlite")) as connection:
                groups = connection.execute("SELECT name,created_at FROM style_groups WHERE name='same-name' ORDER BY created_at").fetchall()
                self.assertEqual(len(groups), 2)
                sources = connection.execute("SELECT source_type,source_id FROM style_group_sources ORDER BY source_type").fetchall()
                self.assertEqual(sources, [('danbooru', '2'), ('nai_test', '2')])

    def test_modern_nai_and_rating_management_source_ids_are_remapped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "primary"
            source = root / "source"
            primary.mkdir()
            source.mkdir()
            make_db(primary / "artist_rater.sqlite", destination=True)
            make_db(source / "artist_rater.sqlite")
            with closing(sqlite3.connect(source / "artist_rater.sqlite")) as connection, connection:
                connection.execute("UPDATE nai_artist_tests SET name='modern-source-test' WHERE id=1")
                connection.execute("INSERT INTO generated_images VALUES (1,'modern-request','generated/one.png')")
                connection.execute("UPDATE nai_artist_test_items SET generated_image_id=1 WHERE id=1")
                connection.execute("INSERT INTO style_groups (id,name,reference_image_path,base_source_type,base_source_id,created_at,updated_at) VALUES (3,'modern-group','','nai_test','1','mg','mg')")
                connection.execute("INSERT INTO style_group_sources VALUES (3,3,'nai_test','1','NAI',0,0,'pending','ms','ms')")
                connection.execute("INSERT INTO style_group_sources VALUES (4,3,'rating_management','all','평가',1,0,'pending','ms','ms')")
                connection.execute("INSERT INTO style_group_artists VALUES (1,3,'source artist','Source Artist','included',0,'ma','ma')")
                connection.execute("INSERT INTO style_group_images VALUES (1,3,'nai_test','1','nai_generated:1','one.png','one.png',8,8,'modern-sha',0,'mi')")
                connection.execute("INSERT INTO style_group_image_artists VALUES (1,'source artist')")
            stats = merge_data_directories(primary, [source])
            self.assertGreaterEqual(stats["rows"], 5)
            with closing(sqlite3.connect(primary / "artist_rater.sqlite")) as connection:
                group = connection.execute("SELECT base_source_type,base_source_id FROM style_groups WHERE name='modern-group'").fetchone()
                self.assertEqual(group, ('nai_test', '2'))
                sources = connection.execute("SELECT source_type,source_id FROM style_group_sources WHERE group_id=(SELECT id FROM style_groups WHERE name='modern-group') ORDER BY source_type").fetchall()
                self.assertEqual(sources, [('nai_test', '2'), ('rating_management', 'all')])
                image = connection.execute("SELECT source_type,source_id FROM style_group_images WHERE sha256='modern-sha'").fetchone()
                self.assertEqual(image, ('nai_test', '2'))
                self.assertEqual(connection.execute("SELECT artist_key FROM style_group_image_artists WHERE image_id=(SELECT id FROM style_group_images WHERE sha256='modern-sha')").fetchone()[0], 'source artist')


if __name__ == "__main__":
    unittest.main()
