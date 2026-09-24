"""S3 template generator (SOW §6.6, RT.1-RT.6): BuildSpec -> baseline OpsDoc, deterministic, no API.

Layout (design coordinates, SOW §4.3): footprint (0, 0)..(W-1, L-1) with the front facade at z = 0. A
foundation layer at y = 0 replaces the ground; walls run from y = 1 to the eaves; each storey's floor slab
sits at its bottom (y = 0, g, g + s, ...); the roof starts one block above the walls.

Front openings come from the spec's measured element boxes (normalized over the wall, eaves = 0, ground = 1),
rasterized with v1 R6.5: windows at least 1 wide and 2 tall (1 on storeys under 4 blocks), never touching
the ground row or the eaves row, glass flush in the 1-block wall; doors 2 tall at ground level, two doors side by
side when 2+ blocks wide.
Sides and back get v1 R4a.4 "sparse" windows: one per storey per 6 blocks of wall.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import yaml

from img2schem.engine.ops import OpsDoc
from img2schem.models import BuildSpec, Element
from img2schem.palette.query import PaletteIndex

PITCH = {"low": "1:2", "medium": "1:1", "steep": "2:1"}
ROLE_SLOT = {"wall": "wall", "roof": "roof", "trim": "trim", "window": "glass", "door": "door", "base": "base",
             "floor": "floor"}  # fmt: skip


class PlanError(ValueError):
    pass


def role_defaults() -> dict[str, str]:
    text = resources.files("img2schem.palette").joinpath("data/role_defaults.yaml").read_text(encoding="utf-8")
    return dict(yaml.safe_load(text))


def _cells(lo: float, hi: float, n: int) -> list[int]:
    """Indices 0..n-1 whose cell centers fall inside [lo, hi] (normalized); the nearest one if none do."""
    inside = [i for i in range(n) if lo <= (i + 0.5) / n <= hi]
    return inside or [min(n - 1, max(0, int((lo + hi) / 2 * n)))]


def _style(spec: BuildSpec, index: PaletteIndex | None, pitch: str, warnings: list[str]) -> dict[str, str]:
    style: dict[str, str] = {}
    for role, m in spec.materials.items():
        slot = ROLE_SLOT.get(role)
        if slot is None:
            warnings.append(f"materials.{role}: unknown role, ignored")
            continue
        if m.chosen:
            style[slot] = m.chosen
        if m.stairs:
            style[f"{slot}.stairs"] = m.stairs
        if m.slab:
            style[f"{slot}.slab"] = m.slab
    for role in ("wall", "roof"):
        if ROLE_SLOT[role] not in style:
            raise PlanError(f"materials.{role}.chosen is required (find a block with `img2schem palette search`)")
    for slot, block in role_defaults().items():
        style.setdefault(slot, block)

    # RT.3: the roof block needs stairs (1:1, 2:1) or a slab (1:2); else switch to the nearest block that has them.
    need = ("slab",) if pitch == "1:2" else ("stairs",)
    if index is not None and spec.roof.type != "flat" and not all(f"roof.{m}" in style for m in need):
        hit = index.usable(style["roof"])
        fam = index.family(style["roof"]) if hit else {}
        if not all(fam.get(m) for m in need):
            lab = hit[1].lab if hit and hit[1].lab else None
            best = index.nearest_with_family(lab, need) if lab else []
            if not best:
                raise PlanError(f"roof block {style['roof']} has no {'/'.join(need)} and no substitute was found")
            warnings.append(f"roof block {style['roof']} has no matching {'/'.join(need)}; using {best[0][1]} (RT.3)")
            style["roof"] = best[0][1]
    return style


def plan_template(spec: BuildSpec, index: PaletteIndex | None = None) -> tuple[OpsDoc, list[str]]:
    warnings: list[str] = []
    sc = spec.scale
    width = max(4, round(spec.facade.width_m * sc.blocks_per_m))
    depth_m = spec.footprint.depth_m
    depth = round(depth_m * sc.blocks_per_m) if depth_m else round(width * spec.footprint.depth_ratio)
    depth = min(64, max(4, depth))
    n, g, s = spec.facade.storeys, sc.ground_storey_height_blocks, sc.storey_height_blocks
    floor_ys = [0] + [g + i * s for i in range(n - 1)]
    storey_h = [g] + [s] * (n - 1)
    roof_y = g + (n - 1) * s
    wall_h = roof_y - 1  # walls: y = 1 .. roof_y - 1
    fp = {"x0": 0, "z0": 0, "x1": width - 1, "z1": depth - 1}
    inner = {"x0": 1, "z0": 1, "x1": width - 2, "z1": depth - 2}

    rtype = spec.roof.type
    if rtype == "auto":
        rtype = "gable" if n <= 3 else "flat"
    pitch = PITCH[spec.roof.pitch]
    style = _style(spec, index, pitch, warnings)

    ops: list[dict[str, Any]] = [
        {"op": "floors", "id": "foundation", "label": "Foundation (replaces the ground)", "footprint": fp, "ys": [0],
         "mat": "$base" if "base" in style else "$wall"},
        {"op": "walls", "id": "walls", "label": f"Walls - {n} storey{'s' * (n > 1)}, {width}x{depth}",
         "footprint": fp, "y0": 1, "height": wall_h},
        {"op": "floors", "id": "floors", "label": "Floor slabs", "footprint": inner, "ys": floor_ys},
    ]  # fmt: skip
    if "base" in style:
        ops.append({"op": "trim_band", "id": "base-course", "label": "Base course", "footprint": fp, "y": 1,
                    "mat": "$base"})  # fmt: skip
    if "trim" in style:
        ops.append({"op": "trim_band", "id": "eaves-band", "label": "Trim band under the eaves", "footprint": fp,
                    "y": wall_h, "mat": "$trim"})  # fmt: skip

    # Front openings from the measured elements (RT.2).
    front = [e for e in spec.elements if e.face == "front"]
    doors = 0
    for i, e in enumerate(front):
        if e.kind == "window":
            ops.append(_window_op(e, i, width, wall_h, fp, storey_h))
        elif e.kind == "door":
            ops += _door_ops(e, i, width)
            doors += 1
        else:
            warnings.append(f"elements[{i}] kind {e.kind!r} is not built by the template (a designer can add it)")
    if doors == 0:
        warnings.append("no door among the front elements; added one at the center (R10.3b)")
        ops += _door_ops(Element(kind="door", bbox=(0.45, 0.6, 0.55, 1.0)), len(front), width)
    for e in spec.elements:
        if e.face != "front":
            warnings.append(f"a {e.face} element is ignored: multiview facades arrive in Phase 4")

    # Sides and back: sparse windows (v1 R4a.4).
    for face, length in (("left", depth), ("right", depth), ("back", width)):
        count = length // 6
        sills = [fy + 2 for fy, h in zip(floor_ys, storey_h, strict=True) if fy + 2 + (2 if h >= 4 else 1) <= wall_h]
        if count and sills:
            ops.append({"op": "openings", "id": f"windows-{face}", "label": f"Windows, {face} side (sparse)",
                        "footprint": fp, "face": face, "sills": sills, "w": 1, "h": 2 if min(storey_h) >= 4 else 1,
                        "count": count, "spacing": 5})  # fmt: skip

    ridge = "x" if spec.roof.ridge == "parallel" else "z"
    ops.append({"op": "roof", "id": "roof", "label": f"Roof - {rtype}, {pitch}", "footprint": fp, "y0": roof_y,
                "type": rtype, "pitch": pitch, "ridge": ridge, "rise": "south",
                "overhang": spec.roof.overhang_blocks, "parapet": rtype == "flat"})  # fmt: skip
    return OpsDoc.model_validate({"style": style, "ops": ops}), warnings


def _window_op(e: Element, i: int, width: int, wall_h: int, fp: dict[str, int], storey_h: list[int]) -> dict[str, Any]:
    x0, y0, x1, y1 = e.bbox
    us = _cells(x0, x1, width)
    rows = _cells(y0, y1, wall_h)  # 0 = top row (y = wall_h)
    ys = sorted(wall_h - r for r in rows)
    bottom, top = 2, wall_h - 1  # never touch the ground row (y = 1) or the eaves row (y = wall_h)
    lo, hi = max(ys[0], bottom), min(ys[-1], top)
    if hi < lo:  # the box lay entirely on a forbidden row
        lo = hi = bottom if ys[0] < bottom else top
    min_h = 2 if min(storey_h) >= 4 else 1
    while hi - lo + 1 < min_h and (lo > bottom or hi < top):  # grow down if allowed, else up
        if lo > bottom:
            lo -= 1
        else:
            hi += 1
    return {"op": "window", "id": f"window-{i}", "label": f"Front window {i} (measured)", "footprint": fp,
            "face": "front", "u0": us[0], "u1": us[-1], "y0": lo, "y1": hi, "recess": 0}  # fmt: skip


def _door_ops(e: Element, i: int, width: int) -> list[dict[str, Any]]:
    us = _cells(e.bbox[0], e.bbox[2], width)
    if len(us) >= 2:
        mid = len(us) // 2
        us = [us[mid - 1], us[mid]]
    else:
        us = us[:1]
    ops: list[dict[str, Any]] = [
        {"op": "carve", "id": f"door-{i}-opening", "label": "Door opening", "from": [us[0], 1, 0],
         "to": [us[-1], 2, 0]},
    ]  # fmt: skip
    for j, u in enumerate(us):
        hinge = "right" if len(us) == 2 and j == 1 else "left"
        ops.append({"op": "door", "id": f"door-{i}-{j}", "label": "Front door (measured)", "pos": [u, 1, 0],
                    "facing": "north", "hinge": hinge})  # fmt: skip
    return ops
