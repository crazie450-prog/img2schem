"""Resolve ``mat`` strings to blocks (see engine/ops.py): slots, family members, literals."""

from __future__ import annotations

from dataclasses import dataclass

from img2schem.palette.query import FAMILY_SHAPES, PaletteIndex
from img2schem.util.block import format_block, parse_block


class MaterialError(ValueError):
    pass


@dataclass(frozen=True)
class Material:
    """A resolved block plus what the engine needs to orient it."""

    name: str
    meta: int
    shape: str  # palette shape, or "unknown" without a palette
    top_block: str | None = None  # slabs with a separate top-half block

    @property
    def block(self) -> str:
        return format_block(self.name, self.meta)


class Resolver:
    def __init__(self, style: dict[str, str], index: PaletteIndex | None = None):
        self.style = style
        self.index = index
        self._cache: dict[str, Material] = {}

    def __call__(self, mat: str) -> Material:
        if mat not in self._cache:
            self._cache[mat] = self._resolve(mat)
        return self._cache[mat]

    def _resolve(self, mat: str) -> Material:
        if not mat.startswith("$"):
            return self._literal(mat)
        key = mat[1:]
        if key in self.style:  # a slot, or an explicit family override such as "roof.stairs"
            return self._resolve(self.style[key]) if self.style[key].startswith("$") else self._literal(self.style[key])
        slot, _, member = key.partition(".")
        if not member:
            raise MaterialError(f"style has no slot {slot!r} (for {mat})")
        if member not in FAMILY_SHAPES:
            raise MaterialError(f"unknown family member {member!r} in {mat} (use one of {', '.join(FAMILY_SHAPES)})")
        base = self._resolve(f"${slot}")
        if self.index is None:
            raise MaterialError(f"{mat}: no palette to look up the {member} of {base.block}; set style[{key!r}]")
        found = self.index.family(base.block).get(member)
        if found is None:
            raise MaterialError(f"{base.block} has no matching {member} in the palette; set style[{key!r}]")
        return self._literal(found)

    def _literal(self, block: str) -> Material:
        try:
            name, meta = parse_block(block)
        except ValueError as e:
            raise MaterialError(str(e)) from None
        if self.index is None:
            return Material(name, meta, guess_shape(name))
        blk = self.index.palette.blocks.get(name)
        if blk is None:
            raise MaterialError(f"{block}: not in the palette")
        return Material(name, meta, blk.shape, blk.top_block)


def guess_shape(name: str) -> str:
    """Without a palette (tests, hand-written builds), infer the shape from vanilla-style names."""
    n = name.split(":", 1)[-1].lower()
    for shape, key in (("stairs", "stairs"), ("slab", "slab"), ("door", "door"), ("log", "log")):
        if key in n and not (shape == "door" and "trapdoor" in n):
            return shape
    return "unknown"
