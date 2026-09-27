"""Materials from a photo (SOW §6.4 RM.1-RM.3, R2.4, R2.12): region colors -> ranked palette blocks.

Regions on the rectified facade follow the spec's element boxes (normalized over the wall): wall = the whole
wall minus every element box (padded), window/door = the inner part of their boxes (frames excluded), base =
the bottom strip of the wall (only when the spec has a ``base`` role). The roof is not in the rectified wall
image, so its region is an optional box on image.png. Each region's color is the median in CIELAB; regions
under 50 px or with median L* < 20 (deep shadow) are unreliable and fall back to the spec's ``rgb`` hint.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from img2schem.models import BuildSpec, MaterialSpec
from img2schem.palette.query import PaletteIndex
from img2schem.util.color import ciede2000, linear_to_srgb, srgb_to_lab

ROLE_TO_MATCH = {"wall": "wall", "roof": "roof", "trim": "trim", "base": "base", "window": "glass", "door": "door"}
MIN_PIXELS = 50
MIN_L = 20.0
CONTRAST_MIN_DE = 8.0  # RM.3
# Windows photograph dark because of the room behind them; only a clearly tinted color picks tinted glass.
WINDOW_MIN_CHROMA = 15.0


@dataclass
class Region:
    role: str
    lab: tuple[float, float, float] | None
    pixels: int
    reliable: bool


def _median_lab(pixels: np.ndarray) -> tuple[float, float, float]:
    lab = np.median(srgb_to_lab(pixels.reshape(-1, 3)), axis=0)
    return float(lab[0]), float(lab[1]), float(lab[2])


def lab_to_srgb(lab: tuple[float, float, float]) -> tuple[int, int, int]:
    L, a, b = lab
    fy = (L + 16) / 116
    f = np.array([fy + a / 500, fy, fy - b / 200])
    xyz = np.where(f > 6 / 29, f**3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * np.array([0.95047, 1.0, 1.08883])
    m_inv = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                      [0.0556434, -0.2040259, 1.0572252]])  # fmt: skip
    rgb = linear_to_srgb(m_inv @ xyz)
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def _box_mask(shape: tuple[int, int], box: tuple[float, float, float, float], shrink: float = 0.0) -> np.ndarray:
    """Normalized [x0, y0, x1, y1] -> boolean mask; ``shrink`` trims that fraction off every side."""
    h, w = shape
    x0, y0, x1, y1 = box
    dx, dy = (x1 - x0) * shrink, (y1 - y0) * shrink
    m = np.zeros(shape, dtype=bool)
    m[int((y0 + dy) * h) : max(int((y0 + dy) * h) + 1, int((y1 - dy) * h)),
      int((x0 + dx) * w) : max(int((x0 + dx) * w) + 1, int((x1 - dx) * w))] = True  # fmt: skip
    return m


def region_colors(wall_img: np.ndarray, spec: BuildSpec, roof_img: np.ndarray | None = None) -> dict[str, Region]:
    """``wall_img``: the rectified facade (H x W x 3). ``roof_img``: pixels of the roof region, if marked."""
    h, w = wall_img.shape[:2]
    front = [e for e in spec.elements if e.face == "front"]
    masks: dict[str, np.ndarray] = {}
    elements = np.zeros((h, w), dtype=bool)
    for e in front:
        x0, y0, x1, y1 = e.bbox
        pad = 0.01
        elements |= _box_mask((h, w), (max(0, x0 - pad), max(0, y0 - pad), min(1, x1 + pad), min(1, y1 + pad)))
    masks["wall"] = ~elements
    if "base" in spec.materials:
        base = np.zeros((h, w), dtype=bool)
        base[int(0.94 * h) :, :] = True
        masks["base"] = base & ~elements
        masks["wall"] &= ~base
    for role, kind in (("window", "window"), ("door", "door")):
        m = np.zeros((h, w), dtype=bool)
        for e in front:
            if e.kind == kind:
                m |= _box_mask((h, w), e.bbox, shrink=0.2)
        if m.any():
            masks[role] = m
    out: dict[str, Region] = {}
    for role, m in masks.items():
        px = wall_img[m]
        lab = _median_lab(px) if len(px) else None
        out[role] = Region(role, lab, len(px), bool(lab and len(px) >= MIN_PIXELS and lab[0] >= MIN_L))
    if roof_img is not None and roof_img.size:  # marked by the owner, so no shadow test: dark roofs are common
        lab = _median_lab(roof_img)
        n = roof_img.shape[0] * roof_img.shape[1]
        out["roof"] = Region("roof", lab, n, n >= MIN_PIXELS)
    return out


def apply_materials(
    spec: BuildSpec, regions: dict[str, Region], index: PaletteIndex, replace: bool = False
) -> list[str]:
    """Fill ``spec.materials[role]`` rgb/candidates/chosen (R2.12); returns notes for the owner."""
    notes: list[str] = []
    roles = list(regions) + [r for r in spec.materials if r not in regions and r in ROLE_TO_MATCH]
    for role in roles:
        region = regions.get(role)
        m = spec.materials.setdefault(role, MaterialSpec())
        lab = region.lab if region and region.reliable else None
        where = f"photo region unreliable ({region.pixels} px)" if region else "no photo region"
        if lab is None and m.rgb:
            lab = tuple(float(v) for v in srgb_to_lab(np.array(m.rgb)))  # type: ignore[assignment]
            notes.append(f"{role}: {where}; used the rgb hint instead (R2.4)")
        if lab is None:
            hint = " (mark it with --roof-box)" if role == "roof" else ""
            notes.append(f"{role}: {where} and no rgb hint{hint}; skipped")
            continue
        m.rgb = lab_to_srgb(lab)
        ranked = index.match(lab, ROLE_TO_MATCH[role], n=8)
        m.candidates = [str(r["block"]) for r in ranked]
        if role == "window" and float(np.hypot(lab[1], lab[2])) < WINDOW_MIN_CHROMA:
            notes.append("window: the photo color is neutral (the room behind the glass); keeping clear glass")
            continue
        if ranked and (replace or not m.chosen):
            m.chosen = m.candidates[0]
    wall, trim = spec.materials.get("wall"), spec.materials.get("trim")
    if wall and trim and wall.chosen and trim.chosen and trim.candidates:  # RM.3 contrast guard

        def lab_of(block: str) -> np.ndarray | None:
            hit = index.usable(block)
            c = index.color_lab(hit[1]) if hit else None
            return np.array(c) if c else None

        wl = lab_of(wall.chosen)
        tl = lab_of(trim.chosen)
        if wl is not None and tl is not None and float(ciede2000(wl, tl)) < CONTRAST_MIN_DE:
            for cand in trim.candidates:
                cl = lab_of(cand)
                if cl is not None and float(ciede2000(wl, cl)) >= CONTRAST_MIN_DE:
                    notes.append(f"trim: {trim.chosen} was too close to the wall; using {cand} (RM.3)")
                    trim.chosen = cand
                    break
    return notes
