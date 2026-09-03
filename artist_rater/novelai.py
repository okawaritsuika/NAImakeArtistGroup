import json
import math
import random
import re
import secrets
import string
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
import urllib.error
import urllib.request

from png_validator import validate_png
from style_logic import normalize_numeric_prompt_closers
from model_definitions import (
    COMPLEXITY_VALUES,
    get_model_definition,
    normalize_model_id,
)

SUBSCRIPTION_URL = "https://image.novelai.net/user/subscription"
GENERATION_URL = "https://image.novelai.net/ai/generate-image"
REQUEST_TIMEOUT = 30
USER_AGENT = "Mozilla/5.0"
MAX_SUBSCRIPTION_BYTES = 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 100
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
MODEL = "nai-diffusion-4-5-full"
VARIETY_PLUS_SKIP_CFG = 59.04722600415217
MAX_PROMPT_LENGTH = 8192
MAX_CHARACTER_PROMPTS = 6
MAX_CHARACTER_PROMPT_LENGTH = 4096
MAX_ERROR_BODY_BYTES = 16 * 1024
SAFE_SAMPLER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_NOISE_SCHEDULES = {"native", "karras", "exponential", "polyexponential"}
COMPLEXITY_TAGS = {value: f"{value} complexity" for value in COMPLEXITY_VALUES}


class NovelAIError(Exception):
    def __init__(self, status_code, public_message):
        super().__init__(public_message)
        self.status = status_code
        self.status_code = status_code
        self.public_message = public_message


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_open(request, timeout):
    return urllib.request.build_opener(NoRedirectHandler()).open(
        request, timeout=timeout
    )


def _connection_error_message(exc):
    reason = getattr(exc, "reason", exc)
    if getattr(reason, "winerror", None) == 10013:
        return "Windows 네트워크 권한이 NovelAI 연결을 차단했습니다. (WinError 10013) 앱을 직접 실행하거나 방화벽 허용 상태를 확인하세요."
    return "Could not connect to the NovelAI server."


def _http_error_detail(exc, app_key):
    try:
        raw = exc.read(MAX_ERROR_BODY_BYTES + 1)[:MAX_ERROR_BODY_BYTES]
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    detail = next((parsed.get(key) for key in ("message", "error", "detail") if isinstance(parsed.get(key), str)), "")
    detail = re.sub(r"[\x00-\x1f\x7f]+", " ", detail).strip()[:500]
    if app_key:
        detail = detail.replace(app_key, "[redacted]")
    return detail


def combine_base_prompt(base_prompt, artist_prompt, leading_prompt=""):
    return ", ".join(
        part for part in (
            normalize_numeric_prompt_closers(leading_prompt).strip(),
            normalize_numeric_prompt_closers(artist_prompt).strip(),
            normalize_numeric_prompt_closers(base_prompt).strip(),
        ) if part
    )


def _required_int(data, key, minimum, maximum):
    value = data.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be an integer from {minimum} to {maximum}.")
    return value


def _finite_number(data, key, minimum, maximum):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number from {minimum} to {maximum}.")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be a number from {minimum} to {maximum}.")
    return value


def _prompt_string(data, key):
    value = data.get(key, "")
    if type(value) is not str:
        raise ValueError(f"{key} must be a string.")
    value = value.strip()
    if len(value) > MAX_PROMPT_LENGTH:
        raise ValueError(f"{key} is too long.")
    return value


def _normalize_complexity(data, definition):
    value = data.get("complexity", "")
    if value is None:
        value = ""
    if type(value) is not str:
        raise ValueError("complexity must be one of low, medium, high, or ultra.")
    value = value.strip().lower()
    if value in {"", "none", "off", "disabled"}:
        return ""
    if value not in COMPLEXITY_TAGS:
        raise ValueError("complexity must be one of low, medium, high, or ultra.")
    if not definition.supports_complexity:
        raise ValueError(f"complexity is only supported by {definition.generation} models.")
    return value


def normalize_generation_data(data):
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")

    model = normalize_model_id(data.get("model"), default=MODEL)
    definition = get_model_definition(model)
    width = _required_int(data, "width", 64, 2048)
    height = _required_int(data, "height", 64, 2048)
    if width % 64 or height % 64:
        raise ValueError("width and height must be multiples of 64.")

    character_prompts = data.get("character_prompts", [])
    if not isinstance(character_prompts, list):
        raise ValueError("character_prompts must be a list of strings.")
    normalized_characters = []
    for value in character_prompts:
        if type(value) is not str:
            raise ValueError("character_prompts must be a list of strings.")
        value = value.strip()
        if not value:
            raise ValueError("Character prompts must not be empty.")
        if len(value) > MAX_CHARACTER_PROMPT_LENGTH:
            raise ValueError("A character prompt is too long.")
        normalized_characters.append(value)
    if len(normalized_characters) > definition.max_character_prompts:
        raise ValueError(
            f"Too many character prompts for {definition.display_name} (maximum {definition.max_character_prompts})."
        )

    sampler = data.get("sampler")
    if type(sampler) is not str or not SAFE_SAMPLER.fullmatch(sampler.strip()):
        raise ValueError("sampler must be a nonempty safe token.")
    noise_schedule = data.get("noise_schedule", "native")
    if noise_schedule not in SAFE_NOISE_SCHEDULES:
        raise ValueError("noise_schedule is not supported.")

    if "seed" not in data:
        seed = random.SystemRandom().randint(1, 4294967295)
    else:
        seed = data["seed"]
    if type(seed) is not int or not 1 <= seed <= 4294967295:
        raise ValueError("seed must be an integer from 1 to 4294967295.")

    variety_plus = data.get("variety_plus", False)
    if type(variety_plus) is not bool:
        raise ValueError("variety_plus must be a boolean.")

    quality_toggle = data.get("quality_toggle", data.get("qualityToggle", False))
    if type(quality_toggle) is not bool:
        raise ValueError("quality_toggle must be a boolean.")
    uc_preset = data.get("uc_preset", data.get("ucPreset", 0))
    if type(uc_preset) is not int or not 0 <= uc_preset <= 4:
        raise ValueError("uc_preset must be an integer from 0 to 4.")
    complexity = _normalize_complexity(data, definition)

    excluded_quality_tags = data.get("excluded_quality_tags", [])
    if not isinstance(excluded_quality_tags, list) or any(type(value) is not str for value in excluded_quality_tags):
        raise ValueError("excluded_quality_tags must be a list of strings.")

    normalized = dict(data)
    normalized.update(
        {
            "base_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "base_prompt")),
            "leading_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "leading_prompt")),
            "quality_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "quality_prompt")),
            "original_quality_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "original_quality_prompt")),
            "fixed_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "fixed_prompt")),
            "excluded_quality_tags": [value.strip() for value in excluded_quality_tags if value.strip()],
            "negative_prompt": normalize_numeric_prompt_closers(_prompt_string(data, "negative_prompt")),
            "character_prompts": [normalize_numeric_prompt_closers(value) for value in normalized_characters],
            "width": width,
            "height": height,
            "steps": _required_int(data, "steps", 1, 50),
            "scale": _finite_number(data, "scale", 0, 10),
            "cfg_rescale": _finite_number(data, "cfg_rescale", 0, 1),
            "sampler": sampler.strip(),
            "noise_schedule": noise_schedule,
            "seed": seed,
            "variety_plus": variety_plus,
            "skip_cfg_above_sigma": VARIETY_PLUS_SKIP_CFG if variety_plus else None,
            "model": model,
            "quality_toggle": quality_toggle,
            "uc_preset": uc_preset,
            "complexity": complexity,
        }
    )
    return normalized


def combine_generation_prompt(data, artist_prompt):
    combined = combine_base_prompt(data["base_prompt"], artist_prompt, data.get("leading_prompt", ""))
    complexity_tag = COMPLEXITY_TAGS.get(data.get("complexity", ""), "")
    if complexity_tag:
        combined = ", ".join(part for part in (combined, complexity_tag) if part)
    return combined


def build_generation_payload(data, artist_prompt, seed=None, model=None):
    if model is None:
        model = data.get("model", MODEL) if isinstance(data, dict) else MODEL
    model = normalize_model_id(model, default=MODEL)
    source = dict(data)
    source["model"] = model
    normalized = normalize_generation_data(source)
    if seed is not None:
        if type(seed) is not int or not 1 <= seed <= 4294967295:
            raise ValueError("seed must be an integer from 1 to 4294967295.")
        normalized["seed"] = seed
    actual_seed = normalized["seed"]
    combined = combine_generation_prompt(normalized, artist_prompt)
    negative = normalized["negative_prompt"]
    char_captions = [
        {"char_caption": prompt, "centers": [{"x": 0.5, "y": 0.5}]}
        for prompt in normalized["character_prompts"]
    ]
    negative_char_captions = [
        {"char_caption": negative, "centers": entry["centers"]}
        for entry in char_captions
    ]
    payload = {
        "input": combined,
        "model": model,
        "action": "generate",
        "parameters": {
            "width": normalized["width"],
            "height": normalized["height"],
            "n_samples": 1,
            "seed": actual_seed,
            "extra_noise_seed": actual_seed,
            "sampler": normalized["sampler"],
            "steps": normalized["steps"],
            "scale": normalized["scale"],
            "negative_prompt": negative,
            "cfg_rescale": normalized["cfg_rescale"],
            "noise_schedule": normalized["noise_schedule"],
            "params_version": 3,
            "legacy": False,
            "legacy_v3_extend": False,
            "add_original_image": False,
            "ucPreset": normalized["uc_preset"],
            "qualityToggle": normalized["quality_toggle"],
            "prefer_brownian": True,
            "controlnet_strength": 1.0,
            "dynamic_thresholding": False,
            "sm": False,
            "sm_dyn": False,
            "deliberate_euler_ancestral_bug": False,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
            "v4_negative_prompt": {
                "caption": {"base_caption": negative, "char_captions": negative_char_captions},
                "use_coords": False,
                "use_order": False,
                "legacy_uc": False,
            },
            "v4_prompt": {
                "caption": {
                    "base_caption": combined,
                    "char_captions": char_captions,
                },
                "use_coords": False,
                "use_order": True,
                "legacy_uc": False,
            },
        },
    }
    if normalized["variety_plus"]:
        payload["parameters"]["skip_cfg_above_sigma"] = normalized["skip_cfg_above_sigma"]
    return payload


def _safe_png_info(archive):
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError("ZIP contains too many entries.")
    normalized_names = set()
    total_size = 0
    png_info = None
    for info in infos:
        normalized_name = info.filename.replace("\\", "/")
        path = PurePosixPath(normalized_name)
        canonical_name = path.as_posix().casefold()
        if canonical_name in normalized_names:
            raise ValueError("ZIP contains duplicate normalized names.")
        normalized_names.add(canonical_name)
        total_size += info.file_size
        if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP uncompressed contents are too large.")
        if info.file_size and (
            info.compress_size == 0
            or info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO
        ):
            raise ValueError("ZIP compression ratio is suspicious.")
        if path.is_absolute() or ".." in path.parts or info.is_dir():
            if path.suffix.lower() == ".png":
                raise ValueError("PNG path is unsafe.")
            continue
        if path.suffix.lower() == ".png":
            if info.file_size > MAX_IMAGE_BYTES:
                raise ValueError("PNG is too large.")
            if png_info is None:
                png_info = info
    if png_info is None:
        raise ValueError("ZIP does not contain a PNG image.")
    return png_info


def generate_novelai_png(app_key, data, artist_prompt, opener=None, model=None):
    source_data = dict(data)
    if model is not None:
        # Comparison generation passes its selected model separately.  Make it
        # part of validation before applying model-specific limits (notably
        # V5's 22 character prompts) and prompt handling.
        source_data["model"] = model
    normalized = normalize_generation_data(source_data)
    model = normalized["model"]
    payload = build_generation_payload(normalized, artist_prompt, normalized["seed"], model=model)
    request = urllib.request.Request(
        GENERATION_URL,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
    )
    request.add_unredirected_header("Authorization", f"Bearer {app_key}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    correlation_id = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(6))
    request.add_header("X-Correlation-Id", correlation_id)
    open_request = opener or _default_open
    try:
        with open_request(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_ZIP_BYTES + 1)
        if len(raw) > MAX_ZIP_BYTES:
            raise ValueError("Generation response is too large.")
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            info = _safe_png_info(archive)
            with archive.open(info) as image_file:
                png = image_file.read(MAX_IMAGE_BYTES + 1)
        if len(png) > MAX_IMAGE_BYTES:
            raise ValueError("Generation response did not contain a valid PNG.")
        png = validate_png(
            png,
            expected_width=normalized["width"],
            expected_height=normalized["height"],
        )
    except urllib.error.HTTPError as exc:
        try:
            if exc.code in (401, 403):
                raise NovelAIError(exc.code, "NovelAI App Key authentication failed.") from None
            detail = _http_error_detail(exc, app_key)
            suffix = f" · {detail}" if detail else ""
            correlation = f" · 요청 ID {correlation_id}" if exc.code == 500 else ""
            raise NovelAIError(502, f"NovelAI generation failed. (HTTP {exc.code}){suffix}{correlation}") from None
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NovelAIError(502, _connection_error_message(exc)) from None
    except (zipfile.BadZipFile, RuntimeError, ValueError, KeyError):
        raise NovelAIError(502, "Could not parse the NovelAI generation response.") from None
    return png, normalized["seed"]


def _subscription_total(data):
    if not isinstance(data, dict):
        raise ValueError("Response must be an object.")
    steps = data.get("trainingStepsLeft")
    if not isinstance(steps, dict):
        raise ValueError("trainingStepsLeft must be an object.")
    values = []
    for key in ("fixedTrainingStepsLeft", "purchasedTrainingSteps"):
        value = steps.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer.")
        values.append(value)
    return sum(values)


def _subscription_usage(data):
    usage = data.get("usage")
    if usage is None:
        return {}
    if not isinstance(usage, dict):
        raise ValueError("usage must be an object.")
    normalized = {}
    if "isNegative" in usage:
        if type(usage["isNegative"]) is not bool:
            raise ValueError("usage.isNegative must be a boolean.")
        normalized["isNegative"] = usage["isNegative"]
    if "percent" in usage:
        percent = usage["percent"]
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("usage.percent must be an integer from 0 to 100.")
        normalized["percent"] = percent
    if "timeUntilNextPercent" in usage:
        remaining = usage["timeUntilNextPercent"]
        if (
            isinstance(remaining, bool)
            or not isinstance(remaining, (int, float))
            or not math.isfinite(remaining)
            or remaining < 0
        ):
            raise ValueError("usage.timeUntilNextPercent must be a nonnegative number.")
        normalized["timeUntilNextPercent"] = remaining
    return normalized


def test_novelai_subscription(app_key, opener=None):
    request = urllib.request.Request(SUBSCRIPTION_URL, method="GET")
    request.add_unredirected_header("Authorization", f"Bearer {app_key}")
    request.add_header("User-Agent", USER_AGENT)
    open_request = opener or _default_open
    try:
        with open_request(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_SUBSCRIPTION_BYTES + 1)
        if len(raw) > MAX_SUBSCRIPTION_BYTES:
            raise ValueError("Subscription response is too large.")
        data = json.loads(raw.decode("utf-8"))
        anlas = _subscription_total(data)
        usage = _subscription_usage(data)
    except urllib.error.HTTPError as exc:
        try:
            if exc.code in (401, 403):
                raise NovelAIError(
                    exc.code, "NovelAI App Key authentication failed."
                ) from None
            raise NovelAIError(
                502, f"NovelAI request failed. (HTTP {exc.code})"
            ) from None
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NovelAIError(502, _connection_error_message(exc)) from None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        raise NovelAIError(502, "Could not parse the NovelAI response.") from None
    result = {"anlas": anlas}
    if usage:
        result["usage"] = usage
    return result
