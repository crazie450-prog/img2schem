import numpy as np

from img2schem.models import BlockGrid
from img2schem.stages.preview import BG, render_front, render_iso, render_side, render_top, write_previews


def _grid():
    # A single marker block at the west end (x=0) of the front row, bottom layer.
    g = BlockGrid.empty(4, 3, 5)
    g.set(0, 0, 0, "minecraft:stone")
    return g


def _solid(img):
    return np.array(img)[..., :3].astype(int).sum(-1) != sum(BG)


def test_front_is_seen_from_north_so_west_is_on_the_right():
    solid = _solid(render_front(_grid(), px=8))
    assert solid.shape == (3 * 8, 4 * 8)
    assert solid[-8:, -8:].all() and not solid[:, :-8].any()


def test_side_is_seen_from_west_so_front_is_on_the_left():
    solid = _solid(render_side(_grid(), px=8))
    assert solid.shape == (3 * 8, 5 * 8)
    assert solid[-8:, :8].all() and not solid[:, 8:].any()


def test_top_has_north_up_east_right():
    solid = _solid(render_top(_grid(), px=8))
    assert solid.shape == (5 * 8, 4 * 8)
    assert solid[:8, :8].all() and not solid[8:, :].any()


def test_iso_and_write(tmp_path):
    g = _grid()
    g.fill((0, 0, 0), (3, 2, 4), "minecraft:bricks")
    assert _solid(render_iso(g)).any()
    paths = write_previews(g, tmp_path)
    assert [p.name for p in paths] == ["preview_front.png", "preview_side.png", "preview_top.png", "preview_iso.png"]
