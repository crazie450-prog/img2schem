"""Curved geometry for the ``loft`` and ``sweep`` ops: 2D profiles rasterized per level, tubes along curves.

Cells are unit blocks; block (x, z) covers [x, x+1) x [z, z+1) and is inside a profile when its center is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from img2schem.engine.ops import Ellipse, Loft, LoftKey, Polygon, Profile, Sweep
from img2schem.engine.states import Direction


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
    """Even-odd rule: which points of the grid (cx, cz) (meshgrid, indexing "ij": rows share x, columns z) lie
    inside the closed polygon ``pts``. Scanline: a point is inside if an odd number of edges cross its column
    line (constant z) at a larger x."""
    x0, z0 = pts[:, 0], pts[:, 1]
    x1, z1 = np.roll(x0, -1), np.roll(z0, -1)
    keep = z0 != z1
    x0, z0, x1, z1 = x0[keep], z0[keep], x1[keep], z1[keep]
    xs, zs = cx[:, 0], cz[0, :]
    result = np.zeros(cx.shape, dtype=bool)
    crosses = (z0[None, :] > zs[:, None]) != (z1[None, :] > zs[:, None])  # [z, edge]
    x_at = x0 + (zs[:, None] - z0) * (x1 - x0) / (z1 - z0)
    for j in np.flatnonzero(crosses.any(axis=1)):
        hits = np.sort(x_at[j][crosses[j]])
        right = len(hits) - np.searchsorted(hits, xs, side="right")  # crossings with x_at > x
        result[:, j] = right % 2 == 1
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


CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
DIRS: tuple[tuple[Direction, int, int], ...] = (("east", 1, 0), ("west", -1, 0), ("south", 0, 1), ("north", 0, -1))
NO_CELLS = np.zeros((0, 3), np.int64)


@dataclass
class LoftCells:
    """A loft's cells by role (disjoint), as (N, 3) arrays of world (x, y, z)."""

    walls: np.ndarray = field(default_factory=lambda: NO_CELLS)
    floors: np.ndarray = field(default_factory=lambda: NO_CELLS)
    mullions: np.ndarray = field(default_factory=lambda: NO_CELLS)
    lights: np.ndarray = field(default_factory=lambda: NO_CELLS)
    steps: np.ndarray = field(default_factory=lambda: NO_CELLS)  # stairs ...
    step_dir: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))  # ... ascending DIRS[i] ...
    step_down: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))  # ... upside down


def _steps(solid: np.ndarray, x: np.ndarray, y: np.ndarray, z: np.ndarray, dy: int) -> tuple[np.ndarray, np.ndarray]:
    """For cells (x, y, z) of ``solid`` (padded by one empty level above and below): whether the face toward
    ``dy`` is open while the surface continues one level over on a side, and that side (index into DIRS: the one
    with the most solid cells over it among the 3 cells on that side; the first on a tie)."""
    yy = y + dy
    scores = np.zeros((len(x), len(DIRS)), np.int64)
    for k, (_, ddx, ddz) in enumerate(DIRS):
        n = sum(solid[x + ddx + p * abs(ddz), yy, z + ddz + p * abs(ddx)].astype(np.int64) for p in (-1, 0, 1))
        scores[:, k] = np.where(solid[x + ddx, yy, z + ddz], n, 0)
    return ~solid[x, yy, z] & (scores.max(axis=1) > 0), scores.argmax(axis=1)


def loft_cells(op: Loft) -> LoftCells:
    smooth = op.interp == "smooth"
    y0, y1 = op.keys[0].y, op.keys[-1].y
    keys = {y: key_at(op.keys, y, smooth) for y in range(y0, y1 + 1)}
    outer = np.concatenate([_transform(shape_points(op.profile.outer), k, op.pivot) for k in keys.values()])
    lo = np.floor(outer.min(axis=0)).astype(int) - 2
    hi = np.ceil(outer.max(axis=0)).astype(int) + 2
    origin, size = (int(lo[0]), int(lo[1])), (int(hi[0] - lo[0] + 1), int(hi[1] - lo[1] + 1))
    kernel = np.ones((3, 3), np.uint8)
    solid = np.zeros((size[0], len(keys) + 2, size[1]), bool)  # the profile at each level (+1), for smoothing
    parts: dict[str, list[np.ndarray]] = {"walls": [], "floors": [], "mullions": [], "lights": []}

    def add(role: str, cells: np.ndarray, y: int) -> None:
        xz = np.argwhere(cells)
        parts[role].append(np.column_stack([xz[:, 0] + origin[0], np.full(len(xz), y), xz[:, 1] + origin[1]]))

    for i, (y, key) in enumerate(keys.items()):
        mask = profile_mask(op.profile, key, op.pivot, origin, size)
        solid[:, i + 1, :] = mask
        is_floor = (op.floor_every is not None and (y - y0) % op.floor_every == 0) or (op.caps and y in (y0, y1))
        edge = mask & ~cv2.erode(mask.astype(np.uint8), CROSS, borderValue=0).astype(bool)  # face-adjacent to outside
        if op.fill == "shell" and not is_floor:
            inner = cv2.erode(mask.astype(np.uint8), kernel, iterations=op.thickness, borderValue=0).astype(bool)
            layer = mask & ~inner
        else:
            layer = mask
        lit = np.zeros_like(mask)
        if op.lights and (is_floor if op.fill == "shell" else y == y1):
            gx = (np.arange(size[0]) + origin[0]) % op.lights.every == 0
            gz = (np.arange(size[1]) + origin[1]) % op.lights.every == 0
            lit = layer & ~edge & gx[:, None] & gz[None, :]
        rib = np.zeros_like(mask)
        if op.mullions and not (is_floor and op.fill == "shell"):
            cx, cz = op.pivot[0] + key["dx"], op.pivot[1] + key["dz"]
            px, pz = np.meshgrid(np.arange(size[0]) + origin[0] + 0.5 - cx,
                                 np.arange(size[1]) + origin[1] + 0.5 - cz, indexing="ij")  # fmt: skip
            pitch = 2 * math.pi / op.mullions.count
            a = np.arctan2(pz, px) - math.radians(key["rotate"])
            off = (a + pitch / 2) % pitch - pitch / 2  # angle to the nearest rib
            rib = layer & (np.abs(np.sin(off)) * np.hypot(px, pz) <= 0.5 + 1e-9)  # within half a block of the line
        add("floors" if is_floor and op.fill == "shell" else "walls", layer & ~lit & ~rib, y)
        add("lights", lit, y)
        add("mullions", rib, y)

    out = LoftCells(**{k: np.concatenate(v) if v else NO_CELLS for k, v in parts.items()})
    if op.smooth and len(out.walls):
        wx, wy, wz = out.walls[:, 0] - origin[0], out.walls[:, 1] - y0 + 1, out.walls[:, 2] - origin[1]
        up, up_dir = _steps(solid, wx, wy, wz, 1)
        down, down_dir = _steps(solid, wx, wy, wz, -1)
        step = up | down
        out.steps, out.step_down = out.walls[step], ~up[step]
        out.step_dir = np.where(up, up_dir, down_dir)[step]
        out.walls = out.walls[~step]
    return out


def sweep_cells(op: Sweep, samples_per_block: int = 4) -> np.ndarray:
    """(N, 3) cells within ``radius`` of the curve."""
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
    cand = np.floor(samples).astype(np.int64)[:, None, :] + grid[None, :, :]  # [sample, offset, xyz]
    near = np.linalg.norm(cand + 0.5 - samples[:, None, :], axis=2) <= r
    return np.unique(cand[near], axis=0)
