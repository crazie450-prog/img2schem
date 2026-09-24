"""Palette queries (RP.7, RP.17 re-scoped for GTNH): block families and color lookups over usable variants.

Families link a full block to the stairs/slab/wall/fence/fence gate that look like it, so roofs and trims can
use matching shapes. Members are found by display-name stem ("Stone Bricks", "Stone Brick Stairs" and
"Stone Brick Slab" all stem to "stone brick"), and among several candidates the nearest color wins.
"""

from __future__ import annotations

import re
from collections import defaultdict

import numpy as np

from img2schem.models import Palette, PaletteBlock, PaletteVariant
from img2schem.util.block import parse_block

FAMILY_SHAPES = ("stairs", "slab", "wall", "fence", "fence_gate")
FAMILY_MAX_DE = 20.0  # a same-stem member further than this (CIE76) doesn't look like the base block

_DROP_WORDS = re.compile(
    r"\((?:fireproof)\)|\b(?:stairs?|slabs?|walls?|fence gate|fences?|block of|blocks?|planks?|wood|double)\b"
)


def stem(display: str) -> str:
    s = _DROP_WORDS.sub(" ", display.lower())
    s = re.sub(r"\bbricks\b", "brick", s)
    s = re.sub(r"\btiles\b", "tile", s)
    return " ".join(s.split())


def delta_e(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return float(np.linalg.norm(np.subtract(a, b)))


class PaletteIndex:
    def __init__(self, palette: Palette):
        self.palette = palette
        self.by_block: dict[str, tuple[PaletteBlock, PaletteVariant]] = {}
        self._stems: dict[str, dict[str, list[PaletteVariant]]] = {s: defaultdict(list) for s in FAMILY_SHAPES}
        for blk in palette.blocks.values():
            for v in blk.usable():
                self.by_block[v.block] = (blk, v)
                if blk.shape in self._stems:
                    self._stems[blk.shape][stem(v.display)].append(v)

    def usable(self, block: str) -> tuple[PaletteBlock, PaletteVariant] | None:
        """The usable variant a placed block (any orientation metadata) belongs to."""
        name, meta = parse_block(block)
        blk = self.palette.blocks.get(name)
        v = blk.variant_for(meta) if blk else None
        return (blk, v) if blk and v and v.block in self.by_block else None

    def family(self, block: str) -> dict[str, str | None]:
        """``{shape: member block}`` for a usable full block; members missing or too far in color are None."""
        hit = self.usable(block)
        out: dict[str, str | None] = dict.fromkeys(FAMILY_SHAPES)
        if hit is None or hit[0].shape != "full_cube" or hit[1].lab is None:
            return out
        lab = hit[1].lab
        for shape in FAMILY_SHAPES:
            cands = [(delta_e(lab, c.lab), c.block) for c in self._stems[shape].get(stem(hit[1].display), []) if c.lab]
            if cands:
                de, member = min(cands)
                out[shape] = member if de <= FAMILY_MAX_DE else None
        return out

    def nearest_with_family(
        self, lab: tuple[float, float, float], need: tuple[str, ...] = ("stairs", "slab"), n: int = 1
    ) -> list[tuple[float, str]]:
        """Usable full blocks closest in color (CIE76) that have every family member in ``need``."""
        out = []
        for block, (blk, v) in self.by_block.items():
            if blk.shape != "full_cube" or v.lab is None:
                continue
            fam = self.family(block)
            if all(fam[m] for m in need):
                out.append((delta_e(lab, v.lab), block))
        return sorted(out)[:n]
