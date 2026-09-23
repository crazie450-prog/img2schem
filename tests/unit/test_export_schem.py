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
    read_schem,
    write_schem,
)


def _random_grid(rng: np.random.Generator, n_pal: int, dims: tuple[int, int, int]) -> BlockGrid:
    palette = [AIR] + [f"minecraft:block_{i}" for i in range(1, n_pal)]
    return BlockGrid(rng.integers(0, n_pal, size=dims), palette)


@settings(max_examples=25, deadline=None)
@given(
    n_pal=st.integers(1, 300),
    dims=st.tuples(st.integers(1, 9), st.integers(1, 9), st.integers(1, 9)),
    version=st.sampled_from([2, 3]),
    seed=st.integers(0, 2**32 - 1),
)
def test_roundtrip_property(tmp_path_factory, n_pal, dims, version, seed):
    grid = _random_grid(np.random.default_rng(seed), n_pal, dims).compact()
    p = tmp_path_factory.mktemp("rt") / "g.schem"
    write_schem(p, grid, 4189, schem_version=version)
    back, info = read_schem(p)
    assert info.version == version and info.data_version == 4189
    assert back.shape == grid.shape
    # Compare decoded states cell by cell (palette order may differ after air normalization).
    assert (np.array(back.palette, dtype=object)[back.idx] == np.array(grid.palette, dtype=object)[grid.idx]).all()


def test_multibyte_varints_exercised(tmp_path):
    grid = _random_grid(np.random.default_rng(1), 300, (10, 4, 10)).compact()
    assert len(grid.palette) > 128
    p = write_schem(tmp_path / "big.schem", grid, 4189)
    raw = nbtlib.load(str(p))["BlockData"]
    assert len(raw) > grid.idx.size  # some cells took two bytes
    back, _ = read_schem(p)
    assert back.palette == grid.palette and (back.idx == grid.idx).all()


def test_index_order_x_fastest_then_z_then_y(tmp_path):
    grid = BlockGrid.empty(3, 2, 2)
    grid.set(1, 0, 0, "minecraft:stone")  # flat index 1
    grid.set(0, 0, 1, "minecraft:bricks")  # flat index x + z*W = 3
    grid.set(0, 1, 0, "minecraft:glass")  # flat index y*W*L = 6
    p = write_schem(tmp_path / "o.schem", grid, 4189)
    f = nbtlib.load(str(p))
    pal = {int(v): str(k) for k, v in f["Palette"].items()}
    data = [pal[int(b)] for b in f["BlockData"]]
    assert data[1] == "minecraft:stone" and data[3] == "minecraft:bricks" and data[6] == "minecraft:glass"


def test_v2_layout_and_metadata(tmp_path):
    grid = BlockGrid.empty(7, 3, 5)
    grid.fill((0, 0, 0), (6, 0, 4), "minecraft:stone")
    grid.set(3, 1, 0, "fabdeco:slate_shingle_stairs[facing=north]")
    p = write_schem(
        tmp_path / "m.schem",
        grid,
        4189,
        meta=SchemMeta(name="t", instance_name="Fab", mc_version="1.21.4", loader="fabric"),
    )
    f = nbtlib.load(str(p))
    assert f.root_name == "Schematic"
    assert int(f["Version"]) == 2 and int(f["PaletteMax"]) == 3
    assert [int(v) for v in f["Offset"]] == [-3, 0, 2] == list(front_center_offset(7))
    md = f["Metadata"]
    assert (int(md["WEOffsetX"]), int(md["WEOffsetY"]), int(md["WEOffsetZ"])) == (-3, 0, 2)
    assert [str(m) for m in md["img2schem"]["ModsRequired"]] == ["fabdeco"]
    assert str(md["img2schem"]["Loader"]) == "fabric"


def test_v3_layout(tmp_path):
    grid = BlockGrid.empty(2, 2, 2)
    grid.set(0, 0, 0, "minecraft:stone")
    p = write_schem(tmp_path / "v3.schem", grid, 4189, schem_version=3)
    f = nbtlib.load(str(p))
    body = f["Schematic"]
    assert int(body["Version"]) == 3
    assert set(body["Blocks"].keys()) >= {"Palette", "Data", "BlockEntities"}
    assert "PaletteMax" not in body


def test_byte_identical_output(tmp_path):
    grid = _random_grid(np.random.default_rng(7), 40, (6, 5, 4))
    meta = SchemMeta(date_ms=0)
    a = write_schem(tmp_path / "a.schem", grid, 4189, meta=meta).read_bytes()
    b = write_schem(tmp_path / "b.schem", grid, 4189, meta=meta).read_bytes()
    assert a == b


def test_reader_normalizes_air_and_handles_v1(tmp_path):
    # A v1-style file written by hand: air is not index 0, no DataVersion.
    root = nbtlib.Compound(
        {
            "Version": nbtlib.Int(1),
            "Width": nbtlib.Short(2),
            "Height": nbtlib.Short(1),
            "Length": nbtlib.Short(1),
            "Offset": nbtlib.IntArray([0, 0, 0]),
            "PaletteMax": nbtlib.Int(2),
            "Palette": nbtlib.Compound({"minecraft:stone": nbtlib.Int(0), "minecraft:air": nbtlib.Int(1)}),
            "BlockData": nbtlib.ByteArray([0, 1]),
        }
    )
    p = tmp_path / "v1.schem"
    with gzip.open(p, "wb") as fh:
        nbtlib.File(root, root_name="Schematic").write(fh)
    grid, info = read_schem(p)
    assert info.version == 1 and info.data_version is None
    assert grid.palette[0] == AIR
    assert grid.palette[grid.idx[0, 0, 0]] == "minecraft:stone" and grid.idx[1, 0, 0] == 0


def test_reader_rejects_bad_index(tmp_path):
    root = nbtlib.Compound(
        {
            "Version": nbtlib.Int(2),
            "DataVersion": nbtlib.Int(1),
            "Width": nbtlib.Short(1),
            "Height": nbtlib.Short(1),
            "Length": nbtlib.Short(1),
            "Palette": nbtlib.Compound({"minecraft:air": nbtlib.Int(0)}),
            "BlockData": nbtlib.ByteArray([5]),
        }
    )
    p = tmp_path / "bad.schem"
    with gzip.open(p, "wb") as fh:
        nbtlib.File(root, root_name="Schematic").write(fh)
    with pytest.raises(ValueError, match="palette size"):
        read_schem(p)


def test_copy_never_overwrites(tmp_path):
    src = tmp_path / "house.schem"
    src.write_bytes(b"x")
    dest = tmp_path / "we"
    assert copy_to_schematics_dir(src, dest).name == "house.schem"
    assert copy_to_schematics_dir(src, dest).name == "house_2.schem"
    assert copy_to_schematics_dir(src, dest).name == "house_3.schem"
