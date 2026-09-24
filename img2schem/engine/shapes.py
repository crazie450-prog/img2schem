"""Curved geometry for the ``loft`` and ``sweep`` ops: 2D profiles rasterized per level, tubes along curves.

Cells are unit blocks; block (x, z) covers [x, x+1) x [z, z+1) and is inside a profile when its center is.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from img2schem.engine.ops import Ellipse, Loft, LoftKey, Polygon, Profile, Sweep


def shape_points(shape: Ellipse | Polygon) -> np.ndarray:
    """(N, 2) outline points in the XZ plane."""
    if isinstance(shape, Polygon):
        return np.array(shape.points, dtype=np.float64)
    n = max(48, int(2 * math.pi * max(shape.rx, shape.rz) * 2))
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.stack([shape.rx * np.cos(t), shape.rz * np.sin(t)], axis=1)
    a = math.radians(shape.rotate)
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return pts @ rot.T + np.array(shape.center)


def _transform(pts: np.ndarray, key: dict[str, float], pivot: tuple[float, float]) -> np.ndarray:
    p = (pts - pivot) * np.array([key["scale"] * key["sx"], key["scale"] * key["sz"]])
    a = math.radians(key["rotate"])
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return p @ rot.T + pivot + np.array([key["dx"], key["dz"]])


def _catmull_rom(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    return 0.5 * (
        2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t**3
    )


FIELDS = ("dx", "dz", "scale", "sx", "sz", "rotate")


def key_at(keys: list[LoftKey], y: int, smooth: bool) -> dict[str, float]:
    """The interpolated transform at height ``y`` (keys sorted by y; clamped outside their range)."""
    if len(keys) == 1 or y <= keys[0].y:
        return {f: getattr(keys[0], f) for f in FIELDS}
    if y >= keys[-1].y:
        return {f: getattr(keys[-1], f) for f in FIELDS}
    i = max(j for j in range(len(keys) - 1) if keys[j].y <= y)
    t = (y - keys[i].y) / (keys[i + 1].y - keys[i].y)
    k0, k1, k2, k3 = keys[max(i - 1, 0)], keys[i], keys[i + 1], keys[min(i + 2, len(keys) - 1)]
    out = {}
    for f in FIELDS:
        a, b, c, d = (getattr(k, f) for k in (k0, k1, k2, k3))
        out[f] = _catmull_rom(a, b, c, d, t) if smooth else b + (c - b) * t
    return out


def inside(pts: np.ndarray, cx: np.ndarray, cz: np.ndarray) -> np.ndarray:
    """Even-odd rule: which points (cx, cz) lie inside the closed polygon ``pts``."""
    result = np.zeros(cx.shape, dtype=bool)
    x0, z0 = pts[:, 0], pts[:, 1]
    x1, z1 = np.roll(x0, -1), np.roll(z0, -1)
    for ax, az, bx, bz in zip(x0, z0, x1, z1, strict=True):
        if az == bz:
            continue
        crosses = (az > cz) != (bz > cz)
        x_at = ax + (cz - az) * (bx - ax) / (bz - az)
        result ^= crosses & (cx < x_at)
    return result


def profile_mask(profile: Profile, key: dict[str, float], pivot: tuple[float, float], origin: tuple[int, int],
                 size: tuple[int, int]) -> np.ndarray:  # fmt: skip
    """Boolean mask [x, z]: cells whose center lies inside the transformed profile; ``origin`` = world (x, z) of
    cell [0, 0]."""
    cx, cz = np.meshgrid(np.arange(size[0]) + origin[0] + 0.5, np.arange(size[1]) + origin[1] + 0.5, indexing="ij")
    mask = inside(_transform(shape_points(profile.outer), key, pivot), cx, cz)
    for m in profile.minus:
        mask &= ~inside(_transform(shape_points(m), key, pivot), cx, cz)
    return mask


def loft_cells(op: Loft) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    """(wall/solid cells, floor cells) in world coordinates."""
    smooth = op.interp == "smooth"
    y0, y1 = op.keys[0].y, op.keys[-1].y
    keys = {y: key_at(op.keys, y, smooth) for y in range(y0, y1 + 1)}
    outer = np.concatenate([_transform(shape_points(op.profile.outer), k, op.pivot) for k in keys.values()])
    lo = np.floor(outer.min(axis=0)).astype(int) - 1
    hi = np.ceil(outer.max(axis=0)).astype(int) + 1
    origin, size = (int(lo[0]), int(lo[1])), (int(hi[0] - lo[0] + 1), int(hi[1] - lo[1] + 1))
    kernel = np.ones((3, 3), np.uint8)
    walls: list[tuple[int, int, int]] = []
    floors: list[tuple[int, int, int]] = []
    for y, key in keys.items():
        mask = profile_mask(op.profile, key, op.pivot, origin, size)
        is_floor = (op.floor_every is not None and (y - y0) % op.floor_every == 0) or (op.caps and y in (y0, y1))
        if op.fill == "shell" and not is_floor:
            inner = cv2.erode(mask.astype(np.uint8), kernel, iterations=op.thickness, borderValue=0).astype(bool)
            layer = mask & ~inner
        else:
            layer = mask
        target = floors if is_floor and op.fill == "shell" else walls
        target.extend((int(x) + origin[0], y, int(z) + origin[1]) for x, z in np.argwhere(layer))
    return walls, floors


def sweep_cells(op: Sweep, samples_per_block: int = 4) -> list[tuple[int, int, int]]:
    pts = np.array(op.points, dtype=np.float64)
    if op.interp == "smooth" and len(pts) > 2:
        ext = np.vstack([pts[0], pts, pts[-1]])
        path = []
        for i in range(len(pts) - 1):
            seg = np.linalg.norm(pts[i + 1] - pts[i])
            for t in np.linspace(0, 1, max(2, int(seg * samples_per_block)), endpoint=False):
                c = ext[i : i + 4]
                path.append([_catmull_rom(c[0, d], c[1, d], c[2, d], c[3, d], float(t)) for d in range(3)])
        path.append(pts[-1])
        samples = np.array(path)
    else:
        segs = [np.linspace(pts[i], pts[i + 1], max(2, int(np.linalg.norm(pts[i + 1] - pts[i]) * samples_per_block)))
                for i in range(len(pts) - 1)]  # fmt: skip
        samples = np.vstack(segs)
    r = op.radius
    k = int(math.ceil(r)) + 1
    grid = np.stack(np.meshgrid(*[np.arange(-k, k + 1)] * 3, indexing="ij"), axis=-1).reshape(-1, 3)
    cells: set[tuple[int, int, int]] = set()
    for s in samples:
        base = np.floor(s).astype(int)
        cand = base + grid
        near = cand[np.linalg.norm(cand + 0.5 - s, axis=1) <= r]
        cells.update((int(a), int(b), int(c)) for a, b, c in near)
    return sorted(cells)
