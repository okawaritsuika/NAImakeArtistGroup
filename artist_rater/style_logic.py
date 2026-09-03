import hashlib
import json
import math
import random
import re


SCORE_SELECTION_WEIGHT = {1: 0.08, 2: 0.2, 3: 0.55, 4: 1.0, 5: 1.6}
_WEIGHTED_PROMPT_GROUP = re.compile(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*::([\s\S]*?)::")
_NUMERIC_PROMPT_MARKER = re.compile(r"(?<![0-9.])([+-]?[0-9]+(?:\.[0-9]+)?)\s*::")
_MISSING_PROMPT_SEPARATOR = re.compile(r"::\s*(?=[+-]?[0-9]+(?:\.[0-9]+)?\s*::)")


def normalize_numeric_prompt_closers(prompt):
    """Normalize weighted prompt markers and numeric tag endings before ``::``."""
    text = str(prompt or "")

    def normalize_group(match):
        prefix = text[: match.start()].rstrip()
        if prefix and not prefix.endswith((",", "::")):
            return match.group(0)
        body = match.group(2).rstrip()
        if body[-1:] in "0123456789":
            body += " "
        return f"{match.group(1)}::{body}::"

    text = _WEIGHTED_PROMPT_GROUP.sub(normalize_group, text)
    weighted_spans = [
        match.span()
        for match in _WEIGHTED_PROMPT_GROUP.finditer(text)
        if not text[: match.start()].rstrip()
        or text[: match.start()].rstrip().endswith((",", "::"))
    ]

    def normalize_marker(match):
        if any(start <= match.start() < end for start, end in weighted_spans):
            return match.group(0)
        prefix = text[: match.start()].rstrip()
        if not prefix or prefix.endswith((",", "::")):
            return f"{match.group(1)}::"
        return f"{match.group(1)} ::"

    text = _NUMERIC_PROMPT_MARKER.sub(normalize_marker, text)
    return _MISSING_PROMPT_SEPARATOR.sub("::, ", text)


def _integer_value(value, error_message):
    if isinstance(value, bool):
        raise ValueError(error_message)
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(error_message) from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError(error_message)
    return int(numeric)


def exact_score(value, error_message="평점은 1부터 5 사이의 정수여야 합니다."):
    if isinstance(value, bool):
        raise ValueError(error_message)
    if isinstance(value, int):
        score = value
    elif isinstance(value, str) and value in {"1", "2", "3", "4", "5"}:
        score = int(value)
    else:
        raise ValueError(error_message)
    if score not in SCORE_SELECTION_WEIGHT:
        raise ValueError(error_message)
    return score


def normalize_artist_key(value):
    """Return the existing artist-tag matching form used by source stores."""
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def score_bucket(value):
    """Apply the style maker's historical half-up 1~5 score bucket."""
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("평점은 유한한 숫자여야 합니다.")
    return max(1, min(5, int(math.floor(numeric + 0.5))))


def _valid_score(value):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) and 1 <= numeric <= 5 else None


def merge_artist_sources(sources):
    """Merge source memberships and score contributions without database access.

    Each source is a mapping with ``source_type``, ``source_id`` and an
    ``artists`` list.  An artist may provide a direct ``score`` or an explicit
    ``contributions`` list.  Explicit contributions are used by style groups
    so their connected rating/NAI sources, rather than the group itself, are
    recorded as provenance.
    """
    buckets = {}
    source_priority = {"rating_management": 0, "nai_test": 1, "style_group": 2}

    for source in sources or []:
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("source_type") or "").strip().lower()
        source_id = str(source.get("source_id") or "").strip()
        source_label = str(source.get("label") or "").strip()
        priority = source_priority.get(source_type, 99)
        for artist in source.get("artists") or []:
            if not isinstance(artist, dict):
                continue
            display = str(
                artist.get("artist_tag") or artist.get("artist") or artist.get("artist_key") or ""
            ).strip()
            key = normalize_artist_key(artist.get("artist_key") or display)
            if not key:
                continue
            bucket = buckets.setdefault(
                key,
                {
                    "artist_key": key,
                    "artist": display or key,
                    "artist_tag": display or key,
                    "_display_priority": priority,
                    "_contributions": {},
                    "_metadata": {},
                    "_image_count": 0,
                },
            )
            if display and priority < bucket["_display_priority"]:
                bucket["artist"] = display
                bucket["artist_tag"] = display
                bucket["_display_priority"] = priority
            image_count = artist.get("image_count")
            if isinstance(image_count, (int, float)) and not isinstance(image_count, bool) and math.isfinite(float(image_count)):
                bucket["_image_count"] = max(bucket["_image_count"], int(image_count))
            metadata = artist.get("metadata")
            if isinstance(metadata, dict) and priority < bucket.get("_metadata_priority", 99):
                bucket["_metadata"] = dict(metadata)
                bucket["_metadata_priority"] = priority

            contributions = artist.get("contributions")
            if contributions is None:
                contributions = []
                if source_type != "style_group" and "score" in artist:
                    contributions.append({
                        "origin_type": source_type,
                        "origin_id": source_id,
                        "label": source_label,
                        "score": artist.get("score"),
                    })
            for contribution in contributions:
                if not isinstance(contribution, dict):
                    continue
                origin_type = str(contribution.get("origin_type", contribution.get("source_type", source_type)) or "").strip().lower()
                origin_id = str(contribution.get("origin_id", contribution.get("source_id", source_id)) or "").strip()
                provenance = (origin_type, origin_id, key)
                numeric = _valid_score(contribution.get("score"))
                if numeric is None or provenance in bucket["_contributions"]:
                    continue
                bucket["_contributions"][provenance] = {
                    "score": numeric,
                    "source_type": origin_type,
                    "source_id": origin_id,
                    "label": str(contribution.get("label") or source_label).strip(),
                }

    result = []
    for key in sorted(buckets):
        bucket = buckets[key]
        contributions = list(bucket["_contributions"].values())
        if not contributions:
            continue
        raw_score = sum(item["score"] for item in contributions) / len(contributions)
        item = {
            "artist_key": key,
            "artist": bucket["artist"],
            "artist_tag": bucket["artist_tag"],
            "score": score_bucket(raw_score),
            "score_bucket": score_bucket(raw_score),
            "raw_score": raw_score,
            "image_count": bucket["_image_count"],
            "score_sources": [
                {
                    "source_type": contribution["source_type"],
                    "source_id": contribution["source_id"],
                    "label": contribution["label"],
                }
                for contribution in contributions
            ],
        }
        item.update(bucket["_metadata"])
        result.append(item)
    return result


# Descriptive aliases keep the pure API discoverable to callers and tests.
merge_style_artist_sources = merge_artist_sources
artist_score_bucket = score_bucket


def select_artists(pool, count, allowed_scores, rng_seed=None):
    try:
        requested_count = _integer_value(count, "선택 가능한 작가 수를 확인하세요.")
        allowed = {exact_score(score) for score in allowed_scores}
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ValueError) and "평점" in str(exc):
            raise
        raise ValueError("선택 가능한 작가 수와 평점을 확인하세요.") from exc

    remaining = []
    seen = set()
    for item in pool or []:
        if not isinstance(item, dict):
            continue
        artist = str(item.get("artist") or "").strip()
        score = exact_score(item.get("score"))
        if not artist or score not in allowed or score not in SCORE_SELECTION_WEIGHT:
            continue
        if artist in seen:
            continue
        remaining.append({"artist": artist, "score": score})
        seen.add(artist)

    if requested_count < 1 or requested_count > len(remaining):
        raise ValueError("선택 가능한 작가 수를 확인하세요.")

    rng = random.Random(rng_seed)
    selected = []
    while len(selected) < requested_count:
        weights = [SCORE_SELECTION_WEIGHT[item["score"]] for item in remaining]
        chosen_index = rng.choices(range(len(remaining)), weights=weights, k=1)[0]
        selected.append(remaining.pop(chosen_index))
    rng.shuffle(selected)
    return selected


def _cent_bounds(low, high):
    low = float(low)
    high = float(high)
    epsilon = 1e-9
    minimum_cent = max(1, math.ceil(low * 100 - epsilon))
    maximum_cent = math.floor(high * 100 + epsilon)
    if minimum_cent > maximum_cent:
        raise ValueError("범위 안에 유효한 양수 센트 가중치가 없습니다.")
    return minimum_cent, maximum_cent


def random_weight(rng, low, high):
    minimum_cent, maximum_cent = _cent_bounds(low, high)
    return rng.randint(minimum_cent, maximum_cent) / 100


def _tier_counts(count, tier_names):
    if count <= 0:
        return {name: 0 for name in tier_names}
    names = set(tier_names)
    counts = {name: 0 for name in tier_names}
    if names == {"high"}:
        counts["high"] = count
        return counts

    high = count // 4 if "high" in names else 0
    if "high" in names:
        counts["high"] = high
    remaining = count - high
    if "low" in names and "mid" in names:
        mid = min(round(count * 0.33), remaining)
        counts["mid"] = mid
        counts["low"] = remaining - mid
    elif "mid" in names:
        counts["mid"] = remaining
    elif "low" in names:
        counts["low"] = remaining
    return counts


def build_balanced_tiers(count, minimum, maximum):
    conceptual = (
        ("low", 0.1, 0.9),
        ("mid", 1.0, 1.49),
        ("high", 1.5, maximum),
    )
    available = []
    for name, low, high in conceptual:
        clipped_low = max(minimum, low)
        clipped_high = min(maximum, high)
        if clipped_low <= clipped_high:
            available.append(
                {"name": name, "min": clipped_low, "max": clipped_high}
            )
    if not available:
        return [
            {
                "name": "range",
                "min": minimum,
                "max": maximum,
                "max_people": count,
            }
        ]

    counts = _tier_counts(count, [tier["name"] for tier in available])
    return [
        {**tier, "max_people": counts[tier["name"]]}
        for tier in available
        if counts[tier["name"]] > 0
    ]


def validate_custom_ranges(ranges, artist_count, minimum, maximum):
    validated = []
    for item in ranges or []:
        if not isinstance(item, dict):
            raise ValueError("사용자 구간을 확인하세요.")
        try:
            low = float(item.get("min"))
            high = float(item.get("max"))
            capacity = _integer_value(item.get("max_people"), "사용자 구간을 확인하세요.")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("사용자 구간을 확인하세요.") from exc
        if (
            not math.isfinite(low)
            or not math.isfinite(high)
            or low <= 0
            or low > high
            or low < minimum
            or high > maximum
            or capacity < 1
            or isinstance(item.get("max_people"), bool)
        ):
            raise ValueError("사용자 구간을 확인하세요.")
        _cent_bounds(low, high)
        validated.append(
            {"name": f"custom_{len(validated)}", "min": low, "max": high, "max_people": capacity}
        )

    ordered = sorted(validated, key=lambda item: (item["min"], item["max"]))
    for previous, current in zip(ordered, ordered[1:]):
        if current["min"] <= previous["max"]:
            raise ValueError("사용자 구간이 서로 겹치지 않게 입력하세요.")
    if sum(item["max_people"] for item in validated) < artist_count:
        raise ValueError("사용자 구간의 총 수용 인원이 작가 수보다 적습니다.")
    return validated


def assign_items_to_tiers(items, tiers, rng, high_first):
    assigned = []
    item_index = 0
    ordered_tiers = (
        sorted(tiers, key=lambda item: item["min"], reverse=True)
        if high_first
        else tiers
    )
    for tier in ordered_tiers:
        for _ in range(tier["max_people"]):
            if item_index >= len(items):
                return assigned
            item = dict(items[item_index])
            item["weight"] = random_weight(rng, tier["min"], tier["max"])
            assigned.append(item)
            item_index += 1
    return assigned


def assign_weights(
    artists,
    mode,
    minimum,
    maximum,
    prefer_high_scores,
    ranges,
    rng_seed=None,
    profile=None,
    positions=None,
):
    try:
        minimum = float(minimum)
        maximum = float(maximum)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("가중치 범위를 확인하세요.") from exc
    if (
        not math.isfinite(minimum)
        or not math.isfinite(maximum)
        or minimum <= 0
        or maximum < minimum
    ):
        raise ValueError("가중치 범위를 확인하세요.")
    if mode not in {"random", "balanced", "custom", "profile"}:
        raise ValueError("가중치 모드를 확인하세요.")

    rng = random.Random(rng_seed)
    items = []
    for index, item in enumerate(artists or []):
        normalized = dict(item)
        if item.get("score") is not None:
            normalized["score"] = exact_score(item.get("score"))
        normalized["_index"] = index
        items.append(normalized)
    if mode == "profile":
        points = validate_weight_profile(profile, minimum, maximum)
        last_index = max(1, len(items) - 1)
        if positions is not None:
            if (
                not isinstance(positions, list)
                or len(positions) != len(items)
                or any(
                    not isinstance(position, (int, float))
                    or isinstance(position, bool)
                    or not math.isfinite(position)
                    or not 0 <= position <= 1
                    for position in positions
                )
            ):
                raise ValueError("가중치 그래프 자리 정보를 확인하세요.")
        result = []
        for index, item in enumerate(items):
            position = positions[index] if positions is not None else index / last_index
            target = interpolate_weight_profile(points, position)
            result.append(
                {key: value for key, value in item.items() if key != "_index"}
                | {"weight": round(target, 2)}
            )
        return result
    if mode == "random" or (mode == "custom" and not ranges):
        return [
            {key: value for key, value in item.items() if key != "_index"}
            | {"weight": random_weight(rng, minimum, maximum)}
            for item in items
        ]

    if mode == "balanced":
        tiers = build_balanced_tiers(len(items), minimum, maximum)
    else:
        tiers = validate_custom_ranges(ranges, len(items), minimum, maximum)

    if prefer_high_scores:
        ranked = sorted(
            items,
            key=lambda item: float(item.get("score") or 3) + rng.random() * 4,
            reverse=True,
        )
    else:
        ranked = rng.sample(items, len(items))
    assigned = assign_items_to_tiers(
        ranked,
        tiers,
        rng,
        high_first=mode == "balanced",
    )
    weights_by_index = {item["_index"]: item["weight"] for item in assigned}
    return [
        {key: value for key, value in item.items() if key != "_index"}
        | {"weight": weights_by_index[item["_index"]]}
        for item in items
    ]


def validate_weight_profile(profile, minimum, maximum):
    if not isinstance(profile, list) or len(profile) < 2:
        raise ValueError("가중치 그래프에는 두 개 이상의 점이 필요합니다.")
    points = []
    for item in profile:
        if not isinstance(item, dict):
            raise ValueError("가중치 그래프 점을 확인하세요.")
        try:
            position = float(item.get("position"))
            weight = float(item.get("weight"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("가중치 그래프 점을 확인하세요.") from exc
        if (
            not math.isfinite(position)
            or not math.isfinite(weight)
            or not 0 <= position <= 1
            or not minimum <= weight <= maximum
        ):
            raise ValueError("가중치 그래프 점을 확인하세요.")
        points.append({"position": position, "weight": weight})
    points.sort(key=lambda item: item["position"])
    if points[0]["position"] != 0 or points[-1]["position"] != 1:
        raise ValueError("가중치 그래프는 첫 자리와 마지막 자리를 포함해야 합니다.")
    if any(left["position"] >= right["position"] for left, right in zip(points, points[1:])):
        raise ValueError("가중치 그래프의 점 위치가 겹칩니다.")
    return points


def interpolate_weight_profile(points, position):
    for left, right in zip(points, points[1:]):
        if position <= right["position"]:
            ratio = (position - left["position"]) / (right["position"] - left["position"])
            return left["weight"] + (right["weight"] - left["weight"]) * ratio
    return points[-1]["weight"]


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
        raw_score = item.get("score")
        normalized_item = {"artist": artist, "weight": weight}
        if raw_score is not None:
            normalized_item["score"] = exact_score(
                raw_score,
                "Artist scores must be integers from 1 to 5.",
            )
        normalized.append(normalized_item)
        seen.add(artist)
    if not normalized:
        raise ValueError("At least one artist is required.")
    return normalized


def format_weight(value):
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def build_artist_prompt(artists):
    prompts = []
    for item in normalize_style_artists(artists):
        artist = item["artist"].replace("_", " ")
        if artist[-1:].isdigit():
            artist += " "
        prompts.append(f'{format_weight(item["weight"])}::artist:{artist}::')
    return normalize_numeric_prompt_closers(", ".join(prompts))


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
