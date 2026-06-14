import json
import math
import random
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
import urllib.error
import urllib.request

from png_validator import validate_png

SUBSCRIPTION_URL = "https://api.novelai.net/user/subscription"
GENERATION_URL = "https://image.novelai.net/ai/generate-image"
REQUEST_TIMEOUT = 12
USER_AGENT = "DanbooruArtistRater/1.0 (local personal tool)"
MAX_SUBSCRIPTION_BYTES = 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 100
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
MODEL = "nai-diffusion-4-5-full"
MAX_PROMPT_LENGTH = 8192
MAX_CHARACTER_PROMPTS = 16
MAX_CHARACTER_PROMPT_LENGTH = 4096
SAFE_SAMPLER = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


def combine_base_prompt(base_prompt, artist_prompt):
    return ", ".join(
        part for part in (base_prompt.strip(), artist_prompt.strip()) if part
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


def normalize_generation_data(data):
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")

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
    if len(normalized_characters) > MAX_CHARACTER_PROMPTS:
        raise ValueError("Too many character prompts.")

    sampler = data.get("sampler")
    if type(sampler) is not str or not SAFE_SAMPLER.fullmatch(sampler.strip()):
        raise ValueError("sampler must be a nonempty safe token.")

    if "seed" not in data:
        seed = random.SystemRandom().randint(1, 4294967295)
    else:
        seed = data["seed"]
    if type(seed) is not int or not 1 <= seed <= 4294967295:
        raise ValueError("seed must be an integer from 1 to 4294967295.")

    normalized = dict(data)
    normalized.update(
        {
            "base_prompt": _prompt_string(data, "base_prompt"),
            "negative_prompt": _prompt_string(data, "negative_prompt"),
            "character_prompts": normalized_characters,
            "width": width,
            "height": height,
            "steps": _required_int(data, "steps", 1, 50),
            "scale": _finite_number(data, "scale", 0, 10),
            "cfg_rescale": _finite_number(data, "cfg_rescale", 0, 1),
            "sampler": sampler.strip(),
            "seed": seed,
        }
    )
    return normalized


def build_generation_payload(data, artist_prompt, seed=None):
    normalized = normalize_generation_data(data)
    if seed is not None:
        if type(seed) is not int or not 1 <= seed <= 4294967295:
            raise ValueError("seed must be an integer from 1 to 4294967295.")
        normalized["seed"] = seed
    actual_seed = normalized["seed"]
    combined = combine_base_prompt(normalized["base_prompt"], artist_prompt)
    negative = normalized["negative_prompt"]
    char_captions = [
        {"char_caption": prompt, "centers": [{"x": 0.5, "y": 0.5}]}
        for prompt in normalized["character_prompts"]
    ]
    return {
        "input": combined,
        "model": MODEL,
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
            "noise_schedule": "native",
            "params_version": 3,
            "legacy": False,
            "legacy_v3_extend": False,
            "add_original_image": True,
            "prefer_brownian": True,
            "use_coords": False,
            "v4_negative_prompt": {
                "caption": {"base_caption": negative, "char_captions": []},
                "legacy_uc": False,
            },
            "v4_prompt": {
                "caption": {
                    "base_caption": combined,
                    "char_captions": char_captions,
                },
                "use_coords": False,
                "use_order": True,
            },
        },
    }


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


def generate_novelai_png(app_key, data, artist_prompt, opener=None):
    normalized = normalize_generation_data(data)
    payload = build_generation_payload(normalized, artist_prompt, normalized["seed"])
    request = urllib.request.Request(
        GENERATION_URL,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        method="POST",
    )
    request.add_unredirected_header("Authorization", f"Bearer {app_key}")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
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
            raise NovelAIError(502, f"NovelAI generation failed. (HTTP {exc.code})") from None
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NovelAIError(502, "Could not connect to the NovelAI server.") from None
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
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NovelAIError(502, "Could not connect to the NovelAI server.") from None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        raise NovelAIError(502, "Could not parse the NovelAI response.") from None
    return {"anlas": anlas}
