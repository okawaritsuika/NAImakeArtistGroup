"""Read-only merge of one or more Artist Rater data directories.

The application writes only to the selected primary directory.  Additional
directories are opened read-only and their rows/files are copied into the
primary directory with stable natural-key and foreign-key mappings.  Running
the merge again is intentionally a no-op for rows that were already imported.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


DB_NAME = "artist_rater.sqlite"

# Image paths stored by the application are relative to one of these roots.
IMAGE_DIRS = {
    "thumbnails": "thumbnails",
    "generated": "generated",
    "confirmed": "confirmed_style_images",
    "comparison": "comparison_images",
    "shared": "arca_style_images",
    "style_group": "style_group_images",
}

# Parent tables must be processed before child tables so that ids can be
# translated.  Tables added by later versions are handled by the fallback
# fingerprint importer below, if they do not have foreign-key dependencies.
TABLE_ORDER = [
    "ratings",
    "artist_cache",
    "skipped_artists",
    "art_styles",
    "arca_style_items",
    "arca_collection_runs",
    "arca_style_images",
    "generated_images",
    "generation_requests",
    "confirmed_styles",
    "comparison_groups",
    "rating_examples",
    "confirmed_style_images",
    "comparison_results",
    "arca_collection_run_items",
    "arca_collection_invalidations",
    "arca_prompt_preset_index",
    "arca_seed_imports",
    "nai_artist_tests",
    "nai_artist_test_items",
    "nai_artist_test_ratings",
    "nai_artist_test_images",
    "style_groups",
    "style_group_sources",
    "style_group_artists",
    "style_group_decisions",
    "style_group_images",
    "style_group_image_artists",
]

SKIP_TABLES = {
    "settings", "sqlite_sequence", "arca_collection_jobs", "data_merge_state",
    "arca_maintenance_state", "arca_seed_import_state", "arca_seed_metadata",
}

PATH_COLUMNS = {
    "ratings": {"representative_thumbnail_path": "thumbnails"},
    "rating_examples": {"image_path": "thumbnails"},
    "art_styles": {"representative_image_path": "generated"},
    "generated_images": {"image_path": "generated"},
    "confirmed_styles": {"image_path": "confirmed"},
    "confirmed_style_images": {"image_path": "confirmed"},
    "comparison_results": {"image_path": "comparison"},
    "arca_style_items": {"representative_image_path": "shared"},
    "arca_style_images": {"image_path": "shared"},
    "style_group_images": {"image_path": "style_group"},
    "style_groups": {"reference_image_path": "style_group"},
}

FK_COLUMNS = {
    ("rating_examples", "rating_id"): ("ratings", "id"),
    ("generated_images", "style_id"): ("art_styles", "id"),
    ("generated_images", "shared_dependency_reference_id"): ("arca_style_images", "id"),
    ("generation_requests", "image_id"): ("generated_images", "id"),
    ("confirmed_style_images", "style_id"): ("confirmed_styles", "id"),
    ("comparison_results", "group_id"): ("comparison_groups", "id"),
    ("comparison_results", "confirmed_style_id"): ("confirmed_styles", "id"),
    ("arca_style_images", "item_id"): ("arca_style_items", "id"),
    ("arca_collection_run_items", "run_id"): ("arca_collection_runs", "id"),
    ("arca_collection_run_items", "item_id"): ("arca_style_items", "id"),
    ("arca_prompt_preset_index", "image_id"): ("arca_style_images", "id"),
    ("style_group_sources", "group_id"): ("style_groups", "id"),
    ("style_group_artists", "group_id"): ("style_groups", "id"),
    ("style_group_decisions", "group_id"): ("style_groups", "id"),
    ("style_group_decisions", "source_id"): ("style_group_sources", "id"),
    ("style_group_images", "group_id"): ("style_groups", "id"),
    ("style_group_image_artists", "image_id"): ("style_group_images", "id"),
    ("nai_artist_test_items", "test_id"): ("nai_artist_tests", "id"),
    ("nai_artist_test_items", "generated_image_id"): ("generated_images", "id"),
    ("nai_artist_test_ratings", "test_id"): ("nai_artist_tests", "id"),
    ("nai_artist_test_images", "test_id"): ("nai_artist_tests", "id"),
    ("nai_artist_test_images", "item_id"): ("nai_artist_test_items", "id"),
    ("nai_artist_test_images", "generated_image_id"): ("generated_images", "id"),
}

NATURAL_KEYS = {
    "ratings": ("artist_tag",),
    "artist_cache": ("artist_tag",),
    "skipped_artists": ("artist_tag",),
    "art_styles": ("style_hash",),
    "generated_images": ("request_id",),
    "generation_requests": ("request_id",),
    "confirmed_style_images": ("image_path",),
    "arca_style_items": ("source_url",),
    "arca_style_images": ("item_id", "image_url"),
    "arca_collection_invalidations": (
        "keyword", "tabs", "max_pages", "max_posts", "search_scope", "invalidated_date"
    ),
    "arca_prompt_preset_index": ("image_id",),
    "arca_seed_imports": ("seed_hash",),
    "style_groups": ("name", "reference_image_path", "created_at"),
    "style_group_artists": ("group_id", "artist_key"),
    "nai_artist_tests": ("name", "config_json", "created_at"),
    "nai_artist_test_items": ("test_id", "ordinal"),
    "nai_artist_test_ratings": ("test_id", "artist_tag"),
    "nai_artist_test_images": ("test_id", "item_id"),
    "style_group_sources": ("group_id", "source_type", "source_id"),
    "style_group_decisions": ("group_id", "source_id", "candidate_key"),
    "style_group_images": ("group_id", "sha256"),
    "style_group_image_artists": ("image_id", "artist_key"),
}


def resolve_data_directory(value):
    """Resolve a selected project/data path to the directory holding the DB.

    The launcher lets users choose a convenient project directory, while the
    source checkout keeps its runtime data in ``artist_rater/data``.  Keep a
    missing directory unchanged so it remains a valid new primary directory.
    """

    directory = Path(value).expanduser().resolve()
    if (directory / DB_NAME).is_file():
        return directory
    candidates = (
        directory / "artist_rater" / "data",
        directory / "data",
        directory / "artist_rater",
    )
    for candidate in candidates:
        if (candidate / DB_NAME).is_file():
            return candidate.resolve()
    return directory


def normalize_data_dirs(data_dirs, primary_data_dir=None):
    """Return ``(primary, sources)`` as resolved unique paths.

    The primary defaults to the first supplied directory.  A primary that
    does not exist yet is allowed because ``init_db`` creates it.  Source
    directories are not created or modified.
    """

    values = [resolve_data_directory(value) for value in (data_dirs or []) if str(value).strip()]
    if not values:
        raise ValueError("하나 이상의 data 디렉터리를 지정해 주세요.")
    unique = []
    seen = set()
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    primary = resolve_data_directory(primary_data_dir) if primary_data_dir else unique[0]
    if primary not in unique:
        raise ValueError("primary data 디렉터리는 --data-dir 중 하나여야 합니다.")
    return primary, [value for value in unique if value != primary]


def _connect(path, read_only=False):
    if read_only:
        connection = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _columns(connection, table):
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _value_key(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    return value


def _row_fingerprint(table, row, columns):
    excluded = {"id", "created_at", "updated_at", "collected_at", "imported_at"}
    payload = [(name, _value_key(row[name])) for name in columns if name not in excluded]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _natural_key(table, row, columns, path_map=None, mapped_values=None):
    keys = NATURAL_KEYS.get(table)
    if keys:
        values = mapped_values or row
        return tuple(_value_key(values.get(key) if hasattr(values, "get") else values[key]) for key in keys)
    if table == "confirmed_styles":
        values = mapped_values or row
        source_id = values["source_id"] if "source_id" in columns else None
        source_type = values["source_type"] if "source_type" in columns else ""
        if source_id is not None:
            return (source_type, source_id)
        image_path = values["image_path"] if "image_path" in columns else ""
        if image_path:
            return ("image", image_path)
    if table == "comparison_results":
        values = mapped_values or row
        get_value = values.get if hasattr(values, "get") else lambda key, default=None: values[key] if key in values.keys() else default
        return (
            get_value("group_id"),
            get_value("confirmed_style_id"),
            get_value("style_name", ""),
        )
    return ("fingerprint", _row_fingerprint(table, mapped_values or row, columns))


def _existing_index(connection, table, columns, path_map=None):
    index = {}
    for row in connection.execute(f'SELECT * FROM "{table}"'):
        key = _natural_key(table, row, columns)
        index.setdefault(key, row)
    return index


def _map_path(value, category, path_map):
    if value in (None, ""):
        return value
    normalized = str(value).replace("\\", "/")
    return path_map.get((category, normalized), value)


def _copy_file_tree(source_root, target_root):
    """Copy files and return source-relative -> primary-relative mappings."""

    source_root, target_root = Path(source_root), Path(target_root)
    if not source_root.is_dir():
        return {}
    target_root.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for existing in target_root.rglob("*"):
        if existing.is_file():
            try:
                digest = hashlib.sha256(existing.read_bytes()).hexdigest()
            except OSError:
                continue
            hashes.setdefault(digest, existing.relative_to(target_root).as_posix())
    mapping = {}
    for source in sorted(item for item in source_root.rglob("*") if item.is_file()):
        relative = source.relative_to(source_root).as_posix()
        try:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
        except OSError:
            continue
        if digest in hashes:
            mapping[relative] = hashes[digest]
            continue
        target = target_root / relative
        if target.exists():
            target = target.with_name(f"{target.stem}__merged{target.suffix}")
            suffix = 2
            while target.exists():
                target = target.with_name(f"{source.stem}__merged{suffix}{source.suffix}")
                suffix += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target_relative = target.relative_to(target_root).as_posix()
        hashes[digest] = target_relative
        mapping[relative] = target_relative
    return mapping


def copy_data_files(primary_dir, source_dir):
    """Copy user data images without changing ``source_dir``."""

    path_map = {}
    for category, dirname in IMAGE_DIRS.items():
        copied = _copy_file_tree(Path(source_dir) / dirname, Path(primary_dir) / dirname)
        path_map.update({(category, source): target for source, target in copied.items()})
    return path_map


def _source_fingerprint(source_dir):
    """Return a cheap fingerprint without reading source file contents.

    The merge only needs to detect whether a source may have changed since the
    last successful import.  File paths, sizes, and nanosecond mtimes catch
    additions, removals, and normal edits while avoiding a second full read of
    large image trees on every application start.
    """

    source_dir = Path(source_dir)
    entries = []
    source_db = source_dir / DB_NAME
    paths = [
        source_db,
        source_db.with_name(source_db.name + "-wal"),
        source_db.with_name(source_db.name + "-shm"),
    ]
    for dirname in IMAGE_DIRS.values():
        root = source_dir / dirname
        if not root.is_dir():
            entries.append((dirname, "missing"))
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            paths.append(path)
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            relative = path.relative_to(source_dir).as_posix()
            entries.append((relative, "unreadable"))
            continue
        relative = path.relative_to(source_dir).as_posix()
        entries.append((relative, stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ensure_merge_state_table(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS data_merge_state (
            source_path TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL
        )
        """
    )


def _mapped_foreign_value(table, column, value, id_maps):
    if value is None:
        return None
    parent = FK_COLUMNS.get((table, column))
    if not parent:
        return value
    return id_maps.get(parent[0], {}).get(value, value)


def _map_special_values(table, values, id_maps):
    """Translate references stored in JSON/non-FK columns."""

    if table == "style_groups" and values.get("base_source_type"):
        source_type = str(values.get("base_source_type") or "").strip().lower()
        if source_type in {"nai", "nai_test"} and values.get("base_source_id") not in (None, ""):
            try:
                raw_id = int(values["base_source_id"])
            except (TypeError, ValueError):
                raw_id = values["base_source_id"]
            values["base_source_id"] = id_maps.get("nai_artist_tests", {}).get(raw_id, raw_id)
        elif source_type in {"rating", "ratings", "danbooru"}:
            values["base_source_type"] = "rating_management"
            values["base_source_id"] = "all"

    if table == "style_group_sources" and "source_type" in values and "source_id" in values:
        source_type = str(values.get("source_type") or "").strip().lower()
        parent = {
            "danbooru": "ratings",
            "rating": "ratings",
            "ratings": "ratings",
            "nai_test": "nai_artist_tests",
            "nai": "nai_artist_tests",
        }.get(source_type)
        raw_source_id = values.get("source_id")
        if source_type in {"rating_management", "ratings_management"}:
            values["source_id"] = "all"
            return values
        if parent and raw_source_id not in (None, ""):
            try:
                source_id = int(raw_source_id)
            except (TypeError, ValueError):
                source_id = raw_source_id
            values["source_id"] = id_maps.get(parent, {}).get(source_id, source_id)

    if table == "style_group_images" and "source_type" in values and "source_id" in values:
        source_type = str(values.get("source_type") or "").strip().lower()
        if source_type in {"rating_management", "ratings_management"}:
            values["source_type"] = "rating_management"
            values["source_id"] = "all"
        elif source_type in {"nai", "nai_test"}:
            values["source_type"] = "nai_test"
            try:
                raw_id = int(values["source_id"])
            except (TypeError, ValueError):
                raw_id = values["source_id"]
            values["source_id"] = id_maps.get("nai_artist_tests", {}).get(raw_id, raw_id)

    if table == "confirmed_styles" and values.get("source_id") is not None:
        parent = {
            "generated": "generated_images",
            "shared": "arca_style_images",
        }.get(str(values.get("source_type") or ""))
        if parent:
            values["source_id"] = id_maps.get(parent, {}).get(values["source_id"], values["source_id"])
    if table == "comparison_groups" and "selected_style_ids_json" in values:
        try:
            selected = json.loads(values["selected_style_ids_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            selected = []
        if isinstance(selected, list):
            selected = [
                id_maps.get("confirmed_styles", {}).get(value, value)
                for value in selected
            ]
            values["selected_style_ids_json"] = json.dumps(selected, ensure_ascii=False)
    if table == "arca_collection_runs" and "job_id" in values:
        # Collection jobs contain live process/resume state.  Do not import
        # them; imported historical runs must never point at a source job.
        values["job_id"] = None
    return values


def _insert_mapped_row(connection, table, row, destination_columns):
    values = {}
    for column in destination_columns:
        if column not in row.keys() or column == "id":
            continue
        # ``row`` has already had all FK, path and embedded references mapped
        # by _merge_table.  Applying those transforms again would remap a
        # destination id that happens to also be a source id.
        values[column] = row[column]
    names = list(values)
    if not names:
        cursor = connection.execute(f'INSERT INTO "{table}" DEFAULT VALUES')
    else:
        placeholders = ",".join("?" for _ in names)
        cursor = connection.execute(
            f'INSERT INTO "{table}" ({",".join(names)}) VALUES ({placeholders})',
            [values[name] for name in names],
        )
    return cursor.lastrowid if "id" in destination_columns else None


def _enrich_existing_row(connection, table, existing, mapped, destination_columns):
    """Fill empty primary fields from a deduplicated source row.

    This matters for the bundled metadata seed: it intentionally has empty
    local image paths, while a source data directory may have downloaded the
    corresponding file.  Existing non-empty primary values always win.
    """

    if "id" not in destination_columns or existing is None:
        return existing
    updates = {}
    for column in destination_columns:
        if column == "id" or column not in mapped:
            continue
        current = existing[column]
        incoming = mapped[column]
        if current in (None, "") and incoming not in (None, ""):
            updates[column] = incoming
    if updates:
        connection.execute(
            f'UPDATE "{table}" SET {",".join(f"{column}=?" for column in updates)} WHERE id=?',
            [*updates.values(), existing["id"]],
        )
        return connection.execute(
            f'SELECT * FROM "{table}" WHERE id=?', (existing["id"],)
        ).fetchone()
    return existing


def _merge_table(connection, source, table, id_maps, path_map):
    source_columns = _columns(source, table)
    destination_columns = _columns(connection, table)
    existing = _existing_index(connection, table, destination_columns, path_map=path_map)
    table_map = id_maps.setdefault(table, {})
    for row in source.execute(f'SELECT * FROM "{table}"'):
        mapped = dict(row)
        for column in destination_columns:
            if column in mapped:
                mapped[column] = _mapped_foreign_value(table, column, mapped[column], id_maps)
                category = PATH_COLUMNS.get(table, {}).get(column)
                if category:
                    mapped[column] = _map_path(mapped[column], category, path_map)
        mapped = _map_special_values(table, mapped, id_maps)
        key = _natural_key(table, row, source_columns, path_map=path_map, mapped_values=mapped)
        old = existing.get(key)
        if old is not None:
            old = _enrich_existing_row(connection, table, old, mapped, destination_columns)
            existing[key] = old
            if "id" in source_columns and "id" in destination_columns:
                table_map[row["id"]] = old["id"]
            continue
        try:
            new_id = _insert_mapped_row(connection, table, mapped, destination_columns)
        except sqlite3.IntegrityError:
            # A source may be from a newer schema with a constraint not visible
            # to its own older data.  Re-read the natural key after conflict so
            # repeated startup remains harmless instead of dropping the source.
            existing = _existing_index(connection, table, destination_columns, path_map=path_map)
            old = existing.get(key)
            if old is None:
                raise
            old = _enrich_existing_row(connection, table, old, mapped, destination_columns)
            new_id = old["id"] if "id" in destination_columns else None
        if "id" in source_columns and "id" in destination_columns:
            table_map[row["id"]] = new_id
        if new_id is not None:
            inserted = connection.execute(
                f'SELECT * FROM "{table}" WHERE id=?', (new_id,)
            ).fetchone()
            existing[key] = inserted
    return table_map


def merge_data_directories(primary_dir, source_dirs):
    """Merge source DBs/files into primary and return import statistics."""

    primary = resolve_data_directory(primary_dir)
    primary.mkdir(parents=True, exist_ok=True)
    sources = [resolve_data_directory(value) for value in source_dirs or []]
    sources = [value for value in dict.fromkeys(sources) if value != primary]
    stats = {"sources": 0, "rows": 0, "files": 0}
    db_path = primary / DB_NAME
    if not sources:
        return stats
    with closing(_connect(db_path)) as destination, destination:
        _ensure_merge_state_table(destination)
        destination_tables = _tables(destination)
        for source_dir in sources:
            source_db = source_dir / DB_NAME
            if not source_db.is_file():
                continue
            fingerprint = _source_fingerprint(source_dir)
            state = destination.execute(
                "SELECT fingerprint FROM data_merge_state WHERE source_path=?",
                (str(source_dir),),
            ).fetchone()
            if state is not None and state[0] == fingerprint:
                stats["sources"] += 1
                continue
            path_map = copy_data_files(primary, source_dir)
            stats["files"] += len(path_map)
            with closing(_connect(source_db, read_only=True)) as source:
                source_tables = _tables(source)
                id_maps = {}
                ordered = [table for table in TABLE_ORDER if table in source_tables and table in destination_tables]
                ordered.extend(
                    table
                    for table in sorted(source_tables - set(ordered) - SKIP_TABLES)
                    if table in destination_tables
                )
                for table in ordered:
                    before = destination.total_changes
                    _merge_table(destination, source, table, id_maps, path_map)
                    stats["rows"] += destination.total_changes - before
            destination.execute(
                "INSERT INTO data_merge_state(source_path,fingerprint) VALUES(?,?) "
                "ON CONFLICT(source_path) DO UPDATE SET fingerprint=excluded.fingerprint",
                (str(source_dir), fingerprint),
            )
            stats["sources"] += 1
    return stats


# Alias kept short for callers and tests.
merge_data_dirs = merge_data_directories
