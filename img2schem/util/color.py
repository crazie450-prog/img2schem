"""Color math: sRGB <-> linear, CIELAB (D65), and average colors of icons."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(c, dtype=np.float64), 0, 1)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return np.round(s * 255).astype(np.int64)


_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """``[..., 3]`` sRGB 0-255 -> ``[..., 3]`` CIELAB (D65)."""
    xyz = srgb_to_linear(rgb) @ _M.T / _WHITE
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def icon_color(path: Path) -> tuple[tuple[int, int, int], float]:
    """Average sRGB color of an icon's opaque pixels (averaged in linear light), and its transparent fraction."""
    px = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64).reshape(-1, 4)
    opaque = px[px[:, 3] >= 128]
    alpha = 1 - len(opaque) / len(px)
    if len(opaque) == 0:
        return (0, 0, 0), 1.0
    mean = linear_to_srgb(srgb_to_linear(opaque[:, :3]).mean(axis=0))
    return (int(mean[0]), int(mean[1]), int(mean[2])), float(alpha)


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# Top (fully lit) face of NEI's isometric 16x16 cube icon, read off the owner's quartz icon: widest at row 3,
# two columns narrower per row above and below.
_TOP_FACE_ROWS = {0: (7, 8), 1: (5, 10), 2: (3, 12), 3: (1, 14), 4: (3, 12), 5: (5, 10), 6: (7, 8)}


def top_face_mask() -> np.ndarray:
    m = np.zeros((16, 16), dtype=bool)
    for r, (c0, c1) in _TOP_FACE_ROWS.items():
        m[r, c0 : c1 + 1] = True
    return m


def icon_face(path: Path) -> tuple[tuple[int, int, int], float] | None:
    """(true texture color, variance) from a cube icon's lit top face: the mean in linear light, and the mean
    CIE76 distance of its pixels from that mean (busy textures read as noise at a distance). None if too few
    opaque pixels."""
    px = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float64)
    if px.shape[:2] != (16, 16):
        return None
    face = px[top_face_mask() & (px[..., 3] >= 128)][:, :3]
    if len(face) < 30:
        return None
    mean = linear_to_srgb(srgb_to_linear(face).mean(axis=0))
    rgb = (int(mean[0]), int(mean[1]), int(mean[2]))
    variance = float(np.linalg.norm(srgb_to_lab(face) - srgb_to_lab(np.array(rgb)), axis=1).mean())
    return rgb, variance


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 color difference (Sharma, Wu & Dalal 2005), vectorized over the last axis."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, dtype=np.float64), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, dtype=np.float64), -1, 0)
    c_bar = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_bar**7 / (c_bar**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dl = L2 - L1
    dc = c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0, dh)
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    l_bar = (L1 + L2) / 2
    cp_bar = (c1p + c2p) / 2
    hsum = h1p + h2p
    h_bar = np.where(
        c1p * c2p == 0,
        hsum,
        np.where(np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)),
    )
    t = (1 - 0.17 * np.cos(np.radians(h_bar - 30)) + 0.24 * np.cos(np.radians(2 * h_bar))
         + 0.32 * np.cos(np.radians(3 * h_bar + 6)) - 0.20 * np.cos(np.radians(4 * h_bar - 63)))  # fmt: skip
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * cp_bar
    s_h = 1 + 0.015 * cp_bar * t
    r_t = (
        -2 * np.sqrt(cp_bar**7 / (cp_bar**7 + 25.0**7)) * np.sin(np.radians(60 * np.exp(-(((h_bar - 275) / 25) ** 2))))
    )
    return np.sqrt((dl / s_l) ** 2 + (dc / s_c) ** 2 + (dH / s_h) ** 2 + r_t * (dc / s_c) * (dH / s_h))
