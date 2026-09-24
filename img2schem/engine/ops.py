"""The build DSL (SOW §6.5, re-scoped for 1.7.10 in SOW_GTNH.md): ops are pydantic models, a discriminated
union on ``op``. Claude's tool schemas are generated from these models (RE.1), so field docs matter.

Coordinates are design coordinates (SOW §4.3): X east, Y up, Z south; the front facade is the plane z = 0
facing north; the ground floor is y = 0. Boxes and rects are inclusive. Negative coordinates are fine; the
compiler normalizes the result.

Materials (``mat``) are one of:
- a slot, ``"$wall"``, resolved through ``OpsDoc.style``;
- a family member, ``"$roof.stairs"`` / ``".slab"`` / ``".wall"`` / ``".fence"`` / ``".fence_gate"``: the style
  key ``"roof.stairs"`` if present, else the palette family of the ``$roof`` block;
- a literal block, ``"minecraft:stonebrick"`` or ``"chisel:marble@3"``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from img2schem.engine.states import Direction

Vec3 = tuple[int, int, int]

SET_CELLS_PER_OP = 64
SET_CELLS_PER_BUILD = 256


class Rect(BaseModel):
    """A footprint in the XZ plane, inclusive."""

    x0: int
    z0: int
    x1: int
    z1: int

    @model_validator(mode="after")
    def _ordered(self) -> Rect:
        if self.x1 < self.x0 or self.z1 < self.z0:
            raise ValueError(f"rect needs x0 <= x1 and z0 <= z1, got {self}")
        return self


class OpBase(BaseModel):
    id: str = Field(description="Stable id, unique in the document.")
    label: str = Field("", description="Human-readable description, e.g. 'Main roof - gable, 1:1'.")
    group: str | None = None
    note: str | None = Field(None, description="Why this op exists (required when moving measured openings).")
    mode: Literal["overwrite", "keep"] = Field(
        "overwrite", description="overwrite: replace earlier blocks; keep: only fill cells that are still air."
    )


class Box(OpBase):
    op: Literal["box"] = "box"
    from_: Vec3 = Field(alias="from")
    to: Vec3
    mat: str
    hollow: bool = False

    model_config = {"populate_by_name": True}


class Walls(OpBase):
    """A closed rectangular wall loop around ``footprint`` from ``y0`` up ``height`` blocks."""

    op: Literal["walls"] = "walls"
    footprint: Rect
    y0: int = 0
    height: int = Field(ge=1)
    mat: str = "$wall"
    thickness: int = Field(1, ge=1)


class Floors(OpBase):
    """Solid floor layers across ``footprint`` at each y in ``ys``."""

    op: Literal["floors"] = "floors"
    footprint: Rect
    ys: list[int]
    mat: str = "$floor"


class Door(OpBase):
    """A two-block door with its lower half at ``pos``. ``facing`` is the wall's outward direction:
    ``north`` for a door in the front wall (z = z0), ``south`` for the back wall (verified in game for north)."""

    op: Literal["door"] = "door"
    pos: Vec3
    facing: Direction = "north"
    mat: str = "$door"
    hinge: Literal["left", "right"] = "left"


class Openings(OpBase):
    """A row of equal windows on one face of ``footprint``, carved through the wall and filled with ``mat``.

    ``face``: front (z = z0), back (z = z1), left (x = x0, west), right (x = x1, east). Windows are ``w`` wide and
    ``h`` tall with their bottom at each y in ``sills``; ``count`` windows are centered on the face with
    ``spacing`` blocks of wall between them (count 0 = as many as fit with ``margin`` from the corners).
    """

    op: Literal["openings"] = "openings"
    footprint: Rect
    face: Literal["front", "back", "left", "right"]
    sills: list[int]
    w: int = Field(1, ge=1)
    h: int = Field(2, ge=1)
    spacing: int = Field(2, ge=1)
    count: int = Field(0, ge=0)
    margin: int = Field(1, ge=0)
    mat: str = "$glass"


class Window(OpBase):
    """One window: a rectangle on a face of ``footprint`` spanning ``u0``..``u1`` along the face (x on front/back,
    z on left/right) and ``y0``..``y1``. ``recess: 1`` leaves the wall cell open and sets the glass one block in,
    which gives the facade depth; ``0`` puts the glass in the wall plane."""

    op: Literal["window"] = "window"
    footprint: Rect
    face: Literal["front", "back", "left", "right"]
    u0: int
    u1: int
    y0: int
    y1: int
    recess: int = Field(0, ge=0, le=1)
    mat: str = "$glass"

    @model_validator(mode="after")
    def _ordered(self) -> Window:
        if self.u1 < self.u0 or self.y1 < self.y0:
            raise ValueError("window needs u0 <= u1 and y0 <= y1")
        return self


class Roof(OpBase):
    """A roof over ``footprint`` whose lowest course sits at ``y0`` (usually the top of the walls + 1).

    - ``type``: flat, gable (ridge along ``ridge``), hip, or shed (rising toward ``rise``);
    - ``pitch``: ``1:1`` stairs, ``1:2`` alternating bottom/top slabs, ``2:1`` stairs over full blocks;
    - ``mat``: the full-block slot (e.g. ``$roof``); stairs and slabs come from ``<mat>.stairs`` / ``<mat>.slab``;
    - ``gable_fill``: fills the triangular gable ends (gable and shed roofs);
    - ``parapet``: flat roofs only, a 1-block ring of ``mat`` around the edge.
    """

    op: Literal["roof"] = "roof"
    footprint: Rect
    y0: int
    type: Literal["flat", "gable", "hip", "shed"] = "gable"
    pitch: Literal["1:1", "1:2", "2:1"] = "1:1"
    ridge: Literal["x", "z"] = "x"
    rise: Direction = "south"
    overhang: int = Field(1, ge=0)
    mat: str = "$roof"
    gable_fill: str = "$wall"
    parapet: bool = False


class Column(OpBase):
    """A vertical run at ``pos`` (x, z) from ``y0``; logs get their vertical axis."""

    op: Literal["column"] = "column"
    pos: tuple[int, int]
    y0: int = 0
    height: int = Field(ge=1)
    mat: str


class Beam(OpBase):
    """An axis-aligned run from ``from`` to ``to`` (exactly one axis may differ); logs get their axis."""

    op: Literal["beam"] = "beam"
    from_: Vec3 = Field(alias="from")
    to: Vec3
    mat: str

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _one_axis(self) -> Beam:
        if sum(a != b for a, b in zip(self.from_, self.to, strict=True)) > 1:
            raise ValueError("beam endpoints may differ on one axis only")
        return self


class TrimBand(OpBase):
    """A 1-block ring around ``footprint`` at height ``y``, pushed out by ``outset`` (cornices, belt courses)."""

    op: Literal["trim_band"] = "trim_band"
    footprint: Rect
    y: int
    mat: str = "$trim"
    outset: int = Field(0, ge=0)


class Carve(OpBase):
    """Set the inclusive box ``from``..``to`` to air."""

    op: Literal["carve"] = "carve"
    from_: Vec3 = Field(alias="from")
    to: Vec3

    model_config = {"populate_by_name": True}


class SetBlock(OpBase):
    """Escape hatch: place single blocks. At most 64 cells per op and 256 per build."""

    op: Literal["set"] = "set"
    cells: list[Vec3] = Field(max_length=SET_CELLS_PER_OP)
    block: str


Op = Annotated[
    Box | Walls | Floors | Door | Openings | Window | Roof | Column | Beam | TrimBand | Carve | SetBlock,
    Field(discriminator="op"),
]


class OpsDoc(BaseModel):
    """``ops.json``: the build program (SOW §5.3)."""

    version: int = 1
    style: dict[str, str] = Field(
        default_factory=dict, description='Slot -> block, e.g. {"wall": "minecraft:brick_block"}.'
    )
    ops: list[Op] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> OpsDoc:
        ids = [o.id for o in self.ops]
        if len(ids) != len(set(ids)):
            raise ValueError("op ids must be unique")
        n_set = sum(len(o.cells) for o in self.ops if isinstance(o, SetBlock))
        if n_set > SET_CELLS_PER_BUILD:
            raise ValueError(f"'set' ops place {n_set} cells; the limit is {SET_CELLS_PER_BUILD} per build")
        return self
