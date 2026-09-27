"""Palette review sheet (Phase 1 DoD): for each block the owner names, its NEI icon, the color img2schem
measured, and its family (stairs, slab, wall, fence, gate) side by side, to check against the game."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from img2schem.models import PaletteVariant
from img2schem.palette.query import FAMILY_SHAPES, PaletteIndex
from img2schem.util.color import hex_color

BG, INK, FAINT = (246, 246, 244), (40, 40, 40), (150, 150, 150)


def _cell(img: Image.Image, x: int, y: int, k: int, title: str, v: PaletteVariant | None, block: str | None) -> None:
    """One cell at (x, y); ``k`` scales the 190 x 150 layout."""
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=12 * k)
    icon_px, pad = 64 * k, 6 * k

    def text(dx: int, dy: int, s: str, fill: tuple[int, int, int]) -> None:
        d.text((x + dx * k, y + dy * k), s, fill=fill, font=font)

    text(6, 4, title, FAINT)
    if v is None:
        text(6, 30, "none found", FAINT)
        return
    icon = Path(v.icon) if v.icon else None
    if icon and icon.is_file():
        big = Image.open(icon).convert("RGBA").resize((icon_px, icon_px), Image.Resampling.NEAREST)
        img.paste(big, (x + pad, y + 20 * k), big)
    else:
        d.rectangle([x + pad, y + 20 * k, x + pad + icon_px, y + 20 * k + icon_px], outline=FAINT)
        text(12, 44, "no icon", FAINT)
    color = v.face_rgb or v.rgb
    if color:  # the measured color, as wide as the icon
        x0 = x + pad + icon_px + pad
        d.rectangle([x0, y + 20 * k, x0 + icon_px, y + 20 * k + icon_px], fill=color, outline=FAINT)
    text(6, 90, (block or v.block)[:28], INK)
    text(6, 104, v.display[:28], INK)
    text(6, 118, hex_color(color) if color else "", FAINT)  # the swatch's color


def review_sheet(idx: PaletteIndex, blocks: list[str], scale: int = 2) -> Image.Image:
    """One row per block: the block, then each family member: the icon (left) and the measured color (right; the
    lit top face for cubes), the one img2schem matches photos against and draws previews with."""
    cell_w, row_h = 190 * scale, 150 * scale
    img = Image.new("RGB", ((1 + len(FAMILY_SHAPES)) * cell_w, len(blocks) * row_h), BG)
    for row, block in enumerate(blocks):
        y = row * row_h
        hit = idx.usable(block)
        _cell(img, 0, y, scale, f"block ({hit[0].shape})" if hit else "block", hit[1] if hit else None, block)
        for col, (shape, member) in enumerate(idx.family(block).items(), start=1):
            m = idx.usable(member) if member else None
            _cell(img, col * cell_w, y, scale, shape, m[1] if m else None, member)
        ImageDraw.Draw(img).line([0, y + row_h - 1, img.width, y + row_h - 1], fill=(220, 220, 216), width=scale)
    return img
