"""Central NovelAI image-model definitions used by generation and storage flows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDefinition:
    model_id: str
    generation: str
    family: str
    display_name: str
    max_character_prompts: int
    supports_complexity: bool = False
    complexity_is_prompt_tag: bool = False

    @property
    def is_v5(self):
        return self.generation == "V5"

    @property
    def is_v45(self):
        return self.generation == "V4.5"


def _definition(
    model_id,
    generation,
    family,
    display_name,
    max_character_prompts,
    *,
    supports_complexity=False,
    complexity_is_prompt_tag=False,
):
    return ModelDefinition(
        model_id=model_id,
        generation=generation,
        family=family,
        display_name=display_name,
        max_character_prompts=max_character_prompts,
        supports_complexity=supports_complexity,
        complexity_is_prompt_tag=complexity_is_prompt_tag,
    )


# V5 uses the same structured v4_prompt/v4_negative_prompt wire objects as the
# currently documented V4.5 image endpoint.  The model ID remains the source of
# truth for generation-specific behavior; there is intentionally no guessed
# v5_prompt field here.
MODEL_DEFINITIONS = {
    "nai-diffusion-5-full": _definition(
        "nai-diffusion-5-full", "V5", "full", "NovelAI Diffusion V5 Full", 22,
        supports_complexity=True, complexity_is_prompt_tag=True,
    ),
    "nai-diffusion-5-curated": _definition(
        "nai-diffusion-5-curated", "V5", "curated", "NovelAI Diffusion V5 Curated", 22,
        supports_complexity=True, complexity_is_prompt_tag=True,
    ),
    "nai-diffusion-4-5-full": _definition(
        "nai-diffusion-4-5-full", "V4.5", "full", "NovelAI Diffusion V4.5 Full", 6,
    ),
    "nai-diffusion-4-5-curated": _definition(
        "nai-diffusion-4-5-curated", "V4.5", "curated", "NovelAI Diffusion V4.5 Curated", 6,
    ),
    # Keep model IDs already accepted by the application so old records and
    # comparison groups continue to work without changing their model.
    "nai-diffusion-4-full": _definition(
        "nai-diffusion-4-full", "V4", "full", "NovelAI Diffusion V4 Full", 6,
    ),
    "nai-diffusion-4-curated-preview": _definition(
        "nai-diffusion-4-curated-preview", "V4", "curated", "NovelAI Diffusion V4 Curated", 6,
    ),
    "nai-diffusion-3": _definition(
        "nai-diffusion-3", "V3", "anime", "NovelAI Diffusion V3", 6,
    ),
    "nai-diffusion-furry-3": _definition(
        "nai-diffusion-furry-3", "V3", "furry", "NovelAI Diffusion Furry V3", 6,
    ),
}

MODEL_ALIASES = {
    "NovelAI Diffusion V5 Full": "nai-diffusion-5-full",
    "NovelAI Diffusion V5 Curated": "nai-diffusion-5-curated",
    "V5 Full": "nai-diffusion-5-full",
    "V5 Curated": "nai-diffusion-5-curated",
    "NAID5F": "nai-diffusion-5-full",
    "NAID5C": "nai-diffusion-5-curated",
    "NovelAI Diffusion V4.5 Full": "nai-diffusion-4-5-full",
    "NovelAI Diffusion V4.5 Curated": "nai-diffusion-4-5-curated",
    "V4.5 Full": "nai-diffusion-4-5-full",
    "V4.5 Curated": "nai-diffusion-4-5-curated",
    "NAID4.5F": "nai-diffusion-4-5-full",
    "NAID4.5C": "nai-diffusion-4-5-curated",
    "NovelAI Diffusion V4 Full": "nai-diffusion-4-full",
    "NovelAI Diffusion V4 Curated": "nai-diffusion-4-curated-preview",
    "NovelAI Diffusion V3": "nai-diffusion-3",
}

COMPLEXITY_VALUES = ("low", "medium", "high", "ultra")
_MODEL_ALIASES_CASEFOLD = {key.casefold(): model_id for key, model_id in MODEL_ALIASES.items()}


def normalize_model_id(value, *, default=None):
    """Return a known model ID, or raise instead of silently falling back."""
    if value is None:
        if default is None:
            raise ValueError("model is required.")
        value = default
    if not isinstance(value, str):
        raise ValueError("model must be a supported NovelAI model ID.")
    text = value.strip()
    model_id = MODEL_ALIASES.get(text, _MODEL_ALIASES_CASEFOLD.get(text.casefold(), text))
    if model_id not in MODEL_DEFINITIONS:
        raise ValueError(f"Unsupported NovelAI model: {text or '(empty)'}.")
    return model_id


def get_model_definition(value, *, default=None):
    return MODEL_DEFINITIONS[normalize_model_id(value, default=default)]


def model_definitions_for_api():
    """Return serializable metadata without exposing any credential material."""
    return [
        {
            "id": definition.model_id,
            "generation": definition.generation,
            "family": definition.family,
            "display_name": definition.display_name,
            "is_v5": definition.is_v5,
            "is_v45": definition.is_v45,
            "max_character_prompts": definition.max_character_prompts,
            "supports_complexity": definition.supports_complexity,
            "complexity_is_prompt_tag": definition.complexity_is_prompt_tag,
        }
        for definition in MODEL_DEFINITIONS.values()
    ]
