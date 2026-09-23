"""LEB128-style varints as used by Sponge schematics (7 bits per byte, 0x80 continuation)."""

from __future__ import annotations

import numpy as np


def encode_varints(values: np.ndarray) -> bytes:
    flat = np.asarray(values).reshape(-1)
    if flat.size == 0:
        return b""
    if int(flat.min()) < 0:
        raise ValueError("varints must be non-negative")
    if int(flat.max()) < 0x80:  # fast path: one byte per value
        return flat.astype(np.uint8).tobytes()
    out = bytearray()
    for v in flat.tolist():
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80)
            v >>= 7
        out.append(v)
    return bytes(out)


def decode_varints(buf: bytes, n: int) -> np.ndarray:
    """Decode exactly ``n`` varints; raises ValueError on truncated or over-long data."""
    arr = np.frombuffer(buf, dtype=np.uint8)
    if len(arr) == n and (n == 0 or int(arr.max()) < 0x80):  # fast path
        return arr.astype(np.int32)
    out = np.empty(n, dtype=np.int32)
    i = 0
    for k in range(n):
        v = 0
        shift = 0
        while True:
            if i >= len(arr):
                raise ValueError(f"varint data truncated after {k} of {n} values")
            b = int(arr[i])
            i += 1
            v |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
            if shift > 28:
                raise ValueError("varint longer than 5 bytes")
        out[k] = v
    if i != len(arr):
        raise ValueError(f"{len(arr) - i} trailing bytes after {n} varints")
    return out
