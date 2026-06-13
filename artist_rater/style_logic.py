import hashlib
import json
import math
import random


SCORE_SELECTION_WEIGHT = {1: 0.08, 2: 0.2, 3: 0.55, 4: 1.0, 5: 1.6}


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


def random_weight(rng, low, high):
    low = float(low)
    high = float(high)
    epsilon = 1e-9
    minimum_cent = max(1, math.ceil(low * 100 - epsilon))
    maximum_cent = math.floor(high * 100 + epsilon)
    if minimum_cent > maximum_cent:
        raise ValueError("범위 안에 유효한 양수 센트 가중치가 없습니다.")
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
    if mode not in {"random", "balanced", "custom"}:
        raise ValueError("가중치 모드를 확인하세요.")

    rng = random.Random(rng_seed)
    items = []
    for index, item in enumerate(artists or []):
        normalized = dict(item)
        normalized["score"] = exact_score(item.get("score"))
        normalized["_index"] = index
        items.append(normalized)
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
            key=lambda item: float(item.get("score") or 0) + rng.random() * 4,
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
