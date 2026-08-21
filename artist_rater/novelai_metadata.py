"""Small, data-only helpers for NovelAI metadata compatibility.

The image parser intentionally keeps the original metadata in ``model`` and
``raw_metadata_json``.  The values returned here are a normalized index used
only for filtering and display; they are never used to rewrite the source
metadata.
"""

import re

from model_definitions import MODEL_DEFINITIONS


MODEL_IDS = (
    "nai-diffusion-5-full",
    "nai-diffusion-5-curated",
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
)
KNOWN_MODEL_IDS = tuple(MODEL_DEFINITIONS)
UNKNOWN_MODEL_ID = ""
UNKNOWN_MODEL_FAMILY = "unknown"
UNKNOWN_MODEL_VARIANT = "unknown"
COMPLEXITY_VALUES = ("low", "medium", "high", "ultra")


def _clean_model_text(value):
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def classify_model(value):
    """Classify a model value without looking at title, date, or prompt text.

    Exact NovelAI model ids are preferred.  Older exported images sometimes
    contain a source string such as ``NovelAI Diffusion V4.5 <hash>``.  That
    proves the generation family but does not prove Full versus Curated, so the
    variant is deliberately left ``unknown`` instead of guessed.
    """
    raw = _clean_model_text(value)
    folded = raw.casefold()
    result = {
        "model_id": UNKNOWN_MODEL_ID,
        "model_family": UNKNOWN_MODEL_FAMILY,
        "model_generation": UNKNOWN_MODEL_FAMILY,
        "model_variant": UNKNOWN_MODEL_VARIANT,
        "model_display_name": "Unknown",
    }
    if not raw:
        return result

    # Canonical ids may be embedded in a server response/source string, but
    # only an actual model value reaches this function.
    for model_id in KNOWN_MODEL_IDS:
        if re.search(r"(?<![a-z0-9])" + re.escape(model_id) + r"(?![a-z0-9])", folded):
            definition = MODEL_DEFINITIONS[model_id]
            generation = str(definition.generation or "").casefold()
            family = generation if generation in {"v5", "v4.5", "v4", "v3"} else "unknown"
            return {
                "model_id": model_id,
                "model_family": family,
                "model_generation": family,
                "model_variant": definition.family,
                "model_display_name": definition.display_name,
            }

    # Human-readable values used by NovelAI PNG/WebP exports.  Variant is only
    # assigned when it is explicitly present in that same model value.
    if re.search(r"(?<![0-9])(?:novelai\s+diffusion\s*)?v?4(?:[._-]5)(?:\b|[-_])", folded):
        family, generation = "v4.5", "v4.5"
    elif re.search(r"(?<![0-9._-])(?:novelai\s+diffusion\s*)?v?5(?:\b|[-_])", folded):
        family, generation = "v5", "v5"
    else:
        return result
    if re.search(r"(?:^|[\s._-])curated(?:$|[\s._-])", folded):
        variant = "curated"
    elif re.search(r"(?:^|[\s._-])full(?:$|[\s._-])", folded):
        variant = "full"
    else:
        variant = UNKNOWN_MODEL_VARIANT
    model_id = ""
    if variant != UNKNOWN_MODEL_VARIANT:
        model_id = "nai-diffusion-5-" + variant if family == "v5" else "nai-diffusion-4-5-" + variant
        display = MODEL_DEFINITIONS[model_id].display_name
    else:
        display = generation.upper() if generation == "v5" else "V4.5"
    return {
        "model_id": model_id,
        "model_family": family,
        "model_generation": generation,
        "model_variant": variant,
        "model_display_name": display,
    }


def model_filter_value(value):
    """Return a SQL-facing filter token or raise for an invalid token."""
    if value in (None, "", "all"):
        return "all"
    folded = _clean_model_text(value).casefold().replace("_", "-")
    if folded == "all":
        return "all"
    aliases = {
        "v5": "v5", "5": "v5", "v4.5": "v4.5", "v4-5": "v4.5", "4.5": "v4.5",
        "unknown": "unknown", "none": "unknown",
        "v5-full": "nai-diffusion-5-full", "v5-curated": "nai-diffusion-5-curated",
        "v4.5-full": "nai-diffusion-4-5-full", "v4.5-curated": "nai-diffusion-4-5-curated",
        "v4-5-full": "nai-diffusion-4-5-full", "v4-5-curated": "nai-diffusion-4-5-curated",
        "v5 full": "nai-diffusion-5-full", "v5 curated": "nai-diffusion-5-curated",
        "v4.5 full": "nai-diffusion-4-5-full", "v4.5 curated": "nai-diffusion-4-5-curated",
    }
    token = aliases.get(folded, folded)
    if token in KNOWN_MODEL_IDS:
        return token
    if token in {"v5", "v4.5", "unknown"}:
        return token
    raise ValueError("모델 필터 값이 올바르지 않습니다.")


def model_filter_sql(value, alias="image"):
    """Return ``(sql, args)`` for image-level model filtering."""
    token = model_filter_value(value)
    if token == "all":
        return "", []
    if token in {"v5", "v4.5", "unknown"}:
        return f"{alias}.model_family=?", [token]
    return f"{alias}.model_id=?", [token]


def _entry_prompt(entry):
    if isinstance(entry, str):
        return entry.strip(), []
    if not isinstance(entry, dict):
        return "", []
    for key in ("char_caption", "char_prompt", "prompt", "caption", "text", "content"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            centers = entry.get("centers")
            return value.strip(), centers if isinstance(centers, list) else []
    return "", []


def _character_values(value):
    if not isinstance(value, list):
        return []
    result = []
    for entry in value:
        prompt, centers = _entry_prompt(entry)
        if prompt:
            result.append({"prompt": prompt, "centers": centers})
    return result


def extract_character_prompts(values):
    """Extract known NovelAI character prompt containers without data loss.

    V4/V4.5 and current V5 exports use ``v4_prompt.caption.char_captions``
    (the name is retained for API compatibility).  A few imported legacy JSON
    records expose the same list under a generic character-prompt key; those
    are accepted without affecting model classification.  Duplicate entries
    are removed by prompt plus centers while retaining order.
    """
    found = []
    visited = set()

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                folded = str(key).casefold().replace("-", "_")
                if folded in {"char_captions", "character_prompts", "characterprompts", "characters_prompts"}:
                    found.extend(_character_values(child))
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    visit(child)

    visit(values)
    result = []
    for entry in found:
        key = (entry["prompt"], repr(entry.get("centers") or []))
        if key not in visited:
            visited.add(key)
            result.append(entry)
    return result


def extract_prompt_parts(values):
    """Return ``(base, negative, characters)`` from NovelAI metadata."""
    if not isinstance(values, dict):
        return "", "", []
    base_candidates = []
    negative_candidates = []

    def add_caption(container, destination):
        if not isinstance(container, dict):
            return
        caption = container.get("caption")
        if isinstance(caption, dict):
            for key in ("base_caption", "base_prompt", "prompt", "text"):
                if isinstance(caption.get(key), str) and caption[key].strip():
                    destination.append(caption[key])
        for key in ("base_caption", "base_prompt"):
            if isinstance(container.get(key), str) and container[key].strip():
                destination.append(container[key])

    for key, value in values.items():
        folded = str(key).casefold().replace("-", "_")
        if folded == "v4_prompt":
            add_caption(value, base_candidates)
        elif folded == "v4_negative_prompt":
            add_caption(value, negative_candidates)
    for key in ("prompt", "prompts", "base_prompt", "base_caption"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            base_candidates.append(value)
    for key in ("uc", "negative_prompt", "negativePrompt", "undesired_content"):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            negative_candidates.append(value)
    base = next((str(value).strip() for value in base_candidates if str(value).strip()), "")
    negative = next((str(value).strip() for value in negative_candidates if str(value).strip()), "")
    return base, negative, extract_character_prompts(values)


def model_fields(value):
    """Return normalized DB columns for a raw ``model`` value."""
    return classify_model(value)


def _split_prompt_tags(value):
    tags, current, stack = [], [], []
    pairs = {"{": "}", "[": "]", "(": ")"}
    for char in str(value or ""):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if char == "," and not stack:
            tags.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        tags.append("".join(current).strip())
    return tags


def extract_complexity(base_prompt, model_family):
    """Restore one explicit V5 complexity tag; reject absent/ambiguous tags."""
    if str(model_family or "").casefold() != "v5":
        return ""
    matches = [
        value for tag in _split_prompt_tags(base_prompt)
        for value in COMPLEXITY_VALUES
        if re.sub(r"\s+", " ", tag).strip().casefold() == f"{value} complexity"
    ]
    return matches[0] if len(matches) == 1 else ""
