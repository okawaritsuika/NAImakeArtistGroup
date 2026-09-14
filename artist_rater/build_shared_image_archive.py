"""Build a verified WebP pack against an explicit, metadata-only release seed."""

import argparse
import hashlib
import json
import os
import sqlite3
import zipfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from pathlib import Path

from arca_style_collector import _image_identity, extract_novelai_metadata
from shared_style_webp import verified_webp


def read_images(db_path):
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT image.*, item.source_url FROM arca_style_images image "
            "JOIN arca_style_items item ON item.id=image.item_id WHERE image.metadata_status='ok'"
        )]


def image_key(row):
    return row["source_url"], _image_identity(row["image_url"])


def archive_image_name(source_url, identity):
    return hashlib.sha256((source_url + "\n" + identity).encode()).hexdigest() + ".webp"


def _convert_entry(task):
    row, source, cache, quality = task
    original = source.read_bytes()
    fingerprint = hashlib.sha256(original + f"webp-v1-q{quality}".encode()).hexdigest()
    converted_path = cache / (fingerprint + ".webp")
    if converted_path.exists():
        converted = converted_path.read_bytes()
        before, after = [extract_novelai_metadata(data) for data in (original, converted)]
        for metadata in (before, after):
            metadata["raw_metadata_json"] = json.loads(metadata["raw_metadata_json"])
        if before != after or after["metadata_status"] != "ok":
            raise ValueError(f"Metadata verification failed for seed image {row['id']}.")
    else:
        converted = verified_webp(original, quality)
        # Two references can share a source: replace atomically after verification.
        temporary = converted_path.with_suffix(f".{os.getpid()}.partial")
        temporary.write_bytes(converted)
        temporary.replace(converted_path)
    identity = _image_identity(row["image_url"])
    return len(original), {
        "image_id": row["id"], "item_id": row["item_id"],
        "source_url": row["source_url"], "image_identity": identity,
        "name": archive_image_name(row["source_url"], identity),
        "bytes": len(converted), "sha256": hashlib.sha256(converted).hexdigest(),
        "cache_path": converted_path,
    }


def build_archive(seed, sources, output, quality=90, workers=4):
    """Sources are (DB, image directory) pairs; all are strictly read-only."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "webp_cache"
    cache.mkdir(exist_ok=True)
    originals = {}
    for db_path, image_dir in sources:
        root = Path(image_dir).resolve()
        for row in read_images(db_path):
            if not row["image_path"]:
                continue
            path = (root / row["image_path"]).resolve()
            if path.is_relative_to(root) and path.is_file():
                originals[image_key(row)] = path
    rows = read_images(seed)
    keys = [image_key(row) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("Release seed contains duplicate stable image identities.")
    missing = sum(key not in originals for key in keys)
    if missing:
        raise ValueError(f"Release seed has {missing} missing source images.")
    files = []
    original_bytes = 0
    tasks = [(row, originals[image_key(row)], cache, quality) for row in rows]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for index, (size, entry) in enumerate(executor.map(_convert_entry, tasks), 1):
            original_bytes += size
            files.append(entry)
            if index % 100 == 0 or index == len(rows):
                print(json.dumps({"verified": index, "total": len(rows)}), flush=True)
    manifest = {
        "format": "naimakeartistgroup-shared-images", "version": 2,
        "quality": quality, "file_count": len(files),
        "total_bytes": sum(entry["bytes"] for entry in files),
        "seed_sha256": hashlib.sha256(Path(seed).read_bytes()).hexdigest(),
        "files": [{k: v for k, v in entry.items() if k != "cache_path"} for entry in files],
    }
    filename = "NAImakeArtistGroup_shared_images_20260914_webp.zip"
    archive_path = output / filename
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for entry in files:
            archive.write(entry["cache_path"], "arca_style_images/" + entry["name"])
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    with archive_path.open("rb") as handle:
        archive_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    result = {
        "filename": filename, "bytes": archive_path.stat().st_size,
        "sha256": archive_hash, "image_count": len(files),
        "image_bytes": manifest["total_bytes"], "original_bytes": original_bytes,
        "quality": quality, "metadata_verified": len(files),
        "seed_sha256": manifest["seed_sha256"],
    }
    (output / "archive_info.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--source", nargs=2, action="append", required=True, metavar=("DB", "IMAGES"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quality", type=int, default=90, choices=range(1, 101))
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 17))
    args = parser.parse_args()
    print(json.dumps(build_archive(args.seed, args.source, args.output, args.quality, args.workers)))


if __name__ == "__main__":
    main()
