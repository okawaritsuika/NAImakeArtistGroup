import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from data_merge import merge_data_directories
from style_worldcup_store import get_worldcup, init_worldcup_tables, list_worldcups


class WorldcupDataMergeTest(unittest.TestCase):
    def _seed_worldcup(self, folder, identifier, image_sources, *, legacy=False):
        folder.mkdir()
        for category, dirname in (("shared", "arca_style_images"), ("confirmed", "confirmed_style_images")):
            images = folder / dirname
            images.mkdir()
            (images / "same.png").write_bytes(f"{identifier}-{category}".encode())
        db = folder / "artist_rater.sqlite"
        if legacy:
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.executescript("""
                    CREATE TABLE style_worldcups (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL UNIQUE,
                        name TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 0, filters_json TEXT NOT NULL,
                        state_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE style_worldcup_participants (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, worldcup_id INTEGER NOT NULL,
                        ordinal INTEGER NOT NULL, title TEXT NOT NULL, source_url TEXT NOT NULL,
                        base_prompt TEXT NOT NULL, recommendation_count INTEGER,
                        image_path TEXT NOT NULL, UNIQUE(worldcup_id, ordinal),
                        FOREIGN KEY(worldcup_id) REFERENCES style_worldcups(id) ON DELETE CASCADE
                    );
                """)
        else:
            init_worldcup_tables(db)
        state = {"round": [0, 1], "next_round": [1], "winner": 1,
                 "history": [{"round_size": 2, "left": 0, "right": 1, "winner": 1}]}
        with closing(sqlite3.connect(db)) as connection, connection:
            connection.execute(
                "INSERT INTO style_worldcups(uuid,name,size,status,revision,filters_json,state_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (identifier, "혼합 월드컵", 2, "completed", 1, "{}", json.dumps(state), "now", "now"),
            )
            for ordinal, image_source in enumerate(image_sources):
                values = [1, ordinal, f"{identifier}-{ordinal}", "", "artist:example", 5, "same.png"]
                columns = "worldcup_id,ordinal,title,source_url,base_prompt,recommendation_count,image_path"
                if not legacy:
                    columns += ",image_source"
                    values.append(image_source)
                connection.execute(
                    f"INSERT INTO style_worldcup_participants({columns}) VALUES({','.join('?' for _ in values)})",
                    values,
                )
        return db, state

    @staticmethod
    def _snapshot(folder):
        return {path.relative_to(folder).as_posix(): path.read_bytes() for path in folder.rglob("*") if path.is_file()}

    def test_id_and_image_collisions_remap_without_changing_ordinals_or_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary, source = root / "primary", root / "source"
            for folder, identifier in ((primary, "primary-uuid"), (source, "source-uuid")):
                folder.mkdir()
                images = folder / "arca_style_images"
                images.mkdir()
                (images / "same.png").write_bytes(identifier.encode())
                db = folder / "artist_rater.sqlite"
                init_worldcup_tables(db)
                state = {"round": [0, 1], "next_round": [1], "winner": 1,
                         "history": [{"round_size": 2, "left": 0, "right": 1, "winner": 1}]}
                with closing(sqlite3.connect(db)) as connection, connection:
                    connection.execute(
                        "INSERT INTO style_worldcups(uuid,name,size,status,revision,filters_json,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (identifier, "같은 이름", 2, "completed", 1, "{}", json.dumps(state), "now", "now"),
                    )
                    connection.executemany(
                        "INSERT INTO style_worldcup_participants(worldcup_id,ordinal,title,source_url,base_prompt,recommendation_count,image_path) VALUES(?,?,?,?,?,?,?)",
                        [(1, ordinal, identifier, "https://arca.live/b/aiart/1", "artist:example", 5, "same.png") for ordinal in range(2)],
                    )
            source_db = source / "artist_rater.sqlite"
            source_before = source_db.read_bytes()
            source_image_before = (source / "arca_style_images" / "same.png").read_bytes()
            stats = merge_data_directories(primary, [source])
            self.assertEqual(stats["rows"], 3)
            primary_db = primary / "artist_rater.sqlite"
            with closing(sqlite3.connect(primary_db)) as connection:
                imported_id = connection.execute("SELECT id FROM style_worldcups WHERE uuid='source-uuid'").fetchone()[0]
                paths = connection.execute("SELECT image_path FROM style_worldcup_participants WHERE worldcup_id=?", (imported_id,)).fetchall()
            self.assertNotEqual(imported_id, 1)
            self.assertEqual(paths, [("same__merged.png",), ("same__merged.png",)])
            imported = get_worldcup(primary_db, primary / "arca_style_images", imported_id)
            self.assertEqual(imported["winner"], 1)
            self.assertEqual(imported["history"], [{"round_size": 2, "left": 0, "right": 1, "winner": 1}])
            self.assertEqual([row["ordinal"] for row in imported["participants"]], [0, 1])
            self.assertTrue(all(row["available"] for row in imported["participants"]))
            self.assertEqual((primary / "arca_style_images" / "same__merged.png").read_bytes(), source_image_before)
            self.assertEqual(source_db.read_bytes(), source_before)
            self.assertEqual((source / "arca_style_images" / "same.png").read_bytes(), source_image_before)
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 0)
            # Force another source import to exercise UUID and remapped FK deduplication.
            with closing(sqlite3.connect(source_db)) as connection, connection:
                connection.execute("UPDATE style_worldcups SET updated_at='later'")
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 0)
            self.assertEqual(len(list_worldcups(primary_db, primary / "arca_style_images")), 2)
            with closing(sqlite3.connect(primary_db)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcup_participants").fetchone()[0], 4)

    def test_mixed_sources_remap_collisions_in_their_own_roots_and_remain_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary, source = root / "primary", root / "source"
            primary_db, _ = self._seed_worldcup(primary, "primary-uuid", ("shared", "confirmed"))
            _, expected_state = self._seed_worldcup(source, "source-uuid", ("shared", "confirmed"))
            # Different collision suffixes make a wrong-root path mapping visible.
            (primary / "confirmed_style_images" / "same__merged.png").write_bytes(b"occupied confirmed name")
            source_before = self._snapshot(source)
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 3)
            with closing(sqlite3.connect(primary_db)) as connection:
                imported_id, state_json = connection.execute(
                    "SELECT id,state_json FROM style_worldcups WHERE uuid='source-uuid'"
                ).fetchone()
                rows = connection.execute(
                    "SELECT ordinal,image_source,image_path FROM style_worldcup_participants WHERE worldcup_id=? ORDER BY ordinal",
                    (imported_id,),
                ).fetchall()
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertNotEqual(imported_id, 1)
            self.assertEqual(json.loads(state_json), expected_state)
            self.assertEqual(rows, [(0, "shared", "same__merged.png"), (1, "confirmed", "same__merged2.png")])
            for category, dirname, filename in (
                ("shared", "arca_style_images", "same__merged.png"),
                ("confirmed", "confirmed_style_images", "same__merged2.png"),
            ):
                self.assertEqual((primary / dirname / filename).read_bytes(), source_before[f"{dirname}/same.png"])
                self.assertEqual((primary / dirname / "same.png").read_bytes(), f"primary-uuid-{category}".encode())
            imported = get_worldcup(
                primary_db, primary / "arca_style_images", imported_id,
                confirmed_image_root=primary / "confirmed_style_images",
            )
            self.assertEqual([row["image_url"] for row in imported["participants"]], [
                "/arca-style-images/same__merged.png", "/confirmed-style-images/same__merged2.png",
            ])
            self.assertTrue(all(row["available"] for row in imported["participants"]))
            summaries = list_worldcups(
                primary_db, primary / "arca_style_images", confirmed_image_root=primary / "confirmed_style_images",
            )
            summary = next(cup for cup in summaries if cup["id"] == imported_id)
            self.assertEqual(summary["winner"], imported["participants"][1])
            self.assertEqual(summary["preview_participants"][0], summary["winner"])
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 0)
            # Re-import the exact same source without changing its DB or files.
            with closing(sqlite3.connect(primary_db)) as connection, connection:
                connection.execute("DELETE FROM data_merge_state")
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 0)
            with closing(sqlite3.connect(primary_db)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcups").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM style_worldcup_participants").fetchone()[0], 4)
            self.assertEqual(self._snapshot(source), source_before)

    def test_legacy_source_without_image_source_defaults_to_shared_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary, source = root / "primary", root / "source"
            primary_db, _ = self._seed_worldcup(primary, "primary-uuid", ("shared", "confirmed"))
            source_db, expected_state = self._seed_worldcup(source, "legacy-uuid", ("shared", "shared"), legacy=True)
            source_before = self._snapshot(source)
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 3)
            with closing(sqlite3.connect(primary_db)) as connection:
                imported_id, state_json = connection.execute(
                    "SELECT id,state_json FROM style_worldcups WHERE uuid='legacy-uuid'"
                ).fetchone()
                self.assertEqual(connection.execute(
                    "SELECT image_source,image_path FROM style_worldcup_participants WHERE worldcup_id=? ORDER BY ordinal",
                    (imported_id,),
                ).fetchall(), [("shared", "same__merged.png"), ("shared", "same__merged.png")])
            self.assertNotEqual(imported_id, 1)
            self.assertEqual(json.loads(state_json), expected_state)
            imported = get_worldcup(
                primary_db, primary / "arca_style_images", imported_id,
                confirmed_image_root=primary / "confirmed_style_images",
            )
            self.assertTrue(all(row["image_url"] == "/arca-style-images/same__merged.png" for row in imported["participants"]))
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 0)
            with closing(sqlite3.connect(source_db)) as connection:
                self.assertNotIn("image_source", {row[1] for row in connection.execute("PRAGMA table_info(style_worldcup_participants)")})
            self.assertEqual(self._snapshot(source), source_before)

    def test_unknown_image_sources_keep_paths_without_guessing_another_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary, source = root / "primary", root / "source"
            primary_db, _ = self._seed_worldcup(primary, "primary-uuid", ("shared", "confirmed"))
            self._seed_worldcup(source, "unknown-uuid", ("future-source", ""))
            source_before = self._snapshot(source)
            self.assertEqual(merge_data_directories(primary, [source])["rows"], 3)
            with closing(sqlite3.connect(primary_db)) as connection:
                imported_id = connection.execute("SELECT id FROM style_worldcups WHERE uuid='unknown-uuid'").fetchone()[0]
                self.assertEqual(connection.execute(
                    "SELECT image_source,image_path FROM style_worldcup_participants WHERE worldcup_id=? ORDER BY ordinal",
                    (imported_id,),
                ).fetchall(), [("future-source", "same.png"), ("", "same.png")])
            imported = get_worldcup(
                primary_db, primary / "arca_style_images", imported_id,
                confirmed_image_root=primary / "confirmed_style_images",
            )
            self.assertTrue(all(not row["available"] and not row["image_url"] for row in imported["participants"]))
            self.assertEqual(self._snapshot(source), source_before)


if __name__ == "__main__":
    unittest.main()
