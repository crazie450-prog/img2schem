"""S7: Sponge schematic writer (v2 default, v3 by flag) and reader (v1/v2/v3). SOW §6.10.

Block data order is ``x + z*Width + y*Width*Length`` (x fastest, then z, then y), varint-encoded.
"""

from __future__ import annotations

import gzip
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nbtlib
import numpy as np
from nbtlib import ByteArray, Compound, File, Int, IntArray, List, Long, Short, String

from img2schem import __version__
from img2schem.models import AIR, BlockGrid
from img2schem.util.blockstate import namespace
from img2schem.util.varint import decode_varints, encode_varints

MAX_DIM = 32767  # NBT shorts are signed (R8.6)


def front_center_offset(width: int) -> tuple[int, int, int]:
    """Paste so the bottom-center of the front facade (z = 0) lands 2 blocks south of the player (§4.3).

    WorldEdit places the region's min corner at ``player + offset``. To be verified on each test bed
    (docs/TEST_BED.md); change here only.
    """
    return (-(width // 2), 0, 2)


def mods_required(palette: list[str]) -> list[str]:
    return sorted({namespace(s) for s in palette if s != AIR} - {"minecraft"})


@dataclass
class SchemMeta:
    name: str = "building"
    author: str = "img2schem"
    instance_name: str | None = None
    mc_version: str | None = None
    loader: str | None = None
    date_ms: int | None = None  # None -> now; pin it for byte-identical output (S5)


@dataclass
class SchemInfo:
    """What the reader recovered besides the grid."""

    version: int
    data_version: int | None
    offset: tuple[int, int, int]
    we_offset: tuple[int, int, int] | None
    metadata: dict[str, Any] = field(default_factory=dict)
    block_entities: int = 0


def _block_data(grid: BlockGrid) -> ByteArray:
    flat = np.transpose(grid.idx, (1, 2, 0)).reshape(-1)  # [Y, Z, X] -> x fastest, then z, then y
    data = encode_varints(flat)
    return ByteArray(np.frombuffer(data, dtype=np.int8))  # NBT bytes are signed (R8.3)


def write_schem(
    path: Path,
    grid: BlockGrid,
    data_version: int,
    *,
    schem_version: int = 2,
    offset: tuple[int, int, int] | None = None,
    meta: SchemMeta | None = None,
) -> Path:
    grid = grid.compact()
    w, h, length = grid.shape
    if max(w, h, length) > MAX_DIM:
        raise ValueError(f"dimensions {grid.shape} exceed {MAX_DIM}")
    if offset is None:
        offset = front_center_offset(w)
    meta = meta or SchemMeta()
    img2schem_meta = Compound(
        {
            "Version": String(__version__),
            "Instance": String(meta.instance_name or ""),
            "MinecraftVersion": String(meta.mc_version or ""),
            "Loader": String(meta.loader or ""),
            "ModsRequired": List[String]([String(m) for m in mods_required(grid.palette)]),
        }
    )
    common_meta = {
        "Name": String(meta.name),
        "Author": String(meta.author),
        "Date": Long(meta.date_ms if meta.date_ms is not None else int(time.time() * 1000)),
        "img2schem": img2schem_meta,
    }
    palette = Compound({s: Int(i) for i, s in enumerate(grid.palette)})
    offset_arr = IntArray(np.array(offset, dtype=np.int32))
    dims = {"Width": Short(w), "Height": Short(h), "Length": Short(length)}

    if schem_version == 2:
        root = Compound(
            {
                "Version": Int(2),
                "DataVersion": Int(data_version),
                **dims,
                "Offset": offset_arr,
                "PaletteMax": Int(len(grid.palette)),
                "Palette": palette,
                "BlockData": _block_data(grid),
                "BlockEntities": List[Compound]([]),
                "Metadata": Compound(
                    {
                        "WEOffsetX": Int(offset[0]),
                        "WEOffsetY": Int(offset[1]),
                        "WEOffsetZ": Int(offset[2]),
                        **common_meta,
                    }
                ),
            }
        )
        f = File(root, root_name="Schematic")
    elif schem_version == 3:
        body = Compound(
            {
                "Version": Int(3),
                "DataVersion": Int(data_version),
                **dims,
                "Offset": offset_arr,
                "Blocks": Compound(
                    {"Palette": palette, "Data": _block_data(grid), "BlockEntities": List[Compound]([])}
                ),
                "Metadata": Compound(common_meta),
            }
        )
        f = File({"Schematic": body}, root_name="")
    else:
        raise ValueError(f"unsupported schem version {schem_version}")
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the gzip header stable so identical grids give identical bytes (S5).
    with path.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        f.write(gz)
    return path


def _to_py(tag: Any) -> Any:
    if isinstance(tag, Compound):
        return {k: _to_py(v) for k, v in tag.items()}
    if isinstance(tag, list):
        return [_to_py(v) for v in tag]
    if isinstance(tag, np.ndarray):
        return tag.tolist()
    if isinstance(tag, str):
        return str(tag)
    if isinstance(tag, int):
        return int(tag)
    if isinstance(tag, float):
        return float(tag)
    return tag


def read_schem(path: Path) -> tuple[BlockGrid, SchemInfo]:
    """Parse a Sponge v1/v2/v3 schematic into a BlockGrid (R8.7). Raises ValueError on bad data."""
    f = nbtlib.load(str(path))
    root: Compound = f["Schematic"] if isinstance(f.get("Schematic"), Compound) else f
    version = int(root.get("Version", 0))
    if version not in (1, 2, 3):
        raise ValueError(f"unsupported or missing Sponge schematic Version: {version}")
    w, h, length = (int(root[k]) & 0xFFFF for k in ("Width", "Height", "Length"))  # unsigned shorts
    if version == 3:
        blocks = root["Blocks"]
        pal_tag, data_tag = blocks["Palette"], blocks["Data"]
        be = len(blocks.get("BlockEntities", []))
    else:
        pal_tag, data_tag = root["Palette"], root["BlockData"]
        be = len(root.get("BlockEntities", root.get("TileEntities", [])))
    n_pal = max(int(v) for v in pal_tag.values()) + 1 if len(pal_tag) else 0
    palette: list[str | None] = [None] * n_pal
    for state, i in pal_tag.items():
        palette[int(i)] = str(state)
    raw = np.asarray(data_tag, dtype=np.int8).view(np.uint8).tobytes()
    flat = decode_varints(raw, w * h * length)
    if flat.size and int(flat.max()) >= n_pal:
        raise ValueError(f"block index {int(flat.max())} >= palette size {n_pal}")
    idx_yzx = flat.reshape(h, length, w)
    idx = np.transpose(idx_yzx, (2, 0, 1))  # -> [X, Y, Z]

    # Normalize so palette[0] is air (the file's own air index may be anything).
    states = [s if s is not None else f"img2schem:unused_{i}" for i, s in enumerate(palette)]
    if AIR in states:
        air_i = states.index(AIR)
        order = [air_i] + [i for i in range(n_pal) if i != air_i]
    else:
        order = list(range(n_pal))
        states = [AIR] + states
        idx = idx + 1
        order = [0] + [i + 1 for i in order]
    remap = np.empty(len(states), dtype=np.int32)
    for new, old in enumerate(order):
        remap[old] = new
    grid = BlockGrid(remap[idx], [states[i] for i in order])

    meta_tag = root.get("Metadata", Compound())
    offset_raw = root.get("Offset")
    offset = tuple(int(v) for v in offset_raw) if offset_raw is not None else (0, 0, 0)
    we_offset = None
    if "WEOffsetX" in meta_tag:
        we_offset = (int(meta_tag["WEOffsetX"]), int(meta_tag["WEOffsetY"]), int(meta_tag["WEOffsetZ"]))
    info = SchemInfo(
        version=version,
        data_version=int(root["DataVersion"]) if "DataVersion" in root else None,
        offset=(offset[0], offset[1], offset[2]),
        we_offset=we_offset,
        metadata=_to_py(meta_tag),
        block_entities=be,
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
