from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def make_rotation_variants(
    image_path: Path,
    output_dir: Path,
    stem: str,
    rotations: list[int] | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rotations = rotations or [0, 90, 180, 270]
    paths: list[Path] = []

    with Image.open(image_path) as original:
        base = ImageOps.grayscale(original)
        base = ImageOps.autocontrast(base)
        base = ImageEnhance.Contrast(base).enhance(1.6)
        base = ImageEnhance.Sharpness(base).enhance(1.4)
        base = base.filter(ImageFilter.SHARPEN)

        for rotation in rotations:
            img = base.rotate(rotation, expand=True)
            img.thumbnail((1800, 1800))
            out = output_dir / f"{stem}_rot{rotation}.jpg"
            img.convert("RGB").save(out, "JPEG", quality=78, optimize=True)
            paths.append(out)

    return paths
