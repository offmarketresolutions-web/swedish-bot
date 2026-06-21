"""Server-side upload sanitization (V2 security S6). Re-encode every uploaded image
to strip EXIF/GPS metadata + neutralize polyglots, validate magic bytes + size, and
guard against decompression bombs. Returns a clean file or raises ValidationError.
"""
from __future__ import annotations

import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image

MAX_BYTES = 8 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard


def sanitize_image(uploaded):
    """Validate + re-encode to a metadata-free JPEG. Raises ValidationError if the
    upload is missing magic bytes / too big / not an allowed image."""
    if uploaded is None:
        return None
    if getattr(uploaded, "size", 0) > MAX_BYTES:
        raise ValidationError("Image too large (max 8 MB).")
    data = uploaded.read()
    try:
        Image.open(io.BytesIO(data)).verify()          # detect truncated/corrupt/polyglot
        img = Image.open(io.BytesIO(data))             # reopen after verify()
        fmt = img.format
        if fmt not in ALLOWED_FORMATS:
            raise ValidationError(f"Unsupported image format: {fmt}")
        img = img.convert("RGB")                        # drop alpha/palette + any modes
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Not a valid image.") from exc

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)            # no exif/icc passed -> stripped
    out.seek(0)
    return InMemoryUploadedFile(
        out, "image", "upload.jpg", "image/jpeg", out.getbuffer().nbytes, None
    )
