import json
import time

from img2schem.instance.discover import discover_curseforge, discover_vanilla
from img2schem.palette.build import build_palette, extract


def _fabric(launchers):
    return next(i for i in discover_vanilla(launchers["vanilla"][0]) if i.loader == "fabric")


def test_shapes_and_properties(launchers):
    pal, report = extract(_fabric(launchers))
    b = pal.blocks
    expected = {
        "minecraft:bricks": "full_cube",
        "minecraft:oak_log": "column",
        "minecraft:oak_stairs": "stairs",
        "minecraft:stone_slab": "slab",
        "minecraft:cobblestone_wall": "wall",
        "minecraft:oak_fence": "fence",
        "minecraft:oak_fence_gate": "fence_gate",
        "minecraft:glass_pane": "pane",
        "minecraft:oak_door": "door",
        "minecraft:oak_trapdoor": "trapdoor",
        "fabdeco:slate_shingles": "full_cube",
        "fabdeco:slate_shingle_stairs": "stairs",
        "fabnested:inner_block": "full_cube",  # jar-in-jar
    }
    assert {k: b[k].shape for k in expected} == expected
    assert b["minecraft:oak_stairs"].properties == {
        "facing": ["east", "north", "south", "west"],
        "half": ["bottom", "top"],
        "shape": ["inner_left", "inner_right", "outer_left", "outer_right", "straight"],
    }
    assert b["minecraft:cobblestone_wall"].properties == {
        "east": ["low"],
        "north": ["low", "tall"],
        "up": ["true"],
        "west": ["tall"],
    }
    assert b["fabdeco:slate_shingle_stairs"].source == "fabdeco-2.1.0.jar"
    assert b["fabnested:inner_block"].source.endswith("META-INF/jars/fabnested-1.0.jar")


def test_resource_pack_overrides_but_cannot_add(launchers):
    pal, _ = extract(_fabric(launchers))
    assert pal.blocks["minecraft:stone"].shape == "column"  # the pack's model wins
    assert "minecraft:not_a_block" not in pal.blocks


def test_code_rendered_and_malformed(launchers):
    pal, report = extract(_fabric(launchers))
    assert "fabdeco:statue" in report.code_rendered  # builtin/entity parent
    assert "minecraft:chest" in report.code_rendered  # model without elements
    assert "fabdeco:broken" not in pal.blocks
    assert any("broken.json" in e["file"] for e in report.parse_errors)
    assert report.blocks_per_mod["fabdeco"] == 3


def test_neoforge_jarjar(launchers):
    (inst,) = discover_curseforge(launchers["curseforge"][0])
    pal, _ = extract(inst)
    assert pal.blocks["neomasonry:plaster"].shape == "full_cube"
    assert pal.blocks["neolib:lib_block"].source.endswith("META-INF/jarjar/neolib-0.3.jar")


def test_validate_state(launchers):
    pal, _ = extract(_fabric(launchers))
    assert pal.validate_state("minecraft:oak_stairs[facing=north,half=top,shape=outer_left]") is None
    assert pal.validate_state("minecraft:oak_stairs[facing=north,waterlogged=false]") is None
    assert pal.validate_state("minecraft:air") is None
    assert "not in" in (pal.validate_state("minecraft:oak_stairs[facing=up]") or "")
    assert "unknown property" in (pal.validate_state("minecraft:bricks[color=red]") or "")
    assert "unknown block" in (pal.validate_state("create:nothing") or "")


def test_cache_hit(launchers, tmp_path):
    inst = _fabric(launchers)
    pal, d, hit = build_palette(inst, tmp_path / "cache")
    assert not hit and (d / "palette_report.json").is_file()
    t = time.perf_counter()
    pal2, d2, hit2 = build_palette(inst, tmp_path / "cache")
    assert hit2 and d2 == d and time.perf_counter() - t < 2
    assert pal2.blocks.keys() == pal.blocks.keys()
    assert json.loads((d / "palette_report.json").read_text())["blocks_per_shape"]["stairs"] == 3
