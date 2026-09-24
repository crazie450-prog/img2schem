import gzip

import nbtlib
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from img2schem.models import AIR, BlockGrid
from img2schem.stages.export_schem import (
    SchemMeta,
    copy_to_schematics_dir,
    front_center_offset,
    read_schematic,
    write_schematic,
)
from img2schem.util.block import format_block


def _decoded(grid: BlockGrid) -> np.ndarray:
    return np.array(grid.palette, dtype=object)[grid.idx]


def _save(root: dict, path):
    with gzip.open(path, "wb") as fh:
        nbtlib.File(nbtlib.Compound(root), root_name="Schematic").write(fh)
    return path


@settings(max_examples=25, deadline=None)
@given(
    n_names=st.integers(1, 400),
    dims=st.tuples(st.integers(1, 9), st.integers(1, 9), st.integers(1, 9)),
    seed=st.integers(0, 2**32 - 1),
)
def test_roundtrip_property(tmp_path_factory, n_names, dims, seed):
    rng = np.random.default_rng(seed)
    palette = [AIR] + [format_block(f"mod{i % 7}:block_{i}", int(rng.integers(0, 16))) for i in range(1, n_names)]
    grid = BlockGrid(rng.integers(0, len(palette), size=dims), palette)
    p = tmp_path_factory.mktemp("rt") / "g.schematic"
    write_schematic(p, grid)
    back, info = read_schematic(p)
    assert info.mapped and back.shape == grid.shape
    assert (_decoded(back) == _decoded(grid)).all()


def test_layout_tags_and_offset(tmp_path):
    grid = BlockGrid.empty(7, 3, 5)
    grid.fill((0, 0, 0), (6, 0, 4), "minecraft:stonebrick")
    grid.set(3, 1, 0, "chisel:marble_stairs.0@2")
    p = write_schematic(tmp_path / "m.schematic", grid, meta=SchemMeta(name="t", instance_name="GTNH", loader="forge"))
    f = nbtlib.load(str(p))
    assert f.root_name == "Schematic" and str(f["Materials"]) == "Alpha"
    assert (int(f["Width"]), int(f["Height"]), int(f["Length"])) == (7, 3, 5)
    assert [int(f[f"WEOffset{a}"]) for a in "XYZ"] == [-3, -1, 2] == list(front_center_offset(7))
    assert [int(f[f"WEOrigin{a}"]) for a in "XYZ"] == [0, 0, 0]
    assert {k: int(v) for k, v in f["SchematicaMapping"].items()} == {
        "minecraft:stonebrick": 1,
        "chisel:marble_stairs.0": 2,
    }
    assert "AddBlocks" not in f  # all local ids < 256
    assert [str(m) for m in f["img2schem"]["ModsRequired"]] == ["chisel"]


def test_index_order_x_fastest_then_z_then_y(tmp_path):
    grid = BlockGrid.empty(3, 2, 2)
    grid.set(1, 0, 0, "minecraft:stone")  # flat index 1
    grid.set(0, 0, 1, "minecraft:wool@14")  # flat index x + z*W = 3
    grid.set(0, 1, 0, "minecraft:glass")  # flat index y*W*L = 6
    f = nbtlib.load(str(write_schematic(tmp_path / "o.schematic", grid)))
    names = {int(v): str(k) for k, v in f["SchematicaMapping"].items()}
    blocks = [int(b) for b in f["Blocks"]]
    data = [int(b) for b in f["Data"]]
    assert (names[blocks[1]], names[blocks[3]], data[3], names[blocks[6]]) == (
        "minecraft:stone",
        "minecraft:wool",
        14,
        "minecraft:glass",
    )


def test_addblocks_schematica_nibble_order(tmp_path):
    # 300 distinct names -> local ids up to 300 need AddBlocks. Cell 0 (even) gets id 257, cell 1 (odd) id 258.
    palette = [AIR] + [f"m:b{i}" for i in range(1, 301)]
    idx = np.zeros((2, 1, 1), dtype=np.int32)
    idx[0, 0, 0], idx[1, 0, 0] = 257, 258
    grid = BlockGrid(idx, palette)
    f = nbtlib.load(str(write_schematic(tmp_path / "a.schematic", grid)))
    local = {str(k): int(v) for k, v in f["SchematicaMapping"].items()}
    assert (local["m:b257"], local["m:b258"]) == (1, 2)  # compact() drops unused names; ids stay < 256
    # Force high ids by using every name.
    idx = np.arange(1, 301, dtype=np.int32).reshape(300, 1, 1)
    f = nbtlib.load(str(write_schematic(tmp_path / "b.schematic", BlockGrid(idx, palette))))
    local = {str(k): int(v) for k, v in f["SchematicaMapping"].items()}
    add = np.asarray(f["AddBlocks"], dtype=np.int8).view(np.uint8)
    assert len(add) == (300 >> 1) + 1  # WorldEdit's FlatNibbleArray size
    ids = [local[f"m:b{i}"] for i in range(1, 301)]
    blocks = np.asarray(f["Blocks"], dtype=np.int8).view(np.uint8)
    for cell in (255, 256):  # odd cell 255 -> id 256, even cell 256 -> id 257
        high = add[cell >> 1] >> 4 if cell % 2 == 0 else add[cell >> 1] & 0xF
        assert (int(high) << 8) | int(blocks[cell]) == ids[cell]


def test_reads_plain_worldedit_file_without_mapping(tmp_path):
    # A classic MCEdit file: numeric ids, AddBlocks in WorldEdit's order (even cell -> low nibble).
    root = {
        "Width": nbtlib.Short(2), "Height": nbtlib.Short(1), "Length": nbtlib.Short(1),
        "Materials": nbtlib.String("Alpha"),
        "Blocks": nbtlib.ByteArray(np.array([0x02, 35], dtype=np.uint8).view(np.int8)),
        "Data": nbtlib.ByteArray([0, 14]),
        "AddBlocks": nbtlib.ByteArray(np.array([0x01], dtype=np.uint8).view(np.int8)),
        "WEOffsetX": nbtlib.Int(-1), "WEOffsetY": nbtlib.Int(0), "WEOffsetZ": nbtlib.Int(2),
        "TileEntities": nbtlib.List[nbtlib.Compound]([]),
    }  # fmt: skip
    grid, info = read_schematic(_save(root, tmp_path / "we.schematic"))
    assert not info.mapped and info.offset == (-1, 0, 2) and info.origin is None
    assert list(_decoded(grid)[:, 0, 0]) == ["id:258", "id:35@14"]


def test_air_with_metadata_is_air(tmp_path):
    root = {
        "Width": nbtlib.Short(2), "Height": nbtlib.Short(1), "Length": nbtlib.Short(1),
        "Materials": nbtlib.String("Alpha"), "Blocks": nbtlib.ByteArray([0, 1]), "Data": nbtlib.ByteArray([5, 0]),
        "SchematicaMapping": nbtlib.Compound({"minecraft:stone": nbtlib.Short(1)}),
    }  # fmt: skip
    grid, _ = read_schematic(_save(root, tmp_path / "air.schematic"))
    assert grid.palette == [AIR, "minecraft:stone"] and grid.idx[0, 0, 0] == 0


def test_rejects_bad_lengths(tmp_path):
    root = {
        "Width": nbtlib.Short(2), "Height": nbtlib.Short(1), "Length": nbtlib.Short(1),
        "Materials": nbtlib.String("Alpha"), "Blocks": nbtlib.ByteArray([1]), "Data": nbtlib.ByteArray([0]),
    }  # fmt: skip
    with pytest.raises(ValueError, match="length"):
        read_schematic(_save(root, tmp_path / "bad.schematic"))


def test_too_many_distinct_blocks(tmp_path):
    palette = [AIR] + [f"m:b{i}" for i in range(1, 4097)]
    idx = np.arange(1, 4097, dtype=np.int32).reshape(16, 16, 16)
    with pytest.raises(ValueError, match="4095"):
        write_schematic(tmp_path / "x.schematic", BlockGrid(idx, palette))


def test_byte_identical_output(tmp_path):
    rng = np.random.default_rng(7)
    grid = BlockGrid(
        rng.integers(0, 40, size=(6, 5, 4)), [AIR] + [format_block(f"m:b{i}", i % 16) for i in range(1, 40)]
    )
    a = write_schematic(tmp_path / "a.schematic", grid).read_bytes()
    b = write_schematic(tmp_path / "b.schematic", grid).read_bytes()
    assert a == b


def test_copy_never_overwrites(tmp_path):
    src = tmp_path / "house.schematic"
    src.write_bytes(b"x")
    dest = tmp_path / "we"
    assert copy_to_schematics_dir(src, dest).name == "house.schematic"
    assert copy_to_schematics_dir(src, dest).name == "house_2.schematic"
