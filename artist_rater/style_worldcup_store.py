"""Saved style tournaments, using immutable participant snapshots."""

import json
import random
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from arca_style_collector import parse_weighted_prompt_tags
from novelai_metadata import classify_model, model_filter_sql, model_filter_value
from style_logic import normalize_artist_key


FILTER_KEYS = ("include_artists", "exclude_artists", "include_tags", "exclude_tags")


class WorldcupConflict(ValueError):
    """The client tried to choose from an obsolete tournament state."""


def _connect(db_path):
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def init_worldcup_tables(db_path):
    with closing(_connect(db_path)) as connection, connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS style_worldcups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                size INTEGER NOT NULL,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                filters_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS style_worldcup_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worldcup_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                base_prompt TEXT NOT NULL,
                recommendation_count INTEGER,
                image_path TEXT NOT NULL,
                image_source TEXT NOT NULL DEFAULT 'shared',
                UNIQUE(worldcup_id, ordinal),
                FOREIGN KEY(worldcup_id) REFERENCES style_worldcups(id) ON DELETE CASCADE
            );
        """)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(style_worldcup_participants)")}
        if "image_source" not in columns:
            connection.execute("ALTER TABLE style_worldcup_participants ADD COLUMN image_source TEXT NOT NULL DEFAULT 'shared'")


def _integer(value, label, maximum=2147483647):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        limit = f"0부터 {maximum} 사이의" if maximum is not None else "0 이상의"
        raise ValueError(f"{label}은(는) {limit} 정수여야 합니다.")
    return value


def _normalize_prompt_tag(value):
    return re.sub(r"^artists?\s*:\s*", "artist:", normalize_artist_key(value))


def _filter_values(value, artists=False):
    if isinstance(value, str):
        if len(value) > 12000:
            raise ValueError("필터 입력이 너무 깁니다.")
        value = re.split(r"[,\r\n]", value)
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("각 필터는 최대 50개의 문자열이어야 합니다.")
    result = []
    for entry in value:
        if not isinstance(entry, str) or len(entry) > 200:
            raise ValueError("필터 항목은 200자 이하의 문자열이어야 합니다.")
        normalized = _normalize_prompt_tag(entry)
        if artists:
            normalized = re.sub(r"^artists?\s*:\s*", "", normalized)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _filters(payload):
    if not isinstance(payload, dict):
        raise ValueError("월드컵 입력은 객체여야 합니다.")
    source = payload.get("filters", payload)
    if not isinstance(source, dict):
        raise ValueError("월드컵 필터는 객체여야 합니다.")
    sources = source.get("sources", payload.get("sources", ["shared"]))
    if not isinstance(sources, list) or not sources or any(
        not isinstance(entry, str) or entry not in {"shared", "confirmed"} for entry in sources
    ):
        raise ValueError("참가 출처는 shared 또는 confirmed를 담은 비어 있지 않은 배열이어야 합니다.")
    result = {
        key: _filter_values(source.get(key, []), artists=key.endswith("artists"))
        for key in FILTER_KEYS
    }
    result["sources"] = list(dict.fromkeys(sources))
    result["model"] = model_filter_value(source.get("model", "all"))
    threshold = source.get("exclude_recommendation_lte")
    if threshold is not None:
        threshold = _integer(threshold, "제외 추천수")
    result["exclude_recommendation_lte"] = threshold
    return result


def _local_image(image_root, value, *, root_is_resolved=False):
    """Return a served relative path only for a safe, existing local file."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        return ""
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts or ":" in value:
        return ""
    try:
        root = image_root if root_is_resolved else Path(image_root).resolve()
        target = (root / path).resolve()
        if root not in target.parents or not target.is_file():
            return ""
    except (OSError, ValueError, RuntimeError):
        return ""
    return path.as_posix()


def _source_root(image_source, image_root, confirmed_image_root):
    if image_source == "shared":
        return image_root
    if image_source != "confirmed":
        raise ValueError("알 수 없는 참가 이미지 출처입니다.")
    if confirmed_image_root is None:
        raise ValueError("확정 그림체 이미지 폴더가 지정되지 않았습니다.")
    return confirmed_image_root


def _shared_candidate_rows(connection, filters):
    clauses = ["image.metadata_status='ok'", "TRIM(COALESCE(image.image_path,''))<>''"]
    arguments = []
    threshold = filters["exclude_recommendation_lte"]
    if threshold is not None:
        clauses.append("item.recommendation_count IS NOT NULL AND item.recommendation_count>?")
        arguments.append(threshold)
    model_clause, model_arguments = model_filter_sql(filters["model"], "image")
    if model_clause:
        clauses.append(model_clause)
        arguments.extend(model_arguments)
    return connection.execute(
        "SELECT image.id AS candidate_id,item.id AS group_id,item.title,item.source_url,item.recommendation_count,image.image_path,"
        "COALESCE(NULLIF(image.model,''),image.model_id,'') AS model,"
        "COALESCE(NULLIF(image.base_prompt,''),image.prompt,'') AS base_prompt "
        "FROM arca_style_images image JOIN arca_style_items item ON item.id=image.item_id "
        "WHERE " + " AND ".join(clauses) + " ORDER BY image.id", arguments,
    )


def _candidate_rows(connection, image_root, filters, confirmed_image_root=None, *, candidate_keys=None):
    roots = {source: Path(_source_root(source, image_root, confirmed_image_root)).resolve() for source in filters["sources"]}
    selected = []
    needs_tags = any(filters[key] for key in FILTER_KEYS)
    tag_filters = {key: set(filters[key]) for key in FILTER_KEYS}
    for image_source, root in roots.items():
        represented_groups = set()
        if image_source == "shared":
            rows = _shared_candidate_rows(connection, filters)
        else:
            rows = connection.execute(
                "SELECT image.id AS candidate_id,style.id AS group_id,style.name AS title,style.source_url,NULL AS recommendation_count,image.image_path,"
                "style.artist_prompt,style.quality_prompt,style.fixed_prompt,style.model "
                "FROM confirmed_style_images image JOIN confirmed_styles style ON style.id=image.style_id "
                "WHERE TRIM(COALESCE(image.image_path,''))<>'' ORDER BY style.id,image.position,image.id"
            )
        for row in rows:
            key = f"{image_source}:{row['candidate_id']}"
            if candidate_keys is not None and key not in candidate_keys:
                continue
            if row["group_id"] in represented_groups:
                if candidate_keys is not None:
                    raise ValueError("같은 그림체를 중복 선택할 수 없습니다.")
                continue
            candidate = dict(row)
            candidate["image_source"] = image_source
            candidate.pop("candidate_id")
            candidate["key"] = key
            model = classify_model(candidate.pop("model"))
            candidate["model_label"] = model["model_display_name"].removeprefix("NovelAI Diffusion ")
            if image_source == "confirmed":
                model_filter = filters["model"]
                if model_filter != "all" and model_filter != model[
                    "model_family" if model_filter in {"v5", "v4.5", "unknown"} else "model_id"
                ]:
                    continue
                candidate["base_prompt"] = ", ".join(
                    value.strip() for key in ("artist_prompt", "quality_prompt", "fixed_prompt")
                    if (value := candidate.pop(key) or "").strip()
                )
            if needs_tags:
                tags = set()
                artists = set()
                for parsed in parse_weighted_prompt_tags(candidate["base_prompt"]):
                    tag = _normalize_prompt_tag(parsed["tag"])
                    tags.add(tag)
                    artist = re.fullmatch(r"artists?\s*:\s*(.+)", tag)
                    if artist:
                        artists.add(artist.group(1).strip())
                if not tag_filters["include_artists"].issubset(artists):
                    continue
                if not tag_filters["include_tags"].issubset(tags):
                    continue
                if tag_filters["exclude_artists"] & artists or tag_filters["exclude_tags"] & tags:
                    continue
            local_path = _local_image(root, row["image_path"], root_is_resolved=True)
            if not local_path:
                continue
            candidate["image_path"] = local_path
            represented_groups.add(candidate["group_id"])
            selected.append(candidate)
    return selected


def preview_candidates(db_path, image_root, payload, *, confirmed_image_root=None):
    filters = _filters(payload)
    with closing(_connect(db_path)) as connection:
        candidates = _candidate_rows(connection, image_root, filters, confirmed_image_root)
        return {"count": len(candidates), "counts": _candidate_counts(candidates)}


def _candidate_counts(candidates):
    counts = {"shared": 0, "confirmed": 0}
    for candidate in candidates:
        counts[candidate["image_source"]] += 1
    return counts


def _requested_size(value):
    if value == "all":
        return value
    value = _integer(value, "참가 인원", maximum=None)
    if value < 2 or value & (value - 1):
        raise ValueError("참가 인원은 2 이상의 2의 거듭제곱 또는 전부 참가를 선택하세요.")
    return value


def _sample_candidates(candidates, requested_size):
    size = len(candidates) if requested_size == "all" else requested_size
    if size < 2:
        raise ValueError("월드컵을 만들려면 조건에 맞는 이미지가 2장 이상 필요합니다.")
    if len(candidates) < size:
        raise ValueError(f"조건에 맞는 이미지가 {len(candidates)}장입니다. {size}강에 필요한 이미지가 부족합니다.")
    return random.SystemRandom().sample(candidates, size)


def _candidate_summary(candidate):
    image_source = candidate["image_source"]
    prefix = "arca-style-images" if image_source == "shared" else "confirmed-style-images"
    detail_prefix = "arca-styles" if image_source == "shared" else "confirmed-styles"
    return {
        "key": candidate["key"], "title": candidate["title"] or "",
        "group_key": f"{image_source}:{candidate['group_id']}",
        "detail_url": f"/api/{detail_prefix}/{candidate['group_id']}",
        "image_source": image_source, "recommendation_count": candidate["recommendation_count"],
        "model_label": candidate["model_label"],
        "image_url": f"/{prefix}/{quote(candidate['image_path'], safe='/')}", "available": True,
        "thumbnail_url": f"/style-manager-thumbnails/{image_source}/{quote(candidate['image_path'], safe='/')}",
    }


def list_candidates(db_path, image_root, payload, *, confirmed_image_root=None):
    filters = _filters(payload)
    sort = payload.get("sort", "default")
    if not isinstance(sort, str) or sort not in {"default", "recommendation_desc", "recommendation_asc"}:
        raise ValueError("후보 정렬 기준이 올바르지 않습니다.")
    page = _integer(payload.get("page", 1), "후보 페이지")
    per_page = _integer(payload.get("per_page", 24), "페이지당 후보 수", 60)
    if page < 1 or per_page < 1:
        raise ValueError("후보 페이지와 페이지당 후보 수는 1 이상이어야 합니다.")
    auto_size = _requested_size(payload["auto_size"]) if "auto_size" in payload else None
    with closing(_connect(db_path)) as connection:
        candidates = _candidate_rows(connection, image_root, filters, confirmed_image_root)
    if sort != "default":
        direction = -1 if sort == "recommendation_desc" else 1
        candidates.sort(key=lambda candidate: (
            candidate["recommendation_count"] is None,
            direction * (candidate["recommendation_count"] or 0),
            0 if candidate["image_source"] == "shared" else 1,
            candidate["group_id"],
        ))
    offset = (page - 1) * per_page
    result = {
        "count": len(candidates), "counts": _candidate_counts(candidates), "page": page, "per_page": per_page,
        "items": [_candidate_summary(candidate) for candidate in candidates[offset:offset + per_page]],
    }
    if auto_size is not None:
        result["selection"] = [_candidate_summary(candidate) for candidate in _sample_candidates(candidates, auto_size)]
    return result


def _validate_selected_keys(keys):
    if not isinstance(keys, list) or len(keys) < 2:
        raise ValueError("참가할 그림체를 2개 이상 선택하세요.")
    if any(not isinstance(key, str) or not re.fullmatch(r"(?:shared|confirmed):[1-9][0-9]*", key) for key in keys):
        raise ValueError("선택한 그림체 식별자를 확인하세요.")
    if len(set(keys)) != len(keys):
        raise ValueError("같은 그림체를 중복 선택할 수 없습니다.")


def _selected_candidates(candidates, keys):
    _validate_selected_keys(keys)
    by_key = {candidate["key"]: candidate for candidate in candidates}
    if any(key not in by_key for key in keys):
        raise ValueError("선택한 그림체가 없거나 현재 조건에 맞지 않습니다. 참가 후보를 다시 확인하세요.")
    return [by_key[key] for key in keys]


def _participant(row, image_root, confirmed_image_root=None):
    image_source = row["image_source"]
    path = _local_image(_source_root(image_source, image_root, confirmed_image_root), row["image_path"]) if image_source in {"shared", "confirmed"} else ""
    url_prefix = "arca-style-images" if image_source == "shared" else "confirmed-style-images"
    return {
        "ordinal": row["ordinal"], "title": row["title"],
        "source_url": row["source_url"], "base_prompt": row["base_prompt"],
        "recommendation_count": row["recommendation_count"],
        "image_source": image_source,
        "image_url": f"/{url_prefix}/{quote(path, safe='/')}" if path else "",
        "available": bool(path),
    }


def _detail(connection, image_root, cup, *, compact=False, confirmed_image_root=None):
    state = json.loads(cup["state_json"])
    result = {key: cup[key] for key in (
        "id", "name", "size", "status", "revision", "created_at", "updated_at"
    )}
    result["filters"] = json.loads(cup["filters_json"])
    result["current_match"] = None
    if cup["status"] == "playing":
        round_entries = state["round"]
        match_index = len(state["next_round"])
        result["current_match"] = {
            "left": round_entries[match_index * 2], "right": round_entries[match_index * 2 + 1],
            "round_size": state.get("round_size", len(round_entries)), "match_number": match_index + 1,
            "matches_in_round": len(round_entries) // 2,
        }
        if state.get("byes"):
            result["current_match"]["bye_count"] = len(state["byes"])
    result["history"] = state["history"]
    result["winner"] = state["winner"]
    participant_query = "SELECT * FROM style_worldcup_participants WHERE worldcup_id=?"
    participant_arguments = [cup["id"]]
    if compact:
        match = result["current_match"]
        ordinals = [match["left"], match["right"]] if match else [state["winner"]]
        participant_query += " AND ordinal IN (" + ",".join("?" for _ in ordinals) + ")"
        participant_arguments.extend(ordinals)
        result["participants_partial"] = True
    result["participants"] = [
        _participant(row, image_root, confirmed_image_root) for row in connection.execute(
            participant_query + " ORDER BY ordinal", participant_arguments,
        )
    ]
    return result


def create_worldcup(db_path, image_root, payload, *, confirmed_image_root=None):
    filters = _filters(payload)
    selection_scope = payload.get("selection_scope", "filtered")
    if not isinstance(selection_scope, str) or selection_scope not in {"filtered", "all"}:
        raise ValueError("참가 명단의 적용 범위가 올바르지 않습니다.")
    candidate_keys = None
    candidate_filters = filters
    if selection_scope == "all":
        _validate_selected_keys(payload.get("selected_candidates"))
        candidate_keys = set(payload["selected_candidates"])
        candidate_filters = _filters({"sources": filters["sources"]})
    requested_size = _requested_size(payload.get("size"))
    name = payload.get("name", "")
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError("월드컵 이름은 200자 이하의 문자열이어야 합니다.")
    name = name.strip() or "그림체 월드컵"
    with closing(_connect(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        candidates = _candidate_rows(connection, image_root, candidate_filters, confirmed_image_root, candidate_keys=candidate_keys)
        if "selected_candidates" in payload:
            candidates = _selected_candidates(candidates, payload["selected_candidates"])
            if requested_size != "all" and requested_size != len(candidates):
                raise ValueError("선택한 그림체 수와 참가 인원이 일치해야 합니다.")
        participants = _sample_candidates(candidates, requested_size)
        size = len(participants)
        state = {"round": list(range(size)), "next_round": [], "history": [], "winner": None}
        if size & (size - 1):
            next_round_size = 1 << (size.bit_length() - 1)
            paired_count = 2 * (size - next_round_size)
            state["round"] = list(range(paired_count))
            state["byes"] = list(range(paired_count, size))
            state["round_size"] = next_round_size * 2
        timestamp = _now()
        cup_id = connection.execute(
            "INSERT INTO style_worldcups(uuid,name,size,status,filters_json,state_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), name, size, "playing", json.dumps(
                {**filters, "selection_scope": "all"} if selection_scope == "all" else filters, ensure_ascii=False),
             json.dumps(state), timestamp, timestamp),
        ).lastrowid
        connection.executemany(
            "INSERT INTO style_worldcup_participants(worldcup_id,ordinal,title,source_url,base_prompt,recommendation_count,image_path,image_source) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [(cup_id, ordinal, row["title"] or "", row["source_url"] or "", row["base_prompt"],
              row["recommendation_count"], row["image_path"], row["image_source"]) for ordinal, row in enumerate(participants)],
        )
        cup = connection.execute("SELECT * FROM style_worldcups WHERE id=?", (cup_id,)).fetchone()
        return _detail(connection, image_root, cup, confirmed_image_root=confirmed_image_root)


def get_worldcup(db_path, image_root, worldcup_id, *, confirmed_image_root=None):
    with closing(_connect(db_path)) as connection:
        cup = connection.execute("SELECT * FROM style_worldcups WHERE id=?", (worldcup_id,)).fetchone()
        return _detail(connection, image_root, cup, confirmed_image_root=confirmed_image_root) if cup else None


def list_worldcups(db_path, image_root, *, confirmed_image_root=None):
    with closing(_connect(db_path)) as connection:
        result = []
        for cup in connection.execute("SELECT * FROM style_worldcups ORDER BY created_at DESC,id DESC"):
            summary = {key: cup[key] for key in (
                "id", "name", "size", "status", "revision", "created_at", "updated_at"
            )}
            winner = json.loads(cup["state_json"])["winner"]
            preview = [
                _participant(row, image_root, confirmed_image_root) for row in connection.execute(
                    "SELECT * FROM style_worldcup_participants WHERE worldcup_id=? "
                    "ORDER BY CASE WHEN ordinal=? THEN 0 ELSE 1 END,ordinal LIMIT 4",
                    (cup["id"], winner),
                )
            ]
            summary["preview_participants"] = preview
            summary["winner"] = next(
                (participant for participant in preview if participant["ordinal"] == winner), None
            )
            result.append(summary)
        return result


def choose_winner(db_path, image_root, worldcup_id, payload, *, confirmed_image_root=None):
    if not isinstance(payload, dict):
        raise ValueError("선택 입력은 객체여야 합니다.")
    revision = _integer(payload.get("revision"), "진행 버전")
    winner = _integer(payload.get("winner"), "선택 참가자", maximum=None)
    with closing(_connect(db_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        cup = connection.execute("SELECT * FROM style_worldcups WHERE id=?", (worldcup_id,)).fetchone()
        if cup is None:
            raise LookupError("월드컵을 찾을 수 없습니다.")
        if cup["revision"] != revision or cup["status"] != "playing":
            raise WorldcupConflict("이미 저장된 선택입니다. 최신 진행 상태를 불러와 주세요.")
        state = json.loads(cup["state_json"])
        round_entries = state["round"]
        byes = state.get("byes", [])
        round_size = state.get("round_size", len(round_entries))
        position = len(state["next_round"]) * 2
        left, right = round_entries[position:position + 2]
        if winner not in (left, right):
            raise ValueError("현재 대결의 참가자 중에서 선택하세요.")
        state["history"].append({"round_size": round_size, "left": left, "right": right, "winner": winner})
        state["next_round"].append(winner)
        status = "playing"
        if len(round_entries) == 2 and not byes:
            state["winner"] = winner
            status = "completed"
        elif len(state["next_round"]) == len(round_entries) // 2:
            state["round"] = state["next_round"] + byes
            state["next_round"] = []
            state["byes"] = []
            state["round_size"] = len(state["round"])
        connection.execute(
            "UPDATE style_worldcups SET state_json=?,status=?,revision=revision+1,updated_at=? WHERE id=?",
            (json.dumps(state), status, _now(), worldcup_id),
        )
        updated = connection.execute("SELECT * FROM style_worldcups WHERE id=?", (worldcup_id,)).fetchone()
        return _detail(
            connection, image_root, updated, compact=payload.get("compact") is True,
            confirmed_image_root=confirmed_image_root,
        )
