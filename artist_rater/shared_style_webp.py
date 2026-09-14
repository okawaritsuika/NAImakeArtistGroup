"""Create distribution copies without changing source images or prompt metadata."""

import io
import json

from PIL import Image

from arca_style_collector import extract_novelai_metadata


def verified_webp(image_bytes, quality=90):
    """Return WebP with the full extracted metadata in EXIF, or fail closed.

    Lossy RGB compression must not be used as storage for stealth metadata.
    EXIF UserComment carries the complete generation JSON independently of it.
    """
    before = extract_novelai_metadata(image_bytes)
    if before["metadata_status"] != "ok":
        raise ValueError("NovelAI metadata is required for a distribution image.")
    raw = json.loads(before["raw_metadata_json"])
    exif = Image.Exif()
    exif[37510] = b"UNICODE\x00" + json.dumps(raw, ensure_ascii=False).encode("utf-16-be")
    output = io.BytesIO()
    with Image.open(io.BytesIO(image_bytes)) as image:
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Animated images are not supported.")
        pixels = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        options = {"icc_profile": image.info["icc_profile"]} if image.info.get("icc_profile") else {}
        pixels.save(output, "WEBP", quality=quality, method=6, exif=exif, **options)
        original_size = image.size
    encoded = output.getvalue()
    after = extract_novelai_metadata(encoded)
    for metadata in (before, after):
        metadata["raw_metadata_json"] = json.loads(metadata["raw_metadata_json"])
    if after != before:
        raise ValueError("WebP conversion changed generation metadata.")
    with Image.open(io.BytesIO(encoded)) as decoded:
        if decoded.size != original_size:
            raise ValueError("WebP conversion changed image dimensions.")
    return encoded
