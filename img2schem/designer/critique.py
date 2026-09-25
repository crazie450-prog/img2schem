"""Photo input and the critique pass (SOW RC.1): Claude sees the owner's photos in the brief, and after it
finishes it gets its build rendered next to the photo to find and fix the biggest differences."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from img2schem.models import BlockGrid, Palette
from img2schem.stages.preview import BG, render_front, render_iso

MAX_EDGE = 1568  # larger images are downscaled by the API anyway
PANEL_H = 520

CRITIQUE_PROMPT = (
    "Critique pass {n} of {total}. Left: the owner's photo. Right: your build as it stands (iso view from the "
    "north-west, and the front elevation seen from the north; flat preview colors, not textures). List the top "
    "discrepancies in massing, proportions, roof, openings and materials, ranked; first check that nothing is "
    "mirrored (the front view is drawn as the photo's viewer sees it: its left is east, larger x). Fix the ones "
    "that matter with "
    "ops (replace_op the op that makes a part rather than covering it), then call finish with an updated "
    "summary. If what remains is cosmetic, call finish right away."
)


def image_block(img: Image.Image, fmt: str = "PNG") -> dict[str, Any]:
    img = img.convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    media = "image/png" if fmt == "PNG" else "image/jpeg"
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def photo_brief(photos: list[Path], notes: str) -> list[dict[str, Any]]:
    """The design brief for a build from photos: the images, then what to do with them."""
    blocks = [image_block(Image.open(p)) for p in photos]
    many = len(photos) > 1
    text = (
        f"Recreate the building in {'these photos (the same building)' if many else 'this photo'} as a Minecraft "
        "build, 1 block = about 1 m. "
        + (f"The owner's notes: {notes}\n\n" if notes else "\n\n")
        + "First say what you see, briefly: footprint width and depth, storeys and heights, the main volumes and "
        "how they step or cantilever, the roof, the openings on the front, and the materials and colors per "
        "role. Then build it: massing and proportions first, then openings, then materials and detail (trims, "
        "frames, recesses). Put the side facing the camera at z = 0 (the front, facing north). Mind the "
        "handedness: the camera stands north of the front looking south, so the photo's LEFT is EAST (larger "
        "x) and its RIGHT is WEST (smaller x); a garage on the photo's left goes at the high-x end. Design "
        "plausible "
        "sides and back where the photo doesn't show them. Leave out plants, cars and people unless the notes "
        "ask for them; hardscape such as a driveway or terrace is fine. Check it with render_views, then call "
        "finish."
    )
    return [*blocks, {"type": "text", "text": text}]


def _label(img: Image.Image, text: str) -> Image.Image:
    font = ImageFont.load_default(size=18)
    width = max(img.width, int(font.getlength(text)) + 12)
    out = Image.new("RGB", (width, img.height + 28), BG)
    out.paste(img, ((width - img.width) // 2, 28))
    ImageDraw.Draw(out).text((6, 4), text, fill=(40, 40, 40), font=font)
    return out


def _fit(img: Image.Image, h: int, pixel_art: bool = False) -> Image.Image:
    img = img.convert("RGB")
    resample = Image.Resampling.NEAREST if pixel_art else Image.Resampling.LANCZOS
    return img.resize((max(1, round(img.width * h / img.height)), h), resample)


def critique_sheet(photo: Path, grid: BlockGrid, palette: Palette | None) -> Image.Image:
    """The photo, the build's iso view and its front elevation side by side, at one height."""
    iso, front = render_iso(grid, 8, palette), render_front(grid, 8, palette)
    panels = [_label(_fit(Image.open(photo), PANEL_H), "photo"),
              _label(_fit(iso, PANEL_H, True), "your build: iso (from the north-west)"),
              _label(_fit(front, PANEL_H, True), "your build: front (from the north; left = east, +x)")]  # fmt: skip
    sheet = Image.new("RGB", (sum(p.width for p in panels) + 16 * (len(panels) - 1), panels[0].height), BG)
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += p.width + 16
    return sheet


def critique_message(photo: Path, grid: BlockGrid, palette: Palette | None, n: int, total: int,
                     save_to: Path | None = None) -> list[dict[str, Any]]:  # fmt: skip
    sheet = critique_sheet(photo, grid, palette)
    if save_to:
        sheet.save(save_to)
    return [image_block(sheet), {"type": "text", "text": CRITIQUE_PROMPT.format(n=n, total=total)}]
