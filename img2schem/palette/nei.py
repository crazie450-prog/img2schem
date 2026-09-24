"""Build the palette from NEI data dumps (SOW_GTNH Q1, D-016).

Inputs, from NEI's Tools -> Data Dumps in the owner's GTNH instance (``.minecraft/dumps``):
- ``block.csv``: ``Name,ID,Has Item,Mod,Class,Display Name`` for every registered block;
- ``itempanel.csv``: ``Item Name,Item ID,Item meta,Has NBT,Display Name`` for every item-panel stack; for a
  block's item, ``Item meta`` is the block metadata of that variant;
- ``itempanel_icons/``: one 16x16 PNG per stack, named by display name (``\\/:*?"<>|`` -> ``_``; other
  characters, including non-ASCII, kept) with ``_2``, ``_3``... for repeats in item-panel order.

An icon is linked to a row only when its display name has exactly as many icons as rows (then the Nth row
gets the Nth icon); otherwise the variant has no color. Shapes come from the block's Java class and name, then
from the icon outline (plain cubes). Variants matching palette/data/exclude.yaml are flagged "excluded"; infested
variants are flagged "infested" when the same name without "Infested" exists (owner rule, D-018).
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter, defaultdict
from importlib import resources
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from img2schem.models import Palette, PaletteBlock, PaletteVariant, Shape
from img2schem.util.block import format_block
from img2schem.util.color import hex_color, icon_color, srgb_to_lab

IMPORTER_VERSION = "3"
# Icons darker than this (CIELAB L*) are flagged: NEI renders some mods' blocks (e.g. Botania metamorphic
# stone) nearly black, but real black blocks (obsidian, black wool) look the same, so they are only flagged.
DARK_ICON_L = 12.0

# (shape, include, exclude): first match wins; tested against "<class simple name> <registry name>", lower case.
_SHAPE_RULES: list[tuple[Shape, str, str | None]] = [
    ("trapdoor", r"trap_?door", None),
    ("door", r"door", None),
    ("fence_gate", r"fence_?gate", None),
    ("fence", r"fence", None),
    ("pane", r"pane\b|_pane|glasspane|iron_bars", r"panel"),
    ("wall", r"wall", r"^marking|wallpaper|sign|banner|torch|lamp|lantern|plate"),
    ("stairs", r"stair", None),
    ("slab", r"slab|halfstep|\bblockstep\b", None),
    ("log", r"\blog\d?\b|_log\b|log_|blocklog|strippedlog", None),
]
# Classes known to be plain full cubes (curated; extend as blocks are verified).
FULL_CUBE_CLASSES = {
    "Block", "BlockStone", "BlockCarvable", "BlockColored", "BlockCompressed", "BlockStoneBrick", "BlockSandStone",
    "BlockWood", "BlockQuartz", "BlockHardenedClay", "BlockClay", "BlockObsidian", "BlockNetherrack",
}  # fmt: skip


# 16x16 alpha outline of NEI's isometric full-cube icon (identical for every plain cube, e.g. minecraft:stone).
_CUBE_OUTLINE = np.array(
    [[c == "#" for c in row] for row in (
        ".......##.......", ".....######.....", "...##########...", *([".##############."] * 10),
        "...##########...", ".....######.....", ".......##.......",
    )]
)  # fmt: skip
CUBE_IOU = 0.95  # stairs icons score ~0.92, slabs ~0.64 (measured on the owner's dump)


def cube_outline_iou(icon: Path) -> float:
    mask = np.asarray(Image.open(icon).convert("RGBA"))[..., 3] >= 128
    if mask.shape != _CUBE_OUTLINE.shape:
        return 0.0
    return float((mask & _CUBE_OUTLINE).sum() / max((mask | _CUBE_OUTLINE).sum(), 1))


def exclude_patterns() -> re.Pattern[str]:
    text = resources.files("img2schem.palette").joinpath("data/exclude.yaml").read_text(encoding="utf-8")
    return re.compile("|".join(f"(?:{p})" for p in yaml.safe_load(text)["patterns"]), re.IGNORECASE)


def shape_overrides() -> dict[str, Shape]:
    text = resources.files("img2schem.palette").joinpath("data/shape_overrides.yaml").read_text(encoding="utf-8")
    return dict(yaml.safe_load(text) or {})


def classify(block_class: str, name: str) -> Shape:
    """Shape from the class simple name and the registry path (the mod id is left out: ``malisisdoors``)."""
    simple = block_class.rsplit(".", 1)[-1]
    key = f"{simple} {name.split(':', 1)[-1]}".lower()
    for shape, include, exclude in _SHAPE_RULES:
        if re.search(include, key) and not (exclude and re.search(exclude, key)):
            if shape == "slab" and "double" in key:
                return "full_cube"
            return shape
    return "full_cube" if simple in FULL_CUBE_CLASSES else "unknown"


def icon_filename_base(display: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", display)


def dumps_key(dumps: Path) -> str:
    h = hashlib.sha256(f"nei-importer={IMPORTER_VERSION}\n".encode())
    for f in ("block.csv", "itempanel.csv"):
        h.update((dumps / f).read_bytes())
    icons = dumps / "itempanel_icons"
    h.update(str(sorted(p.name for p in icons.iterdir()) if icons.is_dir() else []).encode())
    return h.hexdigest()[:16]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def import_nei(dumps: Path) -> Palette:
    """Raises FileNotFoundError / KeyError if the dump files are missing or malformed."""
    blocks_csv = _read_csv(dumps / "block.csv")
    items_csv = _read_csv(dumps / "itempanel.csv")
    icons_dir = dumps / "itempanel_icons"

    pal = Palette(source=str(dumps), key=dumps_key(dumps))
    overrides = shape_overrides()
    excluded = exclude_patterns()
    for r in blocks_csv:
        name = r["Name"]
        if name == "minecraft:air":
            continue
        pal.blocks[name] = PaletteBlock(
            name=name,
            mod=name.split(":", 1)[0],
            block_class=r["Class"],
            display=None if r["Display Name"] == "null" else r["Display Name"],
            shape=overrides.get(name) or classify(r["Class"], name),
        )

    # Icon files per display-name base, in item-panel order: base.png, base_2.png, ...
    icon_count: Counter[str] = Counter()
    if icons_dir.is_dir():
        for p in icons_dir.iterdir():
            m = re.match(r"^(.*?)(?:_(\d+))?\.png$", p.name)
            if m:
                icon_count[m.group(1)] += 1
    row_count = Counter(icon_filename_base(r["Display Name"]) for r in items_csv)
    seen: defaultdict[str, int] = defaultdict(int)
    for r in items_csv:
        base = icon_filename_base(r["Display Name"])
        seen[base] += 1
        blk = pal.blocks.get(r["Item Name"])
        if blk is None or r["Has NBT"] == "true":
            continue  # not a block, or an NBT variant (not placeable from the palette)
        meta = int(r["Item meta"])
        if not 0 <= meta <= 15:
            continue  # damage values beyond 4 bits are not block metadata
        v = PaletteVariant(block=format_block(blk.name, meta), meta=meta, display=r["Display Name"])
        if icon_count[base] == row_count[base]:
            n = seen[base]
            icon = icons_dir / (f"{base}.png" if n == 1 else f"{base}_{n}.png")
            if icon.is_file():
                rgb, alpha = icon_color(icon)
                v.rgb, v.hex, v.alpha = rgb, hex_color(rgb), round(alpha, 3)
                lab = srgb_to_lab(np.array(rgb))
                v.lab = (round(float(lab[0]), 2), round(float(lab[1]), 2), round(float(lab[2]), 2))
                v.icon = str(icon)
                if v.lab[0] < DARK_ICON_L:
                    v.flags.append("dark_icon")
        if excluded.search(f"{blk.block_class.rsplit('.', 1)[-1]} {v.display}"):
            v.flags.append("excluded")
        if all(existing.meta != meta for existing in blk.variants):
            blk.variants.append(v)

    # Infested variants look like their normal counterparts; flag them when that counterpart exists.
    plain = {v.display.lower() for b in pal.blocks.values() for v in b.variants}
    for blk in pal.blocks.values():
        for v in blk.variants:
            m = re.match(r"infested\s+(.+)", v.display, re.IGNORECASE)
            if m and m.group(1).lower() in plain:
                v.flags.append("infested")

    # Blocks without a known shape whose every icon has the plain-cube outline are full cubes.
    for blk in pal.blocks.values():
        icons = [v.icon for v in blk.variants if v.icon]
        if blk.shape == "unknown" and blk.name not in overrides and icons:
            if all(cube_outline_iou(Path(i)) >= CUBE_IOU for i in icons):
                blk.shape = "full_cube"
    return pal
