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
from img2schem.util.color import ciede2000

FAMILY_SHAPES = ("stairs", "slab", "wall", "fence", "fence_gate")
FAMILY_MAX_DE = 20.0  # a same-stem member further than this (CIE76) doesn't look like the base block
ROLES = ("wall", "roof", "trim", "base", "floor", "glass", "door")
BUSY_VARIANCE = 8.0  # RM.2: walls with busier top faces than this read as noise at a distance

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

    def color_lab(self, v: PaletteVariant) -> tuple[float, float, float] | None:
        """The true block color (lit top face) when known, else the icon average."""
        return v.face_lab or v.lab

    def match(self, lab: tuple[float, float, float], role: str, n: int = 8) -> list[dict[str, object]]:
        """RM.2: palette blocks for a role, best first. Score = CIEDE2000 distance + penalties (roof/trim: +6 without
        stairs, +3 without a slab; wall: +2 for a busy texture). Exact: candidates are visited in color order until
        the color distance alone exceeds the n-th best score."""
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r} (one of {', '.join(ROLES)})")
        pool: list[tuple[PaletteBlock, PaletteVariant, tuple[float, float, float]]] = []
        for blk, v in self.by_block.values():
            c = self.color_lab(v)
            if c is None:
                continue
            is_glass = "glass" in f"{blk.name} {v.display}".lower()
            if role == "glass":
                ok = is_glass and blk.shape in ("pane", "full_cube")
            elif role == "door":
                ok = blk.shape == "door"
            else:
                ok = blk.shape == "full_cube" and not is_glass
            if ok:
                pool.append((blk, v, c))
        if not pool:
            return []
        des = ciede2000(np.array(lab), np.array([c for _, _, c in pool]))
        out: list[dict[str, object]] = []
        for i in np.argsort(des, kind="stable"):
            de = float(des[i])
            if len(out) >= n and de > sorted(float(r["score"]) for r in out)[n - 1]:  # type: ignore[arg-type]
                break  # penalties are >= 0, so nothing further can score better
            blk, v, _ = pool[i]
            fam = self.family(v.block) if role in ("roof", "trim") else {}
            penalty = 0.0
            if role in ("roof", "trim"):
                penalty += (6.0 if not fam.get("stairs") else 0.0) + (3.0 if not fam.get("slab") else 0.0)
            if role == "wall" and (v.variance or 0.0) > BUSY_VARIANCE:
                penalty += 2.0
            row = {"block": v.block, "display": v.display, "mod": blk.mod, "de": round(de, 2)}
            row |= {"score": round(de + penalty, 2), "stairs": fam.get("stairs"), "slab": fam.get("slab")}
            out.append(row)
        return sorted(out, key=lambda r: (r["score"], r["block"]))[:n]  # type: ignore[return-value]

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
        assert lab is not None
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
