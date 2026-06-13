import hashlib
import json
import math


def normalize_style_artists(artists):
    normalized = []
    seen = set()
    for item in artists or []:
        if not isinstance(item, dict):
            raise ValueError("Each artist must be an object.")
        artist = str(item.get("artist") or "").strip()
        if not artist:
            raise ValueError("Artist tags must not be empty.")
        if artist in seen:
            raise ValueError("Duplicate artists are not allowed.")
        raw_weight = item.get("weight")
        if isinstance(raw_weight, bool):
            raise ValueError("Artist weights must be positive numbers.")
        try:
            weight = round(float(raw_weight), 2)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Artist weights must be positive numbers.") from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("Artist weights must be positive numbers.")
        try:
            score = int(item.get("score") or 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Artist scores must be integers.") from exc
        normalized.append({"artist": artist, "weight": weight, "score": score})
        seen.add(artist)
    if not normalized:
        raise ValueError("At least one artist is required.")
    return normalized


def format_weight(value):
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def build_artist_prompt(artists):
    return ", ".join(
        f'{format_weight(item["weight"])}::{item["artist"]}::'
        for item in normalize_style_artists(artists)
    )


def style_hash(artists):
    identity = [
        {"artist": item["artist"], "weight": item["weight"]}
        for item in normalize_style_artists(artists)
    ]
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
