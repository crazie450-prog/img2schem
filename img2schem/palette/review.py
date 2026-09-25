"""Palette review sheet (Phase 1 DoD): for each block the owner names, its NEI icon, the color img2schem
measured, and its family (stairs, slab, wall, fence, gate) side by side, to check against the game."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from img2schem.models import PaletteVariant
from img2schem.palette.query import FAMILY_SHAPES, PaletteIndex

CELL_W, ICON, SWATCH, ROW_H = 150, 64, 20, 150
BG, INK, FAINT = (246, 246, 244), (40, 40, 40), (150, 150, 150)
FONT = ImageFont.load_default(size=12)


def _cell(img: Image.Image, x: int, y: int, title: str, v: PaletteVariant | None, block: str | None) -> None:
    d = ImageDraw.Draw(img)
    d.text((x + 6, y + 4), title, fill=FAINT, font=FONT)
    if v is None:
        d.text((x + 6, y + 30), "none found", fill=FAINT, font=FONT)
        return
    icon = Path(v.icon) if v.icon else None
    if icon and icon.is_file():
        big = Image.open(icon).convert("RGBA").resize((ICON, ICON), Image.Resampling.NEAREST)
        img.paste(big, (x + 6, y + 20), big)
    else:
        d.rectangle([x + 6, y + 20, x + 6 + ICON, y + 20 + ICON], outline=FAINT)
        d.text((x + 12, y + 44), "no icon", fill=FAINT, font=FONT)
    color = v.face_rgb or v.rgb
    if color:
        d.rectangle([x + 6 + ICON + 6, y + 20, x + 6 + ICON + 6 + SWATCH, y + 20 + ICON], fill=color, outline=FAINT)
    d.text((x + 6, y + 90), (block or v.block)[:22], fill=INK, font=FONT)
    d.text((x + 6, y + 104), v.display[:22], fill=INK, font=FONT)
    d.text((x + 6, y + 118), v.hex or "", fill=FAINT, font=FONT)


def review_sheet(idx: PaletteIndex, blocks: list[str]) -> Image.Image:
    """One row per block: the block, then each family member. The swatch is the measured color (the lit top
    face for cubes), the one img2schem matches photos against and draws previews with."""
    cols = 1 + len(FAMILY_SHAPES)
    img = Image.new("RGB", (cols * CELL_W, len(blocks) * ROW_H), BG)
    for row, block in enumerate(blocks):
        y = row * ROW_H
        hit = idx.usable(block)
        _cell(img, 0, y, f"block ({hit[0].shape})" if hit else "block", hit[1] if hit else None, block)
        for col, (shape, member) in enumerate(idx.family(block).items(), start=1):
            m = idx.usable(member) if member else None
            _cell(img, col * CELL_W, y, shape, m[1] if m else None, member)
        ImageDraw.Draw(img).line([0, y + ROW_H - 1, img.width, y + ROW_H - 1], fill=(220, 220, 216))
    return img
