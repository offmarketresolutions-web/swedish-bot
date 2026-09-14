"""Generate the photo fixtures the vision path is tested against.

Every existing photo test sends b"\\xff\\xd8\\xff\\xe0fakejpeg" with a mocked vision
response, so the real OCR path has never seen an actual image. These are generated rather
than downloaded on purpose: scraped photos cannot be committed (licensing), are not
reproducible in CI, and a clean stock photo is an EASIER test than the cases that actually
break OCR. So this makes the hard ones deliberately — blur, glare, rotation, and a photo of
the wrong thing entirely.

    uv run python tools/make_test_photos.py

Writes to tests/fixtures/photos/. Deterministic: same bytes every run.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "photos"


def _font(size: int):
    for candidate in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def nameplate(brand: str, model: str, serial: str) -> Image.Image:
    """A rating plate as it looks on the side of an indoor unit: dark label, light text."""
    img = Image.new("RGB", (900, 560), (38, 42, 48))
    d = ImageDraw.Draw(img)
    d.rectangle([26, 26, 874, 534], outline=(150, 156, 164), width=3)
    d.text((60, 70), brand, font=_font(96), fill=(236, 240, 245))
    d.text((60, 200), f"Model: {model}", font=_font(54), fill=(226, 232, 240))
    d.text((60, 280), f"Serial No: {serial}", font=_font(44), fill=(210, 218, 228))
    d.text((60, 350), "230V ~ 50Hz   IP24", font=_font(38), fill=(186, 196, 208))
    d.text((60, 410), "Nordland VVS - auktoriserad", font=_font(32), fill=(160, 172, 186))
    return img


def display(code: str) -> Image.Image:
    """A control panel showing an alarm code — bright segments on a dark screen."""
    img = Image.new("RGB", (760, 460), (18, 20, 24))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([50, 50, 710, 410], radius=18, outline=(90, 96, 104), width=4)
    d.text((150, 120), "ALARM", font=_font(58), fill=(250, 196, 70))
    d.text((250, 210), code, font=_font(150), fill=(255, 92, 72))
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []

    plate = nameplate("IVT", "AirX 500", "4711-88231")
    plate.save(OUT / "nameplate_ivt_airx500.jpg", quality=92)
    written.append("nameplate_ivt_airx500.jpg  — clean rating plate, the easy case")

    # Handheld at arm's length in a dim plant room: the single most common real upload.
    plate.rotate(-7, expand=True, fillcolor=(24, 26, 30)).filter(
        ImageFilter.GaussianBlur(2.2)).save(OUT / "nameplate_blurry.jpg", quality=70)
    written.append("nameplate_blurry.jpg       — same plate, rotated + blurred + low quality")

    display("E4").save(OUT / "display_e4.jpg", quality=92)
    written.append("display_e4.jpg             — alarm code on the control panel")

    # Nothing identifiable. The bot must NOT invent a brand or model from this.
    wrong = Image.new("RGB", (700, 520), (120, 140, 110))
    dw = ImageDraw.Draw(wrong)
    dw.ellipse([180, 150, 520, 400], fill=(86, 104, 80))
    dw.text((210, 60), "en katt, inte en varmepump", font=_font(30), fill=(240, 240, 235))
    wrong.save(OUT / "not_equipment.jpg", quality=88)
    written.append("not_equipment.jpg          — the wrong subject entirely")

    for line in written:
        print("  " + line)
    print(f"\n{len(written)} fixtures -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
