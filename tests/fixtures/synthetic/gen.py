"""Synthetic facade photos with exact ground truth (SOW §8.2).

``render_facade`` paints a front-on facade from element boxes (the BuildSpec convention: normalized over the
wall, eaves = 0, ground = 1) with flat colors plus a roof band above; ``photograph`` warps it into a larger
"photo" with a known homography, then adds sky, noise and vignetting. The true facade corners in the photo
are returned for rectification tests.
"""

from __future__ import annotations

import cv2
import numpy as np


def render_facade(
    elements: list[dict], wall=(150, 97, 83), window=(40, 55, 70), door=(70, 45, 30), roof=(60, 45, 35),
    size=(600, 400), roof_frac=0.25,
) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """Returns (image with a roof band on top, wall-only image). ``size`` = wall (width, height) in px."""
    w, h = size
    rh = int(h * roof_frac)
    img = np.zeros((h + rh, w, 3), np.uint8)
    img[:rh] = roof
    img[rh:] = wall
    for e in elements:
        x0, y0, x1, y1 = e["bbox"]
        color = window if e["kind"] == "window" else door
        img[rh + int(y0 * h) : rh + int(y1 * h), int(x0 * w) : int(x1 * w)] = color
    return img, img[rh:].copy()


def photograph(facade: np.ndarray, roof_px: int, seed: int = 0, noise: float = 4.0):  # type: ignore[no-untyped-def]
    """Warp ``facade`` into a 1400 x 1000 photo with a random perspective. Returns (photo, true wall corners
    TL/TR/BR/BL in photo pixels, homography from the facade's wall frame to the photo)."""
    rng = np.random.default_rng(seed)
    fh, fw = facade.shape[:2]
    src = np.float32([(0, 0), (fw - 1, 0), (fw - 1, fh - 1), (0, fh - 1)])
    base = np.float32([(300, 150), (1100, 150), (1100, 850), (300, 850)])
    dst = (base + rng.uniform(-90, 90, size=(4, 2))).astype(np.float32)
    hmat = cv2.getPerspectiveTransform(src, dst)
    photo = np.full((1000, 1400, 3), (170, 200, 225), np.uint8)  # sky
    warped = cv2.warpPerspective(facade, hmat, (1400, 1000))
    mask = cv2.warpPerspective(np.full((fh, fw), 255, np.uint8), hmat, (1400, 1000)) > 0
    photo[mask] = warped[mask]
    photo = photo.astype(np.float64) + rng.normal(0, noise, photo.shape)
    yy, xx = np.mgrid[0:1000, 0:1400]
    vignette = 1 - 0.15 * (((xx - 700) / 700) ** 2 + ((yy - 500) / 500) ** 2)
    photo = np.clip(photo * vignette[..., None], 0, 255).astype(np.uint8)
    wall_src = np.float32([(0, roof_px), (fw - 1, roof_px), (fw - 1, fh - 1), (0, fh - 1)])
    corners = cv2.perspectiveTransform(wall_src[None], hmat)[0]
    return photo, [(float(x), float(y)) for x, y in corners], hmat
