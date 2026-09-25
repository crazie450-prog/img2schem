"""S1 rectify (v1 R1.1-R1.3, manual corners for now): warp the facade quadrilateral to a front-on rectangle.

Corners are the facade's outer wall corners (ground to eaves) in ``image.png`` pixels, any order; they are
sorted to top-left, top-right, bottom-right, bottom-left. The rectangle's aspect comes from the facade's real
width/height when known (``aspect`` = width / height), else from the average opposite side lengths of the quad.
Without corners the whole image is used (method "none", with a warning).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

OUT_LONG_EDGE = 1024


@dataclass
class Rectified:
    image: Path
    quad: list[tuple[float, float]]  # TL, TR, BR, BL in image.png pixels
    homography: np.ndarray
    size: tuple[int, int]
    method: str


def parse_corners(text: str) -> list[tuple[float, float]]:
    """``"x,y x,y x,y x,y"`` (pixels) -> four points."""
    try:
        pts = [tuple(float(v) for v in p.split(",")) for p in text.replace(";", " ").split()]
    except ValueError:
        raise ValueError(f"corners must look like 'x,y x,y x,y x,y', got {text!r}") from None
    if len(pts) != 4 or any(len(p) != 2 for p in pts):
        raise ValueError(f"need exactly 4 corners 'x,y', got {text!r}")
    return [(p[0], p[1]) for p in pts]


def order_quad(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sort to TL, TR, BR, BL: by angle around the centroid, starting from the top-left-most point."""
    c = np.mean(pts, axis=0)
    by_angle = sorted(pts, key=lambda p: np.arctan2(p[1] - c[1], p[0] - c[0]))  # image y points down: clockwise
    start = min(range(4), key=lambda i: by_angle[i][0] + by_angle[i][1])
    return by_angle[start:] + by_angle[:start]


def rectify(
    image: Path, run_dir: Path, corners: list[tuple[float, float]] | None, aspect: float | None = None
) -> Rectified:
    src = np.asarray(Image.open(image).convert("RGB"))
    h, w = src.shape[:2]
    method = "manual" if corners else "none"
    quad = order_quad(corners) if corners else [(0.0, 0.0), (w - 1.0, 0.0), (w - 1.0, h - 1.0), (0.0, h - 1.0)]
    q = np.array(quad, dtype=np.float64)
    if aspect is None:
        width = float(np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
        height = float(np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
        aspect = width / max(height, 1e-6)
    out_w, out_h = (
        (OUT_LONG_EDGE, round(OUT_LONG_EDGE / aspect))
        if aspect >= 1
        else (round(OUT_LONG_EDGE * aspect), OUT_LONG_EDGE)
    )
    dst = np.array([(0, 0), (out_w - 1, 0), (out_w - 1, out_h - 1), (0, out_h - 1)], dtype=np.float64)
    hmat = cv2.getPerspectiveTransform(q.astype(np.float32), dst.astype(np.float32))
    warped = cv2.warpPerspective(src, hmat, (out_w, out_h), flags=cv2.INTER_AREA)

    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "rectified.png"
    Image.fromarray(warped).save(out)
    debug = Image.fromarray(src)
    draw = ImageDraw.Draw(debug)
    draw.line([*quad, quad[0]], fill=(255, 0, 180), width=max(2, w // 300))
    for (x, y), name in zip(quad, ("TL", "TR", "BR", "BL"), strict=True):
        draw.text((x + 6, y + 6), name, fill=(255, 0, 180))
    debug.save(run_dir / "debug_rectify.png")
    info = {"method": method, "quad": [list(p) for p in quad], "H": hmat.tolist(), "size": [out_w, out_h],
            "aspect": round(float(aspect), 4), "confidence": 1.0 if corners else 0.0}  # fmt: skip
    (run_dir / "rect.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return Rectified(out, quad, hmat, (out_w, out_h), method)
