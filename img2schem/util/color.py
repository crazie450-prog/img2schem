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
