"""S0 ingest (v1 R0.1-R0.3): normalize a photo into image.png + image_meta.json.

EXIF orientation applied, 8-bit RGB, long edge <= 2048 px (LANCZOS), SHA-256 of the original bytes (the cache
key for downstream calls), short edge < 400 px rejected. HEIC needs the optional pillow-heif package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_EDGE = 2048
MIN_SHORT_EDGE = 400


class IngestError(ValueError):
    pass


def ingest(photo: Path, run_dir: Path) -> Path:
    """Write ``run_dir/image.png`` and ``image_meta.json``; returns the image path."""
    data = photo.read_bytes()
    if photo.suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif  # type: ignore[import-not-found]

            pillow_heif.register_heif_opener()
        except ImportError:
            raise IngestError("HEIC photos need `pip install pillow-heif` (or convert the photo to JPEG)") from None
    try:
        raw = Image.open(photo)
        exif = raw.getexif()
        focal = exif.get_ifd(0x8769).get(0x920A) if exif else None  # FocalLength in the Exif sub-IFD
        im: Image.Image = ImageOps.exif_transpose(raw).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise IngestError(f"cannot read {photo}: {e}") from None
    original = im.size
    if min(original) < MIN_SHORT_EDGE:
        raise IngestError(f"{photo.name} is {original[0]}x{original[1]}; the short edge must be >= {MIN_SHORT_EDGE} px")
    factor = min(1.0, MAX_EDGE / max(original))
    if factor < 1.0:
        im = im.resize((round(original[0] * factor), round(original[1] * factor)), Image.Resampling.LANCZOS)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "image.png"
    im.save(out)
    meta = {
        "source": photo.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "original_size": list(original),
        "size": list(im.size),
        "resize_factor": round(factor, 6),
        "focal_length_mm": float(focal) if focal else None,
    }
    (run_dir / "image_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return out
