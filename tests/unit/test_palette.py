import numpy as np
import pytest
from fixtures.jars.make import nei_dumps

from img2schem.palette.nei import classify, icon_filename_base, import_nei
from img2schem.util.color import srgb_to_lab


@pytest.fixture
def pal(tmp_path):
    return import_nei(nei_dumps(tmp_path / "dumps"))


def test_icons_linked_in_panel_order(pal):
    wool = {v.meta: v for v in pal.blocks["minecraft:wool"].variants}
    assert set(wool) == {0, 14}  # the NBT row is skipped
    assert wool[0].rgb == (240, 240, 240) and wool[14].rgb == (160, 40, 35)
    stairs = {v.meta: v.rgb for v in pal.blocks["chisel:aluminum_stairs.1"].variants}
    assert stairs == {0: (130, 130, 130), 8: (110, 110, 110)}  # icons _2/_3: Galacticraft's row came first


def test_colon_names_ambiguous_names_and_big_meta(pal):
    (brain,) = pal.blocks["Automagy:crystalBrain"].variants
    assert brain.rgb == (5, 5, 5) and brain.flags == ["dark_icon"]
    machine = pal.blocks["gregtech:gt.blockmachines"]
    assert [v.meta for v in machine.variants] == [1, 2]  # meta 1086 is not block metadata
    assert all(v.rgb is None for v in machine.variants)  # 2 rows, 1 icon -> no reliable color


def test_color_lookup_strips_orientation_bits(pal):
    assert pal.color("chisel:aluminum_stairs.1@3") == (130, 130, 130)  # variant 0, facing north
    assert pal.color("chisel:aluminum_stairs.1@14") == (110, 110, 110)  # variant 8, upside-down
    assert pal.color("minecraft:stone_slab@9") == (215, 205, 150)  # top-half sandstone slab
    assert pal.color("minecraft:wool@3") == (240, 240, 240)  # unknown variant falls back to meta 0
    assert pal.color("create:nothing") is None


def test_shapes(pal):
    shapes = {n: b.shape for n, b in pal.blocks.items()}
    assert shapes["chisel:aluminum_stairs.1"] == "stairs"
    assert shapes["minecraft:stone_slab"] == "slab"
    assert shapes["malisisdoors:jungleFenceGate"] == "fence_gate"  # mod id "malisisdoors" is not a door
    assert shapes["modernmarkings:wall_arrow"] == "unknown"  # a floor marking, not a wall
    assert "minecraft:air" not in pal.blocks


@pytest.mark.parametrize(
    ("cls", "name", "shape"),
    [
        ("net.minecraft.block.BlockStairs", "minecraft:oak_stairs", "stairs"),
        ("net.minecraft.block.BlockStoneSlab", "minecraft:double_stone_slab", "full_cube"),
        ("net.minecraft.block.BlockWall", "minecraft:cobblestone_wall", "wall"),
        ("net.minecraft.block.BlockPane", "minecraft:glass_pane", "pane"),
        ("net.minecraft.block.BlockPane", "minecraft:iron_bars", "pane"),
        ("x.BlockAdvSolarPanel", "AdvancedSolarPanel:BlockAdvSolarPanel", "unknown"),
        ("net.minecraft.block.BlockDoor", "minecraft:wooden_door", "door"),
        ("net.minecraft.block.BlockTrapDoor", "minecraft:trapdoor", "trapdoor"),
        ("net.minecraft.block.BlockOldLog", "minecraft:log", "log"),
        ("team.chisel.block.BlockCarvable", "chisel:marble_pillar", "full_cube"),
        ("x.BlockCasings1", "gregtech:gt.blockcasings", "unknown"),
    ],
)
def test_classify(cls, name, shape):
    assert classify(cls, name) == shape


def test_icon_filename_base():
    assert icon_filename_base("Crystalline Brain: Air") == "Crystalline Brain_ Air"
    assert icon_filename_base("α Centauri Bb Stone Dust") == "#U03b1 Centauri Bb Stone Dust"


def test_lab_reference_values():
    lab = srgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0]]))
    assert np.allclose(lab[0], [100, 0, 0], atol=0.05) and np.allclose(lab[1], [0, 0, 0], atol=0.05)
    assert np.allclose(lab[2], [53.24, 80.09, 67.20], atol=0.05)
