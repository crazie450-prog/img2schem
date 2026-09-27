from pathlib import Path

import pytest
from fixtures.jars.make import GTNH_BLOCKS, level_dat

from img2schem.instance.world import list_worlds, read_world_palette, resolve_world


def test_read_world_palette(gtnh):
    game = Path(gtnh.game_dir)
    (world,) = list_worlds(game)
    assert resolve_world(game, "img2schem-test") == world
    pal = read_world_palette(world)
    assert pal.blocks == dict(sorted(GTNH_BLOCKS.items()))  # items (\u0002) excluded
    assert pal.validate_block("gregtech:gt.blockcasings@5") is None
    assert pal.validate_block("minecraft:air") is None
    assert "unknown block" in (pal.validate_block("gregtech:nothing") or "")
    assert "malformed" in (pal.validate_block("stone") or "")


def test_not_a_forge_world(tmp_path):
    import gzip

    import nbtlib

    d = tmp_path / "plain"
    d.mkdir()
    with gzip.open(d / "level.dat", "wb") as fh:
        nbtlib.File({"Data": nbtlib.Compound()}, root_name="").write(fh)
    with pytest.raises(ValueError, match="FML"):
        read_world_palette(d)


def test_missing_world(tmp_path):
    level_dat(tmp_path / "saves" / "w" / "level.dat", {})
    with pytest.raises(LookupError):
        resolve_world(tmp_path, "nope")
