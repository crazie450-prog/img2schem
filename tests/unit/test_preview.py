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


def test_stairs_and_slabs_are_drawn_as_their_boxes():
    from img2schem.stages.preview import block_parts

    assert block_parts("minecraft:stone") is None
    assert block_parts("minecraft:stone_slab") == [(0, 0, 0, 1, 0.5, 1)]
    assert block_parts("minecraft:stone_slab@8") == [(0, 0.5, 0, 1, 1, 1)]  # vanilla top half
    # ascending east: the raised back half is on the east (+X) side
    assert block_parts("minecraft:oak_stairs") == [(0, 0, 0, 1, 0.5, 1), (0.5, 0.5, 0, 1, 1, 1)]
    # upside-down, ascending north: full top half, the lower back quarter on the north (-Z) side
    assert block_parts("minecraft:oak_stairs@7") == [(0, 0.5, 0, 1, 1, 1), (0, 0, 0, 1, 0.5, 0.5)]
    g = BlockGrid.empty(3, 2, 3)
    g.set(1, 0, 1, "minecraft:oak_stairs")
    full = BlockGrid.empty(3, 2, 3)
    full.set(1, 0, 1, "minecraft:planks")
    assert 0 < _solid(render_iso(g)).sum() < _solid(render_iso(full)).sum()  # a stair covers less than a cube
