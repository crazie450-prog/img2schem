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

# Block properties that exist in-game but never appear in blockstate asset files (they don't change
# the model), so the extractor cannot see them. validate_state accepts these on any block.
ASSET_INVISIBLE_PROPERTIES = frozenset({"waterlogged", "powered", "persistent", "distance"})

# Semantic labels carried per compiled cell (SOW §5.3).
LABELS = {0: "air", 1: "wall", 2: "window", 3: "door", 4: "roof", 5: "trim", 6: "floor", 7: "base", 8: "other"}


@dataclass
class BlockGrid:
    """``idx[X, Y, Z]`` indexes into ``palette``; index 0 is always ``minecraft:air``."""

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
    data_version: int | None = None
    data_version_source: Literal["jar", "table", "unknown"] = "unknown"
    client_jar: str | None = None
    mods: list[ModInfo] = Field(default_factory=list)
    worldedit: bool = False
    schematics_dir: str | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- palette (Phase 0 subset of §5.3)

Shape = Literal[
    "full_cube", "column", "stairs", "slab", "wall", "fence", "fence_gate", "pane", "door", "trapdoor", "other"
]


class PaletteBlock(BaseModel):
    id: str
    mod: str
    source: str
    shape: Shape = "other"
    properties: dict[str, list[str]] = Field(default_factory=dict)
    default_state: str
    flags: list[str] = Field(default_factory=list)


class PaletteReport(BaseModel):
    blocks_per_mod: dict[str, int] = Field(default_factory=dict)
    blocks_per_shape: dict[str, int] = Field(default_factory=dict)
    code_rendered: list[str] = Field(default_factory=list)
    excluded_per_flag: dict[str, int] = Field(default_factory=dict)
    parse_errors: list[dict[str, str]] = Field(default_factory=list)


class Palette(BaseModel):
    version: int = 1
    extractor_version: str
    cache_key: str
    instance_name: str | None = None
    mc_version: str | None = None
    blocks: dict[str, PaletteBlock] = Field(default_factory=dict)

    def validate_state(self, state: str) -> str | None:
        """Return None if ``state`` is valid for this palette, else a human-readable reason (RP.17)."""
        from img2schem.util.blockstate import parse_state

        try:
            block_id, props = parse_state(state)
        except ValueError as e:
            return str(e)
        if block_id == AIR:
            return None
        blk = self.blocks.get(block_id)
        if blk is None:
            return f"unknown block {block_id!r} (not in the active instance's palette)"
        for k, v in props.items():
            if k not in blk.properties:
                if k in ASSET_INVISIBLE_PROPERTIES:
                    continue
                return f"{block_id}: unknown property {k!r} (known: {sorted(blk.properties)})"
            if v not in blk.properties[k]:
                return f"{block_id}: {k}={v} not in {blk.properties[k]}"
        return None


# ---------------------------------------------------------------- validation


class Issue(BaseModel):
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    pos: tuple[int, int, int] | None = None
    autofix_applied: bool = False
