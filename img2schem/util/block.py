"""Minecraft 1.7.10 blocks: a registry name plus a 0-15 metadata value, written ``name@meta``.

Registry names come from Forge's block registry and may contain upper case, dots and inner spaces
(``IC2:blockMachine``, ``gregtech:gt.blockcasings``, ``Natura:Rare Tree``). ``@0`` may be omitted.
"""

from __future__ import annotations

import re

_BLOCK_RE = re.compile(r"^(?P<name>[^:@\s]+:[^@\s](?:[^@]*[^@\s])??)(?:@(?P<meta>\d+))?$")


def parse_block(block: str) -> tuple[str, int]:
    """``"minecraft:wool@14"`` -> ``("minecraft:wool", 14)``; raises ValueError if malformed."""
    m = _BLOCK_RE.match(block)
    if not m:
        raise ValueError(f"malformed block: {block!r} (expected modid:name or modid:name@meta)")
    meta = int(m.group("meta") or 0)
    if meta > 15:
        raise ValueError(f"metadata {meta} out of range 0-15 in {block!r}")
    return m.group("name"), meta


def format_block(name: str, meta: int = 0) -> str:
    return name if meta == 0 else f"{name}@{meta}"


def namespace(block: str) -> str:
    return block.split(":", 1)[0]
