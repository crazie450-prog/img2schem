"""Builds tiny fake Minecraft instances at test time (SOW §8.3). Nothing here is copied from Minecraft or
any mod: jars hold only the metadata files the detectors read."""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from pathlib import Path

import nbtlib


def _entries(files: dict[str, object]) -> dict[str, str | bytes]:
    return {k: v if isinstance(v, str | bytes) else json.dumps(v) for k, v in files.items()}


def write_jar(path: Path, files: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in _entries(files).items():
            z.writestr(name, data)
    return path


def jar_bytes(files: dict[str, object]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in _entries(files).items():
            z.writestr(name, data)
    return buf.getvalue()


def client_jar(path: Path, mc_version: str) -> Path:
    return write_jar(path, {"version.json": {"id": mc_version}})


def fabric_mod(path: Path, mod_id: str = "fabdeco") -> Path:
    return write_jar(path, {"fabric.mod.json": {"id": mod_id, "name": "Fab Deco", "version": "2.1.0"}})


def neoforge_mod(path: Path) -> Path:
    return write_jar(
        path,
        {
            "META-INF/neoforge.mods.toml": '[[mods]]\nmodId="neomasonry"\nversion="${file.jarVersion}"\n'
            'displayName="Neo Masonry"\n',
            "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 3.4.5\n",
        },
    )


def legacy_forge_mod(path: Path, mod_id: str, name: str, version: str, mod_list_v2: bool = False) -> Path:
    """A Forge 1.7.10 mod with mcmod.info (plain list, or the ``modListVersion: 2`` form)."""
    entry = {"modid": mod_id, "name": name, "version": version, "mcversion": "1.7.10"}
    info: object = {"modListVersion": 2, "modList": [entry]} if mod_list_v2 else [entry]
    return write_jar(path, {"mcmod.info": info})


def level_dat(path: Path, blocks: dict[str, int], items: dict[str, int] | None = None) -> Path:
    """A level.dat with a Forge 1.7.10 FML.ItemData registry (blocks prefixed \\u0001, items \\u0002)."""
    entries = [nbtlib.Compound({"K": nbtlib.String("\u0001" + k), "V": nbtlib.Int(v)}) for k, v in blocks.items()]
    entries += [
        nbtlib.Compound({"K": nbtlib.String("\u0002" + k), "V": nbtlib.Int(v)}) for k, v in (items or {}).items()
    ]
    root = nbtlib.Compound(
        {
            "Data": nbtlib.Compound({"LevelName": nbtlib.String(path.parent.name)}),
            "FML": nbtlib.Compound({"ItemData": nbtlib.List[nbtlib.Compound](entries)}),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as fh:
        nbtlib.File(root, root_name="").write(fh)
    return path


GTNH_BLOCKS = {
    "minecraft:stone": 1,
    "minecraft:planks": 5,
    "minecraft:glass": 20,
    "minecraft:wool": 35,
    "minecraft:gold_block": 41,
    "minecraft:brick_block": 45,
    "minecraft:oak_stairs": 53,
    "minecraft:wooden_door": 64,
    "minecraft:stonebrick": 98,
    "minecraft:glass_pane": 102,
    "minecraft:stone_brick_stairs": 109,
    "gregtech:gt.blockcasings": 1234,
    "chisel:marble": 2051,
    "chisel:marble_stairs.0": 2052,
}


def nei_dumps(root: Path) -> Path:
    """A tiny NEI dump: block.csv, itempanel.csv and itempanel_icons/ with solid-color icons."""
    from PIL import Image

    root.mkdir(parents=True, exist_ok=True)
    (root / "block.csv").write_text(
        "Name,ID,Has Item,Mod,Class,Display Name\n"
        "minecraft:air,0,false,null,net.minecraft.block.BlockAir,null\n"
        "minecraft:wool,35,true,minecraft,net.minecraft.block.BlockColored,Wool\n"
        "minecraft:stone_slab,44,true,minecraft,net.minecraft.block.BlockStoneSlab,Stone Slab\n"
        "chisel:aluminum_stairs.1,2032,true,chisel,team.chisel.block.BlockCarvableStairs,Aluminum Stairs\n"
        "malisisdoors:jungleFenceGate,3000,true,malisisdoors,net.malisis.doors.block.FenceGate,Jungle Fence Gate\n"
        "modernmarkings:wall_arrow,3001,true,modernmarkings,x.MarkingWall,Arrow\n"
        "Automagy:crystalBrain,3002,true,Automagy,x.BlockCrystalBrain,Crystalline Brain\n"
        "gregtech:gt.blockmachines,3003,true,gregtech,gregtech.api.BaseMetaTileEntityBlock,Machine\n"
        "ExtraUtilities:colorStoneBrick,3004,true,ExtraUtilities,x.BlockColor,Colored Stone Bricks\n"
        "Railcraft:machine.alpha,3005,true,Railcraft,x.BlockMachine,World Anchor\n"
        "minecraft:stonebrick,98,true,minecraft,net.minecraft.block.BlockStoneBrick,Stone Bricks\n"
        "minecraft:monster_egg,97,true,minecraft,net.minecraft.block.BlockSilverfish,Stone Monster Egg\n"
        "Ztones:tile.iszm,3006,true,Ztones,x.BlockIszm,Iszm\n",
        encoding="utf-8",
    )
    (root / "itempanel.csv").write_text(
        "Item Name,Item ID,Item meta,Has NBT,Display Name\n"
        "minecraft:wool,35,0,false,White Wool\n"
        "minecraft:wool,35,14,false,Red Wool\n"
        "minecraft:stone_slab,44,0,false,Stone Slab\n"
        "minecraft:stone_slab,44,1,false,Sandstone Slab\n"
        "GalacticraftAmunRa:tile.alucrate.stairs,1284,0,false,Aluminum Stairs\n"
        "chisel:aluminum_stairs.1,2032,0,false,Aluminum Stairs\n"
        "chisel:aluminum_stairs.1,2032,8,false,Aluminum Stairs\n"
        "Automagy:crystalBrain,3002,0,false,Crystalline Brain: Air\n"
        "gregtech:gt.blockmachines,3003,1,false,Machine\n"
        "gregtech:gt.blockmachines,3003,2,false,Machine\n"
        "gregtech:gt.blockmachines,3003,1086,false,Big Meta\n"
        "minecraft:wool,35,5,true,White Wool\n"
        "ExtraUtilities:colorStoneBrick,3004,0,false,Colored Stone Bricks (White)\n"
        "Railcraft:machine.alpha,3005,0,false,World Anchor\n"
        "minecraft:stonebrick,98,0,false,Stone Bricks\n"
        "minecraft:monster_egg,97,2,false,Infested Stone Bricks\n"
        "minecraft:monster_egg,97,5,false,Infested Chiseled Quartz\n"
        "Ztones:tile.iszm,3006,8,false,Iszm \u2467\n",
        encoding="utf-8",
    )
    icons = root / "itempanel_icons"
    icons.mkdir(exist_ok=True)
    colors = {
        "White Wool.png": (240, 240, 240),
        "White Wool_2.png": (0, 0, 0),  # the NBT row's icon
        "Red Wool.png": (160, 40, 35),
        "Stone Slab.png": (160, 160, 160),
        "Sandstone Slab.png": (215, 205, 150),
        "Aluminum Stairs.png": (10, 200, 10),  # Galacticraft's (first row)
        "Aluminum Stairs_2.png": (130, 130, 130),
        "Aluminum Stairs_3.png": (110, 110, 110),
        "Crystalline Brain_ Air.png": (5, 5, 5),
        "Machine.png": (1, 2, 3),  # 2 rows but 1 icon: ambiguous -> no color
    }
    for name, rgb in colors.items():
        Image.new("RGBA", (16, 16), (*rgb, 255)).save(icons / name)
    cubes = {
        "Colored Stone Bricks (White).png": (200, 200, 200),
        "World Anchor.png": (90, 90, 90),
        "Stone Bricks.png": (88, 88, 88),
        "Infested Stone Bricks.png": (88, 88, 88),
        "Infested Chiseled Quartz.png": (220, 220, 215),
        "Iszm \u2467.png": (40, 120, 200),  # non-ASCII characters are kept in icon file names
    }
    for name, rgb in cubes.items():
        cube_icon(rgb).save(icons / name)
    return root


def cube_icon(rgb: tuple[int, int, int]):
    """A 16x16 icon with NEI's isometric full-cube outline."""
    import numpy as np
    from PIL import Image

    from img2schem.palette.nei import _CUBE_OUTLINE

    px = np.zeros((16, 16, 4), dtype=np.uint8)
    px[_CUBE_OUTLINE] = (*rgb, 255)
    return Image.fromarray(px)
