"""Data contracts (SOW §5.3). Pydantic for JSON artifacts; BlockGrid wraps numpy arrays.

Coordinate convention (SOW §4.3): arrays are [X, Y, Z], Y up. X = building width (east +),
Z = depth (south +). The front facade lies in the plane z = 0 and faces north (-Z); y = 0 is the ground.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

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
    # "dark_icon": near-black icon (color may be a render failure); "excluded": matches palette/data/exclude.yaml;
    # "infested": an infested block whose normal counterpart exists; "nbt_variant": the variant's meta can't be
    # material for its shape (stairs 0/8, slab 0-7, log 0-3), so it is stored in tile-entity NBT
    flags: list[str] = Field(default_factory=list)


class PaletteBlock(BaseModel):
    """A block and its variants. A variant is *usable* for building when the block's shape is known, the
    variant has a color, and it has no flags."""

    name: str
    mod: str
    block_class: str
    display: str | None = None
    shape: Shape = "unknown"
    # Slabs only: a separate block for the top half (Chisel's "<name>_top"); then all 16 metas are materials.
    top_block: str | None = None
    variants: list[PaletteVariant] = Field(default_factory=list)

    def usable(self) -> list[PaletteVariant]:
        if self.shape == "unknown":
            return []
        return [v for v in self.variants if v.rgb is not None and not v.flags]

    def variant_for(self, meta: int) -> PaletteVariant | None:
        """The material variant of a placed metadata value (orientation bits stripped per shape)."""
        if self.shape == "slab" and self.top_block:
            material = meta
        else:
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


# ---------------------------------------------------------------- BuildSpec (SOW §5.3: v1 FacadeSpec + v2 fields)


class Scale(BaseModel):
    blocks_per_m: float = Field(default=1.0, gt=0)
    storey_height_blocks: int = Field(default=4, ge=3)
    ground_storey_height_blocks: int = Field(default=4, ge=3)


class Facade(BaseModel):
    width_m: float = Field(gt=0)
    height_m: float | None = None  # estimate incl. roof; informational
    storeys: int = Field(ge=1, le=30)
    symmetric: bool = False


class Footprint(BaseModel):
    depth_ratio: float = Field(default=0.6, gt=0)
    depth_m: float | None = None  # overrides depth_ratio


class RoofSpec(BaseModel):
    type: Literal["flat", "gable", "hip", "shed", "auto"] = "auto"
    ridge: Literal["parallel", "perpendicular"] = "parallel"  # to the front facade
    pitch: Literal["low", "medium", "steep"] = "medium"
    overhang_blocks: int = Field(default=1, ge=0)


class Element(BaseModel):
    """An opening measured on the rectified facade. ``bbox`` = [x0, y0, x1, y1], normalized 0-1 over the wall
    from the left edge to the right and from the eaves (0) down to the ground (1)."""

    kind: str  # window | door | garage | balcony | porch | bay | chimney | ... (template handles window, door)
    bbox: tuple[float, float, float, float]
    storey: int | None = None
    face: Literal["front", "left", "right", "back"] = "front"

    @model_validator(mode="after")
    def _bbox(self) -> Element:
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError(f"bbox must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, got {self.bbox}")
        return self


class MaterialSpec(BaseModel):
    hint: str | None = None
    rgb: tuple[int, int, int] | None = None
    candidates: list[str] = Field(default_factory=list)
    chosen: str | None = None  # a block (name@meta); fills the style slot
    stairs: str | None = None  # optional explicit family members (else the palette family is used)
    slab: str | None = None


class BuildSpec(BaseModel):
    """``spec.json``: the measured, human-editable description of the building."""

    version: int = 2
    input_mode: Literal["photo", "multiview", "describe", "manual"] = "manual"
    building_type: str | None = None
    scale: Scale = Scale()
    facade: Facade
    footprint: Footprint = Footprint()
    roof: RoofSpec = RoofSpec()
    elements: list[Element] = Field(default_factory=list)
    materials: dict[str, MaterialSpec] = Field(default_factory=dict)  # wall, roof, trim, window, door, base, floor
    style: dict[str, Any] = Field(default_factory=dict)
    features: list[dict[str, Any]] = Field(default_factory=list)
    unseen: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- validation


class Issue(BaseModel):
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    pos: tuple[int, int, int] | None = None
    autofix_applied: bool = False
