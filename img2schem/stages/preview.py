"""S7 previews (R9.1, Phase 0 subset): orthographic front/side/top + isometric PNGs, PIL only.

Blocks are colored from the palette (NEI icon colors) when one is given, else with a flat hash color.
Views follow the in-game orientation (SOW §4.3):
  front: seen from the north (-Z) looking south, so east (+X) is on the image's LEFT;
  side:  seen from the west (-X) looking east, so south (+Z) is on the RIGHT;
  top:   seen from above with north up, east right;
  iso:   seen from the north-west, above (front and west faces visible).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from img2schem.models import BlockGrid, Palette

BG = (246, 246, 244)
SHADE = {"top": 1.0, "front": 0.85, "side": 0.7}


def block_color(block: str) -> tuple[int, int, int]:
    """Flat color per block name and metadata (``minecraft:wool@0`` and ``@14`` differ)."""
    d = hashlib.md5(block.encode()).digest()
    # Pull toward mid-gray so hash colors stay readable.
    return tuple(int(60 + b * 0.6) for b in d[:3])  # type: ignore[return-value]


def _palette_rgb(grid: BlockGrid, palette: Palette | None = None) -> np.ndarray:
    colors = [(palette.color(b) if palette else None) or block_color(b) for b in grid.palette[1:]]
    return np.array([BG, *colors], dtype=np.float32)


def _first_hit(idx: np.ndarray, axis: int) -> np.ndarray:
    """Palette index of the first non-air cell along ``axis`` (from index 0), 0 if none."""
    mask = idx != 0
    first = np.argmax(mask, axis=axis)
    hit = np.take_along_axis(idx, np.expand_dims(first, axis), axis=axis).squeeze(axis)
    return np.where(mask.any(axis=axis), hit, 0)


def _to_image(cells: np.ndarray, rgb: np.ndarray, shade: float, px: int) -> Image.Image:
    """``cells[row, col]`` palette indices -> image with px-sized blocks and faint grid lines."""
    img = rgb[cells].copy()
    solid = cells != 0
    img[solid] *= shade
    big = np.repeat(np.repeat(img, px, axis=0), px, axis=1)
    edge = np.zeros((px, px), dtype=bool)
    edge[-1, :] = edge[:, -1] = True
    edges = np.tile(edge, cells.shape) & np.repeat(np.repeat(solid, px, 0), px, 1)
    big[edges] *= 0.85
    return Image.fromarray(np.clip(big, 0, 255).astype(np.uint8))


def render_front(grid: BlockGrid, px: int = 8, palette: Palette | None = None) -> Image.Image:
    cells = _first_hit(grid.idx, axis=2)  # [X, Y]
    return _to_image(cells[::-1, ::-1].T, _palette_rgb(grid, palette), SHADE["front"], px)


def render_side(grid: BlockGrid, px: int = 8, palette: Palette | None = None) -> Image.Image:
    cells = _first_hit(grid.idx, axis=0)  # [Y, Z]
    return _to_image(cells[::-1, :], _palette_rgb(grid, palette), SHADE["side"], px)


def render_top(grid: BlockGrid, px: int = 8, palette: Palette | None = None) -> Image.Image:
    cells = _first_hit(grid.idx[:, ::-1, :], axis=1)  # [X, Z], scanning down from the top
    return _to_image(cells.T, _palette_rgb(grid, palette), SHADE["top"], px)


def render_iso(grid: BlockGrid, px: int = 8, palette: Palette | None = None) -> Image.Image:
    """Painter's algorithm over exposed faces. Screen u = (z - x), v = -(x + z)/2 - y (nearer = lower)."""
    idx = grid.idx
    xs, ys, zs = idx.shape
    rgb = _palette_rgb(grid, palette)
    s = px
    pad = np.pad(idx != 0, 1)
    solid = pad[1:-1, 1:-1, 1:-1]
    top = solid & ~pad[1:-1, 2:, 1:-1]
    north = solid & ~pad[1:-1, 1:-1, :-2]
    west = solid & ~pad[:-2, 1:-1, 1:-1]
    cells = np.argwhere(top | north | west)
    if len(cells) == 0:
        return Image.new("RGB", (4 * s, 4 * s), BG)
    order = np.argsort(-(cells[:, 0] + cells[:, 2] - cells[:, 1]), kind="stable")
    cells = cells[order]

    ox = xs * s + s
    oy = (xs + zs) * s / 2 + ys * s + s
    w = (xs + zs) * s + 2 * s
    h = int((xs + zs) * s / 2 + ys * s + 2 * s)
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)

    def pt(x: float, y: float, z: float) -> tuple[float, float]:
        return (ox + (z - x) * s, oy - (x + z) * s / 2 - y * s)

    for x, y, z in cells.tolist():
        base = rgb[idx[x, y, z]]
        faces = []
        if top[x, y, z]:
            faces.append(("top", [pt(x, y + 1, z), pt(x + 1, y + 1, z), pt(x + 1, y + 1, z + 1), pt(x, y + 1, z + 1)]))
        if north[x, y, z]:
            faces.append(("front", [pt(x, y, z), pt(x + 1, y, z), pt(x + 1, y + 1, z), pt(x, y + 1, z)]))
        if west[x, y, z]:
            faces.append(("side", [pt(x, y, z), pt(x, y, z + 1), pt(x, y + 1, z + 1), pt(x, y + 1, z)]))
        for kind, poly in faces:
            c = tuple(int(v) for v in base * SHADE[kind])
            edge = tuple(int(v * 0.8) for v in c)
            draw.polygon(poly, fill=c, outline=edge)
    return img


def write_previews(grid: BlockGrid, out_dir: Path, px: int = 8, palette: Palette | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, fn in (("front", render_front), ("side", render_side), ("top", render_top), ("iso", render_iso)):
        p = out_dir / f"preview_{name}.png"
        fn(grid, px, palette).save(p)
        paths.append(p)
    return paths
