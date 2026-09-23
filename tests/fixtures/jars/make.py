"""Builds tiny fake Minecraft instances at test time (SOW §8.3). Nothing here is copied from Minecraft:
models are minimal hand-written stand-ins with the same file layout and parent names."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

CUBE_ELEMENT = [
    {
        "from": [0, 0, 0],
        "to": [16, 16, 16],
        "faces": {f: {"texture": "#all"} for f in ("down", "up", "north", "south", "west", "east")},
    }
]
PART_ELEMENT = [{"from": [0, 0, 0], "to": [16, 8, 16], "faces": {"up": {"texture": "#top"}}}]

# Parent/template models: name -> model JSON (namespace minecraft, folder block/).
TEMPLATES: dict[str, dict] = {
    "block": {},
    "cube": {"parent": "block/block", "elements": CUBE_ELEMENT},
    "cube_all": {"parent": "block/cube", "textures": {"down": "#all", "up": "#all"}},
    "cube_column": {"parent": "block/cube", "textures": {"up": "#end", "side": "#side"}},
    "stairs": {"parent": "block/block", "elements": PART_ELEMENT},
    "inner_stairs": {"parent": "block/block", "elements": PART_ELEMENT},
    "outer_stairs": {"parent": "block/block", "elements": PART_ELEMENT},
    "slab": {"parent": "block/block", "elements": PART_ELEMENT},
    "slab_top": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_wall_post": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_wall_side": {"parent": "block/block", "elements": PART_ELEMENT},
    "fence_post": {"parent": "block/block", "elements": PART_ELEMENT},
    "fence_side": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_fence_gate": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_glass_pane_post": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_glass_pane_side": {"parent": "block/block", "elements": PART_ELEMENT},
    "door_bottom_left": {"parent": "block/block", "elements": PART_ELEMENT},
    "door_top_left": {"parent": "block/block", "elements": PART_ELEMENT},
    "template_orientable_trapdoor_bottom": {"parent": "block/block", "elements": PART_ELEMENT},
}


def model_file(ns: str, name: str) -> str:
    return f"assets/{ns}/models/block/{name}.json"


def cube_block(ns: str, name: str) -> dict[str, object]:
    return {
        f"assets/{ns}/blockstates/{name}.json": {"variants": {"": {"model": f"{ns}:block/{name}"}}},
        model_file(ns, name): {"parent": "minecraft:block/cube_all", "textures": {"all": f"{ns}:block/{name}"}},
    }


def stairs_block(ns: str, name: str) -> dict[str, object]:
    variants = {}
    for facing in ("north", "south", "east", "west"):
        for half in ("bottom", "top"):
            for shape, suffix in (
                ("straight", ""),
                ("inner_left", "_inner"),
                ("inner_right", "_inner"),
                ("outer_left", "_outer"),
                ("outer_right", "_outer"),
            ):
                variants[f"facing={facing},half={half},shape={shape}"] = {"model": f"{ns}:block/{name}{suffix}"}
    files: dict[str, object] = {f"assets/{ns}/blockstates/{name}.json": {"variants": variants}}
    for suffix, parent in (("", "stairs"), ("_inner", "inner_stairs"), ("_outer", "outer_stairs")):
        files[model_file(ns, name + suffix)] = {"parent": f"minecraft:block/{parent}"}
    return files


def vanilla_files() -> dict[str, object]:
    ns = "minecraft"
    files: dict[str, object] = {model_file(ns, k): v for k, v in TEMPLATES.items()}
    for name in ("stone", "bricks", "oak_planks", "stone_bricks", "white_concrete", "glass"):
        files.update(cube_block(ns, name))
    files.update(stairs_block(ns, "oak_stairs"))
    files.update(stairs_block(ns, "stone_brick_stairs"))
    files["assets/minecraft/blockstates/air.json"] = {"variants": {"": {"model": "minecraft:block/air"}}}
    files[model_file(ns, "air")] = {"textures": {"particle": "minecraft:block/barrier"}}
    files["assets/minecraft/blockstates/oak_log.json"] = {
        "variants": {f"axis={a}": {"model": "minecraft:block/oak_log"} for a in ("x", "y", "z")}
    }
    files[model_file(ns, "oak_log")] = {"parent": "minecraft:block/cube_column"}
    files["assets/minecraft/blockstates/stone_slab.json"] = {
        "variants": {
            "type=bottom": {"model": "minecraft:block/stone_slab"},
            "type=top": {"model": "minecraft:block/stone_slab_top"},
            "type=double": {"model": "minecraft:block/stone"},
        }
    }
    files[model_file(ns, "stone_slab")] = {"parent": "minecraft:block/slab"}
    files[model_file(ns, "stone_slab_top")] = {"parent": "minecraft:block/slab_top"}
    files["assets/minecraft/blockstates/cobblestone_wall.json"] = {
        "multipart": [
            {"when": {"up": "true"}, "apply": {"model": "minecraft:block/cobblestone_wall_post"}},
            {"when": {"north": "low|tall"}, "apply": {"model": "minecraft:block/cobblestone_wall_side"}},
            {
                "when": {"OR": [{"east": "low"}, {"west": "tall"}]},
                "apply": {"model": "minecraft:block/cobblestone_wall_side"},
            },
        ]
    }
    files[model_file(ns, "cobblestone_wall_post")] = {"parent": "minecraft:block/template_wall_post"}
    files[model_file(ns, "cobblestone_wall_side")] = {"parent": "minecraft:block/template_wall_side"}
    files["assets/minecraft/blockstates/oak_fence.json"] = {
        "multipart": [
            {"apply": {"model": "minecraft:block/oak_fence_post"}},
            {"when": {"north": "true"}, "apply": {"model": "minecraft:block/oak_fence_side"}},
        ]
    }
    files[model_file(ns, "oak_fence_post")] = {"parent": "minecraft:block/fence_post"}
    files[model_file(ns, "oak_fence_side")] = {"parent": "minecraft:block/fence_side"}
    files["assets/minecraft/blockstates/oak_fence_gate.json"] = {
        "variants": {"facing=north,in_wall=false,open=false": {"model": "minecraft:block/oak_fence_gate"}}
    }
    files[model_file(ns, "oak_fence_gate")] = {"parent": "minecraft:block/template_fence_gate"}
    files["assets/minecraft/blockstates/glass_pane.json"] = {
        "multipart": [
            {"apply": {"model": "minecraft:block/glass_pane_post"}},
            {"when": {"east": "true"}, "apply": {"model": "minecraft:block/glass_pane_side"}},
        ]
    }
    files[model_file(ns, "glass_pane_post")] = {"parent": "minecraft:block/template_glass_pane_post"}
    files[model_file(ns, "glass_pane_side")] = {"parent": "minecraft:block/template_glass_pane_side"}
    files["assets/minecraft/blockstates/oak_door.json"] = {
        "variants": {
            f"facing=north,half={h},hinge=left,open=false": {"model": f"minecraft:block/oak_door_{part}_left"}
            for h, part in (("lower", "bottom"), ("upper", "top"))
        }
    }
    files[model_file(ns, "oak_door_bottom_left")] = {"parent": "minecraft:block/door_bottom_left"}
    files[model_file(ns, "oak_door_top_left")] = {"parent": "minecraft:block/door_top_left"}
    files["assets/minecraft/blockstates/oak_trapdoor.json"] = {
        "variants": {"facing=north,half=bottom,open=false": {"model": "minecraft:block/oak_trapdoor_bottom"}}
    }
    files[model_file(ns, "oak_trapdoor_bottom")] = {"parent": "minecraft:block/template_orientable_trapdoor_bottom"}
    files["assets/minecraft/blockstates/chest.json"] = {
        "variants": {f"facing={f}": {"model": "minecraft:block/chest"} for f in ("north", "south")}
    }
    files[model_file(ns, "chest")] = {"textures": {"particle": "minecraft:block/oak_planks"}}
    return files


def write_jar(path: Path, files: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            data = content if isinstance(content, bytes | str) else json.dumps(content)
            z.writestr(name, data)
    return path


def jar_bytes(files: dict[str, object]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content if isinstance(content, bytes | str) else json.dumps(content))
    return buf.getvalue()


def vanilla_jar(path: Path, mc_version: str = "1.21.4", world_version: int = 4189) -> Path:
    files = vanilla_files()
    files["version.json"] = {"id": mc_version, "world_version": world_version}
    return write_jar(path, files)


def fabric_mod(path: Path) -> Path:
    """A Fabric mod ('fabdeco') with a full block + stairs, and a nested jar-in-jar ('fabnested')."""
    nested = {"fabric.mod.json": {"id": "fabnested", "version": "1.0"}}
    nested.update(cube_block("fabnested", "inner_block"))
    files: dict[str, object] = {
        "fabric.mod.json": {"id": "fabdeco", "name": "Fab Deco", "version": "2.1.0"},
        "META-INF/jars/fabnested-1.0.jar": jar_bytes(nested),
    }
    files.update(cube_block("fabdeco", "slate_shingles"))
    files.update(stairs_block("fabdeco", "slate_shingle_stairs"))
    # Malformed blockstate and a builtin/entity block (RP.4, RP.16).
    files["assets/fabdeco/blockstates/broken.json"] = "{ not json"
    files["assets/fabdeco/blockstates/statue.json"] = {"variants": {"": {"model": "fabdeco:block/statue"}}}
    files[model_file("fabdeco", "statue")] = {"parent": "builtin/entity"}
    return write_jar(path, files)


def neoforge_mod(path: Path) -> Path:
    toml = '[[mods]]\nmodId="neomasonry"\nversion="${file.jarVersion}"\ndisplayName="Neo Masonry"\n'
    nested = {"META-INF/neoforge.mods.toml": '[[mods]]\nmodId="neolib"\nversion="0.3"\n'}
    nested.update(cube_block("neolib", "lib_block"))
    files: dict[str, object] = {
        "META-INF/neoforge.mods.toml": toml,
        "META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 3.4.5\n",
        "META-INF/jarjar/neolib-0.3.jar": jar_bytes(nested),
    }
    files.update(cube_block("neomasonry", "plaster"))
    return write_jar(path, files)


def resource_pack(path: Path) -> Path:
    """Overrides minecraft:stone's model to a column and ships a blockstate for a block that doesn't exist."""
    files: dict[str, object] = {
        "pack.mcmeta": {"pack": {"pack_format": 34, "description": "test"}},
        model_file("minecraft", "stone"): {"parent": "minecraft:block/cube_column"},
        "assets/minecraft/blockstates/not_a_block.json": {"variants": {"": {"model": "minecraft:block/stone"}}},
    }
    return write_jar(path, files)


def fabric_game_dir(game_dir: Path) -> Path:
    """Mods + resource pack + options.txt in ``game_dir``."""
    fabric_mod(game_dir / "mods" / "fabdeco-2.1.0.jar")
    (game_dir / "mods" / "worldedit-mod-7.3.jar").parent.mkdir(parents=True, exist_ok=True)
    write_jar(
        game_dir / "mods" / "worldedit-mod-7.3.jar",
        {"fabric.mod.json": {"id": "worldedit", "name": "WorldEdit", "version": "7.3.8"}},
    )
    resource_pack(game_dir / "resourcepacks" / "TestPack.zip")
    (game_dir / "options.txt").write_text('version:3955\nresourcePacks:["vanilla","fabric","file/TestPack.zip"]\n')
    return game_dir
