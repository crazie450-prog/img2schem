"""Data contracts (SOW §5.3). Pydantic for JSON artifacts; BlockGrid wraps numpy arrays.

Coordinate convention (SOW §4.3): arrays are [X, Y, Z], Y up. X = building width (east +),
Z = depth (south +). The front facade lies in the plane z = 0 and faces north (-Z); y = 0 is the ground.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

AIR = "minecraft:air"

# Semantic labels carried per compiled cell (SOW §5.3).
LABELS = {0: "air", 1: "wall", 2: "window", 3: "door", 4: "roof", 5: "trim", 6: "floor", 7: "base", 8: "other"}


@dataclass
class BlockGrid:
    """``idx[X, Y, Z]`` indexes into ``palette`` of ``name@meta`` blocks; index 0 is always ``minecraft:air``."""

    idx: np.ndarray
    palette: list[str] = field(default_factory=lambda: [AIR])

    def __post_init__(self) -> None:
        self.idx = np.asarray(self.idx, dtype=np.int32)
        if self.idx.ndim != 3:
            raise ValueError(f"idx must be 3-D [X, Y, Z], got shape {self.idx.shape}")
        if not self.palette or self.palette[0] != AIR:
            raise ValueError("palette[0] must be minecraft:air")

    @property
    def shape(self) -> tuple[int, int, int]:
        x, y, z = self.idx.shape
        return int(x), int(y), int(z)

    @classmethod
    def empty(cls, x: int, y: int, z: int) -> BlockGrid:
        return cls(np.zeros((x, y, z), dtype=np.int32), [AIR])

    def index_of(self, state: str) -> int:
        """Palette index for ``state``, appending it if new."""
        try:
            return self.palette.index(state)
        except ValueError:
            self.palette.append(state)
            return len(self.palette) - 1

    def set(self, x: int, y: int, z: int, state: str) -> None:
        self.idx[x, y, z] = self.index_of(state)

    def fill(self, lo: tuple[int, int, int], hi: tuple[int, int, int], state: str) -> None:
        """Fill the inclusive box ``lo..hi``."""
        i = self.index_of(state)
        self.idx[lo[0] : hi[0] + 1, lo[1] : hi[1] + 1, lo[2] : hi[2] + 1] = i

    def compact(self) -> BlockGrid:
        """Drop unused palette entries (air stays at 0); order of first use by palette index kept."""
        used = np.unique(self.idx)
        keep = [0] + [int(u) for u in used if u != 0]
        remap = np.zeros(len(self.palette), dtype=np.int32)
        for new, old in enumerate(keep):
            remap[old] = new
        return BlockGrid(remap[self.idx], [self.palette[i] for i in keep])

    def counts(self) -> dict[str, int]:
        c = np.bincount(self.idx.reshape(-1), minlength=len(self.palette))
        return {s: int(n) for s, n in zip(self.palette, c, strict=True) if n and s != AIR}

    def nonair(self) -> int:
        return int(np.count_nonzero(self.idx))

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(directory / "blocks.npz", idx=self.idx)
        (directory / "palette_used.json").write_text(json.dumps(self.palette, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> BlockGrid:
        with np.load(directory / "blocks.npz") as z:
            idx = z["idx"]
        palette = json.loads((directory / "palette_used.json").read_text(encoding="utf-8"))
        return cls(idx, palette)


# ---------------------------------------------------------------- instances

Loader = Literal["vanilla", "fabric", "quilt", "forge", "neoforge", "unknown"]


class ModInfo(BaseModel):
    id: str
    name: str | None = None
    version: str | None = None
    jar: str


class InstanceInfo(BaseModel):
    name: str
    launcher: str
    game_dir: str
    mc_version: str | None = None
    loader: Loader = "unknown"
    loader_version: str | None = None
    client_jar: str | None = None
    mods: list[ModInfo] = Field(default_factory=list)
    worldedit: bool = False
    schematics_dir: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- palette


class WorldPalette(BaseModel):
    """Block registry names of one world, read from its level.dat (Forge 1.7.10 ``FML.ItemData``).

    Numeric IDs are recorded for reference only; schematics store names (see stages/export_schem.py).
    """

    world: str
    level_dat: str
    blocks: dict[str, int] = Field(default_factory=dict)  # registry name -> numeric id in that world

    def validate_block(self, block: str) -> str | None:
        """None if ``block`` exists in this world, else a human-readable reason."""
        from img2schem.util.block import parse_block

        try:
            name, _ = parse_block(block)
        except ValueError as e:
            return str(e)
        if name != AIR and name not in self.blocks:
            return f"unknown block {name!r} (not registered in world {self.world!r})"
        return None


Shape = Literal[
    "full_cube", "stairs", "slab", "wall", "fence", "fence_gate", "pane", "door", "trapdoor", "log", "unknown"
]


class PaletteVariant(BaseModel):
    """One placeable variant (block + metadata) as listed in NEI's item panel."""

    block: str  # name@meta
    meta: int
    display: str
    rgb: tuple[int, int, int] | None = None  # average icon color (None: no reliable icon)
    hex: str | None = None
    lab: tuple[float, float, float] | None = None
    alpha: float | None = None  # transparent fraction of the icon
    icon: str | None = None  # path to the owner's local icon (never committed, SOW C16)
    flags: list[str] = Field(default_factory=list)  # "dark_icon": near-black icon, color may be a render failure


class PaletteBlock(BaseModel):
    name: str
    mod: str
    block_class: str
    display: str | None = None
    shape: Shape = "unknown"
    variants: list[PaletteVariant] = Field(default_factory=list)

    def variant_for(self, meta: int) -> PaletteVariant | None:
        """The material variant of a placed metadata value (orientation bits stripped per shape)."""
        material = {"stairs": meta & 8, "slab": meta & 7, "log": meta & 3}.get(self.shape, meta)
        by_meta = {v.meta: v for v in self.variants}
        return by_meta.get(material) or by_meta.get(meta) or by_meta.get(0)


class Palette(BaseModel):
    """Every block of the instance with shape and per-variant colors (built from NEI dumps, D-016)."""

    version: int = 1
    source: str
    key: str
    blocks: dict[str, PaletteBlock] = Field(default_factory=dict)

    def color(self, block: str) -> tuple[int, int, int] | None:
        from img2schem.util.block import parse_block

        name, meta = parse_block(block)
        blk = self.blocks.get(name)
        v = blk.variant_for(meta) if blk else None
        return v.rgb if v else None


# ---------------------------------------------------------------- validation


class Issue(BaseModel):
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    pos: tuple[int, int, int] | None = None
    autofix_applied: bool = False
