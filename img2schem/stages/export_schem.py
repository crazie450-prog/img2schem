"""S7: MCEdit ``.schematic`` writer/reader for GTNH's WorldEdit 6.3.0 (Minecraft 1.7.10).

Layout, as read from the WorldEdit 6.3.0 jar shipped with GTNH (``SchematicReader``/``SchematicWriter``,
``util/serialization``):
- root compound named ``Schematic``: ``Width/Height/Length`` (short), ``Materials = "Alpha"``,
  ``Blocks`` (low 8 bits of each ID), ``Data`` (metadata), optional ``AddBlocks`` (high 4 bits, two per
  byte), ``Entities``, ``TileEntities``, ``WEOriginX/Y/Z`` and ``WEOffsetX/Y/Z`` (int);
- cell index ``x + z*Width + y*Width*Length`` (x fastest, then z, then y);
- ``SchematicaMapping`` (name -> ID compound): IDs in the file are local to the file and WorldEdit remaps
  each name to the loading world's ID (unknown names become air, with a warning). With this tag present,
  ``AddBlocks`` uses Schematica's nibble order: even cells in the HIGH nibble, odd cells in the low one.

We always write ``SchematicaMapping`` with local IDs (air = 0, then 1..N in palette order), so files never
depend on a particular world's numeric IDs.
"""

from __future__ import annotations

import gzip
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbtlib
import numpy as np
from nbtlib import ByteArray, Compound, File, Int, List, Short, String

from img2schem import __version__
from img2schem.models import AIR, BlockGrid
from img2schem.util.block import format_block, namespace, parse_block

MAX_DIM = 32767  # NBT shorts are signed
MAX_LOCAL_ID = 4095  # 12 bits: Blocks + AddBlocks


def front_center_offset(width: int) -> tuple[int, int, int]:
    """Paste so the bottom-center of the front facade (z = 0) lands 2 blocks south of the player, with the
    build's bottom layer replacing the block the player stands on (§4.3, owner decision D-015).

    WorldEdit sets the clipboard origin to ``min - WEOffset``, so ``//paste`` puts the min corner at
    ``player + WEOffset`` (verified in game, docs/TEST_BED.md). Change here only.
    """
    return (-(width // 2), -1, 2)


def mods_required(palette: list[str]) -> list[str]:
    return sorted({namespace(b) for b in palette if b != AIR} - {"minecraft"})


@dataclass
class SchemMeta:
    name: str = "building"
    instance_name: str | None = None
    mc_version: str | None = None
    loader: str | None = None


@dataclass
class SchemInfo:
    """What the reader recovered besides the grid."""

    offset: tuple[int, int, int] | None
    origin: tuple[int, int, int] | None
    mapped: bool  # names came from SchematicaMapping/IDMap (else placeholders "id:<n>")
    tile_entities: int = 0
    entities: int = 0
    img2schem: dict[str, Any] = field(default_factory=dict)


def _signed(a: np.ndarray) -> ByteArray:
    return ByteArray(a.astype(np.uint8).view(np.int8))  # NBT bytes are signed


def write_schematic(
    path: Path,
    grid: BlockGrid,
    *,
    offset: tuple[int, int, int] | None = None,
    meta: SchemMeta | None = None,
) -> Path:
    grid = grid.compact()
    w, h, length = grid.shape
    if max(w, h, length) > MAX_DIM:
        raise ValueError(f"dimensions {grid.shape} exceed {MAX_DIM}")
    offset = offset or front_center_offset(w)
    meta = meta or SchemMeta()

    # Palette entry -> (local id, metadata). Local ids follow first appearance in the palette.
    local_ids: dict[str, int] = {AIR: 0}
    pal_id = np.zeros(len(grid.palette), dtype=np.int32)
    pal_meta = np.zeros(len(grid.palette), dtype=np.int32)
    for i, block in enumerate(grid.palette):
        name, m = parse_block(block)
        pal_id[i] = local_ids.setdefault(name, len(local_ids))
        pal_meta[i] = m
    if len(local_ids) - 1 > MAX_LOCAL_ID:
        raise ValueError(f"{len(local_ids) - 1} distinct blocks exceed the format's {MAX_LOCAL_ID}")

    flat = np.transpose(grid.idx, (1, 2, 0)).reshape(-1)  # [Y, Z, X] -> x fastest, then z, then y
    ids = pal_id[flat]
    root: dict[str, Any] = {
        "Width": Short(w),
        "Height": Short(h),
        "Length": Short(length),
        "Materials": String("Alpha"),
        "Blocks": _signed(ids & 0xFF),
        "Data": _signed(pal_meta[flat]),
    }
    if int(ids.max(initial=0)) > 0xFF:
        high = (ids >> 8) & 0xF
        n = len(high)
        add = np.zeros((n >> 1) + 1, dtype=np.uint8)
        add[: (n + 1) // 2] |= (high[0::2] << 4).astype(np.uint8)  # even cells: high nibble (Schematica order)
        add[: n // 2] |= high[1::2].astype(np.uint8)  # odd cells: low nibble
        root["AddBlocks"] = _signed(add)
    root["SchematicaMapping"] = Compound({name: Int(i) for name, i in local_ids.items() if name != AIR})
    root["Entities"] = List[Compound]([])
    root["TileEntities"] = List[Compound]([])
    for axis, value in zip("XYZ", offset, strict=True):
        root[f"WEOrigin{axis}"] = Int(0)
        root[f"WEOffset{axis}"] = Int(value)
    root["img2schem"] = Compound(
        {
            "Version": String(__version__),
            "Name": String(meta.name),
            "Instance": String(meta.instance_name or ""),
            "MinecraftVersion": String(meta.mc_version or ""),
            "Loader": String(meta.loader or ""),
            "ModsRequired": List[String]([String(m) for m in mods_required(grid.palette)]),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 and no file name keep the gzip header stable, so identical grids give identical bytes (S5).
    with path.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        File(Compound(root), root_name="Schematic").write(gz)
    return path


def _to_py(tag: Any) -> Any:
    if isinstance(tag, Compound):
        return {k: _to_py(v) for k, v in tag.items()}
    if isinstance(tag, list):
        return [_to_py(v) for v in tag]
    if isinstance(tag, str):
        return str(tag)
    if isinstance(tag, int):
        return int(tag)
    return tag


def read_schematic(path: Path) -> tuple[BlockGrid, SchemInfo]:
    """Parse an MCEdit/WorldEdit ``.schematic``. Raises ValueError on bad data."""
    root = nbtlib.load(str(path))
    if str(root.get("Materials", "Alpha")) != "Alpha":
        raise ValueError(f"unsupported Materials {root['Materials']!r} (only Alpha)")
    w, h, length = (int(root[k]) & 0xFFFF for k in ("Width", "Height", "Length"))
    n = w * h * length
    blocks = np.asarray(root["Blocks"], dtype=np.int8).view(np.uint8).astype(np.int32)
    data = np.asarray(root["Data"], dtype=np.int8).view(np.uint8).astype(np.int32)
    if len(blocks) != n or len(data) != n:
        raise ValueError(f"Blocks/Data length {len(blocks)}/{len(data)} != Width*Height*Length {n}")

    mapping_key = "IDMap" if "IDMap" in root else "SchematicaMapping" if "SchematicaMapping" in root else None
    add_key = "Add" if "Add" in root else "AddBlocks" if "AddBlocks" in root else None
    ids = blocks
    if add_key:
        add = np.asarray(root[add_key], dtype=np.int8).view(np.uint8).astype(np.int32)
        if len(add) < (n + 1) // 2:
            raise ValueError(f"{add_key} too short for {n} cells")
        k = np.arange(n)
        byte = add[k >> 1]
        even = (k & 1) == 0
        friendly = mapping_key is not None  # WorldEdit uses Schematica's nibble order when a mapping exists
        high = np.where(even == friendly, byte >> 4, byte & 0xF)
        ids = ids | (high << 8)

    names: dict[int, str] = {0: AIR}
    if mapping_key:
        for name, v in root[mapping_key].items():
            names[int(v) & 0xFFFF] = str(name)

    cells = ids * 16 + (data & 0xF)
    uniq, inv = np.unique(cells, return_inverse=True)
    palette = [AIR]
    remap = np.zeros(len(uniq), dtype=np.int32)  # unique cell value -> palette index (air of any meta -> 0)
    for i, c in enumerate(uniq.tolist()):
        block_id, m = divmod(int(c), 16)
        name = names.get(block_id, f"id:{block_id}")
        if name != AIR:
            palette.append(format_block(name, m))
            remap[i] = len(palette) - 1
    idx = np.transpose(remap[inv.reshape(-1)].reshape(h, length, w), (2, 0, 1))  # -> [X, Y, Z]
    grid = BlockGrid(idx, palette)

    def vec(prefix: str) -> tuple[int, int, int] | None:
        keys = [f"{prefix}{a}" for a in "XYZ"]
        return (int(root[keys[0]]), int(root[keys[1]]), int(root[keys[2]])) if all(k in root for k in keys) else None

    info = SchemInfo(
        offset=vec("WEOffset"),
        origin=vec("WEOrigin"),
        mapped=mapping_key is not None,
        tile_entities=len(root.get("TileEntities", [])),
        entities=len(root.get("Entities", [])),
        img2schem=_to_py(root.get("img2schem", Compound())),
    )
    return grid, info


def copy_to_schematics_dir(schem: Path, schematics_dir: Path) -> Path:
    """R8.10: copy into WorldEdit's folder, never overwriting (append _2, _3, ...)."""
    schematics_dir.mkdir(parents=True, exist_ok=True)
    target = schematics_dir / schem.name
    n = 2
    while target.exists():
        target = schematics_dir / f"{schem.stem}_{n}{schem.suffix}"
        n += 1
    shutil.copy2(schem, target)
    return target
